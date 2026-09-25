#!/usr/bin/env python3
"""v7.14 tests: THE THINK PROTOCOL (visible reasoning).

The user's ask: "برای هوش مصنوعی هایی که استدلال دارن یه === THINK === /
=== END === بساز که متنشونو اینجا بنویسن که دارن درباره چی و چطور فکر
میکنن، و حتی مدل های بدون استدلال را مجبور به استدلال کن".

Pinned here:
  - extract(): our markers (strict + lenient spacing), native <think>/
    <thinking>/<reasoning>/<thought> tags, unclosed blocks (open=True,
    empty answer), no-block passthrough, empty input, first-block-wins,
    thinking containing a fake === FILE: block never leaks into the answer
  - clean(): the history/parsing diet
  - capable(): reasoner families vs ordinary brains (name heuristic only)
  - the per-workspace mode file: auto default, atomic roundtrip, junk
    rejected, corrupt file degrades to auto, should_force matrix
    (auto/on/off x reasoner/non-reasoner), the NOVA_THINK=0 kill switch
  - force_prompt(): carries both markers, stays tiny, no file protocol
  - chat_turn integration: mocked stream_chat - the think text reaches
    result["think"] + the {t:"think"} event, files are parsed from the
    CLEAN answer, the stored history never contains the markers, and the
    system prompt carries the forced block for a non-reasoner brain
  - the talk server flow: {t:"think"} rides the NDJSON stream, the talk
    history stays clean, the forced fragment rides msgs[0] (mode off ->
    never)
  - UI pins: splitThink/renderThinkBox/renderAnswer + .thinkbox CSS exist,
    the streaming paint sites route through renderAnswer, no emoji
  - the /think command is registered + the version is 8.0.1
Everything is offline-deterministic (the model call is stubbed).
"""
import contextlib
import http.client
import io
import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_think as think  # noqa: E402
import web_server  # noqa: E402


def _read_ndjson(resp):
    raw = resp.read().decode("utf-8")
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
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
    web_server.AUTH_TOKEN = None


class TestThinkExtract(unittest.TestCase):
    def test_closed_block_is_split(self):
        raw = ("=== THINK ===\nاول فکر می‌کنم بعد می‌نویسم\n"
               "=== END ===\nاین پاسخ نهایی است.")
        r = think.extract(raw)
        self.assertEqual(r["think"], "اول فکر می‌کنم بعد می‌نویسم")
        self.assertEqual(r["answer"], "این پاسخ نهایی است.")
        self.assertFalse(r["native"])
        self.assertFalse(r["open"])

    def test_lenient_spacing_still_counts(self):
        for variant in ("===THINK===", "===  Think ===", "===think==="):
            raw = variant + "\nplan\n===END===\nanswer"
            r = think.extract(raw)
            self.assertEqual(r["think"], "plan", variant)
            self.assertEqual(r["answer"], "answer", variant)

    def test_unclosed_block_is_open_with_empty_answer(self):
        r = think.extract("=== THINK ===\nthinking and thinking")
        self.assertTrue(r["open"])
        self.assertEqual(r["answer"], "")
        self.assertIn("thinking", r["think"])

    def test_native_think_tags_convert(self):
        r = think.extract("<think>reasoning here</think>The answer.")
        self.assertTrue(r["native"])
        self.assertEqual(r["think"], "reasoning here")
        self.assertEqual(r["answer"], "The answer.")

    def test_native_variant_tags_convert(self):
        for tag in ("thinking", "reasoning", "thought"):
            r = think.extract("<%s>inner</%s>out" % (tag, tag))
            self.assertEqual(r["think"], "inner", tag)
            self.assertTrue(r["native"], tag)
            self.assertEqual(r["answer"], "out", tag)

    def test_native_unclosed_stream_cut(self):
        r = think.extract("<think>cut off mid thought")
        self.assertTrue(r["open"])
        self.assertTrue(r["native"])
        self.assertEqual(r["answer"], "")

    def test_no_block_passes_through(self):
        raw = "a plain answer with no reasoning at all"
        r = think.extract(raw)
        self.assertIsNone(r["think"])
        self.assertEqual(r["answer"], raw)
        self.assertFalse(r["open"])

    def test_empty_input(self):
        for junk in ("", "   \n  ", None):
            r = think.extract(junk)
            self.assertEqual(r["answer"], junk or "")

    def test_fake_file_block_inside_think_never_leaks(self):
        raw = ("=== THINK ===\nI could write\n=== FILE: evil.py ===\n"
               "but that stays in my head\n=== END ===\nDone explaining.")
        r = think.extract(raw)
        self.assertIn("evil.py", r["think"])
        self.assertNotIn("evil.py", r["answer"])

    def test_first_block_wins_second_stays_visible(self):
        raw = ("=== THINK ===\nfirst plan\n=== END ===\nanswer one\n"
               "=== THINK ===\nsecond plan\n=== END ===\nmore answer")
        r = think.extract(raw)
        self.assertEqual(r["think"], "first plan")
        self.assertIn("answer one", r["answer"])
        self.assertNotIn("first plan", r["answer"])

    def test_clean_strips_everything(self):
        raw = "=== THINK ===\nplan\n=== END ===\nbody"
        self.assertEqual(think.clean(raw), "body")
        self.assertEqual(think.clean("<think>t</think>b"), "b")
        self.assertEqual(think.clean("plain"), "plain")


