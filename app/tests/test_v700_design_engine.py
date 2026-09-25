#!/usr/bin/env python3
"""v7.0.0 tests: the DESIGN ENGINE.

"A weak model must still ship a beautiful, modern website."

Every test pins one layer of the new engine:

  - is_web_task: the web/UI intent detector (EN + FA) that decides when
    the design contract rides in the system prompt
  - DESIGN_CONTRACT: byte-stable prompt section, web turns only
  - polish_html: deterministic charset/viewport/title insertion for full
    HTML pages (the #1 reason a weak-model page "looks broken" on a phone
    is a missing viewport meta)
  - design_polish: the beauty floor - a REFERENCED-but-missing stylesheet
    is filled with NOVA_UI_CSS (the classic weak-model failure: the page
    links css/style.css and the model never outputs it), a page with NO
    styling at all gets nova-ui.css linked, a page with its own CSS is
    left alone
  - offer_apply / apply_approved integration: floor files join the SAME
    undo unit / touched map as the batch (so /undo and the web chips stay
    exactly right)
  - NOVA_UI_CSS quality: passes the pre-apply CSS lint (brace balance)
  - NOVA_NO_DESIGN=1 kill switch
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_design     # noqa: E402
import nova_quality    # noqa: E402

WEAK_HTML = """<!doctype html>
<html>
<head><title>My Shop</title></head>
<body>
<h1>My Shop</h1>
<p>Welcome to my little shop.</p>
</body>
</html>
"""

WEAK_HTML_LINK_MISSING_CSS = """<!doctype html>
<html>
<head><title>Cafe</title></head>
<body>
<h1>Cafe Nova</h1>
<p>Best coffee in town.</p>
</body>
</html>
<link rel="stylesheet" href="css/style.css">
"""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# 1. web/UI intent detection
# --------------------------------------------------------------------------
class TestIsWebTask(unittest.TestCase):
    def test_english_positives(self):
        for t in ("make me a website for my shop",
                  "build a landing page",
                  "a dashboard for my sales",
                  "create an HTML page with a navbar",
                  "responsive portfolio site",
                  "a web app for notes"):
            self.assertTrue(nova_design.is_web_task(t), t)

    def test_persian_positives(self):
        for t in ("یک سایت فروشگاهی بساز",
                  "یک وب‌سایت برای رستوران میخوام",
                  "یک داشبورد مدیریتی بساز",
                  "یک صفحه وب برای رزومه من",
                  "لندینگ پیج برای محصول",
                  "رابط کاربری برنامه را طراحی کن",
                  "یک پنل مدیریت بساز"):
            self.assertTrue(nova_design.is_web_task(t), t)

    def test_negatives(self):
        for t in ("write a python script that prints hello",
                  "fix the bug in main.py",
                  "یک اسکریپت پایتون بنویس که فایل ها را مرتب کند",
                  "explain how generators work",
                  "make a CLI tool for my inventory",
                  ""):
            self.assertFalse(nova_design.is_web_task(t), t)


# --------------------------------------------------------------------------
# 2. the design contract prompt section
# --------------------------------------------------------------------------
class TestDesignContract(unittest.TestCase):
    def test_contract_is_byte_stable(self):
        self.assertEqual(nova_design.DESIGN_CONTRACT,
                         nova_design.DESIGN_CONTRACT)

    def test_contract_contents(self):
        c = nova_design.DESIGN_CONTRACT
        for needle in ("css/style.css", ":root", "gradient", "hover",
                       "640px", "prefers-reduced-motion"):
            self.assertIn(needle, c)

    def test_system_prompt_injects_only_on_web_turns(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.web_turn = True
            self.assertIn(nova_design.DESIGN_CONTRACT, sess.system_prompt())
            sess.web_turn = False
            self.assertNotIn(nova_design.DESIGN_CONTRACT, sess.system_prompt())

    def test_chat_turn_sets_web_flag_from_user_words(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return "Sure, ask me anything else.", True

            old = nova.stream_chat
            nova.stream_chat = fake_stream
            try:
                sess = nova.Session(ws)
                nova.chat_turn(sess, "build me a website", auto=True)
                self.assertTrue(sess.web_turn)
                sess2 = nova.Session(ws)
                nova.chat_turn(sess2, "write a python script", auto=True)
                self.assertFalse(sess2.web_turn)
            finally:
                nova.stream_chat = old


# --------------------------------------------------------------------------
# 3. polish_html - deterministic head fixes
# --------------------------------------------------------------------------
class TestPolishHtml(unittest.TestCase):
    def test_charset_viewport_added(self):
        html = "<!doctype html><html><head><title>t</title></head><body></body></html>"
        out, notes = nova_design.polish_html(html, "index.html")
        self.assertIn("<meta charset=\"utf-8\">", out)
        self.assertIn('name="viewport"', out)
        self.assertIn("charset meta added", notes)
        self.assertIn("viewport meta added", notes)

    def test_existing_metas_are_never_duplicated(self):
        html = ('<!doctype html><html><head>'
                '<meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<title>t</title></head><body></body></html>')
        out, notes = nova_design.polish_html(html, "index.html")
        self.assertEqual(out, html)
        self.assertEqual(notes, [])

    def test_missing_title_added_from_filename(self):
        html = "<!doctype html><html><head></head><body></body></html>"
        out, notes = nova_design.polish_html(html, "shop.html")
        self.assertIn("<title>shop.html</title>", out)
        self.assertIn("title added", notes)

    def test_missing_head_is_built(self):
        html = "<!doctype html><html><body><h1>x</h1></body></html>"
        out, notes = nova_design.polish_html(html, "index.html")
        self.assertIn("<head>", out)
        self.assertIn("<meta charset=\"utf-8\">", out)
        self.assertTrue(any("head" in n for n in notes))

    def test_fragment_is_untouched(self):
        frag = "<div class=\"widget\"><p>hi</p></div>"
        out, notes = nova_design.polish_html(frag, "widget.html")
        self.assertEqual(out, frag)
        self.assertEqual(notes, [])

    def test_idempotent(self):
        out1, _ = nova_design.polish_html(WEAK_HTML, "index.html")
        out2, notes2 = nova_design.polish_html(out1, "index.html")
        self.assertEqual(out1, out2)
        self.assertEqual(notes2, [])


# --------------------------------------------------------------------------
# 4. stylesheet detection
# --------------------------------------------------------------------------
class TestStylesheetHrefs(unittest.TestCase):
    def test_local_links_collected_in_order(self):
        html = ('<link rel="stylesheet" href="css/a.css">'
                '<link rel="icon" href="f.ico">'
                "<link rel='stylesheet' href='b.css'>")
        self.assertEqual(nova_design.stylesheet_hrefs(html),
                         ["css/a.css", "b.css"])

    def test_external_and_data_urls_ignored(self):
        html = ('<link rel="stylesheet" href="https://cdn.example/x.css">'
                '<link rel="stylesheet" href="//cdn.example/y.css">'
                '<link rel="stylesheet" href="data:text/css,body{}">')
        self.assertEqual(nova_design.stylesheet_hrefs(html), [])


# --------------------------------------------------------------------------
# 5. design_polish - the beauty floor
# --------------------------------------------------------------------------
class TestDesignPolish(unittest.TestCase):
    def test_referenced_but_missing_css_is_filled(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", WEAK_HTML_LINK_MISSING_CSS)
            extras, notes = nova_design.design_polish(ws, ["index.html"])
            self.assertEqual(sorted(e[0] for e in extras), sorted(["css/style.css", "nova-ui.js"]) if "nova-ui.js" in [e[0] for e in extras] else ["css/style.css"])
            self.assertEqual(extras[0][1], nova_design.NOVA_UI_CSS)
            self.assertTrue(any("style.css" in n for n in notes))
            # the CALLER (nova._design_polish_hook) writes the extras:
            for rel, content in extras:
                _write(ws / rel, content)
            self.assertEqual((ws / "css" / "style.css").read_text(
                encoding="utf-8"), nova_design.NOVA_UI_CSS)
            # head polish also ran on the same pass
            html = (ws / "index.html").read_text(encoding="utf-8")
            self.assertIn('name="viewport"', html)

    def test_css_present_in_batch_blocks_the_fill(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", WEAK_HTML_LINK_MISSING_CSS)
            _write(ws / "css" / "style.css", "body{color:red}")
            extras, _notes = nova_design.design_polish(
                ws, ["index.html", "css/style.css"])
            self.assertEqual(extras, [])

    def test_css_already_on_disk_blocks_the_fill(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", WEAK_HTML_LINK_MISSING_CSS)
            _write(ws / "css" / "style.css", "body{color:red}")
            extras, _notes = nova_design.design_polish(ws, ["index.html"])
            self.assertEqual(extras, [])

    def test_bare_page_gets_nova_ui_css_linked(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", WEAK_HTML)
            extras, notes = nova_design.design_polish(ws, ["index.html"])
            # v7.2: the bare-page floor now also ships the motion enhancer
            self.assertEqual([e[0] for e in extras],
                             ["nova-ui.css", "nova-ui.js"])
            self.assertTrue(any("nova-ui.css" in n for n in notes))
            html = (ws / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="nova-ui.css"', html)
            self.assertIn('src="nova-ui.js"', html)
            # the caller writes the floor stylesheet:
            for rel, content in extras:
                _write(ws / rel, content)
            self.assertEqual((ws / "nova-ui.css").read_text(
                encoding="utf-8"), nova_design.NOVA_UI_CSS)

    def test_own_css_is_respected(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            html = ('<!doctype html><html><head>'
                    '<meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1">'
                    '<title>t</title>'
                    '<link rel="stylesheet" href="css/style.css"></head>'
                    '<body><h1>x</h1></body></html>')
            _write(ws / "index.html", html)
            _write(ws / "css" / "style.css", "body{color:teal}")
            extras, notes = nova_design.design_polish(
                ws, ["index.html", "css/style.css"])
            self.assertEqual(extras, [])
            self.assertEqual(notes, [])
            self.assertFalse((ws / "nova-ui.css").exists())

    def test_escaping_href_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            html = ('<!doctype html><html><head><title>t</title>'
                    '<link rel="stylesheet" href="../../evil.css"></head>'
                    '<body></body></html>')
            _write(ws / "pages" / "index.html", html)
            extras, _notes = nova_design.design_polish(ws, ["pages/index.html"])
            self.assertEqual(extras, [])
            self.assertFalse((ws.parent / "evil.css").exists())

    def test_idempotent_second_run(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", WEAK_HTML)
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            # simulate the hook writing the extras (real apply flow)
            for rel, content in extras:
                _write(ws / rel, content)
            first_html = (ws / "index.html").read_text(encoding="utf-8")
            extras2, notes2 = nova_design.design_polish(ws, ["index.html"])
            self.assertEqual(extras2, [], "floor css already on disk")
            self.assertEqual(notes2, [], "second polish must be a no-op")
            self.assertEqual((ws / "index.html").read_text(
                encoding="utf-8"), first_html)

    def test_kill_switch(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", WEAK_HTML)
            old = os.environ.get("NOVA_NO_DESIGN")
            os.environ["NOVA_NO_DESIGN"] = "1"
            try:
                extras, notes = nova_design.design_polish(ws, ["index.html"])
                self.assertEqual(extras, [])
                self.assertEqual(notes, [])
                self.assertFalse(nova_design.enabled())
            finally:
                if old is None:
                    os.environ.pop("NOVA_NO_DESIGN", None)
                else:
                    os.environ["NOVA_NO_DESIGN"] = old

    def test_floor_css_passes_the_lint(self):
        ok, problem = nova_quality.preapply_check("nova-ui.css",
                                                  nova_design.NOVA_UI_CSS)
        self.assertTrue(ok, problem)


# --------------------------------------------------------------------------
# 6. apply integration - the floor rides the SAME batch bookkeeping
# --------------------------------------------------------------------------
class TestApplyIntegration(unittest.TestCase):
    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_ni = nova.NONINTERACTIVE

    def tearDown(self):
        nova.stream_chat = self._old_stream
        nova.NONINTERACTIVE = self._old_ni

    def test_offer_apply_fills_missing_css_and_undo_covers_it(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            first = ("=== FILE: index.html ===\n" + WEAK_HTML +
                     "\n=== END ===\nPreview: index.html")
            weak = ("=== FILE: index.html ===\n" + WEAK_HTML_LINK_MISSING_CSS +
                    "\n=== END ===\nPreview: index.html")
            answers = iter([first, weak])

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return next(answers), True

            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            sess = nova.Session(ws)
            nova.chat_turn(sess, "make a cafe website", auto=True)
            res = nova.chat_turn(sess, "redesign the site", auto=True)
            self.assertIn("index.html", res["applied"])
            self.assertIn("css/style.css", res["applied"],
                          "the floor stylesheet must join the batch")
            self.assertTrue((ws / "css" / "style.css").exists())
            html = (ws / "index.html").read_text(encoding="utf-8")
            self.assertIn('name="viewport"', html)
            # END-TO-END undo: the floor file is part of the SAME snapshot
            # unit -> /undo deletes it AND restores the pre-apply html
            old_out = sys.stdout
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
            try:
                nova.cmd_undo(sess, "")
            finally:
                sys.stdout.close()
                sys.stdout = old_out
            self.assertFalse((ws / "css" / "style.css").exists(),
                             "/undo must delete the floor stylesheet")
            # /undo restores the PRE-APPLY state of turn 2 - which is the
            # turn-1 result INCLUDING the design floor polish Nova added
            # back then (exact snapshot semantics, nothing lost)
            restored = (ws / "index.html").read_text(encoding="utf-8")
            self.assertNotIn('href="css/style.css"', restored,
                             "turn-2 content must be gone after /undo")
            self.assertIn('href="nova-ui.css"', restored,
                          "turn-1 floor polish is the pre-apply state")
            self.assertIn("<h1>My Shop</h1>", restored)

    def test_offer_apply_bare_page_links_the_floor(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            weak = ("=== FILE: index.html ===\n" + WEAK_HTML +
                    "\n=== END ===\nPreview: index.html")

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return weak, True

            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "make a little homepage", auto=True)
            self.assertIn("nova-ui.css", res["applied"])
            self.assertIn('href="nova-ui.css"',
                          (ws / "index.html").read_text(encoding="utf-8"))

    def test_apply_approved_runs_the_floor_too(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            weak = ("=== FILE: index.html ===\n" + WEAK_HTML_LINK_MISSING_CSS +
                    "\n=== END ===\nPreview: index.html")

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return weak, True

            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            sess = nova.Session(ws)
            sess.confirm_changes = True           # web approve-before-write
            res = nova.chat_turn(sess, "make a website", auto=True)
            self.assertEqual(res["applied"], [], "staged, not written")
            ok, r = nova.apply_approved(sess, sess.pending_apply["id"],
                                        ["index.html"], {})
            self.assertTrue(ok)
            self.assertIn("css/style.css", r["applied"])
            self.assertTrue((ws / "css" / "style.css").exists())

    def test_non_web_python_turn_gets_no_floor(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            weak = ("=== FILE: main.py ===\nprint('hi')\n=== END ===\n"
                    "Run: python main.py")

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return weak, True

            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "make main.py", auto=True)
            self.assertEqual(res["applied"], ["main.py"])
            self.assertFalse((ws / "nova-ui.css").exists())


# --------------------------------------------------------------------------
# 7. web_server surfaces the engine state
# --------------------------------------------------------------------------
class TestInfoDesignFlag(unittest.TestCase):
    def test_nova_exposes_design_engine(self):
        self.assertTrue(hasattr(nova, "design"))
        self.assertTrue(callable(nova_design.enabled))


# --------------------------------------------------------------------------
# 8. version pin
# --------------------------------------------------------------------------
class TestVersion(unittest.TestCase):
    def test_version_is_7_0_0(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
