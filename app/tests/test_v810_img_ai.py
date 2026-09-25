#!/usr/bin/env python3
"""v8.11.0 tests: the AI IMAGE LAYERS - a connected cloud brain HELPS
FIND photos (layer 1: English phrase expansion feeding extra search
rungs) and MUST give the FINAL verdict on every downloaded photo
(layer 2: vision review; local vision-capable models best effort).

Pins:
  - verdict parser: JSON, prose-wrapped JSON, single quotes, word
    answers, garbage -> (None) so the caller fails soft;
  - wire shapes: openai data-url / anthropic base64 block / gemini
    inline_data (nova_providers._gemini_build) / ollama images field;
  - nova_providers.once(): drains stream_chunks into ONE string;
  - layer 1: AI phrases join the smart_search ladder after the primary
    rung (deduped), [] without a hook, kill switch honours;
  - layer 2 in fill_html_images: a clear AI REJECT skips the candidate
    (placeholder is the last resort), an APPROVE stores the photo with
    the verdict tail in the note, breaker/kill-switch short-circuits;
  - pick_and_save: rejected candidates surface ai_rejected in meta.

All network paths are MOCKED - the pins are offline-deterministic.
"""
import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_images as ni  # noqa: E402
import nova_providers as nprov  # noqa: E402


@contextlib.contextmanager
def _env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    os.environ.update(kw)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


PAGE = ('<html><body><h1>Cafe</h1>'
        '<img src="IMG:red rose" alt="گل سرخ" width="800" height="600">'
        '</body></html>')


def _canned_search(query, limit=5, deadline=None):
    tq = {"en": query, "colors": [], "subject": "rose",
          "weights": [], "orig": query}
    r = {"source": "bing", "title": query,
         "url": "https://img.example.com/%s.jpg" % query.replace(" ", "-"),
         "thumb": "https://img.example.com/%s_t.jpg"
                  % query.replace(" ", "-"),
         "width": 1200, "height": 800}
    return [r], tq


def _fake_fetch(url, deadline=None, max_bytes=None, **kw):
    return ("jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9", {})


def _fake_normalize(raw, ext, ratio=None):
    return raw, ext, (1200, 800)


class VerdictParser(unittest.TestCase):
    """The reviewer's answer -> (ok, reason); unreadable = (None, ...)."""

    def test_json_true_false(self):
        self.assertEqual(nova._img_ai_parse_verdict('{"ok": true}'),
                         (True, ""))
        self.assertEqual(nova._img_ai_parse_verdict(
            '{"ok": false, "reason": "a cat"}'), (False, "a cat"))

    def test_prose_and_single_quotes(self):
        self.assertEqual(nova._img_ai_parse_verdict(
            'Sure! Here it is: {\'ok\': true} hope that helps'), (True, ""))
        self.assertEqual(nova._img_ai_parse_verdict(
            '{"ok": false, "reason": "logo, not a photo"}'),
            (False, "logo, not a photo"))

    def test_regex_fallback(self):
        self.assertEqual(nova._img_ai_parse_verdict(
            'answer: {"ok": true,} done'), (True, ""))
        self.assertEqual(nova._img_ai_parse_verdict('"ok": false'),
                         (False, "rejected"))

    def test_word_answers(self):
        self.assertEqual(nova._img_ai_parse_verdict("Yes."), (True, ""))
        self.assertEqual(nova._img_ai_parse_verdict(
            "No - that is a poster"), (False, "rejected"))

    def test_unreadable_is_none(self):
        ok, why = nova._img_ai_parse_verdict("the photo looks nice I guess")
        self.assertIsNone(ok)
        self.assertEqual(nova._img_ai_parse_verdict(""), (None, "empty answer"))


