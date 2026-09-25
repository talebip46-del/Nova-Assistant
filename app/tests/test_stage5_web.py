#!/usr/bin/env python3
"""Stage-5 tests: web face v5.0 - PWA assets, extended /api/info,
confirm-changes staging + /api/apply approval flow, /api/settings,
explain/autotest wiring. Talks to the REAL handlers on an ephemeral port."""
import json
import struct
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web_server
import nova


def mkfile(ws, rel, content):
    p = Path(ws) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# v6.3: the security guards (rate limiter, auth throttle) are process-wide
# and the tests share 127.0.0.1 - reset them so heavy API test bursts are
# not mistaken for abuse.
def _reset_web_guards():
    try:
        import nova_security as _nsec
        _nsec.API_LIMITER.reset()
        _nsec.SECURE_API_LIMITER.reset()
        _nsec.AUTH_THROTTLE.reset()
    except Exception:
        pass


class WebV5(unittest.TestCase):
    def setUp(self):
        _reset_web_guards()

    @classmethod
    def setUpClass(cls):
        _reset_web_guards()
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_web5_"))
        web_server.nova = nova   # in case the module was reloaded
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        cls.httpd = web_server._make_server(args)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = __import__("threading").Thread(
            target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        import shutil
        shutil.rmtree(cls.ws, ignore_errors=True)

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return (r.status, dict(r.headers), r.read())
        except urllib.error.HTTPError as e:
            return (e.code, dict(e.headers), e.read())

    def post(self, path, obj, ctype="application/json"):
        data = json.dumps(obj).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return (r.status, json.loads(r.read().decode()))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
            except Exception:
                body = {}
            return (e.code, body)

    # ------------------------------------------------- PWA assets
    def test_manifest_served(self):
        code, headers, body = self.get("/manifest.webmanifest")
        self.assertEqual(code, 200)
        m = json.loads(body.decode())
        self.assertEqual(m["display"], "standalone")
        self.assertTrue(m["icons"][0]["src"].startswith("/icons/"))

    def test_sw_served(self):
        code, headers, body = self.get("/sw.js")
        self.assertEqual(code, 200)
        text = body.decode()
        self.assertIn("addEventListener", text)
        self.assertIn("/api/", text)   # api exclusion documented

    def test_icons_are_valid_pngs(self):
        for path in ("/icons/icon-192.png", "/icons/icon-512.png",
                     "/apple-touch-icon.png"):
            code, _, body = self.get(path)
            self.assertEqual(code, 200)
            self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
            w, h = struct.unpack(">II", body[16:24])
            self.assertEqual((w, h), (192, 192) if "192" in path
                             else ((512, 512) if "512" in path else (180, 180)))

    def test_unknown_asset_404(self):
        code, _, _ = self.get("/icons/icon-64.png")
        self.assertEqual(code, 404)

    # ------------------------------------------------- /api/info v5.0
    def test_info_has_v5_fields(self):
        code, _, body = self.get("/api/info")
        self.assertEqual(code, 200)
        info = json.loads(body.decode())
        for key in ("explain", "confirm_changes", "autotest", "todo",
                    "cost", "bg_running", "bg_finished", "pending_apply",
                    "git_repo", "version"):
            self.assertIn(key, info)
        self.assertEqual(info["version"], "8.12.0")
        self.assertFalse(info["confirm_changes"])

    # ------------------------------------------------- settings
    def test_settings_toggle(self):
        code, res = self.post("/api/settings", {"confirm_changes": True})
        self.assertEqual(code, 200)
        self.assertTrue(res["confirm_changes"])
        self.assertTrue(web_server.STATE.sess.confirm_changes)
        code, res = self.post("/api/settings", {"confirm_changes": False})
        self.assertFalse(web_server.STATE.sess.confirm_changes)
        # v8.12: non-bool junk is REJECTED with 400 (it used to be
        # silently ignored while the panel toasted "saved")
        code, res = self.post("/api/settings", {"confirm_changes": "yes"})
        self.assertEqual(code, 400, res)
        self.assertIn("must be a boolean", str(res))

    def test_settings_requires_json_content_type(self):
        code, res = self.post("/api/settings", {"confirm_changes": True},
                              ctype="text/plain")
        self.assertEqual(code, 415)

    # ------------------------------------------------- staging + approval
    def test_stage_and_apply_flow(self):
        sess = web_server.STATE.sess
        sess.confirm_changes = True
        nova.NONINTERACTIVE = True
        try:
            # v6.8.1: the pre-apply lint gate runs on the web approval path
            # too, so the fixture content must be VALID python now
            answer = ("=== FILE: made/app.py ===\nprint('v1')\n=== END ===\n"
                      "=== EDIT: exist.py ===\n<<<<<<< SEARCH\nold_value = 1\n=======\nnew_value = 2\n"
                      ">>>>>>> REPLACE\n=== END ===\n")
            mkfile(self.ws, "exist.py", "old_value = 1\n")
            files, unnamed = nova.parse_files(answer)
            edits = nova.parse_edits(answer)
            res = nova.offer_apply(sess, files, unnamed, edits=edits, auto=True)
            self.assertEqual(res, [])          # nothing written yet
            self.assertFalse((self.ws / "made" / "app.py").exists())
            pend = sess.pending_apply
            self.assertIsNotNone(pend)
            self.assertEqual([p[0] for p in pend["plans"]], ["made/app.py"])
            self.assertIn("exist.py", pend["hunks"])
            # approve via the same code path /api/apply uses
            ok, result = nova.apply_approved(
                sess, pend["id"], ["made/app.py"], {"exist.py": [1]})
            self.assertTrue(ok, result)
            self.assertEqual((self.ws / "made" / "app.py").read_text(encoding="utf-8"),
                             "print('v1')")
            self.assertEqual((self.ws / "exist.py").read_text(encoding="utf-8"),
                             "new_value = 2\n")
            self.assertIsNone(sess.pending_apply)
        finally:
            sess.confirm_changes = False
            nova.NONINTERACTIVE = False

    def test_apply_lint_rejects_broken_file(self):
        # v6.8.1: the browser approval path must honor the pre-apply
        # lint gate - a syntax-broken file is refused WITHOUT writing
        sess = web_server.STATE.sess
        sess.confirm_changes = True
        nova.NONINTERACTIVE = True
        try:
            answer = "=== FILE: bad/app.py ===\ndef (:\n=== END ===\n"
            files, unnamed = nova.parse_files(answer)
            nova.offer_apply(sess, files, unnamed, edits=[], auto=True)
            pend = sess.pending_apply
            self.assertIsNotNone(pend)
            ok, result = nova.apply_approved(sess, pend["id"], ["bad/app.py"], {})
            self.assertFalse(ok)
            self.assertIn("pre-apply check failed", result["error"])
            self.assertFalse((self.ws / "bad" / "app.py").exists())
        finally:
            sess.confirm_changes = False
            nova.NONINTERACTIVE = False
            sess.pending_apply = None

    def test_apply_rejects_stale_batch(self):
        sess = web_server.STATE.sess
        sess.pending_apply = {"id": "p_old", "plans": [], "hunks": {},
                              "ts": time.time() - 99999}
        ok, result = nova.apply_approved(sess, "p_old", [], {})
        self.assertFalse(ok)
        self.assertIn("expired", result["error"])
        sess.pending_apply = None

    def test_apply_wrong_id_refused(self):
        sess = web_server.STATE.sess
        sess.pending_apply = {"id": "p_real", "plans": [], "hunks": {},
                              "ts": time.time()}
        ok, result = nova.apply_approved(sess, "p_other", [], {})
        self.assertFalse(ok)
        self.assertIn("no matching", result["error"])
        sess.pending_apply = None

    def test_api_apply_endpoint(self):
        sess = web_server.STATE.sess
        sess.confirm_changes = True
        nova.NONINTERACTIVE = True
        try:
            answer = "=== FILE: api_made.py ===\nx = 1\n=== END ===\n"
            files, unnamed = nova.parse_files(answer)
            nova.offer_apply(sess, files, unnamed, edits=[], auto=True)
            bid = sess.pending_apply["id"]
            # wrong id -> 409
            code, res = self.post("/api/apply", {"id": "nope", "files": [],
                                                 "hunks": {}})
            self.assertEqual(code, 409)
            # right id -> applied
            code, res = self.post("/api/apply", {"id": bid,
                                                 "files": ["api_made.py"],
                                                 "hunks": {}})
            self.assertEqual(code, 200)
            self.assertEqual(res["applied"], ["api_made.py"])
            self.assertTrue((self.ws / "api_made.py").is_file())
            # second apply with the same id -> 409 (already consumed)
            code, res = self.post("/api/apply", {"id": bid, "files": [],
                                                 "hunks": {}})
            self.assertEqual(code, 409)
        finally:
            sess.confirm_changes = False
            nova.NONINTERACTIVE = False

    def test_apply_invalid_hunk_index_ignored(self):
        sess = web_server.STATE.sess
        sess.pending_apply = {"id": "p1", "plans": [], "hunks": {"a.py": [("x", "y")]},
                              "ts": time.time()}
        ok, result = nova.apply_approved(sess, "p1", [], {"a.py": [99, 0, -1, "x"]})
        self.assertTrue(ok)          # nothing selected -> skipped, not an error
        self.assertEqual(result["applied"], [])
        self.assertIn("a.py", result["skipped"])
        sess.pending_apply = None

    def test_edit_staging_revalidates_at_apply(self):
        """The file changed between staging and approval -> the stale hunk
        is refused instead of corrupting the file."""
        sess = web_server.STATE.sess
        sess.confirm_changes = True
        nova.NONINTERACTIVE = True
        try:
            # v6.8.1: fixtures are valid python now - the approval path
            # runs the pre-apply lint gate on the merged result
            mkfile(self.ws, "drift.py", "line_a = 1\nline_b = 2\n")
            answer = ("=== EDIT: drift.py ===\n<<<<<<< SEARCH\nline_a = 1\n=======\n"
                      "LINE_A = 1\n>>>>>>> REPLACE\n=== END ===\n")
            edits = nova.parse_edits(answer)
            nova.offer_apply(sess, [], [], edits=edits, auto=True)
            # user edits the file manually AFTER staging
            mkfile(self.ws, "drift.py", "completely_different = 0\n")
            ok, result = nova.apply_approved(sess, sess.pending_apply["id"],
                                             [], {"drift.py": [1]})
            self.assertTrue(ok)
            self.assertTrue(any("hunk 1" in e for e in result["errors"]))
            self.assertEqual((self.ws / "drift.py").read_text(encoding="utf-8"),
                             "completely_different = 0\n")
        finally:
            sess.confirm_changes = False
            nova.NONINTERACTIVE = False


if __name__ == "__main__":
    unittest.main()
