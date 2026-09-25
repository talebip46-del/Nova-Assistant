#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v8.11.0 "master switch" - regression suite.

The user report this round: "Nova is full of bugs, its coding is broken,
it feels like it never ends." The audit found three root families and
this suite pins the fixes:

  A. FALSE REJECTS - the apply/run gates refused healthy batches
     (probe wiring poisoned by pre-existing files, onclick="print()",
     setAttribute ids, namespace packages, @staticmethod signatures,
     SVG <path></path>, unclosed <p> siblings, '$#' base literals,
     '@import' sheets skipping truncation checks, backtick prose).
  B. BROKEN ANSWERS - the router downgraded sizeless models on hard
     tasks, auto-continue stitched cut answers with a blank line,
     prose before === THINK === vanished, digest-of-digest lobotomy.
  C. THE LOOP THAT NEVER ENDS - the terminal /loop and /verify ran
     without the web face's fix budget, the same-error brake was
     evaded by alternating failures, unrunnable/timeout failures were
     fed to fix rounds, empty answers were recorded as successes,
     refused batches re-ran stale code, and the web UI erased every
     refusal banner within a second.

Every test reproduces the exact user-visible failure first.
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import nova  # noqa: E402
import nova_probe  # noqa: E402
import nova_guardian as gd  # noqa: E402
import nova_quality as nq  # noqa: E402
import nova_design  # noqa: E402
import nova_router  # noqa: E402
import nova_think  # noqa: E402
import nova_ctxengine as ce  # noqa: E402


def _spec(**kw):
    d = {"shadow": None, "glass": None, "motion": set(),
         "grain": None, "neon": None, "aurora": None}
    for k, v in kw.items():
        if k == "motion":
            d["motion"] = set(v) if not isinstance(v, set) else v
        else:
            d[k] = v
    return d