class WireShapes(unittest.TestCase):
    """Vision messages in the exact shape each provider kind wants."""

    def test_openai_data_url(self):
        msgs = nova._img_ai_messages("openai", "P", "QUJD")
        c = msgs[0]["content"]
        self.assertEqual(c[0]["type"], "text")
        self.assertEqual(c[1]["type"], "image_url")
        self.assertTrue(c[1]["image_url"]["url"]
                        .startswith("data:image/jpeg;base64,QUJD"))

    def test_anthropic_block(self):
        msgs = nova._img_ai_messages("anthropic", "P", "QUJD")
        c = msgs[0]["content"]
        self.assertEqual(c[0]["type"], "image")
        self.assertEqual(c[0]["source"]["media_type"], "image/jpeg")
        self.assertEqual(c[0]["source"]["data"], "QUJD")
        self.assertEqual(c[1]["type"], "text")

    def test_gemini_and_ollama_compact(self):
        for kind in ("gemini", "ollama"):
            msgs = nova._img_ai_messages(kind, "P", "QUJD")
            self.assertEqual(msgs[0]["images"], ["QUJD"])
            self.assertEqual(msgs[0]["content"], "P")

    def test_gemini_build_inline_data(self):
        payload = nprov._gemini_build(
            [{"role": "user", "content": "hi", "images": ["QUJD"]}], 0.1)
        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "hi"})
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "image/jpeg")
        self.assertEqual(parts[1]["inline_data"]["data"], "QUJD")

    def test_gemini_build_system_still_works(self):
        payload = nprov._gemini_build(
            [{"role": "system", "content": "S"},
             {"role": "user", "content": "hi"}], 0.1)
        self.assertEqual(payload["systemInstruction"],
                         {"parts": [{"text": "S"}]})
        self.assertEqual(payload["contents"][0]["parts"], [{"text": "hi"}])

    def test_once_collects(self):
        with mock.patch.object(nprov, "stream_chunks",
                               lambda *a, **k: iter(["a", "b", "c"])):
            self.assertEqual(nprov.once({"kind": "openai"}, "m", []), "abc")


class CloudResolution(unittest.TestCase):
    """The MANDATORY verifier is the CLOUD brain; local is the fallback."""

    def test_no_providers_no_cloud(self):
        with mock.patch.object(nova, "providers", None):
            self.assertEqual(nova._img_ai_cloud(), (None, ""))

    def test_unkeyed_cloud_is_unusable(self):
        cfg = {"name": "x", "kind": "openai", "base": "https://api.x.com",
               "model": "m", "key": ""}
        with mock.patch.object(nova, "_provider_cfg", return_value=cfg):
            self.assertEqual(nova._img_ai_cloud(), (None, ""))

    def test_keyed_active_cloud_wins(self):
        cfg = {"name": "x", "kind": "openai", "base": "https://api.x.com",
               "model": "m", "key": "sk-1"}
        with mock.patch.object(nova, "_provider_cfg", return_value=cfg):
            got, model = nova._img_ai_cloud()
        self.assertEqual(got, cfg)
        self.assertEqual(model, "m")

    def test_utility_route_cloud_wins_first(self):
        rcfg = {"name": "r", "kind": "gemini", "base": "https://g.api",
                "model": "gm", "key": "k"}
        with mock.patch.object(nova.providers, "resolve_route",
                               return_value=(rcfg, "gm")), \
             mock.patch.object(nova, "_provider_cfg",
                               return_value={"kind": "ollama",
                                             "model": "qwen2.5-coder"}):
            got, model = nova._img_ai_cloud()
        self.assertEqual(got, rcfg)
        self.assertEqual(model, "gm")

    def test_local_active_is_not_cloud(self):
        with mock.patch.object(
                nova, "_provider_cfg",
                return_value={"kind": "ollama", "model": "qwen2.5-coder"}):
            self.assertEqual(nova._img_ai_cloud(), (None, ""))


class KillSwitchAndBreaker(unittest.TestCase):
    """NOVA_NO_IMG_AI=1 and the 3-fail breaker pause the AI layers."""

    def test_kill_switch_disables_hooks_at_import(self):
        import importlib
        with _env(NOVA_NO_IMG_AI="1"):
            import importlib as il
            il.reload(nova)
            self.assertIsNone(ni.AI_QUERY_HOOK)
            self.assertIsNone(ni.AI_VERIFY_HOOK)
        il.reload(nova)     # restore for the other tests
        self.assertIsNotNone(ni.AI_VERIFY_HOOK)

    def test_breaker_short_circuits(self):
        import time as _t
        with _env(NOVA_NO_IMG_AI=""):
            nova._IMG_AI_STATE["until"] = _t.time() + 1e9  # breaker OPEN
            try:
                self.assertEqual(nova._img_ai_verify("red rose", b"x"),
                                 (True, "ai-cold"))
                with mock.patch.object(
                        nova, "providers",
                        mock.Mock(side_effect=AssertionError("no call"))):
                    self.assertEqual(nova._img_ai_queries("red rose"), [])
            finally:
                nova._IMG_AI_STATE["until"] = 0.0

    def test_three_fails_open_breaker(self):
        old = dict(nova._IMG_AI_STATE)
        try:
            nova._IMG_AI_STATE["fails"] = 0
            nova._IMG_AI_STATE["until"] = 0.0
            nova._img_ai_note_fail()
            nova._img_ai_note_fail()
            self.assertFalse(nova._img_ai_open())
            nova._img_ai_note_fail()          # the third one trips it
            self.assertTrue(nova._img_ai_open())
        finally:
            nova._IMG_AI_STATE.clear()
            nova._IMG_AI_STATE.update(old)


