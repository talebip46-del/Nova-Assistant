#!/usr/bin/env python3
# =====================================================================
#  Nova v8.11.0 "code guardian" regression tests:
#   - nova_guardian: the string-aware delimiter scanner (comments /
#     strings / heredocs per family, line numbers, no false errors),
#     the markup tag matcher, ~30 language profiles, the external
#     parse-only tools (when installed), the offline bug patterns.
#   - the supervisor: deterministic reject BEFORE anything is written,
#     the exact repair prompt, the fail-soft model layer (fake brain),
#     findings_summary, the tolerant agent-JSON parser.
#   - the dedicated websearch: SEPARATE "guardian:" cache namespace,
#     hard time budget, NEVER raises, offline = built-in knowledge base
#     (correctness never depends on the internet).
#   - settings: .nova/guardian.json roundtrip, validation, reset.
#   - audit_workspace: the fleet sweeps the tree (ignored dirs skipped).
#   - nova.py integration: the pre-apply fleet gate (broken batch ->
#     nothing written + one-shot repair context), the post-apply fleet
#     review wiring, _feedback_fix_note guardian lines, /guardian in
#     TOOLS, /status line, web_guardian_state, the web surface
#     (/api/info guardian block, /api/settings fields, panel ids).
#  Everything is offline (NOVA_GUARDIAN_WEB=0 is forced in setUp).
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

os.environ["NOVA_GUARDIAN_WEB"] = "0"      # the suite is offline

import nova                    # noqa: E402
import nova_guardian as gd     # noqa: E402
import nova_think              # noqa: E402

APP = Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


# =====================================================================
# 1. the scanner (the offline floor)
# =====================================================================
class TestScanner(unittest.TestCase):
    def test_healthy_python_is_clean(self):
        e, _w = gd.scan_delims(
            'def f(x):\n    d = {"a": [1, 2]}  # } ] (\n    return d\n',
            "py")
        self.assertEqual(e, [])

    def test_brackets_inside_strings_and_comments_never_invent_errors(self):
        e, _w = gd.scan_delims('x = ")}{"; y = \'{[}\'; z = 1\n', "py")
        self.assertEqual(e, [])
        e, _w = gd.scan_delims("/* } { ) ( */ int x = (1 + 2);\n", "c")
        self.assertEqual(e, [])

    def test_missing_close_reports_opener_line(self):
        e, _w = gd.scan_delims("def f():\n    if x:\n        return [1, 2\n",
                               "py")
        self.assertTrue(any("[" in msg for _ln, msg in e), e)

    def test_swapped_closer_is_flagged(self):
        e, _w = gd.scan_delims("x = (1 + 2]\n", "c")
        self.assertTrue(any("]" in msg for _ln, msg in e), e)

    def test_heredoc_body_is_free_form(self):
        sh = 'cat <<EOF\nthis } { [ is ] "fine"\nEOF\necho "done"\n'
        e, _w = gd.scan_delims(sh, "shell")
        self.assertEqual(e, [])

    def test_unterminated_heredoc_warns(self):
        _e, w = gd.scan_delims("cat <<EOF\nline\n", "shell")
        self.assertTrue(any("heredoc" in msg for _ln, msg in w), w)

    def test_unterminated_block_comment_warns(self):
        _e, w = gd.scan_delims("int x = 1; /* still open\n", "c")
        self.assertTrue(any("comment" in msg for _ln, msg in w), w)

    def test_sql_line_comments_hide_brackets(self):
        e, _w = gd.scan_delims("-- ) ( }\nSELECT (1);\n", "sql")
        self.assertEqual(e, [])

    def test_tags_healthy_and_void(self):
        e, _w = gd.scan_tags('<meta charset="utf-8"><div><img src="x">'
                             '<br><input type="text"></div>')
        self.assertEqual(e, [])

    def test_tags_mismatch_and_unclosed(self):
        e, _w = gd.scan_tags("<div><span>hi</div></span>")
        self.assertTrue(e, "swapped closes must be flagged")
        e, _w = gd.scan_tags("<p>unclosed")
        self.assertTrue(e, "an unclosed tag must be flagged")

    def test_tags_script_body_is_not_markup(self):
        e, _w = gd.scan_tags('<script>if (a<b) { x="</div>"; }</script>'
                             "<div>ok</div>")
        self.assertEqual(e, [])

    def test_markup_check_returns_flat_list(self):
        self.assertEqual(gd._html_check("a.html", "<div>ok</div>"), [])
        self.assertTrue(gd._html_check("a.html", "<div>"))


