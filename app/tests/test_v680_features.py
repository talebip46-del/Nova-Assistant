#!/usr/bin/env python3
"""v6.8 feature tests: edit harness (git commit-per-edit, unified patch,
atomic transactions, pre-apply lint), autonomy (sub-agents, self-test
helpers), local models (hardware, bench), quality (linter, coverage,
docs), security (secretbox at-rest encryption, rlimits, sandbox) and UX
(doctor wizard, timeline, dependency graph). Pure stdlib, temp dirs,
no network (Ollama calls are faked)."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova as nova
import nova_astmap as astmap
import nova_bench as bench
import nova_depgraph as depgraph
import nova_diffview as diffview
import nova_hardware as hardware
import nova_memory as nmem
import nova_quality as quality
import nova_rlimits as rlimits
import nova_sandbox as sandbox
import nova_secretbox as secretbox
import nova_subagent as subagent


def _mkws():
    return Path(tempfile.mkdtemp(prefix="nova_v680_"))


def _bare_session(ws):
    """A Session without __init__ side effects, wired for the apply path."""
    s = nova.Session.__new__(nova.Session)
    s.ws = ws
    s.last_batch = []
    s.touched = {}
    s.last_request = ""
    s.last_feedback = None
    s.autotest = False
    s.auto = False
    s.auto_yolo = False
    s.explain = False
    s.mode = "code"
    s.limits = {"cpu_s": 0, "ram_mb": 0}
    s.lock_pass = None
    s.rescan = lambda *a, **k: None
    return s


# =====================================================================
class TestSecretBox(unittest.TestCase):
    def test_roundtrip_unicode(self):
        key = secretbox.derive_key("pass-فارسی", secretbox.new_salt())
        msg = "سلام Nova 🚀\nline2"
        blob = secretbox.seal_bytes(msg.encode("utf-8"), key)
        self.assertEqual(secretbox.open_bytes(blob, key).decode("utf-8"), msg)

    def test_tamper_rejected(self):
        key = secretbox.derive_key("pw", secretbox.new_salt())
        blob = bytearray(secretbox.seal_bytes(b"secret data", key))
        blob[-1] ^= 0x01                     # flip the LAST tag byte
        with self.assertRaises(ValueError):
            secretbox.open_bytes(bytes(blob), key)

    def test_wrong_key_rejected(self):
        k1 = secretbox.derive_key("pw1", secretbox.new_salt())
        k2 = secretbox.derive_key("pw2", secretbox.new_salt())
        blob = secretbox.seal_bytes(b"data", k1)
        with self.assertRaises(ValueError):
            secretbox.open_bytes(blob, k2)

    def test_self_test(self):
        ok, msg = secretbox.self_test()
        self.assertTrue(ok, msg)

    def test_file_seal(self):
        ws = _mkws()
        try:
            p = ws / "mem.json.enc"
            key = secretbox.derive_key("pp", secretbox.new_salt())
            secretbox.seal_file(p, '{"history": ["سلام"]}', key)
            self.assertTrue(secretbox.is_sealed(p))
            self.assertFalse(secretbox.is_sealed(ws / "missing.json.enc"))
            self.assertEqual(
                secretbox.open_file(p, key).decode("utf-8"),
                '{"history": ["سلام"]}')
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestMemoryEncryption(unittest.TestCase):
    def setUp(self):
        self.ws = _mkws()
        nmem.set_cipher(None)                # clean slate per test

    def tearDown(self):
        nmem.set_cipher(None)
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_plaintext_default(self):
        nmem.save_memory(self.ws, [{"role": "user", "content": "a"}], [])
        self.assertTrue(nmem.memory_path(self.ws).is_file())
        self.assertFalse(nmem.encryption_on())

    def test_sealed_roundtrip_and_plaintext_removal(self):
        self.assertTrue(nmem.set_cipher("s3cret"))
        nmem.save_memory(self.ws, [{"role": "user", "content": "رمز"}],
                         [("user", "رمز")], extra={"model": "m"})
        p = nmem.memory_path(self.ws)
        enc = p.with_name(nmem.MEMORY_ENC_FILE)
        self.assertTrue(enc.is_file())
        self.assertFalse(p.is_file(), "plaintext twin must be gone")
        self.assertEqual(enc.read_bytes()[:5], secretbox.MAGIC)
        h, t, m = nmem.load_memory(self.ws)
        self.assertEqual(h[0]["content"], "رمز")
        self.assertEqual(m.get("model"), "m")
        self.assertFalse(m.get("locked"))

    def test_locked_meta_when_no_passphrase(self):
        nmem.set_cipher("s3cret")
        nmem.save_memory(self.ws, [{"role": "user", "content": "a"}], [])
        nmem.set_cipher(None)                # next run without passphrase
        h, t, m = nmem.load_memory(self.ws)
        self.assertEqual((h, t), ([], []))
        self.assertTrue(m.get("locked"))

    def test_locked_meta_wrong_passphrase(self):
        nmem.set_cipher("right")
        nmem.save_memory(self.ws, [{"role": "user", "content": "a"}], [])
        nmem.set_cipher("wrong")
        h, t, m = nmem.load_memory(self.ws)
        self.assertTrue(m.get("locked"))

    def test_clear_removes_both(self):
        nmem.set_cipher("pp")
        nmem.save_memory(self.ws, [{"role": "user", "content": "a"}], [])
        self.assertEqual(nmem.clear_memory(self.ws), "")
        self.assertFalse(nmem.has_memory(self.ws))


class TestRlimits(unittest.TestCase):
    def test_parse_size(self):
        self.assertEqual(rlimits.parse_size("2g"), 2048)
        self.assertEqual(rlimits.parse_size("512m"), 512)
        self.assertEqual(rlimits.parse_size("512000k"), 500)
        self.assertEqual(rlimits.parse_size("100"), 100)
        self.assertEqual(rlimits.parse_size("junk"), 0)
        self.assertEqual(rlimits.parse_size(""), 0)

    def test_env_limits(self):
        with mock.patch.dict(os.environ,
                             {"NOVA_CPU_LIMIT": "30", "NOVA_RAM_LIMIT": "256m"}):
            lim = rlimits.env_limits()
        self.assertEqual(lim, {"cpu_s": 30, "ram_mb": 256})

    def test_popen_kwargs_posix_shape(self):
        if os.name == "nt":
            self.skipTest("posix preexec")
        kw, job = rlimits.popen_kwargs(2, 64)
        self.assertTrue(kw.get("preexec_fn"))
        self.assertIsNone(job)
        kw2, _ = rlimits.popen_kwargs(0, 0)
        self.assertEqual(kw2, {})

    def test_child_killed_by_ram_limit(self):
        if os.name == "nt":
            self.skipTest("posix rlimit")
        kw, _ = rlimits.popen_kwargs(0, 48)
        p = subprocess.run(
            [sys.executable, "-c", "b = bytearray(300*1024*1024)"],
            capture_output=True, timeout=30, **kw)
        self.assertNotEqual(p.returncode, 0,
                            "the 300MB allocation must hit the 48MB ceiling")


class TestSandbox(unittest.TestCase):
    def _cfg(self, **over):
        cfg = dict(sandbox.DEFAULTS)
        cfg.update(over)
        return cfg

    def test_wrap_docker(self):
        engines = {"docker": "/usr/bin/docker"}
        cfg = self._cfg(engine="docker", image="py:3.11", mem="1g", cpus="1")
        eng, argv = sandbox.wrap("/ws", ["python", "x.py"], cfg, engines)
        self.assertEqual(eng, "docker")
        self.assertEqual(argv[0], "/usr/bin/docker")
        self.assertIn("--network", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertIn("py:3.11", argv)
        self.assertEqual(argv[-2:], ["python", "x.py"])

    def test_wrap_bwrap_ro_root(self):
        engines = {"bwrap": "/usr/bin/bwrap"}
        cfg = self._cfg(engine="bwrap")
        eng, argv = sandbox.wrap("/ws", ["ls"], cfg, engines)
        self.assertEqual(eng, "bwrap")
        self.assertIn("--unshare-net", argv)
        self.assertIn("--ro-bind", argv)

    def test_wrap_firejail(self):
        engines = {"firejail": "/usr/bin/firejail"}
        eng, argv = sandbox.wrap("/ws", ["ls"], self._cfg(), engines)
        self.assertEqual(eng, "firejail")
        self.assertIn("--net=none", argv)

    def test_no_engine_reason(self):
        eng, why = sandbox.wrap("/ws", ["ls"], self._cfg(), {})
        self.assertIsNone(eng)
        self.assertIn("no container runtime", why)

    def test_rejects_shell_string(self):
        eng, _why = sandbox.wrap("/ws", "rm -rf /", self._cfg(),
                                 {"docker": "/bin/docker"})
        self.assertIsNone(eng)

    def test_config_roundtrip(self):
        ws = _mkws()
        try:
            self.assertEqual(sandbox.save_config(ws, {"on": True, "engine": "docker"}), "")
            cfg = sandbox.load_config(ws)
            self.assertTrue(cfg["on"])
            self.assertEqual(cfg["engine"], "docker")
            self.assertEqual(cfg["image"], sandbox.DEFAULTS["image"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_status_line_without_engine(self):
        line = sandbox.status_line(_mkws(), sandbox.DEFAULTS, {})
        self.assertIn("NO container runtime", line)


# =====================================================================
class TestAstMap(unittest.TestCase):
    def test_py_symbols_kinds_and_sigs(self):
        code = ('import os\n\n\n'
                'def greet(name: str = "world") -> str:\n'
                '    """Say hi."""\n'
                '    return f"hi {name}"\n\n\n'
                'class Engine:\n'
                '    def run(self, x):\n        return x\n\n\n'
                'VERSION = "1.0"\n')
        syms = astmap.py_symbols(code)
        names = [(s["kind"], s["name"]) for s in syms]
        self.assertIn(("function", "greet"), names)
        self.assertIn(("class", "Engine"), names)
        self.assertIn(("method", "run"), names)
        self.assertIn(("variable", "VERSION"), names)
        greet = next(s for s in syms if s["name"] == "greet")
        # ast.unparse renders strings with single quotes
        self.assertIn("name: str='world'", greet["sig"])
        self.assertIn("-> str", greet["sig"])
        self.assertEqual(greet["doc"], "Say hi.")
        self.assertTrue(all(s["line"] > 0 for s in syms))

    def test_syntax_error_returns_empty(self):
        self.assertEqual(astmap.py_symbols("def broken(:\n"), [])

    def test_js_symbols(self):
        code = ("class App {}\n"
                "function handler(a, b) {}\n"
                "const fn = async (x) => {}\n")
        syms = astmap.js_symbols(code)
        names = {s["name"] for s in syms}
        self.assertEqual(names, {"App", "handler", "fn"})

    def test_symbols_for_dispatch(self):
        self.assertEqual(astmap.symbols_for("a.py", "X = 1")[0]["kind"],
                         "variable")
        self.assertEqual(astmap.symbols_for("a.txt", "hello"), [])

    def test_change_summary(self):
        old = "def f():\n    pass\n"
        new = "def f(x):\n    pass\n\ndef g():\n    pass\n"
        added, removed, changed = astmap.symbol_change(old, new)
        self.assertEqual(added, ["g"])
        self.assertEqual(changed, ["f"])
        summary = astmap.change_summary(old, new)
        self.assertIn("f", summary)
        self.assertIn("g", summary)


class TestDepGraph(unittest.TestCase):
    def test_build_edges_and_cycles(self):
        ws = _mkws()
        try:
            (ws / "a.py").write_text("from b import y\n", encoding="utf-8")
            (ws / "b.py").write_text("from c import z\n", encoding="utf-8")
            (ws / "c.py").write_text("from a import x\n", encoding="utf-8")
            (ws / "solo.py").write_text("import os\n", encoding="utf-8")
            g = depgraph.build(ws)
            self.assertIn(["a.py", "b.py"], g["edges"])
            self.assertIn(["b.py", "c.py"], g["edges"])
            self.assertEqual(len(g["cycles"]), 1)
            self.assertEqual(set(g["cycles"][0]), {"a.py", "b.py", "c.py"})
            self.assertIn("solo.py", depgraph.orphans(g))
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_js_relative_imports(self):
        ws = _mkws()
        try:
            (ws / "main.js").write_text(
                "const util = require('./util.js');\n", encoding="utf-8")
            (ws / "util.js").write_text("module.exports = 1;\n", encoding="utf-8")
            g = depgraph.build(ws)
            self.assertIn(["main.js", "util.js"], g["edges"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_mermaid_and_dot_output(self):
        g = {"nodes": {"a/b.py": {"kind": "py"}},
             "edges": [["a/b.py", "a/b.py"]], "missing": [], "cycles": []}
        m = depgraph.to_mermaid(g)
        self.assertTrue(m.startswith("graph TD"))
        self.assertIn("a_b_py", m)
        d = depgraph.to_dot(g)
        self.assertTrue(d.startswith("digraph"))
        self.assertIn("a_b_py", d)

    def test_node_modules_skipped(self):
        ws = _mkws()
        try:
            nm = ws / "node_modules" / "lib"
            nm.mkdir(parents=True)
            (nm / "index.js").write_text("require('./x')\n", encoding="utf-8")
            g = depgraph.build(ws)
            self.assertEqual(g["nodes"], {})
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestSubAgent(unittest.TestCase):
    def test_parse_task_list(self):
        self.assertEqual(subagent.parse_task_list('["a","b"]'), ["a", "b"])
        self.assertEqual(
            subagent.parse_task_list('Sure!\n```json\n["x", 5, "y"]\n```'),
            ["x", "y"])
        self.assertEqual(subagent.parse_task_list("no json here"), [])
        self.assertEqual(len(subagent.parse_task_list(
            json.dumps(["t"] * 50))), subagent.MAX_TASKS)

    def test_run_parallel_order_and_errors(self):
        def worker(t):
            if t == "boom":
                raise RuntimeError("kaputt")
            return t.upper()
        res = subagent.run_parallel(["a", "boom", "c"], worker, 3)
        self.assertEqual([r[0] for r in res], ["a", "boom", "c"])
        self.assertEqual(res[0][1], "A")
        self.assertIsNone(res[0][2])
        self.assertIn("kaputt", res[1][2])
        self.assertEqual(res[2][1], "C")

    def test_run_parallel_empty(self):
        self.assertEqual(subagent.run_parallel([], lambda t: t), [])

    def test_split_tasks_uses_chat_fn(self):
        def chat(prompt, section="utility"):
            self.assertIn("GOAL:", prompt)
            return '["task one", "task two"]'
        self.assertEqual(subagent.split_tasks("build it", chat),
                         ["task one", "task two"])

    def test_merge_report_contains_results(self):
        out = subagent.merge_report(
            "goal", [("t1", "res one", None), ("t2", None, "dead")],
            lambda p, s="utility": p)
        self.assertIn("res one", out)
        self.assertIn("dead", out)
        self.assertIn("goal", out)


# =====================================================================
class TestBench(unittest.TestCase):
    def _fake_fetch(self, text="=== FILE: hello.py ===\nprint('hi')\n=== END ===",
                    wall=2.0, tok=60):
        return lambda m, p, pred: (text, wall, tok)

    def test_bench_model_protocol(self):
        row = bench.bench_model("m1", fetch=self._fake_fetch())
        self.assertEqual(row["protocol"], 1)
        self.assertEqual(row["tps"], 30.0)
        self.assertEqual(set(row["cases"]), {"chat", "code", "protocol"})

    def test_bench_model_error_case(self):
        def bad(m, p, pred):
            raise OSError("down")
        row = bench.bench_model("m2", fetch=bad)
        self.assertTrue(row["cases"]["chat"]["error"])
        self.assertEqual(row["protocol"], 0)

    def test_record_and_best_for(self):
        ws = _mkws()
        try:
            bench.record(ws, bench.bench_model("good", fetch=self._fake_fetch()))
            bench.record(ws, bench.bench_model(
                "bad", fetch=self._fake_fetch(text="no protocol here")))
            best, row = bench.best_for(ws, "coding")
            self.assertEqual(best, "good")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_score_proto_dominates_for_coding(self):
        fast_sloppy = {"model": "a", "tps": 200, "protocol": 0, "wall": 1,
                       "cases": {}}
        slow_exact = {"model": "b", "tps": 5, "protocol": 1, "wall": 9,
                      "cases": {}}
        self.assertGreater(bench.score_row(slow_exact, "coding"),
                           bench.score_row(fast_sloppy, "coding"))

    def test_table(self):
        rows = [{"model": "m", "tps": 12.3, "protocol": 1, "wall": 4.0,
                 "cases": {}}]
        self.assertIn("12.3", bench.table(rows))


class TestQuality(unittest.TestCase):
    def test_preapply_python(self):
        ok, _ = quality.preapply_check("a.py", "def f():\n    return 1\n")
        self.assertTrue(ok)
        ok, prob = quality.preapply_check("a.py", "def f(:\n")
        self.assertFalse(ok)
        self.assertIn("syntax error", prob)

    def test_preapply_json(self):
        ok, prob = quality.preapply_check("cfg.json", '{"a": 1}')
        self.assertTrue(ok)
        ok, prob = quality.preapply_check("cfg.json", "{broken")
        self.assertFalse(ok)
        self.assertIn("JSON", prob)

    def test_preapply_html_unbalanced(self):
        ok, prob = quality.preapply_check(
            "p.html", "<html><body><script>var a=1;</body></html>")
        self.assertFalse(ok)
        self.assertIn("script", prob)

    def test_preapply_empty_ok(self):
        self.assertTrue(quality.preapply_check("a.py", "   \n")[0])

    def test_generate_docs(self):
        ws = _mkws()
        try:
            (ws / "app.py").write_text(
                '"""Module doc."""\n'
                'def tool(x):\n    """Does a thing."""\n    return x\n',
                encoding="utf-8")
            name, err = quality.generate_docs(ws)
            self.assertEqual(err, "")
            text = (ws / name).read_text(encoding="utf-8")
            self.assertIn("Module doc.", text)
            self.assertIn("def tool(x)", text)
            self.assertIn("Does a thing.", text)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_run_coverage_no_tests(self):
        ws = _mkws()
        try:
            res = quality.run_coverage(ws, cmd=None)
            self.assertEqual(res["mode"], "none")
            self.assertFalse(res["ok"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_run_coverage_runs_plain_cmd(self):
        ws = _mkws()
        try:
            (ws / "t.py").write_text("print('hello-tests')\n", encoding="utf-8")
            res = quality.run_coverage(ws, cmd=[sys.executable, "t.py"])
            self.assertIn(res["mode"], ("tests-only", "coverage"))
            self.assertTrue(res["ok"])
            self.assertIn("hello-tests", res["report"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestPatch(unittest.TestCase):
    def test_parse_and_apply_single(self):
        old = "line1\nline2\nline3\n"
        patch = "\n".join(diffview.unified_diff(
            "f.txt", old, "line1\nTWO\nline3\n"))
        files, probs = diffview.parse_patch(patch)
        self.assertEqual(probs, [])
        self.assertIn("f.txt", files)
        new, applied, problems = diffview.apply_patch(old, files["f.txt"])
        self.assertEqual(problems, [])
        self.assertEqual(new, "line1\nTWO\nline3\n")

    def test_multi_hunk_bottom_up(self):
        old = "a\nb\nc\nd\ne\nf\ng\n"
        new = "a\nB\nc\nd\ne\nF\ng\n"
        files, _ = diffview.parse_patch(
            "\n".join(diffview.unified_diff("m.txt", old, new)))
        out, applied, problems = diffview.apply_patch(old, files["m.txt"])
        self.assertEqual(out, new)
        self.assertEqual(applied, len(files["m.txt"]))

    def test_fuzzy_trailing_ws(self):
        old = "x = 1  \ny = 2\n"
        hunks = [(1, ["x = 1", "y = 2"], 1, ["x = 1  # one", "y = 2"])]
        out, applied, problems = diffview.apply_patch(old, hunks)
        self.assertEqual(applied, 1)
        self.assertEqual(out, "x = 1  # one\ny = 2\n")

    def test_missing_context_reported(self):
        hunks = [(9, ["nope"], 9, ["never"])]
        out, applied, problems = diffview.apply_patch("abc\n", hunks)
        self.assertEqual(applied, 0)
        self.assertEqual(problems[0][0], 1)

    def test_parse_ignores_prelude(self):
        patch = ("commit abc123\n"
                 "diff --git a/x.py b/x.py\n"
                 "--- a/x.py\n+++ b/x.py\n"
                 "@@ -1,1 +1,2 @@\n"
                 " old\n+new\n")
        files, probs = diffview.parse_patch(patch)
        self.assertEqual(probs, [])
        self.assertEqual(files["x.py"][0][1], ["old"])


# =====================================================================
class TestAtomicTxAndLint(unittest.TestCase):
    def setUp(self):
        self.ws = _mkws()
        self.sess = _bare_session(self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_lint_rejects_bad_python_nothing_written(self):
        f1 = self.ws / "good.py"
        f1.write_text("OLD = 1\n", encoding="utf-8")
        applied = nova.offer_apply(
            self.sess,
            [("good.py", "GOOD = 2\n"), ("bad.py", "def (:\n")],
            [], auto=True)
        self.assertEqual(applied, [])
        self.assertEqual(f1.read_text(encoding="utf-8"), "OLD = 1\n")
        self.assertFalse((self.ws / "bad.py").exists())
        self.assertEqual(self.sess.last_feedback["syntax"][0][0], "bad.py")

    def test_atomic_rollback_on_write_failure(self):
        (self.ws / "a_file.py").write_text("A=1\n", encoding="utf-8")
        # a DIRECTORY where the 3rd file should be -> open() fails mid-batch
        blocker = self.ws / "sub"
        blocker.mkdir()
        plans = [("a_file.py", "A=2\n", self.ws / "a_file.py"),
                 ("new_file.py", "B=3\n", self.ws / "new_file.py"),
                 ("sub", "C=4\n", blocker)]
        with mock.patch.object(nova, "safe_join",
                               side_effect=lambda ws, p: ws / p):
            applied = nova.offer_apply(self.sess, [], [], edits=None,
                                       auto=True) if False else None
        # call offer_apply with prebuilt plans via monkeypatched internals:
        # simpler path - run offer_apply with a target that is a directory
        # by passing it through files (safe_join here returns ws/p directly)
        with mock.patch.object(nova, "safe_join",
                               side_effect=lambda ws, p: ws / p):
            applied = nova.offer_apply(
                self.sess,
                [("a_file.py", "A=2\n"), ("new_file.py", "B=3\n"),
                 ("sub", "C=4\n")],
                [], auto=True)
        self.assertEqual(applied, [])
        self.assertEqual((self.ws / "a_file.py").read_text(encoding="utf-8"),
                         "A=1\n", "rolled back to the pre-apply content")
        self.assertFalse((self.ws / "new_file.py").exists(),
                         "the rolled-back new file must be gone")
        self.assertEqual(self.sess.last_batch, [])
        self.assertEqual(self.sess.touched, {})

    def test_successful_batch_unchanged_semantics(self):
        applied = nova.offer_apply(
            self.sess,
            [("x.py", "print('ok')\n"), ("s/app/y.py", "print('deep')\n")],
            [], auto=True)
        self.assertEqual(applied, ["x.py", "s/app/y.py"])
        self.assertTrue((self.ws / "x.py").is_file())
        self.assertTrue((self.ws / "s/app/y.py").is_file())
        self.assertEqual(len(self.sess.last_batch), 0)   # both were new


@unittest.skipUnless(shutil.which("git"), "git required")
class TestGitCommitPerFile(unittest.TestCase):
    def setUp(self):
        self.ws = _mkws()
        subprocess.run(["git", "init", "-q"], cwd=str(self.ws), check=True)
        subprocess.run(["git", "config", "user.email", "t@t"],
                       cwd=str(self.ws), check=True)
        subprocess.run(["git", "config", "user.name", "t"],
                       cwd=str(self.ws), check=True)
        (self.ws / "a.py").write_text("A = 1\n", encoding="utf-8")
        (self.ws / "b.py").write_text("B = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.ws), check=True)
        subprocess.run(["git", "commit", "-qm", "init"],
                       cwd=str(self.ws), check=True)
        self.sess = _bare_session(self.ws)
        self.sess.touched = {"a.py": "modified", "b.py": "modified"}

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_two_files_two_commits(self):
        (self.ws / "a.py").write_text("A = 2\n", encoding="utf-8")
        (self.ws / "b.py").write_text("B = 2\n", encoding="utf-8")
        self.sess.last_batch = []
        nova._git_autocommit(self.sess, ["a.py", "b.py"])
        log = subprocess.run(
            ["git", "log", "--format=%s"], cwd=str(self.ws),
            capture_output=True, text=True).stdout.splitlines()
        # init + one commit per applied file (newest = last applied)
        self.assertGreaterEqual(len(log), 3)
        self.assertIn("b.py", log[0])
        self.assertIn("a.py", log[1])

    def test_ast_detail_in_message(self):
        # rewrite a.py with a changed function -> the message names it
        (self.ws / "a.py").write_text("def calc(x):\n    return x\n",
                                      encoding="utf-8")
        old = "A = 1\n"
        self.sess.last_batch = [(self.ws / "a.py",
                                 self.ws / ".nova_backups" / "old.py")]
        bk = self.sess.last_batch[0][1]
        bk.parent.mkdir(exist_ok=True)
        bk.write_text(old, encoding="utf-8")
        nova._git_autocommit(self.sess, ["a.py"])
        log = subprocess.run(["git", "log", "--format=%s", "-1"],
                             cwd=str(self.ws), capture_output=True,
                             text=True).stdout
        self.assertIn("calc", log)


# =====================================================================
class TestDoctorTimelineCommands(unittest.TestCase):
    def setUp(self):
        self.ws = _mkws()
        self.sess = _bare_session(self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_run_doctor_report_and_persist(self):
        rep = nova.run_doctor(self.ws)
        ids = [c["id"] for c in rep["checks"]]
        for want in ("python", "workspace", "ollama", "hardware", "encryption"):
            self.assertIn(want, ids)
        self.assertTrue((self.ws / ".nova" / "doctor.json").is_file())

    def test_cmd_doctor_prints(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_doctor(self.sess, "")
        out = buf.getvalue()
        self.assertIn("Nova setup doctor", out)
        self.assertIn("checks passed", out)

    def test_cmd_timeline_empty_then_units(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_timeline(self.sess, "")
        self.assertIn("Timeline is empty", buf.getvalue())
        # push one unit
        f = self.ws / "u.py"
        f.write_text("X=1\n", encoding="utf-8")
        nova.snaps.push_auto_unit(self.ws, [(f, None)], note="test note")
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_timeline(self.sess, "")
        self.assertIn("test note", buf.getvalue())
        uid = nova.snaps.list_units(self.ws)[-1]["id"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_timeline(self.sess, f"show {uid}")
        self.assertIn("u.py", buf.getvalue())


class TestGraphCommands(unittest.TestCase):
    def setUp(self):
        self.ws = _mkws()
        (self.ws / "m1.py").write_text("import m2\n", encoding="utf-8")
        (self.ws / "m2.py").write_text("V = 1\n", encoding="utf-8")
        self.sess = _bare_session(self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_cmd_graph_report_and_mermaid(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_graph(self.sess, "--mermaid deps.md")
        out = buf.getvalue()
        self.assertIn("files: 2", out)
        self.assertIn("m1.py", out)
        self.assertTrue((self.ws / "deps.md").is_file())
        self.assertIn("graph TD",
                      (self.ws / "deps.md").read_text(encoding="utf-8"))

    def test_cmd_symbols(self):
        (self.ws / "m2.py").write_text("class K:\n    def go(self):\n        pass\n",
                                       encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_symbols(self.sess, "m2.py")
        self.assertIn("class K", buf.getvalue())
        self.assertIn("def go(self)", buf.getvalue())


class TestHardware(unittest.TestCase):
    def test_detect_fields(self):
        hw = hardware.detect()
        self.assertIn("ram_gb", hw)
        self.assertIn("cores", hw)
        self.assertIsInstance(hw["gpus"], list)
        self.assertIn(hw["os"], ("Linux", "Windows", "Darwin"))

    def test_suggest_tiers(self):
        low = {"ram_gb": 4, "gpus": []}
        high = {"ram_gb": 64, "gpus": [{"name": "RTX", "vram_gb": 24}]}
        self.assertIn("0.5B", hardware.suggest(low)["params"])
        self.assertGreater(hardware.suggest(high)["num_ctx"],
                           hardware.suggest(low)["num_ctx"])

    def test_speculative_honest_when_no_server(self):
        spec = hardware.speculative({"ram_gb": 8}, server_exe=None)
        self.assertFalse(spec["supported"])
        self.assertIn("Ollama", spec["note"])

    def test_speculative_recipe_with_server(self):
        spec = hardware.speculative({"ram_gb": 8}, server_exe="/x/llama-server",
                                    draft_model="d.gguf")
        self.assertTrue(spec["supported"])
        self.assertIn("d.gguf", spec["recipe"])

    def test_report_lines(self):
        text = hardware.report({"ram_gb": 8, "cores": 4, "gpus": [],
                                "os": "Linux", "machine": "x86"},
                               hardware.suggest())
        self.assertIn("RAM", text)


class TestKnowledgeDenseVectors(unittest.TestCase):
    def setUp(self):
        from nova_modules import knowledge
        self.knowledge = knowledge
        self.ws = _mkws()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def _ingest(self):
        (self.ws / "doc.md").write_text(
            "Nova supports hot reloading of the config file. "
            "کلید رمزنگاری فایل‌ها ذخیره می‌شود. " * 4,
            encoding="utf-8")
        return self.knowledge.ingest(self.ws, ["doc.md"])

    def test_hybrid_search_and_vector_store(self):
        res = self._ingest()
        self.assertEqual(res["files"], 1)
        hits = self.knowledge.search(self.ws, "hot reloading config", k=3)
        self.assertTrue(hits)
        self.assertIn("reloading", hits[0]["text"])
        # dense store now exists (sqlite) and is populated
        vdb = self.ws / ".nova" / "knowledge" / "vectors.db"
        self.assertTrue(vdb.is_file())
        import sqlite3
        conn = sqlite3.connect(str(vdb))
        try:
            n = conn.execute("SELECT COUNT(*) FROM vec").fetchone()[0]
        finally:
            conn.close()
        self.assertGreater(n, 0)

    def test_typo_tolerance_via_char_ngrams(self):
        self._ingest()
        hits = self.knowledge.search(self.ws, "reloadingg configg", k=3)
        self.assertTrue(hits, "char-3gram dense layer should catch typos")

    def test_reset_removes_vectors(self):
        self._ingest()
        self.knowledge.reset(self.ws)
        self.assertFalse(
            (self.ws / ".nova" / "knowledge" / "vectors.db").exists())

    def test_embedding_deterministic_and_normalized(self):
        v1 = self.knowledge._embed_hash("hello world of code")
        v2 = self.knowledge._embed_hash("hello world of code")
        self.assertEqual(v1, v2)
        norm = sum(x * x for x in v1) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)


class TestRepomapAstUpgrade(unittest.TestCase):
    def test_ast_signatures_with_defaults(self):
        import nova_repomap as rm
        code = ('def f(a, b=2):\n    pass\n\n\n'
                'class C:\n    def m(self):\n        pass\n')
        sigs = rm.file_signatures("x.py", code)
        joined = "; ".join(sigs)
        self.assertIn("def f(a, b=2)", joined)
        self.assertIn("class C", joined)
        # methods stay out of the MAP (budget) - they live in /symbols
        self.assertNotIn("def m(", joined)


class TestVersion(unittest.TestCase):
    def test_version_pinned(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
