#!/usr/bin/env python3
# =====================================================================
#  Nova v6.6.0 regression tests - the provider upgrade:
#    26-provider registry, workspace key vault, custom providers,
#    auto model discovery (+cache), per-section routing, request
#    economy (response cache / budgets / output caps), web endpoints.
#  Everything is offline: network calls are monkeypatched, never opened.
# =====================================================================
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_providers as providers    # noqa: E402
import nova_economy as econ           # noqa: E402
import nova                           # noqa: E402


def _reset_cfg():
    """Isolate from other tests: empty config, no active provider."""
    providers._ACTIVE["name"] = None
    providers._MODEL_OVERRIDES.clear()
    with providers._CFG_LOCK:
        providers._CFG.update({"ws": None, "keys": {}, "custom": [],
                               "routing": {}, "economy": {},
                               "discovered": {}})


class _WSTestCase(unittest.TestCase):
    """A test with its own temp workspace wired into the provider layer."""

    def setUp(self):
        _reset_cfg()
        self._env = mock.patch.dict("os.environ", {}, clear=True)
        self._env.start()
        self.ws = Path(tempfile.mkdtemp(prefix="nova_v660_"))
        providers.load_config(self.ws)

    def tearDown(self):
        self._env.stop()
        _reset_cfg()


# --------------------------------------------------------------- registry
class TestRegistry(unittest.TestCase):
    def setUp(self):
        _reset_cfg()

    def test_at_least_24_builtin_providers(self):
        self.assertGreaterEqual(len(providers.PROVIDERS), 24)

    def test_ollama_is_first_in_names(self):
        self.assertEqual(providers.names()[0], "ollama")

    def test_every_provider_has_required_fields(self):
        for name, cfg in providers.PROVIDERS.items():
            for field in ("kind", "base", "model", "label"):
                self.assertIn(field, cfg, f"{name} missing {field}")

    def test_kinds_are_known(self):
        for name, cfg in providers.PROVIDERS.items():
            self.assertIn(cfg["kind"], ("openai", "anthropic", "gemini", "ollama"),
                          f"{name} has an unknown kind")

    def test_cloud_bases_are_https(self):
        for name, cfg in providers.PROVIDERS.items():
            if cfg.get("needs_key", name not in providers._KEYLESS):
                self.assertTrue(cfg["base"].startswith("https://"),
                                f"{name} is a cloud provider with a non-https base")

    def test_keyless_locals_exist(self):
        for n in ("ollama", "lmstudio", "llamacpp", "vllm"):
            self.assertFalse(providers.PROVIDERS[n].get("needs_key", False))

    def test_key_envs_are_unique_and_named(self):
        envs = [c["key_env"] for c in providers.PROVIDERS.values() if c.get("key_env")]
        self.assertEqual(len(envs), len(set(envs)), "two providers share a key_env")


# --------------------------------------------------------------- config file
class TestParseConfig(unittest.TestCase):
    def test_empty_and_junk(self):
        for junk in (None, 42, "x", [], {}):
            out = providers.parse_config(junk)
            self.assertEqual(out["keys"], {})
            self.assertEqual(out["custom"], [])

    def test_keys_validated(self):
        # keys are PROVIDER IDS: builtin names or custom slugs - anything
        # else in the file is a hostile hand-edit and must be dropped
        out = providers.parse_config({"keys": {"openai": "sk-ok",
                                               "UPPER Case": "v",
                                               "bad name!": "v2",
                                               "empty": "   "}})
        self.assertEqual(out["keys"], {"openai": "sk-ok"})

    def test_custom_validation(self):
        out = providers.parse_config({"custom": [
            {"name": "ok1", "base": "https://a.example/v1", "model": "m1",
             "kind": "openai", "label": "OK 1"},
            {"name": "openai", "base": "https://evil/v1"},        # builtin clash
            {"name": "Bad Name", "base": "https://a/v1"},         # slug fail
            {"name": "ok2", "base": "ftp://nope"},                # scheme fail
            {"name": "ok3", "base": "https://a/v1", "kind": "ws"},# kind fail -> openai
            "not a dict",
        ]})
        names = [c["name"] for c in out["custom"]]
        self.assertEqual(names, ["ok1", "ok3"])
        self.assertEqual(out["custom"][1]["kind"], "openai")

    def test_routing_and_economy_validation(self):
        out = providers.parse_config({
            "routing": {"talk": "groq/llama-3.3-70b-versatile",
                        "bogus": "x/y", "coding": ""},
            "economy": {"cache": False, "daily_budget_usd": 2.5,
                        "max_tokens": {"talk": 700, "nope": 9, "coding": -4},
                        "unknown_field": 1}})
        self.assertEqual(out["routing"], {"talk": "groq/llama-3.3-70b-versatile"})
        self.assertEqual(out["economy"]["daily_budget_usd"], 2.5)
        self.assertEqual(out["economy"]["max_tokens"], {"talk": 700})
        self.assertNotIn("unknown_field", out["economy"])

    def test_discovered_validation(self):
        out = providers.parse_config({"discovered": {
            "groq": {"ts": 1712345678, "models": ["a", "a", "b x y",
                                                  42, {"id": "nope"}]},
            "bad": {"ts": "x", "models": ["a"]}}})
        self.assertEqual(out["discovered"]["groq"]["models"], ["a", "b x y"])
        self.assertNotIn("bad", out["discovered"])