# =====================================================================
# A. the gates must never refuse healthy code again
# =====================================================================
class TestProbeFalseRejects(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_preexisting_workspace_bug_no_longer_poisons_the_batch(self):
        (self.ws / "old.js").write_text(
            'document.getElementById("gone").textContent = "x";\n',
            encoding="utf-8")
        res = nova_probe.pre_apply_gate([("app.py", "print('hi')\n")],
                                        ws=str(self.ws))
        self.assertFalse(res["reject"],
                         "a pre-existing bug in an untouched file must "
                         "never refuse a healthy batch")
        self.assertEqual(res["errors"], [])

    def test_batch_own_dead_reference_is_still_an_error(self):
        res = nova_probe.pre_apply_gate(
            [("page.html", '<button onclick="go()">x</button>')])
        self.assertTrue(res["reject"])
        self.assertTrue(res["errors"])

    def test_print_handler_is_a_browser_global(self):
        html = ('<!doctype html><html><body><button onclick="print()">p'
                '</button><script>console.log("hi")</script></body>'
                "</html>")
        res = nova_probe.pre_apply_gate([("page.html", html)])
        self.assertFalse(res["reject"], "onclick=print() is healthy")

    def test_setattribute_is_a_definition(self):
        js = ('var el = document.createElement("div");\n'
              'el.setAttribute("id","box");\n'
              'document.getElementById("box");\n')
        res = nova_probe.pre_apply_gate([("app.js", js)])
        self.assertFalse(res["reject"])

    def test_setattribute_class_is_a_definition(self):
        js = ('el.setAttribute("class", "card active");\n'
              'document.querySelector(".card");\n')
        res = nova_probe.pre_apply_gate([("app.js", js)])
        self.assertFalse(res["reject"])

    def test_namespace_package_import_passes(self):
        (self.ws / "pkg").mkdir()
        (self.ws / "pkg" / "helpers.py").write_text("def hi():\n"
                                                    "    return 1\n",
                                                    encoding="utf-8")
        res = nova_probe.pre_apply_gate(
            [("main.py", "from .pkg import helpers\nprint(helpers.hi())\n")],
            ws=str(self.ws))
        self.assertFalse(res["reject"],
                         "namespace packages are valid since Python 3.3")

    def test_staticmethod_call_is_not_a_typeerror(self):
        py = ("class C:\n"
              "    @staticmethod\n"
              "    def util(a, b):\n"
              "        return a + b\n"
              "    def run(self):\n"
              "        return self.util(1, 2)\n")
        res = nova_probe.pre_apply_gate([("m.py", py)])
        self.assertFalse(res["reject"])

    def test_regular_method_arg_overflow_still_rejected(self):
        py = ("class C:\n"
              "    def util(self, a):\n"
              "        return a\n"
              "    def run(self):\n"
              "        return self.util(1, 2)\n")
        res = nova_probe.pre_apply_gate([("m.py", py)])
        self.assertTrue(res["reject"])

    def test_remote_script_demotes_handler_errors_to_warns(self):
        html = ('<html><body><script src="https://cdn.example.com/x.js">'
                '</script><button onclick="auth2.signOut()">out</button>'
                "</body></html>")
        res = nova_probe.pre_apply_gate([("page.html", html)])
        self.assertFalse(res["reject"],
                         "a CDN script may define the handler - warn only")

    def test_parse_agent_json_budget(self):
        text = "{" * 19000
        t0 = time.time()
        self.assertIsNone(nova_probe.parse_agent_json(text))
        self.assertLess(time.time() - t0, 2.0,
                        "the bracket-soup scan must be budgeted")


class TestGuardianFalseRejects(unittest.TestCase):
    def _errs(self, name, body):
        r = gd.validate(name, body)
        return r.get("errors") if isinstance(r, dict) else r

    def test_svg_explicit_closer_is_valid_xml(self):
        self.assertEqual(self._errs(
            "icon.svg",
            '<svg viewBox="0 0 10 10"><path d="M0 0"></path>'
            "<circle r=\"1\"></circle></svg>"), [])

    def test_unclosed_svg_still_flagged(self):
        self.assertTrue(self._errs("icon.svg", '<svg viewBox="0 0 10 10">'))

    def test_p_sibling_autocloses_like_a_browser(self):
        self.assertEqual(self._errs(
            "page.html",
            "<html><body><p>one\n<p>two\n<p>three\n</body></html>"), [])

    def test_lone_unclosed_p_stays_strict(self):
        e, _w = gd.scan_tags("<p>unclosed")
        self.assertTrue(e)

    def test_swapped_closes_still_flagged(self):
        e, _w = gd.scan_tags("<div><span>hi</div></span>")
        self.assertTrue(e)

    def test_arg_count_dollar_hash_is_not_a_comment(self):
        self.assertEqual(self._errs(
            "run.sh",
            "#!/bin/bash\nif [ $# -eq 2 ]; then\n  echo ok\nfi\n"), [])

    def test_dollar_hash_in_zsh_without_masking_tool(self):
        self.assertEqual(self._errs(
            "run.zsh",
            "#!/bin/zsh\nif [ $# -eq 2 ]; then\n  echo ok\nfi\n"), [])

    def test_base_literal_16ff_is_not_a_comment(self):
        self.assertEqual(self._errs(
            "calc.sh", "echo $(( 16#ff + 1 ))\n"), [])

    def test_real_unclosed_bracket_still_flagged(self):
        self.assertTrue(self._errs(
            "run.zsh", "#!/bin/zsh\nif [ $# -eq 2 ; then\n  echo ok\nfi\n"))

    def test_plain_comments_still_work(self):
        self.assertEqual(self._errs(
            "run.sh", "#!/bin/bash\n# a real comment\necho hi # trailing\n"),
            [])

    def test_parse_agent_json_budget(self):
        t0 = time.time()
        gd.parse_agent_json("{" * 19000)
        self.assertLess(time.time() - t0, 2.0)

    def test_junk_settings_do_not_claim_custom(self):
        ws = Path(tempfile.mkdtemp())
        try:
            p = gd.settings_path(ws)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"junk": 1}), encoding="utf-8")
            self.assertFalse(gd.load_settings(ws).get("custom"))
            p.write_text(json.dumps({"on": True}), encoding="utf-8")
            self.assertTrue(gd.load_settings(ws).get("custom"))
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestQualityFalseRejects(unittest.TestCase):
    def test_truncated_css_with_import_is_caught(self):
        ok, p = nq.preapply_check(
            "style.css", "@import url('x.css');\n.card{color:red;\n")
        self.assertFalse(ok, "the @import exemption must not skip the "
                             "brace-balance check")
        self.assertIn("CSS", p or "")

    def test_import_only_sheet_still_passes(self):
        ok, p = nq.preapply_check(
            "style.css", "@import url('x.css');\n@charset 'utf-8';\n")
        self.assertTrue(ok, p)

    def test_plain_truncated_css_still_caught(self):
        ok, _p = nq.preapply_check("style.css", ".card{color:red;\n")
        self.assertFalse(ok)

    def test_lone_backtick_prose_does_not_reject_the_page(self):
        ok, p = nq.preapply_check(
            "doc.html",
            "<!doctype html><html><body><p>press `</p></body></html>"
            "<p>or ` here</p>")
        self.assertTrue(ok, p)

    def test_really_truncated_page_still_caught(self):
        ok, _p = nq.preapply_check(
            "doc.html", "<!doctype html><html><body><p>hi</body>")
        self.assertFalse(ok)

    def test_template_literal_inside_script_still_stripped(self):
        ok, p = nq.preapply_check(
            "page.html",
            '<html><body><script>const t = `<div>`;</script></body>'
            "</html>")
        self.assertTrue(ok, p)

    def test_esm_module_js_passes(self):
        ok, p = nq.preapply_check(
            "mod.js", 'import { x } from "./y.js";\nexport const a = 1;\n')
        self.assertTrue(ok, p)

    def test_broken_js_still_caught(self):
        ok, _p = nq.preapply_check("bad.js", "function { broken")
        self.assertFalse(ok)

    def test_esm_hint_regex_exists(self):
        self.assertTrue(nq._ESM_HINT_RE.search("import x from 'y';\n"))
        self.assertTrue(nq._ESM_HINT_RE.search("export default class {}\n"))


