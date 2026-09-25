#!/usr/bin/env python3
"""v7.2.0 tests: Nova IMAGES - the internet photo engine.

"کاری کن بتونه خیلی راحت با اینترنت کار کنه، عکس دانلود کنه، اصلا عکس
 مورد نظر رو بتونه پیدا کنه، با دقت تمام"

Every test pins one layer (all NETWORK-FREE via stubs):

  - slug / _sniff_ext / placeholder_svg: pure helpers (magic bytes decide,
    Persian folds to a safe base, placeholders are valid deterministic XML)
  - search_images: multi-provider merge + dedupe + quality order, a
    failing provider never fails the search, no-network -> []
  - download_image: extension from magic bytes only, size cap, no net
    module -> refused; the SSRF layer itself stays pinned via safe_url
  - pick_and_save: search->download chain, cache idempotency (no
    re-download), miss -> (None, "", meta)
  - fill_html_images: the deterministic <img> filler - IMG: protocol,
    placeholder-host srcs, broken local paths, dead remote URLs (404)
    get real photos; working local files and data: URIs stay untouched;
    403 remote URLs are left alone; offline falls back to generated
    local art; NOVA_NO_IMAGES=1 kills everything
  - _image_fill_hook + offer_apply: assets join the SAME undo unit
    (end-to-end /undo deletes them again)
  - the [IMG: ...] model token: registry, dispatch, follow-up text
  - /img + /imgdl: registry, help payload coverage, output
  - prompt wiring: BASE_SYSTEM + DESIGN_CONTRACT teach the protocol
"""
import base64
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_images     # noqa: E402
import nova_design     # noqa: E402
import nova_search     # noqa: E402

PNG_BYTES = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
JPG_BYTES = (b"\xff\xd8\xff\xe0" + b"\x00" * 64)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _res(title="a photo", url="http://cdn.example.com/x.jpg", thumb="",
         w=1200, h=800, source="ddg"):
    return {"title": title, "url": url, "thumb": thumb,
            "width": w, "height": h, "source": source}


class _FakeNet:
    """Stand-in for nova_search: http_get_bytes returns canned payloads."""
    def __init__(self, payloads=None, code=None):
        self.payloads = payloads or {}
        self.code = code
        self.calls = []

    def http_get_bytes(self, url, timeout=None, max_bytes=1 << 20):
        self.calls.append(url)
        payload = self.payloads.get(url)
        if payload is None:
            err = OSError("not found")
            err.code = self.code if self.code is not None else 404
            raise err
        return payload, "image/png", url


class _Err403(Exception):
    pass


def _net403(url, timeout=None, max_bytes=1 << 20):
    import urllib.error
    raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)


def _net404(url, timeout=None, max_bytes=1 << 20):
    import urllib.error
    raise urllib.error.HTTPError(url, 404, "nope", {}, None)


# --------------------------------------------------------------------------
# 1. pure helpers
# --------------------------------------------------------------------------
class TestHelpers(unittest.TestCase):
    def test_slug_ascii(self):
        self.assertEqual(nova_images.slug("Mount Damavand!"), "mount-damavand")

    def test_slug_persian_folds_to_safe_base(self):
        self.assertEqual(nova_images.slug("کوه دماوند"), "img")

    def test_slug_empty(self):
        self.assertEqual(nova_images.slug(""), "img")
        self.assertEqual(nova_images.slug("///"), "img")

    def test_sniff_extensions(self):
        f = nova_images._sniff_ext
        self.assertEqual(f(PNG_BYTES), "png")
        self.assertEqual(f(JPG_BYTES), "jpg")
        self.assertEqual(f(b"GIF89a" + b"\x00" * 10), "gif")
        self.assertEqual(f(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10), "webp")
        self.assertEqual(f(b'<?xml version="1.0"?><svg/>'), "svg")
        self.assertEqual(f(b"<html>not an image</html>"), None)
        self.assertEqual(f(b""), None)

    def test_placeholder_svg_is_valid_deterministic_xml(self):
        a = nova_images.placeholder_svg("گل رز")
        b = nova_images.placeholder_svg("گل رز")
        self.assertEqual(a, b)                       # deterministic
        ET.fromstring(a)                             # valid XML
        self.assertIn("گل رز", a)                    # label kept
        self.assertNotIn("<script", a)

    def test_placeholder_svg_escapes_xml(self):
        svg = nova_images.placeholder_svg('rose & "<gift>"')
        ET.fromstring(svg)                           # must not raise
        self.assertIn("&amp;", svg)

    def test_placeholder_differs_per_label(self):
        self.assertNotEqual(nova_images.placeholder_svg("rose"),
                            nova_images.placeholder_svg("tulip"))


