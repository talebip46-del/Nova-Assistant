#!/usr/bin/env python3
# =====================================================================
#  Nova v8.11.0 "context engine" regression tests:
#   - nova_ctxengine: per-backend windows (local vs cloud, SEPARATE),
#     user-saved settings override the runtime defaults, validation
#     never trusts a hand-edited file, invalid updates never clobber
#     good stored values.
#   - the smart digest: newest messages verbatim, old block folded
#     (goals / file paths / commands / decisions kept), three
#     escalating modes, deterministic and offline (no model call).
#   - nova.py integration: the session windows are the law for
#     _prompt_ctx / num_ctx / llama-server -c, auto-compact after a
#     turn, digest before the brutal trim ladder.
#   - the web surface: /api/info ctx block, /api/settings ctx fields,
#     the Models-tab panel ids.
#  Everything is offline.
# =====================================================================
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova                    # noqa: E402
import nova_ctxengine as ce    # noqa: E402
import nova_think              # noqa: E402

APP = Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _pair(u, a):
    return [{"role": "user", "content": u}, {"role": "assistant", "content": a}]


class TestEngineSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self._env = {k: os.environ.pop(k, None)
                     for k in ("NOVA_NUM_CTX", "NOVA_CLOUD_CTX")}

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v

    def test_defaults_and_not_custom(self):
        s = ce.load_settings(self.ws)
        self.assertFalse(s["custom"])
        self.assertEqual(s["local_ctx"], 4096)
        self.assertEqual(s["cloud_ctx"], 16384)
        self.assertTrue(s["auto_compact"])
        self.assertEqual(s["compact_threshold"], 0.85)
        self.assertEqual(s["keep_recent"], 4)

    def test_env_overrides_defaults(self):
        os.environ["NOVA_NUM_CTX"] = "2048"
        os.environ["NOVA_CLOUD_CTX"] = "8192"
        s = ce.load_settings(self.ws)
        self.assertEqual(s["local_ctx"], 2048)
        self.assertEqual(s["cloud_ctx"], 8192)

    def test_env_typo_never_crashes(self):
        os.environ["NOVA_NUM_CTX"] = "abc"
        self.assertEqual(ce.load_settings(self.ws)["local_ctx"], 4096)

    def test_save_load_roundtrip_is_custom(self):
        self.assertEqual(ce.save_settings(
            self.ws, {"local_ctx": 8192, "cloud_ctx": 100_000}), "")
        s = ce.load_settings(self.ws)
        self.assertTrue(s["custom"])
        self.assertEqual(s["local_ctx"], 8192)
        self.assertEqual(s["cloud_ctx"], 100_000)
        # the file lives where the map says it does
        self.assertTrue((self.ws / ".nova" / "context.json").is_file())

    def test_invalid_update_never_clobbers_stored_values(self):
        ce.save_settings(self.ws, {"local_ctx": 8192,
                                   "compact_threshold": 0.7})
        # v8.11: an update with ZERO valid fields is refused outright -
        # the old write-anyway path stored a defaults file whose valid
        # keys then claimed custom=True and froze the env windows
        err = ce.save_settings(
            self.ws, {"local_ctx": 10**9, "compact_threshold": 0.01,
                      "keep_recent": 1, "auto_compact": "yes",
                      "hacker": True})
        self.assertTrue(err, "an all-invalid save must return an error")
        s = ce.load_settings(self.ws)
        self.assertEqual(s["local_ctx"], 8192)
        self.assertEqual(s["compact_threshold"], 0.7)
        self.assertEqual(s["keep_recent"], 4)
        self.assertTrue(s["auto_compact"])
        self.assertNotIn("hacker", s)

    def test_bounds(self):
        self.assertEqual(ce.LOCAL_MIN, 512)
        self.assertEqual(ce.CLOUD_MIN, 2048)
        ce.save_settings(self.ws, {"local_ctx": ce.LOCAL_MIN,
                                   "cloud_ctx": ce.CLOUD_MIN,
                                   "compact_threshold": ce.THRESHOLD_MIN,
                                   "keep_recent": ce.KEEP_MIN})
        s = ce.load_settings(self.ws)
        self.assertEqual((s["local_ctx"], s["cloud_ctx"],
                          s["compact_threshold"], s["keep_recent"]),
                         (512, 2048, 0.5, 2))
        ce.save_settings(self.ws, {"local_ctx": ce.LOCAL_MAX,
                                   "cloud_ctx": ce.CLOUD_MAX,
                                   "compact_threshold": ce.THRESHOLD_MAX,
                                   "keep_recent": ce.KEEP_MAX})
        s = ce.load_settings(self.ws)
        self.assertEqual((s["local_ctx"], s["cloud_ctx"],
                          s["compact_threshold"], s["keep_recent"]),
                         (262_144, 4_000_000, 0.95, 16))

    def test_corrupted_file_falls_back(self):
        ce.save_settings(self.ws, {"local_ctx": 8192})
        (self.ws / ".nova" / "context.json").write_text("{broken", encoding="utf-8")
        s = ce.load_settings(self.ws)
        self.assertFalse(s["custom"])
        self.assertEqual(s["local_ctx"], 4096)

    def test_oversized_file_ignored(self):
        p = self.ws / ".nova" / "context.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"local_ctx": 9999}) + " " + "x" * 9000,
                     encoding="utf-8")
        self.assertFalse(ce.load_settings(self.ws)["custom"])

    def test_reset(self):
        ce.save_settings(self.ws, {"local_ctx": 8192})
        self.assertEqual(ce.reset_settings(self.ws), "")
        self.assertFalse(ce.load_settings(self.ws)["custom"])


