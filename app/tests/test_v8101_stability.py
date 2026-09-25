#!/usr/bin/env python3
"""v8.11.0 tests: THE STABILITY SWEEP regression net.

Every fix ships with the test that proves it - the v8.7 law. This file
pins the seventeen bugs found in the word-by-word sweep:

  A1  nova.py auto-continue: without a think module (or when extract()
      raises) the merged RAW answer is the truth - the continuation tail
      alone used to win and the first chunk's files vanished silently
  A2  nova.py parse_files salvage: an INDENTED complete === FILE: block
      was re-parsed by the salvage path (duplicate entry + false [fix])
  A3  nova.py /undo: the snapshot path now clears sess.last_batch (the
      legacy fallback used to resurrect stale backups afterwards)
  S1  nova.py set_workspace resets the one-shot repair contexts
  S3  nova.py /services call: an unbalanced quote is a usage hint
  B1  nova_guardian: `if [[ ` is valid bash (the pattern backtracked
      through the double bracket and rejected healthy batches)
  B4  nova_guardian: ${#var} - '#' is a length operator, not a comment
  B5  nova_guardian: the 'gxx' registry key resolves the g++ binary
  B7  nova_guardian scan_tags: inline script newlines survive (line
      numbers after a multi-line script were N lines too small)
  B8  nova_guardian: the tool subprocess decodes utf-8 (locale codec
      crashed on Persian tool output and the verdict was lost)
  B2  nova_probe: querySelector("tag") is a tag selector, not an id
  B3  nova_probe: `from . import X` resolves X.py in the anchor dir
  -   nova_probe _script_candidates: parent hops resolve via normpath
  -   nova_probe findings_summary: completeness-review gaps are advisory
  B6  nova_vision: qwen2-vl / qwen2.5-vl match the fallback name regex
  -   nova_vision load_settings: custom = bool(saved) (v8.7 law)
  C1  web_server /api/info: the four state blocks ship DICTS
      (_state_safe) - _flag_safe's bool() silently disabled the guardian
      /probe/vision/compaction the first time a user hit Save
  C2  web index.html: the todo / changes panels are shown explicitly
      (style.display="" never beats the stylesheet's display:none)
  C3  web_server _same_origin: a malformed origin port is a clean False
  D1  nova_security AttemptThrottle: lazy prune keeps RAM flat
  D2  nova_modules/flow.py: the http step fetches through the pinned
      SSRF stack (plain urlopen re-resolved DNS after the safe_url check)
  D3  nova_quality: a comments-only CSS sheet passes preapply
  D5  nova_intel: a hostile ts never crashes recall / _decisions_block
  -   nova_design parse_layers: the contract's own range grammar
      (shadow=1..5) declares the layer at level 0
  -   nova_subagent: NOVA_AGENTS=1 is honored (serial), not floored to 2

Everything offline-deterministic.
"""
import contextlib
import io
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_guardian as guardian  # noqa: E402
import nova_probe as probe  # noqa: E402
import nova_vision as vision  # noqa: E402
import nova_quality  # noqa: E402
import nova_security  # noqa: E402
import nova_design  # noqa: E402
import nova_intel  # noqa: E402
import nova_subagent  # noqa: E402
import web_server  # noqa: E402


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield


def _src(rel):
    return (Path(__file__).resolve().parent.parent / rel).read_text(
        encoding="utf-8")


