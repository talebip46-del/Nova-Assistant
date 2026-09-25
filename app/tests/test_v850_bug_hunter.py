#!/usr/bin/env python3
# =====================================================================
#  Nova v8.11.0 "bug hunter" regression tests:
#   - nova_probe WIRING: the element graph across html/js/css - dead
#     id lookups, dead inline handlers, toggled-but-undefined classes,
#     missing local files (advisory: the design floor heals styles),
#     python relative imports, node require("./x"), the browser-global
#     allowlist, minified/binary skip, line numbers.
#   - nova_probe SMOKE: real subprocess runs - crash -> error finding,
#     clean exit -> pass, interactive input -> info (not a bug),
#     endless loop -> warn, entry picking rules (no tests/, no dom-js),
#     the NOVA_PROBE_RUN=0 kill-switch.
#   - nova_probe BROWSER: honest skips (no html / playwright off);
#     the real headless run only when Playwright exists on this box.
#   - nova_probe COMPLETENESS: the local-brain supervisor - fake brain
#     JSON parsing, gap extraction, garbage answers never crash, the
#     wiring skeletons (html ids/buttons, py defs, js functions).
#   - settings: .nova/probe.json roundtrip + validation + reset,
#     master_on + the NOVA_PROBE=0 kill-switch.
#   - orchestrators: pre_apply_gate (reject + exact repair prompt),
#     run_post_apply verdicts + findings_summary + report_lines.
#   - nova.py integration: the pre-apply wiring gate (dead batch ->
#     NOTHING written + one-shot repair context + probe_reject event),
#     healthy bundles pass (also with the design floor's own extras),
#     the post-apply behavior sweep wiring, _feedback_fix_note hunter
#     lines, /probe in TOOLS, /status line, web_probe_state, the web
#     surface (/api/info probe block, /api/settings probe fields,
#     panel ids), absolute/pip imports never false-reject.
#  Everything is offline: NOVA_PROBE_RUN/BROWSER + NOVA_GUARDIAN_WEB
#  are pinned in setUp (the dedicated subprocess test re-enables RUN).
# =====================================================================
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["NOVA_GUARDIAN_WEB"] = "0"     # the suite is offline
os.environ["NOVA_PROBE_RUN"] = "0"        # no subprocess runs by default
os.environ["NOVA_PROBE_BROWSER"] = "0"    # no headless browser by default

import nova                    # noqa: E402
import nova_probe as pb        # noqa: E402
import nova_think              # noqa: E402

APP = Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


