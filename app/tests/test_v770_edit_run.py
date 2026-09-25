#!/usr/bin/env python3
"""v7.7.0 tests: EDIT-after-RUN stability - the user's report.

"من یک سایت ساختم و حتی راحت run زدم و ران شد، اما وقتی گفتم edit اش کنه
یهویی خروجی خراب شد و دکمه run دیگه کار نمیکرد و ارور میخورد"

Live reproduction of that exact journey (build -> Run works -> ask for an
edit) exposed four real defects, every one pinned here:

  1. 'Preview: index.html' / 'Run: start index.html' hints were handed to
     the SHELL: exit 127 even though the site was healthy. The web auto-fix
     round then fed a NON-EXISTENT error back to the model, which rewrote
     HEALTHY files - the "run worked, then everything broke" loop.
     -> preview hints are now intercepted and OPEN the file (exit 0,
        no shell, no auto-fix).
  2. An === EDIT: === block whose === END === never came was dropped
     SILENTLY (raw SEARCH/REPLACE markers left as broken chat output) and
     - worse - the lazy DOTALL body swallowed the NEXT block's header and
     END, so the following edit's hunks landed in the FIRST file
     (wrong-file corruption, the same v6.9 FILE-protocol bug).
     -> parse_edits is now a left-to-right scan that recovers unclosed
        blocks and never crosses the next header line.
  3. A pure-prose Run hint ('refresh your browser page') was also
     shell-executed -> 127 -> phantom auto-fix. It is now refused cleanly
     and never becomes the project's remembered command.
  4. After an edit turn with no fresh Run line the web Run chip died (or
     held a stale command). chat_turn now carries the last known hint
     forward (workspace switches and /clear reset it).

All tests are NETWORK-FREE; the model is scripted via nova.stream_chat.
"""
import os
import re
import types
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova  # noqa: E402
import web_server  # noqa: E402


def _tmp_ws(testcase):
    """A temp workspace whose cleanup tolerates the .nova dirs the
    Session machinery (rag/style/snapshots) leaves behind."""
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="nova_v77_")
    testcase.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return Path(d)


def _site_html(slogan="بهترین محصولات"):
    return ('<!DOCTYPE html>\n<html lang="fa" dir="rtl">\n<head>\n'
            '<meta charset="UTF-8">\n<title>فروشگاه</title>\n'
            '<link rel="stylesheet" href="css/style.css">\n</head>\n<body>\n'
            '<h1 id="title">فروشگاه من</h1>\n'
            f'<p id="slogan">{slogan}</p>\n'
            '<script src="js/main.js"></script>\n</body>\n</html>\n')


def _valid_html(text):
    low = str(text).lower()
    for tag in ("script", "style", "html", "body"):
        op = len(re.findall(r"<" + tag + r"[\s>]", low))
        cl = len(re.findall(r"</" + tag + r"\s*>", low))
        if op != cl:
            return False
    return True


