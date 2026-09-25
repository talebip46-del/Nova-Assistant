#!/usr/bin/env python3
"""v8.0.1 tests: the coffe8_after report - generated sites shipped with
NO real internet photos. Three deterministic holes, three pins:

  1. TINY base64 data: URIs (procedural pixel junk a weak model embeds
     instead of the IMG: protocol) used to be classified "leave" and
     stayed on the page forever -> now refilled from the alt text
     (real photo online, local art placeholder offline).
  2. JS card grids: a renderer that builds cards with
     document.createElement never puts an <img> in the HTML, so IMG:
     literals in its data array were never filled -> applied .js files
     now get their "IMG:..." literals replaced with downloaded assets.
  3. Zero-img safety net: a COMPLETE page (doctype/</html>) that ships
     without a single <img> gets a hero slot injected (after </h1> /
     first <section> / <body>) and filled like any protocol tag.
     Snippets (no doctype/body) stay untouched.

All network-dependent paths are MOCKED (smart_search + _fetch_image)
so the pins are offline-deterministic; one extra pin exercises the
offline fallback (search fails -> placeholder SVG replaces the junk).
"""
import base64
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_images as ni  # noqa: E402


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


# a real-ish tiny JPEG: a candidate _fetch_image would return
# CONTRACT: _fetch_image -> (ext, raw_bytes, meta) - ext FIRST
_FAKE_JPG_RAW = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


def _canned_search(query, limit=5, deadline=None):
    """One believable search result for any query."""
    tq = {"en": query, "colors": []}
    r = {"source": "bing", "title": query,
         "url": "https://img.example.com/%s.jpg"
                % query.replace(" ", "-"),
         "thumb": "https://img.example.com/%s_t.jpg"
                  % query.replace(" ", "-"),
         "w": 1200, "h": 800}
    return [r], tq


def _fake_fetch(url, deadline=None, max_bytes=None, **kw):
    return ("jpg", _FAKE_JPG_RAW, {})


def _fake_normalize(raw, ext, ratio=None):
    # pass bytes through untouched but report believable dims
    return raw, ext, (1200, 800)


