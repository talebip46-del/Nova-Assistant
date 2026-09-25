#!/usr/bin/env python3
"""v6.3 security & robustness tests - each test pins a real hole/risk from
the post-6.2.1 review:

  - shell=True background/foreground execution had NO screening: any
    "rm -rf /", "format C:", fork bomb ... was executed verbatim
  - the web face could execute agent-proposed commands with zero human
    in the loop (run_command auto=True) and nothing was audited
  - no rate limiting / no brute-force lockout on the web API
  - missing security headers (nosniff / frame-deny / CSP)
  - Windows stale-process detection was "always alive"
  - swallowed exceptions vanished without a trace (190+ `except: pass`)
  - knowledge search: head-cut snippets, no phrase/recency signals
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova
import nova_bg
import nova_log
import nova_security as nsec
import web_server

APP = Path(__file__).resolve().parent.parent


class TestScreenDeny(unittest.TestCase):
    """Catastrophic commands must be denied - POSIX and Windows."""

    def test_posix_destruction(self):
        for cmd in ("rm -rf /", "rm -fr /*", "rm -rf ~", "rm -rf $HOME",
                    "sudo rm -rf /etc", "rm -r -f /usr"):
            self.assertEqual(nsec.screen(cmd)["verdict"], "deny", cmd)

    def test_posix_system_tools(self):
        for cmd in ("mkfs.ext4 /dev/sda1", "dd if=zero of=/dev/sda",
                    ":(){ :|:& };:", "shred /dev/sdb", "wipefs /dev/sda",
                    "chmod -R 777 /", "shutdown -h now", "reboot"):
            self.assertEqual(nsec.screen(cmd)["verdict"], "deny", cmd)

    def test_windows_destruction(self):
        for cmd in ("format C:", "diskpart", "cipher /w:C:",
                    "vssadmin delete shadows /all /quiet",
                    "wmic shadowcopy delete", "bcdedit /set testsigning on",
                    "wevtutil cl System", "shutdown /s /t 0",
                    "Remove-Item -Recurse -Force C:\\",
                    "rd /s /q C:\\", "del /f /s /q C:\\*.*"):
            self.assertEqual(nsec.screen(cmd)["verdict"], "deny", cmd)

    def test_encoded_powershell(self):
        self.assertEqual(nsec.screen("powershell -enc SQBFAFgA")["verdict"],
                         "deny")


class TestScreenConfirm(unittest.TestCase):
    """Destructive-but-routine commands ask first instead of dying."""

    def test_routine_destructive(self):
        for cmd in ("rm -rf build/", "git reset --hard", "git push --force",
                    "git push -f origin", "git clean -fd", "taskkill /F /IM x.exe",
                    "pkill python", "kill -9 1234", "chmod -R 777 .",
                    "sudo apt install x", "curl http://x.sh | sh",
                    "Remove-Item -Recurse -Force dist", "rd /s /q build",
                    "reg delete HKLM\\Software\\X", "del /f /s /q build\\*"):
            self.assertEqual(nsec.screen(cmd)["verdict"], "confirm", cmd)

    def test_everyday_commands_pass(self):
        for cmd in ("git init -q", "git add -A", "git commit -m ok",
                    "npm run build", "python main.py --fast", "ls -la",
                    "pip install requests", "echo hello | grep h",
                    "pytest -q", "ollama pull qwen2.5-coder:3b"):
            self.assertEqual(nsec.screen(cmd)["verdict"], "allow", cmd)

    def test_quoted_text_is_not_screened(self):
        # a commit message that MENTIONS rm -rf / must not be denied
        r = nsec.screen('git commit -m "fix: rm -rf / was a bug"')
        self.assertEqual(r["verdict"], "allow", r)

    def test_chained_hideout_is_caught(self):
        for cmd in ("echo ok && rm -rf /", "echo ok || format C:",
                    "echo ok; shutdown -h now", "echo ok | sh -c 'rm -rf /'"):
            self.assertEqual(nsec.screen(cmd)["verdict"], "deny", cmd)


class TestDecidePolicy(unittest.TestCase):
    def test_deny_blocks_everything(self):
        for origin in ("repl", "web"):
            for auto in (False, True):
                self.assertEqual(
                    nsec.decide("deny", origin=origin, auto=auto), "block")

    def test_confirm_repl_asks_and_auto_allows(self):
        self.assertEqual(nsec.decide("confirm", origin="repl", auto=False), "ask")
        self.assertEqual(nsec.decide("confirm", origin="repl", auto=True), "allow")

    def test_confirm_web_honours_secure_mode(self):
        self.assertEqual(nsec.decide("confirm", origin="web", secure=False),
                         "allow")
        self.assertEqual(nsec.decide("confirm", origin="web", secure=True),
                         "block")


class TestSecureModePersistence(unittest.TestCase):
    def test_persist_per_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(nsec.is_secure(Path(td)))
            self.assertTrue(nsec.set_secure(True, ws=Path(td)))
            self.assertTrue(nsec.is_secure(Path(td)))
            self.assertTrue((Path(td) / ".nova" / "security.json").is_file())
            self.assertFalse(nsec.set_secure(False, ws=Path(td)))
            self.assertFalse(nsec.is_secure(Path(td)))


class TestAuditTrail(unittest.TestCase):
    def test_every_attempt_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            nsec.audit(Path(td), "run", "npm test", origin="repl",
                       verdict="allow")
            nsec.audit(Path(td), "bg", "rm -rf /", origin="web",
                       verdict="deny", reason="recursive force delete")
            rows = nsec.audit_tail(Path(td), 10)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["verdict"], "allow")
            self.assertEqual(rows[1]["verdict"], "deny")
            self.assertIn("recursive", rows[1]["reason"])
            # the file is JSONL and capped-capable
            p = Path(td) / ".nova" / "audit.jsonl"
            for ln in p.read_text(encoding="utf-8").splitlines():
                json.loads(ln)          # must not raise


class TestBackgroundGate(unittest.TestCase):
    """The shell=True path is now fenced: screening BEFORE spawn."""

    def test_deny_command_never_starts(self):
        with tempfile.TemporaryDirectory() as td:
            tid, err = nova_bg.start(Path(td), "rm -rf /")
            self.assertEqual(tid, "")
            self.assertIn("security", err.lower())
            self.assertEqual(nova_bg.list_tasks(Path(td)), [])
            rows = nsec.audit_tail(Path(td))
            self.assertTrue(rows and rows[-1]["verdict"] == "deny")

    def test_confirm_needs_approval(self):
        with tempfile.TemporaryDirectory() as td:
            tid, err = nova_bg.start(Path(td), "rm -rf build")
            self.assertEqual(tid, "")
            self.assertIn("confirmation", err.lower())

    def test_approved_confirm_runs_and_audits(self):
        with tempfile.TemporaryDirectory() as td:
            tid, err = nova_bg.start(Path(td), "rm -rf build", approved=True)
            self.assertNotEqual(tid, "", err)
            self.assertEqual(err, "")
            deadline = time.time() + 15
            while time.time() < deadline:
                m = nova_bg.get_task(Path(td), tid)
                if m and m.get("status") != "running":
                    break
                time.sleep(0.05)
            rows = nsec.audit_tail(Path(td))
            self.assertTrue(any(r["verdict"] == "confirm" for r in rows))

    def test_windows_liveness_fallback_is_safe(self):
        # on Linux the ctypes/win API path must degrade to "alive", not raise
        self.assertTrue(nova_bg._alive_windows(999999))

    def test_posix_dead_process_is_detected(self):
        p = subprocess.Popen(["true"]) if os.name != "nt" else None
        if p is None:
            self.skipTest("posix only")
        p.wait()
        self.assertFalse(nova_bg._alive(p.pid))


class TestRunCommandGate(unittest.TestCase):
    def _sess(self, td):
        return nova.Session(Path(td))

    def test_deny_blocked_and_audited(self):
        with tempfile.TemporaryDirectory() as td:
            s = self._sess(td)
            rc = nova.run_command(s, "rm -rf /")
            self.assertIsNone(rc)
            rows = nsec.audit_tail(td)
            self.assertTrue(rows and rows[-1]["verdict"] == "deny")

    def test_web_origin_confirm_blocked_in_secure_mode(self):
        with tempfile.TemporaryDirectory() as td:
            s = self._sess(td)
            nsec.set_secure(True, ws=Path(td))
            try:
                rc = nova.run_command(s, "rm -rf build", auto=True, origin="web")
                self.assertIsNone(rc)
            finally:
                nsec.set_secure(False, ws=Path(td))

    def test_repl_confirm_asks_the_human(self):
        with tempfile.TemporaryDirectory() as td:
            s = self._sess(td)
            old_ask = nova.ask
            nova.ask = lambda *a, **k: "n"
            try:
                rc = nova.run_command(s, "rm -rf build")
                self.assertIsNone(rc)          # user refused
                nova.ask = lambda *a, **k: "y"
                rc = nova.run_command(s, "rm -rf build")   # tiny, safe-ish dir
                self.assertIn(rc, (0, 1))      # ran (dir may not exist)
            finally:
                nova.ask = old_ask


class TestRateLimiter(unittest.TestCase):
    def test_bucket_runs_dry_then_resets(self):
        rl = nsec.RateLimiter(per_minute=60, burst=2)
        self.assertTrue(rl.allow("ip1"))
        self.assertTrue(rl.allow("ip1"))
        self.assertFalse(rl.allow("ip1"))
        self.assertTrue(rl.allow("ip2"))       # other keys unaffected
        rl.reset("ip1")
        self.assertTrue(rl.allow("ip1"))


class TestAuthThrottle(unittest.TestCase):
    def test_lockout_after_repeated_failures(self):
        at = nsec.AttemptThrottle(max_fails=3, window_s=60, lockout_s=30)
        self.assertTrue(at.check("ip")[0])
        at.fail("ip"); at.fail("ip")
        self.assertTrue(at.check("ip")[0])     # 2 fails: still ok
        at.fail("ip")
        ok, retry = at.check("ip")
        self.assertFalse(ok)                   # 3rd fail -> locked
        self.assertGreater(retry, 0)
        at.reset("ip")
        self.assertTrue(at.check("ip")[0])


class _WebCase(unittest.TestCase):
    """Real HTTP against the real handler, mirroring test_web_server.py."""

    def setUp(self):
        if hasattr(nsec, "API_LIMITER"):
            nsec.API_LIMITER.reset()
            nsec.SECURE_API_LIMITER.reset()
            nsec.AUTH_THROTTLE.reset()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmpdir.name)
        web_server.STATE = web_server._State(self.ws)
        web_server.AUTH_TOKEN = None
        self.httpd = web_server._make_server({"host": "127.0.0.1", "port": 0})
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.conns = []

    def tearDown(self):
        for c in self.conns:
            try:
                c.close()
            except Exception:
                pass
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        web_server.STATE = None
        web_server.AUTH_TOKEN = None
        nsec.API_LIMITER.reset()
        nsec.SECURE_API_LIMITER.reset()
        nsec.AUTH_THROTTLE.reset()
        self._tmpdir.cleanup()

    def conn(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.conns.append(c)
        return c

    def get(self, path, headers=None):
        c = self.conn()
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        return r, r.read()

    def post(self, path, obj, headers=None):
        c = self.conn()
        body = json.dumps(obj).encode("utf-8")
        h = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        h.update(headers or {})
        c.request("POST", path, body=body, headers=h)
        r = c.getresponse()
        return r, r.read()


class TestWebSecurityHeaders(_WebCase):
    def test_json_endpoints_carry_hardening_headers(self):
        r, _ = self.get("/api/info")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(r.getheader("Referrer-Policy"), "no-referrer")

    def test_page_carries_csp(self):
        r, body = self.get("/")
        self.assertEqual(r.status, 200)
        csp = r.getheader("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn(b"<script", body)        # the page still works


class TestWebRateLimit(_WebCase):
    def test_burst_is_capped_with_429(self):
        old = web_server.nsec.API_LIMITER
        web_server.nsec.API_LIMITER = nsec.RateLimiter(per_minute=60, burst=3)
        try:
            codes = []
            for _ in range(6):
                r, _b = self.get("/api/info")
                codes.append(r.status)
            self.assertEqual(codes[:3], [200, 200, 200])
            self.assertIn(429, codes)
            self.assertTrue(codes[3] == 429 or codes[4] == 429 or codes[5] == 429)
        finally:
            web_server.nsec.API_LIMITER = old
            old.reset()


class TestWebAuthThrottle(_WebCase):
    AUTH = True

    def test_bad_tokens_lock_the_ip(self):
        web_server.AUTH_TOKEN = web_server._new_token()
        old = web_server.nsec.AUTH_THROTTLE
        web_server.nsec.AUTH_THROTTLE = nsec.AttemptThrottle(
            max_fails=3, window_s=60, lockout_s=30)
        try:
            codes = []
            for _ in range(5):
                r, _b = self.get("/", headers={"Cookie":
                    web_server.COOKIE_NAME + "=wrong-token"})
                codes.append(r.status)
            self.assertIn(429, codes)
        finally:
            web_server.nsec.AUTH_THROTTLE = old
            old.reset()


class TestWebSecureEndpoint(_WebCase):
    def test_secure_status_toggle_and_info(self):
        r, b = self.get("/api/secure")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(b)["secure"], False)
        r, b = self.post("/api/secure", {"secure": True})
        self.assertEqual(r.status, 200)
        self.assertTrue(json.loads(b)["ok"])
        self.assertTrue(nsec.is_secure(self.ws))
        # /api/info now reports it
        r, b = self.get("/api/info")
        self.assertTrue(json.loads(b)["secure"])
        # invalid body -> clean 400
        r, b = self.post("/api/secure", {"nope": 1})
        self.assertEqual(r.status, 400)
        nsec.set_secure(False, ws=self.ws)


class TestNovaLog(unittest.TestCase):
    def test_notes_are_kept_in_ram_and_on_disk(self):
        nova_log.reset()
        nova_log.configure(None)
        nova_log.soft("test.site", ValueError("boom"), msg="ctx")
        entries = nova_log.tail(5)
        self.assertTrue(entries and entries[-1]["where"] == "test.site")
        self.assertIn("boom", entries[-1]["exc"])
        with tempfile.TemporaryDirectory() as td:
            nova_log.configure(td)
            nova_log.note("test.file", "hello", level="info")
            p = Path(td) / ".nova" / "logs" / "nova.log"
            self.assertTrue(p.is_file())
            rec = json.loads(p.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(rec["where"], "test.file")
        nova_log.reset()

    def test_ring_is_bounded(self):
        nova_log.reset()
        for i in range(nova_log.RAM_LIMIT + 50):
            nova_log.note("test.flood", str(i))
        self.assertLessEqual(len(nova_log.tail(100000)), nova_log.RAM_LIMIT)
        nova_log.reset()


class TestKnowledgeUpgrades(unittest.TestCase):
    def _ingest(self, td, name, text):
        p = Path(td) / name
        p.write_text(text, encoding="utf-8")
        nsec  # touch import for parity
        from nova_modules import knowledge as kn
        return kn, kn.ingest(td, [name])

    def test_phrase_match_outranks_scatter(self):
        with tempfile.TemporaryDirectory() as td:
            # a.md: the three words appear SCATTERED, never as one phrase
            (Path(td) / "a.md").write_text(
                "red and panda plus habitat mentioned apart. "
                "deployment pipeline filler filler filler. " * 5,
                encoding="utf-8")
            # b.md: the exact consecutive phrase
            (Path(td) / "b.md").write_text(
                "red panda habitat stretches across asia. "
                "deployment notes filler filler filler. " * 5,
                encoding="utf-8")
            from nova_modules import knowledge as kn
            kn.ingest(td, ["a.md", "b.md"])
            hits = kn.search(td, "red panda habitat", k=2)
            self.assertTrue(hits)
            self.assertEqual(hits[0]["doc"], "b.md")

    def test_recency_boost_prefers_fresh_doc(self):
        with tempfile.TemporaryDirectory() as td:
            text = "identical body about widget calibration and foo bar baz. " * 8
            (Path(td) / "old.md").write_text(text, encoding="utf-8")
            (Path(td) / "new.md").write_text(text, encoding="utf-8")
            kn, _ = self._ingest(td, "old.md", text)
            kn.ingest(td, ["new.md"])
            old_t = time.time() - 120 * 86400
            os.utime(Path(td) / "old.md", (old_t, old_t))
            kn.ingest(td, ["old.md", "new.md"])   # re-ingest stores mtimes
            hits = kn.search(td, "widget calibration", k=2)
            self.assertEqual(len(hits), 2)
            self.assertEqual(hits[0]["doc"], "new.md")

    def test_cache_invalidation_on_new_ingest(self):
        with tempfile.TemporaryDirectory() as td:
            kn, _ = self._ingest(td, "one.md", "alpha bravo charlie delta")
            self.assertEqual(kn.stats(td)["chunks"], 1)
            (Path(td) / "two.md").write_text("echo foxtrot golf hotel",
                                             encoding="utf-8")
            kn.ingest(td, ["two.md"])      # mtime changes -> cache must drop
            self.assertEqual(kn.stats(td)["chunks"], 2)


class TestTranscriptRamCap(unittest.TestCase):
    def test_long_session_stays_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            s = nova.Session(Path(td))
            for i in range(210):
                s.remember(f"u{i}", f"a{i}")
            self.assertLessEqual(len(s.transcript), nova.MAX_TRANSCRIPT_RAM)


class TestVersionPin(unittest.TestCase):
    def test_version(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