class TestParseEditsV77(unittest.TestCase):
    """The v7.7 left-to-right scan (unclosed salvage + no header swallow)."""

    def test_closed_single_hunk(self):
        txt = ("=== EDIT: app.py ===\n"
               "<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE\n"
               "=== END ===")
        self.assertEqual(nova.parse_edits(txt),
                         [("app.py", [("old line", "new line")])])

    def test_closed_multi_hunk_crlf(self):
        txt = ("=== EDIT: x.py ===\r\n"
               "<<<<<<< SEARCH\r\na = 1\r\n=======\r\na = 2\r\n>>>>>>> REPLACE\r\n"
               "<<<<<<< SEARCH\r\nb = 1\r\n=======\r\nb = 2\r\n>>>>>>> REPLACE\r\n"
               "=== END ===\r\n")
        self.assertEqual(nova.parse_edits(txt),
                         [("x.py", [("a = 1", "a = 2"), ("b = 1", "b = 2")])])

    def test_end_edit_variant_closes(self):
        txt = ("=== EDIT: a.py ===\n"
               "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n"
               "=== END EDIT ===")
        self.assertEqual(nova.parse_edits(txt),
                         [("a.py", [("x", "y")])])

    def test_empty_replace_still_parses(self):
        txt = ("=== EDIT: app.py ===\n"
               "<<<<<<< SEARCH\nkill me\n=======\n\n>>>>>>> REPLACE\n"
               "=== END ===")
        self.assertEqual(nova.parse_edits(txt),
                         [("app.py", [("kill me", "")])])

    def test_unclosed_block_is_recovered(self):
        txt = ("=== EDIT: index.html ===\n"
               "<<<<<<< SEARCH\n<p>old</p>\n=======\n<p>new</p>\n"
               ">>>>>>> REPLACE")
        self.assertEqual(nova.parse_edits(txt),
                         [("index.html", [("<p>old</p>", "<p>new</p>")])])

    def test_unclosed_followed_by_closed_no_wrong_file_swallow(self):
        # THE v7.7 corruption fix: the unclosed first block's body used to
        # swallow the second block's header AND END, so b.txt's hunk landed
        # in index.html
        txt = ("=== EDIT: index.html ===\n"
               "<<<<<<< SEARCH\n<p>old</p>\n=======\n<p>new</p>\n"
               ">>>>>>> REPLACE\n\n"
               "=== EDIT: b.txt ===\n"
               "<<<<<<< SEARCH\n1\n=======\n2\n>>>>>>> REPLACE\n"
               "=== END ===\n")
        self.assertEqual(nova.parse_edits(txt),
                         [("index.html", [("<p>old</p>", "<p>new</p>")]),
                          ("b.txt", [("1", "2")])])

    def test_unclosed_body_stops_at_run_line(self):
        txt = ("=== EDIT: a.py ===\n"
               "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n"
               "\nPreview: index.html\nsome prose")
        self.assertEqual(nova.parse_edits(txt),
                         [("a.py", [("x", "y")])])

    def test_malformed_unclosed_yields_empty_hunks(self):
        txt = "=== EDIT: c.txt ===\n<<<<<<< SEARCH\nonly the search side"
        self.assertEqual(nova.parse_edits(txt), [("c.txt", [])])

    def test_edit_mention_inside_file_body_is_not_protocol(self):
        txt = ("=== FILE: page.html ===\n"
               "<html><!-- === EDIT: fake.txt === --></html>\n"
               "=== END ===\n")
        self.assertEqual(nova.parse_edits(txt), [])

    def test_crlf_closed_block_is_closed(self):
        # v7.7.1 audit: '=== END ===\r\n' made the end-regex miss -> the
        # closed block was misread as unclosed and its salvage body
        # swallowed the NEXT block into a phantom hunk (real edit refused)
        txt = ("=== EDIT: app.py ===\r\n"
               "<<<<<<< SEARCH\r\ncolor = 'red'\r\n=======\r\n"
               "color = 'blue'\r\n>>>>>>> REPLACE\r\n"
               "=== END ===\r\n"
               "Run: python app.py\n")
        self.assertEqual(nova.parse_edits(txt),
                         [("app.py", [("color = 'red'", "color = 'blue'")])])

    def test_eight_arrow_hunk_is_still_refused(self):
        txt = ("=== EDIT: app.py ===\n"
               "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>>> REPLACE\n"
               "=== END ===")
        self.assertEqual(nova.parse_edits(txt), [("app.py", [])])