# =====================================================================
# 2. the language fleet - validate() over the registry
# =====================================================================
class TestValidate(unittest.TestCase):
    def test_python_healthy_and_broken(self):
        self.assertEqual(gd.validate("a.py", "x = 1\n")["errors"], [])
        r = gd.validate("a.py", "def f(:\n")
        self.assertTrue(r["errors"])
        self.assertTrue(any("python" in v for v in r["via"]), r["via"])

    def test_python_py2_print_is_caught(self):
        r = gd.validate("a.py", 'print "old"\n')
        self.assertTrue(r["errors"], r)

    def test_python_warns_on_mutable_default(self):
        r = gd.validate("a.py", "def f(x=[]):\n    pass\n")
        self.assertTrue(r["warns"] and not r["errors"], r)

    def test_js_broken_without_node(self):
        r = gd.validate("m.js", "function f( {\n  return 1;\n}\n")
        self.assertTrue(r["errors"], "node or the scanner must catch this")

    def test_html_broken(self):
        r = gd.validate("i.html", "<html><body><div>x</body></html>")
        self.assertTrue(r["errors"], r)

    def test_css_broken_braces(self):
        r = gd.validate("s.css", "body { color: red;\n.a { margin: 0; }")
        self.assertTrue(r["errors"], r)
        self.assertEqual(gd.validate("s.css", "a{b:c}")["errors"], [])

    def test_json_and_yaml(self):
        self.assertTrue(gd.validate("c.json", '{"a": 1,}')["errors"])
        self.assertTrue(gd.validate("c.yaml", "a:\n\tb: 1\n")["errors"])
        self.assertEqual(gd.validate("c.yaml", "a:\n  b: [1, 2]\n")["errors"],
                         [])

    def test_go_rust_java_structure(self):
        for name, good, bad in (
                ("m.go", "package main\nfunc main() {\n}\n",
                 "package main\nfunc main( {\n}\n"),
                ("p.rs", "fn main() {\n}\n", "fn main( {\n}\n"),
                ("M.java", "class M {\n  void f() {\n  }\n}\n",
                 "class M {\n  void f( {\n}\n")):
            self.assertEqual(gd.validate(name, good)["errors"], [], name)
            self.assertTrue(gd.validate(name, bad)["errors"], name)

    def test_shell_else_if_and_missing_space(self):
        self.assertTrue(gd.validate("s.sh", "else if true; then echo; fi\n")
                        ["errors"])
        self.assertTrue(gd.validate("s.sh", "if [-f x]; then echo; fi\n")
                        ["errors"])
        self.assertEqual(gd.validate(
            "s.sh", "if [ -f x ]; then echo; fi\n")["errors"], [])

    def test_c_gets_is_error_and_if_assign_warns(self):
        r = gd.validate("t.c", "int main(void){ char b[9]; gets(b); }\n")
        self.assertTrue(r["errors"], r)
        r = gd.validate("t.c", "int main(void){ if (x = 5) {} }\n")
        self.assertTrue(r["warns"] and not r["errors"], r)

    def test_go_typo_PrintIn(self):
        r = gd.validate("m.go", 'package main\nfunc main(){ '
                        'fmt.PrintIn("x") }\n')
        self.assertTrue(any("Println" in msg for _l, msg in r["errors"])
                        or any("Println" in msg for _l, msg in r["warns"]), r)

    def test_generic_never_blocks(self):
        r = gd.validate("Dockerfile", "RUN echo ( unclosed\n")
        self.assertFalse(r["errors"])
        self.assertTrue(r["warns"], "generic problems stay advisory")

    def test_markdown_never_blocks(self):
        r = gd.validate("R.md", "# hi\nsee ( [ note\n")
        self.assertEqual(r["errors"], [])

    def test_binary_is_skipped(self):
        r = gd.validate("img.png", "PNG\x00\x01\x02 \x00 junk")
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("binary" in v for v in r["via"]), r)

    def test_empty_content_passes(self):
        for name in ("a.py", "b.js", "c.css", "d.json", "e.md"):
            self.assertEqual(gd.validate(name, "")["errors"], [])

    def test_oversized_file_still_structurally_checked(self):
        big = "x = (1)\n" * 60_000 + "def f(:\n"   # > MAX_GUARD_FILE_CHARS
        r = gd.validate("big.py", big)
        self.assertTrue(any("structure-only" in v for v in r["via"]), r["via"])


