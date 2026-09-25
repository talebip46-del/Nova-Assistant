#!/usr/bin/env python3
"""v6.4 tests: the simple-chat (گفت و گو) web tab + the small-model file
protocol hardening.

Two bug families reported by a real user are pinned here:
  1. "the file it made was wrong / could not run" - markdown fences written
     INTO files, === FILE: === blocks without === END === silently dropped,
     'Run:' lines ending up inside file bodies, 'python3' hints that do not
     exist on Windows, and a frozen exe suggesting ITSELF as interpreter;
  2. the new simple-chat tab - /api/talk streams a protocol-free turn with
     its own RAM-capped history and never touches the coding session.
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
from unittest import mock

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
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield


def _reset_web_guards():
    try:
        import nova_security as _nsec
        _nsec.API_LIMITER.reset()
        _nsec.SECURE_API_LIMITER.reset()
        _nsec.AUTH_THROTTLE.reset()
    except Exception:
        pass


# =====================================================================
# 1. file protocol hardening (pure parsing)
# =====================================================================
class TestFenceStripping(unittest.TestCase):
    def test_fenced_python_body_is_stripped(self):
        ans = ("Here is your file:\n\n=== FILE: hello.py ===\n```python\n"
               'print("hi")\n```\n=== END ===\n\nRun: python3 hello.py')
        hints = []
        files, unnamed = nova.parse_files(ans, run_hints=hints)
        self.assertEqual(files, [("hello.py", 'print("hi")')])
        self.assertEqual(unnamed, [])
        self.assertEqual(hints, [])          # the outer Run: hint is separate

    def test_fenced_html_body_is_stripped(self):
        ans = ("=== FILE: index.html ===\n```html\n<!DOCTYPE html>\n"
               "<html></html>\n```\n=== END ===")
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [("index.html", "<!DOCTYPE html>\n<html></html>")])

    def test_bare_fences_are_stripped(self):
        ans = "=== FILE: s.js ===\n```\nconsole.log(1)\n```\n=== END ==="
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [("s.js", "console.log(1)")])

    def test_readme_with_legit_fences_is_untouched(self):
        body = "```python\nprint(1)\n```\n\ntext\n\n```bash\nls\n```"
        ans = "=== FILE: README.md ===\n" + body + "\n=== END ==="
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [("README.md", body)])

    def test_three_fences_are_untouched(self):
        body = "```python\nprint(1)\n```\nmore\n```"
        ans = "=== FILE: w.md ===\n" + body + "\n=== END ==="
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [("w.md", body)])

    def test_plain_body_is_byte_identical(self):
        ans = "=== FILE: x.py ===\nprint('x')\n=== END ===\nRun: python3 x.py"
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [("x.py", "print('x')")])


class TestUnclosedBlockSalvage(unittest.TestCase):
    def test_unclosed_block_is_recovered_with_note(self):
        ans = "=== FILE: app.py ===\nimport sys\n\ndef main():\n    print('x')\n\nRun: python app.py"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            files, _ = nova.parse_files(ans)
        self.assertEqual(files,
                         [("app.py", "import sys\n\ndef main():\n    print('x')")])
        self.assertIn("[fix]", buf.getvalue())     # never silent

    def test_complete_plus_unclosed_blocks(self):
        ans = ("=== FILE: a.py ===\nprint('a')\n=== END ===\nsome text\n"
               "=== FILE: b.py ===\nprint('b')\n=== END MISSING")
        files, _ = nova.parse_files(ans)
        self.assertEqual([f[0] for f in files], ["a.py", "b.py"])
        self.assertEqual(files[1][1], "print('b')")

    def test_salvage_stops_at_next_marker(self):
        ans = "=== FILE: c.py ===\nprint('c')\n=== PLAN ===\n1. next"
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [("c.py", "print('c')")])

    def test_prose_marker_mid_sentence_is_ignored(self):
        ans = ("You can use === FILE: x.py === in your answer protocol "
               "description.\nDone!")
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [])

    def test_truncated_single_fence_is_dropped(self):
        ans = "=== FILE: b.py ===\n```python\nprint(1)\nprint(2)"
        files, _ = nova.parse_files(ans)
        self.assertEqual(files, [("b.py", "print(1)\nprint(2)")])


class TestRunHintInBody(unittest.TestCase):
    def test_run_line_inside_body_is_stripped_and_collected(self):
        ans = "=== FILE: a.py ===\nprint(1)\nRun: python a.py\n=== END ==="
        hints = []
        files, _ = nova.parse_files(ans, run_hints=hints)
        self.assertEqual(files, [("a.py", "print(1)")])
        self.assertEqual(hints, ["python a.py"])

    def test_makefile_lowercase_run_target_stays(self):
        ans = "=== FILE: Makefile ===\nall: build\n\nrun: main.py\n=== END ==="
        hints = []
        files, _ = nova.parse_files(ans, run_hints=hints)
        self.assertEqual(files, [("Makefile", "all: build\n\nrun: main.py")])
        self.assertEqual(hints, [])


class TestInterpreterNormalization(unittest.TestCase):
    def test_non_python_commands_pass_through(self):
        self.assertEqual(nova._normalize_run_hint("node server.js"),
                         "node server.js")
        self.assertEqual(nova._normalize_run_hint("start index.html"),
                         "start index.html")

    def test_quotes_and_whitespace_are_trimmed(self):
        a = nova._normalize_run_hint("  `python app.py` ")
        b = nova._normalize_run_hint("python app.py")
        self.assertEqual(a, b)

    def test_posix_output_is_a_valid_interpreter(self):
        if os_is_posix():
            out = nova._normalize_run_hint("python3 hello.py")
            parts = out.split()
            self.assertEqual(parts[1:], ["hello.py"])
            self.assertTrue(parts[0].startswith("python"),
                            "unexpected interpreter: " + parts[0])

    def test_windows_rewrites_python3_to_a_real_interpreter(self):
        with mock.patch.object(nova.os, "name", "nt"), \
                mock.patch.object(nova.shutil, "which",
                                  side_effect=lambda c: "C:\\Py\\python.exe"
                                  if c == "python" else None):
            self.assertEqual(nova._normalize_run_hint("python3 hello.py"),
                             "python hello.py")

    def test_windows_versioned_python_is_normalized(self):
        with mock.patch.object(nova.os, "name", "nt"), \
                mock.patch.object(nova.shutil, "which",
                                  side_effect=lambda c: "C:\\Py\\python.exe"
                                  if c == "python" else None):
            self.assertEqual(nova._normalize_run_hint("python3.11 app.py"),
                             "python app.py")

    def test_frozen_exe_never_suggests_itself(self):
        # a packaged NovaAssistant.exe used to produce
        # 'NovaAssistant.exe main.py' as the run suggestion
        with mock.patch.object(nova.sys, "frozen", True, create=True), \
                mock.patch.object(nova.os, "name", "nt"), \
                mock.patch.object(nova.shutil, "which",
                                  side_effect=lambda c: "C:\\Py\\python.exe"
                                  if c == "python" else None):
            self.assertEqual(nova.py_run_name(), "python")

    def test_non_frozen_suggests_the_running_interpreter(self):
        name = nova.py_run_name()
        self.assertTrue(name.startswith("python") or name == "py",
                        "unexpected interpreter name: " + name)


def os_is_posix():
    return nova.os.name != "nt"


# =====================================================================
# 2. the simple-chat (گفت و گو) endpoint
# =====================================================================
class _ServerCase(unittest.TestCase):
    AUTH = False

    def setUp(self):
        _reset_web_guards()
        self._tmpdir = tempfile.TemporaryDirectory()
        workspace = Path(self._tmpdir.name)
        web_server.STATE = web_server._State(workspace)
        web_server.AUTH_TOKEN = web_server._new_token() if self.AUTH else None
        self.token = web_server.AUTH_TOKEN
        self.httpd = web_server._make_server({"host": "127.0.0.1", "port": 0})
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
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
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        self._conns.append(c)
        return c


class TestTalkTab(_ServerCase):
    def _post_talk(self, body):
        c = self.conn()
        c.request("POST", "/api/talk", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return r, _read_ndjson(r)

    def test_talk_rejects_empty_message(self):
        r, _ = self._post_talk({"message": "  "})
        self.assertEqual(r.status, 400)

    def test_talk_rejects_oversized_message(self):
        r, _ = self._post_talk({"message": "x" * 20_001})
        self.assertEqual(r.status, 400)

    def test_talk_streams_tokens_and_keeps_history(self):
        captured = {}

        def fake_stream_chat(model, messages, temperature, sess=None, section=None):
            captured["messages"] = messages
            captured["temperature"] = temperature
            if nova.TOKEN_SINK:
                nova.TOKEN_SINK("سلام! ")
                nova.TOKEN_SINK("چطوری؟")
            return "سلام! چطوری؟", True

        with _quiet(), mock.patch.object(web_server.nova, "stream_chat",
                                         fake_stream_chat):
            r, events = self._post_talk({"message": "سلام"})
        self.assertEqual(r.status, 200)
        toks = "".join(e["text"] for e in events if e.get("t") == "tok")
        self.assertEqual(toks, "سلام! چطوری؟")
        done = [e for e in events if e.get("t") == "done"]
        self.assertEqual(len(done), 1)
        self.assertIsNone(done[0]["run_cmd"])
        self.assertEqual(done[0]["changed"], [])
        # history: user + assistant, and the system prompt is the TALK one
        hist = web_server.STATE.talk_history
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["role"], "user")
        self.assertEqual(hist[1]["content"], "سلام! چطوری؟")
        msgs = captured["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("SIMPLE CHAT", msgs[0]["content"])
        # NOT the coding agent's system prompt (its brand/rules must be absent)
        self.assertNotIn("Nova Code", msgs[0]["content"])
        self.assertNotIn("MOST IMPORTANT RULE", msgs[0]["content"])
        self.assertEqual(captured["temperature"], web_server.TALK_TEMPERATURE)

    def test_talk_history_is_capped_in_ram(self):
        web_server.STATE.talk_history = [
            {"role": "user", "content": "junk %d" % i}
            for i in range(web_server.TALK_HISTORY_CAP)]

        def fake_stream_chat(model, messages, temperature, sess=None, section=None):
            return "ok", True

        with _quiet(), mock.patch.object(web_server.nova, "stream_chat",
                                         fake_stream_chat):
            r, _ = self._post_talk({"message": "hello"})
        self.assertEqual(r.status, 200)
        hist = web_server.STATE.talk_history
        self.assertEqual(len(hist), web_server.TALK_HISTORY_CAP)
        self.assertEqual(hist[-1]["content"], "ok")
        self.assertEqual(hist[-2]["content"], "hello")
        self.assertTrue(hist[0]["content"].startswith("junk"))

    def test_talk_empty_answer_emits_a_clear_error(self):
        def fake_stream_chat(model, messages, temperature, sess=None, section=None):
            return "", False          # e.g. Ollama is down

        with _quiet(), mock.patch.object(web_server.nova, "stream_chat",
                                         fake_stream_chat):
            r, events = self._post_talk({"message": "سلام"})
        self.assertEqual(r.status, 200)
        errs = [e for e in events if e.get("t") == "err"]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["text"], web_server.TALK_EMPTY_MSG)
        self.assertEqual(web_server.STATE.talk_history, [])

    def test_talk_never_touches_the_coding_session(self):
        sess = web_server.STATE.sess
        before_touched = dict(sess.touched)
        before_history = list(sess.history)

        def fake_stream_chat(model, messages, temperature, sess=None, section=None):
            return "گپ ساده", True

        with _quiet(), mock.patch.object(web_server.nova, "stream_chat",
                                         fake_stream_chat):
            r, _ = self._post_talk({"message": "سلام"})
        self.assertEqual(r.status, 200)
        self.assertEqual(sess.touched, before_touched)
        self.assertEqual(sess.history, before_history)

    def test_talk_fails_fast_while_a_turn_is_running(self):
        # a simple-chat turn must not queue 3 minutes behind a coding turn
        acquired = web_server.TURN_LOCK.acquire(timeout=5)
        self.assertTrue(acquired)
        try:
            r, _ = self._post_talk({"message": "hello"})
            self.assertEqual(r.status, 409)
        finally:
            web_server.TURN_LOCK.release()

    def test_version_is_640(self):
        self.assertEqual(nova.VERSION, "8.12.0")

    def test_index_html_has_both_chat_tabs(self):
        page = (Path(web_server.WEB_DIR) / "index.html").read_text(
            encoding="utf-8")
        self.assertIn('data-view="talk"', page)      # the new simple-chat tab
        self.assertIn("کدنویسی", page)               # renamed coding tab
        self.assertIn("/api/talk", page)             # wired to the endpoint
        self.assertIn("panel-talk", page)


if __name__ == "__main__":
    unittest.main()