class TestPreviewTarget(unittest.TestCase):
    """Run/Preview hints that really mean 'open the document'."""

    def setUp(self):
        self.ws = _tmp_ws(self)
        (self.ws / "index.html").write_text("<html></html>", encoding="utf-8")
        (self.ws / "my page.html").write_text("<html></html>", encoding="utf-8")

    def test_bare_html(self):
        p = nova.preview_target(self.ws, "index.html")
        self.assertIsNotNone(p)
        self.assertTrue(p.is_file())

    def test_open_prefixes(self):
        for cmd in ("start index.html", 'start "" "index.html"',
                    "open index.html", "xdg-open index.html",
                    "cmd /c start index.html", "explorer index.html"):
            p = nova.preview_target(self.ws, cmd)
            self.assertIsNotNone(p, cmd)
            self.assertEqual(p.name, "index.html", cmd)

    def test_quoted_and_padded(self):
        p = nova.preview_target(self.ws, '  "index.html"  ')
        self.assertIsNotNone(p)
        p = nova.preview_target(self.ws, "my page.html")
        self.assertIsNotNone(p)

    def test_htm_extension(self):
        (self.ws / "page.htm").write_text("<html></html>", encoding="utf-8")
        self.assertIsNotNone(nova.preview_target(self.ws, "page.htm"))

    def test_shell_commands_are_never_previews(self):
        for cmd in ("python app.py", "npm run dev", "node server.js",
                    "python -m http.server 8000", "git status"):
            self.assertIsNone(nova.preview_target(self.ws, cmd), cmd)

    def test_metacharacters_are_refused(self):
        for cmd in ("index.html; rm -rf /", "index.html && calc",
                    "start $(calc)", "a|b.html", "a>b.html"):
            self.assertIsNone(nova.preview_target(self.ws, cmd), cmd)

    def test_non_document_suffixes_are_not_previews(self):
        (self.ws / "note.txt").write_text("hi", encoding="utf-8")
        self.assertIsNone(nova.preview_target(self.ws, "note.txt"))

    def test_missing_file_still_returns_the_path(self):
        p = nova.preview_target(self.ws, "missing.html")
        self.assertIsNotNone(p)
        self.assertFalse(p.is_file())

    def test_absolute_missing_still_returns_the_path(self):
        # absolute paths are open-or-note, never a shell - a missing one
        # gets the friendly 'does not exist' note instead of a 127 + a
        # phantom auto-fix round
        p = nova.preview_target(self.ws, str(self.ws.parent / "no_such.html"))
        self.assertIsNotNone(p)
        self.assertFalse(p.is_file())

    def test_absolute_existing_opens(self):
        outside = self.ws.parent / "outside_v77.html"
        outside.write_text("<html></html>", encoding="utf-8")
        self.addCleanup(lambda: outside.exists() and outside.unlink())
        p = nova.preview_target(self.ws, str(outside))
        self.assertIsNotNone(p)
        self.assertTrue(p.is_file())

    def test_traversal_is_refused(self):
        self.assertIsNone(nova.preview_target(self.ws, "../x.html"))

    def test_zwnj_and_nbsp_filenames_are_previews(self):
        # v7.7.1 audit: ZWNJ (U+200C) is ubiquitous in Persian words
        # (تازه‌سازی.html) and is NOT \w - without it the interception
        # dies exactly where Persian users need it
        (self.ws / "تازه‌سازی.html").write_text("<html></html>",
                                                  encoding="utf-8")
        p = nova.preview_target(self.ws, "تازه‌سازی.html")
        self.assertIsNotNone(p)
        self.assertTrue(p.is_file())
        (self.ws / "page\u00a0one.html").write_text("<html></html>",
                                                     encoding="utf-8")
        self.assertIsNotNone(nova.preview_target(self.ws, "page\u00a0one.html"))

    def test_open_flag_tokens_are_peeled(self):
        # v7.7.1 audit: 'start /min index.html' used to glue '/min' onto
        # the path and dead-end at 'does not exist'
        for cmd in ("start /min index.html", "xdg-open --arg index.html"):
            p = nova.preview_target(self.ws, cmd)
            self.assertIsNotNone(p, cmd)
            self.assertEqual(p.name, "index.html", cmd)


class TestPreviewRun(unittest.TestCase):
    """run_command: preview hints open the file, never touch the shell."""

    def setUp(self):
        self.ws = _tmp_ws(self)
        self.sess = nova.Session(self.ws)
        self.sess.model = "fake:7b"
        self.sess._local_brain = lambda: True

    def test_existing_file_opens_and_returns_zero(self):
        (self.ws / "index.html").write_text("<html></html>", encoding="utf-8")
        opened = []
        with mock.patch.object(nova, "open_browser",
                               side_effect=lambda url: opened.append(url)), \
                mock.patch.object(nova.subprocess, "Popen",
                                  side_effect=AssertionError("shell ran!")):
            code = nova.run_command(self.sess, "index.html", auto=True,
                                    origin="web")
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].startswith("file://"))
        self.assertIn("index.html", opened[0])

    def test_start_prefix_opens_too(self):
        (self.ws / "index.html").write_text("<html></html>", encoding="utf-8")
        opened = []
        with mock.patch.object(nova, "open_browser",
                               side_effect=lambda url: opened.append(url)):
            code = nova.run_command(self.sess, "start index.html", auto=True,
                                    origin="web")
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)

    def test_missing_file_returns_none_without_shell(self):
        with mock.patch.object(nova, "open_browser") as ob, \
                mock.patch.object(nova.subprocess, "Popen",
                                  side_effect=AssertionError("shell ran!")):
            code = nova.run_command(self.sess, "missing.html", auto=True,
                                    origin="web")
        self.assertIsNone(code)
        ob.assert_not_called()
        self.assertIsNone(self.sess.last_failed)   # no phantom fix material

    def test_prose_hint_is_refused_cleanly(self):
        with mock.patch.object(nova.subprocess, "Popen",
                               side_effect=AssertionError("shell ran!")):
            code = nova.run_command(
                self.sess, "صفحه را در مرورگر تازه‌سازی کنید", auto=True,
                origin="web")
        self.assertIsNone(code)
        self.assertIsNone(self.sess.last_failed)

    def test_real_shell_command_still_runs(self):
        # a REAL command must go through the normal (screened) shell path
        code = nova.run_command(self.sess, "echo nova_v77_ok", auto=True,
                                origin="web")
        self.assertEqual(code, 0)

    def test_unrunnable_command_sets_last_failed_but_not_a_code_error(self):
        code = nova.run_command(self.sess, "definitely_not_a_cmd_v77",
                                auto=True, origin="web")
        self.assertIsNotNone(self.sess.last_failed)
        self.assertTrue(nova.is_unrunnable_failure(
            code, self.sess.last_failed.get("output") or ""))