class TestVaultAndResolve(_WSTestCase):
    def test_missing_key_raises_without_file_or_env(self):
        with self.assertRaises(providers.ProviderError):
            providers.resolve("openai")

    def test_env_key_still_works(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env"}):
            cfg = providers.resolve("openai")
        self.assertEqual(cfg["key"], "sk-env")

    def test_file_key_wins_over_env(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env"}):
            providers.set_key(self.ws, "openai", "sk-file")
            cfg = providers.resolve("openai")
        self.assertEqual(cfg["key"], "sk-file")
        self.assertEqual(providers.key_source("openai"), "file")

    def test_key_file_written_and_masked(self):
        providers.set_key(self.ws, "groq", "gsk_secret_1234")
        p = self.ws / ".nova" / "providers.json"
        self.assertTrue(p.is_file())
        body = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(body["keys"]["groq"], "gsk_secret_1234")
        self.assertEqual(providers.mask_key("gsk_secret_1234"), "...1234")
        # masked value NEVER contains the full secret
        self.assertNotIn("gsk_secret_1234", providers.mask_key("gsk_secret_1234"))

    def test_del_key_restores_env(self):
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "sk-env"}):
            providers.set_key(self.ws, "groq", "sk-file")
            self.assertEqual(providers.resolve("groq")["key"], "sk-file")
            providers.del_key(self.ws, "groq")
            self.assertEqual(providers.resolve("groq")["key"], "sk-env")

    def test_corrupt_config_degrades_to_empty(self):
        p = self.ws / ".nova" / "providers.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{broken json", encoding="utf-8")
        providers.load_config(self.ws)
        # no key anywhere -> the clean ProviderError, never a crash
        with self.assertRaises(providers.ProviderError):
            providers.resolve("openai")


class TestCustomProviders(_WSTestCase):
    def test_add_list_del(self):
        err = providers.add_custom(self.ws, "relay1", "https://my.box/v1",
                                   model="qwen2.5-coder-7b")
        self.assertEqual(err, "")
        self.assertIn("relay1", providers.names())
        e = providers.entry("relay1")
        self.assertEqual(e["base"], "https://my.box/v1")
        self.assertFalse(e["needs_key"], "custom keys must be optional")
        cfg = providers.resolve("relay1")        # no key -> still resolves
        self.assertEqual(cfg["key"], "")
        providers.set_key(self.ws, "relay1", "sk-relay")
        self.assertEqual(providers.resolve("relay1")["key"], "sk-relay")
        err = providers.del_custom(self.ws, "relay1")
        self.assertEqual(err, "")
        self.assertNotIn("relay1", providers.names())

    def test_name_rules(self):
        self.assertNotEqual(providers.add_custom(self.ws, "x", "https://a/v1"), "")
        self.assertNotEqual(providers.add_custom(self.ws, "openai", "https://a/v1"), "")
        self.assertNotEqual(providers.add_custom(self.ws, "ok1", "ftp://a/v1"), "")
        self.assertNotEqual(providers.add_custom(self.ws, "ok1", "https://a/v1",
                                                 kind="ws"), "")

    def test_del_cascades_key_and_route(self):
        providers.add_custom(self.ws, "relay2", "https://my.box/v1")
        providers.set_key(self.ws, "relay2", "sk-r")
        providers.set_route(self.ws, "talk", "relay2/m1")
        self.assertEqual(providers.route_target("talk"), "relay2/m1")
        providers.del_custom(self.ws, "relay2")
        self.assertEqual(providers.route_target("talk"), "")
        self.assertEqual(providers.key_status("relay2"), (False, ""))