class TinyDataUri(unittest.TestCase):
    """FIX-1: < 15 KB embedded payloads are junk -> refilled."""

    def test_tiny_helper_math(self):
        tiny = base64.b64encode(b"x" * 100).decode()
        big = base64.b64encode(b"x" * 40_000).decode()
        self.assertTrue(ni._tiny_data_uri("data:image/png;base64," + tiny))
        self.assertFalse(ni._tiny_data_uri("data:image/png;base64," + big))
        # undecodable garbage has no real-photo bytes either -> junk
        self.assertTrue(ni._tiny_data_uri("data:image/png;base64,%%%"))
        self.assertTrue(ni._tiny_data_uri("data:image/png;base64,"))
        # url-encoded (non-base64) flavor
        self.assertTrue(ni._tiny_data_uri(
            "data:image/svg+xml," + "%41" * 50))

    def test_classify_routes_tiny_to_broken(self):
        tiny = base64.b64encode(b"x" * 100).decode()
        big = base64.b64encode(b"x" * 40_000).decode()
        kind, q = ni._classify("<img>", "data:image/png;base64," + tiny,
                               "espresso cup", Path("."), Path("."))
        self.assertEqual(kind, "broken")
        self.assertEqual(q, "espresso cup")
        kind, q = ni._classify("<img>", "data:image/png;base64," + big,
                               "espresso cup", Path("."), Path("."))
        self.assertEqual(kind, "leave")

    def test_tiny_junk_gets_refilled(self):
        tiny = base64.b64encode(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
        page = ('<html><body><h1>Cafe</h1>'
                '<img src="data:image/png;base64,%s" '
                'alt="espresso cup"></body></html>' % tiny)
        with _env(NOVA_NO_IMAGES=""), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(page, encoding="utf-8")
            with mock.patch.object(ni, "smart_search", _canned_search), \
                 mock.patch.object(ni, "_fetch_image", _fake_fetch), \
                 mock.patch.object(ni, "normalize_for_page",
                                   _fake_normalize):
                extras, notes = ni.fill_html_images(ws, ["index.html"])
            out = (ws / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("data:image", out)          # junk GONE
        self.assertIn("assets/images/", out)         # real asset linked
        self.assertEqual(len(extras), 1)             # asset joined undo
        self.assertTrue(any("espresso cup" in n for n in notes))

    def test_tiny_junk_offline_gets_placeholder(self):
        """Offline the junk STILL goes (local art), never stays data:."""
        tiny = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
        page = ('<html><body><h1>Cafe</h1>'
                '<img src="data:image/png;base64,%s" '
                'alt="latte art"></body></html>' % tiny)
        with _env(NOVA_NO_IMAGES=""), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(page, encoding="utf-8")
            with mock.patch.object(ni, "smart_search",
                                   lambda q, limit=5, deadline=None:
                                       ([], None)):
                extras, notes = ni.fill_html_images(ws, ["index.html"])
            out = (ws / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("data:image", out)
        self.assertIn("assets/images/_ph-", out)     # svg placeholder
        self.assertEqual(len(extras), 1)


class JsLiterals(unittest.TestCase):
    """FIX-2: IMG: literals inside generated .js data arrays."""

    def test_js_literal_replaced(self):
        js = ('const ITEMS=[{name:"espresso",img:"IMG:espresso cup",'
              'alt:"اسپرسو"},{name:"latte",img:\'IMG:latte art\'}];')
        with _env(NOVA_NO_IMAGES=""), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "script.js").write_text(js, encoding="utf-8")
            with mock.patch.object(ni, "smart_search", _canned_search), \
                 mock.patch.object(ni, "_fetch_image", _fake_fetch), \
                 mock.patch.object(ni, "normalize_for_page",
                                   _fake_normalize):
                extras, notes = ni.fill_html_images(ws, ["script.js"])
            out = (ws / "script.js").read_text(encoding="utf-8")
            self.assertNotIn("IMG:", out)
            self.assertEqual(out.count("assets/images/"), 2)  # both
            self.assertEqual(len(extras), 2)
            # root-relative (browsers resolve against the PAGE)
            self.assertIn('"assets/images/', out)

    def test_js_offline_keeps_literal(self):
        """No network -> the literal stays (honest) instead of a lie."""
        js = 'const ITEMS=[{img:"IMG:espresso cup"}];'
        with _env(NOVA_NO_IMAGES=""), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "script.js").write_text(js, encoding="utf-8")
            with mock.patch.object(ni, "smart_search",
                                   lambda q, limit=5, deadline=None:
                                       ([], None)):
                extras, notes = ni.fill_html_images(ws, ["script.js"])
            out = (ws / "script.js").read_text(encoding="utf-8")
        self.assertIn("IMG:espresso cup", out)
        self.assertEqual(len(extras), 0)

    def test_js_dedup_shares_one_download(self):
        js = ('const A=[{img:"IMG:espresso cup"}];'
              'const B=[{img:"IMG:espresso cup"}];')
        with _env(NOVA_NO_IMAGES=""), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "script.js").write_text(js, encoding="utf-8")
            calls = {"n": 0}

            def _count_search(query, limit=5, deadline=None):
                calls["n"] += 1
                return _canned_search(query, limit, deadline)

            with mock.patch.object(ni, "smart_search", _count_search), \
                 mock.patch.object(ni, "_fetch_image", _fake_fetch), \
                 mock.patch.object(ni, "normalize_for_page",
                                   _fake_normalize):
                extras, notes = ni.fill_html_images(ws, ["script.js"])
        self.assertEqual(calls["n"], 1)              # cache dedupe
        self.assertEqual(len(extras), 1)

    def test_js_without_img_untouched(self):
        js = 'const x = "IMGX: not a literal";\nconst y = "IMG";'
        with _env(NOVA_NO_IMAGES=""), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "script.js").write_text(js, encoding="utf-8")
            extras, notes = ni.fill_html_images(ws, ["script.js"])
            self.assertEqual(
                (ws / "script.js").read_text(encoding="utf-8"), js)
            self.assertEqual(len(extras), 0)