# --------------------------------------------------------------------------
# 2. search_images - multi-provider merge
# --------------------------------------------------------------------------
class TestSearchImages(unittest.TestCase):
    def test_empty_or_no_net(self):
        with mock.patch.object(nova_images, "_ns_mod", None):
            self.assertEqual(nova_images.search_images("rose"), [])
        self.assertEqual(nova_images.search_images(""), [])
        self.assertEqual(nova_images.search_images("   "), [])
        self.assertEqual(nova_images.search_images("x" * 500), [])

    def test_merge_dedupe_and_quality_order(self):
        ddg = [_res("big", "http://a/1.jpg", w=1200),
               _res("svg", "http://a/2.svg", w=800),
               _res("tiny", "http://a/3.jpg", w=80)]
        opv = [_res("dup", "http://a/1.jpg", source="openverse"),
               _res("fresh", "http://b/4.jpg", source="openverse", w=700)]
        with mock.patch.object(nova_images, "_ddg_search", return_value=ddg), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=opv), \
             mock.patch.object(nova_images, "_commons_search",
                               return_value=[]):
            out = nova_images.search_images("rose", limit=6)
        urls = [r["url"] for r in out]
        self.assertEqual(len(urls), len(set(urls)), "deduped")
        self.assertIn("http://b/4.jpg", urls, "second provider merged")
        self.assertEqual(len(out), 4)
        # quality order: decent raster first, svg last
        self.assertEqual(out[-1]["url"], "http://a/2.svg")
        self.assertNotIn("http://a/1.jpg", urls[-1:])

    def test_failing_provider_never_fails_the_search(self):
        def boom(q, l, d):
            raise RuntimeError("geo-blocked")
        with mock.patch.object(nova_images, "_ddg_search",
                               side_effect=boom), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=[_res("ok")]), \
             mock.patch.object(nova_images, "_commons_search",
                               return_value=[]):
            out = nova_images.search_images("rose", limit=3)
        self.assertEqual([r["url"] for r in out], ["http://cdn.example.com/x.jpg"])

    def test_stops_at_limit(self):
        ddg = [_res(f"p{i}", f"http://a/{i}.jpg") for i in range(10)]
        with mock.patch.object(nova_images, "_ddg_search", return_value=ddg), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=[]) as opv:
            out = nova_images.search_images("rose", limit=4)
        self.assertEqual(len(out), 4)
        opv.assert_not_called()