# --------------------------------------------------------------- routing
class TestRouting(_WSTestCase):
    def test_parse_target_slashes_and_bare(self):
        self.assertEqual(providers.parse_target("groq/llama-3.3-70b-versatile"),
                         ("groq", "llama-3.3-70b-versatile"))
        self.assertEqual(providers.parse_target("openai/org/gpt-4o"),
                         ("openai", "org/gpt-4o"))
        self.assertEqual(providers.parse_target("groq"), ("groq", ""))
        with self.assertRaises(providers.ProviderError):
            providers.parse_target("no-such-provider/m1")

    def test_route_roundtrip(self):
        self.assertEqual(providers.set_route(self.ws, "talk",
                                             "groq/llama-3.3-70b-versatile"), "")
        self.assertEqual(providers.route_target("talk"),
                         "groq/llama-3.3-70b-versatile")
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "sk-x"}):
            cfg, model = providers.resolve_route("talk")
        self.assertEqual(cfg["name"], "groq")
        self.assertEqual(model, "llama-3.3-70b-versatile")

    def test_route_off_and_bad_section(self):
        providers.set_route(self.ws, "talk", "groq/m1")
        self.assertEqual(providers.set_route(self.ws, "talk", "off"), "")
        self.assertEqual(providers.route_target("talk"), "")
        self.assertNotEqual(providers.set_route(self.ws, "nope", "groq/m1"), "")
        self.assertNotEqual(providers.set_route(self.ws, "talk", "bad!!/x"), "")

    def test_resolve_route_no_route(self):
        self.assertEqual(providers.resolve_route("utility"), (None, ""))

    def test_sections_are_stable(self):
        self.assertEqual(providers.SECTIONS,
                         ("coding", "talk", "utility", "council"))


# --------------------------------------------------------------- discovery
class TestDiscoveryParsers(unittest.TestCase):
    def test_openai_shapes(self):
        self.assertEqual(providers._models_parse_openai(
            {"data": [{"id": "a"}, {"id": "b"}]}), ["a", "b"])
        self.assertEqual(providers._models_parse_openai(
            [{"id": "a"}, {"name": "b"}]), ["a", "b"])
        self.assertEqual(providers._models_parse_openai({"nope": 1}), [])
        self.assertEqual(providers._models_parse_openai("junk"), [])
        self.assertEqual(providers._models_parse_openai(
            {"data": [{"id": "a"}, {"id": "a"}, {"id": ""}, 42]}), ["a"])

    def test_gemini_prefix_and_embed_filter(self):
        out = providers._models_parse_gemini({"models": [
            {"name": "models/gemini-2.0-flash"},
            {"name": "models/text-embedding-004"},
            {"name": "models/gemini-2.0-flash"},        # dupe after strip
            {"name": 42},
        ]})
        self.assertEqual(out, ["gemini-2.0-flash"])

    def test_ollama_tags_shape(self):
        out = providers._models_parse_ollama(
            {"models": [{"name": "qwen2.5-coder:7b"}, {"model": "llama3:8b"}]})
        self.assertEqual(out, ["qwen2.5-coder:7b", "llama3:8b"])

    def test_clean_model_list_cap(self):
        raw = [f"m{i}" for i in range(2000)]
        out = providers._clean_model_list(raw)
        self.assertLessEqual(len(out), providers.MAX_MODELS_CACHED)


