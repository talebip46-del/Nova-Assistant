#!/usr/bin/env python3
"""v7.9.0 tests: THE REAL b.ai + the usage panel.

The user's ask (message 22): "منظورم واقعا سایت b.ai بود سرچ کن و ببین /
مطمعن شو تمام پرووایدر ها کامل کار میکنن و حتی بتونم ببینم چقدر
توکن-درخواست-کردیت مصرف کردم و حتی اگه شد ببینم چقدر context هم مصرف کردم"

Verified against the REAL B.AI docs (docs.b.ai):
  - Production Base URL  https://api.b.ai/v1   (OpenAI-compatible:
    GET /models, POST /chat/completions, POST /responses, POST /messages)
  - Auth:  Authorization: Bearer <BAI_API_KEY>   (x-api-key also accepted)
  - Credits law: 1 USD = 1,000,000 Credits, and "X Credits/Token is
    numerically equivalent to USD X / 1M Tokens" -> Nova's USD pricing
    table doubles as the credit rate (nova_cost.CREDITS_PER_USD).

Pinned here:
  1. 'bai' is its own provider (api.b.ai/v1, BAI_API_KEY, default model
     'auto'); the aliases 'b.ai' / 'b-ai' / 'b ai' / 'bankofai' resolve
     EVERYWHERE (entry / resolve / set_key / del_key / key_status /
     routing / parse_target) and the vault stores one canonical row.
     Blackbox keeps its own separate entry (the v7.8 guess was wrong).
  2. usage_summary(): the ledger aggregates into requests / prompt /
     completion / total tokens / USD / CREDIT equivalent / per-provider,
     plus the last request's CONTEXT tokens vs the model's context
     window (ctx_pct). Fail-soft on a corrupt ledger.
  3. credits_of + ctx_limit math (incl. the 1.40 Credits/Token doc
     example and longest-prefix matching).
  4. web surface: /api/providers state carries "usage"; action
     cost_reset wipes the ledger; cmd_cost prints requests + credits +
     the context gauge.
  5. PRACTICAL wire test: a real local HTTP server speaks the B.AI
     chat-completions SSE dialect (incl. the final usage chunk) and
     stream_chunks() pulls BOTH the text and the real token counts
     through an actual socket - not a mocked urlopen.

All tests are NETWORK-FREE except the loopback socket (127.0.0.1).
"""
import http.server
import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova  # noqa: E402
import nova_cost  # noqa: E402
import nova_economy as econ  # noqa: E402
import nova_providers as providers  # noqa: E402


class _WSTestCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(prefix="nova_v79_")
        self.addCleanup(providers.load_config, None)
        self.ws = Path(d)
        providers.load_config(self.ws)


