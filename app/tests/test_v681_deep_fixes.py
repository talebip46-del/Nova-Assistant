#!/usr/bin/env python3
"""v6.8.1 regression tests - the deep-audit fixes: tx rollback of the
FAILING file itself, web-approval lint gate, secretbox (passphrase,salt)
cache, pure-addition / '-- ' / overlapping unified-diff hunks, hostile
env values (inf / NOVA_AGENTS=abc), relative-name imports, repomap
symbol priority, EncodedCommand screening, bg finished-timestamps,
stream locks, memory at-rest across workspaces."""
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
import nova_bg as nova_bg
import nova_diffview as diffview
import nova_depgraph as depgraph
import nova_rlimits as rlimits
import nova_secretbox as secretbox
import nova_security as nsec
import nova_subagent as subagent


def _mkws():
    return Path(tempfile.mkdtemp(prefix="nova_v681_"))


def _bare_session(ws):
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
class TestTxRollbackOfFailingFile(unittest.TestCase):
    """HIGH fix: open(target,'w') truncates BEFORE the write - the file
    whose write dies mid-way must be restored / removed too."""

    def setUp(self):
        self.ws = _mkws()
        self.sess = _bare_session(self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_overwrite_file_restored_when_later_batch_item_fails(self):
        f = self.ws / "first.py"
        f.write_text("X = 1\n", encoding="utf-8")
        # lone surrogate = UnicodeEncodeError (a ValueError) raised WHILE
        # writing - exactly the mid-write failure the old journal missed
        applied = nova.offer_apply(
            self.sess,
            [("first.py", "X = 2\n"), ("second.py", "bad \ud800 surrogate\n")],
            [], auto=True)
        self.assertEqual(applied, [])
        self.assertEqual(f.read_text(encoding="utf-8"), "X = 1\n",
                         "the truncated file must be back to its old content")
        self.assertFalse((self.ws / "second.py").exists())

    def test_new_partial_file_removed(self):
        applied = nova.offer_apply(
            self.sess,
            [("first.py", "ok \ud800\n")], [], auto=True)
        self.assertEqual(applied, [])
        leftovers = [p for p in self.ws.rglob("*")
                     if p.is_file() and ".nova_backups" not in p.parts]
        self.assertEqual(leftovers, [], "no partial stray file may survive")


class TestWebApprovalLintGate(unittest.TestCase):
    def test_apply_approved_rejects_broken_python(self):
        ws = _mkws()
        sess = _bare_session(ws)
        broken = ws / "broken.py"
        sess.pending_apply = {
            "id": "p1", "ts": nova.time.time(),
            "plans": [("broken.py", "def (:\n", ws / "broken.py")],
            "hunks": {}}
        try:
            ok, result = nova.apply_approved(sess, "p1", ["broken.py"], {})
            self.assertFalse(ok)
            self.assertIn("pre-apply check failed", result["error"])
            self.assertFalse(broken.exists())
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_apply_approved_allows_valid_python(self):
        ws = _mkws()
        sess = _bare_session(ws)
        sess.pending_apply = {
            "id": "p1", "ts": nova.time.time(),
            "plans": [("ok.py", "A = 1\n", ws / "ok.py")],
            "hunks": {}}
        try:
            ok, result = nova.apply_approved(sess, "p1", ["ok.py"], {})
            self.assertTrue(ok, result)
            self.assertEqual((ws / "ok.py").read_text(encoding="utf-8"),
                             "A = 1\n")
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestSecretBoxCache(unittest.TestCase):
    def test_cache_respects_salt(self):
        k1 = secretbox.cached_key("pw", b"salt-one")
        k2 = secretbox.cached_key("pw", b"salt-two")
        self.assertNotEqual(k1, k2,
                            "same passphrase + different salt MUST give "
                            "different keys (cross-workspace sealing)")
        k3 = secretbox.cached_key("pw", b"salt-one")
        self.assertEqual(k1, k3, "the cache itself must still hit")


class TestMemoryAcrossWorkspaces(unittest.TestCase):
    def setUp(self):
        self.ws1 = _mkws()
        self.ws2 = _mkws()
        nova.nmem.set_cipher(None)

    def tearDown(self):
        nova.nmem.set_cipher(None)
        for ws in (self.ws1, self.ws2):
            shutil.rmtree(ws, ignore_errors=True)

    def test_same_passphrase_two_workspaces_roundtrip(self):
        import nova_memory as nmem
        nmem.set_cipher("pw")
        nmem.save_memory(self.ws1, [{"role": "user", "content": "one"}], [])
        nmem.save_memory(self.ws2, [{"role": "user", "content": "two"}], [])
        h1, _t, _m = nmem.load_memory(self.ws1)
        h2, _t, _m = nmem.load_memory(self.ws2)
        self.assertEqual(h1[0]["content"], "one")
        self.assertEqual(h2[0]["content"], "two")


# =====================================================================
class TestDiffviewHardening(unittest.TestCase):
    def test_pure_addition_hunk_applies(self):
        out, applied, problems = diffview.apply_patch(
            "a\nb\nc\n", [(3, [], 4, ["tail"])])
        self.assertEqual(problems, [])
        self.assertEqual(applied, 1)
        self.assertEqual(out, "a\nb\nc\ntail\n")

    def test_new_file_zero_start_hunk(self):
        out, applied, problems = diffview.apply_patch(
            "", [(0, [], 1, ["hello", "world"])])
        self.assertEqual(problems, [])
        self.assertEqual(out, "hello\nworld")

    def test_deleted_dash_dash_line_not_a_header(self):
        patch = ("--- a/x.sql\n+++ b/x.sql\n"
                 "@@ -1,2 +1,2 @@\n"
                 " intro\n--- sql comment\n+-- new comment\n")
        files, problems = diffview.parse_patch(patch)
        self.assertEqual(problems, [])
        old, new = files["x.sql"][0][1], files["x.sql"][0][3]
        self.assertEqual(old, ["intro", "-- sql comment"])
        self.assertEqual(new, ["intro", "-- new comment"])
        out, applied, problems = diffview.apply_patch(
            "intro\n-- sql comment\n", files["x.sql"])
        self.assertEqual(problems, [])
        self.assertEqual(out, "intro\n-- new comment\n")

    def test_overlapping_hunks_rejected(self):
        hunks = [(1, ["a", "b"], 1, ["X"]), (2, ["b", "c"], 2, ["Y"])]
        out, applied, problems = diffview.apply_patch("a\nb\nc\n", hunks)
        self.assertEqual(applied, 1)
        self.assertEqual(len(problems), 1)
        self.assertIn("overlap", problems[0][1])

    def test_multi_hunk_regression(self):
        old = "a\nb\nc\nd\ne\nf\ng\n"
        new = "a\nB\nc\nd\ne\nF\ng\n"
        files, _ = diffview.parse_patch(
            "\n".join(diffview.unified_diff("m.txt", old, new)))
        out, applied, problems = diffview.apply_patch(old, files["m.txt"])
        self.assertEqual(out, new)
        self.assertEqual(problems, [])


# =====================================================================
class TestHostileEnv(unittest.TestCase):
    def test_parse_size_inf(self):
        self.assertEqual(rlimits.parse_size("inf"), 0)
        self.assertEqual(rlimits.parse_size("1e999"), 0)
        self.assertEqual(rlimits.parse_size("2g"), 2048)

    def test_env_limits_inf_no_crash(self):
        with mock.patch.dict(os.environ,
                             {"NOVA_CPU_LIMIT": "inf",
                              "NOVA_RAM_LIMIT": "1e999"}):
            lim = rlimits.env_limits()
        self.assertEqual(lim, {"cpu_s": 0, "ram_mb": 0})

    def test_nova_agents_junk_no_crash(self):
        with mock.patch.dict(os.environ, {"NOVA_AGENTS": "abc"}):
            res = subagent.run_parallel(["t"], lambda t: t.upper())
        self.assertEqual(res, [("t", "T", None)])

    def test_parse_task_list_with_brackets_in_prose(self):
        self.assertEqual(
            subagent.parse_task_list(
                'Note [see below] then: ["task one","task two"] end'),
            ["task one", "task two"])


class TestDepgraphRelativeNames(unittest.TestCase):
    def test_from_dot_import_resolves(self):
        ws = _mkws()
        try:
            pkg = ws / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("X = 1\n", encoding="utf-8")
            (pkg / "mod.py").write_text("from . import __init__\n",
                                        encoding="utf-8")
            (pkg / "other.py").write_text("from . import helper\n",
                                          encoding="utf-8")
            (pkg / "helper.py").write_text("H = 1\n", encoding="utf-8")
            g = depgraph.build(ws)
            self.assertIn(["pkg/other.py", "pkg/helper.py"], g["edges"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestRepomapPriority(unittest.TestCase):
    def test_functions_outrank_constants(self):
        import nova_repomap as rm
        code = "\n".join(f"C{i} = {i}" for i in range(10)) + \
            "\n\ndef important_fn():\n    pass\n\n\nclass C:\n    pass\n"
        sigs = rm.file_signatures("x.py", code)
        joined = "; ".join(sigs)
        self.assertIn("important_fn", joined)
        self.assertIn("class C", joined)


class TestEncodedCommandScreening(unittest.TestCase):
    def test_all_spellings_denied(self):
        for flag in ("-EncodedCommand", "-enc", "-e", "-ec"):
            scr = nsec.screen(f"powershell {flag} cGluZw==")
            self.assertEqual(scr["verdict"], "deny", flag)

    def test_plain_powershell_not_flagged_as_encoded(self):
        scr = nsec.screen("powershell -Command Get-Process")
        joined = "; ".join(scr["reasons"]).lower()
        self.assertNotIn("encoded", joined)


@unittest.skipUnless(shutil.which("git"), "git required")
class TestBgFinishedTimestamps(unittest.TestCase):
    def test_newly_finished_uses_finished_field(self):
        ws = _mkws()
        try:
            nova_bg.bg_dir(ws).mkdir(parents=True, exist_ok=True)
            old_start = int(nova_bg.time.time()) - 9999
            meta = {"id": "b0001", "cmd": "x", "started": old_start,
                    "finished": int(nova_bg.time.time()) - 5,
                    "status": "finished", "exit": 0, "dur": 1.0}
            (nova_bg._meta_path(ws, "b0001")).write_text(
                json.dumps(meta), encoding="utf-8")
            # a new session's cursor = its own start (now - 0) - the old
            # started-based filter never announced this job
            got = nova_bg.newly_finished(ws, since_ts=int(nova_bg.time.time()) - 60)
            self.assertEqual([m["id"] for m in got], ["b0001"])
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_pid_match_rejects_superset_command(self):
        # word-boundary guard: recorded 'sleep 2' must not match a
        # squatter running 'sleep 20' on the recycled pid
        if not hasattr(os, "fork"):
            self.skipTest("posix only")
        p = subprocess.Popen(["sh", "-c", "sleep 20"])
        try:
            self.assertTrue(nova_bg._pid_matches_cmd(p.pid, "sleep 20"))
            self.assertFalse(nova_bg._pid_matches_cmd(p.pid, "sleep 2"))
        finally:
            p.kill()
            p.wait(timeout=10)


class TestStreamLock(unittest.TestCase):
    def test_stream_lock_is_reentrant_and_serializes(self):
        import threading
        self.assertIsInstance(nova._STREAM_LOCK,
                              type(threading.RLock()))
        # RLock semantics (a turn's emit + heartbeat share one thread)
        with nova._STREAM_LOCK:
            with nova._STREAM_LOCK:      # re-entry must not deadlock
                pass
        # cross-thread serialization: threads append strictly inside the
        # lock, so the counter can never race
        counter = {"n": 0}

        def bump():
            for _ in range(200):
                with nova._STREAM_LOCK:
                    v = counter["n"]
                    counter["n"] = v + 1

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(counter["n"], 800)


class TestLimitAndLockArgs(unittest.TestCase):
    def test_limit_cpu_inf_no_crash(self):
        ws = _mkws()
        sess = _bare_session(ws)
        buf = io.StringIO()
        with redirect_stdout(buf):
            nova.cmd_limit(sess, "cpu inf")
        self.assertIn("bad cpu value", buf.getvalue())
        shutil.rmtree(ws, ignore_errors=True)

    def test_lock_no_arg_noninteractive_stays_safe(self):
        ws = _mkws()
        sess = _bare_session(ws)
        nova.NONINTERACTIVE = True
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                nova.cmd_lock(sess, "")
            self.assertIn("memory at rest", buf.getvalue())
        finally:
            nova.NONINTERACTIVE = False
            shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