class TestDiscover(_WSTestCase):
    def _patch_fetch(self, payload, calls):
        def fake_get_json(url, headers, timeout):
            calls.append((url, dict(headers)))
            return payload
        return mock.patch.object(providers, "_get_json", side_effect=fake_get_json)

    def test_discover_caches_one_request(self):
        calls = []
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "sk-x"}):
            with self._patch_fetch({"data": [{"id": "m1"}, {"id": "m2"}]}, calls):
                out = providers.discover("groq")
            self.assertEqual(out, ["m1", "m2"])
            # second call inside TTL: NO new request (the request diet)
            with self._patch_fetch({"data": [{"id": "m3"}]}, calls):
                out = providers.discover("groq")
            self.assertEqual(out, ["m1", "m2"])
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0][0].startswith("https://api.groq.com/openai/v1/models"))
            self.assertEqual(calls[0][1].get("Authorization"), "Bearer sk-x")
        # the cache is persisted with the workspace
        providers.load_config(self.ws)
        self.assertEqual(providers.cached_models("groq"), ["m1", "m2"])

    def test_force_refetches(self):
        calls = []
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "sk-x"}):
            with self._patch_fetch({"data": [{"id": "m1"}]}, calls):
                providers.discover("groq")
            with self._patch_fetch({"data": [{"id": "m2"}]}, calls):
                providers.discover("groq", force=True)
        self.assertEqual(len(calls), 2)

    def test_missing_key_raises_clean(self):
        with self.assertRaises(providers.ProviderError):
            providers.discover("openai")

    def test_stale_cache_survives_a_dead_network(self):
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "sk-x"}):
            providers.discover("groq", force=True) if False else None
            with self._patch_fetch({"data": [{"id": "m1"}]}, []):
                providers.discover("groq", force=True)
            def boom(url, headers, timeout):
                raise urllib.error.URLError("net down")
            with mock.patch.object(providers, "_get_json", side_effect=boom):
                out = providers.discover("groq", force=True)
            self.assertEqual(out, ["m1"])

    def test_ollama_uses_tags_endpoint(self):
        calls = []
        with self._patch_fetch({"models": [{"name": "q:1b"}]}, calls):
            out = providers.discover("ollama", force=True)
        self.assertEqual(out, ["q:1b"])
        self.assertTrue(calls[0][0].endswith("/api/tags"))


# --------------------------------------------------------------- economy config
class TestEconomyConfig(_WSTestCase):
    def test_defaults(self):
        eco = providers.economy()
        self.assertTrue(eco["cache"])
        self.assertEqual(eco["max_tokens"]["talk"], 1024)
        self.assertEqual(eco["max_tokens"]["utility"], 512)
        self.assertEqual(eco["max_tokens"]["coding"], 0)
        self.assertEqual(eco["daily_budget_usd"], 0.0)

    def test_max_tokens_for_sections(self):
        self.assertEqual(providers.max_tokens_for("talk"), 1024)
        self.assertEqual(providers.max_tokens_for("utility"), 512)
        self.assertEqual(providers.max_tokens_for("coding"), 0)
        self.assertEqual(providers.max_tokens_for(None), 0)

    def test_set_economy_persists(self):
        self.assertEqual(providers.set_economy(
            self.ws, {"daily_budget_usd": 3.0, "max_tokens": {"talk": 800}}), "")
        providers.load_config(self.ws)
        self.assertEqual(providers.economy()["daily_budget_usd"], 3.0)
        self.assertEqual(providers.economy()["max_tokens"]["talk"], 800)
        self.assertEqual(providers.economy()["max_tokens"]["utility"], 512,
                         "a partial max_tokens update must keep the other defaults")