class TestRegistry(unittest.TestCase):
    def test_fleet_size_and_no_double_booked_exts(self):
        self.assertGreaterEqual(gd.lang_count(), 28)
        seen = {}
        for lid, prof in gd.LANGS.items():
            for ext in prof["exts"]:
                self.assertNotIn(ext, seen,
                                 "%s double-booked by %s/%s"
                                 % (ext, seen.get(ext), lid))
                seen[ext] = lid

    def test_the_promise_is_covered(self):
        need = (".py", ".js", ".ts", ".jsx", ".html", ".css", ".json",
                ".yaml", ".toml", ".sh", ".c", ".cpp", ".java", ".cs",
                ".go", ".rs", ".php", ".rb", ".sql", ".kt", ".swift",
                ".lua", ".vue", ".svelte", ".xml", ".dart")
        for ext in need:
            self.assertIn(ext, gd._EXT_MAP, "the fleet must cover " + ext)

    def test_resolve_lang(self):
        self.assertEqual(gd.resolve_lang("a/b/main.PY"), "python")
        self.assertEqual(gd.resolve_lang("x.unknownext"), "generic")
        self.assertEqual(gd.resolve_lang("no_ext"), "generic")
        self.assertEqual(gd.resolve_lang("q.R"), "r")

    def test_every_profile_is_complete(self):
        for lid, prof in gd.LANGS.items():
            self.assertTrue(prof["label"], lid)
            # v8.7: "rust" joined - a lifetime 'a must not be counted
            # as a string opener (every lifetime-using .rs file used
            # to be falsely rejected by the c-family scan).
            self.assertIn(prof["family"],
                          ("c", "py", "shell", "sql", "plain", "rust"), lid)
            self.assertTrue(prof["brief"], lid)
            self.assertTrue(prof["kb"], "offline KB required for " + lid)

    def test_rust_lifetimes_are_not_strings(self):
        # v8.7 regression pin: a perfectly valid lifetime-using rust
        # file must pass the structure floor with zero errors.
        rust = ("struct S<'a> {\n"
                "    name: &'a str,\n"
                "}\n"
                "fn main() {\n"
                "    let s = S { name: \"x\" };\n"
                "    println!(\"{}\", s.name);\n"
                "}\n")
        rep = gd.validate("m.rs", rust)
        self.assertEqual(rep["errors"], [])

    def test_heredoc_with_redirect_is_not_bracket_scanned(self):
        # v8.7 regression pin: `cat <<EOF > f` bodies are heredocs.
        sh = "cat <<EOF > out.txt\nhello { world [ again ]\nEOF\necho done\n"
        rep = gd.validate("s.sh", sh)
        self.assertEqual(rep["errors"], [])

    def test_html_optional_end_tags_autoclose(self):
        # v8.7 regression pin: sibling <li>/<td> auto-close like a
        # browser; <p> (mandatory end tag in Nova's book) stays strict.
        e, _w = gd.scan_tags("<ul><li>one<li>two</ul>")
        self.assertEqual(e, [])
        e, _w = gd.scan_tags("<table><tr><td>a<td>b<tr><td>c</table>")
        self.assertEqual(e, [])
        e, _w = gd.scan_tags("<p>unclosed")
        self.assertTrue(e)