# --------------------------------------------------------------- registry
class TestBaiProvider(_WSTestCase):
    def test_bai_is_registered(self):
        self.assertIn("bai", providers.PROVIDERS)
        self.assertIn("bai", providers.names())
        e = providers.entry("bai") or {}
        self.assertEqual(e["kind"], "openai")
        self.assertEqual(e["base"], "https://api.b.ai/v1")
        self.assertEqual(e["key_env"], "BAI_API_KEY")
        self.assertEqual(e["model"], "auto")
        self.assertIn("b.ai", e["label"])
        self.assertTrue(e["needs_key"])

    def test_aliases_point_to_bai(self):
        for alias in ("b.ai", "b-ai", "b ai", "bai", "bankofai",
                      "bank of ai", " B.AI ", "B-AI"):
            self.assertEqual(providers._canon(alias), "bai", alias)
            self.assertEqual((providers.entry(alias) or {}).get("name"),
                             "bai", alias)

    def test_resolve_via_alias(self):
        with mock.patch.dict("os.environ", {"BAI_API_KEY": "sk-bai-1"}):
            cfg = providers.resolve("b.ai")
        self.assertEqual(cfg["name"], "bai")
        self.assertEqual(cfg["key"], "sk-bai-1")
        self.assertEqual(cfg["base"], "https://api.b.ai/v1")
        self.assertEqual(providers.default_model(cfg), "auto")

    def test_resolve_without_key_is_a_clean_error(self):
        with mock.patch.dict("os.environ", {"BAI_API_KEY": ""}):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.resolve("b.ai")
            self.assertIn("BAI_API_KEY", str(cm.exception))

    def test_set_key_via_alias_lands_on_bai_row(self):
        self.assertEqual(providers.set_key(self.ws, "b.ai", "sk-test-bai"), "")
        self.assertEqual(providers.key_source("bai"), "file")
        is_set, masked = providers.key_status("b.ai")
        self.assertTrue(is_set)
        self.assertEqual(masked, "...-bai")
        raw = json.loads(providers.config_path(self.ws).read_text())
        self.assertEqual(raw["keys"].get("bai"), "sk-test-bai")
        self.assertNotIn("b.ai", raw.get("keys", {}))
        # env no longer needed: resolve reads the vault row
        cfg = providers.resolve("b.ai")
        self.assertEqual(cfg["key"], "sk-test-bai")

    def test_del_key_via_alias(self):
        providers.set_key(self.ws, "b.ai", "sk-x")
        self.assertEqual(providers.del_key(self.ws, "b-ai"), "")
        self.assertEqual(providers.key_source("bai"), "")

    def test_parse_target_and_routing(self):
        self.assertEqual(providers.parse_target("b.ai/glm-5.3"),
                         ("bai", "glm-5.3"))
        self.assertEqual(providers.parse_target("B.AI/kimi-k3"),
                         ("bai", "kimi-k3"))
        self.assertEqual(providers.set_route(self.ws, "talk", "b.ai/glm-5.3"), "")
        with mock.patch.dict("os.environ", {"BAI_API_KEY": "sk-bai-1"}):
            cfg, model = providers.resolve_route("talk")
        self.assertEqual(cfg["name"], "bai")
        self.assertEqual(model, "glm-5.3")
        # a stored route under the OLD wrong canonical name still resolves
        self.assertEqual(providers.set_route(self.ws, "utility", "bai/auto"), "")
        with mock.patch.dict("os.environ", {"BAI_API_KEY": "sk-bai-1"}):
            cfg2, model2 = providers.resolve_route("utility")
        self.assertEqual((cfg2["name"], model2), ("bai", "auto"))

    def test_models_endpoint_matches_docs(self):
        cfg = dict(providers.PROVIDERS["bai"], name="bai", key="sk-bai-1")
        url, headers = providers._models_endpoint(cfg)
        self.assertEqual(url, "https://api.b.ai/v1/models")
        self.assertEqual(headers.get("Authorization"), "Bearer sk-bai-1")

    def test_bai_models_payload_shape_parses(self):
        # the exact response shape from docs.b.ai (object=list, success)
        payload = {"object": "list", "success": True, "data":
                   [{"id": "glm-5.3", "object": "model", "created": 1787587200},
                    {"id": "deepseek-v4.1-flash", "object": "model"},
                    {"id": "kimi-k3", "object": "model"}]}
        self.assertEqual(providers._models_parse("openai", payload),
                         ["glm-5.3", "deepseek-v4.1-flash", "kimi-k3"])

    def test_blackbox_stays_separate(self):
        e = providers.entry("blackbox") or {}
        self.assertEqual(e["base"], "https://api.blackbox.ai/api")
        self.assertNotEqual(e["key_env"], "BAI_API_KEY")
        self.assertEqual(providers._canon("blackboxai"), "blackbox")
        ns = providers.names()
        self.assertIn("blackbox", ns)
        self.assertIn("bai", ns)

    def test_web_state_lists_bai(self):
        sess = SimpleNamespace(ws=str(self.ws))
        st = nova.web_providers_state(sess)
        ids = [p["id"] for p in st["providers"]]
        self.assertIn("bai", ids)
        self.assertIn("blackbox", ids)
        row = next(p for p in st["providers"] if p["id"] == "bai")
        self.assertEqual(row["key_env"], "BAI_API_KEY")
        self.assertEqual(row["model_default"], "auto")

    def test_discover_reads_bai_models(self):
        body = json.dumps({"object": "list", "success": True, "data":
                           [{"id": "glm-5.3"}, {"id": "kimi-k3"}]}).encode()

        class R:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self, n=-1):
                return body

        cfg = dict(providers.PROVIDERS["bai"], name="bai", key="k")
        with mock.patch.dict("os.environ", {"BAI_API_KEY": "k"}), \
                mock.patch.object(providers.urllib.request, "urlopen",
                                  return_value=R()):
            models = providers.discover("b.ai", force=True, timeout=5)
        self.assertEqual(models, ["glm-5.3", "kimi-k3"])
        self.assertEqual(providers.cached_models("bai"),
                         ["glm-5.3", "kimi-k3"])


