#!/usr/bin/env python3
"""v7.8.0 tests: CLOUD FIRST - providers, real usage, retry, talk cache.

The user's ask (message 20): "حالا وقتشه یکم بریم روی مدل های ابری با
api key و اینکه توی لیست پرووایدر ها b.ai و hugging face رو هم اضافه کن
و اینکه هر کاری کن که خروجیش بدون خطا و باگ باشه و بهترین خروجی رو با
کمترین مصرف کردیت و درخواست و توکن داشته باشیم"

v7.9 correction (the user: "منظورم واقعا سایت b.ai بود"): b.ai is the
B.AI platform - its own provider now (tests moved to test_v790); here
blackbox keeps its own identity + the shared behaviours stay pinned.

Pinned here:

  1. Blackbox AI is a first-class provider under its OWN name; the
     alias 'blackboxai' resolves and the vault stores one row under the
     CANONICAL name. ('b.ai' belongs to the real B.AI platform since
     v7.9 - see test_v790_providers_usage.py.)
  2. Hugging Face stays (router.huggingface.co, HF_TOKEN).
  3. REAL usage capture: the final SSE chunks of OpenAI-compatible /
     Anthropic / Gemini streams carry actual token counts - folded into
     the caller's usage dict, so the ledger stops guessing. OpenAI gets
     stream_options.include_usage (the one provider that must be asked).
  4. ONE calm retry for transient cloud failures (HTTP 429/5xx, dropped
     connection) BEFORE the first token; auth/model errors and
     mid-stream deaths are never retried (that would duplicate text or
     waste a request that cannot succeed).
  5. cache_talk: identical RESENT talk turns are served from the local
     response cache (zero tokens / credits / requests); the gate is a
     pure function and the economy flag validates + persists.

All tests are NETWORK-FREE (urlopen is faked / stream chunks scripted).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova  # noqa: E402
import nova_economy as econ  # noqa: E402
import nova_providers as providers  # noqa: E402


class _WSTestCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(prefix="nova_v78_")
        self.addCleanup(providers.load_config, None)
        self.ws = Path(d)
        providers.load_config(self.ws)


# --------------------------------------------------------------- registry
class TestBlackboxAndAliases(_WSTestCase):
    def test_blackbox_is_a_real_provider(self):
        self.assertIn("blackbox", providers.PROVIDERS)
        self.assertIn("blackbox", providers.names())
        e = providers.entry("blackbox") or {}
        self.assertEqual(e.get("kind"), "openai")
        # v7.9: blackbox no longer CLAIMS b.ai - that is the real B.AI
        self.assertNotIn("b.ai", e.get("label", ""))
        self.assertEqual(e.get("key_env"), "BLACKBOX_API_KEY")
        self.assertTrue(e.get("base", "").startswith("https://"))
        self.assertTrue(e.get("needs_key"), "blackbox is a paid cloud - key required")

    def test_huggingface_still_registered(self):
        e = providers.entry("huggingface") or {}
        self.assertEqual(e.get("kind"), "openai")
        self.assertIn("huggingface", providers.names())
        self.assertIn("router.huggingface.co", e.get("base", ""))
        self.assertEqual(e.get("key_env"), "HF_TOKEN")

    def test_alias_blackboxai_everywhere(self):
        self.assertIsNone(providers.entry("no-such-thing"))
        self.assertEqual((providers.entry("blackboxai") or {}).get("name"), "blackbox")
        self.assertEqual(providers._canon(" BlackboxAI "), "blackbox")
        with mock.patch.dict("os.environ", {"BLACKBOX_API_KEY": "bbk-1"}):
            cfg = providers.resolve("blackboxai")
        self.assertEqual(cfg["name"], "blackbox")
        self.assertEqual(cfg["key"], "bbk-1")

    def test_alias_hf_everywhere(self):
        self.assertEqual((providers.entry("hf") or {}).get("name"), "huggingface")
        self.assertEqual(providers._canon("hugging face"), "huggingface")

    def test_aliases_never_appear_in_names(self):
        ns = providers.names()
        self.assertNotIn("b.ai", ns)
        self.assertNotIn("hf", ns)
        self.assertNotIn("blackboxai", ns)

    def test_set_key_via_alias_lands_on_canonical_row(self):
        err = providers.set_key(self.ws, "blackboxai", "sk-test-bbai")
        self.assertEqual(err, "")
        self.assertEqual(providers.key_source("blackbox"), "file")
        is_set, masked = providers.key_status("blackboxai")
        self.assertTrue(is_set)
        self.assertEqual(masked, "...bbai", "only the last 4 chars may show")
        # the vault file itself carries the canonical name only
        raw = json.loads(providers.config_path(self.ws).read_text())
        self.assertIn("blackbox", raw.get("keys", {}))
        self.assertNotIn("blackboxai", raw.get("keys", {}))
        self.assertEqual(raw["keys"]["blackbox"], "sk-test-bbai")

    def test_del_key_via_alias(self):
        providers.set_key(self.ws, "blackboxai", "sk-x")
        self.assertEqual(providers.del_key(self.ws, "blackboxai"), "")
        self.assertEqual(providers.key_source("blackbox"), "")

    def test_parse_target_and_route_with_alias(self):
        prov, model = providers.parse_target("blackboxai/blackboxai")
        self.assertEqual((prov, model), ("blackbox", "blackboxai"))
        self.assertEqual(providers.set_route(self.ws, "talk", "blackboxai/blackboxai"), "")
        with mock.patch.dict("os.environ", {"BLACKBOX_API_KEY": "bbk-1"}):
            cfg, model = providers.resolve_route("talk")
        self.assertEqual(cfg["name"], "blackbox")
        self.assertEqual(model, "blackboxai")

    def test_blackbox_models_endpoint_shape(self):
        cfg = dict(providers.PROVIDERS["blackbox"], name="blackbox", key="k")
        url, headers = providers._models_endpoint(cfg)
        self.assertEqual(url, "https://api.blackbox.ai/api/models")
        self.assertEqual(headers.get("Authorization"), "Bearer k")


# --------------------------------------------------------------- usage capture
class TestUsageCapture(unittest.TestCase):
    def test_openai_final_chunk_usage_only(self):
        u = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        out = providers._openai_parse(
            json.dumps({"choices": [], "usage":
                        {"prompt_tokens": 120, "completion_tokens": 45}}), u)
        self.assertEqual(out, [])
        self.assertEqual(u, {"prompt_tokens": 120, "completion_tokens": 45,
                             "actual": True})

    def test_openai_chunk_with_choices_and_usage(self):
        u = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        out = providers._openai_parse(
            json.dumps({"choices": [{"delta": {"content": "hi"}}],
                        "usage": {"prompt_tokens": 9, "completion_tokens": 2}}), u)
        self.assertEqual(out, ["hi"])
        self.assertTrue(u["actual"])
        self.assertEqual(u["prompt_tokens"], 9)

    def test_openai_without_usage_stays_estimate(self):
        u = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        providers._openai_parse(
            json.dumps({"choices": [{"delta": {"content": "x"}}]}), u)
        self.assertFalse(u["actual"])

    def test_junk_never_crashes_usage(self):
        u = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        self.assertEqual(providers._openai_parse("not json", u), [])
        self.assertEqual(providers._openai_parse("[DONE]", u), [])
        providers._openai_parse(json.dumps({"usage": "junk"}), u)
        self.assertFalse(u["actual"])

    def test_anthropic_message_start_and_delta(self):
        u = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        providers._anthropic_parse(json.dumps(
            {"type": "message_start",
             "message": {"usage": {"input_tokens": 300}}}), u)
        self.assertEqual(u["prompt_tokens"], 300)
        providers._anthropic_parse(json.dumps(
            {"type": "content_block_delta",
             "delta": {"type": "text_delta", "text": "hi"}}), u)
        providers._anthropic_parse(json.dumps(
            {"type": "message_delta", "usage": {"output_tokens": 77}}), u)
        self.assertEqual(u["completion_tokens"], 77)
        self.assertTrue(u["actual"])

    def test_gemini_usage_metadata(self):
        u = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        out = providers._gemini_parse(json.dumps(
            {"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
             "usageMetadata": {"promptTokenCount": 51,
                               "candidatesTokenCount": 8}}), u)
        self.assertEqual(out, ["ok"])
        self.assertEqual(u["prompt_tokens"], 51)
        self.assertEqual(u["completion_tokens"], 8)
        self.assertTrue(u["actual"])

    def _capture(self, cfg, **kw):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _FakeResp([b"data: [DONE]\n"])

        with mock.patch.object(providers.urllib.request, "urlopen",
                               side_effect=fake_urlopen):
            list(providers._openai_stream(
                cfg, "m", [{"role": "user", "content": "hi"}], 0.2, 30, **kw))
        return json.loads(captured["req"].data)

    def test_openai_asks_for_stream_usage(self):
        cfg = dict(providers.PROVIDERS["openai"], name="openai", key="k")
        body = self._capture(cfg)
        self.assertEqual(body["stream_options"], {"include_usage": True})

    def test_other_providers_not_burdened(self):
        cfg = dict(providers.PROVIDERS["groq"], name="groq", key="k")
        body = self._capture(cfg)
        self.assertNotIn("stream_options", body)
        cfg = dict(providers.PROVIDERS["blackbox"], name="blackbox", key="k")
        body = self._capture(cfg)
        self.assertNotIn("stream_options", body)

    def test_stream_chunks_reports_real_usage(self):
        cfg = dict(providers.PROVIDERS["openai"], name="openai", key="k")
        u = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        lines = [
            b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":15,'
            b'"completion_tokens":4}}\n\n',
            b"data: [DONE]\n\n",
        ]

        def fake_urlopen(req, timeout=None):
            return _FakeResp(lines)

        with mock.patch.object(providers.urllib.request, "urlopen",
                               side_effect=fake_urlopen):
            gen = providers.stream_chunks(cfg, "m", [{"role": "user",
                                                      "content": "hi"}],
                                          0.2, 30, usage=u)
            self.assertEqual("".join(gen), "Hello")
        self.assertEqual(u, {"prompt_tokens": 15, "completion_tokens": 4,
                             "actual": True})


class _FakeResp:
    def __init__(self, lines=()):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --------------------------------------------------------------- retry
class TestTransientRetry(unittest.TestCase):
    def test_classifier(self):
        self.assertTrue(nova._transient_provider_error("HTTP 429: rate limited"))
        self.assertTrue(nova._transient_provider_error("HTTP 503: overloaded"))
        self.assertTrue(nova._transient_provider_error("HTTP 529: capacity"))
        self.assertTrue(nova._transient_provider_error(
            "cannot reach the provider endpoint (conn refused)"))
        self.assertFalse(nova._transient_provider_error(
            "HTTP 401 - the API key is missing or wrong"))
        self.assertFalse(nova._transient_provider_error(
            "HTTP 404 - model name or base URL is probably wrong"))
        self.assertFalse(nova._transient_provider_error("API error: bad request"))
        self.assertFalse(nova._transient_provider_error(""))
        self.assertFalse(nova._transient_provider_error(None))

    def _run_stream_chat(self, fake_stream):
        """stream_chat against a scripted cloud brain. Returns
        (text, complete, call_count)."""
        calls = {"n": 0}

        def wrapper(*a, **kw):
            calls["n"] += 1
            return fake_stream(calls["n"])

        cfg = {"name": "groq", "kind": "openai", "base": "https://x/v1",
               "model": "m", "key": "k"}
        with mock.patch.object(nova.providers, "stream_chunks",
                               side_effect=wrapper), \
                mock.patch.object(nova, "_provider_cfg", return_value=cfg), \
                mock.patch.object(nova.time, "sleep"):
            text, complete = nova.stream_chat(
                "m", [{"role": "user", "content": "hi"}], 0.2,
                sess=None, quiet=True)
        return text, complete, calls["n"]

    def test_rate_limit_gets_one_retry_then_success(self):
        def fake(n):
            if n == 1:
                raise providers.ProviderError("HTTP 429: rate limited")
            return iter(["hello"])
        text, complete, n = self._run_stream_chat(fake)
        self.assertEqual(text, "hello")
        self.assertTrue(complete)
        self.assertEqual(n, 2, "exactly ONE retry after a 429")

    def test_mid_stream_death_is_never_retried(self):
        def fake(n):
            def gen():
                yield "partial "
                raise providers.ProviderError("HTTP 500: boom")
            return gen()
        text, complete, n = self._run_stream_chat(fake)
        self.assertEqual(text, "partial ")
        self.assertFalse(complete)
        self.assertEqual(n, 1, "a retry here would duplicate the text")

    def test_auth_error_is_never_retried(self):
        def fake(n):
            raise providers.ProviderError(
                "HTTP 401 - the API key is missing or wrong")
        text, complete, n = self._run_stream_chat(fake)
        self.assertEqual(text, "")
        self.assertFalse(complete)
        self.assertEqual(n, 1, "a retry cannot fix a bad key")

    def test_clean_success_no_retry(self):
        def fake(n):
            return iter(["ok"])
        text, complete, n = self._run_stream_chat(fake)
        self.assertEqual((text, complete, n), ("ok", True, 1))


# --------------------------------------------------------------- talk cache
class TestTalkCache(_WSTestCase):
    def test_default_is_on(self):
        self.assertTrue(providers.economy()["cache_talk"])

    def test_clean_economy_validates_flag(self):
        self.assertEqual(providers._clean_economy({"cache_talk": False}),
                         {"cache_talk": False})
        self.assertEqual(providers._clean_economy({"cache_talk": "yes"}), {})
        self.assertEqual(providers._clean_economy({"cache_talk": 1}), {})

    def test_flag_persists_per_workspace(self):
        self.assertEqual(providers.set_economy(self.ws, {"cache_talk": False}), "")
        self.assertFalse(providers.economy()["cache_talk"])
        # a fresh load from disk keeps the setting
        providers.load_config(self.ws)
        self.assertFalse(providers.economy()["cache_talk"])

    def test_gate_function(self):
        self.assertTrue(nova._cacheable_section("utility", {}))
        self.assertTrue(nova._cacheable_section("utility", None))
        self.assertTrue(nova._cacheable_section("talk", {"cache_talk": True}))
        self.assertTrue(nova._cacheable_section("talk", {}))
        self.assertTrue(nova._cacheable_section("talk", None))
        self.assertFalse(nova._cacheable_section("talk", {"cache_talk": False}))
        self.assertFalse(nova._cacheable_section("coding", {}))
        self.assertFalse(nova._cacheable_section(None, {}))
        self.assertFalse(nova._cacheable_section("council", {}))

    def test_talk_cache_roundtrip_saves_a_request(self):
        msgs = [{"role": "system", "content": "s"},
                {"role": "user", "content": "سلام"}]
        k = econ.cache_key("blackbox", "blackboxai", msgs, 0.7)
        self.assertIsNone(econ.cache_get(self.ws, k))
        econ.cache_put(self.ws, k, "پاسخ کش‌شده")
        self.assertEqual(econ.cache_get(self.ws, k), "پاسخ کش‌شده")
        st = econ.stats(self.ws)
        self.assertEqual(st["cache_entries"], 1)

    def test_different_history_is_a_cache_miss(self):
        """The 'ask again, I want another answer' case must NOT hit the
        cache: the second turn's history differs (it contains the first
        answer), so the key differs."""
        a = econ.cache_key("blackbox", "blackboxai",
                           [{"role": "user", "content": "سلام"}], 0.7)
        b = econ.cache_key("blackbox", "blackboxai",
                           [{"role": "user", "content": "سلام"},
                            {"role": "assistant", "content": "پاسخ اول"},
                            {"role": "user", "content": "سلام"}], 0.7)
        self.assertNotEqual(a, b)


# --------------------------------------------------------------- version pin
class TestVersion(unittest.TestCase):
    def test_version(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