# --------------------------------------------------------------------------
# 3. download_image - magic bytes, caps, SSRF layer
# --------------------------------------------------------------------------
class TestDownloadImage(unittest.TestCase):
    def test_no_net_module_refused(self):
        with mock.patch.object(nova_images, "_ns_mod", None):
            rel, meta = nova_images.download_image(
                "http://a/x.png", Path(tempfile.mkdtemp()), "x")
        self.assertIsNone(rel)
        self.assertIn("no network", meta["error"])

    def test_bad_urls_refused(self):
        d = Path(tempfile.mkdtemp())
        for bad in ("", "   ", "x" * 3000):
            rel, _m = nova_images.download_image(bad, d, "x")
            self.assertIsNone(rel)

    def test_deadline_refuses(self):
        import time
        rel, meta = nova_images.download_image(
            "http://a/x.png", Path(tempfile.mkdtemp()), "x",
            deadline=time.monotonic() - 5)
        self.assertIsNone(rel)
        self.assertIn("time budget", meta["error"])

    def test_save_png_with_sniffed_extension(self):
        net = _FakeNet({"http://a/pic": PNG_BYTES})
        d = Path(tempfile.mkdtemp())
        with mock.patch.object(nova_images, "_ns_mod", net):
            name, meta = nova_images.download_image("http://a/pic", d, "rose")
        self.assertTrue(name.startswith("rose-"))
        self.assertTrue(name.endswith(".png"))
        self.assertEqual((d / name).read_bytes(), PNG_BYTES)
        self.assertEqual(meta["bytes"], len(PNG_BYTES))

    def test_html_masquerading_as_image_refused(self):
        net = _FakeNet({"http://a/x.jpg": b"<html>login page</html>"})
        d = Path(tempfile.mkdtemp())
        with mock.patch.object(nova_images, "_ns_mod", net):
            rel, meta = nova_images.download_image("http://a/x.jpg", d, "x")
        self.assertIsNone(rel)
        self.assertIn("not an image", meta["error"])

    def test_idempotent_name_for_same_url(self):
        net = _FakeNet({"http://a/pic": PNG_BYTES})
        d = Path(tempfile.mkdtemp())
        with mock.patch.object(nova_images, "_ns_mod", net):
            n1, _ = nova_images.download_image("http://a/pic", d, "x")
            n2, _ = nova_images.download_image("http://a/pic", d, "x")
        self.assertEqual(n1, n2)

    def test_ssrf_layer_still_pinned_in_nova_search(self):
        # the network layer nova_images reuses must refuse private targets
        self.assertIsNone(nova_search.safe_url("http://127.0.0.1/x.png"))
        self.assertIsNone(nova_search.safe_url("http://169.254.169.254/meta"))
        self.assertIsNone(nova_search.safe_url("http://192.168.1.5/x.png"))
        self.assertIsNone(nova_search.safe_url("file:///etc/passwd"))
        self.assertIsNone(nova_search.safe_url("ftp://host/x"))
        self.assertIsNotNone(nova_search.safe_url("https://example.com/x.png"))

    def test_oversize_refused_before_read(self):
        class _Huge(_FakeNet):
            def http_get_bytes(self, url, timeout=None, max_bytes=1 << 20):
                raise ValueError("payload larger than the %d byte cap"
                                 % max_bytes)
        d = Path(tempfile.mkdtemp())
        with mock.patch.object(nova_images, "_ns_mod", _Huge()):
            rel, meta = nova_images.download_image("http://a/huge", d, "x")
        self.assertIsNone(rel)
        self.assertIn("cap", meta["error"])


# --------------------------------------------------------------------------
# 4. pick_and_save - the search->download chain + cache
# --------------------------------------------------------------------------
class TestPickAndSave(unittest.TestCase):
    def test_happy_path_and_cache_idempotency(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"http://a/1.jpg": PNG_BYTES})
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[_res("red rose",
                                                  "http://a/1.jpg")]), \
             mock.patch.object(nova_images, "_ns_mod", net):
            rel, source, meta = nova_images.pick_and_save("red rose", ws)
            # v7.4: the ratio bucket ("l" = 3:2 default) rides the slug
            self.assertEqual(rel, "assets/images/red-rose-l-"
                                  + rel.split("-")[-1])
            self.assertTrue((ws / rel).is_file())
            self.assertEqual(source, "ddg")
            self.assertEqual(meta["w"], 1200)
            calls_after_first = len(net.calls)
            rel2, source2, _m = nova_images.pick_and_save("red rose", ws)
        self.assertEqual(rel2, rel)
        self.assertEqual(source2, "cache")
        self.assertEqual(len(net.calls), calls_after_first,
                         "cache hit must not re-download")

    def test_tries_next_result_when_first_is_dead(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"http://a/2.jpg": JPG_BYTES})
        results = [_res("dead", "http://a/1.jpg"),
                   _res("alive", "http://a/2.jpg")]
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=results), \
             mock.patch.object(nova_images, "_ns_mod", net):
            rel, _s, _m = nova_images.pick_and_save("rose", ws)
        self.assertIsNotNone(rel)
        self.assertTrue((ws / rel).read_bytes().startswith(b"\xff\xd8"))

    def test_no_results(self):
        ws = Path(tempfile.mkdtemp())
        with mock.patch.object(nova_images, "_ddg_search", return_value=[]), \
             mock.patch.object(nova_images, "_ns_mod", _FakeNet()):
            rel, source, meta = nova_images.pick_and_save("zzz", ws)
        self.assertIsNone(rel)
        self.assertEqual(meta.get("candidates"), 0)

    def test_empty_query(self):
        rel, _s, _m = nova_images.pick_and_save("  ", Path(tempfile.mkdtemp()))
        self.assertIsNone(rel)


