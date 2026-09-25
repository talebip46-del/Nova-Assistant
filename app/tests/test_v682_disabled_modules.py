#!/usr/bin/env python3
"""v6.8.2 tests: the module kill-switch.

The four media/automation modules (voice / photo / pixel / flow) are
DISABLED by default on the web surface - product focus is the two chat
surfaces (code chat + normal talk). These tests pin BOTH halves of the
feature:

  - the web tab buttons ship dead (disabled + aria-disabled + a
    «غیرفعال» badge right on the button) and switchView() refuses the
    view programmatically (web/index.html static checks)
  - every API endpoint of a disabled module answers a clean 403 JSON
    (path-prefix routes AND the kind-parameterised gallery/file routes),
    while /api/chat, /api/talk and every still-enabled module keep
    working untouched
  - NOVA_DISABLED_MODULES re-opens modules without code edits (empty =
    all on, a custom list = partial off, junk names ignored)
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import web_server  # noqa: E402
import nova        # noqa: E402


def _reset_guards():
    # v6.3: the security limiters are process-wide - reset so the test
    # bursts here (and alongside the other web suites) are not mistaken
    # for abuse.
    try:
        import nova_security as nsec
        nsec.API_LIMITER.reset()
        nsec.SECURE_API_LIMITER.reset()
        nsec.AUTH_THROTTLE.reset()
    except Exception:
        pass


ENV = "NOVA_DISABLED_MODULES"


class KillSwitchServer(unittest.TestCase):
    """Talks to the REAL handlers on an ephemeral port (same pattern as
    test_v6_web / test_stage5_web)."""

    @classmethod
    def setUpClass(cls):
        _reset_guards()
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_v682_"))
        web_server.nova = nova
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        cls.httpd = web_server._make_server(args)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        _reset_guards()
        # each test starts from the PRISTINE default: env unset -> the
        # kill-switch ships all four modules disabled
        self._old = os.environ.pop(ENV, None)

    def tearDown(self):
        if self._old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = self._old

    # ---------------- helpers ----------------
    def get(self, path):
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def post(self, path, obj):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def set_env(self, value):
        os.environ[ENV] = value

    # ---------------- default: all four off ----------------
    def test_default_all_module_post_endpoints_are_403(self):
        for path, body in (
                ("/api/voice/tts", {"text": "سلام"}),
                ("/api/voice/stt", {"data_b64": "aGk="}),
                ("/api/photo/generate", {"prompt": "گربه"}),
                ("/api/pixel/generate", {"prompt": "گربه"}),
                ("/api/pixel/upscale", {"k": "x"}),
                ("/api/flow/save", {"name": "f", "steps": []}),
                ("/api/flow/run", {"name": "f"}),
                ("/api/flow/delete", {"name": "f"})):
            code, body_out = self.post(path, body)
            self.assertEqual(code, 403, "%s must be kill-switched" % path)
            self.assertTrue(body_out.get("disabled"), path)
            self.assertIn("module", body_out)

    def test_default_all_module_get_endpoints_are_403(self):
        for path in ("/api/flows", "/api/flow", "/api/flow_status?run=x",
                     "/api/gallery?k=pixel", "/api/gallery?k=photo",
                     "/api/gallery?k=voice", "/api/file?k=voice&name=n"):
            code, body_out = self.get(path)
            self.assertEqual(code, 403, "%s must be kill-switched" % path)
            self.assertTrue(body_out.get("disabled"), path)

    def test_403_body_names_the_module_in_persian(self):
        code, body = self.post("/api/voice/tts", {"text": "سلام"})
        self.assertEqual(code, 403)
        self.assertEqual(body.get("module"), "voice")
        self.assertIn("غیرفعال", body.get("error", ""))
        code, body = self.get("/api/flows")
        self.assertEqual(code, 403)
        self.assertEqual(body.get("module"), "flow")
        self.assertIn("غیرفعال", body.get("error", ""))

    # ---------------- still-enabled surface untouched ----------------
    def test_chat_and_talk_are_not_blocked(self):
        # empty message -> the normal 400 validation error, NOT the
        # kill-switch 403 (proves the chat routes pass the guard)
        code, body = self.post("/api/talk", {})
        self.assertEqual(code, 400)
        self.assertFalse(body.get("disabled", False))
        code, body = self.post("/api/chat", {})
        self.assertEqual(code, 400)
        self.assertFalse(body.get("disabled", False))

    def test_enabled_modules_still_reach_their_handlers(self):
        # knowledge stays on: its endpoints must NOT answer 403
        code, body = self.get("/api/knowledge?q=x")
        self.assertNotEqual(code, 403)
        self.assertFalse(body.get("disabled", False))
        # gallery of an unknown kind passes the guard and hits the real
        # handler -> the normal 400 "unknown gallery kind"
        code, body = self.get("/api/gallery?k=bogus")
        self.assertEqual(code, 400)
        self.assertFalse(body.get("disabled", False))

    # ---------------- NOVA_DISABLED_MODULES control ----------------
    def test_empty_env_reenables_everything(self):
        self.set_env("")
        code, body = self.post("/api/voice/tts", {"text": "  "})
        # module is alive again: the REAL handler ran (no TTS engine in
        # the test env -> the normal 502), not the kill-switch 403
        self.assertEqual(code, 502)
        self.assertFalse(body.get("disabled", False))
        code, _ = self.get("/api/flows")
        self.assertEqual(code, 200)

    def test_partial_list_disables_only_the_named_modules(self):
        self.set_env("pixel")
        code, body = self.post("/api/pixel/generate", {"prompt": "x"})
        self.assertEqual(code, 403)
        self.assertEqual(body.get("module"), "pixel")
        code, body = self.post("/api/voice/tts", {"text": "  "})
        self.assertEqual(code, 502)          # voice is NOT switch-403'd
        self.assertFalse(body.get("disabled", False))
        code, _ = self.get("/api/flows")
        self.assertEqual(code, 200)          # flow is NOT in the list

    def test_junk_names_are_ignored(self):
        self.set_env("banana, flow ,,")
        code, _ = self.post("/api/voice/tts", {"text": "  "})
        self.assertEqual(code, 502)          # not in the list -> alive
        code, body = self.post("/api/flow/run", {"name": "f"})
        self.assertEqual(code, 403)          # flow IS in the list
        self.assertEqual(body.get("module"), "flow")

    def test_unknown_kind_param_passes_the_guard(self):
        # /api/file with a non-module kind must not be caught by the
        # kind-parameterised branch
        code, body = self.get("/api/file?k=code&name=n")
        self.assertNotEqual(code, 403)
        self.assertFalse(body.get("disabled", False))


class TabMarkup(unittest.TestCase):
    """The index.html half: dead buttons WITH the «غیرفعال» badge, and
    the switchView() guard so the panels can never be opened."""

    @classmethod
    def setUpClass(cls):
        cls.page = (APP / "web" / "index.html").read_text(encoding="utf-8")

    def _tab_line(self, view):
        for line in self.page.splitlines():
            if 'data-view="%s"' % view in line and "mtab" in line:
                return line
        self.fail("no tab line for %r" % view)

    def test_four_module_tabs_ship_disabled_with_badge(self):
        for view in ("voice", "photo", "pixel", "flow"):
            line = self._tab_line(view)
            self.assertIn("disabled", line, view)
            self.assertIn('aria-disabled="true"', line, view)
            self.assertIn("غیرفعال", line, view)
            self.assertIn("mtab-dis", line, view)

    def test_chat_and_talk_tabs_are_not_disabled(self):
        for view in ("chat", "talk"):
            line = self._tab_line(view)
            self.assertNotIn("disabled", line, view)
            self.assertNotIn("mtab-dis", line, view)

    def test_other_tabs_stay_enabled(self):
        for view in ("knowledge", "models", "status"):
            line = self._tab_line(view)
            self.assertNotIn("disabled", line, view)

    def test_switchview_refuses_disabled_views(self):
        self.assertIn("DISABLED_VIEWS", self.page)
        self.assertIn("showNotice(", self.page)
        # the guard sits at the TOP of switchView - before any panel
        # could be un-hidden
        head = self.page[self.page.index("function switchView("):]
        head = head[:head.index("currentView = view;")]
        self.assertIn("DISABLED_VIEWS[view]", head)
        self.assertIn("return;", head)


if __name__ == "__main__":
    unittest.main()