class TestThinkCapable(unittest.TestCase):
    def test_native_reasoners_are_capable(self):
        for name in ("deepseek-r1:14b", "deepseek-r1-distill-qwen-7b",
                     "QwQ-32B", "qwen3:4b", "Qwen3-Coder-30B",
                     "o3-mini", "o1-preview", "phi-4-reasoning",
                     "glm-4.5-air", "magistral-small"):
            self.assertTrue(think.capable(name), name)

    def test_ordinary_brains_are_not(self):
        for name in ("qwen2.5-coder:7b", "llama3.1:8b", "gpt-4o",
                     "mistral-7b", "phi3:mini", "granite-code:8b", ""):
            self.assertFalse(think.capable(name), name)

    def test_junk_input_is_safe(self):
        self.assertFalse(think.capable(None))
        self.assertFalse(think.capable(12345))


class TestThinkModeFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_is_auto(self):
        self.assertEqual(think.mode(self.ws), "auto")

    def test_set_get_roundtrip(self):
        for m in ("on", "off", "auto"):
            self.assertEqual(think.set_mode(self.ws, m), m)
            self.assertEqual(think.mode(self.ws), m)

    def test_uppercase_and_spaces_are_folded(self):
        self.assertEqual(think.set_mode(self.ws, "  ON "), "on")
        self.assertEqual(think.mode(self.ws), "on")

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            think.set_mode(self.ws, "maybe")

    def test_corrupt_file_degrades_to_auto(self):
        (self.ws / ".nova").mkdir(exist_ok=True)
        (self.ws / ".nova" / think.CONFIG_NAME).write_text("{broken",
                                                           encoding="utf-8")
        self.assertEqual(think.mode(self.ws), "auto")

    def test_wrong_value_degrades_to_auto(self):
        (self.ws / ".nova").mkdir(exist_ok=True)
        (self.ws / ".nova" / think.CONFIG_NAME).write_text(
            json.dumps({"mode": "sometimes"}), encoding="utf-8")
        self.assertEqual(think.mode(self.ws), "auto")