class ZeroImgSafetyNet(unittest.TestCase):
    """FIX-3: complete pages with zero <img> get a hero photo."""

    MULTI_SHAPE = (
        '<!doctype html>\n<html lang="fa" dir="rtl">\n<head>'
        '<title>کافه نوا — نسخه چندفایلی</title></head>\n<body>\n'
        '<section class="hero"><h1>قهوه‌ی تازه</h1>'
        '<p>در قلب شهر</p></section>\n'
        '<main class="grid" id="grid"></main>\n'
        '<script src="script.js"></script>\n</body>\n</html>')

    def _fill(self, page, names=("index.html",)):
        td = tempfile.TemporaryDirectory()
        ws = Path(td.name)
        (ws / "index.html").write_text(page, encoding="utf-8")
        with _env(NOVA_NO_IMAGES=""):
            with mock.patch.object(ni, "smart_search", _canned_search), \
                 mock.patch.object(ni, "_fetch_image", _fake_fetch), \
                 mock.patch.object(ni, "normalize_for_page",
                                   _fake_normalize):
                extras, notes = ni.fill_html_images(ws, list(names))
        out = (ws / "index.html").read_text(encoding="utf-8")
        return out, extras, notes, td   # td kept alive by caller

    def test_complete_page_gets_hero(self):
        out, extras, notes, td = self._fill(self.MULTI_SHAPE)
        try:
            self.assertIn("<img", out)                    # hero injected
            self.assertNotIn("IMG:", out)                 # and FILLED
            self.assertIn("assets/images/", out)
            self.assertGreaterEqual(len(extras), 1)
            self.assertTrue(any("hero slot injected" in n for n in notes))
            # after </h1> - the preferred anchor
            self.assertLess(out.index("</h1>"),
                            out.index("<img"))
        finally:
            td.cleanup()

    def test_page_with_img_untouched_by_net(self):
        page = ('<!doctype html><html><head><title>Cafe — x</title>'
                '</head><body><h1>a</h1>'
                '<img src="data:image/png;base64,%s" alt="p">'
                '</body></html>'
                % base64.b64encode(b"y" * 40_000).decode())
        out, extras, notes, td = self._fill(page)
        try:
            # the big data: photo stays; NO second hero was injected
            self.assertEqual(out.count("<img"), 1)
            self.assertFalse(any("hero slot" in n for n in notes))
        finally:
            td.cleanup()

    def test_snippet_never_gets_hero(self):
        page = '<div class="card"><h3>latte</h3><p>melty</p></div>'
        out, extras, notes, td = self._fill(page)
        try:
            self.assertNotIn("<img", out)
            self.assertEqual(len(extras), 0)
        finally:
            td.cleanup()

    def test_hero_query_strips_delimiters(self):
        self.assertEqual(ni._hero_query(self.MULTI_SHAPE), "کافه نوا")
        self.assertEqual(ni._hero_query("<title>Solo Cafe</title>"),
                         "Solo Cafe")
        self.assertEqual(ni._hero_query("<html><body>no title</body>"), "")

    def test_inject_anchor_priority(self):
        html = "<body><section><h1>a</h1></section></body>"
        out = ni._inject_hero(html, "<IMG>")
        self.assertIn("<h1>a</h1>\n<IMG>", out)
        html = "<body><section><h2>a</h2></section></body>"
        out = ni._inject_hero(html, "<IMG>")
        self.assertIn("<section>\n<IMG>", out)
        html = "<body><p>x</p></body>"
        out = ni._inject_hero(html, "<IMG>")
        self.assertIn("<body>\n<IMG>", out)
        self.assertEqual(ni._inject_hero("<div>x</div>", "<IMG>"),
                         "<div>x</div>")