# =====================================================================
# 1. the wiring probe
# =====================================================================
class TestWiring(unittest.TestCase):
    def test_dead_id_is_an_error_with_line_number(self):
        r = pb.wiring_check([
            ("index.html", '<html><body><p>hi</p></body></html>'),
            ("app.js", 'let a = 1;\nlet b = 2;\n'
                       'document.getElementById("missingBox");')])
        self.assertEqual(len(r["errors"]), 1)
        f, line, msg = r["errors"][0]
        self.assertEqual(f, "app.js")
        self.assertEqual(line, 3)
        self.assertIn("#missingBox", msg)
        self.assertIn("dead reference", msg)

    def test_defined_id_is_clean(self):
        r = pb.wiring_check([
            ("index.html", '<div id="app"></div>'),
            ("app.js", 'document.getElementById("app");')])
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["warns"], [])

    def test_template_literal_and_id_assignment_define_ids(self):
        js = ('el.innerHTML = "<div id=\'dynamicCard\'>x</div>";\n'
              'other.id = "secondOne";\n'
              'document.getElementById("dynamicCard");\n'
              'document.getElementById("secondOne");')
        r = pb.wiring_check([("app.js", js)])
        self.assertEqual(r["errors"], [])

    def test_query_selector_dead_id_is_an_error(self):
        r = pb.wiring_check([
            ("app.js", 'document.querySelector("#ghostPanel");')])
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("#ghostPanel", r["errors"][0][2])

    def test_composite_selector_class_miss_warns(self):
        # '#list .item' -> #list is the id, .item is a CLASS - a miss on
        # the class is advisory, a miss on the id would be an error
        r = pb.wiring_check([
            ("index.html", '<div id="list"></div>'),
            ("app.js", 'document.querySelectorAll("#list .item");')])
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("item" in m for _f, _l, m in r["warns"]))

    def test_dead_inline_handler_is_an_error(self):
        r = pb.wiring_check([
            ("index.html", '<button onclick="startApp()">go</button>')])
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("startApp", r["errors"][0][2])
        self.assertIn("dead handler", r["errors"][0][2])

    def test_defined_inline_handler_is_clean(self):
        r = pb.wiring_check([
            ("index.html", '<button onclick="startApp()">go</button>'),
            ("app.js", 'function startApp(){ alert(1); }')])
        self.assertEqual(r["errors"], [])

    def test_global_handlers_never_flag(self):
        r = pb.wiring_check([
            ("index.html",
             '<button onclick="event.stopPropagation()">x</button>'
             '<a onclick="alert(1)">y</a>'
             '<button onclick="window.print()">p</button>')])
        self.assertEqual(r["errors"], [])

    def test_class_toggled_but_never_defined_warns_only(self):
        r = pb.wiring_check([
            ("app.js", 'el.classList.toggle("fancyMode");')])
        self.assertEqual(len(r["warns"]), 1)
        self.assertIn("fancyMode", r["warns"][0][2])
        self.assertEqual(r["errors"], [])

    def test_state_hint_classes_stay_quiet(self):
        r = pb.wiring_check([
            ("app.js",
             'el.classList.add("is-open"); el.classList.toggle("active");'
             'el.classList.remove("has-error");')])
        self.assertEqual(r["warns"], [])

    def test_missing_script_and_stylesheet_are_advisory(self):
        # the design floor heals styles post-apply; scripts stay advisory
        # because a static page + "js later" is a legal Nova workflow
        r = pb.wiring_check([
            ("index.html",
             '<html><head><link rel="stylesheet" href="css/style.css">'
             '</head><body><script src="js/main.js"></script></body>'
             '</html>')])
        self.assertEqual(r["errors"], [])
        kinds = " ".join(m for _f, _l, m in r["warns"])
        self.assertIn("style.css", kinds)
        self.assertIn("main.js", kinds)

    def test_missing_img_and_page_link_are_advisory(self):
        r = pb.wiring_check([
            ("index.html",
             '<img src="photos/cat.png"><a href="about.html">about</a>')])
        self.assertEqual(r["errors"], [])
        self.assertEqual(len(r["warns"]), 2)

    def test_remote_refs_never_flag(self):
        r = pb.wiring_check([
            ("index.html",
             '<script src="https://cdn.example.com/x.js"></script>'
             '<img src="data:image/png;base64,AAA">'
             '<a href="https://example.com/next">n</a>'
             '<a href="#top">t</a>')])
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["warns"], [])

    def test_batch_file_satisfies_reference(self):
        r = pb.wiring_check([
            ("index.html", '<script src="app.js"></script>'),
            ("app.js", "console.log(1);")])
        self.assertEqual(r["warns"], [])

    def test_python_relative_import_missing_is_an_error(self):
        r = pb.wiring_check([("myapp/core.py", "from .util import x\n")])
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("util", r["errors"][0][2])

    def test_python_relative_import_present_is_clean(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "myapp").mkdir()
            (Path(td) / "myapp" / "util.py").write_text("x = 1\n")
            r = pb.wiring_check([("myapp/core.py",
                                  "from .util import x\n")], ws=Path(td))
        self.assertEqual(r["errors"], [])

    def test_python_pip_import_never_false_flags(self):
        r = pb.wiring_check([("tool.py",
                              "import requests\nimport json\n")])
        self.assertEqual(r["errors"], [])

    def test_node_relative_require_missing_is_an_error(self):
        r = pb.wiring_check([("lib/index.js",
                              'const cfg = require("../config/app");\n')])
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("config/app", r["errors"][0][2])

    def test_node_relative_require_present_is_clean(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config").mkdir()
            (Path(td) / "config" / "app.js").write_text("module.exports={}")
            r = pb.wiring_check([("lib/index.js",
                                  'const cfg = require("../config/app");\n')],
                                 ws=Path(td))
        self.assertEqual(r["errors"], [])

    def test_minified_files_are_skipped(self):
        big = "var a=1;" + "x=1;" * 2000
        r = pb.wiring_check([("app.min.js", big +
                              'document.getElementById("zzz");')])
        self.assertEqual(r["errors"], [])

    def test_workspace_pool_widens_the_graph(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "old.html").write_text('<div id="legacy"></div>')
            r = pb.wiring_check([("new.js",
                                  'document.getElementById("legacy");')],
                                ws=Path(td))
        self.assertEqual(r["errors"], [])


# =====================================================================
# 2. the smoke probe (real subprocess - this class re-enables RUN)
# =====================================================================
class TestSmoke(unittest.TestCase):
    def setUp(self):
        os.environ.pop("NOVA_PROBE_RUN", None)   # runs allowed here
        self._old = os.environ.get("NOVA_PROBE_TIMEOUT")
        os.environ["NOVA_PROBE_TIMEOUT"] = "6"

    def tearDown(self):
        os.environ["NOVA_PROBE_RUN"] = "0"
        if self._old is None:
            os.environ.pop("NOVA_PROBE_TIMEOUT", None)
        else:
            os.environ["NOVA_PROBE_TIMEOUT"] = self._old

    def test_crash_becomes_an_error_finding(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "app.py").write_text(
                "x = [1, 2]\nprint(x[5])\n")
            r = pb.smoke_one(td, "app.py")
        self.assertEqual(r["level"], "error")
        self.assertIn("IndexError", r["msg"])

    def test_clean_exit_passes(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "app.py").write_text("print('ok')\n")
            r = pb.smoke_one(td, "app.py")
        self.assertEqual(r["level"], "pass")

    def test_interactive_is_info_not_a_bug(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "talk.py").write_text(
                'name = input("who? ")\nprint(name)\n')
            r = pb.smoke_one(td, "talk.py")
        self.assertEqual(r["level"], "info")
        self.assertIn("interactive", r["msg"])

    def test_endless_loop_warns(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "loop.py").write_text("while True:\n    pass\n")
            r = pb.smoke_one(td, "loop.py", timeout=2)
        self.assertEqual(r["level"], "warn")
        self.assertIn("did not finish", r["msg"])

    def test_server_like_timeout_passes(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "srv.py").write_text(
                "import time\nprint('serving...')\n"
                "while True:\n    time.sleep(0.1)\n")
            r = pb.smoke_one(td, "srv.py", server_like=True, timeout=2)
        self.assertEqual(r["level"], "pass")
        self.assertIn("server", r["msg"])

    def test_node_crash_is_parsed(self):
        node = pb.shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "bad.js").write_text(
                "console.log(neverDefined123);\n")
            r = pb.smoke_one(td, "bad.js")
        self.assertEqual(r["level"], "error")
        self.assertIn("ReferenceError", r["msg"])

    def test_entry_picking_rules(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "test_a.py").write_text(
                'if __name__ == "__main__": pass\n')
            (Path(td) / "ui.js").write_text(
                'document.getElementById("x");\n')
            (Path(td) / "main.py").write_text(
                'if __name__ == "__main__":\n    print(1)\n')
            picks = pb._pick_entries(td, ["test_a.py", "ui.js",
                                          "main.py"])
        names = [p[0] for p in picks]
        self.assertEqual(names, ["main.py"])

    def test_kill_switch(self):
        os.environ["NOVA_PROBE_RUN"] = "0"
        try:
            r = pb.smoke_check("/tmp", ["app.py"])
            self.assertEqual(r["ran"], 0)
            self.assertIn("NOVA_PROBE_RUN=0", r.get("skipped", ""))
        finally:
            os.environ["NOVA_PROBE_RUN"] = "0"