# =====================================================================
# B. answers must not be broken before they are even applied
# =====================================================================
class TestRouterPicksBrainsHonestely(unittest.TestCase):
    def test_hard_task_never_downgrades_a_sizeless_model(self):
        m = nova_router.pick_local_model(
            "hard", ["llama3.1:latest", "qwen2.5:0.5b"], "llama3.1:latest")
        self.assertEqual(m, "",
                         "unknown current size must keep the current brain")

    def test_hard_task_still_upgrades_when_provably_bigger(self):
        m = nova_router.pick_local_model(
            "hard", ["qwen2.5:3b", "phi4:latest"], "qwen2.5:0.5b")
        self.assertEqual(m, "qwen2.5:3b")

    def test_easy_task_still_picks_smallest(self):
        m = nova_router.pick_local_model(
            "easy", ["qwen2.5:0.5b", "llama3.1:latest"], "llama3.1:latest")
        self.assertEqual(m, "qwen2.5:0.5b")

    def test_comma_separated_files_signal_now_matches(self):
        # 'file, file' with a space after the comma used to never match
        # (\b cannot follow the comma when a space comes next)
        d_plain = nova_router.classify_difficulty(
            "two files: a.py, b.py")
        d_and = nova_router.classify_difficulty(
            "two files: a.py and b.py")
        self.assertEqual(d_plain, d_and,
                         "the comma and 'and' forms must score the same")


class TestThinkPrefix(unittest.TestCase):
    def test_prose_before_think_survives(self):
        out = nova_think.extract(
            "Sure! Here is the fix:\n=== THINK ===\nplan\n=== END ===\n"
            "```python\nprint(1)\n```")
        self.assertIn("Sure!", out["answer"])
        self.assertEqual(out["think"], "plan")

    def test_open_think_salvage_keeps_prefix(self):
        out = nova_think.extract(
            "Intro\n=== THINK ===\nhalf reasoning\n"
            "=== FILE: a.py ===\nprint(1)\n")
        self.assertIn("Intro", out["answer"])
        self.assertIn("=== FILE: a.py ===", out["answer"])

    def test_half_think_alone_stays_empty(self):
        out = nova_think.extract(
            "Preamble\n=== THINK ===\nhalf reasoning no end")
        self.assertEqual(out["answer"], "")
        self.assertTrue(out["open"])