# --------------------------------------------------------------- wire payload
class _FakeResp:
    def __init__(self, lines=()):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestWirePayloads(unittest.TestCase):
    """The economy touches the REQUEST payloads - pin those bytes."""

    def _capture(self, gen):
        """Iterate a provider stream generator with urlopen faked; return
        the captured urllib Request."""
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _FakeResp([b"data: [DONE]\n"])

        with mock.patch.object(providers.urllib.request, "urlopen",
                               side_effect=fake_urlopen):
            out = list(gen)
        self.assertEqual(out, [])
        return captured["req"]

    def test_openai_uses_max_tokens_field(self):
        cfg = dict(providers.PROVIDERS["groq"], name="groq", key="k")
        req = self._capture(providers._openai_stream(
            cfg, "m", [{"role": "user", "content": "hi"}], 0.2, 30, max_tokens=512))
        body = json.loads(req.data)
        self.assertEqual(body["max_tokens"], 512)

    def test_openai_provider_uses_completion_field(self):
        cfg = dict(providers.PROVIDERS["openai"], name="openai", key="k")
        req = self._capture(providers._openai_stream(
            cfg, "m", [{"role": "user", "content": "hi"}], 0.2, 30, max_tokens=700))
        body = json.loads(req.data)
        self.assertEqual(body["max_completion_tokens"], 700)
        self.assertNotIn("max_tokens", body)

    def test_openai_no_cap_no_field(self):
        cfg = dict(providers.PROVIDERS["groq"], name="groq", key="k")
        req = self._capture(providers._openai_stream(
            cfg, "m", [{"role": "user", "content": "hi"}], 0.2, 30, max_tokens=0))
        body = json.loads(req.data)
        self.assertNotIn("max_tokens", body)

    def test_anthropic_cache_control_on_stable_system(self):
        cfg = dict(providers.PROVIDERS["anthropic"], name="anthropic", key="k")
        msgs = [{"role": "system", "content": "CORE RULES"},
                {"role": "user", "content": "hi"}]
        req = self._capture(providers._anthropic_stream(cfg, "m", msgs, 0.2, 30, max_tokens=0))
        body = json.loads(req.data)
        self.assertEqual(body["max_tokens"], 8192)
        sysblk = body["system"]
        self.assertIsInstance(sysblk, list)
        self.assertEqual(sysblk[0]["text"], "CORE RULES")
        self.assertEqual(sysblk[0]["cache_control"], {"type": "ephemeral"})

    def test_anthropic_cache_can_be_disabled(self):
        with mock.patch.object(providers, "anthropic_cache_enabled", return_value=False):
            cfg = dict(providers.PROVIDERS["anthropic"], name="anthropic", key="k")
            msgs = [{"role": "system", "content": "CORE"},
                    {"role": "user", "content": "hi"}]
            req = self._capture(providers._anthropic_stream(cfg, "m", msgs, 0.2, 30))
            body = json.loads(req.data)
        self.assertEqual(body["system"], "CORE")

    def test_anthropic_cap_is_min_of_env_and_section(self):
        cfg = dict(providers.PROVIDERS["anthropic"], name="anthropic", key="k")
        with mock.patch.dict("os.environ", {"NOVA_MAX_TOKENS": "900"}):
            req = self._capture(providers._anthropic_stream(
                cfg, "m", [{"role": "user", "content": "hi"}], 0.2, 30, max_tokens=400))
            self.assertEqual(json.loads(req.data)["max_tokens"], 400)
            req = self._capture(providers._anthropic_stream(
                cfg, "m", [{"role": "user", "content": "hi"}], 0.2, 30, max_tokens=0))
            self.assertEqual(json.loads(req.data)["max_tokens"], 900)

    def test_gemini_max_output_tokens(self):
        cfg = dict(providers.PROVIDERS["gemini"], name="gemini", key="k")
        req = self._capture(providers._gemini_stream(
            cfg, "m", [{"role": "user", "content": "hi"}], 0.2, 30, max_tokens=640))
        body = json.loads(req.data)
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 640)