# =====================================================================
# 3. the browser probe (honest skips; the real run when possible)
# =====================================================================
class TestBrowser(unittest.TestCase):
    def test_kill_switch_skips_honestly(self):
        r = pb.browser_check("/tmp", ["index.html"])
        self.assertFalse(r["ran"])
        self.assertIn("NOVA_PROBE_BROWSER=0", r["skipped"])

    def test_no_html_skips(self):
        os.environ.pop("NOVA_PROBE_BROWSER", None)
        try:
            r = pb.browser_check("/tmp", ["app.py"])
        finally:
            os.environ["NOVA_PROBE_BROWSER"] = "0"
        self.assertIn("no html", r["skipped"])

    def test_real_probe_when_playwright_exists(self):
        os.environ.pop("NOVA_PROBE_BROWSER", None)
        if not pb.playwright_available():
            os.environ["NOVA_PROBE_BROWSER"] = "0"
            self.skipTest("playwright not installed on this machine")
        os.environ.pop("NOVA_PROBE_BROWSER", None)
        try:
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / "broken.html").write_text(
                    "<html><body><button onclick=\"ghostFn()\">x</button>"
                    "<script>function realOne(){}\n"
                    "ghostFn();</script></body></html>")
                r = pb.browser_check(td, ["broken.html"], budget=20)
        finally:
            os.environ["NOVA_PROBE_BROWSER"] = "0"
        self.assertTrue(r["ran"], r)
        joined = " ".join(m for _f, _l, m in r["errors"])
        self.assertIn("ghostFn", joined)