# =====================================================================
# 3. the supervisor - review_batch / repair / findings
# =====================================================================
class TestSupervisor(unittest.TestCase):
    def test_broken_batch_is_rejected_with_repair_prompt(self):
        rep = gd.review_batch([("app.py", "def f(:\n")], chat_fn=None,
                              cfg={"model": False, "web": False})
        self.assertEqual(rep["verdict"], "reject")
        self.assertEqual(rep["rejects"][0]["file"], "app.py")
        rp = gd.repair_prompt(rep)
        self.assertIn("app.py", rp)
        self.assertIn("NOTHING was written", rp)
        self.assertIn("=== FILE:", rp)

    def test_healthy_batch_passes(self):
        rep = gd.review_batch([("a.py", "x = 1\n"), ("b.css", "a{b:c}")],
                              chat_fn=None, cfg={"model": False,
                                                 "web": False})
        self.assertEqual(rep["verdict"], "pass")

    def test_reject_syntax_off_downgrades_to_warn(self):
        rep = gd.review_batch([("app.py", "def f(:\n")], chat_fn=None,
                              cfg={"reject_syntax": False, "model": False})
        self.assertNotEqual(rep["verdict"], "reject")

    def test_model_layer_runs_with_fake_brain(self):
        def fake_chat(prompt):
            self.assertIn("review sub-agent", prompt)
            return ('```json\n{"syntax_ok": false, "bugs": '
                    '[{"line": 1, "severity": "warn", '
                    '"msg": "unused import os"}]}\n```')

        rep = gd.review_batch([("a.py", "import os\nx = 1\n")],
                              chat_fn=fake_chat,
                              cfg={"model": True, "web": False})
        self.assertTrue(rep["model_used"])
        self.assertTrue(rep["agents"][0]["findings"])
        self.assertEqual(rep["verdict"], "warn")

    def test_model_layer_off_or_mute(self):
        def boom(prompt):
            raise AssertionError("must not be called")

        self.assertFalse(gd.review_batch(
            [("a.py", "x = 1\n")], chat_fn=boom,
            cfg={"model": False, "web": False})["model_used"])
        rep = gd.review_batch([("a.py", "x = 1\n")],
                              chat_fn=lambda p: "not json at all",
                              cfg={"model": True, "web": False})
        self.assertTrue(rep["agents"][0]["findings"] == [],
                        "a derailed sub-agent must fail soft")

    def test_findings_summary_flat_and_capped(self):
        rep = gd.review_batch([("app.py", "def f(:\n")], chat_fn=None,
                              cfg={"model": False, "web": False})
        fs = gd.findings_summary(rep)
        self.assertTrue(fs and fs[0][0] == "app.py")

    def test_parse_agent_json_tolerant(self):
        data = gd.parse_agent_json(
            'noise {"syntax_ok": false, "bugs": [{"line": 3, '
            '"severity": "error", "msg": "m"}]} tail')
        self.assertEqual(data["bugs"][0]["line"], 3)
        self.assertIsNone(gd.parse_agent_json("no json"))
        self.assertIsNone(gd.parse_agent_json(""))
        # a brace inside a JSON string must not end the object early
        data = gd.parse_agent_json('{"bugs": [{"msg": "has } brace"}]}')
        self.assertEqual(data["bugs"][0]["msg"], "has } brace")


# =====================================================================
# 4. the dedicated websearch - offline first, never raises
# =====================================================================
class TestGuardianWebsearch(unittest.TestCase):
    def test_offline_kb_answers_and_never_raises(self):
        out = gd.web_lookup("python", lang="python")
        self.assertFalse(out["ok"])
        self.assertEqual(out["source"], "offline-kb")
        self.assertIn("print is a function", out["digest"])

    def test_empty_query_is_safe(self):
        self.assertFalse(gd.web_lookup("", lang=None)["ok"])

    def test_env_kill_switch_forces_offline(self):
        old = os.environ.get("NOVA_GUARDIAN_WEB")
        os.environ["NOVA_GUARDIAN_WEB"] = "0"
        try:
            out = gd.web_lookup("rust", lang="rust")
            self.assertEqual(out["source"], "offline-kb")
        finally:
            if old is None:
                os.environ.pop("NOVA_GUARDIAN_WEB", None)
            else:
                os.environ["NOVA_GUARDIAN_WEB"] = old

    def test_knowledge_note_covers_fleet(self):
        for lid in gd.LANGS:
            self.assertTrue(gd.knowledge_note(lid).startswith("- "), lid)

    def test_separate_cache_namespace(self):
        self.assertIn('"guardian:"', _src("nova_guardian.py"))