class TestIsUnrunnable(unittest.TestCase):
    def test_posix_not_found_codes(self):
        for c in (126, 127, 9009):
            self.assertTrue(nova.is_unrunnable_failure(c, ""))

    def test_windows_message(self):
        self.assertTrue(nova.is_unrunnable_failure(
            1, "'foo' is not recognized as an internal or external command"))

    def test_sh_not_found_message(self):
        self.assertTrue(nova.is_unrunnable_failure(
            2, "/bin/sh: 1: whatever: not found"))

    def test_real_program_failure_is_not_unrunnable(self):
        self.assertFalse(nova.is_unrunnable_failure(
            1, 'Traceback (most recent call last):\n  File "main.py", line 5\n'
               'NameError: name "x" is not defined'))

    def test_success_and_no_start_are_not_unrunnable(self):
        self.assertFalse(nova.is_unrunnable_failure(0, ""))
        self.assertFalse(nova.is_unrunnable_failure(None, "anything"))


GOOD_SITE = ("سایت آماده است.\n\n"
             "=== FILE: index.html ===\n" + _site_html() +
             "=== END ===\n\nPreview: index.html")

EDIT_NO_HINT = ("ویرایش شد.\n\n=== EDIT: index.html ===\n"
                "<<<<<<< SEARCH\n<p id=\"slogan\">بهترین محصولات</p>\n"
                "=======\n<p id=\"slogan\">فروش ویژه</p>\n"
                ">>>>>>> REPLACE\n=== END ===\n")

EDIT_PROSE_HINT = ("ویرایش شد.\n\n=== EDIT: index.html ===\n"
                   "<<<<<<< SEARCH\n<p id=\"slogan\">بهترین محصولات</p>\n"
                   "=======\n<p id=\"slogan\">تخفیف پاییزی</p>\n"
                   ">>>>>>> REPLACE\n=== END ===\n\n"
                   "Run: صفحه را در مرورگر تازه‌سازی کنید")


class TestSalvagedSpans(unittest.TestCase):
    """v7.7.1 audit: a Run/tool line inside a SALVAGED edit body must not
    hijack the turn's Run command or tool round."""

    def test_run_line_inside_salvaged_body_is_excluded(self):
        makefile_edit = ("=== EDIT: Makefile ===\n"
                         "<<<<<<< SEARCH\nold:\n\techo old\n=======\n"
                         "run:\n\techo built\n>>>>>>> REPLACE\n")
        self.assertIsNone(nova.extract_run_hint(makefile_edit))

    def test_hint_after_salvaged_block_still_wins(self):
        txt = ("=== EDIT: Makefile ===\n"
               "<<<<<<< SEARCH\na\n=======\nrun:\n\techo x\n>>>>>>> REPLACE\n"
               "\nPreview: index.html\n")
        self.assertEqual(nova.extract_run_hint(txt), "index.html")

    def test_token_inside_salvaged_body_never_fires(self):
        txt = ("=== EDIT: page.html ===\n"
               "<<<<<<< SEARCH\nold img\n=======\n"
               "[IMG: red rose]\n>>>>>>> REPLACE\n")
        act = nova.find_model_action(txt)
        # either None or a no-op: the token is inside the recovered body
        if act is not None:
            self.fail("tool token inside a salvaged edit body fired: %r" % (act,))