# =====================================================================
# 4. the completeness probe
# =====================================================================
class TestCompleteness(unittest.TestCase):
    def test_gaps_are_parsed_from_a_fake_brain(self):
        def brain(prompt):
            self.assertIn("USER REQUEST", prompt)
            return ('sure! {"complete": false, "gaps": '
                    '[{"what": "logout button missing", '
                    '"where": "index.html"}, '
                    '{"what": "no handler for the search box", '
                    '"where": "-"}]} hope that helps')
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "index.html").write_text(
                '<h1>shop</h1><div id="app"></div>')
            r = pb.review_completeness("a shop with login and logout",
                                       td, ["index.html"], brain)
        self.assertTrue(r["model_used"])
        self.assertFalse(r["complete"])
        self.assertEqual(len(r["gaps"]), 2)
        self.assertEqual(r["gaps"][0][0], "index.html")

    def test_no_brain_no_model(self):
        r = pb.review_completeness("build x", "/tmp", ["a.py"], None)
        self.assertFalse(r["model_used"])

    def test_garbage_answer_never_crashes(self):
        r = pb.review_completeness("build x", "/tmp", ["a.py"],
                                   lambda p: "I cannot answer that")
        self.assertFalse(r["model_used"])
        self.assertEqual(r["gaps"], [])

    def test_skeletons_are_real_facts(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "page.html").write_text(
                '<button onclick="go()">a</button><div id="app"></div>'
                "<h1>Title</h1>")
            sk = pb.skeleton_of(td, "page.html")
            self.assertIn("1 button", sk)
            self.assertIn("app", sk)
            self.assertIn("go", sk)
            (Path(td) / "m.py").write_text("def load():\n    pass\n")
            self.assertIn("load", pb.skeleton_of(td, "m.py"))
            (Path(td) / "s.js").write_text("function submit(){}\n")
            self.assertIn("submit", pb.skeleton_of(td, "s.js"))