class TestShouldForce(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_matrix(self):
        cases = [
            ("auto", "qwen2.5-coder", True),    # weak brain -> forced
            ("auto", "deepseek-r1:7b", False),  # native -> not forced
            ("on", "deepseek-r1:7b", True),     # on -> everyone
            ("on", "qwen2.5-coder", True),
            ("off", "qwen2.5-coder", False),    # off -> nobody
            ("off", "deepseek-r1:7b", False),
        ]
        for m, model, want in cases:
            think.set_mode(self.ws, m)
            self.assertEqual(think.should_force(self.ws, model), want,
                             (m, model))

    def test_kill_switch_env(self):
        think.set_mode(self.ws, "on")
        with mock.patch.dict("os.environ", {"NOVA_THINK": "0"}):
            self.assertFalse(think.enabled())
            self.assertFalse(think.should_force(self.ws, "qwen2.5-coder"))
        with mock.patch.dict("os.environ", {"NOVA_THINK": "1"}):
            self.assertTrue(think.enabled())

    def test_unknown_model_defaults_to_forced(self):
        self.assertTrue(think.should_force(self.ws, None))
        self.assertTrue(think.should_force(self.ws, ""))


class TestForcePrompt(unittest.TestCase):
    def test_carries_both_markers(self):
        p = think.force_prompt("coding")
        self.assertIn(think.THINK_START, p)
        self.assertIn(think.THINK_END, p)

    def test_no_file_protocol_leak(self):
        p = think.force_prompt("talk")
        self.assertNotIn("=== FILE:", p)
        self.assertNotIn("=== EDIT:", p)
        self.assertNotIn("[SEARCH:", p)

    def test_stays_tiny(self):
        # a 4k-token local window must not feel this (~90 tokens)
        self.assertLess(len(think.force_prompt("coding")), 1200)

    def test_sections_named(self):
        self.assertIn("coding agent", think.force_prompt("coding"))
        self.assertIn("chat", think.force_prompt("talk"))


class TestChatTurnIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sess = nova.Session(Path(self._tmp.name))
        self.events = []
        self._old_sink = nova.EVENT_SINK
        nova.EVENT_SINK = self.events.append

    def tearDown(self):
        nova.EVENT_SINK = self._old_sink
        self._tmp.cleanup()
        _reset_web_guards()

    def _run(self, answer, auto=False):
        with mock.patch.object(nova, "stream_chat",
                               return_value=(answer, True)):
            with _quiet():
                return nova.chat_turn(self.sess, "یک ماژول جمع بساز",
                                      auto=auto)

    def test_think_reaches_result_and_event(self):
        answer = ("=== THINK ===\nneed an add function\n"
                  "=== END ===\n=== FILE: m.py ===\n"
                  "def add(a, b):\n    return a + b\n=== END ===")
        with mock.patch.object(nova, "run_command", return_value=0):
            res = self._run(answer, auto=True)
        self.assertIn("need an add function", res.get("think") or "")
        think_evts = [e for e in self.events if e.get("t") == "think"]
        self.assertTrue(think_evts)
        self.assertIn("need an add function", think_evts[0]["text"])
        self.assertFalse(think_evts[0]["native"])

    def test_files_parse_from_clean_answer(self):
        answer = ("=== THINK ===\nplan the module\n"
                  "=== END ===\n=== FILE: m.py ===\n"
                  "def add(a, b):\n    return a + b\n=== END ===")
        with mock.patch.object(nova, "run_command", return_value=0):
            res = self._run(answer, auto=True)
        self.assertIn("m.py", res["files"])

    def test_history_stays_clean(self):
        answer = ("=== THINK ===\nprivate scratchpad\n"
                  "=== END ===\nJust a plain explanation this time.")
        self._run(answer)
        assistant_msgs = [m["content"] for m in self.sess.history
                          if m["role"] == "assistant"]
        self.assertTrue(assistant_msgs)
        self.assertNotIn("private scratchpad", assistant_msgs[-1])
        self.assertIn("plain explanation", assistant_msgs[-1])

    def test_native_reasoner_answer_is_converted(self):
        answer = "<think>step by step plan</think>Final words."
        res = self._run(answer)
        self.assertEqual(res.get("think"), "step by step plan")
        self.assertEqual(res["answer"], "Final words.")
        think_evts = [e for e in self.events if e.get("t") == "think"]
        self.assertTrue(think_evts and think_evts[0]["native"])

    def test_forced_prompt_rides_system_for_weak_brain(self):
        captured = {}

        def fake(model, messages, temperature, sess=None, section=None):
            captured["messages"] = messages
            return ("=== THINK ===\nx\n=== END ===\n"
                    "done - nothing to build"), True

        with mock.patch.object(nova, "stream_chat", side_effect=fake):
            with _quiet():
                nova.chat_turn(self.sess, "سلام، حالت چطوره", auto=False)
        sys_msgs = [m for m in captured["messages"]
                    if m["role"] == "system"]
        self.assertTrue(sys_msgs)
        self.assertIn(think.THINK_START, sys_msgs[0]["content"])

    def test_mode_off_removes_forced_prompt(self):
        think.set_mode(self.sess.ws, "off")
        captured = {}

        def fake(model, messages, temperature, sess=None, section=None):
            captured["messages"] = messages
            return "plain answer", True

        with mock.patch.object(nova, "stream_chat", side_effect=fake):
            with _quiet():
                nova.chat_turn(self.sess, "سلام", auto=False)
        sys_msgs = [m for m in captured["messages"]
                    if m["role"] == "system"]
        self.assertTrue(sys_msgs)
        self.assertNotIn(think.THINK_START, sys_msgs[0]["content"])


class _ServerCase(unittest.TestCase):
    def setUp(self):
        _reset_web_guards()
        self._tmpdir = tempfile.TemporaryDirectory()
        workspace = Path(self._tmpdir.name)
        web_server.STATE = web_server._State(workspace)
        web_server.AUTH_TOKEN = None
        self.httpd = web_server._make_server({"host": "127.0.0.1",
                                              "port": 0})
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self._conns = []
        self.ws = str(workspace)

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

    def _post_talk(self, body):
        c = self.conn()
        c.request("POST", "/api/talk", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return r, _read_ndjson(r)


class TestTalkThinkServerFlow(_ServerCase):
    def _stub(self, captured, text):
        def fake_stream_chat(model, messages, temperature,
                             sess=None, section=None):
            captured["messages"] = messages
            captured["model"] = model
            if nova.TOKEN_SINK:
                nova.TOKEN_SINK(text)
            return text, True
        return fake_stream_chat

    def test_think_event_and_clean_history(self):
        nova.talk_web_set(Path(self.ws), "off")
        captured = {}
        answer = ("=== THINK ===\nthe user greets - answer warmly\n"
                  "=== END ===\nسلام! خوشحالم که اینجایی.")
        with mock.patch.object(nova, "stream_chat",
                               side_effect=self._stub(captured, answer)):
            r, events = self._post_talk({"message": "سلام"})
        self.assertEqual(r.status, 200)
        think_evts = [e for e in events if e.get("t") == "think"]
        self.assertTrue(think_evts)
        self.assertIn("answer warmly", think_evts[0]["text"])
        hist = web_server.STATE.talk_history
        assistant = [m["content"] for m in hist if m["role"] == "assistant"]
        self.assertTrue(assistant)
        self.assertNotIn("answer warmly", assistant[-1])
        self.assertIn("خوشحالم", assistant[-1])

    def test_forced_fragment_rides_system(self):
        nova.talk_web_set(Path(self.ws), "off")
        captured = {}
        with mock.patch.object(nova, "stream_chat",
                               side_effect=self._stub(
                                   captured, "=== THINK ===\ns\n"
                                   "=== END ===\nپاسخ")):
            r, events = self._post_talk({"message": "یه سوال ساده"})
        self.assertEqual(r.status, 200)
        sys_msgs = [m for m in captured["messages"]
                    if m["role"] == "system"]
        self.assertTrue(sys_msgs)
        self.assertIn(think.THINK_START, sys_msgs[0]["content"])

    def test_mode_off_keeps_system_clean(self):
        nova.talk_web_set(Path(self.ws), "off")
        think.set_mode(Path(self.ws), "off")
        captured = {}
        with mock.patch.object(nova, "stream_chat",
                               side_effect=self._stub(captured, "پاسخ")):
            r, events = self._post_talk({"message": "یه سوال ساده"})
        self.assertEqual(r.status, 200)
        sys_msgs = [m for m in captured["messages"]
                    if m["role"] == "system"]
        self.assertTrue(sys_msgs)
        self.assertNotIn(think.THINK_START, sys_msgs[0]["content"])


class TestThinkUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parent.parent
                    / "web" / "index.html").read_text(encoding="utf-8")
        m = re.search(r"<script[^>]*>(.*?)</script>", cls.html, re.S)
        cls.js = m.group(1) if m else ""

    def test_helpers_exist(self):
        for needle in ("function splitThink(", "function renderThinkBox(",
                       "function renderAnswer("):
            self.assertIn(needle, self.js)

    def test_native_tags_handled_client_side_too(self):
        self.assertIn("think|thinking|reasoning|thought", self.js)

    def test_stream_paints_route_through_render_answer(self):
        # both streaming sites (coding tab + talk tab) must use the
        # THINK-aware renderer, never the raw renderMd(acc)
        self.assertNotIn("renderMd(acc)", self.js)
        self.assertGreaterEqual(self.js.count("renderAnswer(acc)"), 2)

    def test_css_present(self):
        for needle in (".thinkbox{", ".thinkbox summary", ".thinkbody"):
            self.assertIn(needle, self.html)

    def test_collapsible_details_used(self):
        self.assertIn('<details class="thinkbox"', self.js)

    def test_no_emoji_added(self):
        bad = [c for c in self.html
               if 0x1F000 <= ord(c) <= 0x1FAFF or ord(c) in
               (0x2728, 0x2705, 0x274C, 0x26A1, 0x2B50)]
        self.assertFalse(bad)


class TestThinkCommandRegistered(unittest.TestCase):
    def test_command_in_table(self):
        cmds = [c.get("cmd") for c in nova.TOOLS]
        self.assertIn("/think", cmds)

    def test_command_help_groups(self):
        flat = [c for _, _, cs in nova.HELP_GROUPS for c in cs]
        self.assertIn("/think", flat)

    def test_version_is_7140(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(think.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