class Layer1Find(unittest.TestCase):
    """Cloud phrases join the search ladder after the primary rung."""

    def setUp(self):
        self._hook = ni.AI_QUERY_HOOK

    def tearDown(self):
        ni.AI_QUERY_HOOK = self._hook
        ni._AI_RUNG_CACHE.clear()

    def test_rungs_injected_after_primary(self):
        seen = []

        def fake_search(q, limit=5, deadline=None):
            seen.append(q)
            return []
        ni.AI_QUERY_HOOK = lambda q: ["rose flower macro",
                                      "red rose bouquet", q]
        with mock.patch.object(ni, "search_images", fake_search), \
             _env(NOVA_NO_IMG_AI=""):
            ni.smart_search("red rose", limit=3, deadline=None)
        self.assertEqual(seen[0], "red rose")            # primary first
        self.assertIn("rose flower macro", seen[:4])
        self.assertIn("red rose bouquet", seen[:4])
        self.assertLess(seen.index("rose flower macro"),
                        len(seen) - 1)                   # NOT last

    def test_no_hook_no_rungs(self):
        ni.AI_QUERY_HOOK = None
        seen = []

        def fake_search(q, limit=5, deadline=None):
            seen.append(q)
            return []
        with mock.patch.object(ni, "search_images", fake_search):
            ni.smart_search("red rose", limit=3, deadline=None)
        self.assertEqual(seen, ["red rose"])

    def test_hook_error_is_swallowed(self):
        def boom(q):
            raise RuntimeError("cloud down")
        ni.AI_QUERY_HOOK = boom
        seen = []

        def fake_search(q, limit=5, deadline=None):
            seen.append(q)
            return []
        with mock.patch.object(ni, "search_images", fake_search), \
             _env(NOVA_NO_IMG_AI=""):
            ni.smart_search("red rose", limit=3, deadline=None)
        self.assertIn("red rose", seen)