# --------------------------------------------------------------------------
# 5. fill_html_images - the deterministic <img> filler
# --------------------------------------------------------------------------
class TestFillHtmlImages(unittest.TestCase):
    def _fill(self, html, name="index.html", net=None, results=None,
              enabled=True):
        ws = Path(tempfile.mkdtemp())
        _write(ws / name, html)
        env = {"NOVA_NO_IMAGES": "1" if not enabled else ""}
        results = results if results is not None else [_res()]
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=results), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_commons_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_ns_mod",
                               net if net is not None else _FakeNet(
                                   {"http://cdn.example.com/x.jpg":
                                    PNG_BYTES})), \
             mock.patch.dict(os.environ, env):
            extras, notes = nova_images.fill_html_images(ws, [name])
        out = (ws / name).read_text(encoding="utf-8")
        return ws, out, extras, notes

    def test_protocol_img_gets_real_photo(self):
        html = ('<html><body><img src="IMG:red rose" alt="گل رز">'
                "</body></html>")
        ws, out, extras, notes = self._fill(html)
        self.assertIn('src="assets/images/', out)
        self.assertNotIn("IMG:", out)
        self.assertIn('alt="گل رز"', out, "alt untouched")
        self.assertIn('loading="lazy"', out)
        self.assertIn('decoding="async"', out)
        self.assertTrue(extras and extras[0][0].startswith("assets/images/"))
        self.assertTrue(any("[img]" in n for n in notes))

    def test_placeholder_host_src_filled_from_alt(self):
        html = ('<html><body><img '
                'src="https://via.placeholder.com/600x400" '
                'alt="blue lake"></body></html>')
        ws, out, extras, _n = self._fill(html)
        self.assertIn('src="assets/images/', out)
        self.assertNotIn("via.placeholder.com", out)

    def test_broken_local_src_filled_from_alt(self):
        html = ('<html><body><img src="images/missing.jpg" '
                'alt="green forest"></body></html>')
        ws, out, _e, _n = self._fill(html)
        self.assertIn('src="assets/images/', out)
        self.assertNotIn("images/missing.jpg", out)

    def test_working_local_src_untouched(self):
        ws = Path(tempfile.mkdtemp())
        ok = ws / "assets" / "images" / "ok.jpg"
        ok.parent.mkdir(parents=True, exist_ok=True)
        ok.write_bytes(JPG_BYTES)
        html = ('<html><body><img src="assets/images/ok.jpg" '
                'alt="kept"></body></html>')
        _write(ws / "index.html", html)
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[_res()]), \
             mock.patch.object(nova_images, "_ns_mod", _FakeNet()), \
             mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}):
            extras, notes = nova_images.fill_html_images(ws, ["index.html"])
        out = (ws / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="assets/images/ok.jpg"', out)
        self.assertEqual(extras, [])
        self.assertEqual(notes, [])

    def test_data_uri_untouched(self):
        """v8.0.1 re-pin: a LARGE embedded photo (>= 15 KB decoded) is
        still left alone; the old pin asserted the coffe8_after bug
        (tiny procedural junk like base64,AAAA also stayed) - tiny
        payloads are now refilled, pinned in test_v801_image_fill.py."""
        big = base64.b64encode(b"x" * 40_000).decode()
        html = ('<html><body><h1>t</h1>'
                '<img src="data:image/png;base64,%s" '
                'alt="d"></body></html>' % big)
        ws, out, extras, notes = self._fill(html)
        self.assertIn("data:image/png;base64,", out)
        self.assertEqual(extras, [])

    def test_remote_working_url_pinned_local(self):
        html = ('<html><body><img src="http://cdn.example.com/x.jpg" '
                'alt="hero"></body></html>')
        ws, out, extras, notes = self._fill(html)
        self.assertIn('src="assets/images/', out,
                      "working remote photo is downloaded local")
        self.assertNotIn("cdn.example.com", out)
        self.assertTrue(any("pinned" in n for n in notes))

    def test_remote_dead_url_404_replaced_by_search(self):
        html = ('<html><body><img src="https://invented.example.net/pic.jpg" '
                'alt="sunset beach"></body></html>')
        ws, out, extras, notes = self._fill(html)
        self.assertIn('src="assets/images/', out)
        self.assertNotIn("invented.example.net", out)

    def test_remote_403_left_alone(self):
        html = ('<html><body><img src="https://pics.example.org/hot.jpg" '
                'alt="cold mountain"></body></html>')
        ws = Path(tempfile.mkdtemp())
        _write(ws / "index.html", html)
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[_res()]), \
             mock.patch.object(nova_images, "_ns_mod",
                               mock.Mock(side_effect=_net403)), \
             mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}):
            extras, notes = nova_images.fill_html_images(ws, ["index.html"])
        out = (ws / "index.html").read_text(encoding="utf-8")
        self.assertIn("https://pics.example.org/hot.jpg", out,
                      "403 = hotlink protection; browser may still show it")
        self.assertEqual(extras, [])

    def test_offline_falls_back_to_local_art_placeholder(self):
        html = ('<html><body><img src="IMG:mountain" alt="m"></body></html>')
        ws, out, extras, notes = self._fill(
            html, results=[], net=_FakeNet())
        self.assertIn('src="assets/images/_ph-', out)
        self.assertTrue(any("placeholder" in n for n in notes))
        svg_rel, svg_bytes = extras[0]
        self.assertTrue(svg_rel.endswith(".svg"))
        ET.fromstring(svg_bytes.decode("utf-8"))

    def test_no_network_module_still_placesholders(self):
        html = ('<html><body><img src="IMG:lake" alt="l"></body></html>')
        ws = Path(tempfile.mkdtemp())
        _write(ws / "index.html", html)
        with mock.patch.object(nova_images, "_ns_mod", None), \
             mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}):
            extras, notes = nova_images.fill_html_images(ws, ["index.html"])
        out = (ws / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="assets/images/_ph-', out)
        self.assertEqual(len(extras), 1)

    def test_kill_switch_disables_everything(self):
        html = ('<html><body><img src="IMG:rose" alt="r"></body></html>')
        ws, out, extras, notes = self._fill(html, enabled=False)
        self.assertIn('src="IMG:rose"', out, "raw output preserved")
        self.assertEqual(extras, [])
        self.assertEqual(notes, [])

    def test_second_page_reuses_query_cache_without_new_download(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"http://cdn.example.com/x.jpg": PNG_BYTES})
        html_a = '<html><body><img src="IMG:rose" alt="r"></body></html>'
        html_b = ('<html><body><img '
                  'src="https://via.placeholder.com/9x9" alt="rose">'
                  "</body></html>")
        _write(ws / "a.html", html_a)
        _write(ws / "b.html", html_b)
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[_res()]), \
             mock.patch.object(nova_images, "_ns_mod", net), \
             mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}):
            nova_images.fill_html_images(ws, ["a.html"])
            downloads_after_a = len(net.calls)
            nova_images.fill_html_images(ws, ["b.html"])
        self.assertEqual(len(net.calls), downloads_after_a,
                         "same query on page 2 must hit the cache")
        b = (ws / "b.html").read_text(encoding="utf-8")
        self.assertIn('src="assets/images/', b)

    def test_subdirectory_page_gets_correct_relative_path(self):
        html = ('<html><body><img src="IMG:rose" alt="r"></body></html>')
        ws, out, _e, _n = self._fill(html, name="pages/about.html")
        self.assertIn('src="../assets/images/', out)

    def test_page_without_imgs_untouched(self):
        html = "<html><body><h1>plain</h1></body></html>"
        ws, out, extras, notes = self._fill(html)
        self.assertEqual(out, html)
        self.assertEqual(extras, [])
        self.assertEqual(notes, [])

    def test_lazy_attrs_not_duplicated(self):
        html = ('<html><body><img src="IMG:rose" alt="r" '
                'loading="lazy"></body></html>')
        ws, out, _e, _n = self._fill(html)
        self.assertEqual(out.count('loading="lazy"'), 1)


    def test_img_tag_with_gt_in_alt_is_handled(self):
        # v7.2 audit: `>` inside a quoted attribute must not truncate the tag
        html = ('<html><body><img src="IMG:rose" alt="a > b">'
                "</body></html>")
        ws, out, extras, _n = self._fill(html)
        self.assertIn('alt="a > b"', out)
        self.assertIn('src="assets/images/', out)

    def test_data_src_attribute_not_confused_with_src(self):
        # v7.2 audit: lazy-load templates carry data-src - the rewrite
        # must hit the REAL src
        html = ('<html><body><img data-src="lazy.png" src="IMG:rose" '
                'alt="r"></body></html>')
        ws, out, _e, _n = self._fill(html)
        self.assertIn('data-src="lazy.png"', out)
        self.assertIn('src="assets/images/', out)
        self.assertNotIn('src="IMG:rose"', out)

    def test_self_closing_img_gets_clean_attrs(self):
        html = '<html><body><img src="IMG:rose" alt="r" /></body></html>'
        ws, out, _e, _n = self._fill(html)
        self.assertIn('loading="lazy"', out)
        self.assertNotIn("/ loading=", out)

    def test_stale_cache_after_undo_does_not_produce_dead_src(self):
        # v7.2 audit: after /undo deletes the asset, a cache-hit rewrite
        # used to point pages at the deleted file forever
        # (v8.0.1: the canned candidate carries the subject - the
        # subject-orphan gate would rightly skip a title-less "a photo")
        html = '<html><body><img src="IMG:rose" alt="r"></body></html>'
        ws = Path(tempfile.mkdtemp())
        _write(ws / "index.html", html)
        net = _FakeNet({"http://cdn.example.com/x.jpg": PNG_BYTES})
        with mock.patch.object(
                nova_images, "_ddg_search",
                return_value=[_res("red rose flower")]), \
             mock.patch.object(nova_images, "_ns_mod", net), \
             mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}):
            nova_images.fill_html_images(ws, ["index.html"])
            asset = next((ws / "assets" / "images").glob("*.png"))
            asset.unlink()                     # exactly what /undo does
            nova_images.fill_html_images(ws, ["index.html"])
        out = (ws / "index.html").read_text(encoding="utf-8")
        target = out.split('src="')[1].split('"')[0]
        self.assertTrue((ws / target).is_file(),
                        f"rewritten src must exist after undo: {target}")

    def test_fill_never_touches_files_outside_workspace(self):
        outside = Path(tempfile.mkdtemp()) / "evil.html"
        outside.write_text('<html><body><img src="IMG:rose" alt="r">'
                           "</body></html>", encoding="utf-8")
        ws = Path(tempfile.mkdtemp())
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[_res()]), \
             mock.patch.object(nova_images, "_ns_mod", _FakeNet()), \
             mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}):
            _extras, notes = nova_images.fill_html_images(
                ws, [str(outside)])
        self.assertIn("outside the workspace", " ".join(notes))
        self.assertIn("IMG:rose", outside.read_text(encoding="utf-8"),
                      "the outside file must stay untouched")

    def test_placeholder_svg_survives_control_characters(self):
        import xml.etree.ElementTree as ET
        svg = nova_images.placeholder_svg("a\x00b\x07c")
        ET.fromstring(svg)

