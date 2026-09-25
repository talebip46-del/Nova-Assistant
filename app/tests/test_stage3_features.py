#!/usr/bin/env python3
"""Stage-3 feature tests: feedback loop, todo/plan parsing, skills,
background tasks, council helpers, git helpers. No network; git tests
only when a real git binary exists."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_feedback as fb
import nova_todo as todo
import nova_skills as sk
import nova_bg as bg
import nova_council as council
import nova_commitmsg as cm
from nova_policy import NovaIgnore


def mkfile(ws, rel, content):
    p = Path(ws) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TempWS(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_t3_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)


# ------------------------------------------------- feedback
class TestFeedback(TempWS):
    def test_good_and_bad_py(self):
        mkfile(self.ws, "good.py", "x = 1\n")
        mkfile(self.ws, "bad.py", "def f(:\n")
        probs = fb.check_files(self.ws, ["good.py", "bad.py"])
        self.assertEqual([p[0] for p in probs], ["bad.py"])

    def test_good_and_bad_json(self):
        mkfile(self.ws, "ok.json", '{"a": 1}')
        mkfile(self.ws, "no.json", "{bad")
        probs = fb.check_files(self.ws, ["ok.json", "no.json"])
        self.assertEqual([p[0] for p in probs], ["no.json"])

    def test_js_checked_when_node_present(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node not installed")
        mkfile(self.ws, "ok.js", "let x = 1;\n")
        mkfile(self.ws, "bad.js", "let x = ;\n")
        probs = fb.check_files(self.ws, ["ok.js", "bad.js"])
        self.assertEqual([p[0] for p in probs], ["bad.js"])

    def test_html_not_reported(self):
        mkfile(self.ws, "index.html", "<div>whatever</div>")
        self.assertEqual(fb.check_files(self.ws, ["index.html"]), [])

    def test_missing_file_ignored(self):
        self.assertEqual(fb.check_files(self.ws, ["ghost.py"]), [])

    def test_detect_pytest(self):
        mkfile(self.ws, "tests/test_x.py", "def test_x():\n    assert 1\n")
        cmd, source = fb.detect_test_cmd(self.ws)
        self.assertIsNotNone(cmd)
        self.assertIn("pytest", source.lower())

    def test_detect_none(self):
        mkfile(self.ws, "main.py", "print(1)\n")
        cmd, _ = fb.detect_test_cmd(self.ws)
        self.assertIsNone(cmd)

    def test_run_tests_reports(self):
        mkfile(self.ws, "tests/test_ok.py", "import unittest\n"
               "class T(unittest.TestCase):\n    def test_ok(self):\n"
               "        self.assertTrue(True)\n")
        res = fb.run_tests(self.ws, cmd=f'"{sys.executable}" -m unittest discover -s tests',
                           timeout=60)
        self.assertTrue(res["ok"])
        self.assertEqual(res["passed"], 1)

    def test_run_tests_failure_detected(self):
        mkfile(self.ws, "tests/test_bad.py", "import unittest\n"
               "class T(unittest.TestCase):\n    def test_bad(self):\n"
               "        self.assertTrue(False)\n")
        res = fb.run_tests(self.ws, cmd=f'"{sys.executable}" -m unittest discover -s tests',
                           timeout=60)
        self.assertFalse(res["ok"])
        self.assertEqual(res["failed"], 1)

    def test_no_test_setup(self):
        res = fb.run_tests(self.ws, timeout=30)
        # v8.0 honesty contract: "nothing ran" is n/a (None), NOT a pass
        self.assertIsNone(res["ok"])
        self.assertIsNone(res["exit"])
        self.assertFalse(res["ran"])


# ------------------------------------------------- todo
class TestTodo(unittest.TestCase):
    PLAN = ("intro text\n=== PLAN ===\n1. [x] setup\n2. write parser\n"
            "3. [ ] tests\n=== END ===\nfooter")

    def test_parse_plan(self):
        items = todo.parse_plan(self.PLAN)
        self.assertEqual(len(items), 3)
        self.assertTrue(items[0]["done"])
        self.assertFalse(items[1]["done"])
        self.assertEqual(items[1]["text"], "write parser")

    def test_last_block_wins(self):
        two = self.PLAN + "\n=== PLAN ===\n1. only-new\n=== END ==="
        items = todo.parse_plan(two)
        self.assertEqual(items, [{"done": False, "text": "only-new"}])

    def test_empty_block_ignored(self):
        self.assertEqual(todo.parse_plan("=== PLAN ===\n\n=== END ==="), [])

    def test_no_plan(self):
        self.assertEqual(todo.parse_plan("just text, no plan"), [])
        self.assertEqual(todo.parse_plan(None), [])

    def test_dash_and_paren_items(self):
        items = todo.parse_plan("=== PLAN ===\n- [X] a\n2) b\n* c\n=== END ===")
        self.assertEqual([i["text"] for i in items], ["a", "b", "c"])
        self.assertTrue(items[0]["done"])

    def test_render_progress(self):
        items = todo.parse_plan(self.PLAN)
        self.assertIn("1. [x] setup", todo.render(items))
        self.assertEqual(todo.progress(items), "1/3")
        self.assertFalse(todo.all_done(items))

    def test_status_prompt_capped(self):
        items = [{"done": False, "text": "x" * 300} for _ in range(20)]
        sp = todo.status_prompt(items)
        self.assertLess(len(sp), 900)
        self.assertIn("CURRENT TASK PLAN", sp)

    def test_cmd_items(self):
        items, msg = todo.cmd_items_from_args("add first", [])
        self.assertEqual(len(items), 1)
        items, msg = todo.cmd_items_from_args("done 1", items)
        self.assertTrue(items[0]["done"])
        items, msg = todo.cmd_items_from_args("del 1", items)
        self.assertEqual(items, [])
        items, msg = todo.cmd_items_from_args("bogus", items)
        self.assertIn("usage", msg)
        items, msg = todo.cmd_items_from_args("done 99", [{"done": False, "text": "a"}])
        self.assertIn("no item", msg)


# ------------------------------------------------- skills
class TestSkills(TempWS):
    def test_add_list_remove(self):
        self.assertEqual(sk.add(self.ws, "docker", "always add restart policy", trigger="docker"), "")
        skills = sk.list_skills(self.ws)
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["name"], "docker")
        sk.add(self.ws, "docker", "updated instructions")
        self.assertEqual(sk.get(self.ws, "docker")["instructions"], "updated instructions")
        sk.remove(self.ws, "docker")
        self.assertEqual(sk.list_skills(self.ws), [])

    def test_add_validation(self):
        self.assertTrue(sk.add(self.ws, "", "body"))
        self.assertTrue(sk.add(self.ws, "x", "  "))

    def test_record_success_threshold(self):
        r1 = sk.record_success(self.ws, "build a flask todo app", "python main.py")
        self.assertEqual(r1, "counted")
        r2 = sk.record_success(self.ws, "Build a Flask TODO app!", "python main.py")
        self.assertEqual(r2, "counted")     # normalization -> same signature
        r3 = sk.record_success(self.ws, "build a  flask todo app", "python main.py")
        self.assertTrue(r3.startswith("auto:"))
        name = r3.split(":", 1)[1]
        s = sk.get(self.ws, name)
        self.assertIsNotNone(s)
        self.assertTrue(s["auto"])

    def test_manual_skill_bump_on_match(self):
        sk.add(self.ws, "docker-deploy", "use restart: always", trigger="docker deploy")
        r = sk.record_success(self.ws, "help me docker deploy my app", "docker compose up -d")
        self.assertEqual(r, "bumped")
        self.assertEqual(sk.get(self.ws, "docker-deploy")["uses"], 1)

    def test_inject_text(self):
        sk.add(self.ws, "testing", "always use pytest fixtures", trigger="test")
        sk.bump(self.ws, "testing")
        text = sk.inject_text(self.ws)
        self.assertIn("Learned skills", text)
        self.assertIn("always use pytest fixtures", text)
        # empty workspace -> no injection
        ws2 = tempfile.mkdtemp(prefix="nova_sk2_")
        try:
            self.assertEqual(sk.inject_text(Path(ws2)), "")
        finally:
            import shutil
            shutil.rmtree(ws2, ignore_errors=True)

    def test_corrupt_files_fail_soft(self):
        d = self.ws / ".nova"
        d.mkdir(exist_ok=True)
        (d / "skills.json").write_text("}{", encoding="utf-8")
        (d / "skills_pending.json").write_text("nope", encoding="utf-8")
        self.assertEqual(sk.list_skills(self.ws), [])
        self.assertEqual(sk.inject_text(self.ws), "")
        self.assertIn(sk.record_success(self.ws, "some task", "ls"), ("counted", ""))


# ------------------------------------------------- background tasks
class TestBackground(TempWS):
    def test_start_finish_log(self):
        tid, err = bg.start(self.ws, "echo hello-bg", timeout=30)
        self.assertEqual(err, "")
        deadline = time.time() + 15
        while time.time() < deadline:
            meta = bg.get_task(self.ws, tid)
            if meta and meta["status"] != "running":
                break
            time.sleep(0.1)
        meta = bg.get_task(self.ws, tid)
        self.assertEqual(meta["status"], "finished")
        self.assertEqual(meta["exit"], 0)
        _, log = bg.tail_log(self.ws, tid)
        self.assertIn("hello-bg", log)

    def test_failing_command_status(self):
        tid, _ = bg.start(self.ws, "exit 3", timeout=30)
        deadline = time.time() + 15
        while time.time() < deadline:
            meta = bg.get_task(self.ws, tid)
            if meta and meta["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(bg.get_task(self.ws, tid)["status"], "failed")

    def test_empty_command_rejected(self):
        tid, err = bg.start(self.ws, "   ")
        self.assertEqual(tid, "")
        self.assertTrue(err)

    def test_no_such_task(self):
        meta, msg = bg.tail_log(self.ws, "b999")
        self.assertIsNone(meta)
        self.assertIn("no such task", msg)
        self.assertIn("no such task", bg.kill(self.ws, "b999"))

    def test_newly_finished_notification(self):
        tid, _ = bg.start(self.ws, "echo done-notify", timeout=30)
        deadline = time.time() + 15
        while time.time() < deadline:
            if bg.newly_finished(self.ws, since_ts=0):
                break
            time.sleep(0.1)
        fin = bg.newly_finished(self.ws, since_ts=0)
        self.assertTrue(any(m["id"] == tid for m in fin))

    def test_corrupt_meta_skipped(self):
        d = bg.bg_dir(self.ws)
        d.mkdir(parents=True, exist_ok=True)
        (d / "bbroken.json").write_text("{", encoding="utf-8")
        self.assertEqual(bg.list_tasks(self.ws), [])


# ------------------------------------------------- council helpers
class TestCouncil(unittest.TestCase):
    def test_resolve_explicit_provider(self):
        import nova_providers as prov
        name, model, label = council.resolve_partner("groq", "ollama", "nova-code", prov)
        self.assertEqual(name, "groq")
        self.assertEqual(model, prov.PROVIDERS["groq"]["model"])

    def test_resolve_provider_with_model(self):
        import nova_providers as prov
        name, model, _ = council.resolve_partner("openai:gpt-4o-mini", "ollama", "x", prov)
        self.assertEqual((name, model), ("openai", "gpt-4o-mini"))

    def test_resolve_unknown_is_ollama_model(self):
        import nova_providers as prov
        name, model, _ = council.resolve_partner("qwen2.5:7b", "ollama", "nova-code", prov)
        self.assertEqual((name, model), ("ollama", "qwen2.5:7b"))

    def test_resolve_no_partner_raises(self):
        import nova_providers as prov
        with self.assertRaises(ValueError):
            council.resolve_partner("", "ollama", "nova-code", prov, ollama_models=["nova-code"])

    def test_resolve_default_second_local_model(self):
        import nova_providers as prov
        name, model, _ = council.resolve_partner(
            "", "ollama", "nova-code", prov,
            ollama_models=["nova-code", "qwen2.5-coder:14b"])
        self.assertEqual((name, model), ("ollama", "qwen2.5-coder:14b"))

    def test_partner_persistence(self):
        import tempfile, shutil
        ws = Path(tempfile.mkdtemp(prefix="nova_c_"))
        try:
            self.assertEqual(council.load_partner(ws), "")
            council.save_partner(ws, "groq")
            self.assertEqual(council.load_partner(ws), "groq")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_judge_prompt_shape(self):
        p = council.judge_prompt("question", "answer A", "answer B", "X", "Y")
        self.assertIn("Answer A (X)", p)
        self.assertIn("Answer B (Y)", p)
        self.assertIn("one-line verdict", p)

    def test_collect_ollama_error_is_clean(self):
        with self.assertRaises(urllib.error.URLError):
            council.collect_ollama("m", [{"role": "user", "content": "hi"}],
                                   0.2, 2, "http://localhost:1")


# ------------------------------------------------- git helpers
class TestGitHelpers(TempWS):
    GIT = cm.git_available()

    def _git_init(self):
        subprocess.run("git init -q", shell=True, cwd=str(self.ws), check=True)
        subprocess.run("git config user.email t@t.io && git config user.name T",
                       shell=True, cwd=str(self.ws), check=True)

    def test_heuristic_message(self):
        msg = cm.heuristic_message("", "build a todo app\nsecond line",
                                   ["app.py", "a.js", "b.js", "c.js"], ["x.py"])
        self.assertTrue(msg.startswith(cm.NOVA_PREFIX))
        self.assertIn("new app.py, a.js, b.js +1", msg)
        self.assertIn("edit x.py", msg)
        self.assertIn("build a todo app", msg)
        self.assertLessEqual(len(msg), 150)

    def test_excludes_written(self):
        self._git_init()
        self.assertEqual(cm.ensure_excludes(self.ws), "")
        excl = (self.ws / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn(".nova/", excl)
        # idempotent
        cm.ensure_excludes(self.ws)
        excl2 = (self.ws / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertEqual(excl2.count(".nova/"), 1)

    def test_auto_commit_flow(self):
        if not self.GIT:
            self.skipTest("git missing")
        self._git_init()
        cm.ensure_excludes(self.ws)
        f = mkfile(self.ws, "app.py", "print(1)\n")
        ok, detail = cm.auto_commit(self.ws, cm.heuristic_message(
            "", "first commit test", ["app.py"], []), [f])
        self.assertTrue(ok, detail)
        log = subprocess.run("git log --oneline", shell=True, cwd=str(self.ws),
                             capture_output=True, text=True).stdout
        self.assertIn(cm.NOVA_PREFIX, log)

    def test_auto_commit_no_repo(self):
        f = mkfile(self.ws, "app.py", "x\n")
        ok, detail = cm.auto_commit(self.ws, "nova: test", [f])
        self.assertFalse(ok)
        self.assertEqual(detail, "")

    def test_session_helpers_empty(self):
        if not self.GIT:
            self.skipTest("git missing")
        self._git_init()
        rows = cm.session_log(self.ws)
        self.assertEqual(rows, [])
        prompt, n = cm.build_pr_prompt(self.ws)
        self.assertEqual((prompt, n), ("", 0))

    def test_pr_prompt_after_commits(self):
        if not self.GIT:
            self.skipTest("git missing")
        self._git_init()
        cm.ensure_excludes(self.ws)
        for i in range(2):
            f = mkfile(self.ws, f"f{i}.py", f"print({i})\n")
            cm.auto_commit(self.ws, f"{cm.NOVA_PREFIX} step {i}", [f])
        prompt, n = cm.build_pr_prompt(self.ws)
        self.assertEqual(n, 2)
        self.assertIn("TITLE:", prompt)
        self.assertIn("Diff stat", prompt)


if __name__ == "__main__":
    unittest.main()
