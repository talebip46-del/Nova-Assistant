#!/usr/bin/env python3
"""v6.9.0 tests: "check the coding section, agent and sub-agents line by
line; make the coding section stronger; a section guiding every command;
modern stickers".

Every test pins one real change:
  - mixed answers (=== EDIT: === + an unnamed fenced NEW file): the named
    work is CARRIED across the protocol-repair round and the unnamed block
    gets named -> both land (was: the unnamed file silently vanished)
  - a fenced === EDIT:/FILE: === block is never re-asked as "unnamed"
  - offer_apply: leftover unnamed blocks next to named work are LOUD
    (auto: printed note + event; REPL: the Save-as? prompt)
  - _default_run_cmd / run-hint fallback: the model forgot "Run:" ->
    the web Run button and the auto loops still get a verify command
  - /api/help + web_help_payload: every TOOLS command exactly once,
    Persian descriptions, full guard chain
  - the icon system: zero emoji (U+2300+) anywhere in index.html, the
    sprite + guide tab exist, v6.8.2 kill-switch markup intact
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

os.environ.setdefault("NOVA_DISABLED_MODULES", "")

import nova  # noqa: E402

HTML = (APP / "web" / "index.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. mixed FILE/EDIT answers: carried work + one repair round
# --------------------------------------------------------------------------
class TestMixedWorkRepair(unittest.TestCase):
    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_ni = nova.NONINTERACTIVE

    def tearDown(self):
        nova.stream_chat = self._old_stream
        nova.NONINTERACTIVE = self._old_ni

    def test_is_protocol_block(self):
        self.assertTrue(nova._is_protocol_block("=== EDIT: a.py ===\n..."))
        self.assertTrue(nova._is_protocol_block("=== file: x.js ==="))
        self.assertFalse(nova._is_protocol_block("plain code\nprint(1)"))

    def test_edit_plus_unnamed_new_file_both_land(self):
        """The user's 'cannot create multiple files AND edit them' scenario:
        round 1 has an EDIT block + a fenced unnamed NEW file; the repair
        round 1.5 names the new file; round 2 re-emits only that file."""
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "app.py").write_text("print('old')\n", encoding="utf-8")
            answers = iter([
                # round 1: valid EDIT block + a plain fenced NEW file
                "=== EDIT: app.py ===\n<<<<<<< SEARCH\nprint('old')\n=======\nprint('new')\n>>>>>>> REPLACE\n=== END ===\n"
                "```python\n# helper\nprint('helper')\n```",
                # round 2: the repair - the model re-emits ONLY the new file
                "=== FILE: helper.py ===\nprint('helper')\n=== END ===",
            ])

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return next(answers), True

            nova.stream_chat = fake_stream
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "edit app.py and add helper.py", auto=True)
            self.assertEqual(sorted(res["applied"]), ["app.py", "helper.py"],
                             "edit AND new file must both survive")
            self.assertIn("print('new')",
                          (ws / "app.py").read_text(encoding="utf-8"))
            self.assertTrue((ws / "helper.py").is_file())

    def test_carried_edit_survives_when_model_reemits_only_files(self):
        """The repair round must not be able to LOSE round-1 edits."""
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "app.py").write_text("a = 1\n", encoding="utf-8")
            answers = iter([
                "=== EDIT: app.py ===\n<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n=== END ===\n"
                "```\nsome unnamed snippet\n```",
                "=== FILE: b.js ===\nconsole.log(1);\n=== END ===",
            ])

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return next(answers), True

            nova.stream_chat = fake_stream
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "work", auto=True)
            self.assertIn("app.py", res["applied"])
            self.assertEqual((ws / "app.py").read_text(encoding="utf-8").strip(),
                             "a = 2", "round-1 edit must still be applied")

    def test_fenced_edit_block_is_never_asked_as_unnamed(self):
        """A whole === EDIT: === block wrapped in fences is protocol text
        (already parsed) - the repair message must not fire for it."""
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "a.py").write_text("x = 1\n", encoding="utf-8")
            calls = []

            def fake_stream(model, msgs, mode, sess=None, section=None):
                calls.append(msgs[-1]["content"])
                return ("```=== EDIT: a.py ===\n<<<<<<< SEARCH\nx = 1\n"
                        "=======\nx = 2\n>>>>>>> REPLACE\n=== END ===```"), True

            nova.stream_chat = fake_stream
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "bump x", auto=True)
            self.assertEqual(len(calls), 1, "no repair round for fenced protocol")
            self.assertEqual(res["applied"], ["a.py"])
            self.assertIn("x = 2", (ws / "a.py").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 2. leftover unnamed blocks next to named work are LOUD
# --------------------------------------------------------------------------
class TestLeftoverUnnamed(unittest.TestCase):
    def test_auto_prints_skip_note_and_emits_event(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            events = []
            old_emit = nova.EVENT_SINK
            nova.EVENT_SINK = events.append
            try:
                sess = nova.Session(ws)
                sess.touched["x.py"] = "new"
                nova.offer_apply(
                    sess,
                    [("x.py", "print(1)\n")],
                    ["unnamed leftover body"],
                    edits=None, auto=True)
            finally:
                nova.EVENT_SINK = old_emit
            self.assertTrue((ws / "x.py").is_file())
            self.assertTrue(
                any("unnamed" in str(e.get("text", "")) for e in events),
                "the web face must get the skip note as an event")

    def test_repl_still_prompts_save_as(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            old_input, old_ni, old_ask = nova.ui_input, nova.NONINTERACTIVE, nova.ask
            nova.ui_input = lambda *a, **k: "leftover.py"
            nova.ask = lambda *a, **k: "y"       # approve the apply prompt
            nova.NONINTERACTIVE = False
            try:
                sess = nova.Session(ws)
                sess.touched["x.py"] = "new"
                applied = nova.offer_apply(
                    sess, [("x.py", "print(1)\n")],
                    ["print('body')\n"], edits=None, auto=False)
            finally:
                nova.ui_input, nova.NONINTERACTIVE, nova.ask = old_input, old_ni, old_ask
            self.assertIn("leftover.py", applied)
            self.assertTrue((ws / "leftover.py").is_file())


# --------------------------------------------------------------------------
# 3. the run-hint fallback (model forgot its Run: line)
# --------------------------------------------------------------------------
class TestRunHintFallback(unittest.TestCase):
    def test_default_run_cmd_prefers_main_like_entries(self):
        py = nova._default_run_cmd(["css/style.css", "helper.py", "main.py"])
        self.assertTrue(py.endswith("main.py"), py)
        self.assertTrue(nova._default_run_cmd(["index.html", "css/a.css"]) == "")

    def test_chat_turn_fills_run_cmd_when_model_forgot_it(self):
        old_stream = nova.stream_chat
        try:
            def fake_stream(model, msgs, mode, sess=None, section=None):
                return ("=== FILE: main.py ===\nprint('hi')\n=== END ===\n"
                        "(no Run line on purpose)"), True

            nova.stream_chat = fake_stream
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                res = nova.chat_turn(sess, "make main.py", auto=True)
                # v6.9 final-audit contract: the DERIVED command goes to its
                # own key - /verify and /auto may only follow a command the
                # MODEL wrote (a derived 'python helper.py' on a support
                # module would fake a green verify).
                self.assertFalse(res.get("run_cmd"),
                                 "derived cmd must never pose as the model's")
                self.assertTrue((res.get("suggested_run") or "").endswith("main.py"))
        finally:
            nova.stream_chat = old_stream

    def test_derived_cmd_does_not_hijack_verify_loop(self):
        old_stream = nova.stream_chat
        try:
            def fake_stream(model, msgs, mode, sess=None, section=None):
                return ("=== FILE: helper.py ===\nX = 1\n=== END ==="), True

            nova.stream_chat = fake_stream
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                res = nova.chat_turn(sess, "add helper", auto=True)
                # verify_flow adopts res["run_cmd"] only - which stays None
                self.assertIsNone(res["run_cmd"])
                self.assertTrue((res.get("suggested_run") or "")
                                .endswith("helper.py"))
        finally:
            nova.stream_chat = old_stream

    def test_explicit_run_hint_is_never_overridden(self):
        old_stream = nova.stream_chat
        try:
            def fake_stream(model, msgs, mode, sess=None, section=None):
                return ("=== FILE: main.py ===\nprint('hi')\n=== END ===\n"
                        "Run: python main.py --serve"), True

            nova.stream_chat = fake_stream
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                res = nova.chat_turn(sess, "make main.py", auto=True)
                # the hint survives (interpreter-normalized for THIS machine)
                self.assertTrue(res["run_cmd"].endswith("main.py --serve"))
                self.assertNotIn("--serve", nova._default_run_cmd(res["applied"]))
        finally:
            nova.stream_chat = old_stream


# --------------------------------------------------------------------------
# 4. the guide payload + /api/help
# --------------------------------------------------------------------------
class TestHelpPayload(unittest.TestCase):
    def test_every_tool_appears_exactly_once(self):
        payload = nova.web_help_payload()
        seen = [it["cmd"] for g in payload["groups"] for it in g["items"]]
        self.assertEqual(len(seen), len(nova.TOOLS), "all TOOLS, exactly once")
        self.assertEqual(len(seen), len(set(seen)), "no duplicates")
        for g in payload["groups"]:
            self.assertTrue(g["title"])
            for it in g["items"]:
                self.assertTrue(it["usage"].startswith("/"))

    def test_persian_descriptions_present(self):
        payload = nova.web_help_payload()
        flat = {it["cmd"]: it for g in payload["groups"] for it in g["items"]}
        self.assertIn("فهرست", flat["/help"]["help"])
        self.assertIn("اجرا", flat["/run"]["help"])

    def test_tools_usage_strings_are_clean(self):
        for t in nova.TOOLS:
            self.assertFalse(t["usage"].endswith("] ]") or
                             "name] odel" in t["usage"], t["usage"])


# --------------------------------------------------------------------------
# 4b. the JS pre-apply gate (v6.9 bugfix: _which_node returned a BOOL, so
# every valid .js file was rejected with "expected str, bytes or os.PathLike"
# and whole multi-file batches died in the lint gate)
# --------------------------------------------------------------------------
class TestJsLintGate(unittest.TestCase):
    def test_valid_js_passes_preapply(self):
        import nova_quality
        ok, problem = nova_quality.preapply_check(
            "js/main.js", "const el = document.querySelector('#x');\n"
            "if (el) { el.textContent = 'hi'; }\n")
        self.assertTrue(ok, "valid JS must pass the gate: " + str(problem))

    def test_broken_js_is_still_rejected(self):
        import nova_quality
        ok, problem = nova_quality.preapply_check(
            "js/main.js", "function( { broken at all")
        self.assertFalse(ok)
        self.assertNotIn("PathLike", problem, "the linter's own crash must "
                                              "never masquerade as a lint error")


# --------------------------------------------------------------------------
# 5. the web face: guide tab + icon system (regression pins)
# --------------------------------------------------------------------------
class TestWebFace(unittest.TestCase):
    def test_no_emoji_anywhere(self):
        bad = sorted({hex(ord(ch)) for ch in HTML if ord(ch) >= 0x2300})
        self.assertEqual(bad, [], "emoji stickers must stay dead: %s" % bad)

    def test_icon_sprite_exists(self):
        for sym in ("i-code", "i-chat", "i-help", "i-trash", "i-send",
                    "i-play", "i-check", "i-warn", "i-gauge", "i-brain"):
            self.assertIn('id="%s"' % sym, HTML)

    def test_guide_tab_and_loader(self):
        self.assertIn('data-view="help"', HTML)
        self.assertNotIn('data-view="help"  disabled', HTML)
        self.assertIn('id="panel-help"', HTML)
        self.assertIn("loadHelpTab", HTML)
        self.assertIn("help: () => loadHelpTab()", HTML)
        self.assertIn("/api/help", HTML)

    def test_killswitch_markup_untouched(self):
        # v6.8.2's pins must survive the icon rework
        for view in ("voice", "photo", "pixel", "flow"):
            line = next(l for l in HTML.splitlines()
                        if 'data-view="%s"' % view in l and "mtab" in l)
            self.assertIn("disabled", line, view)
            self.assertIn("غیرفعال", line, view)
            self.assertIn("mtab-dis", line, view)


# --------------------------------------------------------------------------
# 6. final-audit regressions (the line-by-line sweep)
# --------------------------------------------------------------------------
class TestAuditFixes(unittest.TestCase):
    def _sess(self, ws):
        return nova.Session(ws)

    def test_prepare_edits_merges_path_spellings(self):
        """'app.py' + './app.py' in one answer = ONE target (the second
        plan used to overwrite the first from the ORIGINAL disk content)."""
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "app.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
            edits = [
                ("app.py", [("a = 1", "a = 111")]),
                ("./app.py", [("b = 2", "b = 222")]),
            ]
            plans, problems = nova.prepare_edits(self._sess(ws), edits)
            self.assertEqual(len(plans), 1, plans)
            self.assertEqual(problems, [])
            self.assertIn("a = 111", plans[0][3])
            self.assertIn("b = 222", plans[0][3])

    def test_parse_files_splits_swallowed_sibling(self):
        """Block A forgets === END === and the lazy body swallowed block B:
        both files must land, loudly (the old code wrote B's header into
        A's content and dropped B entirely)."""
        text = ("=== FILE: a.py ===\nprint('a')\n"
                "=== FILE: b.py ===\nprint('b')\n=== END ===\n"
                "=== END ===\nRun: python a.py")
        files, unnamed = nova.parse_files(text)
        names = sorted(n for n, _c in files)
        self.assertEqual(names, ["a.py", "b.py"], files)
        bodies = dict(files)
        self.assertEqual(bodies["a.py"].strip(), "print('a')")
        self.assertEqual(bodies["b.py"].strip(), "print('b')")

    def test_apply_approved_rolls_back_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "keep.py").write_text("x = 0\n", encoding="utf-8")
            nova.NONINTERACTIVE = True
            try:
                sess = self._sess(ws)
                sess.touched["keep.py"] = "new"
                nova.offer_apply(sess, [("keep.py", "x = 0\n")], [], auto=True)
                # stage a two-file batch; make the SECOND write impossible
                # by pointing its target at a directory
                (ws / "bad").mkdir()
                plans = [("keep.py", "x = 1\n", ws / "keep.py"),
                         ("bad", "y\n", ws / "bad")]
                edits = []
                sess.pending_apply = {"id": "t1", "plans": plans,
                                      "hunks": {}, "ts": __import__("time").time()}
                ok, res = nova.apply_approved(sess, "t1", ["keep.py", "bad"], {})
                self.assertTrue(ok)
                self.assertEqual(res["applied"], [])
                self.assertIn("rolled back", " ".join(res["errors"]))
                self.assertEqual((ws / "keep.py").read_text(encoding="utf-8"),
                                 "x = 0\n", "file 1 must be restored")
            finally:
                nova.NONINTERACTIVE = False

    def test_same_origin_rejects_null(self):
        import web_server

        class _H:
            def __init__(self, headers):
                self.headers = headers

        h = _H({"Origin": "null", "Host": "127.0.0.1:8765"})
        self.assertFalse(web_server._same_origin(h),
                         "sandboxed-iframe Origin: null must be refused")
        h2 = _H({"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"})
        self.assertTrue(web_server._same_origin(h2))
        h3 = _H({"Host": "127.0.0.1:8765"})
        self.assertTrue(web_server._same_origin(h3), "no Origin = GET nav")

    def test_windows_reserved_names_are_prefixed(self):
        parts = nova.sanitize_parts("con.txt")
        self.assertTrue(parts[0].startswith("_"), parts)
        self.assertNotEqual(parts[0].lower()[:-1], "con.txt")

    def test_css_quoted_brace_passes(self):
        import nova_quality
        ok, problem = nova_quality.preapply_check(
            "css/style.css", 'q:after{content:"}"}\nbody{color:red}\n')
        self.assertTrue(ok, problem)

    def test_timeline_shows_newest_first(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            calls = {}

            def fake_list_units(w):
                calls["ws"] = w
                return [{"id": "newest", "ts": 3, "note": "n", "files": []},
                        {"id": "mid", "ts": 2, "note": "m", "files": []},
                        {"id": "oldest", "ts": 1, "note": "o", "files": []}]

            old = nova.snaps
            nova.snaps = __import__("types").SimpleNamespace(list_units=fake_list_units)
            try:
                buf = io.StringIO()
                old_stdout = sys.stdout
                sys.stdout = buf
                try:
                    nova.cmd_timeline(self._sess(ws), "2")
                finally:
                    sys.stdout = old_stdout
            finally:
                nova.snaps = old
            out = buf.getvalue()
            self.assertIn("newest", out)
            self.assertNotIn("oldest", out, "/timeline 2 must show the 2 NEWEST")

    def test_headerless_hunk_block_gets_repair_round(self):
        old_stream = nova.stream_chat
        try:
            answers = iter([
                "```\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n"
                ">>>>>>> REPLACE\n```",
                "=== EDIT: a.py ===\n<<<<<<< SEARCH\nx = 1\n=======\n"
                "x = 2\n>>>>>>> REPLACE\n=== END ===",
            ])

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return next(answers), True

            nova.stream_chat = fake_stream
            with tempfile.TemporaryDirectory() as td:
                ws = Path(td)
                (ws / "a.py").write_text("x = 1\n", encoding="utf-8")
                sess = self._sess(ws)
                res = nova.chat_turn(sess, "bump x", auto=True)
                self.assertEqual(res["applied"], ["a.py"])
                self.assertIn("x = 2", (ws / "a.py").read_text(encoding="utf-8"))
        finally:
            nova.stream_chat = old_stream

    def test_cli_provider_beats_profile(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            old = nova._CLI_PROVIDER
            nova._CLI_PROVIDER = "ollama"
            try:
                import nova_project as nproj
                nproj.save_profile(ws, {"provider": "openai", "model": "x"})
                sess = self._sess(ws)
                cfg = nova._provider_cfg()
                self.assertEqual(cfg.get("name"), "ollama",
                                 "the CLI --provider must win for this run")
            finally:
                nova._CLI_PROVIDER = old

    def test_web_confirm_stages_even_without_auto(self):
        """/fix typed into the web box (auto=False, NONINTERACTIVE) must
        STAGE, not silently apply."""
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            old_ni = nova.NONINTERACTIVE
            nova.NONINTERACTIVE = True
            try:
                sess = self._sess(ws)
                sess.confirm_changes = True
                applied = nova.offer_apply(sess, [("x.py", "print(1)\n")],
                                           [], auto=False)
                self.assertEqual(applied, [])
                self.assertTrue(getattr(sess, "pending_apply", None))
                self.assertFalse((ws / "x.py").exists())
            finally:
                nova.NONINTERACTIVE = old_ni

    def test_profile_set_coerces_and_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            sess = self._sess(Path(td))
            v, err = nova._coerce_profile_value("run_timeout", "300")
            self.assertEqual((v, err), (300, ""))
            v, err = nova._coerce_profile_value("autotest", "off")
            self.assertEqual((v, err), (False, ""))
            v, err = nova._coerce_profile_value("run_timeout", "abc")
            self.assertIsNone(v)
            v, err = nova._coerce_profile_value("mode", "nope")
            self.assertIsNone(v)


if __name__ == "__main__":
    unittest.main()