# --------------------------------------------------------------- nova.py
class TestAutoContinueKeepsTheRawTruth(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sess = nova.Session(Path(self._tmp.name))
        self._old_sink = nova.EVENT_SINK
        nova.EVENT_SINK = []
        self._old_hard = nova._LAST_STREAM_HARD
        nova._LAST_STREAM_HARD = False
        self._env = mock.patch.dict(
            "os.environ", {"NOVA_GUARDIAN": "0", "NOVA_PROBE": "0"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        nova.EVENT_SINK = self._old_sink
        nova._LAST_STREAM_HARD = self._old_hard
        self._tmp.cleanup()

    def test_think_module_missing_tail_never_wins(self):
        seq = ["=== FILE: a.py ===\nprint('part one')\n",
               "=== END ===\nPreview: a.py"]

        def fake(model, messages, temperature, sess=None, section=None,
                 quiet=False):
            if len(seq) > 1:
                return seq.pop(0), False
            return seq[0], True

        with mock.patch.object(nova, "think", None), \
                mock.patch.object(nova, "stream_chat", side_effect=fake), \
                _quiet():
            res = nova.chat_turn(self.sess, "بساز", auto=True)
        self.assertIn("print('part one')", res["answer"],
                      "the merged RAW answer is the truth")
        self.assertIn("a.py", res["files"])
        hist = "".join(str(m) for m in self.sess.history[-1:])
        self.assertIn("part one", hist, "history carries the full answer")

    def test_extract_failure_falls_back_to_raw(self):
        seq = ["=== FILE: a.py ===\nx = 1\n",
               "=== END ===\n"]

        def fake(model, messages, temperature, sess=None, section=None,
                 quiet=False):
            if len(seq) > 1:
                return seq.pop(0), False
            return seq[0], True

        exploding = mock.Mock()
        exploding.extract = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(nova, "think", exploding), \
                mock.patch.object(nova, "stream_chat", side_effect=fake), \
                _quiet():
            res = nova.chat_turn(self.sess, "بساز", auto=True)
        self.assertIn("x = 1", res["answer"])

    def test_think_present_behavior_unchanged(self):
        first = "=== THINK ===\nlet me plan the cafe step by"
        second = ("step\n=== END ===\n=== FILE: index.html ===\n"
                  "<h1>کافه</h1>\n=== END ===\nPreview: index.html")
        seq = [first, second]

        def fake(model, messages, temperature, sess=None, section=None,
                 quiet=False):
            if len(seq) > 1:
                return seq.pop(0), False
            return seq[0], True

        with mock.patch.object(nova, "stream_chat", side_effect=fake), \
                _quiet():
            res = nova.chat_turn(self.sess, "بساز", auto=True)
        self.assertIn("index.html", res["files"])
        self.assertIn("let me plan", res.get("think") or "")


class TestIndentedFileBlock(unittest.TestCase):
    def test_indented_complete_block_parses_once(self):
        files, _unnamed = nova.parse_files(
            "  === FILE: a.py ===\nprint(1)\n  === END ===\n",
            run_hints=[])
        self.assertEqual(files, [("a.py", "print(1)")])

    def test_indented_unclosed_block_still_salvaged(self):
        files, _unnamed = nova.parse_files(
            "  === FILE: b.py ===\nprint(2)\n", run_hints=[])
        self.assertEqual(files, [("b.py", "print(2)")])


class TestUndoSnapshotClearsLegacyBatch(unittest.TestCase):
    def test_undo_source_clears_last_batch_on_snapshot_path(self):
        src = _src("nova.py")
        self.assertIn("sess.last_batch = []", src)
        # the clear sits INSIDE the snapshot-undo branch (before the
        # legacy fallback), right after `if res["undone"]:`
        i = src.find('if res["undone"]:')
        j = src.find("# legacy fallback")
        self.assertTrue(0 < i < j)
        self.assertIn("sess.last_batch = []", src[i:j])


class TestWorkspaceResetsRepairContexts(unittest.TestCase):
    def test_set_workspace_resets_repairs(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sess = nova.Session(Path(tmp.name))
            sess.guardian_repair = "GUARDIAN: fix project A"
            sess.probe_repair = "BUG HUNTER: fix project A"
            with _quiet():
                sess.set_workspace(Path(tempfile.mkdtemp()))
            self.assertIsNone(sess.guardian_repair)
            self.assertIsNone(sess.probe_repair)
        finally:
            tmp.cleanup()


# ------------------------------------------------------------- guardian
class TestGuardianShellPatterns(unittest.TestCase):
    def test_double_bracket_is_valid_bash(self):
        res = guardian.validate(
            "tool.sh",
            "#!/usr/bin/env bash\nif [[ -f config ]]; then\n"
            "  source config\nfi\n")
        self.assertEqual(res["errors"], [])

    def test_single_bracket_no_space_still_caught(self):
        res = guardian.validate(
            "tool.sh", "#!/usr/bin/env bash\nif [-f config]; then\nfi\n")
        self.assertTrue(any("missing space" in e[1] for e in res["errors"]))

    def test_param_length_operator_is_not_a_comment(self):
        res = guardian.validate("tool.zsh",
                                "#!/bin/zsh\nlen=${#var}\necho $len\n")
        self.assertEqual(res["errors"], [])

    def test_nested_param_expansion_balances(self):
        res = guardian.validate(
            "tool.zsh",
            "#!/bin/zsh\nn=$((${#a}+${#b}))\necho $n\n")
        self.assertEqual(res["errors"], [])

    def test_gxx_key_resolves_gxx_or_gxx_fallbacks(self):
        lookup = guardian._which.__defaults__  # none - inspect via behavior
        import shutil
        has_any = shutil.which("gxx") or shutil.which("g++")
        if has_any:
            self.assertIn("gxx", guardian.tools_available())
        else:
            self.assertNotIn("gxx", guardian.tools_available())

    def test_tool_subprocess_decodes_utf8(self):
        src = _src("nova_guardian.py")
        self.assertIn('encoding="utf-8", errors="replace"', src)

    def test_scan_tags_preserves_script_newlines(self):
        html = ('<html>\n<body>\n<script>\nvar a = 1;\nvar b = 2;\n'
                '</script>\n<h1>after</h1>\n<div>\n<span>oops\n'
                '</body>\n</html>\n')
        errors, _warns = guardian.scan_tags(html, "index.html")
        # the script has 2 body lines + 2 fence lines = 4 shifted lines;
        # <span> sits on line 8 and the report must say so
        self.assertTrue(any("line 8" in e[1] for e in errors), errors)


# --------------------------------------------------------------- probe
class TestProbeSelectors(unittest.TestCase):
    HTML = ('<html><body><form id="main"><button>go</button></form>'
            '<script src="app.js"></script></body></html>')

    def test_tag_selector_is_not_a_dead_id(self):
        js = ('document.querySelector("form").addEventListener('
              '"submit", function(){});\n'
              'document.querySelectorAll("button").forEach(function(b){});')
        r = probe.wiring_check([("index.html", self.HTML),
                                ("app.js", js)])
        self.assertEqual(r["errors"], [])

    def test_dead_id_still_caught(self):
        r = probe.wiring_check([("app.js",
                                 'document.querySelector("#ghost");')])
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("#ghost", r["errors"][0][2])

    def test_get_element_by_id_raw_form_still_tracked(self):
        r = probe.wiring_check([("app.js",
                                 'document.getElementById("ghost2");')])
        self.assertTrue(any("#ghost2" in e[2] for e in r["errors"]))

    def test_bare_relative_import_resolves_sibling(self):
        r = probe.wiring_check([
            ("pkg/main.py", "from . import utils\nutils.go()\n"),
            ("pkg/utils.py", "def go():\n    return 1\n")])
        self.assertEqual(r["errors"], [])

    def test_bare_relative_import_missing_still_caught(self):
        r = probe.wiring_check([
            ("pkg/main.py", "from . import missing_m\nmissing_m.go()\n"),
            ("pkg/utils.py", "x = 1\n")])
        self.assertTrue(any("not found" in e[2] for e in r["errors"]))

    def test_script_candidates_parent_hop(self):
        cands = probe._script_candidates("sub", "../app.js")
        self.assertIn("app.js", cands)
        cands2 = probe._script_candidates("a/b", "../../lib/x.js")
        self.assertIn("lib/x.js", cands2)

    def test_review_gaps_are_advisory_warns(self):
        rep = {"wiring": {}, "static": {}, "smoke": {}, "browser": {},
               "review": {"gaps": [("footer", "no contact info")]}}
        flat = probe.findings_summary(rep)
        self.assertTrue(flat)
        self.assertTrue(all(lv == "warn" for _f, _l, _m, lv in flat))


# --------------------------------------------------------------- vision
class TestVision(unittest.TestCase):
    def test_qwen_dash_vl_names_match(self):
        for name in ("qwen2-vl:7b", "qwen2.5-vl:3b", "qwen3-vl",
                     "qwen2vl:7b", "qwen-vl"):
            self.assertTrue(vision.NAME_RE.search(name), name)

    def test_non_vision_qwen_stays_text_only(self):
        for name in ("qwen2-coder:7b", "qwen-max", "qwen2:7b"):
            self.assertFalse(vision.NAME_RE.search(name), name)

    def test_load_settings_custom_requires_saved_fields(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".nova").mkdir()
        (tmp / ".nova" / vision.VISION_FILE).write_text(
            '{"junk": true}\n', encoding="utf-8")
        s = vision.load_settings(tmp)
        self.assertFalse(s.get("custom"))


# ------------------------------------------------------------------ web
class TestWebSurface(unittest.TestCase):
    def test_info_states_ship_dicts(self):
        src = _src("web_server.py")
        self.assertIn("_state_safe(nova.web_ctx_state, sess)", src)
        self.assertIn("_state_safe(nova.web_guardian_state, sess)", src)
        self.assertIn("_state_safe(nova.web_probe_state, sess)", src)
        self.assertIn("_state_safe(nova.web_vision_state, sess)", src)

    def test_state_safe_returns_none_on_failure(self):
        self.assertIsNone(web_server._state_safe(lambda: 1 / 0))
        self.assertEqual(web_server._state_safe(lambda: {"a": 1}), {"a": 1})

    def test_same_origin_malformed_port_is_false(self):
        class H:
            def __init__(self):
                self.headers = {"Origin": "http://127.0.0.1:abc",
                                "Host": "127.0.0.1:8765"}

        self.assertFalse(web_server._same_origin(H()))

    def test_same_origin_valid_still_true(self):
        class H:
            def __init__(self):
                self.headers = {"Origin": "http://127.0.0.1:8765",
                                "Host": "127.0.0.1:8765"}

        self.assertTrue(web_server._same_origin(H()))

    def test_panels_shown_explicitly(self):
        html = _src("web/index.html")
        self.assertIn('panel.style.display = "block";', html)
        self.assertIn('cp.style.display = "block"', html)

    def test_module_endpoints_guarded(self):
        src = _src("web_server.py")
        for needle in ('path == "/api/assign/clear"',
                       'path == "/api/platforms/scan"',
                       'path == "/api/knowledge/reset"'):
            i = src.find(needle)
            self.assertTrue(i > 0, needle)
            chunk = src[i:i + 700]
            self.assertIn("except Exception", chunk, needle)


# ------------------------------------------------------------ security
class TestSecurity(unittest.TestCase):
    def test_throttle_prunes_stale_entries(self):
        th = nova_security.AttemptThrottle(max_fails=3, window_s=0.05,
                                           lockout_s=0.05)
        th.fail("a")
        th.fail("b")
        th._last_prune = time.monotonic() - 400
        time.sleep(0.06)
        th.check("c")
        self.assertNotIn("a", th._fails)
        self.assertNotIn("b", th._fails)

    def test_throttle_lockout_still_works(self):
        th = nova_security.AttemptThrottle(max_fails=2, window_s=60,
                                           lockout_s=60)
        th.fail("x")
        ok, _ = th.check("x")
        self.assertTrue(ok)
        th.fail("x")
        ok, retry = th.check("x")
        self.assertFalse(ok)
        self.assertGreater(retry, 0)


# ---------------------------------------------------------------- misc
class TestFlowAndQualityAndIntel(unittest.TestCase):
    def test_flow_http_uses_pinned_stack(self):
        src = (_src("nova_modules/flow.py"))
        self.assertIn("http_get_bytes", src)
        # the user-URL http STEP fetches through the pinned stack; the
        # remaining plain urlopen sites are the trusted LLM endpoints
        # (local Ollama base / the configured platform), not user URLs
        i = src.find("def _http(self, st, w):")
        j = src.find("def _condition(self, w):")
        self.assertTrue(0 < i < j)
        self.assertNotIn("urllib.request.urlopen", src[i:j])

    def test_comments_only_css_passes_preapply(self):
        ok, why = nova_quality.preapply_check("style.css",
                                              "/* nothing here */\n")
        self.assertTrue(ok)

    def test_intel_recall_survives_hostile_ts(self):
        tmp = Path(tempfile.mkdtemp())
        m = nova_intel.SemanticMemory(tmp / "mem.json")
        m.records = [{"id": "a", "text": "hello world", "kind": "fact",
                      "tags": [], "tf": {"hello": 1, "world": 1},
                      "ts": "2024-01-01"},
                     {"id": "b", "text": "hello again", "kind": "fact",
                      "tags": [], "tf": {"hello": 1, "again": 1},
                      "ts": 1700000000}]
        hits = m.recall("hello", k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["text"], "hello again")
        self.assertEqual(hits[0]["ts"], 1700000000)

    def test_subagent_env_one_is_serial(self):
        with mock.patch.dict("os.environ", {"NOVA_AGENTS": "1"}), \
                _quiet():
            res = nova_subagent.run_parallel(
                ["t1", "t2"], lambda t: t.upper())
        self.assertEqual([r[1] for r in res], ["T1", "T2"])

    def test_design_range_grammar_declares_level_zero(self):
        spec = nova_design.parse_layers(
            "shadow=1..5; glass=1..4; grain=1..4; neon=1..3; "
            "aurora=1..3; motion=float,fade-down,fade-up,slide-in,"
            "pop,glow|all")
        for k in ("shadow", "glass", "grain", "neon", "aurora"):
            self.assertEqual(spec[k], 0, k)
        self.assertTrue(spec["motion"])
        sheet = nova_design.layers_css(spec)
        self.assertTrue(sheet)

    def test_design_sane_grammar_unchanged(self):
        spec = nova_design.parse_layers("shadow=2; motion=float")
        self.assertEqual(spec["shadow"], 2)
        self.assertEqual(spec["motion"], {"float"})


# ------------------------------------------------------ release pins
class TestReleasePins(unittest.TestCase):
    def test_version_and_codename(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(nova.CODENAME, "master switch")
        import nova_think
        self.assertEqual(nova_think.VERSION, "8.12.0")

    def test_fix_markers_present(self):
        # the 8.10.1 release left "v8.10.1 fix" markers in every module
        # it touched - and the 8.11.0 release ("master switch")
        # touched a DIFFERENT subset; both marker families must survive
        untouched_by_8110 = ("nova_vision.py", "nova_security.py",
                             "nova_intel.py", "nova_memory.py",
                             "nova_subagent.py", "nova_iran_services.py",
                             "nova_modules/flow.py")
        for f in untouched_by_8110:
            self.assertIn("v8.10.1", _src(f), f)
        touched_by_8110 = ("nova.py", "web_server.py", "nova_guardian.py",
                           "nova_probe.py", "nova_quality.py",
                           "nova_design.py", "nova_ctxengine.py",
                           "nova_think.py", "nova_router.py")
        for f in touched_by_8110:
            self.assertIn("v8.11", _src(f), f)


if __name__ == "__main__":
    unittest.main(verbosity=1)