# --------------------------------------------------------------- econ cache
class TestEconCache(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_econ_"))

    def test_cache_key_stability(self):
        msgs = [{"role": "user", "content": "hello"}]
        a = econ.cache_key("groq", "m1", msgs, 0.2)
        b = econ.cache_key("groq", "m1", msgs, 0.20000001)
        c = econ.cache_key("groq", "m1", [{"role": "user", "content": "changed"}], 0.2)
        d = econ.cache_key("openai", "m1", msgs, 0.2)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)

    def test_put_get_roundtrip_and_counters(self):
        k = econ.cache_key("groq", "m1", [{"role": "user", "content": "x"}], 0.2)
        self.assertIsNone(econ.cache_get(self.ws, k))
        econ.cache_put(self.ws, k, "cached answer")
        self.assertEqual(econ.cache_get(self.ws, k), "cached answer")
        st = econ.stats(self.ws)
        self.assertEqual(st["cache_entries"], 1)

    def test_ttl_expiry(self):
        k = econ.cache_key("groq", "m1", [{"role": "user", "content": "x"}], 0.2)
        econ.cache_put(self.ws, k, "old")
        self.assertEqual(econ.cache_get(self.ws, k, ttl=-1), None,
                         "an expired entry must never be served")

    def test_lru_cap(self):
        for i in range(10):
            k = econ.cache_key("groq", "m1",
                               [{"role": "user", "content": f"q{i}"}], 0.2)
            econ.cache_put(self.ws, k, f"a{i}", max_entries=3)
        st = econ.stats(self.ws)
        self.assertEqual(st["cache_entries"], 3)

    def test_bump_and_day_reset(self):
        econ.bump(self.ws, "cache_hits", 2)
        econ.bump_tokens_saved(self.ws, 500)
        self.assertEqual(econ.stats(self.ws)["counters"]["cache_hits"], 2)
        self.assertEqual(econ.stats(self.ws)["counters"]["tokens_saved"], 500)
        yesterday = json.loads((self.ws / ".nova" / "responses_cache.json")
                               .read_text(encoding="utf-8"))
        yesterday["day"] = "2000-01-01"
        counters, _ = econ.parse_store(yesterday)
        self.assertEqual(counters["cache_hits"], 0, "a new day resets counters")

    def test_junk_store_degrades(self):
        for junk in (None, 42, "x", [], {"cache": "nope"}):
            counters, entries = econ.parse_store(junk)
            self.assertEqual(entries, [])

    def test_broken_cache_file_never_breaks(self):
        p = self.ws / ".nova" / "responses_cache.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{broken", encoding="utf-8")
        self.assertIsNone(econ.cache_get(self.ws, "k"))
        econ.cache_put(self.ws, "k", "answer")     # heals the file
        self.assertEqual(econ.cache_get(self.ws, "k"), "answer")


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_bud_"))

    def test_no_budget_no_block(self):
        self.assertIsNone(econ.budget_block(self.ws, "openai"))

    def test_usd_budget_blocks(self):
        with mock.patch.dict("os.environ", {}):
            providers._ACTIVE["name"] = None
            providers.set_economy(self.ws, {"daily_budget_usd": 1.0})
            fake = {"today": {"per_model": {"openai :: gpt-4o": {
                "cost": 1.5, "ptok": 10, "ctok": 10}}}}
            with mock.patch("nova_cost.report", return_value=fake):
                reason = econ.budget_block(self.ws, "openai")
            self.assertIsNotNone(reason)
            self.assertIn("budget", reason)
            self.assertIsNone(econ.budget_block(self.ws, "groq"),
                              "another provider must not be blocked")

    def test_token_budget_blocks(self):
        providers.set_economy(self.ws, {"daily_token_budget": 1000})
        fake = {"today": {"per_model": {"openai :: gpt-4o": {
            "cost": 0.0, "ptok": 700, "ctok": 600}}}}
        with mock.patch("nova_cost.report", return_value=fake):
            reason = econ.budget_block(self.ws, "openai")
        self.assertIsNotNone(reason)
        self.assertIn("token", reason)

    def test_under_budget_passes(self):
        providers.set_economy(self.ws, {"daily_budget_usd": 10.0})
        fake = {"today": {"per_model": {"openai :: gpt-4o": {
            "cost": 0.01, "ptok": 10, "ctok": 10}}}}
        with mock.patch("nova_cost.report", return_value=fake):
            self.assertIsNone(econ.budget_block(self.ws, "openai"))


# --------------------------------------------------------------- stream_chat
def _fake_ollama_urlopen(calls, text, prompt_eval=7, eval_count=5):
    """Fake Ollama NDJSON endpoint; returns a urlopen side_effect."""
    import urllib.request as _ur

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            calls.append(1)
            yield (json.dumps({"message": {"content": text}, "done": False,
                               "prompt_eval_count": prompt_eval,
                               "eval_count": eval_count}) + "\n").encode()
            yield (json.dumps({"message": {"content": ""}, "done": True,
                               "prompt_eval_count": prompt_eval,
                               "eval_count": eval_count}) + "\n").encode()

    def effect(req, timeout=None):
        calls.append(("url", req.full_url))
        return FakeResp()
    return effect


def _fake_sse_urlopen(captured, pieces):
    """Fake SSE endpoint (OpenAI-style); returns a urlopen side_effect."""
    lines = []
    for p in pieces:
        lines.append(b'data: ' + json.dumps(
            {"choices": [{"delta": {"content": p}}]}).encode() + b"\n")
    lines.append(b"data: [DONE]\n")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(lines)

    def effect(req, timeout=None):
        captured["req"] = req
        return FakeResp()
    return effect