class TestAutoContinueStitch(unittest.TestCase):
    """v8.11: the resume prompt says 'continue EXACTLY where it stopped',
    but the merge glued the continuation on with a BLANK LINE - a stream
    cut mid-token ('def fo' + 'o(bar):') wrote 'def fo\n\no(bar):' to
    disk. The corrupted file then sailed through every gate discussion
    as 'Nova's coding is broken' though the model's answer was perfect."""

    def _join(self, raw, cont):
        # the exact rule chat_turn's auto-continue uses (including the
        # nothing-usable guard)
        import re as _re
        if not (cont or "").strip():
            return raw or ""
        if _re.search(r"\w\Z", raw or "") and _re.match(r"\w", cont):
            return (raw or "") + cont
        return (raw or "").rstrip() + "\n\n" + cont.rstrip()

    def test_mid_token_cut_joins_directly(self):
        merged = self._join("=== FILE: a.py ===\nimport flask\n\ndef fo",
                            "o(bar):\n    return bar\n\n=== END ===")
        files, _edits = nova.parse_files(merged)
        self.assertTrue(files)
        body = files[0][1]
        self.assertIn("def foo(bar):", body,
                      "the mid-token continuation must be joined exactly")
        self.assertNotIn("def fo\n\no(bar):", body)

    def test_clean_line_cut_keeps_the_blank_line_join(self):
        merged = self._join("some answer text\n",
                            "more paragraphs follow")
        self.assertEqual(merged, "some answer text\n\nmore paragraphs follow")

    def test_empty_continuation_keeps_raw(self):
        self.assertEqual(self._join("kept", "   "), "kept")


class TestCtxDigestSurvivesRefolds(unittest.TestCase):
    def test_extract_user_redigests_a_digest_message(self):
        msg = {"role": "user",
               "content": ce._DIGEST_MARK + "\n"
                          "#1 user: build a flask app with login\n"
                          "#1 decision: use bcrypt hashing\n"
                          "files seen: server.py"}
        out = ce._extract_user(msg)
        self.assertIn("user: build a flask app with login", out)
        self.assertIn("decision: use bcrypt hashing", out)

    def test_two_folds_keep_goal_and_decision(self):
        hist = [
            {"role": "user", "content": "please build a flask app with login"},
            {"role": "assistant",
             "content": "decision: use bcrypt hashing\n" + ("x" * 400)},
            {"role": "user", "content": "now add tests for the login route"},
            {"role": "assistant", "content": "wrote the tests\n" + ("y" * 400)},
        ]
        h1, s1 = ce.compress_history(hist, budget_tokens=180,
                                     keep_recent=2, cpt=2.7)
        self.assertEqual(s1["mode"], "digest")
        hist2 = [h1[0]] + h1[1:] + [
            {"role": "user", "content": "add logout " + ("z" * 400)},
            {"role": "assistant", "content": "w " * 300},
        ]
        h2, s2 = ce.compress_history(hist2, budget_tokens=220,
                                     keep_recent=2, cpt=2.7)
        self.assertEqual(s2["mode"], "digest")
        d2 = h2[0]["content"]
        self.assertIn("flask app", d2, "goal lost on re-fold")
        self.assertIn("bcrypt", d2, "decision lost on re-fold")

    def test_tight_mode_walks_roles_not_even_indices(self):
        # the digest is bloated by an assistant decision line; tight mode
        # keeps only the user goals - with the OLD even-index walk the
        # digest-first history mislabeled assistant lines as 'user:'
        # BOTH assistant decisions are ~_MAX_LINE long, so the folded
        # digest exceeds even the 64-token headroom floor and tight mode
        # (goals only) has to fire
        hist = [
            {"role": "user", "content": "goal one"},
            {"role": "assistant",
             "content": "decision: " + ("x" * 150)},
            {"role": "user", "content": "goal two"},
            {"role": "assistant",
             "content": "decision: " + ("y" * 150)},
            {"role": "user", "content": "goal three"},
            {"role": "assistant", "content": "short reply"},
        ]
        h, s = ce.compress_history(hist, budget_tokens=30, keep_recent=2,
                                   cpt=2.7)
        self.assertEqual(s["mode"], "tight")
        body = h[0]["content"]
        self.assertIn("goal one", body, "the saved digest goal vanished")
        self.assertIn("goal two", body)
        self.assertNotIn("decision:", body,
                         "tight mode carries goals only")