# =====================================================================
# 5. settings
# =====================================================================
class TestGuardianSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults_and_roundtrip(self):
        s = gd.load_settings(self.ws)
        self.assertTrue(s["on"] and s["model"] and s["web"]
                        and s["reject_syntax"])
        self.assertFalse(s["custom"])
        self.assertEqual(gd.save_settings(
            self.ws, {"model": False, "bogus": 1}), "")
        s = gd.load_settings(self.ws)
        self.assertTrue(s["custom"] and s["model"] is False)
        self.assertNotIn("bogus", s)
        self.assertTrue((self.ws / ".nova" / "guardian.json").is_file())

    def test_reset(self):
        gd.save_settings(self.ws, {"on": False})
        self.assertEqual(gd.reset_settings(self.ws), "")
        self.assertTrue(gd.load_settings(self.ws)["on"])

    def test_enabled_fails_soft_to_default(self):
        self.assertTrue(gd.enabled({}, "on"))
        self.assertTrue(gd.enabled(None, "web"))
        self.assertFalse(gd.enabled({"on": False}, "on"))


# =====================================================================
# 6. audit_workspace
# =====================================================================
class TestAudit(unittest.TestCase):
    def test_sweep_finds_problems_and_skips_ignored_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "src").mkdir()
            (ws / "src" / "good.py").write_text("x = 1\n", encoding="utf-8")
            (ws / "src" / "bad.py").write_text("def (:\n", encoding="utf-8")
            (ws / "node_modules").mkdir()
            (ws / "node_modules" / "n.js").write_text("} } }",
                                                      encoding="utf-8")
            rep = gd.audit_workspace(ws)
            names = [d["file"] for d in rep]
            self.assertTrue(any("bad.py" in n for n in names), names)
            self.assertFalse(any("node_modules" in n for n in names), names)

    def test_ext_filter_and_empty_root(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "a.py").write_text("def (:\n", encoding="utf-8")
            self.assertEqual(gd.audit_workspace(ws, exts=(".rs",)), [])
            self.assertEqual(gd.audit_workspace(ws / "nope"), [])