class TestPreviewAuditTrail(unittest.TestCase):
    """v7.7.1 audit: the preview branch leaves the same nsec audit trail."""

    def test_preview_open_is_audited(self):
        ws = _tmp_ws(self)
        (ws / "index.html").write_text("<html></html>", encoding="utf-8")
        sess = nova.Session(ws)
        sess.model = "fake:7b"
        sess._local_brain = lambda: True
        if nova.nsec is None:
            self.skipTest("nova_security unavailable")
        with mock.patch.object(nova.nsec, "audit",
                               side_effect=lambda *a, **k: None) as aud:
            code = nova.run_command(sess, "index.html", auto=True,
                                    origin="web")
        self.assertEqual(code, 0)
        self.assertTrue(aud.called)
        self.assertEqual(aud.call_args.args[1], "preview")


EDIT_NO_HINT2 = ("ویرایش شد.\n\n=== EDIT: index.html ===\n"
                 "<<<<<<< SEARCH\n<p id=\"slogan\">تخفیف پاییزی</p>\n"
                 "=======\n<p id=\"slogan\">فروش ویژه</p>\n"
                 ">>>>>>> REPLACE\n=== END ===\n")


class TestRunCmdCarryForward(unittest.TestCase):
    """The Run chip stays alive across edit turns (v7.7)."""

    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_installed = nova.list_installed_models
        self.addCleanup(setattr, nova, "stream_chat", self._old_stream)
        self.addCleanup(setattr, nova, "list_installed_models",
                        self._old_installed)
        nova.list_installed_models = lambda: []
        self.ws = _tmp_ws(self)
        self.sess = nova.Session(self.ws)
        self.sess.model = "fake:7b"
        self.sess._local_brain = lambda: True

    def _turn(self, answer):
        nova.stream_chat = lambda model, msgs, mode, sess=None, section=None, \
            quiet=False: (answer, True)
        return nova.chat_turn(self.sess, "continue", auto=True)

    def test_build_turn_records_the_hint(self):
        res = self._turn(GOOD_SITE)
        self.assertEqual(res["run_cmd"], "index.html")
        self.assertEqual(self.sess.last_run_cmd, "index.html")
        self.assertTrue((self.ws / "index.html").exists())

    def test_edit_without_hint_carries_the_last_one(self):
        self._turn(GOOD_SITE)
        res = self._turn(EDIT_NO_HINT)
        self.assertEqual(res["run_cmd"], "index.html")
        self.assertIn("فروش ویژه",
                      (self.ws / "index.html").read_text(encoding="utf-8"))

    def test_prose_hint_never_poisons_the_remembered_command(self):
        # the SEARCH matches what turn 1 really wrote (v7.7.1 audit: the
        # old fixture searched text that was never on disk, so the edit
        # was refused and the test passed for the wrong reason)
        self._turn(GOOD_SITE)
        res = self._turn(EDIT_PROSE_HINT)
        self.assertIn("index.html", res["applied"])
        # the model's own (prose) hint is still what the user sees...
        self.assertIn("تازه", res["run_cmd"])
        # ...but the project's remembered command stays runnable
        self.assertEqual(self.sess.last_run_cmd, "index.html")
        # and the next hint-less turn carries the GOOD command forward
        res2 = self._turn(EDIT_NO_HINT2)
        self.assertEqual(res2["run_cmd"], "index.html")
        self.assertIn("فروش ویژه",
                      (self.ws / "index.html").read_text(encoding="utf-8"))

    def test_pure_question_turn_adds_no_chip(self):
        self._turn(GOOD_SITE)
        res = self._turn("چرا؟ توضیح بده فقط.")
        self.assertIsNone(res.get("run_cmd"))

    def test_workspace_switch_resets_the_hint(self):
        self._turn(GOOD_SITE)
        self.assertEqual(self.sess.last_run_cmd, "index.html")
        self.sess.set_workspace(_tmp_ws(self))
        self.assertEqual(self.sess.last_run_cmd, "")

    def test_staged_batch_carries_the_chip(self):
        old_ni = nova.NONINTERACTIVE
        old_cc = self.sess.confirm_changes
        nova.NONINTERACTIVE = True
        self.sess.confirm_changes = True
        try:
            self._turn(GOOD_SITE)          # staged, nothing on disk yet
            self.assertIsNotNone(self.sess.pending_apply)
            self.assertFalse((self.ws / "index.html").exists())
            res = self._turn(EDIT_NO_HINT)  # staged again, still no hint
            self.assertEqual(res.get("applied"), [])
            # v8.11 contract: a merely STAGED batch carries NO Run chip -
            # the old pending_apply backfill re-offered the project's last
            # hint while nothing was on disk (the UI then said 'nothing
            # written yet' AND offered to run code that does not exist)
            self.assertIsNone(res.get("run_cmd"))
            self.assertFalse((self.ws / "index.html").exists())
        finally:
            nova.NONINTERACTIVE = old_ni
            self.sess.confirm_changes = old_cc
            self.sess.pending_apply = None