# --------------------------------------------------------------- credits + ctx
class TestCreditsAndContext(unittest.TestCase):
    def test_credits_conversion_is_the_bai_law(self):
        self.assertEqual(nova_cost.CREDITS_PER_USD, 1_000_000)
        self.assertEqual(nova_cost.credits_of(1.0), 1_000_000.0)
        self.assertEqual(nova_cost.credits_of(0), 0.0)
        self.assertEqual(nova_cost.credits_of(None), 0.0)
        self.assertEqual(nova_cost.credits_of("junk"), 0.0)
        # docs example: 1.32 Credits/Token == $1.32 / 1M tokens
        self.assertAlmostEqual(nova_cost.credits_of(1.32), 1_320_000.0)

    def test_pricing_doubles_as_credit_rate(self):
        # 1M input tokens at $1.40/1M -> $1.40 -> 1.4M credits
        # (the pricing.json override path, like b.ai's GLM-5.3 row)
        d = tempfile.mkdtemp(prefix="nova_v79c_")
        (Path(d) / ".nova").mkdir()
        (Path(d) / ".nova" / "pricing.json").write_text(
            json.dumps({"glm-5.3": [1.40, 4.40]}), encoding="utf-8")
        usd = nova_cost.cost_of(d, "bai", "glm-5.3", 1_000_000, 0)
        self.assertAlmostEqual(usd, 1.40, places=6)
        self.assertAlmostEqual(nova_cost.credits_of(usd), 1_400_000.0, places=0)

    def test_ctx_limit_known_models(self):
        self.assertEqual(nova_cost.ctx_limit("gpt-4o-mini"), (128_000, 16_000))
        self.assertEqual(nova_cost.ctx_limit("gpt-4.1-mini"), (1_000_000, 32_000))
        self.assertEqual(nova_cost.ctx_limit("claude-sonnet-4-5"), (200_000, 64_000))
        self.assertEqual(nova_cost.ctx_limit("deepseek-chat"), (131_072, 8_000))
        self.assertEqual(nova_cost.ctx_limit("kimi-k3"), (262_144, 8_000))

    def test_ctx_limit_unknown_is_none(self):
        self.assertEqual(nova_cost.ctx_limit("totally-unknown-model"),
                         (None, None))
        self.assertEqual(nova_cost.ctx_limit(""), (None, None))
        self.assertEqual(nova_cost.ctx_limit(None), (None, None))


