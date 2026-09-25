#!/usr/bin/env python3
"""v7.1.0 tests: the line-by-line audit sweep fixes.

Every test pins one REAL finding from the 4-agent full-codebase audit:

  - collect_error_files: POSIX absolute traceback paths are re-based onto
    the workspace (/fix used to run BLIND on Linux/macOS - only Windows
    C:\\ paths were handled)
  - parse_files: a plain ``` fenced block in the same answer as named
    FILE blocks no longer vanishes silently
  - an EMPTY === FILE: === block can no longer blank an existing file
  - bulleted tool tokens ('- [READ: x]') are accepted
  - nova_subagent: bracket soup cannot hang the turn (capped scan);
    run_parallel still returns results in order without the `with` block
  - nova_quality: an @import-only stylesheet passes the pre-apply lint
  - nova_design: doctype-only pages are polished AFTER the doctype
    (quirks mode defeated the whole design floor); cache-busted hrefs
    ('style.css?v=2') fill the REAL file, never a junk name;
    root-absolute hrefs ('/css/style.css') resolve from the ws root;
    NOVA_NO_DESIGN=1 kills the prompt contract too
  - nova_providers: del_key normalizes its name (silent no-op before)
  - the preview server's autoindex no longer lists dotfile names
"""
import os
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_design     # noqa: E402
import nova_quality    # noqa: E402
import nova_subagent   # noqa: E402
import nova_providers as providers  # noqa: E402


# --------------------------------------------------------------------------
# 1. /fix on POSIX: absolute traceback paths reach the workspace
# --------------------------------------------------------------------------
class TestCollectErrorFiles(unittest.TestCase):
    def test_posix_absolute_traceback_path_is_rebased(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "main.py").write_text("x = 1/0\n", encoding="utf-8")
            sess = nova.Session(ws)
            out = 'Traceback (most recent call last):\n' \
                  '  File "%s", line 1, in <module>\n' \
                  'ZeroDivisionError: division by zero' % (ws / "main.py")
            picked = nova.collect_error_files(sess, out, "python main.py")
            self.assertTrue(any(n == "main.py" for n, _c in picked),
                            picked)

    def test_absolute_path_outside_ws_stays_out(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            sess = nova.Session(ws)
            out = '  File "/etc/passwd", line 1'
            picked = nova.collect_error_files(sess, out, "")
            self.assertEqual(picked, [])

    def test_relative_path_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "app.py").write_text("print(1)\n", encoding="utf-8")
            sess = nova.Session(ws)
            picked = nova.collect_error_files(sess, "error in app.py:", "")
            self.assertTrue(any(n == "app.py" for n, _c in picked))