# =====================================================================
# 5. settings + master switch
# =====================================================================
class TestSettings(unittest.TestCase):
    def test_roundtrip_validation_and_reset(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(pb.load_settings(td), dict(
                pb.DEFAULTS, custom=False))
            err = pb.save_settings(td, {"smoke": False, "hack": True})
            self.assertEqual(err, "")
            s = pb.load_settings(td)
            self.assertFalse(s["smoke"])
            self.assertTrue(s["wiring"])          # untouched default
            self.assertTrue(s["custom"])
            self.assertNotIn("hack", s)           # hostile key dropped
            pb.save_settings(td, {"smoke": "yes"})   # wrong type ignored
            self.assertFalse(pb.load_settings(td)["smoke"])
            pb.reset_settings(td)
            self.assertTrue(pb.load_settings(td)["smoke"])

    def test_broken_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / ".nova"
            d.mkdir()
            (d / "probe.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(pb.load_settings(td),
                             dict(pb.DEFAULTS, custom=False))

    def test_master_on_and_env_kill(self):
        self.assertTrue(pb.master_on(None))
        self.assertTrue(pb.master_on({"on": False}) is False)
        old = os.environ.get("NOVA_PROBE")
        os.environ["NOVA_PROBE"] = "0"
        try:
            self.assertFalse(pb.master_on(None))
        finally:
            if old is None:
                os.environ.pop("NOVA_PROBE", None)
            else:
                os.environ["NOVA_PROBE"] = old


# =====================================================================
# 6. the orchestrators
# =====================================================================
class TestOrchestrators(unittest.TestCase):
    def test_pre_apply_gate_rejects_and_builds_repair(self):
        r = pb.pre_apply_gate([
            ("index.html", '<button onclick="go()">x</button>'),
            ("app.js", 'document.getElementById("nope");')])
        self.assertTrue(r["reject"])
        self.assertTrue(r["repair"].startswith("BUG HUNTER:"))
        self.assertIn("#nope", r["repair"])
        self.assertIn("go(", r["repair"])
        self.assertIn("=== FILE:", r["repair"])

    def test_pre_apply_gate_respects_reject_wiring_off(self):
        r = pb.pre_apply_gate([
            ("app.js", 'document.getElementById("nope");')],
            cfg={"reject_wiring": False})
        self.assertFalse(r["reject"])
        self.assertEqual(r["repair"], "")
        self.assertTrue(r["errors"])       # findings still reported

    def test_pre_apply_gate_healthy_is_clean(self):
        r = pb.pre_apply_gate([
            ("index.html", '<div id="app"></div>'),
            ("app.js", 'function go(){}\n'
                       'document.getElementById("app");')])
        self.assertFalse(r["reject"])
        self.assertEqual(r["errors"], [])

    def test_run_post_apply_verdicts_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "index.html").write_text(
                '<button onclick="go()">x</button>')
            rep = pb.run_post_apply(td, ["index.html"],
                                    request="a page", chat_fn=None)
        self.assertEqual(rep["verdict"], "bug")
        flat = rep["findings"]
        self.assertTrue(any("go(" in m for _f, _l, m, _lv in flat))
        lines = pb.report_lines(rep)
        self.assertTrue(all(lv in ("error", "warn") for lv, _t in lines))

    def test_run_post_apply_clean_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            # v8.6 note: the static_check sweep (honestly) flags a
            # handler whose defining script the page never loads, so a
            # CLEAN fixture must actually wire app.js in.
            (Path(td) / "index.html").write_text(
                '<div id="app"></div>'
                '<script src="app.js"></script>'
                '<button onclick="go()">x</button>')
            (Path(td) / "app.js").write_text(
                'function go(){ document.getElementById("app").'
                'textContent = "ok"; }\n')
            rep = pb.run_post_apply(td, ["index.html", "app.js"],
                                    request="", chat_fn=None)
        self.assertEqual(rep["verdict"], "pass")
        self.assertEqual(rep["findings"], [])