# --------------------------------------------------------------- usage_summary
class TestUsageSummary(_WSTestCase):
    def test_empty_workspace_is_all_zeros(self):
        s = nova_cost.usage_summary(str(self.ws))
        for part in ("today", "total"):
            self.assertEqual(s[part]["requests"], 0)
            self.assertEqual(s[part]["total_tokens"], 0)
            self.assertEqual(s[part]["cost_usd"], 0.0)
            self.assertEqual(s[part]["credits"], 0.0)
            self.assertEqual(s[part]["per_provider"], {})
        self.assertIsNone(s["last_request"])
        self.assertIn("requests_saved", s["cache_savings"])

    def test_corrupt_ledger_never_raises(self):
        (self.ws / ".nova").mkdir(exist_ok=True)
        (self.ws / ".nova" / "costs.json").write_text("{broken json",)
        s = nova_cost.usage_summary(str(self.ws))
        self.assertEqual(s["total"]["requests"], 0)

    def test_records_aggregate_into_the_summary(self):
        ws = str(self.ws)
        nova_cost.record(ws, "bai", "glm-5.3", 1200, 300, actual=True)
        nova_cost.record(ws, "groq", "llama-3.3-70b-versatile", 500, 150,
                         actual=True, dur_s=1.0)
        s = nova_cost.usage_summary(ws)
        self.assertEqual(s["total"]["requests"], 2)
        self.assertEqual(s["total"]["prompt_tokens"], 1700)
        self.assertEqual(s["total"]["completion_tokens"], 450)
        self.assertEqual(s["total"]["total_tokens"], 2150)
        self.assertGreater(s["total"]["cost_usd"], 0)
        self.assertGreater(s["total"]["credits"], 0)
        self.assertAlmostEqual(s["total"]["credits"],
                               round(s["total"]["cost_usd"] * 1_000_000, 3),
                               places=2)
        per = s["total"]["per_provider"]
        self.assertEqual(per["bai"]["requests"], 1)
        self.assertEqual(per["groq"]["requests"], 1)
        self.assertEqual(per["bai"]["ptok"], 1200)
        # today's block saw them too (same day)
        self.assertEqual(s["today"]["requests"], 2)
        # failed requests are still requests - the user must see them
        nova_cost.record(ws, "openai", "gpt-4o-mini", 10, 0, ok=False)
        self.assertEqual(s and nova_cost.usage_summary(ws)["total"]["requests"], 3)

    def test_last_request_context_gauge(self):
        ws = str(self.ws)
        nova_cost.record(ws, "openai", "gpt-4o", 64000, 1000, actual=True)
        s = nova_cost.usage_summary(ws)
        last = s["last_request"]
        self.assertIsNotNone(last)
        self.assertEqual(last["provider"], "openai")
        self.assertEqual(last["model"], "gpt-4o")
        self.assertEqual(last["context_tokens"], 64000)
        self.assertEqual(last["ctx_window"], 128_000)
        self.assertEqual(last["ctx_pct"], 50.0)
        self.assertTrue(last["actual"])

    def test_last_request_unknown_window_has_no_pct(self):
        ws = str(self.ws)
        nova_cost.record(ws, "custom-relay", "mystery-model", 4000, 100)
        last = nova_cost.usage_summary(ws)["last_request"]
        self.assertIsNone(last["ctx_window"])
        self.assertIsNone(last["ctx_pct"])
        self.assertEqual(last["context_tokens"], 4000)

    def test_cache_savings_surface_in_the_summary(self):
        ws = str(self.ws)
        econ.bump(ws, "requests_saved", 4)
        econ.bump(ws, "tokens_saved", 9000)
        s = nova_cost.usage_summary(ws)
        self.assertEqual(s["cache_savings"]["requests_saved"], 4)
        self.assertEqual(s["cache_savings"]["tokens_saved"], 9000)


