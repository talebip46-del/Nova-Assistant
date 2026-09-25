#!/usr/bin/env python3
"""v7.12 tests: WEB SEARCH IN THE SIMPLE CHAT (the user's ask: "توی چت
معمولی هم باید سرچ وب داشته باشیم").

Pinned here:
  - talk_needs_web heuristic (fa/en triggers, years, phatic lines, modes)
  - talk_web_query / talk_web_block formatting (caps, empty results)
  - the per-workspace mode file (auto default, corrupt-file fail-soft,
    atomic persistence, invalid mode rejected)
  - the server flow: {t:"web"} event, [WEB RESULTS] block riding msgs[1]
    and NEVER entering talk_history, fail-soft on search errors
  - talk-side commands /web and /search (no model call for /web)
  - GET /api/talk/web + the request-body mode flip
  - the UI pins (segmented control, source chips, send body carries the
    mode) and the version
Everything network-dependent is stubbed (nova.ns.web_search) - the suite
stays offline-deterministic.
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


FA_RESULTS = [
    {"title": "قیمت دلار - بانک مرکزی", "url": "https://www.cbi.ir/page/x",
     "snippet": "نرخ امروز دلار در بازار آزاد"},
    {"title": "دلار امروز - ایسنا", "url": "https://www.isna.ir/dollar",
     "snippet": "قیمت دلار امروز بازار"},
    {"title": "Wikipedia Dollar", "url": "https://en.wikipedia.org/wiki/Dollar",
     "snippet": "The dollar is a currency."},
]


# =====================================================================
# 1. the heuristic (pure)
# =====================================================================
class TestTalkNeedsWeb(unittest.TestCase):
    def test_version_is_7120(self):
        self.assertEqual(nova.VERSION, "8.12.0")

    def test_fa_price_and_news_trigger(self):
        self.assertTrue(nova.talk_needs_web("قیمت دلار امروز چنده؟"))
        self.assertTrue(nova.talk_needs_web("آخرین اخبار فوتبال ایران رو بگو"))

    def test_fa_zwnj_spelling_triggers(self):
        # جست‌وجو contains ZWNJ; the normalized form must match
        self.assertTrue(nova.talk_needs_web("لطفا جست‌وجو کن درباره پایتون"))

    def test_fa_spaced_spelling_triggers(self):
        self.assertTrue(nova.talk_needs_web("جست و جو کن: بهترین لپتاپ ۲۰۲۶"))

    def test_explicit_search_verbs_trigger(self):
        self.assertTrue(nova.talk_needs_web("سرچ کن مدل جدید openai"))
        self.assertTrue(nova.talk_needs_web("برام پیدا کن بهترین لپتاپ"))

    def test_weather_triggers(self):
        self.assertTrue(nova.talk_needs_web("هواشناسی تهران فردا چطوره؟"))
        self.assertTrue(nova.talk_needs_web("what is the weather in Tehran"))

    def test_forward_years_trigger(self):
        self.assertTrue(nova.talk_needs_web("what happens in 2026 with AI"))
        self.assertTrue(nova.talk_needs_web("تقویم سال ۱۴۰۴ چیه"))

    def test_greetings_and_normal_chat_stay_quiet(self):
        for msg in ("سلام", "چطوری؟", "مرسی", "خوبی؟", "یه جوک بگو",
                    "REST و GraphQL چه تفاوتی دارن؟",
                    "یه شعر کوتاه درباره دریا بگو"):
            self.assertFalse(nova.talk_needs_web(msg), msg)

    def test_min_length_guard(self):
        self.assertFalse(nova.talk_needs_web("قیمت؟"))   # too short to trust

    def test_slash_commands_never_trigger(self):
        self.assertFalse(nova.talk_needs_web("/web off"))
        self.assertFalse(nova.talk_needs_web("/search قیمت دلار"))

    def test_modes_off_and_always(self):
        self.assertFalse(nova.talk_needs_web("قیمت دلار", mode="off"))
        self.assertTrue(nova.talk_needs_web("سلام", mode="always"))

    def test_persian_digits_fold(self):
        t = nova._talk_web_norm("قیمت ۱۲۳")
        self.assertIn("123", t)
        t2 = nova._talk_web_norm("جست‌وجو")
        self.assertNotIn("\u200c", t2)


# =====================================================================
# 2. query + block formatting (pure)
# =====================================================================
class TestTalkWebQueryAndBlock(unittest.TestCase):
    def test_query_collapses_and_strips_markdown(self):
        q = nova.talk_web_query("  **قیمت**  دلار\n   امروز؟  ")
        self.assertEqual(q, "قیمت دلار امروز؟")

    def test_query_capped_on_word_boundary(self):
        q = nova.talk_web_query("word " * 60)
        self.assertLessEqual(len(q), nova.TALK_WEB_QUERY_CAP)
        self.assertFalse(q.endswith(" "))   # cut at a space, not mid-word

    def test_block_numbered_with_urls(self):
        b = nova.talk_web_block("q", FA_RESULTS)
        self.assertIn("[WEB RESULTS - query: q - 3 results]", b)
        self.assertIn("1. قیمت دلار - بانک مرکزی", b)
        self.assertIn("https://www.isna.ir/dollar", b)
        self.assertIn("cite them inline like [1], [2]", b)

    def test_block_empty_results_is_empty(self):
        self.assertEqual(nova.talk_web_block("q", []), "")
        self.assertEqual(nova.talk_web_block("q", [{"url": ""}]), "")

    def test_block_caps_results_and_snippet(self):
        many = [{"title": "t%d" % i, "url": "https://a.ir/%d" % i,
                 "snippet": "s" * 500} for i in range(12)]
        b = nova.talk_web_block("q", many)
        self.assertEqual(b.count("https://a.ir/"), nova.TALK_WEB_MAX_RESULTS)
        self.assertNotIn("s" * 400, b)   # snippets truncated

    def test_block_skips_urlless_rows(self):
        b = nova.talk_web_block("q", [{"title": "no url", "snippet": "x"},
                                      FA_RESULTS[0]])
        self.assertIn("1. قیمت دلار", b)   # renumbered, junk skipped


# =====================================================================
# 3. the mode file (per workspace)
# =====================================================================
class TestTalkWebModeFile(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def test_default_is_auto(self):
        self.assertEqual(nova.talk_web_get(self.ws), "auto")

    def test_set_and_get_roundtrip(self):
        for m in nova.TALK_WEB_MODES:
            self.assertEqual(nova.talk_web_set(self.ws, m), m)
            self.assertEqual(nova.talk_web_get(self.ws), m)

    def test_set_rejects_junk(self):
        with self.assertRaises(ValueError):
            nova.talk_web_set(self.ws, "junk")
        with self.assertRaises(ValueError):
            nova.talk_web_set(self.ws, "")

    def test_corrupt_file_degrades_to_auto(self):
        p = nova.talk_web_path(self.ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")
        self.assertEqual(nova.talk_web_get(self.ws), "auto")

    def test_wrong_value_degrades_to_auto(self):
        p = nova.talk_web_path(self.ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"mode": "turbo"}), encoding="utf-8")
        self.assertEqual(nova.talk_web_get(self.ws), "auto")

    def test_web_talk_state_payload(self):
        nova.talk_web_set(self.ws, "always")
        st = nova.web_talk_state(type("S", (), {"ws": self.ws})())
        self.assertEqual(st["mode"], "always")
        self.assertEqual(st["modes"], ["off", "auto", "always"])
        self.assertEqual(st["default"], "auto")


# =====================================================================
# 4. the server flow (real server, stubbed brain + search)
# =====================================================================
class _ServerCase(unittest.TestCase):
    def setUp(self):
        _reset_web_guards()
        self._tmpdir = tempfile.TemporaryDirectory()
        workspace = Path(self._tmpdir.name)
        web_server.STATE = web_server._State(workspace)
        web_server.AUTH_TOKEN = None
        self.httpd = web_server._make_server({"host": "127.0.0.1", "port": 0})
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

    def _get(self, path):
        c = self.conn()
        c.request("GET", path)
        r = c.getresponse()
        return r, json.loads(r.read().decode("utf-8"))


class TestTalkWebServerFlow(_ServerCase):
    def _stub_brain(self, captured, text="پاسخ آزمایشی"):
        def fake_stream_chat(model, messages, temperature,
                             sess=None, section=None):
            captured["messages"] = messages
            captured["section"] = section
            if nova.TOKEN_SINK:
                nova.TOKEN_SINK(text)
            return text, True
        return fake_stream_chat

    def test_get_talk_web_mode_default_auto(self):
        r, data = self._get("/api/talk/web")
        self.assertEqual(r.status, 200)
        self.assertEqual(data["mode"], "auto")
        self.assertEqual(data["modes"], ["off", "auto", "always"])

    def test_request_body_flips_and_persists_mode(self):
        captured = {}
        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  self._stub_brain(captured)), \
                mock.patch.object(web_server.nova.ns, "web_search",
                                  lambda q, max_results=6, **kw: FA_RESULTS):
            # mode=always searches even a greeting - the stub keeps the
            # suite offline-deterministic (never a real network call)
            r, _ = self._post_talk({"message": "سلام",
                                    "web": "always"})
        self.assertEqual(r.status, 200)
        self.assertEqual(nova.talk_web_get(self.ws), "always")
        # the next turn WITHOUT the field keeps the persisted mode
        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  self._stub_brain(captured)), \
                mock.patch.object(web_server.nova.ns, "web_search",
                                  lambda q, max_results=6, **kw: FA_RESULTS):
            self._post_talk({"message": "سلام"})
        self.assertEqual(nova.talk_web_get(self.ws), "always")

    def test_off_mode_never_searches(self):
        events = []

        def fake_search(q, max_results=6, **kw):
            events.append("searched")
            return FA_RESULTS

        captured = {}
        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  self._stub_brain(captured)), \
                mock.patch.object(web_server.nova.ns, "web_search",
                                  fake_search):
            r, evs = self._post_talk({"message": "قیمت دلار امروز چنده؟",
                                      "web": "off"})
        self.assertEqual(r.status, 200)
        self.assertEqual(events, [])                  # never searched
        self.assertEqual([e for e in evs if e.get("t") == "web"], [])
        self.assertEqual(len(captured["messages"]), 2)  # system + user only

    def test_auto_mode_searches_fresh_facts_and_injects_block(self):
        captured = {}
        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  self._stub_brain(captured)), \
                mock.patch.object(web_server.nova.ns, "web_search",
                                  lambda q, max_results=6, **kw: FA_RESULTS):
            r, evs = self._post_talk({"message": "قیمت دلار امروز چنده؟"})
        self.assertEqual(r.status, 200)
        msgs = captured["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("SIMPLE CHAT", msgs[0]["content"])
        self.assertEqual(len(msgs), 3)                # sys + web block + user
        self.assertEqual(msgs[1]["role"], "system")
        self.assertIn("[WEB RESULTS", msgs[1]["content"])
        self.assertIn("cbi.ir", msgs[1]["content"])
        web_evs = [e for e in evs if e.get("t") == "web"]
        self.assertEqual(len(web_evs), 1)
        self.assertEqual(web_evs[0]["query"], "قیمت دلار امروز چنده؟")
        self.assertEqual(web_evs[0]["results"][0]["url"],
                         "https://www.cbi.ir/page/x")
        # the block NEVER enters the talk history
        hist = web_server.STATE.talk_history
        self.assertEqual(len(hist), 2)
        blob = json.dumps(hist, ensure_ascii=False)
        self.assertNotIn("WEB RESULTS", blob)
        self.assertNotIn("cbi.ir", blob)

    def test_auto_mode_greeting_skips_the_search(self):
        captured = {}
        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  self._stub_brain(captured)), \
                mock.patch.object(web_server.nova.ns, "web_search",
                                  side_effect=AssertionError("must not run")):
            r, evs = self._post_talk({"message": "سلام"})
        self.assertEqual(r.status, 200)
        self.assertEqual(len(captured["messages"]), 2)   # no web block

    def test_search_failure_is_fail_soft(self):
        captured = {}

        def boom(q, max_results=6, **kw):
            raise RuntimeError("duckduckgo rate limit - use a fallback")

        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  self._stub_brain(captured)), \
                mock.patch.object(web_server.nova.ns, "web_search", boom):
            r, evs = self._post_talk({"message": "قیمت دلار امروز چنده؟"})
        self.assertEqual(r.status, 200)
        toks = "".join(e["text"] for e in evs if e.get("t") == "tok")
        self.assertEqual(toks, "پاسخ آزمایشی")        # the answer survives
        self.assertEqual([e for e in evs if e.get("t") == "web"], [])
        notes = [e["text"] for e in evs if e.get("t") == "note"]
        self.assertTrue(any("جست‌وجو ناموفق" in n for n in notes))
        self.assertEqual(len(captured["messages"]), 2)   # no block

    def test_web_command_flips_mode_without_a_model_call(self):
        called = []

        def must_not_call(*a, **kw):
            called.append(1)
            return "", False

        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  must_not_call):
            r, evs = self._post_talk({"message": "/web off"})
        self.assertEqual(r.status, 200)
        self.assertEqual(called, [])
        self.assertEqual(nova.talk_web_get(self.ws), "off")
        modes = [e for e in evs if e.get("t") == "webmode"]
        self.assertEqual(len(modes), 1)
        self.assertEqual(modes[0]["mode"], "off")

    def test_web_command_bare_shows_current_mode(self):
        nova.talk_web_set(self.ws, "always")
        called = []

        def must_not_call(*a, **kw):
            called.append(1)
            return "", False

        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  must_not_call):
            r, evs = self._post_talk({"message": "/web"})
        self.assertEqual(r.status, 200)
        self.assertEqual(called, [])
        modes = [e for e in evs if e.get("t") == "webmode"]
        self.assertEqual(len(modes), 1)
        self.assertEqual(modes[0]["mode"], "always")

    def test_search_command_answers_without_the_model(self):
        called = []

        def must_not_call(*a, **kw):
            called.append(1)
            return "", False

        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  must_not_call), \
                mock.patch.object(web_server.nova.ns, "web_search",
                                  lambda q, max_results=6, **kw: FA_RESULTS):
            r, evs = self._post_talk({"message": "/search قیمت دلار"})
        self.assertEqual(r.status, 200)
        self.assertEqual(called, [])
        web_evs = [e for e in evs if e.get("t") == "web"]
        self.assertEqual(len(web_evs), 1)
        toks = "".join(e["text"] for e in evs if e.get("t") == "tok")
        self.assertIn("نتایج وب برای «قیمت دلار»", toks)
        self.assertIn("https://www.isna.ir/dollar", toks)
        hist = web_server.STATE.talk_history
        self.assertEqual(hist[-2]["role"], "user")
        self.assertIn("نتایج وب", hist[-1]["content"])

    def test_search_command_failure_degrades_cleanly(self):
        def boom(q, max_results=6, **kw):
            raise RuntimeError("offline")

        called = []

        def must_not_call(*a, **kw):
            called.append(1)
            return "", False

        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  must_not_call), \
                mock.patch.object(web_server.nova.ns, "web_search", boom):
            r, evs = self._post_talk({"message": "/search قیمت دلار"})
        self.assertEqual(r.status, 200)
        self.assertEqual(called, [])                  # no model fallback
        self.assertEqual([e for e in evs if e.get("t") == "web"], [])
        self.assertEqual(web_server.STATE.talk_history, [])
        notes = [e["text"] for e in evs if e.get("t") == "note"]
        self.assertTrue(any("ناموفق" in n for n in notes))

    def test_search_command_empty_query_shows_usage(self):
        called = []

        def must_not_call(*a, **kw):
            called.append(1)
            return "", False

        with _quiet(), \
                mock.patch.object(web_server.nova, "stream_chat",
                                  must_not_call):
            r, _ = self._post_talk({"message": "/search"})
        self.assertEqual(r.status, 200)
        self.assertEqual(called, [])


# =====================================================================
# 5. UI pins (the segmented control + source chips + send body)
# =====================================================================
class TestTalkWebUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (Path(web_server.WEB_DIR) / "index.html").read_text(
            encoding="utf-8")

    def test_segmented_control_exists_with_three_modes(self):
        self.assertIn('id="talkWebModes"', self.page)
        for m in ("auto", "always", "off"):
            self.assertIn('data-wm="%s"' % m, self.page)

    def test_send_body_carries_the_mode(self):
        self.assertIn('{message: text, web: talkWebMode}', self.page)

    def test_web_event_handler_renders_sources(self):
        self.assertIn('ev.t === "web"', self.page)
        self.assertIn("buildTalkSources", self.page)
        self.assertIn('className = "talksrc"', self.page)
        # sources survive the final innerHTML wipe
        self.assertIn("body.appendChild(buildTalkSources(talkSources))",
                      self.page)

    def test_sources_are_xss_safe(self):
        # textContent for chips, rel noopener, and an http(s)-only href gate
        self.assertIn('a.textContent = (title || dom || url).slice(0, 60)',
                      self.page)
        self.assertIn('/^https?:\\/\\//i.test(url)', self.page)
        self.assertIn('a.rel = "noopener noreferrer"', self.page)

    def test_mode_load_and_webmode_sync(self):
        self.assertIn('"/api/talk/web"', self.page)
        self.assertIn('ev.t === "webmode"', self.page)
        self.assertIn("loadTalkWebMode", self.page)

    def test_no_emoji_pins(self):
        bad = [c for c in self.page if ord(c) >= 0x2300]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