# --------------------------------------------------------------------------
# 6. apply integration - assets ride the SAME undo unit
# --------------------------------------------------------------------------
class TestApplyIntegration(unittest.TestCase):
    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_ni = nova.NONINTERACTIVE
        self._env = os.environ.get("NOVA_NO_IMAGES")
        os.environ["NOVA_NO_IMAGES"] = ""
        self._ddg = nova_images._ddg_search
        self._opv = nova_images._openverse_search
        self._cms = nova_images._commons_search
        self._bng = nova_images._bing_search
        self._ns = nova_images._ns_mod
        nova_images._ddg_search = lambda q, l, d: [
            _res("red rose", "http://cdn.example.com/x.jpg")]
        nova_images._bing_search = lambda q, l, d: []
        nova_images._openverse_search = lambda q, l, d: []
        nova_images._commons_search = lambda q, l, d: []
        nova_images._ns_mod = _FakeNet(
            {"http://cdn.example.com/x.jpg": PNG_BYTES})

    def tearDown(self):
        nova.stream_chat = self._old_stream
        nova.NONINTERACTIVE = self._old_ni
        if self._env is None:
            os.environ.pop("NOVA_NO_IMAGES", None)
        else:
            os.environ["NOVA_NO_IMAGES"] = self._env
        nova_images._ddg_search = self._ddg
        nova_images._openverse_search = self._opv
        nova_images._commons_search = self._cms
        nova_images._bing_search = self._bng
        nova_images._ns_mod = self._ns

    def test_offer_apply_writes_photo_assets_and_undo_covers_them(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            answer = ('=== FILE: index.html ===\n'
                      '<html><body><img src="IMG:red rose" alt="r">'
                      '</body></html>\n=== END ===\nPreview: index.html')

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return answer, True

            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            sess = nova.Session(ws)
            res = nova.chat_turn(sess, "یک سایت گل فروشی بساز", auto=True)
            assets = [a for a in res["applied"]
                      if a.startswith("assets/images/")]
            self.assertTrue(assets, "the downloaded photo joins the batch")
            html = (ws / "index.html").read_text(encoding="utf-8")
            self.assertIn('src="assets/images/', html)
            self.assertTrue((ws / assets[0]).is_file())
            # END-TO-END undo: the photo is part of the SAME snapshot unit
            old_out = sys.stdout
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
            try:
                nova.cmd_undo(sess, "")
            finally:
                sys.stdout.close()
                sys.stdout = old_out
            self.assertFalse((ws / assets[0]).exists(),
                             "/undo must delete the downloaded photo")
            # the html itself was NEW in this first batch too - undo
            # removes it as well (exact snapshot semantics)
            self.assertFalse((ws / "index.html").exists())

    def test_apply_approved_writes_photo_assets_too(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            answer = ('=== FILE: index.html ===\n'
                      '<html><body><img src="IMG:red rose" alt="r">'
                      "</body></html>\n=== END ===\nPreview: index.html")

            def fake_stream(model, msgs, mode, sess=None, section=None):
                return answer, True

            nova.stream_chat = fake_stream
            nova.NONINTERACTIVE = True
            sess = nova.Session(ws)
            sess.confirm_changes = True
            res = nova.chat_turn(sess, "یک سایت بساز", auto=True)
            self.assertEqual(res["applied"], [], "staged, not written")
            ok, r = nova.apply_approved(sess, sess.pending_apply["id"],
                                        ["index.html"], {})
            self.assertTrue(ok)
            self.assertTrue(any(a.startswith("assets/images/")
                                for a in r["applied"]))
            self.assertIn('src="assets/images/',
                          (ws / "index.html").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 7. the [IMG: ...] model token
# --------------------------------------------------------------------------
class TestImgModelToken(unittest.TestCase):
    def setUp(self):
        self._pick = nova_images.pick_and_save

    def tearDown(self):
        nova_images.pick_and_save = self._pick

    def test_registry_and_dispatch(self):
        acts = {a["name"]: a for a in nova.MODEL_ACTIONS}
        self.assertIn("IMG", acts)
        self.assertTrue(acts["IMG"]["needs_ns"])
        found = nova.find_model_action("I'll fetch a photo.\n[IMG: red rose]")
        self.assertIsNotNone(found)
        self.assertEqual(found[0]["name"], "IMG")
        self.assertEqual(found[1], "red rose")
        # a token mentioned inside a sentence must NOT trigger
        self.assertIsNone(
            nova.find_model_action("use [IMG: x] inside your html tags"))

    def test_tool_briefing_teaches_the_token(self):
        self.assertIn("[IMG:", nova.model_tool_section())

    def test_followup_contains_saved_path(self):
        nova_images.pick_and_save = lambda q, ws, **k: (
            "assets/images/rose-123.jpg", "ddg", {"w": 800, "h": 600})
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.ws = Path(td)
            follow = nova._action_img(sess, "red rose")
        self.assertIn("assets/images/rose-123.jpg", follow)
        self.assertIn("ddg", follow)
        self.assertIn("800x600", follow)

    def test_failure_followup_tells_the_model_to_continue(self):
        nova_images.pick_and_save = lambda q, ws, **k: (None, "", {})
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.ws = Path(td)
            follow = nova._action_img(sess, "unicorn photo")
        self.assertIn("no real photo", follow)
        self.assertIn("Do NOT invent URLs", follow)

    def test_missing_module_is_fail_soft(self):
        old = nova.imgsys
        try:
            nova.imgsys = None
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                self.assertIsNone(nova._action_img(sess, "x"))
        finally:
            nova.imgsys = old


# --------------------------------------------------------------------------
# 8. /img + /imgdl commands, registry, help, prompts
# --------------------------------------------------------------------------
class TestCommandsAndRegistry(unittest.TestCase):
    def setUp(self):
        self._ddg = nova_images._ddg_search
        self._ns = nova_images._ns_mod
        nova_images._ddg_search = lambda q, l, d: [
            _res("damavand", "http://cdn.example.com/x.jpg",
                 w=1400, h=800)]
        nova_images._ns_mod = _FakeNet(
            {"http://cdn.example.com/x.jpg": PNG_BYTES})

    def tearDown(self):
        nova_images._ddg_search = self._ddg
        nova_images._ns_mod = self._ns

    def test_tools_registered_once(self):
        cmds = [t["cmd"] for t in nova.TOOLS]
        self.assertEqual(cmds.count("/img"), 1)
        self.assertEqual(cmds.count("/imgdl"), 1)
        self.assertIsNotNone(nova.TOOL_INDEX.get("/img"))
        self.assertIsNotNone(nova.TOOL_INDEX.get("/imgdl"))

    def test_help_payload_includes_img_commands(self):
        payload = nova.web_help_payload()
        items = [i["cmd"] for g in payload["groups"] for i in g["items"]]
        self.assertIn("/img", items)
        self.assertIn("/imgdl", items)
        self.assertEqual(items.count("/img"), 1)
        # every TOOLS entry still appears exactly once
        self.assertEqual(len(items), len(nova.TOOLS))

    def test_cmd_img_searches_downloads_reports(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.ws = Path(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                nova.cmd_img(sess, "mount damavand 1")
            out = buf.getvalue()
            self.assertIn("[1]", out)
            self.assertIn("damavand", out)
            self.assertIn("assets/images/", out)
            self.assertTrue((Path(td) / "assets" / "images").exists())

    def test_cmd_img_usage(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.ws = Path(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                nova.cmd_img(sess, "")
            self.assertIn("usage", buf.getvalue().lower())

    def test_cmd_imgdl_downloads_and_rejects_private(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            sess.ws = Path(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                nova.cmd_imgdl(sess, "http://cdn.example.com/x.jpg hero")
            self.assertIn("assets/images/", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                nova.cmd_imgdl(sess, "http://127.0.0.1:9/x.png")
            self.assertIn("not a downloadable image", buf.getvalue())

    def test_ssrf_guard_is_real_not_stubbed(self):
        # v7.2 audit: the private-URL rejection must be proven against the
        # REAL network layer, not a canned stub response
        import nova_search
        with self.assertRaises(ValueError):
            nova_search.http_get_bytes("http://127.0.0.1:9/x.png")
        with self.assertRaises(ValueError):
            nova_search.http_get_bytes("http://169.254.169.254/latest/meta-data")

    def test_img_token_inside_file_body_does_not_fire(self):
        # v7.2 audit: a commented [IMG: ...] inside generated HTML must
        # never burn a real tool round
        answer = ("=== FILE: index.html ===\n"
                  "<!-- ask for a photo: [IMG: hero banner photo] -->\n"
                  "<html></html>\n=== END ===\nPreview: index.html")
        self.assertIsNone(nova.find_model_action(answer))

    def test_prompts_teach_the_protocol(self):
        self.assertIn('src="IMG:', nova_design.DESIGN_CONTRACT)
        self.assertIn("IMG:english description", nova.BASE_SYSTEM)
        self.assertIn("Never invent image URLs", nova_design.DESIGN_CONTRACT)

    def test_kill_switch_flag_exists(self):
        with mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": "1"}):
            self.assertFalse(nova_images.enabled())
            self.assertFalse(nova_images.available())
        with mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}):
            self.assertTrue(nova_images.enabled())


if __name__ == "__main__":
    unittest.main()
