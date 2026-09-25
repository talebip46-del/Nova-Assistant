#!/usr/bin/env python3
"""v8.11.0 tests: the PRE-RUN GATE + the fix-loop brake - the user's report.

"بعد اینکه کد اماده شد و من میام دکمه run رو بزنم یهویی خطای سینتکسی پیدا
میشه و هوش مصنوعی و نوا میرن برای درست کردنش ولی من میخوام کلا قبل از اجرا
از درست بودن سینتکس و بدون باگ بودن مطمعن شن و اصلا وقتی توی این حالت میرن
برای درست کردنش انگار توی یک لوپ گیر میکننن و کارشون تموم نمیشه"

Two defects, every one pinned here:

  1. Run executed whatever the command named - a syntax error surfaced
     only as a runtime traceback, and only THEN did the fix machinery
     wake up. The v8.8 pre-run gate syntax-checks the files the command
     will actually EXECUTE (interpreter-led segments only + the local
     import closure of a Python entry) BEFORE the shell sees the
     command; a file that cannot parse is never run - the exact errors
     ride in sess.last_failed for one bounded fix round instead.

     False-positive discipline (the same check the apply gate uses):
       - 'git diff main.py' / 'cat app.js' / 'rm bad.py' never gate
         (they do not execute the file);
       - redirection targets are data sinks, not executed syntax;
       - HTML/CSS/JSON stay out of scope (rendered/data files);
       - stdlib/site-packages imports are never chased (existence test);
       - anything ambiguous fails OPEN (the real run stays the judge).

  2. The fix cycle could spin forever: the 'same error twice' guards in
     /auto and /verify compared the output tail byte-for-byte (a shifted
     line number defeated them), and the web autofix fired one bounded
     round PER CLICK with no session-level stop. v8.8 adds the
     normalized error_signature() alongside the exact one, plus a
     MAX_FIX_ROUNDS brake that pauses auto-fix with an honest message
     until a green run (or /autofix on) re-arms it.

All tests are NETWORK-FREE; nothing here calls the model.
"""
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova  # noqa: E402
import web_server  # noqa: E402


def _tmp_ws(testcase):
    import shutil
    d = tempfile.mkdtemp(prefix="nova_v88_")
    testcase.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return Path(d)


class _Sess:
    """A minimal stand-in for the file-scan helpers (no Session machinery
    needed: the pre-run gate only reads the workspace)."""
    def __init__(self, ws):
        self.ws = ws


BROKEN_PY = "def f(:\n    pass\n"
GOOD_PY = "def f():\n    return 1\n"


# --------------------------------------------------------------- extraction
class TestPrerunNamedFiles(unittest.TestCase):
    """_prerun_named_files: only files an interpreter will EXECUTE."""

    def test_interpreter_led_commands_gate_their_entry(self):
        for cmd, want in (("python main.py", "main.py"),
                          ("python3 main.py", "main.py"),
                          ("py -3 main.py", "main.py"),
                          ("python3.11 main.py", "main.py"),
                          ("node app.js --serve", "app.js"),
                          ("pytest -q test_app.py", "test_app.py"),
                          ("./main.py --help", "main.py"),
                          ("python main.py arg1 arg2", "main.py")):
            got = nova._prerun_named_files(cmd)
            self.assertIn(want, got, cmd)

    def test_non_executor_commands_never_gate(self):
        # the false-positive discipline: mentioning a file is not running it
        for cmd in ("git diff main.py", "cat app.js", "rm broken.py",
                    "echo hello", "ls -la", "pip install -r reqs.txt",
                    "git add main.py", "code main.py"):
            self.assertEqual(nova._prerun_named_files(cmd), [], cmd)

    def test_compound_commands_gate_only_executor_segments(self):
        self.assertEqual(nova._prerun_named_files("echo x && python main.py"),
                         ["main.py"])
        self.assertEqual(nova._prerun_named_files("python a.py | grep foo"),
                         ["a.py"])
        self.assertEqual(nova._prerun_named_files("cat b.js ; node a.js"),
                         ["a.js"])

    def test_redirect_targets_are_stripped(self):
        # a redirection WRITES the file - it is never executed syntax
        self.assertEqual(nova._prerun_named_files("python build.py > out.py"),
                         ["build.py"])
        self.assertEqual(nova._prerun_named_files("python a.py 2> err.js"),
                         ["a.py"])

    def test_data_and_markup_extensions_stay_out_of_scope(self):
        # html/css/json are data/rendered files - the apply gate guards
        # them at write time; the run gate only cares about executed code
        self.assertEqual(nova._prerun_named_files("python app.py cfg.json"),
                         ["app.py"])
        self.assertEqual(nova._prerun_named_files("node gen.js template.html"),
                         ["gen.js"])