class SubjectIntelligence(unittest.TestCase):
    """v8.0.1: subject selection + the subject-orphan gate + the staged
    parallel provider fan-out (the coffee81 live findings)."""

    def test_subject_prefers_known_nouns(self):
        tq = ni.translate_query("chocolate cake slice")
        self.assertEqual(tq.get("subject"), "cake")
        tq = ni.translate_query("coffee shop interior warm")
        self.assertEqual(tq.get("subject"), "shop")
        tq = ni.translate_query("espresso cup dark coffee")
        self.assertEqual(tq.get("subject"), "coffee")
        # stem-aware: 'roses' is the known 'rose'
        tq = ni.translate_query("red roses bouquet hero")
        # 'bouquet' is itself a dict noun and sits last among knowns
        self.assertEqual(tq.get("subject"), "bouquet")

    def test_subject_brand_name_never_hijacks(self):
        tq = ni.translate_query("کافه نوا")
        self.assertEqual(tq.get("subject"), "cafe")

    def test_orphan_candidates_skipped(self):
        """A candidate that never mentions the subject is skipped even
        when it is the only result - placeholder beats a wrong photo."""
        import base64 as b64

        def _jpg(w, h, rgb):
            from PIL import Image  # noqa: F401 - pillow is installed
            import io as _io
            im = Image.new("RGB", (w, h), rgb)
            buf = _io.BytesIO()
            im.save(buf, "JPEG")
            return buf.getvalue()

        junk = {"title": "totally unrelated thing",
                "url": "http://x/wrong.jpg", "thumb": "",
                "width": 1200, "height": 800, "source": "ddg"}
        with _env(NOVA_NO_IMAGES=""), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(
                '<html><body><h1>t</h1>'
                '<img src="IMG:red rose" alt="r"></body></html>',
                encoding="utf-8")
            with mock.patch.object(ni, "smart_search",
                                   lambda q, limit=5, deadline=None:
                                       ([junk], ni.translate_query(q))), \
                 mock.patch.object(ni, "_fetch_image",
                                   lambda url, deadline=None, **kw:
                                       ("jpg", _jpg(1200, 800,
                                                    (200, 30, 30)), {})):
                extras, notes = ni.fill_html_images(ws, ["index.html"])
            out = (ws / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("wrong.jpg", out)
        self.assertIn("_ph-red-rose-", out)
        # the placeholder joins the undo unit as the slot's asset
        self.assertEqual(len(extras), 1)
        self.assertTrue(extras[0][0].endswith(".svg"))

    def test_staged_fanout_skips_stage2_when_stage1_fills(self):
        ddg = [{"title": "rose %d" % i, "url": "http://a/%d.jpg" % i,
                "thumb": "", "width": 1200, "height": 800,
                "source": "ddg"} for i in range(10)]
        with mock.patch.object(ni, "_ddg_search", return_value=ddg), \
             mock.patch.object(ni, "_bing_search", return_value=[]), \
             mock.patch.object(ni, "_openverse_search",
                               return_value=[]) as opv, \
             mock.patch.object(ni, "_commons_search",
                               return_value=[]) as com:
            out = ni.search_images("rose", limit=4)
        self.assertEqual(len(out), 4)
        opv.assert_not_called()
        com.assert_not_called()

    def test_hung_provider_does_not_block_fast_one(self):
        import time as _t

        def _hung(query, limit, deadline):
            _t.sleep(30)          # would blow any sane test budget
            return []

        def _fast(query, limit, deadline):
            return [{"title": "rose fast", "url": "http://f/r.jpg",
                     "thumb": "", "width": 1200, "height": 800,
                     "source": "bing"}]

        t0 = _t.monotonic()
        with mock.patch.object(ni, "_ddg_search", side_effect=_hung), \
             mock.patch.object(ni, "_bing_search", side_effect=_fast), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            out = ni.search_images("rose", limit=4)
        took = _t.monotonic() - t0
        self.assertGreaterEqual(len(out), 1)
        self.assertEqual(out[0].get("url"), "http://f/r.jpg")
        # the hung provider must not delay the answer by its full hang
        self.assertLess(took, 20, "fast provider must not wait 30 s")


class KillSwitch(unittest.TestCase):
    def test_no_images_flag_stops_everything(self):
        with _env(NOVA_NO_IMAGES="1"), tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "index.html").write_text(
                "<!doctype html><html><body><h1>x</h1></body></html>",
                encoding="utf-8")
            (ws / "script.js").write_text('a="IMG:espresso cup";',
                                          encoding="utf-8")
            extras, notes = ni.fill_html_images(ws, ["index.html",
                                                     "script.js"])
            self.assertEqual(extras, [])
            self.assertIn("IMG:espresso cup",
                          (ws / "script.js").read_text(encoding="utf-8"))


class VersionPin(unittest.TestCase):
    def test_version_is_801(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