# =====================================================================
# 7. nova.py integration
# =====================================================================
class TestNovaIntegration(unittest.TestCase):
    def test_version_pins(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        # v8.5 moved the codename to "bug hunter" (the guardian
        # itself is unchanged - only the release pin moved)
        # v8.6 moved the codename to "bug net + vision" (the guardian
        # law is untouched by that)
        self.assertEqual(nova.CODENAME, "master switch")
        self.assertEqual(nova_think.VERSION, "8.12.0")
        self.assertTrue(any("Version 8.12.0" in ln
                            for ln in _src("nova.py").splitlines()[:8]))

    def test_guardian_registered_in_tools(self):
        entry = next((t for t in nova.TOOLS if t["cmd"] == "/guardian"), None)
        self.assertIsNotNone(entry)
        self.assertIs(entry["fn"], nova.cmd_guardian)

    def test_pre_apply_gate_refuses_broken_batch(self):
        """THE core law: a syntax-broken file in a language the OLD lint
        gate never knew (Go here) means NOTHING is written, the repair
        context is set, and the web face gets the event."""
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            events = []
            old_emit = nova.EVENT_SINK
            nova.EVENT_SINK = events.append
            try:
                sess = nova.Session(ws)
                sess.touched["main.go"] = "new"
                with contextlib.redirect_stdout(io.StringIO()):
                    applied = nova.offer_apply(
                        sess, [("main.go", "package main\n\nfunc main( {\n"
                                         "\tprintln(\"x\")\n}\n")],
                        [], edits=None, auto=True)
            finally:
                nova.EVENT_SINK = old_emit
            self.assertEqual(applied, [])
            self.assertFalse((ws / "main.go").exists())
            self.assertTrue(sess.guardian_repair
                            and "main.go" in sess.guardian_repair)
            self.assertTrue(any(e.get("t") == "guardian_reject"
                                for e in events), events)

    def test_pre_apply_gate_passes_healthy_batch(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            sess = nova.Session(ws)
            sess.touched["app.py"] = "new"
            with contextlib.redirect_stdout(io.StringIO()):
                applied = nova.offer_apply(
                    sess, [("app.py", "x = 1\nprint(x)\n")],
                    [], edits=None, auto=True)
            self.assertEqual(applied, ["app.py"])
            self.assertTrue((ws / "app.py").is_file())

    def test_repair_context_is_one_shot_in_chat_turn(self):
        sess = nova.Session(Path(tempfile.mkdtemp()))
        sess.guardian_repair = "GUARDIAN: fix line 3 of app.py"
        composed_holder = {}

        def fake_stream(model, msgs, mode, sess=None, section=None,
                        quiet=False):
            composed_holder["prompt"] = msgs[-1]["content"]
            return ("just an answer, no files"), True

        old_stream = nova.stream_chat
        nova.stream_chat = fake_stream
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                nova.chat_turn(sess, "اوکی درستش کن")
        finally:
            nova.stream_chat = old_stream
        self.assertIn("GUARDIAN: fix line 3", composed_holder["prompt"])
        self.assertIsNone(sess.guardian_repair, "one shot only")

    def test_feedback_fix_note_includes_guardian(self):
        sess = nova.Session(Path(tempfile.mkdtemp()))
        sess.last_feedback = {"syntax": [], "lint": [], "tests": None,
                              "guardian": [("main.js", 12,
                                            "undefined variable foo")]}
        note = nova._feedback_fix_note(sess)
        self.assertIn("GUARDIAN (main.js, line 12)", note)
        self.assertIn("undefined variable foo", note)

    def test_status_and_master_switch(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            self.assertTrue(nova._guardian_master_on(sess))
            old = os.environ.get("NOVA_GUARDIAN")
            os.environ["NOVA_GUARDIAN"] = "0"
            try:
                self.assertFalse(nova._guardian_master_on(sess))
            finally:
                if old is None:
                    os.environ.pop("NOVA_GUARDIAN", None)
                else:
                    os.environ["NOVA_GUARDIAN"] = old

    def test_web_guardian_state_shape(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            st = nova.web_guardian_state(sess)
            for key in ("on", "model", "web", "reject_syntax", "langs",
                        "tools", "custom", "env_off"):
                self.assertIn(key, st)
            self.assertGreaterEqual(st["langs"], 28)

    def test_draft_valid_uses_the_fleet(self):
        text = ("=== FILE: app.py ===\ndef f(:\n=== END ===\n"
                "Run: python app.py")
        self.assertFalse(nova._draft_valid(text),
                         "a fleet-rejected draft must never win")

    def test_guardian_repair_prompt_contract(self):
        """The repair prompt must speak the === FILE: protocol the
        parser understands - a fix round that ignores it is lost."""
        rep = gd.review_batch([("app.py", "def f(:\n")], chat_fn=None,
                              cfg={"model": False})
        rp = gd.repair_prompt(rep)
        for needle in ("=== FILE:", "=== END ===", "app.py"):
            self.assertIn(needle, rp)


# =====================================================================
# 8. the web surface
# =====================================================================
class TestWebSurface(unittest.TestCase):
    def test_web_server_has_guardian_endpoints(self):
        src = _src("web_server.py")
        self.assertIn('"guardian": _state_safe', src)
        self.assertIn("guardian_reset", src)
        for key in ("guardian_on", "guardian_model", "guardian_web",
                    "guardian_reject"):
            self.assertIn(key, src)

    def test_index_html_has_the_guardian_panel(self):
        html = _src("web/index.html")
        for needle in ("guardianState", "guardianOn", "guardianModel",
                       "guardianWeb", "guardianReject", "guardianSave",
                       "guardianReset", "renderGuardianPanel"):
            self.assertIn(needle, html)
        self.assertIn("زیرایجنت", html)

    def test_index_html_js_is_valid(self):
        import re
        import subprocess
        html = _src("web/index.html")
        for m in re.finditer(r"<script>(.*?)</script>", html, re.DOTALL):
            with tempfile.NamedTemporaryFile("w", suffix=".js",
                                             delete=False,
                                             encoding="utf-8") as f:
                f.write(m.group(1))
                p = f.name
            try:
                r = subprocess.run(["node", "--check", p],
                                   capture_output=True, text=True,
                                   timeout=30)
                self.assertEqual(r.returncode, 0, r.stderr[:300])
            finally:
                os.unlink(p)


if __name__ == "__main__":
    unittest.main()