# --------------------------------------------------------------- web + cli
class TestWebUsageSurface(_WSTestCase):
    def test_state_carries_usage(self):
        ws = str(self.ws)
        nova_cost.record(ws, "bai", "glm-5.3", 800, 200, actual=True)
        sess = SimpleNamespace(ws=ws)
        st = nova.web_providers_state(sess)
        self.assertIn("usage", st)
        self.assertEqual(st["usage"]["total"]["requests"], 1)
        self.assertEqual(st["usage"]["total"]["per_provider"]["bai"]["ptok"], 800)
        self.assertEqual(st["usage"]["last_request"]["model"], "glm-5.3")

    def test_cost_reset_action(self):
        ws = str(self.ws)
        nova_cost.record(ws, "bai", "glm-5.3", 800, 200, actual=True)
        sess = SimpleNamespace(ws=ws)
        ok, payload, status = nova.web_providers_action(sess, {"action": "cost_reset"})
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertEqual(payload["usage"]["total"]["requests"], 0)
        self.assertFalse((self.ws / ".nova" / "costs.json").exists())

    def test_unknown_action_still_400(self):
        ok, _payload, status = nova.web_providers_action(
            SimpleNamespace(ws=str(self.ws)), {"action": "nope"})
        self.assertFalse(ok)
        self.assertEqual(status, 400)

    def test_cmd_cost_prints_requests_credits_context(self):
        ws = str(self.ws)
        nova_cost.record(ws, "openai", "gpt-4o", 64000, 1000, actual=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_cost(SimpleNamespace(ws=ws, history=[]), "")
        out = buf.getvalue()
        self.assertIn("request(s)", out)
        self.assertIn("credits", out)
        self.assertIn("64000".replace("000", ",000"), out)
        self.assertIn("50.0% of the 128,000-token window", out)

    def test_cmd_cost_reset(self):
        ws = str(self.ws)
        nova_cost.record(ws, "openai", "gpt-4o", 100, 10, actual=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_cost(SimpleNamespace(ws=ws), "reset")
        self.assertIn("cleared", buf.getvalue())
        self.assertFalse((self.ws / ".nova" / "costs.json").exists())


# --------------------------------------------------------------- practical wire
class _SSEServer(http.server.BaseHTTPRequestHandler):
    """Speaks the B.AI /chat/completions SSE dialect on the loopback."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # silence the test runner
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"object": "list", "success": True, "data":
                               [{"id": "glm-5.3"}, {"id": "kimi-k3"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer sk-live-bai":
            self.send_error(401)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        req = json.loads(self.rfile.read(length) or b"{}")
        # the request MUST be the plain OpenAI chat-completions shape
        assert req.get("stream") is True
        assert isinstance(req.get("messages"), list)
        chunks = [
            b'data: {"choices":[{"delta":{"content":"\\u0633"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"\\u0644\\u0627\\u0645"}}]}\n\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":111,'
            b'"completion_tokens":22,"total_tokens":133}}\n\n',
            b"data: [DONE]\n\n",
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # HTTP/1.1 + no Content-Length -> read to EOF; close_connection keeps
        # the handler from hanging on keep-alive
        self.close_connection = True
        self.end_headers()
        for c in chunks:
            self.wfile.write(c)


class TestPracticalWireAgainstLocalServer(_WSTestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SSEServer)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_full_bai_dialect_over_a_real_socket(self):
        base = f"http://127.0.0.1:{self.port}/v1"
        name = "baimock"
        self.assertEqual(providers.add_custom(
            self.ws, name, base, model="glm-5.3", kind="openai",
            label="local B.AI mock"), "")
        providers.set_key(self.ws, name, "sk-live-bai")
        cfg = providers.resolve(name)
        self.assertEqual(cfg["key"], "sk-live-bai")
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        gen = providers.stream_chunks(
            cfg, "glm-5.3", [{"role": "user", "content": "سلام"}], 0.2, 10,
            usage=usage)
        text = "".join(gen)
        self.assertEqual(text, "سلام")
        self.assertTrue(usage["actual"])
        self.assertEqual(usage["prompt_tokens"], 111)
        self.assertEqual(usage["completion_tokens"], 22)
        # and the same server serves model discovery (1 request, cached)
        models = providers.discover(name, force=True, timeout=5)
        self.assertEqual(models, ["glm-5.3", "kimi-k3"])
        # wrong key -> a clean ProviderError, never a traceback
        providers.set_key(self.ws, name, "sk-wrong")
        cfg2 = providers.resolve(name)
        with self.assertRaises(providers.ProviderError) as cm:
            list(providers.stream_chunks(
                cfg2, "glm-5.3", [{"role": "user", "content": "x"}], 0.2, 10))
        self.assertIn("401", str(cm.exception))

    def test_ledger_prices_a_turn_on_the_wire_result(self):
        base = f"http://127.0.0.1:{self.port}/v1"
        name = "baimock2"
        self.assertEqual(providers.add_custom(
            self.ws, name, base, model="glm-5.3"), "")
        providers.set_key(self.ws, name, "sk-live-bai")
        cfg = providers.resolve(name)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        with mock.patch.dict("os.environ", {"NOVA_TEST_SILENT": "1"}):
            list(providers.stream_chunks(
                cfg, "glm-5.3", [{"role": "user", "content": "hi"}], 0.2, 10,
                usage=usage))
        nova_cost.record(str(self.ws), name, "glm-5.3",
                         usage["prompt_tokens"], usage["completion_tokens"],
                         actual=True)
        s = nova_cost.usage_summary(str(self.ws))
        self.assertEqual(s["total"]["requests"], 1)
        self.assertEqual(s["last_request"]["context_tokens"], 111)
        self.assertEqual(s["total"]["per_provider"][name]["requests"], 1)


# --------------------------------------------------------------- version pin
class TestVersion(unittest.TestCase):
    def test_version(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