# =====================================================================
# 7. nova.py integration
# =====================================================================
class TestNovaIntegration(unittest.TestCase):
    def test_version_pins(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        # v8.6 moved the codename to "bug net + vision" (the hunter
        # probes are untouched by that)
        self.assertEqual(nova.CODENAME, "master switch")
        self.assertEqual(nova_think.VERSION, "8.12.0")
        self.assertTrue(any("Version 8.12.0" in ln
                            for ln in _src("nova.py").splitlines()[:8]))

    def test_probe_registered_in_tools(self):
        entry = next((t for t in nova.TOOLS if t["cmd"] == "/probe"), None)
        self.assertIsNotNone(entry)
        self.assertIs(entry["fn"], nova.cmd_probe)

    def test_pre_apply_wiring_gate_refuses_dead_batch(self):
        """THE core law: a batch whose wiring is dead (a button wired to
        nothing) is refused BEFORE one byte is written."""
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            events = []
            old_emit = nova.EVENT_SINK
            nova.EVENT_SINK = events.append
            try:
                sess = nova.Session(ws)
                sess.touched["index.html"] = "new"
                with contextlib.redirect_stdout(io.StringIO()):
                    applied = nova.offer_apply(
                        sess, [("index.html",
                                '<button onclick="go()">x</button>')],
                        [], edits=None, auto=True)
            finally:
                nova.EVENT_SINK = old_emit
            self.assertEqual(applied, [])
            self.assertFalse((ws / "index.html").exists())
            self.assertTrue(sess.probe_repair
                            and "go(" in sess.probe_repair)
            self.assertTrue(any(e.get("t") == "probe_reject"
                                for e in events), events)

    def test_pre_apply_wiring_gate_passes_healthy_batch(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            sess = nova.Session(ws)
            sess.touched["index.html"] = "new"
            sess.touched["app.js"] = "new"
            with contextlib.redirect_stdout(io.StringIO()):
                applied = nova.offer_apply(
                    sess, [("index.html", '<div id="app"></div>'
                                          '<script src="app.js"></script>'),
                           ("app.js", 'document.getElementById("app");')],
                    [], edits=None, auto=True)
            self.assertIn("index.html", applied)
            self.assertIn("app.js", applied)
            self.assertIsNone(sess.probe_repair)

    def test_pip_import_batch_still_applies(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.touched["tool.py"] = "new"
            with contextlib.redirect_stdout(io.StringIO()):
                applied = nova.offer_apply(
                    sess, [("tool.py",
                            "import requests\n\n"
                            "if __name__ == '__main__':\n"
                            "    print('x')\n")],
                    [], edits=None, auto=True)
            self.assertIn("tool.py", applied)

    def test_repair_context_is_one_shot_in_chat_turn(self):
        sess = nova.Session(Path(tempfile.mkdtemp()))
        sess.probe_repair = "BUG HUNTER: fix #btn wiring"
        holder = {}

        def fake_stream(model, msgs, mode, sess=None, section=None,
                        quiet=False):
            holder["prompt"] = msgs[-1]["content"]
            return ("just an answer, no files"), True

        old_stream = nova.stream_chat
        nova.stream_chat = fake_stream
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                nova.chat_turn(sess, "درستش کن")
        finally:
            nova.stream_chat = old_stream
        self.assertIn("fix #btn wiring", holder["prompt"])
        self.assertIsNone(sess.probe_repair, "one shot only")

    def test_feedback_fix_note_includes_hunter(self):
        sess = nova.Session(Path(tempfile.mkdtemp()))
        sess.last_feedback = {"syntax": [], "lint": [], "tests": None,
                              "probe": [("index.html", 12,
                                         "dead reference: #box")]}
        note = nova._feedback_fix_note(sess)
        self.assertIn("BUG HUNTER (index.html, line 12)", note)
        self.assertIn("dead reference: #box", note)

    def test_master_switch_and_status_line(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            self.assertTrue(nova._probe_master_on(sess))
            old = os.environ.get("NOVA_PROBE")
            os.environ["NOVA_PROBE"] = "0"
            try:
                self.assertFalse(nova._probe_master_on(sess))
            finally:
                if old is None:
                    os.environ.pop("NOVA_PROBE", None)
                else:
                    os.environ["NOVA_PROBE"] = old
        self.assertIn("/probe", _src("nova.py"))

    def test_web_probe_state_shape(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            st = nova.web_probe_state(sess)
            for key in ("on", "wiring", "smoke", "browser", "review",
                        "reject_wiring", "playwright", "custom",
                        "env_off"):
                self.assertIn(key, st)
            self.assertTrue(st["on"])
            self.assertTrue(st["reject_wiring"])

    def test_web_server_and_panel_surface(self):
        ws = _src("web_server.py")
        self.assertIn('"probe": _state_safe', ws)
        self.assertIn('("probe_on", "on")', ws)
        self.assertIn('"probe_reject"', ws)
        html = _src("web/index.html")
        for eid in ("probeState", "probeOn", "probeWiring", "probeSmoke",
                    "probeBrowser", "probeReview", "probeReject",
                    "probeSave", "probeReset", "renderProbePanel"):
            self.assertIn(eid, html)

    def test_guardian_repair_and_probe_repair_coexist(self):
        sess = nova.Session(Path(tempfile.mkdtemp()))
        sess.guardian_repair = "GUARDIAN: fix a"
        sess.probe_repair = "BUG HUNTER: fix b"
        holder = {}

        def fake_stream(model, msgs, mode, sess=None, section=None,
                        quiet=False):
            holder["prompt"] = msgs[-1]["content"]
            return ("ok"), True

        old = nova.stream_chat
        nova.stream_chat = fake_stream
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                nova.chat_turn(sess, "ok")
        finally:
            nova.stream_chat = old
        self.assertIn("GUARDIAN: fix a", holder["prompt"])
        self.assertIn("BUG HUNTER: fix b", holder["prompt"])
        self.assertIsNone(sess.guardian_repair)
        self.assertIsNone(sess.probe_repair)


if __name__ == "__main__":
    unittest.main()