class TestCtxSettingsContract(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_all_invalid_save_writes_nothing_and_admits_it(self):
        err = ce.save_settings(self.ws, {"local_ctx": 10 ** 9})
        self.assertTrue(err)
        self.assertFalse((self.ws / ".nova" / "context.json").exists())
        self.assertFalse(ce.load_settings(self.ws)["custom"])

    def test_valid_save_still_works(self):
        self.assertEqual(ce.save_settings(self.ws, {"local_ctx": 8192}), "")
        s = ce.load_settings(self.ws)
        self.assertEqual(s["local_ctx"], 8192)
        self.assertTrue(s["custom"])


# =====================================================================
# C. the loop that never ends
# =====================================================================
class TestSignatureAndGuards(unittest.TestCase):
    def test_two_real_errors_do_not_merge(self):
        a = nova.error_signature({"code": 1,
                                  "output": "TypeError: expect 2 args, got 3"})
        b = nova.error_signature({"code": 1,
                                  "output": "TypeError: expect 3 args, got 2"})
        self.assertNotEqual(a, b,
                            "digit-blanking merged two distinct errors")

    def test_line_number_drift_still_merges(self):
        a = nova.error_signature({"code": 1,
                                  "output": 'File "m.py", line 7\nNameError: x'})
        b = nova.error_signature({"code": 1,
                                  "output": 'File "m.py", line 9\nNameError: x'})
        self.assertEqual(a, b,
                         "the v8.8 drift guard must keep working")

    def test_permission_traceback_is_runnable(self):
        out = ("Traceback (most recent call last):\n"
               "PermissionError: [Errno 13] Access is denied: 'out.csv'")
        self.assertFalse(nova.is_unrunnable_failure(1, out),
                         "a program that ran and crashed is fixable")

    def test_shell_not_found_is_unrunnable(self):
        self.assertTrue(nova.is_unrunnable_failure(
            1, "sh: 1: deploy: not found"))
        self.assertTrue(nova.is_unrunnable_failure(127, "whatever"))
        self.assertFalse(nova.is_unrunnable_failure(1, ""))

    def test_vite_build_is_not_a_server(self):
        self.assertFalse(nova._looks_like_server("npx vite build"))
        self.assertFalse(nova._looks_like_server("vite build && npm test"))
        self.assertTrue(nova._looks_like_server("npx vite"))
        self.assertTrue(nova._looks_like_server("npm run dev"))

    def test_prerun_argv_file_is_not_gated(self):
        files = nova._prerun_named_files("python gen.py skeleton.py")
        self.assertEqual(files, ["gen.py"])

    def test_prerun_pytest_still_gates_all_named_tests(self):
        files = nova._prerun_named_files("pytest test_a.py test_b.py")
        self.assertIn("test_a.py", files)
        self.assertIn("test_b.py", files)

    def test_prerun_compound_segments_each_gate_their_entry(self):
        files = nova._prerun_named_files("python gen.py && python main.py")
        self.assertIn("gen.py", files)
        self.assertIn("main.py", files)


class TestAutoLoopBrakes(unittest.TestCase):
    """Behavioral: _auto_build_inner driven with stubbed chat_turn /
    run_command - the loop must stop honestly instead of cycling."""

    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.sess = types.SimpleNamespace(
            ws=self.ws, auto_yolo=True, policy={}, touched={},
            todo=None, ignore=None, last_failed=None, fix_rounds=0,
            last_feedback=None, last_cmd="", history=[], model="x",
            last_request="", explain=False, web_turn=False,
            pending_apply=None, last_run_cmd="",
            last_composed="", ctx_settings=None, limits={})
        self._old_noninteractive = nova.NONINTERACTIVE
        nova.NONINTERACTIVE = True

    def tearDown(self):
        nova.NONINTERACTIVE = self._old_noninteractive
        shutil.rmtree(self.ws, ignore_errors=True)

    def _drive(self, results, run_exit=1, failures=None):
        calls = {"chat": 0, "run": 0}

        def fake_chat(sess, text, auto=False):
            calls["chat"] += 1
            return results[min(calls["chat"], len(results)) - 1]

        def fake_run(sess, cmd, auto=False, origin="repl"):
            calls["run"] += 1
            if failures:
                f = failures[min(calls["run"], len(failures)) - 1]
                sess.last_failed = f
                return f.get("_exit", 1)
            sess.last_failed = {"cmd": cmd, "code": run_exit,
                                "output": "boom"}
            return run_exit

        old_chat, old_run = nova.chat_turn, nova.run_command
        nova.chat_turn, nova.run_command = fake_chat, fake_run
        try:
            nova._auto_build_inner(self.sess, "build it")
        finally:
            nova.chat_turn, nova.run_command = old_chat, old_run
        return calls

    def _res(self, **kw):
        base = {"answer": "work done", "files": [], "edits": [],
                "applied": [], "run_cmd": None, "run_exit": None,
                "complete": True}
        base.update(kw)
        return base

    def test_alternating_errors_stop_at_the_budget(self):
        # each round a DIFFERENT error: the old consecutive-only brake
        # never fired and the loop burned every step
        fails = [{"cmd": "python app.py", "code": 1, "output": "err A v%d" % i}
                 for i in range(9)]
        calls = self._drive([self._res(run_cmd="python app.py")] * 9,
                            failures=fails)
        self.assertLessEqual(calls["chat"] - 1, nova.MAX_FIX_ROUNDS,
                             "fix rounds must respect the session budget "
                             "(%d fired)" % (calls["chat"] - 1))

    def test_unrunnable_failure_never_gets_a_fix_round(self):
        calls = self._drive(
            [self._res(run_cmd="nope_v811")],
            failures=[{"cmd": "nope_v811", "code": 127,
                       "output": "/bin/sh: nope_v811: not found",
                       "_exit": 127}])
        self.assertEqual(calls["chat"], 1, "no fix round for a command "
                                           "the OS never ran")

    def test_timeout_never_gets_a_fix_round(self):
        calls = self._drive(
            [self._res(run_cmd="python serve.py")],
            failures=[{"cmd": "python serve.py", "code": "timeout",
                       "output": "", "_exit": -1}])
        self.assertEqual(calls["chat"], 1, "no fix round on a timeout")

    def test_refused_batch_skips_the_run_and_reports(self):
        ran = {"run": 0}

        def fake_run(sess, cmd, auto=False, origin="repl"):
            ran["run"] += 1
            return 0

        calls = {"chat": 0}
        old_chat, old_run = nova.chat_turn, nova.run_command
        self.sess.last_feedback = {"syntax": [("app.py", "bad")]}

        def counting_chat(sess, text, auto=False):
            calls["chat"] += 1
            # each round applies afresh - and the gates refuse it again
            # (the flag is per-turn: the real offer_apply raises it at
            # every refusal, the loop guard consumes it once)
            sess.batch_refused = True
            return self._res(run_cmd="python app.py",
                             files=["app.py"], applied=[])
        nova.chat_turn = counting_chat
        try:
            nova._auto_build_inner(self.sess, "build it")
        finally:
            nova.chat_turn, nova.run_command = old_chat, old_run
        self.assertEqual(ran["run"], 0,
                         "a refused batch must never run the stale command")
        self.assertGreaterEqual(calls["chat"], 2,
                                "the refusal must go back to the model")

    def test_empty_answer_is_not_a_success(self):
        finished = []

        class FakeLoop:
            def phase(self, *a, **k):
                pass

            def finish(self, ok, evidence=None, note=""):
                finished.append(ok)

            def record(self, *a, **k):
                pass

            def attempt(self):
                pass

        old_chat = nova.chat_turn
        nova.chat_turn = lambda *a, **k: self._res(answer="")
        try:
            nova._auto_build_inner(self.sess, "build it", loop=FakeLoop())
        finally:
            nova.chat_turn = old_chat
        self.assertEqual(finished, [],
                         "an empty answer must not be recorded as success")


class TestVerifyLoopBrakes(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.sess = types.SimpleNamespace(
            ws=self.ws, touched={}, last_failed=None, fix_rounds=0,
            last_feedback=None, last_cmd="python app.py", todo=None,
            history=[], model="x", last_request="", explain=False,
            limits={}, ignore=None)
        self._old_noninteractive = nova.NONINTERACTIVE
        nova.NONINTERACTIVE = True

    def tearDown(self):
        nova.NONINTERACTIVE = self._old_noninteractive
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_verify_stops_on_the_budget_with_alternating_errors(self):
        chats = {"n": 0}
        runs = {"n": 0}
        fails = [{"cmd": "python app.py", "code": 1,
                  "output": "err B%d" % i} for i in range(9)]

        def fake_chat(sess, text, auto=False):
            chats["n"] += 1
            return {"answer": "", "files": [], "edits": [], "applied": [],
                    "run_cmd": None}

        def fake_run(sess, cmd, auto=False, origin="repl"):
            runs["n"] += 1
            self.sess.last_failed = fails[min(runs["n"],
                                              len(fails)) - 1]
            return 1

        old_chat, old_run = nova.chat_turn, nova.run_command
        nova.chat_turn, nova.run_command = fake_chat, fake_run
        try:
            nova.verify_flow(self.sess, "python app.py")
        finally:
            nova.chat_turn, nova.run_command = old_chat, old_run
        self.assertLessEqual(chats["n"], nova.MAX_FIX_ROUNDS,
                             "verify fix rounds must respect the budget")


class TestPreviewAndFeedbackReset(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        (self.ws / "index.html").write_text("<p>hi</p>", encoding="utf-8")
        self.sess = types.SimpleNamespace(
            ws=self.ws, policy={}, touched={},
            last_failed={"cmd": "x", "code": 1, "output": "old"},
            fix_rounds=3, last_feedback={"lint": [("a", "b")]},
            last_cmd="", history=[], model="x", last_request="",
            explain=False, auto_yolo=True, todo=None,
            ignore=None, pending_apply=None, last_run_cmd="",
            web_turn=False, ctx_settings=None, last_composed="",
            limits={}, run_timeout=60)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_preview_green_resets_the_loop_state(self):
        code = nova.run_command(self.sess, "start index.html", auto=True)
        self.assertEqual(code, 0)
        self.assertIsNone(self.sess.last_failed,
                          "a preview is a green verdict - the stale "
                          "failure must not survive it")
        self.assertEqual(self.sess.fix_rounds, 0)

    def test_green_run_clears_all_gate_notes(self):
        (self.ws / "ok.py").write_text("print(1)\n", encoding="utf-8")
        code = nova.run_command(self.sess, "python ok.py", auto=True)
        self.assertEqual(code, 0)
        self.assertIsNone(self.sess.last_feedback)


# =====================================================================
# the web face of the same honesty
# =====================================================================
class TestWebDoneContract(unittest.TestCase):
    CODE_ERROR = {"cmd": "python app.py", "code": 1,
                  "output": "Traceback (most recent call last):\n"
                            "NameError: x"}

    def _drive(self, run_exit, chat_result=None):
        import web_server
        old_nova, old_state = web_server.nova, web_server.STATE
        rounds = []
        stub = types.SimpleNamespace(
            run_command=lambda *a, **k: run_exit,
            chat_turn=lambda *a, **k: (rounds.append(1) or chat_result or
                                       {"files": [], "edits": [],
                                        "applied": [], "answer": "fixed"}),
            build_fix_message=lambda *a, **k: "fix me",
            is_unrunnable_failure=nova.is_unrunnable_failure,
            _looks_like_server=nova._looks_like_server,
            fix_budget_left=nova.fix_budget_left,
            bump_fix_round=nova.bump_fix_round,
            reset_fix_rounds=nova.reset_fix_rounds,
            MAX_FIX_ROUNDS=nova.MAX_FIX_ROUNDS,
            c=nova.c, C=nova.C, TOKEN_SINK=None, EVENT_SINK=None,
        )
        web_server.nova = stub
        sess = types.SimpleNamespace(
            touched={}, pending_apply=None, autofix=True,
            last_failed=None, confirm_changes=False, fix_rounds=0)
        web_server.STATE = types.SimpleNamespace(sess=sess)
        try:
            sess.last_failed = dict(self.CODE_ERROR)
            h = object.__new__(web_server.Handler)
            events = []
            h._emit = events.append
            h._run_turn("run", "python app.py")
            return events, rounds
        finally:
            web_server.nova = old_nova
            web_server.STATE = old_state

    def test_fix_round_surfaces_its_run_hint(self):
        fx = {"files": ["a.py"], "edits": [], "applied": ["a.py"],
              "answer": "fixed", "run_cmd": "python a.py"}
        events, _rounds = self._drive(1, chat_result=fx)
        done = [e for e in events if e.get("t") == "done"][0]
        self.assertEqual(done.get("run_cmd"), "python a.py",
                         "the fix's fresh Run hint must reach the button")

    def test_done_without_a_fix_round_has_no_autofix_key(self):
        events, _rounds = self._drive(127)   # unrunnable: no fix fires
        done = [e for e in events if e.get("t") == "done"][0]
        self.assertNotIn("autofix", done)

    def test_brake_message_only_after_the_skips(self):
        # a timeout run prints the TIMEOUT skip, not the budget pause
        import contextlib
        buf = io.StringIO()
        events, rounds = None, None
        with contextlib.redirect_stdout(buf):
            events, rounds = self._drive(-1, chat_result={
                "files": [], "edits": [], "applied": [],
                "answer": "", "cmd": "python serve.py"})
        out = buf.getvalue()
        self.assertNotIn("paused - the last", out)
        self.assertIn("killed at the timeout", out)


# =====================================================================
# the design engine's opt-in must be opt-IN
# =====================================================================
class TestDesignImpliedContext(unittest.TestCase):
    def test_prose_mention_activates_nothing(self):
        page = ('<!doctype html><html><head><style>body{color:#222}'
                '</style></head><body><p>add the class nv-glass-2 to any '
                "card.</p></body></html>")
        self.assertEqual(nova_design._implied_layers(page), _spec())

    def test_class_attribute_still_implies(self):
        spec = nova_design._implied_layers('<div class="nv-glass-3">x</div>')
        self.assertEqual(spec["glass"], 0)

    def test_style_block_selectors_still_imply(self):
        spec = nova_design._implied_layers("<style>.nv-shadow-2{}</style>")
        self.assertEqual(spec["shadow"], 0)

    def test_classlist_call_still_implies(self):
        spec = nova_design._implied_layers(
            '<script>el.classList.add("nv-neon-2")</script>')
        self.assertEqual(spec["neon"], 0)

    def test_layers_href_matches_only_the_real_sheet(self):
        self.assertFalse(nova_design._LAYERS_LINK_HREF_RE.search(
            '<link href="nova-layers.css.old">'))
        self.assertEqual(
            nova_design._LAYERS_LINK_HREF_RE.findall(
                '<link rel="stylesheet" href="css/nova-layers.css">'),
            ["css/nova-layers.css"])


# =====================================================================
# source pins for the loop brakes
# =====================================================================
class TestSourcePins(unittest.TestCase):
    def test_stream_chat_carries_num_ctx(self):
        src = (APP / "nova.py").read_text(encoding="utf-8")
        self.assertIn('"num_ctx": (num_ctx or _eff_ctx(sess))', src)
        self.assertIn("num_ctx=_eff_ctx(sess)", src)

    def test_dispatch_routes_auto(self):
        src = (APP / "nova.py").read_text(encoding="utf-8")
        i = src.index("def dispatch(sess, line):")
        self.assertIn("auto_build(sess, line)", src[i:i + 900])

    def test_backfill_requires_applied_files(self):
        src = (APP / "nova.py").read_text(encoding="utf-8")
        i = src.index("elif not result.get(\"run_cmd\")")
        j = src.index("result[\"run_cmd\"] = sess.last_run_cmd", i)
        cond = src[i:j]
        self.assertIn("result.get(\"applied\")", cond)
        self.assertNotIn("or getattr(sess, \"pending_apply\", None)", cond,
                         "a staged batch must not resurrect the stale chip")


if __name__ == "__main__":
    unittest.main()
