#!/usr/bin/env python3
"""v6.9.0 tests: "the coding panel delivers broken code / cannot create or
edit multiple files / cannot run code nicely".

Every test here pins one REAL gap found by auditing the coding pipeline
end-to-end (model answer -> parse -> stage/apply -> run):

  - flex_match: === EDIT: === hunks whose SEARCH drifted by trailing
    spaces / indentation are now applied (was: always refused -> "Nova
    cannot edit files"); ambiguous or absent matches are STILL refused
  - hunk_preview / apply_hunks share the same tolerant fallback
  - CSS finally gets pre-apply lint (brace balance) - a truncated
    stylesheet used to ship silently
  - the protocol-repair round: code blocks WITHOUT a === FILE: name ===
    header trigger ONE corrective re-ask instead of vanishing (web used
    to skip them silently -> "Nova cannot create files")
  - build_fix_message: the shared fix prompt for REPL /verify AND the
    web one-round auto-fix after a failed Run click
  - child runs: stdin=DEVNULL (input() programs used to HANG a Run click
    until the wall timeout) + PYTHONUTF8 (Persian output used to crash
    Windows children with UnicodeEncodeError)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_diffview   # noqa: E402
import nova_quality    # noqa: E402


# --------------------------------------------------------------------------
# 1. flex_match - whitespace-tolerant SEARCH matching
# --------------------------------------------------------------------------
class TestFlexMatch(unittest.TestCase):
    def test_exact_hit_still_returns_span(self):
        span = nova_diffview.flex_match("a\nbb\nc", "bb")
        self.assertIsNotNone(span)
        self.assertEqual("a\nbb\nc"[span[0]:span[1]], "bb")

    def test_trailing_space_drift_is_tolerated(self):
        hay = "def main():\n    print('hi')   \n    return 0\n"
        span = nova_diffview.flex_match(hay, "def main():\n  print('hi')\n  return 0")
        self.assertIsNotNone(span)
        self.assertEqual(hay[span[0]:span[1]],
                         "def main():\n    print('hi')   \n    return 0")

    def test_indentation_drift_is_tolerated(self):
        hay = "if x:\n        y = 1\n        z = 2\n"
        span = nova_diffview.flex_match(hay, "if x:\n    y = 1\n    z = 2")
        self.assertIsNotNone(span)

    def test_ambiguous_is_refused(self):
        self.assertIsNone(nova_diffview.flex_match("x = 1\nx = 1\n", "x = 1"))

    def test_absent_is_refused(self):
        self.assertIsNone(nova_diffview.flex_match("a\nb\n", "c"))

    def test_trailing_newline_needle_matches_up_to_eol(self):
        hay = "a\nb\nc\n"
        span = nova_diffview.flex_match(hay, "a\nb\n")
        self.assertIsNotNone(span)
        self.assertEqual(hay[span[0]:span[1]], "a\nb\n")

    def test_eof_match_runs_to_end(self):
        hay = "a\nb"
        span = nova_diffview.flex_match(hay, "a\nb")
        self.assertEqual(span, (0, len(hay)))

    def test_empty_inputs_are_never_matched(self):
        self.assertIsNone(nova_diffview.flex_match("abc", ""))
        self.assertIsNone(nova_diffview.flex_match("", "abc"))


# --------------------------------------------------------------------------
# 2. the edit pipeline (prepare_edits / apply_hunks / hunk_preview)
# --------------------------------------------------------------------------
class TestEditPipelineTolerance(unittest.TestCase):
    def _sess(self, ws):
        return nova.Session(ws)

    def test_prepare_edits_applies_drifted_hunk(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "app.py").write_text(
                "def main():\n    print('hi')\n    return 0\n", encoding="utf-8")
            sess = self._sess(ws)
            plans, problems = nova.prepare_edits(sess, [
                ("app.py", [("def main():\n  print('hi')\n  return 0",
                             "def main():\n  print('bye')\n  return 1")])])
            self.assertEqual(problems, [])
            self.assertEqual(len(plans), 1)
            self.assertIn("print('bye')", plans[0][3])
            self.assertIn("return 1", plans[0][3])

    def test_prepare_edits_still_refuses_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "app.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
            sess = self._sess(ws)
            plans, problems = nova.prepare_edits(sess, [("app.py", [("x = 1", "x = 2")])])
            self.assertEqual(plans, [])
            self.assertTrue(problems and "times" in problems[0][1])

    def test_prepare_edits_still_refuses_absent(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "app.py").write_text("a = 1\n", encoding="utf-8")
            sess = self._sess(ws)
            plans, problems = nova.prepare_edits(sess, [("app.py", [("zzz", "y")])])
            self.assertEqual(plans, [])
            self.assertTrue(problems)

    def test_apply_hunks_flex_fallback(self):
        text, applied, problems = nova_diffview.apply_hunks(
            "a = 1\nb = 2 \nc = 3\n", [("b = 2", "b = 22")])
        self.assertEqual(problems, [])
        self.assertIn("b = 22", text)
        self.assertEqual(len(applied), 1)

    def test_hunk_preview_renders_drifted_hunk(self):
        lines, ok = nova_diffview.hunk_preview(
            "def f():\n    return 1  \n", "def f():\n    return 1", "def f():\n    return 2")
        self.assertTrue(ok)
        self.assertTrue(any(ln.startswith("-") for ln in lines))
        self.assertTrue(any(ln.startswith("+") for ln in lines))


# --------------------------------------------------------------------------
# 3. CSS pre-apply lint
# --------------------------------------------------------------------------
class TestCssLint(unittest.TestCase):
    def test_balanced_css_passes(self):
        ok, why = nova_quality.preapply_check("style.css",
                                              "body { color: red; }\n.a { b: c; }")
        self.assertTrue(ok, why)

    def test_unbalanced_css_is_blocked(self):
        ok, why = nova_quality.preapply_check("style.css",
                                              "body { color: red;\n.a { b: c; }")
        self.assertFalse(ok)
        self.assertIn("CSS", why)

    def test_ruleless_css_is_blocked(self):
        # v8.11.0 contract update: the v7.1.0 docstring always said an
        # all-comments sheet "has no braces on purpose" - but the code
        # never implemented that half and this test pinned the buggy
        # rejection instead (a comments-only placeholder refused the
        # WHOLE atomic batch). Comments-only now passes; a sheet with no
        # braces AND no comments is still refused as suspicious.
        ok, why = nova_quality.preapply_check("style.css",
                                              "/* nothing here */\n")
        self.assertTrue(ok)
        ok, why = nova_quality.preapply_check("style.css", "@import url(x.css);")
        self.assertTrue(ok)
        ok, why = nova_quality.preapply_check("style.css",
                                              "plain text without any rule")
        self.assertFalse(ok)

    def test_truncated_css_is_blocked(self):
        ok, why = nova_quality.preapply_check("css/style.css",
                                              ".header {\n  background: #000;\n  color: #fff;")
        self.assertFalse(ok)


# --------------------------------------------------------------------------
# 4. the protocol-repair round (unnamed code blocks)
# --------------------------------------------------------------------------
class TestProtocolRepair(unittest.TestCase):
    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_ni = nova.NONINTERACTIVE

    def tearDown(self):
        nova.stream_chat = self._old_stream
        nova.NONINTERACTIVE = self._old_ni

    def test_unnamed_blocks_trigger_one_repair_and_apply(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            answers = iter([
                # round 1: a plain fenced block with NO === FILE: header
                "Here is your script:\n```python\nprint('hi')\n```\nRun: python game.py",
                # round 2 (the repair): the SAME code, properly named
                "=== FILE: game.py ===\nprint('hi')\n=== END ===\nRun: python game.py",
            ])
            prompts = []

            def fake_stream(model, msgs, mode, sess=None, section=None):
                prompts.append(msgs[-1]["content"])
                return next(answers), True

            nova.stream_chat = fake_stream
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "make a tiny script", auto=True)
            self.assertEqual(len(prompts), 2, "exactly ONE repair round")
            self.assertIn("=== FILE:", prompts[1])
            self.assertEqual(res["applied"], ["game.py"])
            self.assertEqual((ws / "game.py").read_text(encoding="utf-8").strip(),
                             "print('hi')")

    def test_named_files_skip_the_repair_round(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            calls = []

            def fake_stream(model, msgs, mode, sess=None, section=None):
                calls.append(1)
                return ("=== FILE: x.py ===\nprint(1)\n=== END ===\n"
                        "Run: python x.py"), True

            nova.stream_chat = fake_stream
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "make x.py", auto=True)
            self.assertEqual(len(calls), 1, "no repair when the protocol was used")
            self.assertEqual(res["applied"], ["x.py"])

    def test_web_staged_flow_after_repair(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            answers = iter([
                "```python\nprint('hi')\n```",
                "=== FILE: game.py ===\nprint('hi')\n=== END ===\nRun: python game.py",
            ])

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return next(answers), True

            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True          # web face
            sess = nova.Session(ws)
            sess.confirm_changes = True         # web approve-before-write
            res = nova.chat_turn(sess, "make a script", auto=True)
            self.assertEqual(res["applied"], [], "staging writes nothing yet")
            self.assertTrue(getattr(sess, "pending_apply", None),
                            "the batch must be staged for the browser panel")
            ok, _r = nova.apply_approved(sess, sess.pending_apply["id"],
                                         ["game.py"], {})
            self.assertTrue(ok)
            self.assertTrue((ws / "game.py").exists())


# --------------------------------------------------------------------------
# 5. the shared fix prompt (REPL /verify + web auto-fix)
# --------------------------------------------------------------------------
class TestBuildFixMessage(unittest.TestCase):
    def test_message_carries_cmd_output_and_protocol(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.last_failed = {"cmd": "python app.py", "code": 1,
                                "output": "Traceback ... ZeroDivisionError"}
            msg = nova.build_fix_message(sess)
            self.assertIn("python app.py", msg)
            self.assertIn("ZeroDivisionError", msg)
            self.assertIn("=== EDIT:", msg)

    def test_no_failure_no_message(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.last_failed = None
            self.assertIsNone(nova.build_fix_message(sess))


# --------------------------------------------------------------------------
# 6. child runs: stdin EOF + UTF-8 env + interactive hint
# --------------------------------------------------------------------------
class TestRunEnvironment(unittest.TestCase):
    def _run(self, ws, script):
        sess = nova.Session(ws)
        exe = sys.executable
        if " " in exe:
            exe = '"' + exe + '"'
        code = nova.run_command(sess, exe + " " + script, auto=True)
        return sess, code

    def test_stdin_is_devnull_and_utf8_env_reaches_children(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "probe.py").write_text(
                "import sys, os\n"
                "data = sys.stdin.read()\n"
                "open('probe.txt', 'w', encoding='utf-8').write("
                "('EOF-OK' if data == '' else 'HAS-DATA') + '|' "
                "+ str(os.environ.get('PYTHONUTF8')))\n",
                encoding="utf-8")
            sess, code = self._run(ws, "probe.py")
            self.assertEqual(code, 0)
            probe = (ws / "probe.txt").read_text(encoding="utf-8")
            self.assertTrue(probe.startswith("EOF-OK"),
                            "stdin must be DEVNULL: " + probe)
            self.assertIn("|1", probe, "children must run with PYTHONUTF8=1")

    def test_interactive_program_fails_fast_with_clean_error(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "ask.py").write_text(
                "name = input('your name: ')\nprint('hi', name)\n",
                encoding="utf-8")
            sess, code = self._run(ws, "ask.py")
            self.assertNotEqual(code, 0)
            self.assertIsNotNone(sess.last_failed)
            self.assertIn("EOFError", sess.last_failed["output"])


# --------------------------------------------------------------------------
# 7. the autofix flag is exposed to the web UI (info + settings)
# --------------------------------------------------------------------------
class TestAutofixFlag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import web_server
        import threading
        cls.web_server = web_server
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_v683_web_"))
        web_server.nova = nova
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        cls.httpd = web_server._make_server(args)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        import urllib.request
        with urllib.request.urlopen(self.base + path, timeout=15) as r:
            return r.status, r.read().decode()

    def _post(self, path, obj):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            self.base + path, data=__import__("json").dumps(obj).encode(),
            headers={"Content-Type": "application/json",
                     "Origin": self.base})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_autofix_roundtrips_through_settings_and_info(self):
        code, body = self._post("/api/settings", {"autofix": False})
        self.assertEqual(code, 200)
        self.assertIn('"autofix":false', body.replace(" ", ""))
        code, body = self._get("/api/info")
        self.assertEqual(code, 200)
        self.assertIn('"autofix":false', body.replace(" ", ""))
        self._post("/api/settings", {"autofix": True})   # restore default


if __name__ == "__main__":
    unittest.main()