# ----------------------------------------------------------------- closure
class TestPrerunClosure(unittest.TestCase):
    """The local import closure: 'python main.py' must see utils.py too."""

    def test_same_dir_imports_are_followed(self):
        ws = _tmp_ws(self)
        (ws / "main.py").write_text(
            "import utils\nimport os\nfrom helpers import h\n", encoding="utf-8")
        (ws / "utils.py").write_text(GOOD_PY, encoding="utf-8")
        (ws / "helpers.py").write_text(GOOD_PY, encoding="utf-8")
        files = nova._prerun_candidate_files(_Sess(ws), "python main.py")
        self.assertIn("main.py", files)
        self.assertIn("utils.py", files)
        self.assertIn("helpers.py", files)

    def test_stdlib_and_missing_modules_are_never_chased(self):
        ws = _tmp_ws(self)
        (ws / "main.py").write_text(
            "import os\nimport sys\nimport requests\nfrom json import loads\n",
            encoding="utf-8")
        files = nova._prerun_candidate_files(_Sess(ws), "python main.py")
        self.assertEqual(files, ["main.py"])

    def test_package_import_follows_init_and_module(self):
        ws = _tmp_ws(self)
        (ws / "pkg").mkdir()
        (ws / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (ws / "pkg" / "core.py").write_text(GOOD_PY, encoding="utf-8")
        (ws / "run.py").write_text("from pkg.core import c\n", encoding="utf-8")
        files = nova._prerun_candidate_files(_Sess(ws), "python run.py")
        self.assertIn("pkg/__init__.py", files)
        self.assertIn("pkg/core.py", files)

    def test_relative_imports_are_followed(self):
        ws = _tmp_ws(self)
        (ws / "pkg").mkdir()
        (ws / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (ws / "pkg" / "mod.py").write_text(
            "from . import core\nfrom .helper import h2\n", encoding="utf-8")
        (ws / "pkg" / "core.py").write_text(GOOD_PY, encoding="utf-8")
        (ws / "pkg" / "helper.py").write_text(GOOD_PY, encoding="utf-8")
        files = nova._prerun_candidate_files(_Sess(ws), "python pkg/mod.py")
        self.assertIn("pkg/core.py", files)
        self.assertIn("pkg/helper.py", files)

    def test_closure_is_bounded(self):
        ws = _tmp_ws(self)
        (ws / "main.py").write_text("import m0\n", encoding="utf-8")
        for i in range(30):
            (ws / ("m%d.py" % i)).write_text(
                "import m%d\n" % (i + 1), encoding="utf-8")
        files = nova._prerun_candidate_files(_Sess(ws), "python main.py")
        self.assertLessEqual(len(files), nova.PRERUN_FILE_CAP)


# -------------------------------------------------------------------- gate
class TestPrerunGate(unittest.TestCase):
    """_prerun_gate: deterministic, offline, fail-open."""

    def test_broken_entry_is_refused_with_exact_problem(self):
        ws = _tmp_ws(self)
        (ws / "main.py").write_text(BROKEN_PY, encoding="utf-8")
        probs = nova._prerun_gate(_Sess(ws), "python main.py")
        self.assertEqual(len(probs), 1)
        rel, problem = probs[0]
        self.assertEqual(rel, "main.py")
        self.assertIn("line", problem.lower())

    def test_broken_imported_module_is_caught_even_though_not_named(self):
        ws = _tmp_ws(self)
        (ws / "main.py").write_text("import utils\n", encoding="utf-8")
        (ws / "utils.py").write_text(BROKEN_PY, encoding="utf-8")
        probs = nova._prerun_gate(_Sess(ws), "python main.py")
        self.assertEqual([r for r, _p in probs], ["utils.py"])

    def test_clean_workspace_passes(self):
        ws = _tmp_ws(self)
        (ws / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (ws / "app.js").write_text("console.log(1);\n", encoding="utf-8")
        self.assertEqual(nova._prerun_gate(_Sess(ws), "python main.py"), [])
        self.assertEqual(nova._prerun_gate(_Sess(ws), "node app.js"), [])

    def test_empty_and_missing_files_fail_open(self):
        ws = _tmp_ws(self)
        (ws / "empty.py").write_text("", encoding="utf-8")
        self.assertEqual(nova._prerun_gate(_Sess(ws), "python empty.py"), [])
        self.assertEqual(nova._prerun_gate(_Sess(ws), "python gone.py"), [])

    def test_non_executor_commands_are_never_refused(self):
        # a broken file sitting in the workspace must not block git/cat
        ws = _tmp_ws(self)
        (ws / "main.py").write_text(BROKEN_PY, encoding="utf-8")
        self.assertEqual(nova._prerun_gate(_Sess(ws), "git diff main.py"), [])
        self.assertEqual(nova._prerun_gate(_Sess(ws), "cat main.py"), [])

    def test_broken_js_entry_is_refused_when_node_exists(self):
        ws = _tmp_ws(self)
        (ws / "app.js").write_text("function {(;\n", encoding="utf-8")
        node = nova.shutil.which("node") if hasattr(nova, "shutil") \
            else __import__("shutil").which("node")
        if not node:
            self.skipTest("node not installed")
        probs = nova._prerun_gate(_Sess(ws), "node app.js")
        self.assertEqual([r for r, _p in probs], ["app.js"])


# ------------------------------------------------- run_command integration
class TestRunCommandGate(unittest.TestCase):
    """The gate inside the real run_command: nothing executes, evidence
    lands in sess.last_failed, the loop brake resets on a green run."""

    def setUp(self):
        self.ws = _tmp_ws(self)
        self.sess = nova.Session(self.ws)
        self.sess.model = "fake:7b"
        self.sess._local_brain = lambda: True

    def test_broken_entry_never_reaches_the_shell(self):
        (self.ws / "main.py").write_text(BROKEN_PY, encoding="utf-8")
        marker = self.ws / "ran.txt"
        code = nova.run_command(self.sess, "python main.py; echo RAN > ran.txt",
                                auto=True)
        self.assertEqual(code, nova.PRERUN_EXIT)
        self.assertFalse(marker.exists())     # the shell NEVER saw it
        self.assertIsNotNone(self.sess.last_failed)
        self.assertEqual(self.sess.last_failed["code"], "prerun")
        self.assertIn("main.py", self.sess.last_failed["output"])
        # the evidence must survive the unrunnable filter (so the autofix
        # round really fires instead of being skipped)
        self.assertFalse(nova.is_unrunnable_failure(
            code, self.sess.last_failed["output"]))

    def test_broken_import_blocks_the_run_too(self):
        (self.ws / "main.py").write_text("import utils\n", encoding="utf-8")
        (self.ws / "utils.py").write_text(BROKEN_PY, encoding="utf-8")
        code = nova.run_command(self.sess, "python main.py", auto=True)
        self.assertEqual(code, nova.PRERUN_EXIT)
        self.assertIn("utils.py", self.sess.last_failed["output"])

    def test_green_run_executes_and_resets_the_brake(self):
        (self.ws / "main.py").write_text("print('hi')\n", encoding="utf-8")
        self.sess.fix_rounds = 2
        code = nova.run_command(self.sess, "python main.py", auto=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.sess.fix_rounds, 0)
        self.assertIsNone(self.sess.last_failed)

    def test_repl_path_offers_the_fix_instead_of_crashing(self):
        (self.ws / "main.py").write_text(BROKEN_PY, encoding="utf-8")
        with mock.patch.object(nova, "offer_fix") as ofix:
            code = nova.run_command(self.sess, "python main.py", auto=False)
        self.assertEqual(code, nova.PRERUN_EXIT)
        ofix.assert_called_once_with(self.sess)

    def test_after_the_fix_the_same_command_runs(self):
        (self.ws / "main.py").write_text(BROKEN_PY, encoding="utf-8")
        first = nova.run_command(self.sess, "python main.py", auto=True)
        self.assertEqual(first, nova.PRERUN_EXIT)
        (self.ws / "main.py").write_text(GOOD_PY, encoding="utf-8")
        second = nova.run_command(self.sess, "python main.py", auto=True)
        self.assertEqual(second, 0)


# ---------------------------------------------------------- loop brakes v8.8
class TestErrorSignature(unittest.TestCase):
    """error_signature: 'line 3' and 'line 7' are the SAME root cause."""

    def test_shifted_line_numbers_normalize_to_the_same_signature(self):
        a = {"code": 1, "output": 'File "main.py", line 3\nSyntaxError: invalid syntax'}
        b = {"code": 1, "output": 'File "main.py", line 7\nSyntaxError: invalid syntax'}
        self.assertEqual(nova.error_signature(a), nova.error_signature(b))

    def test_different_errors_stay_different(self):
        a = {"code": 1, "output": "SyntaxError: invalid syntax"}
        b = {"code": 1, "output": "NameError: name 'x' is not defined"}
        self.assertNotEqual(nova.error_signature(a), nova.error_signature(b))

    def test_exit_code_is_part_of_the_signature(self):
        a = {"code": 1, "output": "boom"}
        b = {"code": 2, "output": "boom"}
        self.assertNotEqual(nova.error_signature(a), nova.error_signature(b))

    def test_timestamp_and_whitespace_noise_is_absorbed(self):
        a = {"code": 1, "output": "[12:00:01]  ERROR   boom"}
        b = {"code": 1, "output": "[12:00:59]  ERROR boom"}
        self.assertEqual(nova.error_signature(a), nova.error_signature(b))


class TestFixBudget(unittest.TestCase):
    """The session-level brake: MAX_FIX_ROUNDS, re-armed honestly."""

    def test_budget_counts_down_and_resets(self):
        sess = types.SimpleNamespace(fix_rounds=0)
        self.assertEqual(nova.fix_budget_left(sess), nova.MAX_FIX_ROUNDS)
        for i in range(nova.MAX_FIX_ROUNDS):
            nova.bump_fix_round(sess)
        self.assertEqual(nova.fix_budget_left(sess), 0)
        nova.reset_fix_rounds(sess)
        self.assertEqual(nova.fix_budget_left(sess), nova.MAX_FIX_ROUNDS)

    def test_missing_attr_degrades_to_full_budget(self):
        sess = object()
        self.assertEqual(nova.fix_budget_left(sess), nova.MAX_FIX_ROUNDS)

    def test_env_override_is_clamped(self):
        with mock.patch.dict(os.environ, {"NOVA_FIX_ROUNDS": "99"}):
            self.assertLessEqual(nova.MAX_FIX_ROUNDS, 8)
        with mock.patch.dict(os.environ, {"NOVA_FIX_ROUNDS": "0"}):
            self.assertGreaterEqual(nova.MAX_FIX_ROUNDS, 1)

    def test_workspace_switch_re_arms(self):
        sess = nova.Session(_tmp_ws(self))
        sess.fix_rounds = 3
        sess.set_workspace(_tmp_ws(self))
        self.assertEqual(sess.fix_rounds, 0)


class TestWebAutofixBrake(unittest.TestCase):
    """BEHAVIORAL: the web auto-fix block honors the brake - one round per
    failure while the budget lasts, then an honest stop with zero rounds."""

    PRERUN_ERR = {"cmd": "python main.py", "code": "prerun",
                  "output": "SYNTAX ERROR in main.py: Python syntax error: "
                            "line 1: invalid syntax\n"
                            "(pre-run gate: the command never ran)"}

    def setUp(self):
        self._old_nova = web_server.nova
        self._old_state = web_server.STATE
        stub = types.SimpleNamespace(
            is_unrunnable_failure=nova.is_unrunnable_failure,
            _looks_like_server=nova._looks_like_server,
            fix_budget_left=nova.fix_budget_left,
            bump_fix_round=nova.bump_fix_round,
            reset_fix_rounds=nova.reset_fix_rounds,
            MAX_FIX_ROUNDS=nova.MAX_FIX_ROUNDS,
            build_fix_message=lambda *a, **k: "fix me",
            dispatch=lambda *a, **k: None,
            c=nova.c, C=nova.C, TOKEN_SINK=None, EVENT_SINK=None,
        )
        self._code = {"v": nova.PRERUN_EXIT}
        stub.run_command = lambda *a, **k: self._code["v"]
        self._rounds = []
        stub.chat_turn = lambda *a, **k: (
            self._rounds.append(1) or
            {"files": [], "edits": [], "applied": []})
        web_server.nova = stub
        self.sess = types.SimpleNamespace(
            touched={}, pending_apply=None, autofix=True,
            last_failed=None, confirm_changes=False, fix_rounds=0)
        web_server.STATE = types.SimpleNamespace(sess=self.sess)
        self.addCleanup(self._restore_state)

    def _restore_state(self):
        web_server.nova = self._old_nova
        web_server.STATE = self._old_state

    def _drive(self, last_failed):
        self.sess.last_failed = last_failed
        h = object.__new__(web_server.Handler)
        events = []
        h._emit = events.append
        h._run_turn("run", "python main.py")
        return events

    def test_prerun_failure_fires_one_fix_round(self):
        events = self._drive(dict(self.PRERUN_ERR))
        self.assertEqual(len(self._rounds), 1)
        self.assertEqual(self.sess.fix_rounds, 1)
        dones = [e for e in events if e.get("t") == "done"]
        self.assertEqual(len(dones), 1)

    def test_brake_stops_the_loop_with_zero_rounds(self):
        self.sess.fix_rounds = nova.MAX_FIX_ROUNDS   # budget exhausted
        events = self._drive(dict(self.PRERUN_ERR))
        self.assertEqual(self._rounds, [])           # NO round fired
        self.assertEqual(self.sess.fix_rounds, nova.MAX_FIX_ROUNDS)
        dones = [e for e in events if e.get("t") == "done"]
        self.assertEqual(len(dones), 1)              # the turn still lands
        errs = [e for e in events if e.get("t") == "err"]
        self.assertEqual(errs, [])                   # and stays honest

    def test_green_run_re_arms_the_brake(self):
        # the real run_command does this; pinned here via the helper the
        # handler shares with it
        self.sess.fix_rounds = nova.MAX_FIX_ROUNDS
        nova.reset_fix_rounds(self.sess)
        self.assertEqual(nova.fix_budget_left(self.sess), nova.MAX_FIX_ROUNDS)

    def test_autofix_on_re_arms_the_brake(self):
        self.sess.fix_rounds = nova.MAX_FIX_ROUNDS
        h = object.__new__(web_server.Handler)
        h._run_turn("chat", "/autofix on")
        self.assertTrue(self.sess.autofix)
        self.assertEqual(self.sess.fix_rounds, 0)


# ---------------------------------------------------------- web UI surface
class TestWebUiEvent(unittest.TestCase):
    """The browser learns about a refused run through prerun_reject."""

    def test_index_html_handles_prerun_reject(self):
        src = (APP / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('ev.t === "prerun_reject"', src)
        self.assertIn("خطای سینتکس پیش از اجرا", src)

    def test_index_html_js_still_parses(self):
        import tempfile as tf
        src = (APP / "web" / "index.html").read_text(encoding="utf-8")
        blocks = re.findall(r"<script>(.*?)</script>", src, re.S)
        self.assertTrue(blocks)
        for b in blocks:
            with tf.NamedTemporaryFile("w", suffix=".js", delete=False,
                                       encoding="utf-8") as f:
                f.write(b)
                path = f.name
            try:
                r = subprocess.run(["node", "--check", path],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[:200])
            finally:
                os.unlink(path)


# -------------------------------------------------------------- version pin
class TestVersionPin(unittest.TestCase):
    def test_version_is_880(self):
        self.assertEqual(nova.VERSION, "8.12.0")

    def test_codename_is_prerun_gate(self):
        self.assertEqual(nova.CODENAME, "master switch")

    def test_prerun_constants_are_sane(self):
        self.assertEqual(nova.PRERUN_EXIT, -2)
        self.assertGreaterEqual(nova.PRERUN_FILE_CAP, 4)
        self.assertLessEqual(nova.PRERUN_FILE_CAP, 64)
        self.assertGreaterEqual(nova.PRERUN_FILE_BYTES, 100_000)

    def test_gate_wiring_sits_after_policy_before_spawn(self):
        src = (APP / "nova.py").read_text(encoding="utf-8")
        i_policy = src.index("verdict = npol.check_command(sess.policy, cmd)")
        i_gate = src.index("prerun = _prerun_gate(sess, cmd)")
        i_spawn = src.index("proc = subprocess.Popen(")
        self.assertLess(i_policy, i_gate)
        self.assertLess(i_gate, i_spawn)

    def test_loop_guards_use_the_normalized_signature(self):
        src = (APP / "nova.py").read_text(encoding="utf-8")
        # both autonomous loops must consult error_signature
        # (v8.11: the normalized value is computed once per round as
        # `norm = error_signature(f)` and checked against last_norm AND
        # the last few rounds - the consecutive-only check was evaded
        # by alternating failures)
        i_auto = src.index("def _auto_build_inner")
        i_verify = src.index("def verify_flow")
        i_auto_use = src.index("norm = error_signature(f)", i_auto)
        self.assertLess(i_auto, i_auto_use)
        self.assertLess(i_auto_use, i_verify)
        i_auto_cmp = src.index("norm == last_norm or norm in recent_norms", i_auto)
        self.assertLess(i_auto_use, i_auto_cmp)
        i_verify_use = src.index("norm = error_signature(f)", i_verify)
        self.assertLess(i_verify, i_verify_use)
        i_verify_cmp = src.index("norm == last_norm or norm in recent_norms", i_verify)
        self.assertLess(i_verify_use, i_verify_cmp)

    def test_loops_carry_the_v811_brakes(self):
        src = (APP / "nova.py").read_text(encoding="utf-8")
        # v8.11: the terminal loops enforce the SAME fix budget and the
        # same web-parity skips the web face has had since v7.7/v8.8
        i_auto = src.index("def _auto_build_inner")
        i_verify = src.index("def verify_flow")
        i_end = src.index("def build_fix_message")
        body = src[i_auto:i_end]
        for needle in ('fix_budget_left(sess) <= 0',
                       'bump_fix_round(sess)',
                       'is_unrunnable_failure(f.get("code")',
                       'norm == last_norm or norm in recent_norms',
                       'collect_error_files(sess, f["output"], f["cmd"])',
                       'gates refused the model\'s files'):
            self.assertIn(needle, body)



if __name__ == "__main__":
    unittest.main()