class TestWebAutofixGuard(unittest.TestCase):
    """BEHAVIORAL (v7.7.1 audit): the web auto-fix decision drives the real
    Handler._run_turn with stubbed run/chat layers - the three skip
    branches and the real fix round, no source-string pinning."""

    CODE_ERROR = {"cmd": "python app.py", "code": 1,
                  "output": "Traceback (most recent call last):\nNameError: x"}
    NOT_FOUND = {"cmd": "definitely_not_a_cmd_v77", "code": 127,
                 "output": "/bin/sh: 1: definitely_not_a_cmd_v77: not found"}
    SERVER = {"cmd": "python -m http.server 8000", "code": 1,
              "output": "Serving HTTP on 0.0.0.0"}
    TIMEOUT = {"cmd": "python serve.py", "code": "timeout", "output": ""}

    def setUp(self):
        self._old_nova = web_server.nova
        self._old_state = web_server.STATE
        stub = types.SimpleNamespace(
            run_command=lambda *a, **k: k.get("_code", 1),
            chat_turn=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("fix round ran!")),
            build_fix_message=lambda *a, **k: "fix me",
            is_unrunnable_failure=nova.is_unrunnable_failure,
            _looks_like_server=nova._looks_like_server,
            # v8.8: the fix-loop brake rides in the same block - the real
            # implementations operate on sess.fix_rounds, which the harness
            # sess carries
            fix_budget_left=nova.fix_budget_left,
            bump_fix_round=nova.bump_fix_round,
            reset_fix_rounds=nova.reset_fix_rounds,
            MAX_FIX_ROUNDS=nova.MAX_FIX_ROUNDS,
            c=nova.c, C=nova.C, TOKEN_SINK=None, EVENT_SINK=None,
        )
        # run_command's return code is set per-test via a mutable cell
        self._code = {"v": 1}
        stub.run_command = lambda *a, **k: self._code["v"]
        web_server.nova = stub
        self.sess = types.SimpleNamespace(
            touched={}, pending_apply=None, autofix=True,
            last_failed=None, confirm_changes=False, fix_rounds=0)
        web_server.STATE = types.SimpleNamespace(sess=self.sess)
        self.addCleanup(self._restore_state)

    def _restore_state(self):
        # single cleanup, ordered: the real nova module goes back FIRST,
        # then a fresh _State (whose __init__ calls nova.Session) — LIFO
        # cleanups would otherwise rebuild _State under the stub
        web_server.nova = self._old_nova
        web_server.STATE = self._old_state

    def _drive(self, last_failed, run_exit):
        self._code["v"] = run_exit
        self.sess.last_failed = last_failed
        h = object.__new__(web_server.Handler)
        events = []
        h._emit = events.append
        h._run_turn("run", "cmd")
        return events

    def test_real_code_error_fires_exactly_one_fix_round(self):
        rounds = []
        web_server.nova.chat_turn = lambda *a, **k: (rounds.append(1) or
                                                     {"files": [], "edits": [], "applied": []})
        events = self._drive(dict(self.CODE_ERROR), run_exit=1)
        self.assertEqual(len(rounds), 1)
        errs = [e for e in events if e.get("t") == "err"]
        self.assertEqual(errs, [])
        # the done event always lands (a broken turn must never kill it)
        dones = [e for e in events if e.get("t") == "done"]
        self.assertEqual(len(dones), 1)
        self.assertEqual(dones[0].get("run_exit"), 1)

    def test_unrunnable_failure_skips_the_fix_round(self):
        events = self._drive(dict(self.NOT_FOUND), run_exit=127)
        done = [e for e in events if e.get("t") == "done"][0]
        self.assertNotIn("autofix", done)
        self.assertEqual(done.get("run_exit"), 127)
        self.assertEqual([e for e in events if e.get("t") == "err"], [])

    def test_server_command_skips_the_fix_round(self):
        events = self._drive(dict(self.SERVER), run_exit=1)
        done = [e for e in events if e.get("t") == "done"][0]
        self.assertNotIn("autofix", done)
        self.assertEqual(done.get("run_exit"), 1)

    def test_timeout_skips_the_fix_round(self):
        events = self._drive(dict(self.TIMEOUT), run_exit=-1)
        done = [e for e in events if e.get("t") == "done"][0]
        self.assertNotIn("autofix", done)

    def test_source_pins_match_the_behavior(self):
        src = (APP / "web_server.py").read_text(encoding="utf-8")
        self.assertIn('sess.last_failed.get("code") == "timeout"', src)
        self.assertIn("nova.is_unrunnable_failure", src)
        self.assertIn("nova._looks_like_server", src)
        first_fix = src.index("[autofix] the run failed")
        self.assertLess(src.index("nova.is_unrunnable_failure"), first_fix)