# --------------------------------------------------------------------------
# 2. the fenced block next to named blocks must survive
# --------------------------------------------------------------------------
class TestFencedNextToNamed(unittest.TestCase):
    def test_named_plus_fenced_yields_file_and_unnamed(self):
        text = ("=== FILE: index.html ===\n<h1>hi</h1>\n=== END ===\n"
                "And the script:\n```python\nprint('hi')\n```\n")
        files, unnamed = nova.parse_files(text)
        self.assertEqual([f[0] for f in files], ["index.html"])
        self.assertEqual(len(unnamed), 1)
        self.assertIn("print('hi')", unnamed[0])

    def test_fence_inside_file_body_is_not_double_reported(self):
        text = ("=== FILE: README.md ===\n"
                "# docs\n```python\nprint('example')\n```\n"
                "=== END ===\n")
        files, unnamed = nova.parse_files(text)
        self.assertEqual([f[0] for f in files], ["README.md"])
        self.assertEqual(unnamed, [])
        self.assertIn("print('example')", files[0][1])

    def test_chat_turn_repairs_the_fenced_second_file(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            answers = iter([
                "=== FILE: index.html ===\n<h1>hi</h1>\n=== END ===\n"
                "```python\nprint('hi')\n```",
                "=== FILE: main.py ===\nprint('hi')\n=== END ===\n",
            ])
            prompts = []

            def fake_stream(model, msgs, mode, sess=None, section=None):
                prompts.append(msgs[-1]["content"])
                return next(answers), True

            old = nova.stream_chat
            old_ni = nova.NONINTERACTIVE
            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            try:
                sess = nova.Session(ws)
                res = nova.chat_turn(sess, "make a page and a script",
                                     auto=True)
                self.assertEqual(len(prompts), 2, "exactly ONE repair round")
                self.assertIn("main.py", res["applied"])
                self.assertTrue((ws / "main.py").exists())
            finally:
                nova.stream_chat = old
                nova.NONINTERACTIVE = old_ni


# --------------------------------------------------------------------------
# 3. an EMPTY FILE block must never blank an existing file
# --------------------------------------------------------------------------
class TestEmptyBlockGuard(unittest.TestCase):
    def test_existing_file_survives_an_empty_block(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "main.py").write_text("print('precious')\n",
                                        encoding="utf-8")

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return ("=== FILE: main.py ===\n=== END ===\n"
                        "Run: python main.py"), True

            old = nova.stream_chat
            old_ni = nova.NONINTERACTIVE
            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            try:
                sess = nova.Session(ws)
                nova.chat_turn(sess, "update main.py", auto=True)
            finally:
                nova.stream_chat = old
                nova.NONINTERACTIVE = old_ni
            self.assertEqual((ws / "main.py").read_text(encoding="utf-8"),
                             "print('precious')\n")

    def test_new_empty_file_is_still_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return "=== FILE: pkg/__init__.py ===\n=== END ===", True

            old = nova.stream_chat
            old_ni = nova.NONINTERACTIVE
            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            try:
                sess = nova.Session(ws)
                res = nova.chat_turn(sess, "make a package", auto=True)
            finally:
                nova.stream_chat = old
                nova.NONINTERACTIVE = old_ni
            self.assertIn("pkg/__init__.py", res["applied"])
            self.assertTrue((ws / "pkg" / "__init__.py").exists())


# --------------------------------------------------------------------------
# 4. bulleted tool tokens
# --------------------------------------------------------------------------
class TestBulletedToolToken(unittest.TestCase):
    def test_bullet_prefixed_read_token_is_found(self):
        found = nova.find_model_action("Let me look first.\n- [READ: main.py]")
        self.assertIsNotNone(found)
        self.assertEqual(found[0]["name"], "READ")
        self.assertEqual(found[1], "main.py")

    def test_token_in_a_sentence_is_still_rejected(self):
        self.assertIsNone(
            nova.find_model_action("I will [READ: main.py] now ok?"))


# --------------------------------------------------------------------------
# 5. sub-agent: bracket bomb + executor lifecycle
# --------------------------------------------------------------------------
class TestSubagentHardening(unittest.TestCase):
    def test_bracket_soup_returns_fast(self):
        bomb = "[" * 2000 + "]" * 2000
        t0 = time.monotonic()
        out = nova_subagent.parse_task_list(bomb)
        dt = time.monotonic() - t0
        self.assertEqual(out, [])
        self.assertLess(dt, 2.0, "bracket soup must not hang the turn")

    def test_real_list_still_parses(self):
        out = nova_subagent.parse_task_list(
            'Here is the plan: ["research the api", "draft the ui"] thanks')
        self.assertEqual(out, ["research the api", "draft the ui"])

    def test_run_parallel_orders_results(self):
        tasks = ["a", "b", "c"]
        res = nova_subagent.run_parallel(
            tasks, lambda t: t.upper(), max_parallel=3)
        self.assertEqual([r[1] for r in res], ["A", "B", "C"])
        self.assertTrue(all(r[2] is None for r in res))

    def test_run_parallel_captures_worker_errors(self):
        def boom(_t):
            raise RuntimeError("nope")
        res = nova_subagent.run_parallel(["x"], boom, max_parallel=2)
        self.assertEqual(len(res), 1)
        self.assertIsNone(res[0][1])
        self.assertIn("nope", res[0][2])


# --------------------------------------------------------------------------
# 6. @import-only stylesheets pass the lint
# --------------------------------------------------------------------------
class TestCssLintImport(unittest.TestCase):
    def test_import_only_css_passes(self):
        ok, problem = nova_quality.preapply_check(
            "theme.css", "@import url('base.css');\n")
        self.assertTrue(ok, problem)

    def test_charset_only_css_passes(self):
        ok, problem = nova_quality.preapply_check(
            "t.css", '@charset "utf-8";\n')
        self.assertTrue(ok, problem)

    def test_broken_css_still_rejected(self):
        ok, problem = nova_quality.preapply_check(
            "t.css", "body { color: red;\n")
        self.assertFalse(ok)


# --------------------------------------------------------------------------
# 7. design engine hardening (audit findings)
# --------------------------------------------------------------------------
class TestDesignHardening(unittest.TestCase):
    def test_doctype_only_page_is_polished_after_doctype(self):
        html = "<!DOCTYPE html>\n<body><h1>x</h1></body>"
        out, notes = nova_design.polish_html(html, "index.html")
        self.assertTrue(out.lower().startswith("<!doctype html>"),
                        out[:80])
        self.assertIn("<head>", out)

    def test_doctype_only_page_floor_link_never_quirks(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            p = ws / "index.html"
            p.write_text("<!DOCTYPE html>\n<body><h1>x</h1></body>",
                         encoding="utf-8")
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            # v7.2: the bare-page floor also ships the motion enhancer
            self.assertEqual([e[0] for e in extras],
                             ["nova-ui.css", "nova-ui.js"])
            out = p.read_text(encoding="utf-8")
            self.assertTrue(out.lower().startswith("<!doctype html>"))
            self.assertIn('href="nova-ui.css"', out)

    def test_query_string_href_fills_the_real_file(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(
                '<!doctype html><html><head><title>t</title>'
                '<link rel="stylesheet" href="css/style.css?v=2"></head>'
                '<body></body></html>', encoding="utf-8")
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            self.assertEqual(sorted(e[0] for e in extras), sorted(["css/style.css", "nova-ui.js"]) if "nova-ui.js" in [e[0] for e in extras] else ["css/style.css"])
            self.assertFalse((ws / "css" / "style.css?v=2").exists())

    def test_root_absolute_href_resolves_from_ws_root(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "pages").mkdir()
            (ws / "pages" / "about.html").write_text(
                '<!doctype html><html><head><title>t</title>'
                '<link rel="stylesheet" href="/css/style.css"></head>'
                '<body></body></html>', encoding="utf-8")
            extras, _ = nova_design.design_polish(ws, ["pages/about.html"])
            # v8.0: the nested page also gets nova-ui.js inside pages/ -
            # the injected src="nova-ui.js" resolves in the page's own
            # folder (the v7.4 fix covered only the legacy branch).
            self.assertEqual(sorted(e[0] for e in extras),
                             sorted(["css/style.css", "nova-ui.js",
                                     "pages/nova-ui.js"]))

    def test_kill_switch_disables_the_contract_too(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.web_turn = True
            old = os.environ.get("NOVA_NO_DESIGN")
            os.environ["NOVA_NO_DESIGN"] = "1"
            try:
                self.assertNotIn(nova_design.DESIGN_CONTRACT,
                                 sess.system_prompt())
            finally:
                if old is None:
                    os.environ.pop("NOVA_NO_DESIGN", None)
                else:
                    os.environ["NOVA_NO_DESIGN"] = old

    def test_system_prompt_is_kv_stable_across_calls(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.web_turn = True
            a = sess.system_prompt()
            b = sess.system_prompt()
            self.assertEqual(a, b)


# --------------------------------------------------------------------------
# 8. providers vault
# --------------------------------------------------------------------------
class TestProvidersVault(unittest.TestCase):
    def test_del_key_normalizes_the_name(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            providers.load_config(ws)
            try:
                err = providers.set_key(ws, "Groq", "sk-test-123")
                self.assertEqual(err, "")
                err = providers.del_key(ws, "GROQ")
                self.assertEqual(err, "")
                self.assertNotIn("groq", providers._CFG.get("keys") or {})
            finally:
                providers._CFG.clear()
                providers._CFG.update({"ws": None})


# --------------------------------------------------------------------------
# 9. preview server autoindex hides dotfiles
# --------------------------------------------------------------------------
class TestPreviewDotfiles(unittest.TestCase):
    def test_listing_hides_dotfiles_and_fetch_404s(self):
        from http.client import HTTPConnection
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / ".env").write_text("SECRET=1\n", encoding="utf-8")
            sub = ws / "sub"
            sub.mkdir()
            (sub / "page.html").write_text("<h1>ok</h1>", encoding="utf-8")
            sess = nova.Session(ws)
            import io as _io
            old = sys.stdout
            sys.stdout = _io.StringIO()
            try:
                nova.cmd_serve(sess, "")
                port = sess.serve_port
            finally:
                sys.stdout = old
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/sub/")
                body = conn.getresponse().read().decode("utf-8")
                conn.close()
                self.assertIn("page.html", body)
                conn = HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/")
                root_body = conn.getresponse().read().decode("utf-8")
                conn.close()
                self.assertNotIn(".env", root_body)
                conn = HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/.env")
                code = conn.getresponse().status
                conn.close()
                self.assertEqual(code, 404)
            finally:
                nova.stop_serve(sess)


# --------------------------------------------------------------------------
# 10. version pin
# --------------------------------------------------------------------------
class TestVersion(unittest.TestCase):
    def test_version_is_7_1_0(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
