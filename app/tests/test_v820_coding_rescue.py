#!/usr/bin/env python3
"""v8.2 tests: THE CUT-ANSWER RESCUE for the coding section.

The user's report: "یک مدل 4b با قدرت تفکر ... وسط کد نویسی قطع میشد و
نوا ارور می‌داد که هوش مصنوعی بلاک شده چون ==end== نداره" - a thinking
model got cut mid-code and Nova answered 'empty answer' because the
=== END === closer never came. The user added: "تمام مدل ها خودکار
==end== رو جا میذارن" - every weak model forgets the closer.

Pinned here (the whole possible/impossible coding matrix):
  - extract() salvage: an OPEN think block that carries REAL WORK
    (unclosed FILE/EDIT header, code fence, tool token) keeps the work -
    the prose becomes the think box (salvaged=True, open=False)
  - the v7.14 law still holds: a COMPLETE quoted file example inside an
    open think block never leaks into the answer
  - native <think> open blocks salvage the same way
  - NOVA_THINK=0 does not disable the salvage (protocol hygiene)
  - the salvaged answer parses into real files through parse_files
  - _resume_tail / _resume_message: tail cap, request anchor, the
    === END === guidance in the instruction
  - chat_turn integration (mocked stream_chat):
      * open think + no work -> ONE auto-continue round, merged raw,
        re-extracted, files applied from the continuation
      * truncated mid-file (complete=False) + salvaged half file ->
        continuation completes the file content on disk
      * a clean complete answer -> NO continuation call
      * NOVA_AUTO_CONTINUE=0 disables the rescue
      * a hard stream error (_LAST_STREAM_HARD) blocks the rescue
      * the resume message carries the raw tail
  - stream_chat (fake Ollama wire): done_reason=length -> complete=False,
    done_reason=stop -> complete=True, a mid-stream Ollama error sets
    _LAST_STREAM_HARD, the cloud finish_reason=length contract
  - nova_providers finish-reason capture (openai / anthropic / gemini
    parse helpers + the stream_chunks reset)
  - the coding scenario matrix: unclosed FILE + Run hint, unclosed EDIT,
    first block forgot END + second complete, quoted END inside a file
    body, CRLF answers, fence-wrapped answer, an open-think-only answer
    produces no files (honest, never fake work)
  - UI pins: the client splitThink salvage (workRe) exists, renderAnswer
    still owns the paint sites
  - version 8.11.0
Everything is offline-deterministic (the model call is stubbed).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_think as think  # noqa: E402
import nova_providers as providers  # noqa: E402
import web_server  # noqa: E402


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


# --------------------------------------------------------------- extraction
class TestMarkerSalvage(unittest.TestCase):
    def test_open_think_with_unclosed_file_is_salvaged(self):
        raw = ("=== THINK ===\nI will build the site\n"
               "=== FILE: index.html ===\n<h1>hi</h1>\n")
        r = think.extract(raw)
        self.assertTrue(r.get("salvaged"))
        self.assertFalse(r["open"])
        self.assertTrue(r["answer"].startswith("=== FILE: index.html ==="))
        self.assertIn("I will build the site", r["think"])

    def test_open_think_prose_only_stays_open(self):
        r = think.extract("=== THINK ===\nstill thinking about the plan and")
        self.assertTrue(r["open"])
        self.assertEqual(r["answer"], "")
        self.assertFalse(r.get("salvaged"))

    def test_quoted_complete_file_inside_open_think_never_leaks(self):
        # the v7.14 law: a COMPLETE example file stays reasoning
        raw = ("=== THINK ===\nI could write\n=== FILE: evil.py ===\n"
               "but that stays in my head\n=== END ===\nDone explaining.")
        r = think.extract(raw)
        self.assertNotIn("evil.py", r["answer"])
        self.assertTrue(r["open"])

    def test_quoted_example_then_real_unclosed_file_salvages_the_real_one(self):
        raw = ("=== THINK ===\nfor example:\n=== FILE: ex.py ===\n"
               "print('demo')\n=== END ===\n"
               "=== FILE: real.py ===\nprint('real')")
        r = think.extract(raw)
        self.assertTrue(r.get("salvaged"))
        self.assertTrue(r["answer"].startswith("=== FILE: real.py ==="))
        self.assertNotIn("ex.py", r["answer"])

    def test_open_think_with_fence_is_salvaged(self):
        raw = "=== THINK ===\nthe plan:\n```html\n<html><body>x</body></html>\n"
        r = think.extract(raw)
        self.assertTrue(r.get("salvaged"))
        self.assertTrue(r["answer"].startswith("```html"))

    def test_open_think_with_tool_token_is_salvaged(self):
        raw = "=== THINK ===\nI need data first\n[SEARCH: python requests]\n"
        r = think.extract(raw)
        self.assertTrue(r.get("salvaged"))
        self.assertTrue(r["answer"].startswith("[SEARCH:"))

    def test_closed_think_has_no_salvage_flag(self):
        raw = "=== THINK ===\nplan\n=== END ===\n=== FILE: a.py ===\nx=1\n=== END ==="
        r = think.extract(raw)
        self.assertFalse(r["open"])
        self.assertFalse(r.get("salvaged"))
        self.assertTrue(r["answer"].startswith("=== FILE: a.py ==="))

    def test_open_edit_header_is_salvaged(self):
        raw = ("=== THINK ===\np\n=== EDIT: app.py ===\n"
               "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n")
        r = think.extract(raw)
        self.assertTrue(r.get("salvaged"))
        self.assertTrue(r["answer"].startswith("=== EDIT: app.py ==="))

    def test_crlf_answer_still_salvages(self):
        raw = ("=== THINK ===\r\nplan\r\n=== FILE: a.py ===\r\nx=1\r\n")
        r = think.extract(raw.replace("=== END ===", "__none__"))
        self.assertTrue(r.get("salvaged"))
        self.assertIn("x=1", r["answer"])

    def test_salvaged_answer_parses_into_real_files(self):
        raw = ("=== THINK ===\nbuilding\n=== FILE: m.py ===\n"
               "def add(a, b):\n    return a + b\n")
        r = think.extract(raw)
        files, unnamed = nova.parse_files(r["answer"])
        self.assertEqual([f[0] for f in files], ["m.py"])
        self.assertIn("return a + b", files[0][1])

    def test_kill_switch_keeps_salvage(self):
        # NOVA_THINK=0 kills the FORCED prompt - native capture (and the
        # v8.2 salvage that protects its work) must stay on
        raw = "<think>plan\n=== FILE: a.py ===\nx=1\n"
        with mock.patch.dict("os.environ", {"NOVA_THINK": "0"}):
            r = think.extract(raw)
        self.assertTrue(r.get("salvaged"))


class TestNativeSalvage(unittest.TestCase):
    def test_native_open_with_file_is_salvaged(self):
        raw = "<think>reasoning here\n=== FILE: a.py ===\nprint(1)\n"
        r = think.extract(raw)
        self.assertTrue(r.get("salvaged"))
        self.assertTrue(r["native"])
        self.assertTrue(r["answer"].startswith("=== FILE: a.py ==="))
        self.assertIn("reasoning here", r["think"])

    def test_native_open_prose_only_stays_open(self):
        r = think.extract("<think>half a reasoning that got cut")
        self.assertTrue(r["open"])
        self.assertEqual(r["answer"], "")

    def test_native_open_quoted_complete_file_stays_reasoning(self):
        raw = ("<think>I could show\n=== FILE: ex.py ===\nprint(1)\n"
               "=== END ===\nmore thinking")
        r = think.extract(raw)
        self.assertNotIn("ex.py", r["answer"])

    def test_native_closed_untouched(self):
        raw = "<think>plan</think>answer text"
        r = think.extract(raw)
        self.assertEqual(r["answer"], "answer text")
        self.assertFalse(r["open"])


# --------------------------------------------------------------- resume
class TestResumeHelpers(unittest.TestCase):
    def test_resume_tail_caps(self):
        raw = "x" * 5000
        t = nova._resume_tail(raw, cap=100)
        self.assertEqual(len(t), 100)
        self.assertEqual(nova._resume_tail("", cap=10), "")
        self.assertEqual(nova._resume_tail("abc", cap=100), "abc")

    def test_resume_message_carries_tail_and_instruction(self):
        msg = nova._resume_message("=== FILE: index.html ===\n<h1>cu",
                                   "یک سایت کافه بساز")
        self.assertIn("<h1>cu", msg)
        self.assertIn("یک سایت کافه بساز", msg)
        self.assertIn("=== END ===", msg)
        self.assertIn("Continue EXACTLY", msg)

    def test_resume_message_caps_request(self):
        msg = nova._resume_message("tail", "r" * 500)
        self.assertIn("r" * 300 + "...", msg)
        self.assertNotIn("r" * 400, msg)

    def test_resume_tail_is_the_actual_end(self):
        raw = "HEAD\n" + "mid\n" * 500 + "THE_CUT_POINT"
        self.assertTrue(nova._resume_tail(raw).endswith("THE_CUT_POINT"))


# --------------------------------------------------------------- chat_turn
class TestChatTurnRescue(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sess = nova.Session(Path(self._tmp.name))
        self.events = []
        self._old_sink = nova.EVENT_SINK
        nova.EVENT_SINK = self.events.append
        self._old_hard = nova._LAST_STREAM_HARD
        nova._LAST_STREAM_HARD = False
        # v8.4: the code guardian's post-apply fleet review adds ONE
        # deliberate local model call per applied file. These tests
        # count stream_chat calls for the RESCUE loop itself, so the
        # fleet is parked at the documented kill-switch here.
        # v8.5: the bug hunter's completeness probe adds ONE more -
        # parked at its own kill-switch likewise.
        self._env_patcher = mock.patch.dict(
            "os.environ", {"NOVA_GUARDIAN": "0", "NOVA_PROBE": "0"})
        self._env_patcher.start()

    def tearDown(self):
        self._env_patcher.stop()
        nova.EVENT_SINK = self._old_sink
        nova._LAST_STREAM_HARD = self._old_hard
        self._tmp.cleanup()
        _reset_web_guards()

    def _run(self, answers, auto=True, env=None):
        """stream_chat returns each answer in order (the last one repeats)."""
        seq = list(answers)

        def fake(model, messages, temperature, sess=None, section=None,
                 quiet=False):
            captured.setdefault("calls", []).append(
                [dict(m) for m in messages])
            if len(seq) > 1:
                return seq.pop(0), False
            return seq[0], True

        captured = {}
        with mock.patch.dict("os.environ",
                             env or {}, clear=False):
            with mock.patch.object(nova, "stream_chat",
                                   side_effect=fake):
                with _quiet():
                    res = nova.chat_turn(self.sess, "یک کافه بساز",
                                         auto=auto)
        return res, captured

    def test_open_think_empty_answer_triggers_one_continue(self):
        first = "=== THINK ===\nlet me plan the cafe site step by"
        second = ("step\n=== END ===\n=== FILE: index.html ===\n"
                  "<h1>کافه</h1>\n=== END ===\nPreview: index.html")
        res, cap = self._run([first, second])
        self.assertEqual(len(cap["calls"]), 2, "exactly ONE continuation")
        self.assertIn("index.html", res["files"])
        self.assertIn("let me plan", res.get("think") or "")

    def test_resume_message_carries_the_raw_tail(self):
        first = "=== THINK ===\n" + "x" * 300
        second = "more\n=== END ===\nAll done."
        res, cap = self._run([first, second])
        second_msgs = cap["calls"][1]
        user_texts = [m["content"] for m in second_msgs
                      if m["role"] == "user"]
        self.assertTrue(any("xxxx" in t for t in user_texts),
                        "the tail of the cut answer must ride along")

    def test_truncated_half_file_gets_completed(self):
        half = ("=== THINK ===\nplan\n=== END ===\n"
                "=== FILE: m.py ===\ndef add(a, b):")
        rest = ("\n    return a + b\n=== END ===\nPreview: m.py")
        with mock.patch.object(nova, "run_command", return_value=0):
            res, cap = self._run([half, rest])
        self.assertEqual(len(cap["calls"]), 2)
        self.assertIn("m.py", res["files"])
        on_disk = (self.sess.ws / "m.py").read_text(encoding="utf-8")
        self.assertIn("return a + b", on_disk)

    def test_clean_complete_answer_never_continues(self):
        good = ("=== FILE: a.py ===\nx=1\n=== END ===\nRun: python a.py")
        res, cap = self._run([good])
        self.assertEqual(len(cap["calls"]), 1)
        self.assertIn("a.py", res["files"])

    def test_open_think_with_salvaged_work_does_not_continue(self):
        # the stream said 'done' but the model forgot === END === after
        # starting the file - the salvage already recovered it, no extra
        # generation is spent
        raw = ("=== THINK ===\nplan\n=== FILE: a.py ===\nx=1\n")
        res, cap = self._run([raw])
        self.assertEqual(len(cap["calls"]), 1)
        self.assertIn("a.py", res["files"])

    def test_auto_continue_env_zero_disables_rescue(self):
        first = "=== THINK ===\nstill planning the whole thing"
        res, cap = self._run([first, "more"], env={"NOVA_AUTO_CONTINUE": "0"})
        self.assertEqual(len(cap["calls"]), 1)
        self.assertEqual(res["answer"], "")

    def test_hard_stream_error_blocks_rescue(self):
        first = "=== THINK ===\nstill planning"
        nova._LAST_STREAM_HARD = True   # as stream_chat sets on [ollama error]
        res, cap = self._run([first, "more"])
        self.assertEqual(len(cap["calls"]), 1)

    def test_rescue_budget_is_capped_at_two(self):
        seq = ["=== THINK ===\ncut one",
               "=== THINK ===\ncut two",
               "=== THINK ===\ncut three"]

        def fake(model, messages, temperature, sess=None, section=None,
                 quiet=False):
            if len(seq) > 1:
                return seq.pop(0), False
            return seq[0], False

        with mock.patch.object(nova, "stream_chat", side_effect=fake):
            with _quiet():
                res = nova.chat_turn(self.sess, "بساز", auto=True)
        # first call + 2 continuations = 3 total, never more
        self.assertEqual(res["answer"], "")
        self.assertFalse(res.get("complete"))

    def test_think_event_fires_once_after_rescue(self):
        first = "=== THINK ===\ncut mid reasoning"
        second = "more\n=== END ===\nplain final answer"
        res, cap = self._run([first, second])
        think_evts = [e for e in self.events if e.get("t") == "think"]
        self.assertEqual(len(think_evts), 1)
        self.assertIn("cut mid reasoning", think_evts[0]["text"])

    def test_history_gets_the_merged_clean_answer(self):
        first = "=== THINK ===\ncut"
        second = "=== END ===\nThe site is ready."
        self._run([first, second])
        assistant = [m["content"] for m in self.sess.history
                     if m["role"] == "assistant"]
        self.assertTrue(assistant)
        self.assertNotIn("=== THINK ===", assistant[-1])
        self.assertIn("The site is ready.", assistant[-1])

    def test_complete_flag_is_honest_after_rescue(self):
        first = "=== THINK ===\ncut"
        second = "=== END ===\nfinal"
        res, cap = self._run([first, second])
        # the mocked last call reports complete=True
        self.assertTrue(res.get("complete"))


# --------------------------------------------------------------- stream_chat
class _FakeResp:
    def __init__(self, lines):
        self._lines = [l if isinstance(l, bytes) else l.encode()
                       for l in lines]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


class TestStreamChatDoneReason(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nova_rescue_"))
        self.sess = nova.Session(self.tmp)
        self._old_urlopen = nova.urllib.request.urlopen

    def tearDown(self):
        nova.urllib.request.urlopen = self._old_urlopen
        self._old_hard = getattr(nova, "_LAST_STREAM_HARD", False)
        nova._LAST_STREAM_HARD = False
        nova._LOCAL_SCAN.update(at=0.0, key=None, list=[])

    def _stream(self, lines):
        def fake_urlopen(req, timeout=None):
            return _FakeResp(lines)
        nova.urllib.request.urlopen = fake_urlopen
        with _quiet():
            return nova.stream_chat(nova.DEFAULT_MODEL,
                                    [{"role": "user", "content": "p"}],
                                    0.4, sess=self.sess, section="coding")

    def test_done_reason_length_is_incomplete(self):
        text, complete = self._stream([
            json.dumps({"message": {"content": "=== FILE: a.py ===\nx="}}),
            json.dumps({"message": {"content": ""}, "done": True,
                        "done_reason": "length",
                        "prompt_eval_count": 1, "eval_count": 2})])
        self.assertFalse(complete, "a length-cut answer is NOT complete")
        self.assertIn("=== FILE:", text)

    def test_done_reason_stop_is_complete(self):
        text, complete = self._stream([
            json.dumps({"message": {"content": "hello"}}),
            json.dumps({"message": {"content": ""}, "done": True,
                        "done_reason": "stop",
                        "prompt_eval_count": 1, "eval_count": 2})])
        self.assertTrue(complete)

    def test_missing_done_reason_defaults_complete(self):
        _t, complete = self._stream([
            json.dumps({"message": {"content": "hello"}}),
            json.dumps({"message": {"content": ""}, "done": True})])
        self.assertTrue(complete)

    def test_ollama_error_sets_hard_flag(self):
        _t, complete = self._stream([
            json.dumps({"message": {"content": "par"}}),
            json.dumps({"error": "model requires more system memory"})])
        self.assertFalse(complete)
        self.assertTrue(nova._LAST_STREAM_HARD)


class TestProvidersFinishReason(unittest.TestCase):
    def tearDown(self):
        providers.LAST_FINISH_REASON = ""

    def test_openai_length(self):
        providers._openai_parse(json.dumps({
            "choices": [{"delta": {}, "finish_reason": "length"}]}), None)
        self.assertEqual(providers.LAST_FINISH_REASON, "length")

    def test_openai_stop(self):
        providers._openai_parse(json.dumps({
            "choices": [{"delta": {}, "finish_reason": "stop"}]}), None)
        self.assertEqual(providers.LAST_FINISH_REASON, "stop")

    def test_anthropic_max_tokens(self):
        providers._anthropic_parse(json.dumps({
            "type": "message_delta",
            "delta": {"stop_reason": "max_tokens"},
            "usage": {"output_tokens": 5}}), None)
        self.assertEqual(providers.LAST_FINISH_REASON, "length")

    def test_gemini_max_tokens(self):
        providers._gemini_parse(json.dumps({
            "candidates": [{"finishReason": "MAX_TOKENS",
                            "content": {"parts": []}}]}), None)
        self.assertEqual(providers.LAST_FINISH_REASON, "length")

    def test_stream_chunks_resets_the_flag(self):
        providers.LAST_FINISH_REASON = "length"

        class _ErrCfg(dict):
            pass
        with self.assertRaises(providers.ProviderError):
            with _quiet():
                list(providers.stream_chunks(
                    {"kind": "nope", "name": "x"}, "m",
                    [{"role": "user", "content": "p"}], 0.2))
        self.assertEqual(providers.LAST_FINISH_REASON, "",
                         "stream_chunks resets the flag at entry")


# --------------------------------------------------------------- the matrix
class TestCodingScenarioMatrix(unittest.TestCase):
    """Every 'possible and impossible' coding shape the parser must
    survive - the user asked for the whole matrix, not just the happy
    path. Each case lists the raw model answer shape."""

    def _parse(self, raw):
        return nova.parse_files(raw), nova.parse_edits(raw)

    def test_unclosed_file_at_end_of_answer(self):
        (files, unnamed), _e = self._parse(
            "=== FILE: index.html ===\n<html>body</html>")
        self.assertEqual(files[0][0], "index.html")
        self.assertIn("<html>", files[0][1])

    def test_unclosed_file_followed_by_run_hint(self):
        (files, unnamed), _e = self._parse(
            "=== FILE: app.py ===\nprint('x')\nRun: python app.py")
        self.assertEqual(files[0][0], "app.py")
        self.assertNotIn("Run:", files[0][1])

    def test_unclosed_edit_recovered(self):
        _f, edits = self._parse(
            "=== EDIT: a.py ===\n<<<<<<< SEARCH\nold\n=======\nnew\n"
            ">>>>>>> REPLACE\n")
        self.assertEqual(len(edits[0][1]), 1)

    def test_first_block_forgot_end_second_complete(self):
        (files, _u), _e = self._parse(
            "=== FILE: a.py ===\nx=1\n=== FILE: b.py ===\ny=2\n=== END ===\n")
        names = [f[0] for f in files]
        self.assertIn("a.py", names)
        self.assertIn("b.py", names)
        self.assertEqual(dict(files)["b.py"].strip(), "y=2")

    def test_quoted_end_inside_file_body_stays_content(self):
        (files, _u), _e = self._parse(
            "=== FILE: x.py ===\nprint('=== END ===')\n=== END ===\n")
        self.assertIn("=== END ===", files[0][1])

    def test_crlf_answer_writes_lf_files(self):
        (files, _u), _e = self._parse(
            "=== FILE: a.py ===\r\nx=1\r\ny=2\r\n=== END ===\r\n")
        self.assertNotIn("\r", files[0][1])

    def test_fence_wrapped_whole_answer(self):
        (files, _u), _e = self._parse(
            "```html\n=== FILE: index.html ===\n<h1>x</h1>\n=== END ===\n```")
        self.assertEqual(files[0][0], "index.html")

    def test_open_think_only_answer_has_no_files(self):
        # honest: a pure reasoning cut produces NOTHING - the rescue loop
        # (not the parser) is what recovers the turn
        raw = "=== THINK ===\nstill planning the whole site"
        with mock.patch.object(think, "extract", think.extract):
            r = think.extract(raw)
        self.assertEqual(r["answer"], "")
        files, _unnamed = nova.parse_files(r["answer"])
        self.assertEqual(files, [])

    def test_salvaged_marker_answer_fully_applies(self):
        raw = ("=== THINK ===\nplan\n=== FILE: index.html ===\n"
               "<h1>کافه نوا</h1>\n=== FILE: styles.css ===\n"
               "body{margin:0}\n")
        r = think.extract(raw)
        (files, _u), _e = self._parse(r["answer"])
        self.assertEqual([f[0] for f in files],
                         ["index.html", "styles.css"])


# --------------------------------------------------------------- UI pins
class TestUIPins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parent.parent
                    / "web" / "index.html").read_text(encoding="utf-8")
        import re as _re
        m = _re.search(r"<script[^>]*>(.*?)</script>", cls.html, _re.S)
        cls.js = m.group(1) if m else ""

    def test_client_salvage_exists(self):
        self.assertIn("workRe", self.js)
        self.assertIn("salvage", self.js)

    def test_render_answer_still_owns_paint(self):
        self.assertNotIn("renderMd(acc)", self.js)
        self.assertGreaterEqual(self.js.count("renderAnswer(acc)"), 2)

    def test_native_tags_still_handled_client_side(self):
        self.assertIn("think|thinking|reasoning|thought", self.js)


class TestWebServerRescuePins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (Path(__file__).resolve().parent.parent
                   / "web_server.py").read_text(encoding="utf-8")

    def test_talk_rescue_wired(self):
        self.assertIn("_resume_message", self.src)
        self.assertIn("_talk_cut", self.src)


# --------------------------------------------------------------- versions
class TestVersions(unittest.TestCase):
    def test_nova_version(self):
        self.assertEqual(nova.VERSION, "8.12.0")

    def test_think_version(self):
        self.assertEqual(think.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