class TestE2EEditAfterRun(unittest.TestCase):
    """The user's journey, end to end on the real pipeline."""

    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_installed = nova.list_installed_models
        self._old_ni = nova.NONINTERACTIVE
        self.addCleanup(setattr, nova, "stream_chat", self._old_stream)
        self.addCleanup(setattr, nova, "list_installed_models",
                        self._old_installed)
        self.addCleanup(setattr, nova, "NONINTERACTIVE", self._old_ni)
        nova.list_installed_models = lambda: []
        nova.NONINTERACTIVE = True
        self.ws = _tmp_ws(self)
        self.sess = nova.Session(self.ws)
        self.sess.model = "fake:7b"
        self.sess._local_brain = lambda: True
        self._answers = []

    def _turn(self, user_msg):
        ans, self._answers = self._answers[0], self._answers[1:]
        nova.stream_chat = lambda model, msgs, mode, sess=None, section=None, \
            quiet=False: (ans, True)
        return nova.chat_turn(self.sess, user_msg, auto=True)

    def test_build_run_edit_run_survives(self):
        index = self.ws / "index.html"
        # 1. build
        self._answers = [GOOD_SITE]
        r1 = self._turn("یک سایت بساز")
        self.assertIn("index.html", r1["applied"])
        self.assertTrue(_valid_html(index.read_text(encoding="utf-8")))
        # 2. Run click on the preview hint opens the browser, no shell
        opened = []
        with mock.patch.object(nova, "open_browser",
                               side_effect=lambda url: opened.append(url)):
            self.assertEqual(nova.run_command(
                self.sess, r1["run_cmd"], auto=True, origin="web"), 0)
        self.assertEqual(len(opened), 1)
        # 3. ask for an edit
        self._answers = [EDIT_NO_HINT]
        r2 = self._turn("ویرایشش کن")
        self.assertIn("index.html", r2["applied"])
        body = index.read_text(encoding="utf-8")
        self.assertIn("فروش ویژه", body)
        self.assertTrue(_valid_html(body))
        # the Run chip survived the edit turn
        self.assertEqual(r2["run_cmd"], "index.html")
        # 4. a broken full rewrite is refused whole - the site stays intact
        broken = GOOD_SITE.replace("فروشگاه من</h1>", 'فروشگاه من</h1>\n<script>')
        self._answers = [broken]
        r3 = self._turn("کلا عوضش کن")
        self.assertEqual(r3["applied"], [])
        self.assertTrue(_valid_html(index.read_text(encoding="utf-8")))

    def test_unclosed_edit_turn_still_edits(self):
        index = self.ws / "index.html"
        self._answers = [GOOD_SITE]
        self._turn("یک سایت بساز")
        unclosed = ("ویرایش شد.\n\n=== EDIT: index.html ===\n"
                    "<<<<<<< SEARCH\n<p id=\"slogan\">بهترین محصولات</p>\n"
                    "=======\n<p id=\"slogan\">حراج جمعه</p>\n"
                    ">>>>>>> REPLACE")
        self._answers = [unclosed]
        r = self._turn("ویرایش بدون اند")
        self.assertIn("index.html", r["applied"])
        self.assertIn("حراج جمعه", index.read_text(encoding="utf-8"))


class TestVersionPin(unittest.TestCase):
    def test_version_is_770(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