class TestStreamChatSections(unittest.TestCase):
    """stream_chat(section=...) - routing, cache and budget integration."""

    def setUp(self):
        _reset_cfg()
        self._env = mock.patch.dict("os.environ", {}, clear=True)
        self._env.start()
        self.ws = Path(tempfile.mkdtemp(prefix="nova_stream_"))
        providers.load_config(self.ws)
        self.sess = nova.Session(self.ws)
        econ.cache_clear(self.ws)

    def tearDown(self):
        self._env.stop()
        _reset_cfg()

    def test_utility_answer_is_cached(self):
        calls = []
        fake = mock.patch.object(nova.urllib.request, "urlopen",
                                 side_effect=_fake_ollama_urlopen(
                                     calls, "compact summary text"))
        msgs = [{"role": "user", "content": "summarize this please"}]
        with fake:
            a1, ok1 = nova.stream_chat(self.sess.model, msgs, 0.2,
                                       sess=self.sess, section="utility")
        self.assertEqual(a1, "compact summary text")
        self.assertTrue(ok1)
        n_first = len(calls)
        # same prompt again -> served from the LOCAL cache, zero requests
        with fake:
            a2, ok2 = nova.stream_chat(self.sess.model, msgs, 0.2,
                                       sess=self.sess, section="utility")
        self.assertEqual(a2, "compact summary text")
        self.assertEqual(len(calls), n_first,
                         "a cached utility call must not hit the network")
        st = econ.stats(self.ws)
        self.assertEqual(st["counters"]["cache_hits"], 1)
        self.assertEqual(st["counters"]["requests_saved"], 1)
        self.assertGreater(st["counters"]["tokens_saved"], 0)

    def test_coding_section_is_never_cached(self):
        calls = []
        fake = mock.patch.object(nova.urllib.request, "urlopen",
                                 side_effect=_fake_ollama_urlopen(calls, "answer"))
        msgs = [{"role": "user", "content": "build it"}]
        with fake:
            nova.stream_chat(self.sess.model, msgs, 0.4, sess=self.sess)
        with fake:
            nova.stream_chat(self.sess.model, msgs, 0.4, sess=self.sess)
        self.assertEqual(len(calls), 4,
                         "coding turns must always be fresh (2 requests)")

    def test_budget_blocks_before_request(self):
        providers.set_economy(self.ws, {"daily_budget_usd": 1.0})
        # record enough spend for today via the real ledger
        nova.nova_cost.record(self.ws, "openai", "gpt-4o", 5_000_000, 1_000_000,
                              actual=True)
        blocked = []
        real_stream = nova.providers.stream_chunks

        def guard(*a, **k):
            blocked.append(1)
            return real_stream(*a, **k)

        # the active brain is ollama (free) - switch the session to openai
        self.sess.model = "gpt-4o"
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-x"}):
            providers.set_provider("openai")
            with mock.patch.object(nova.providers, "stream_chunks", side_effect=guard):
                answer, ok = nova.stream_chat(self.sess.model,
                                              [{"role": "user", "content": "hi"}],
                                              0.2, sess=self.sess)
        self.assertEqual((answer, ok), ("", False))
        self.assertEqual(blocked, [], "a blocked request must never reach the provider")
        self.assertEqual(econ.stats(self.ws)["counters"]["blocked"], 1)

    def test_talk_routing_uses_the_routed_brain(self):
        providers.set_key(self.ws, "groq", "gsk-routed")
        providers.set_route(self.ws, "talk", "groq/llama-3.3-70b-versatile")
        captured = {}
        fake = mock.patch.object(
            nova.urllib.request, "urlopen",
            side_effect=_fake_sse_urlopen(captured, ["hi from groq"]))
        self.sess.model = "somewhere-else:7b"
        with fake:
            answer, ok = nova.stream_chat(self.sess.model,
                                          [{"role": "user", "content": "hello"}],
                                          0.7, sess=self.sess, section="talk")
        self.assertEqual(answer, "hi from groq")
        self.assertTrue(ok)
        url = captured["req"].full_url
        self.assertTrue(url.startswith("https://api.groq.com/openai/v1/chat/completions"))
        auth = captured["req"].headers.get("Authorization")
        self.assertEqual(auth, "Bearer gsk-routed")
        body = json.loads(captured["req"].data)
        self.assertEqual(body["model"], "llama-3.3-70b-versatile")
        self.assertEqual(body["max_tokens"], 1024, "the talk output cap applies")

    def test_bad_route_falls_back_to_active_brain(self):
        providers.set_route(self.ws, "talk", "openai/m1")   # no key -> unusable
        self.sess.model = "some-ollama-model"
        calls = []
        fake = mock.patch.object(nova.urllib.request, "urlopen",
                                 side_effect=_fake_ollama_urlopen(calls, "local answer"))
        with fake:
            answer, ok = nova.stream_chat(self.sess.model,
                                          [{"role": "user", "content": "hello"}],
                                          0.7, sess=self.sess, section="talk")
        self.assertEqual(answer, "local answer")
        self.assertTrue(ok)
        urls = [c[1] for c in calls if isinstance(c, tuple)]
        self.assertTrue(urls and urls[0].startswith("http://localhost:11434"),
                        "the fallback must go to the active (local) brain")


