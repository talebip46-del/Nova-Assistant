"""Unit tests for web_server.py.

Runs the REAL ThreadingHTTPServer/Handler on an ephemeral 127.0.0.1
port (loopback only - no external network, no LLM/Ollama calls).
Slash commands that don't touch a provider (e.g. /help) are used to
exercise the streaming turn machinery without a network dependency.
"""
import contextlib
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import web_server  # noqa: E402


def _read_ndjson(resp):
    """Decode a chunked NDJSON response body into a list of events."""
    raw = resp.read().decode("utf-8")
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            pass  # http.client already de-chunks; nothing else to strip
    return events


@contextlib.contextmanager
def _quiet():
    """Swallow the agent's own console prints (mirrored to stdout by
    the web bridge) so `/help`-style turns don't flood test output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


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


class _ServerCase(unittest.TestCase):
    """Base class: spins up a fresh server + workspace per test, and
    always resets web_server's module globals afterwards so tests
    never leak auth/session state into each other."""

    AUTH = False  # override in subclasses that need a token

    def setUp(self):
        _reset_web_guards()
        self._tmpdir = tempfile.TemporaryDirectory()
        workspace = Path(self._tmpdir.name)
        web_server.STATE = web_server._State(workspace)
        web_server.AUTH_TOKEN = web_server._new_token() if self.AUTH else None
        self.token = web_server.AUTH_TOKEN
        self.httpd = web_server._make_server({"host": "127.0.0.1", "port": 0})
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self._conns = []

    def tearDown(self):
        for c in self._conns:
            try:
                c.close()
            except Exception:
                pass
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        web_server.STATE = None
        web_server.AUTH_TOKEN = None
        self._tmpdir.cleanup()

    def conn(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self._conns.append(c)
        return c


class TestFavicon(_ServerCase):
    def test_favicon_ico(self):
        c = self.conn()
        c.request("GET", "/favicon.ico")
        r = c.getresponse()
        body = r.read()
        self.assertEqual(r.status, 200)
        self.assertIn("image/svg+xml", r.getheader("Content-Type", ""))
        self.assertTrue(body.strip().startswith(b"<svg"))

    def test_favicon_svg(self):
        c = self.conn()
        c.request("GET", "/favicon.svg")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        r.read()

    def test_favicon_is_public_even_when_auth_required(self):
        web_server.AUTH_TOKEN = web_server._new_token()
        c = self.conn()
        c.request("GET", "/favicon.ico")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        r.read()


class TestNoAuthOnLoopback(_ServerCase):
    """Default behavior (127.0.0.1) must stay exactly as before: no
    token, no cookie, nothing new for a normal local user to trip on."""

    def test_page_loads_without_token(self):
        c = self.conn()
        c.request("GET", "/")
        r = c.getresponse()
        body = r.read()
        self.assertEqual(r.status, 200)
        self.assertIn(b"Nova Assistant", body)
        self.assertIsNone(r.getheader("Set-Cookie"))

    def test_api_info_without_token(self):
        c = self.conn()
        c.request("GET", "/api/info")
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 200)
        for key in ("agent", "version", "provider", "model", "workspace", "workspace_name"):
            self.assertIn(key, data)


class TestAuthRequired(_ServerCase):
    AUTH = True

    def test_page_without_token_is_rejected(self):
        c = self.conn()
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 401)

    def test_api_info_without_cookie_is_rejected(self):
        c = self.conn()
        c.request("GET", "/api/info")
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 401)

    def test_wrong_token_is_rejected(self):
        c = self.conn()
        c.request("GET", "/?token=not-the-real-token")
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 401)

    def test_correct_token_grants_a_cookie_that_unlocks_the_api(self):
        c = self.conn()
        c.request("GET", "/?token=" + self.token)
        r = c.getresponse()
        body = r.read()
        self.assertEqual(r.status, 200)
        set_cookie = r.getheader("Set-Cookie", "")
        self.assertIn("nova_token=" + self.token, set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn(b"Nova Assistant", body)

        # the cookie alone (no query token) must now unlock the API
        c2 = self.conn()
        c2.request("GET", "/api/info", headers={"Cookie": "nova_token=" + self.token})
        r2 = c2.getresponse()
        data = json.loads(r2.read())
        self.assertEqual(r2.status, 200)
        self.assertIn("workspace_name", data)

    def test_post_endpoints_require_the_cookie(self):
        c = self.conn()
        c.request("POST", "/api/chat", body=json.dumps({"message": "/help"}),
                   headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 401)
        self.assertIn("error", data)


class TestLoopbackHostsTable(unittest.TestCase):
    """Guards the exact decision serve() makes: only these hosts skip
    the auth token. Catches an accidental future change (e.g. someone
    adding '0.0.0.0' here) that would silently disable protection.
    NOTE: '' (empty) is deliberately NOT exempt: it binds 0.0.0.0."""

    def test_local_hosts_are_exempt(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            self.assertIn(host, web_server.LOOPBACK_HOSTS)

    def test_empty_host_is_not_exempt(self):
        # '' binds all interfaces (0.0.0.0) - it must require a token
        self.assertNotIn("", web_server.LOOPBACK_HOSTS)

    def test_network_hosts_are_not_exempt(self):
        for host in ("0.0.0.0", "192.168.1.5", "::"):
            self.assertNotIn(host, web_server.LOOPBACK_HOSTS)


class TestRequestValidation(_ServerCase):
    def test_chat_rejects_empty_message(self):
        c = self.conn()
        c.request("POST", "/api/chat", body=json.dumps({"message": "  "}),
                   headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 400)
        self.assertIn("error", data)

    def test_chat_rejects_oversized_message(self):
        c = self.conn()
        huge = "x" * 100_001
        c.request("POST", "/api/chat", body=json.dumps({"message": huge}),
                   headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 400)
        self.assertIn("100k", data["error"])

    def test_run_rejects_empty_command(self):
        c = self.conn()
        c.request("POST", "/api/run", body=json.dumps({"command": ""}),
                   headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 400)
        self.assertIn("error", data)

    def test_run_rejects_oversized_command(self):
        c = self.conn()
        c.request("POST", "/api/run", body=json.dumps({"command": "x" * 501}),
                   headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 400)

    def test_body_must_be_json_object(self):
        c = self.conn()
        c.request("POST", "/api/chat", body="not json",
                   headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 400)
        self.assertIn("error", data)

    def test_unknown_get_path_is_404(self):
        c = self.conn()
        c.request("GET", "/nope")
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 404)

    def test_unknown_post_path_is_404(self):
        c = self.conn()
        c.request("POST", "/nope", body="{}", headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 404)


class TestCSRFProtection(_ServerCase):
    """The v4.1 drive-by (CSRF) guards on the tokenless loopback default:
    cross-site Origins, non-JSON content types and rebinding Host headers
    must all be rejected BEFORE an agent turn can start."""

    def test_cross_origin_post_is_rejected(self):
        c = self.conn()
        c.request("POST", "/api/run", body=json.dumps({"command": "echo hi"}),
                  headers={"Content-Type": "application/json",
                           "Origin": "https://evil.example"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 403)
        self.assertIn("error", data)

    def test_same_origin_post_is_allowed(self):
        with _quiet():
            c = self.conn()
            c.request("POST", "/api/chat", body=json.dumps({"message": "/help"}),
                      headers={"Content-Type": "application/json",
                               "Origin": "http://127.0.0.1:%d" % self.port})
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            r.read()
            c.close()

    def test_non_json_content_type_is_rejected(self):
        # what a cross-site HTML <form> posts looks like: text/plain
        c = self.conn()
        c.request("POST", "/api/run", body=json.dumps({"command": "echo hi"}),
                  headers={"Content-Type": "text/plain"})
        r = c.getresponse()
        data = json.loads(r.read())
        self.assertEqual(r.status, 415)
        self.assertIn("error", data)

    def test_rebinding_host_header_is_rejected(self):
        c = self.conn()
        c.request("GET", "/", headers={"Host": "evil.example"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)

    def test_non_ascii_token_is_not_a_crash(self):
        # secrets.compare_digest(str, str) raises TypeError on non-ASCII
        # input: a hostile ?token=%C3%A9 must end as a clean 401, not a
        # dead handler thread (needs token mode - loopback skips tokens)
        web_server.AUTH_TOKEN = web_server._new_token()
        try:
            c = self.conn()
            c.request("GET", "/?token=%C3%A9")
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 401)
        finally:
            web_server.AUTH_TOKEN = None

    def test_error_response_closes_connection(self):
        # unread request bodies must not desync HTTP/1.1 keep-alive
        c = self.conn()
        c.request("POST", "/nope", body="x" * 100,
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 404)
        self.assertEqual(r.getheader("Connection", "").lower(), "close")


class TestStreamedTurn(_ServerCase):
    """Exercises the real NDJSON streaming path end-to-end with a slash
    command that never touches a network/LLM provider."""

    def test_help_command_streams_notes_and_terminates_cleanly(self):
        with _quiet():
            c = self.conn()
            c.request("POST", "/api/chat", body=json.dumps({"message": "/help"}),
                       headers={"Content-Type": "application/json"})
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            self.assertEqual(r.getheader("Transfer-Encoding"), "chunked")
            events = _read_ndjson(r)
            c.close()
        self.assertTrue(events, "expected at least one NDJSON event")
        self.assertEqual(events[-1]["t"], "done")

    def test_unknown_slash_command_reports_note_and_done(self):
        with _quiet():
            c = self.conn()
            c.request("POST", "/api/chat", body=json.dumps({"message": "/totally-not-a-command"}),
                       headers={"Content-Type": "application/json"})
            r = c.getresponse()
            events = _read_ndjson(r)
            c.close()
        self.assertEqual(events[-1]["t"], "done")
        notes = " ".join(e["text"] for e in events if e["t"] == "note")
        self.assertIn("unknown command", notes)

    def test_turn_lock_serializes_concurrent_requests(self):
        """A second /api/chat while one is still 'in flight' must queue
        or be rejected with 409 - never corrupt the shared session."""
        results = []

        def fire():
            c = self.conn()
            c.request("POST", "/api/chat", body=json.dumps({"message": "/help"}),
                       headers={"Content-Type": "application/json"})
            r = c.getresponse()
            r.read()
            results.append(r.status)
            c.close()

        with _quiet():
            threads = [threading.Thread(target=fire) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
        # every request must resolve to a real HTTP status (200, since
        # /help returns almost instantly and the lock timeout is 180s)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(status == 200 for status in results))


if __name__ == "__main__":
    unittest.main()