class Layer2VerifyFill(unittest.TestCase):
    """fill_html_images honours the AI's final verdict."""

    def setUp(self):
        self._hook = ni.AI_VERIFY_HOOK

    def tearDown(self):
        ni.AI_VERIFY_HOOK = self._hook

    def _fill(self, ws, hook, expect_query=None, img_ai_env=""):
        calls = []

        def spy(q, jpeg):
            calls.append((q, jpeg))
            return hook(q, jpeg)
        ni.AI_VERIFY_HOOK = spy
        with mock.patch.object(ni, "smart_search", _canned_search), \
             mock.patch.object(ni, "_fetch_image", _fake_fetch), \
             mock.patch.object(ni, "normalize_for_page", _fake_normalize), \
             _env(NOVA_NO_IMG_AI=img_ai_env):
            extras, notes = ni.fill_html_images(ws, ["index.html"])
        return extras, notes, calls

    def test_approve_stores_photo_with_tail(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(PAGE, encoding="utf-8")
            extras, notes, calls = self._fill(
                ws, lambda q, j: (True, "ai-approved"))
            self.assertEqual(len(calls), 1)
            self.assertIn("red rose", calls[0][0])
            self.assertGreater(len(calls[0][1]), 32)      # real bytes seen
            self.assertIn("assets/images/", (ws / "index.html")
                          .read_text(encoding="utf-8"))
            self.assertTrue(any("ai-approved" in n for n in notes))
            self.assertEqual(len(extras), 1)

    def test_reject_skips_to_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(PAGE, encoding="utf-8")
            extras, notes, calls = self._fill(
                ws, lambda q, j: (False, "not a rose"))
            # both candidate URLs (url + thumb) of the one result were
            # seen and BOTH got the AI's NO
            self.assertEqual(len(calls), 2)
            out = (ws / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("assets/images/.jpg", out)
            imgs = list((ws / "assets" / "images").glob("*.jpg")) \
                if (ws / "assets" / "images").exists() else []
            self.assertEqual(imgs, [])
            self.assertTrue(any("ai-rejected 2" in n for n in notes))

    def test_reject_then_approve_uses_next_candidate(self):
        verdicts = [(False, "junk"), (True, "ai-approved")]

        def hook(q, j):
            return verdicts.pop(0)
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(PAGE, encoding="utf-8")

            def two_results(query, limit=5, deadline=None):
                tq = {"en": query, "colors": [], "subject": "rose",
                      "weights": [], "orig": query}
                rs = [{"source": "bing", "title": f"{query} {i}",
                       "url": f"https://img.example.com/{i}.jpg",
                       "thumb": f"https://img.example.com/{i}_t.jpg",
                       "width": 1200, "height": 800} for i in range(2)]
                return rs, tq
            calls = []

            def spy(q, jpeg):
                calls.append(q)
                return hook(q, jpeg)
            ni.AI_VERIFY_HOOK = spy
            with mock.patch.object(ni, "smart_search", two_results), \
                 mock.patch.object(ni, "_fetch_image", _fake_fetch), \
                 mock.patch.object(ni, "normalize_for_page",
                                   _fake_normalize), \
                 _env(NOVA_NO_IMG_AI=""):
                extras, notes = ni.fill_html_images(ws, ["index.html"])
            self.assertEqual(len(calls), 2)               # 1st NO, 2nd YES
            self.assertTrue(any("ai-approved" in n for n in notes))

    def test_hook_crash_fails_soft(self):
        def boom(q, j):
            raise RuntimeError("api exploded")
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(PAGE, encoding="utf-8")
            extras, notes, calls = self._fill(ws, boom)
            self.assertTrue(any("ai-err" in n for n in notes))
            self.assertTrue((ws / "assets" / "images").exists())

    def test_kill_switch_skips_verification(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(PAGE, encoding="utf-8")
            extras, notes, calls = self._fill(
                ws, lambda q, j: (_ for _ in ()).throw(AssertionError("no")),
                img_ai_env="1")
            self.assertEqual(calls, [])                   # never consulted
            self.assertIn("assets/images/", (ws / "index.html")
                          .read_text(encoding="utf-8"))


class Layer2VerifyPick(unittest.TestCase):
    """pick_and_save (the [IMG:] token / _action_img path) too."""

    def setUp(self):
        self._hook = ni.AI_VERIFY_HOOK

    def tearDown(self):
        ni.AI_VERIFY_HOOK = self._hook

    def test_pick_rejected_reports_ai_rejected(self):
        ni.AI_VERIFY_HOOK = lambda q, j: (False, "a cat")
        with tempfile.TemporaryDirectory() as td, _env(NOVA_NO_IMG_AI=""):
            with mock.patch.object(ni, "smart_search", _canned_search), \
                 mock.patch.object(ni, "_fetch_image", _fake_fetch), \
                 mock.patch.object(ni, "normalize_for_page",
                                   _fake_normalize):
                rel, src, meta = ni.pick_and_save("red rose", Path(td))
                self.assertIsNone(rel)
                # url + thumb = 2 candidate downloads, 2 AI rejections
                self.assertEqual(meta.get("ai_rejected"), 2)

    def test_pick_approved_carries_verdict(self):
        ni.AI_VERIFY_HOOK = lambda q, j: (True, "ai-approved")
        with tempfile.TemporaryDirectory() as td, _env(NOVA_NO_IMG_AI=""):
            ws = Path(td)
            with mock.patch.object(ni, "smart_search", _canned_search), \
                 mock.patch.object(ni, "_fetch_image", _fake_fetch), \
                 mock.patch.object(ni, "normalize_for_page",
                                   _fake_normalize):
                rel, src, meta = ni.pick_and_save("red rose", ws)
                self.assertIsNotNone(rel)
                self.assertEqual(meta.get("ai"), "ai-approved")
                self.assertTrue((ws / rel).is_file())


class LocalVisionGate(unittest.TestCase):
    """No cloud brain: only a VISION-named local model gets asked."""

    def test_text_only_model_never_asked(self):
        old = dict(nova._IMG_AI_STATE)
        try:
            nova._IMG_AI_STATE["local"] = None
            with mock.patch.object(
                    nova, "_provider_cfg",
                    return_value={"kind": "ollama",
                                  "model": "qwen2.5-coder:7b"}), \
                 mock.patch.object(
                     nova, "_ollama_once",
                     mock.Mock(side_effect=AssertionError("no call"))):
                ok, tail = nova._img_ai_verify("red rose", b"\xff\xd8")
            self.assertTrue(ok)
            self.assertIs(nova._IMG_AI_STATE["local"], False)
        finally:
            nova._IMG_AI_STATE.clear()
            nova._IMG_AI_STATE.update(old)

    def test_vision_model_is_asked(self):
        old = dict(nova._IMG_AI_STATE)
        try:
            nova._IMG_AI_STATE["local"] = None
            with mock.patch.object(
                    nova, "_provider_cfg",
                    return_value={"kind": "ollama",
                                  "model": "llava:13b"}), \
                 mock.patch.object(nova, "_ollama_once",
                                   return_value='{"ok": true}'):
                ok, tail = nova._img_ai_verify("red rose", b"\xff\xd8")
            self.assertTrue(ok)
            self.assertEqual(tail, "local-approved")
        finally:
            nova._IMG_AI_STATE.clear()
            nova._IMG_AI_STATE.update(old)

    def test_vision_model_rejection_honoured(self):
        old = dict(nova._IMG_AI_STATE)
        try:
            nova._IMG_AI_STATE["local"] = None
            with mock.patch.object(
                    nova, "_provider_cfg",
                    return_value={"kind": "ollama",
                                  "model": "llama3.2-vision"}), \
                 mock.patch.object(nova, "_ollama_once",
                                   return_value='{"ok": false,'
                                                ' "reason": "a cat"}'):
                ok, tail = nova._img_ai_verify("red rose", b"\xff\xd8")
            self.assertFalse(ok)
            self.assertEqual(tail, "a cat")
        finally:
            nova._IMG_AI_STATE.clear()
            nova._IMG_AI_STATE.update(old)


class CloudGateFlow(unittest.TestCase):
    """With a cloud brain: real verdict honoured, infra fails soft."""

    def _cfg(self):
        return {"name": "c", "kind": "openai",
                "base": "https://api.c.com", "model": "cm", "key": "k"}

    def test_cloud_rejection_rejects(self):
        with mock.patch.object(nova, "_img_ai_cloud",
                               return_value=(self._cfg(), "cm")), \
             mock.patch.object(nova.providers, "once",
                               return_value='{"ok": false,'
                                            ' "reason": "a poster"}'):
            ok, tail = nova._img_ai_verify("red rose", b"\xff\xd8")
        self.assertFalse(ok)
        self.assertEqual(tail, "a poster")

    def test_cloud_approval_approved(self):
        with mock.patch.object(nova, "_img_ai_cloud",
                               return_value=(self._cfg(), "cm")), \
             mock.patch.object(nova.providers, "once",
                               return_value='{"ok": true}'):
            ok, tail = nova._img_ai_verify("red rose", b"\xff\xd8")
        self.assertTrue(ok)
        self.assertEqual(tail, "ai-approved")

    def test_cloud_down_fails_soft(self):
        old = dict(nova._IMG_AI_STATE)
        try:
            nova._IMG_AI_STATE["fails"] = 0
            with mock.patch.object(nova, "_img_ai_cloud",
                                   return_value=(self._cfg(), "cm")), \
                 mock.patch.object(nova.providers, "once",
                                   side_effect=RuntimeError("429")):
                ok, tail = nova._img_ai_verify("red rose", b"\xff\xd8")
            self.assertTrue(ok)                    # NEVER bricks the fill
            self.assertEqual(tail, "ai-unreachable")
        finally:
            nova._IMG_AI_STATE.clear()
            nova._IMG_AI_STATE.update(old)

    def test_garbage_answer_fails_soft(self):
        with mock.patch.object(nova, "_img_ai_cloud",
                               return_value=(self._cfg(), "cm")), \
             mock.patch.object(nova.providers, "once",
                               return_value="I like this photo a lot!"):
            ok, tail = nova._img_ai_verify("red rose", b"\xff\xd8")
        self.assertTrue(ok)
        self.assertEqual(tail, "ai-soft")

    def test_query_expansion_parses_array(self):
        with mock.patch.object(nova, "_img_ai_cloud",
                               return_value=(self._cfg(), "cm")), \
             mock.patch.object(
                 nova.providers, "once",
                 return_value='["red rose flower closeup", '
                              '\'red roses bouquet\']'):
            nova._IMG_AI_QCACHE.clear()
            out = nova._img_ai_queries("گل سرخ")
            self.assertEqual(out, ["red rose flower closeup",
                                   "red roses bouquet"])

    def test_query_expansion_error_returns_empty(self):
        with mock.patch.object(nova, "_img_ai_cloud",
                               return_value=(self._cfg(), "cm")), \
             mock.patch.object(nova.providers, "once",
                               side_effect=RuntimeError("quota")):
            nova._IMG_AI_QCACHE.clear()
            self.assertEqual(nova._img_ai_queries("گل سرخ"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