# --------------------------------------------------------------- web helpers
class TestWebProvidersHelpers(unittest.TestCase):
    def setUp(self):
        _reset_cfg()
        self._env = mock.patch.dict("os.environ", {}, clear=True)
        self._env.start()
        self.ws = Path(tempfile.mkdtemp(prefix="nova_webprov_"))
        providers.load_config(self.ws)
        self.sess = nova.Session(self.ws)

    def tearDown(self):
        self._env.stop()
        _reset_cfg()

    def test_state_never_leaks_full_keys(self):
        providers.set_key(self.ws, "groq", "gsk_SUPER_secret_9999")
        st = nova.web_providers_state(self.sess)
        self.assertNotIn("gsk_SUPER_secret_9999", json.dumps(st))
        g = [p for p in st["providers"] if p["id"] == "groq"][0]
        self.assertTrue(g["key_set"])
        self.assertTrue(g["key_masked"].endswith("9999"))

    def test_state_lists_all_providers_and_sections(self):
        st = nova.web_providers_state(self.sess)
        ids = [p["id"] for p in st["providers"]]
        self.assertIn("ollama", ids)
        self.assertIn("openrouter", ids)
        self.assertEqual([s["id"] for s in st["sections"]],
                         ["coding", "talk", "utility", "council"])

    def test_action_set_key_triggers_discovery(self):
        with mock.patch.object(providers, "discover",
                               return_value=["m1", "m2", "m3"]) as d:
            ok, payload, status = nova.web_providers_action(
                self.sess, {"action": "set_key", "provider": "groq",
                            "key": "gsk_x_1234"})
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertEqual(payload["models_found"], 3)
        d.assert_called_once()

    def test_action_rejects_garbage(self):
        for data, status in (
            ({"action": "set_key", "provider": "nope", "key": "k"}, 404),
            ({"action": "set_key", "provider": "groq", "key": ""}, 400),
            ({"action": "route", "section": "bogus", "target": "groq/m"}, 400),
            ({"action": "route", "section": "talk", "target": "ghost/m"}, 400),
            ({"action": "unknown"}, 400),
            ({"action": "economy", "updates": "nope"}, 400),
        ):
            ok, _payload, got = nova.web_providers_action(self.sess, data)
            self.assertEqual(got, status, f"case {data} -> {got}")

    def test_action_route_and_economy(self):
        ok, payload, status = nova.web_providers_action(
            self.sess, {"action": "route", "section": "utility",
                        "target": "deepseek/deepseek-chat"})
        self.assertTrue(ok)
        self.assertEqual(payload["routing"]["utility"], "deepseek/deepseek-chat")
        ok, _p, _s = nova.web_providers_action(
            self.sess, {"action": "economy",
                        "updates": {"daily_budget_usd": 2.0, "cache": False}})
        self.assertTrue(ok)
        self.assertEqual(providers.economy()["daily_budget_usd"], 2.0)
        self.assertFalse(providers.cache_enabled())

    def test_action_custom_roundtrip(self):
        ok, _p, _s = nova.web_providers_action(
            self.sess, {"action": "custom_add", "name": "myrelay",
                        "base": "https://r.example/v1", "model": "m1"})
        self.assertTrue(ok)
        ok, _p, _s = nova.web_providers_action(
            self.sess, {"action": "custom_del", "name": "myrelay"})
        self.assertTrue(ok)
        self.assertNotIn("myrelay", providers.names())


# --------------------------------------------------------------- version
class TestVersion(unittest.TestCase):
    def test_version_pinned(self):
        self.assertEqual(nova.VERSION, "8.12.0")

    def test_new_commands_registered(self):
        cmds = {t["cmd"] for t in nova.TOOLS if isinstance(t, dict) and "cmd" in t}
        for c in ("/key", "/catalog", "/brain", "/custom", "/saver"):
            self.assertIn(c, cmds)


if __name__ == "__main__":
    unittest.main()