class TestEngineCompress(unittest.TestCase):
    def _filler_pair(self, i):
        """One realistic pair: lots of raw text, few durable facts
        (exactly what the digest must compress hard)."""
        return _pair(
            "Fix the bug in src/app%d.py please and run `npm test`\n" % i
            + "filler chat that adds no durable value " * 8,
            "=== FILE: src/app%d.py ===\n=== END ===\n" % i
            + "Decision: we use bcrypt for hashing\n"
            + "narration of the obvious " * 6)

    def _big_history(self, pairs=6):
        h = []
        for i in range(pairs):
            h += self._filler_pair(i)
        return h

    def test_under_budget_untouched(self):
        h = self._big_history(3)
        new, st = ce.compress_history(h, 100_000, keep_recent=4)
        self.assertFalse(st["changed"])
        self.assertEqual(new, h)

    def test_digest_keeps_recent_verbatim(self):
        h = self._big_history(8) + _pair("quick check", "done")
        new, st = ce.compress_history(h, 1200, keep_recent=2)
        self.assertTrue(st["changed"])
        self.assertEqual(st["mode"], "digest")
        self.assertEqual(new[1:], h[-2:])
        self.assertIn(ce._DIGEST_MARK, new[0]["content"])
        # the useful facts survived the fold
        body = new[0]["content"]
        self.assertIn("src/app", body)
        self.assertIn("npm test", body)
        self.assertIn("bcrypt", body)

    def test_digest_dedupes_repeated_paths(self):
        # _pair(...) * 4 is ALREADY a flat list of dicts - no re-flatten
        # (iterating a dict yields its KEYS, which would poison the list)
        h = _pair("do it\nsee logs/x.log for details",
                  "done, no findings") * 4
        new, st = ce.compress_history(h, 60, keep_recent=2)
        self.assertTrue(st["changed"])
        body = new[0]["content"]
        self.assertEqual(body.count("x.log"), 1, body)

    def test_tight_mode_when_digest_too_roomy(self):
        h = []
        for i in range(5):
            paths = " ".join("dir%d/unique_file_%d_%d.py" % (i, i, j)
                             for j in range(6))
            h += _pair("goal %d\n%s" % (i, paths),
                       "wrote %d\n%s" % (i, paths))
        h += _pair("tiny", "ok")
        new, st = ce.compress_history(h, 120, keep_recent=2)
        self.assertTrue(st["changed"])
        self.assertEqual(st["mode"], "tight")
        self.assertEqual(new[1:], h[-2:])

    def test_drop_mode_keeps_recent_only(self):
        h = self._big_history(6)
        new, st = ce.compress_history(h, 40, keep_recent=4)
        self.assertTrue(st["changed"])
        self.assertEqual(st["mode"], "drop")
        self.assertEqual(new[1:], h[-4:])

    def test_short_and_empty_history_untouched(self):
        for h in ([], self._big_history(1), self._big_history(2)[:4]):
            new, st = ce.compress_history(h, 10, keep_recent=4)
            self.assertFalse(st["changed"])

    def test_compression_actually_shrinks(self):
        h = self._big_history(8)
        before = sum(ce.est_tokens(m["content"]) for m in h)
        new, st = ce.compress_history(h, 1000, keep_recent=2)
        after = sum(ce.est_tokens(m["content"]) for m in new)
        self.assertTrue(st["changed"])
        self.assertLess(after, before)
        self.assertLessEqual(after, st["tokens_after"] + 1)
        self.assertEqual(st["tokens_before"], before)

    def test_non_dict_entries_tolerated(self):
        h = ["junk", 42, {"role": "user", "content": "x"}]
        new, st = ce.compress_history(h, 10_000, keep_recent=2)
        self.assertFalse(st["changed"])


class TestSessionIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.sess = nova.Session(self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_session_uses_global_defaults(self):
        local, cloud = self.sess._ctx_wins()
        self.assertEqual(local, nova.NUM_CTX)
        self.assertEqual(cloud, max(2048, nova._envint("NOVA_CLOUD_CTX", 16384)))
        self.assertEqual(self.sess._effective_num_ctx(), nova.NUM_CTX)

    def test_custom_settings_are_the_law(self):
        self.assertEqual(ce.save_settings(
            self.ws, {"local_ctx": 8192, "cloud_ctx": 200_000}), "")
        self.sess.ctx_settings = ce.load_settings(self.ws)
        local, cloud = self.sess._ctx_wins()
        self.assertEqual((local, cloud), (8192, 200_000))
        self.assertEqual(self.sess._effective_num_ctx(), 8192)
        # the numbers survive even when the global says otherwise
        old = nova.NUM_CTX
        try:
            nova.NUM_CTX = 1024
            self.assertEqual(self.sess._effective_num_ctx(), 8192)
        finally:
            nova.NUM_CTX = old

    def test_prompt_ctx_local_and_cloud_separate(self):
        ce.save_settings(self.ws, {"local_ctx": 8192, "cloud_ctx": 200_000})
        self.sess.ctx_settings = ce.load_settings(self.ws)
        old_prov, old_cfg = nova.providers, nova._provider_cfg
        nova.providers = None
        nova._provider_cfg = lambda: {"kind": "ollama", "name": "ollama"}
        try:
            self.assertEqual(self.sess._prompt_ctx(), 8192)     # local brain
            nova._provider_cfg = lambda: {"kind": "openai",
                                          "name": "groq",
                                          "base": "https://api.groq.com/v1"}
            self.assertEqual(self.sess._prompt_ctx(), 200_000)  # cloud brain
        finally:
            nova.providers, nova._provider_cfg = old_prov, old_cfg

    def test_prompt_ctx_follows_coding_route(self):
        import types
        ce.save_settings(self.ws, {"local_ctx": 8192, "cloud_ctx": 250_000})
        self.sess.ctx_settings = ce.load_settings(self.ws)
        stub = types.SimpleNamespace(resolve_route=lambda s: (
            {"kind": "groq"}, "m") if s == "coding" else (None, ""))
        old = nova.providers
        nova.providers = stub
        try:
            self.assertEqual(self.sess._prompt_ctx(), 250_000)
        finally:
            nova.providers = old

    def test_build_messages_digests_instead_of_blind_trim(self):
        ce.save_settings(self.ws, {"local_ctx": 6144, "keep_recent": 2})
        self.sess.ctx_settings = ce.load_settings(self.ws)
        self.sess.history = self._big_history(8)
        msgs = self.sess.build_messages("continue please")
        joined = "\n".join(str(m.get("content", "")) for m in msgs)
        self.assertIn("compact digest", joined)
        # everything fits the window
        win = self.sess._prompt_ctx()
        used = sum(nova._est_tokens(str(m.get("content", ""))) for m in msgs)
        self.assertLessEqual(used, win)
        # the newest pair survived verbatim
        self.assertEqual(msgs[-3:-1], self.sess.history[-2:])

    def test_maybe_ctx_compact_after_turn(self):
        ce.save_settings(self.ws, {"local_ctx": 2048,
                                   "auto_compact": True})
        self.sess.ctx_settings = ce.load_settings(self.ws)
        self.sess.history = self._big_history(8)
        self.sess.transcript = []
        used_before = self.sess._ctx_used_tokens()
        self.assertGreater(used_before, int(2048 * 0.85))
        self.sess._maybe_ctx_compact()
        self.assertLess(self.sess._ctx_used_tokens(), used_before)
        self.assertIn("compact digest", self.sess.history[0]["content"])
        # the newest four messages stayed verbatim
        self.assertEqual(self.sess.history[-4:], self._big_history(8)[-4:])

    def test_maybe_ctx_compact_respects_auto_off(self):
        ce.save_settings(self.ws, {"local_ctx": 2048, "auto_compact": False})
        self.sess.ctx_settings = ce.load_settings(self.ws)
        self.sess.history = self._big_history()
        before = list(self.sess.history)
        self.sess._maybe_ctx_compact()
        self.assertEqual(self.sess.history, before)

    def test_maybe_ctx_compact_idle_under_threshold(self):
        self.sess.history = _pair("small", "answer")
        before = list(self.sess.history)
        self.sess._maybe_ctx_compact()
        self.assertEqual(self.sess.history, before)

    def _big_history(self, pairs=8):
        h = []
        for i in range(pairs):
            h += _pair("build feature %d in src/mod%d.py\n%s"
                       % (i, i, "more chatter to inflate the window " * 10),
                       "=== FILE: src/mod%d.py ===\n=== END ===\n"
                       "decision: use queue %d\n%s"
                       % (i, i, "step by step narration " * 8))
        return h


class TestStreamChatNumCtx(unittest.TestCase):
    """the Ollama payload must carry the SESSION's window - Nova's law
    overrides whatever default Ollama picked for the model."""

    class _FakeResp:
        def __init__(self, lines):
            self._lines = lines

        def __iter__(self):
            return iter(self._lines)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _run_stream(self, sess):
        captured = {}
        real_urlopen = nova.urllib.request.urlopen

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(
                req.data.decode("utf-8"))
            return self._FakeResp([
                json.dumps({"message": {"content": "hi"},
                            "done": False}).encode("utf-8"),
                json.dumps({"message": {"content": ""},
                            "done": True}).encode("utf-8"),
            ])

        nova.urllib.request.urlopen = fake_urlopen
        olds = (nova.providers, nova.econ, nova.lmodels, nova.nova_cost,
                nova._provider_cfg, nova.TOKEN_SINK)
        nova.providers = None
        nova.econ = None
        nova.lmodels = None
        nova.nova_cost = None
        nova._provider_cfg = lambda: {"kind": "ollama", "name": "ollama",
                                      "model": "fake"}
        nova.TOKEN_SINK = None
        try:
            text, complete = nova.stream_chat("fake", [{"role": "user",
                                                        "content": "x"}],
                                               0.4, sess=sess, quiet=True)
        finally:
            nova.urllib.request.urlopen = real_urlopen
            (nova.providers, nova.econ, nova.lmodels, nova.nova_cost,
             nova._provider_cfg, nova.TOKEN_SINK) = olds
        self.assertEqual(text, "hi")
        self.assertTrue(complete)
        return captured["payload"]

    def test_session_window_wins(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.ctx_settings = {"custom": True, "local_ctx": 8192,
                                 "cloud_ctx": 100_000, "auto_compact": True,
                                 "compact_threshold": 0.85, "keep_recent": 4}
            payload = self._run_stream(sess)
        self.assertEqual(payload["options"]["num_ctx"], 8192)

    def test_no_session_keeps_global_default(self):
        payload = self._run_stream(None)
        self.assertEqual(payload["options"]["num_ctx"], nova.NUM_CTX)


class TestWebSurface(unittest.TestCase):
    def test_web_ctx_state_shape(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            st = nova.web_ctx_state(sess)
        for k in ("local_ctx", "cloud_ctx", "auto_compact", "threshold",
                  "keep_recent", "custom", "backend", "win", "used",
                  "ratio", "history", "bounds"):
            self.assertIn(k, st)
        self.assertEqual(st["local_ctx"], nova.NUM_CTX)
        self.assertFalse(st["custom"])
        self.assertIn("local_min", st["bounds"])

    def test_api_info_exposes_ctx_block(self):
        src = _src("web_server.py")
        self.assertIn('"ctx": _state_safe(nova.web_ctx_state, sess)', src)

    def test_api_settings_accepts_ctx_fields(self):
        src = _src("web_server.py")
        for field in ("ctx_local", "ctx_cloud", "ctx_auto",
                      "ctx_threshold", "ctx_keep", "ctx_reset"):
            self.assertIn(field, src)
        self.assertIn("nova.ctxengine.save_settings", src)
        self.assertIn("nova.ctxengine.reset_settings", src)

    def test_index_has_context_engine_panel(self):
        html = _src("web/index.html")
        for el in ("ctxLocal", "ctxCloud", "ctxThr", "ctxKeep", "ctxAuto",
                   "ctxSave", "ctxReset", "ctxState", "renderCtxPanel"):
            self.assertIn(el, html)
        # the panel posts to the SAME /api/settings endpoint
        self.assertIn('"/api/settings"', html)

    def test_terminal_command_registered(self):
        src = _src("nova.py")
        self.assertIn('"cmd": "/ctxset"', src)
        self.assertIn("def cmd_ctxset", src)
        self.assertIn("def _ctxset_report", src)

    def test_ollama_payload_is_session_aware(self):
        src = _src("nova.py")
        # v8.11: the payload resolves the window through _eff_ctx, and a
        # sess-less caller (draft / explore / reviewer) may carry the
        # session's window explicitly via the num_ctx keyword
        self.assertIn('"num_ctx": (num_ctx or _eff_ctx(sess))', src)
        self.assertIn("def _eff_ctx(sess):", src)
        self.assertIn("def stream_chat(model, messages, temperature, sess=None, "
                      "section=None,\n                quiet=False, num_ctx=None):",
                      src)
        # llama-server gets the same law via its -c flag
        self.assertIn("ctx=(sess._effective_num_ctx() if sess is not None else NUM_CTX)",
                      _src("nova.py"))

    def test_status_and_help_mention_ctxset(self):
        src = _src("nova.py")
        self.assertIn("/ctxset", src)
        self.assertIn("ctx local {ctx_local}/cloud {ctx_cloud}", src)


class TestVersionPins(unittest.TestCase):
    def test_core_versions_are_830(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(nova_think.VERSION, "8.12.0")

    def test_codename_pin(self):
        # v8.5 moved the codename to "bug hunter" - the ctxengine
        # FEATURE tests below stay valid; only the codename pin moved.
        # v8.6 moved the codename to "bug net + vision" - the ctxengine
        # law (separate local/cloud windows) is untouched by that
        self.assertEqual(nova.CODENAME, "master switch")
        self.assertNotEqual(nova.CODENAME, "context engine")

    def test_engine_module_header(self):
        head = _src("nova_ctxengine.py").splitlines()[:8]
        self.assertTrue(any("CONTEXT ENGINE" in ln for ln in head))


if __name__ == "__main__":
    unittest.main(verbosity=2)
