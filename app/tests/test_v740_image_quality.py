#!/usr/bin/env python3
"""v7.4.0 tests: the IMAGE QUALITY pass.

"عکسایی که پیدا میکنه سازشون خیلی عجیبه و سایز هر عکس با اونیکی فرق داره
 و حتی بعضی عکس ها قشنگ معموله از یک جای خاص برداشته شدن و روشون متن داره"

Every test pins one fix (all NETWORK-FREE via stubs):

  - quality gates: watermarked stock hosts, clip-art/logo hosts, social
    frames and meme farms NEVER come back from search_images; text-y
    titles (logo/infographic/meme/screenshot...) out; extreme banner and
    infographic ratios out; tiny thumbnails out; gif/svg out
  - false-positive guards: "texture"/"textbook"/"icons of roses" style
    titles must NOT be gated (word-boundary regex)
  - two-pass relaxation: junk-only providers still return results (the
    gates prune junk, they can never return LESS than v7.3 did)
  - normalize_for_page (real Pillow payloads when available):
    EXIF rotation fixed, center-crop to the declared ratio with the
    55%-of-a-side protection, 1600px cap, jpeg re-encode, transparency
    passthrough, animated passthrough, known-tiny -> None, no-Pillow
    no-op
  - fill_html_images: the model's width/height attrs decide the crop;
    files carry dims attrs when the tag had none; the ratio bucket
    keeps square/landscape/portrait slots on separate cache entries;
    searched svg never lands on a page; the :where(img) floor css is
    injected on non-floor pages only
  - pick_and_save / save_result normalize too; /imgdl stays literal
"""
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova_images          # noqa: E402

PIL_OK = importlib.util.find_spec("PIL") is not None
if PIL_OK:
    from PIL import Image   # noqa: E402

PNG_BYTES = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)   # magic-valid junk
JPG_BYTES = (b"\xff\xd8\xff\xe0" + b"\x00" * 64)    # magic-valid junk


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _res(title="a photo", url="http://cdn.example.com/x.jpg", thumb="",
         w=1200, h=800, source="ddg"):
    return {"title": title, "url": url, "thumb": thumb,
            "width": w, "height": h, "source": source}


def _jpg_bytes(w=1200, h=800, color=(180, 60, 60), exif_orientation=None):
    """A REAL jpeg payload (Pillow) - the normalizer can actually work
    with it. exif_orientation=6 -> 90° CW rotation flag (phone shots)."""
    if not PIL_OK:
        return JPG_BYTES
    im = Image.new("RGB", (w, h), color)
    exif = b""
    if exif_orientation:
        from PIL import ImageOps
        buf = io.BytesIO()
        exif = Image.Exif()
        exif[274] = exif_orientation          # Orientation tag
        im.save(buf, "JPEG", quality=90, exif=exif)
        return buf.getvalue()
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _png_bytes(w=600, h=600, transparent=False):
    if not PIL_OK:
        return PNG_BYTES
    mode = "RGBA" if transparent else "RGB"
    im = Image.new(mode, (w, h), (40, 90, 200, 40 if transparent else 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class _FakeNet:
    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.calls = []

    def http_get_bytes(self, url, timeout=None, max_bytes=1 << 20):
        self.calls.append(url)
        payload = self.payloads.get(url)
        if payload is None:
            raise OSError("not found")
        return payload, "image/jpeg", url


# --------------------------------------------------------------------------
# 1. quality gates
# --------------------------------------------------------------------------
class TestQualityGates(unittest.TestCase):
    def test_watermark_stock_hosts_never_pass(self):
        for host in ("shutterstock.com", "gettyimages.com", "alamy.de",
                     "www.123rf.com", "depositphotos.com",
                     "stock.adobe.com", "media.istockphoto.com"):
            self.assertFalse(nova_images._candidate_ok(
                _res(url=f"https://{host}/photo.jpg"), strict=True),
                host)
            self.assertFalse(nova_images._candidate_ok(
                _res(url=f"https://{host}/photo.jpg"), strict=False),
                host)

    def test_clipart_logo_hosts_never_pass(self):
        for host in ("www.freepik.com", "cdn.cleanpng.com", "pngwing.com",
                     "www.flaticon.com", "icons8.com", "pngtree.com",
                     "www.stickpng.com"):
            self.assertFalse(nova_images._candidate_ok(
                _res(url=f"https://{host}/img.png"), strict=True), host)

    def test_social_meme_hosts_never_pass(self):
        for host in ("i.pinimg.com", "pinterest.com", "i.ytimg.com",
                     "imgflip.com", "i.redd.it", "i.imgflip.com",
                     "scontent.fbcdn.net"):
            self.assertFalse(nova_images._candidate_ok(
                _res(url=f"https://{host}/x.jpg"), strict=True), host)

    def test_texty_titles_rejected_strict_only(self):
        for title in ("company logo png", "home icon", "infographic of seo",
                      "marketing chart", "watermark sample", "cat meme",
                      "app screenshot", "smiley sticker"):
            self.assertFalse(nova_images._candidate_ok(
                _res(title=title), strict=True), title)

    def test_text_gate_false_positives_survive(self):
        # word-boundary regex: these REAL photo words must stay
        for title in ("textbook cover", "texture of marble",
                      "vintage poster of roses", "chess diagram opening",
                      "athletics stadium"):  # 'diagram' IS gated -> false
            pass  # (placeholder to keep the loop honest - see below)
        for title in ("textbook cover", "texture of marble",
                      "vintage poster of roses", "athletics stadium"):
            self.assertTrue(nova_images._candidate_ok(
                _res(title=title), strict=True), title)

    def test_extreme_ratios_rejected_strict(self):
        self.assertFalse(nova_images._candidate_ok(
            _res(url="http://a/banner.jpg", w=3000, h=200), strict=True))
        self.assertFalse(nova_images._candidate_ok(
            _res(url="http://a/infographic.jpg", w=400, h=1400),
            strict=True))

    def test_portrait_ok(self):
        self.assertTrue(nova_images._candidate_ok(
            _res(url="http://a/portrait.jpg", w=600, h=900), strict=True))

    def test_tiny_rejected_strict_soft_in_relaxed(self):
        r = _res(w=300, h=200)
        self.assertFalse(nova_images._candidate_ok(r, strict=True))
        self.assertTrue(nova_images._candidate_ok(r, strict=False))

    def test_gif_and_svg_never_pass(self):
        self.assertFalse(nova_images._candidate_ok(
            _res(url="http://a/funny.gif"), strict=True))
        self.assertFalse(nova_images._candidate_ok(
            _res(url="http://a/logo.svg"), strict=True))
        self.assertFalse(nova_images._candidate_ok(
            _res(url="http://a/logo.svg"), strict=False))

    def test_search_still_returns_something_when_all_gate_out(self):
        junk = [_res("logo", "http://a/1.svg", w=500, h=500),
                _res("strip", "http://a/2.jpg", w=3000, h=100)]
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=junk), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_commons_search",
                               return_value=[]):
            out = nova_images.search_images("niche thing", limit=4)
        self.assertEqual(len(out), 2, "gates prune - they never empty")

    def test_search_stops_when_strict_fills_limit(self):
        good = [_res(f"p{i}", f"http://a/{i}.jpg") for i in range(6)]
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=good), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=[]) as opv:
            out = nova_images.search_images("rose", limit=4)
        self.assertEqual(len(out), 4)
        opv.assert_not_called()

    def test_search_prefers_strict_over_soft(self):
        ddg = [_res("small", "http://a/small.jpg", w=300, h=200),
               _res("good", "http://a/good.jpg", w=1200, h=800)]
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=ddg), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_commons_search",
                               return_value=[]):
            out = nova_images.search_images("rose", limit=2)
        self.assertEqual(out[0]["url"], "http://a/good.jpg")


# --------------------------------------------------------------------------
# 2. normalize_for_page (real payloads; skipped without Pillow)
# --------------------------------------------------------------------------
@unittest.skipUnless(PIL_OK, "Pillow not installed")
class TestNormalizeForPage(unittest.TestCase):
    def test_exif_rotation_fixed(self):
        raw = _jpg_bytes(800, 1200, exif_orientation=6)
        out, ext, dims = nova_images.normalize_for_page(raw, "jpg", 1.5)
        self.assertEqual(ext, "jpg")
        self.assertIsNotNone(dims)
        w, h = dims
        self.assertGreater(w, h, "orientation-6 portrait must become landscape")

    def test_center_crop_to_declared_ratio(self):
        out, ext, dims = nova_images.normalize_for_page(
            _jpg_bytes(1600, 900), "jpg", 1.5)
        w, h = dims
        self.assertEqual(ext, "jpg")
        self.assertAlmostEqual(w / h, 1.5, places=1)
        self.assertLess(len(out), 400_000, "re-encoded jpeg stays small")

    def test_resolution_capped_no_upscale(self):
        _o, _e, dims = nova_images.normalize_for_page(
            _jpg_bytes(3000, 2000), "jpg", 1.5)
        self.assertLessEqual(dims[0], 1600)
        _o2, _e2, dims2 = nova_images.normalize_for_page(
            _jpg_bytes(600, 400), "jpg", 1.5)
        self.assertEqual(dims2, (600, 400), "small photos are never upscaled")

    def test_portrait_protected_from_landscape_crop(self):
        _o, _e, dims = nova_images.normalize_for_page(
            _jpg_bytes(600, 900), "jpg", 1.5)
        self.assertEqual(dims, (600, 900),
                         "cropping would cut >55% - portrait stays portrait")

    def test_known_tiny_payload_rejected(self):
        out, _e, _d = nova_images.normalize_for_page(
            _jpg_bytes(100, 80), "jpg", 1.5)
        self.assertIsNone(out, "a 100x80 thumbnail must not reach the page")

    def test_transparent_png_passes_through(self):
        raw = _png_bytes(600, 600, transparent=True)
        out, ext, dims = nova_images.normalize_for_page(raw, "png", 1.5)
        self.assertEqual((out, ext), (raw, "png"))
        self.assertEqual(dims, (600, 600))

    def test_opaque_png_becomes_jpeg(self):
        out, ext, dims = nova_images.normalize_for_page(
            _png_bytes(1600, 900), "png", 1.5)
        self.assertEqual(ext, "jpg")
        self.assertTrue(out.startswith(b"\xff\xd8"))
        self.assertAlmostEqual(dims[0] / dims[1], 1.5, places=1)

    def test_animated_gif_passes_through(self):
        if not PIL_OK:
            self.skipTest("Pillow")
        buf = io.BytesIO()
        Image.new("P", (60, 40)).save(buf, "GIF", save_all=True,
                                      append_images=[Image.new("P", (60, 40))])
        out, ext, _d = nova_images.normalize_for_page(buf.getvalue(), "gif")
        self.assertEqual((out, ext), (buf.getvalue(), "gif"))

    def test_unparseable_payload_fails_open(self):
        out, ext, dims = nova_images.normalize_for_page(PNG_BYTES, "png")
        self.assertEqual((out, ext), (PNG_BYTES, "png"))
        self.assertIsNone(dims)

    def test_no_pillow_noop(self):
        with mock.patch.object(nova_images, "_pil", return_value=(None, None)):
            out, ext, dims = nova_images.normalize_for_page(
                JPG_BYTES, "jpg", 1.5)
        self.assertEqual((out, ext), (JPG_BYTES, "jpg"))

    def test_tag_ratio_parsing(self):
        self.assertEqual(nova_images._tag_ratio(
            '<img src="x" width="1200" height="600">'), 2.0)
        self.assertEqual(nova_images._tag_ratio(
            '<img src="x" width="1200px" height="800px">'), 1.5)
        self.assertIsNone(nova_images._tag_ratio(
            '<img src="x" width="abc" height="600">'))
        self.assertIsNone(nova_images._tag_ratio('<img src="x">'))
        self.assertIsNone(nova_images._tag_ratio(
            '<img src="x" width="3000" height="100">'), )

    def test_ratio_bucket(self):
        f = nova_images._ratio_bucket
        self.assertEqual(f(None), "l")
        self.assertEqual(f(1.5), "l")
        self.assertEqual(f(1.0), "s")
        self.assertEqual(f(0.667), "p")


# --------------------------------------------------------------------------
# 3. fill_html_images integration
# --------------------------------------------------------------------------
def _run_fill(html, name="index.html", net=None, results=None):
    ws = Path(tempfile.mkdtemp())
    _write(ws / name, html)
    results = results if results is not None else [
        _res("red rose", "http://cdn.example.com/x.jpg")]
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
                                _jpg_bytes(1600, 900)})):
        extras, notes = nova_images.fill_html_images(ws, [name])
    out = (ws / name).read_text(encoding="utf-8")
    return ws, out, extras, notes


class TestFillQuality(unittest.TestCase):
    def _fill(self, html, name="index.html", net=None, results=None):
        return _run_fill(html, name=name, net=net, results=results)

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_tag_ratio_decides_the_crop(self):
        html = ('<html><body><img src="IMG:red rose" alt="r" '
                'width="1200" height="600"></body></html>')
        ws, out, extras, _n = self._fill(html)
        src = out.split('src="assets/images/')[1].split('"')[0]
        from PIL import Image as I
        with I.open(io.BytesIO((ws / "assets/images" / src).read_bytes())) as im:
            w, h = im.size
        self.assertAlmostEqual(w / h, 2.0, places=1,
                               msg="model's 2:1 attrs decide the crop")
        self.assertIn('width="1200"', out, "model attrs kept")
        self.assertNotIn('width="1200" height="600" width=', out)

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_dims_attrs_added_when_tag_has_none(self):
        html = '<html><body><img src="IMG:red rose" alt="r"></body></html>'
        ws, out, _e, _n = self._fill(html)
        self.assertRegex(out, r'width="\d{3,4}" height="\d{2,4}"',
                         "explicit size box added")

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_ratio_buckets_get_separate_files(self):
        net = _FakeNet({"http://cdn.example.com/x.jpg":
                        _jpg_bytes(1600, 900)})
        html = ('<html><body>'
                '<img src="IMG:red rose" alt="a" width="1200" height="800">'
                '<img src="IMG:red rose" alt="b" width="400" height="400">'
                '</body></html>')
        ws, out, extras, _n = self._fill(html, net=net)
        srcs = [s.split('"')[0] for s in
                out.split('src="assets/images/')[1:]]
        self.assertEqual(len(srcs), 2)
        self.assertNotEqual(srcs[0], srcs[1],
                            "square slot must not reuse the 3:2 file")

    def test_searched_svg_never_lands_on_the_page(self):
        html = '<html><body><img src="IMG:red rose" alt="r"></body></html>'
        results = [_res("logo", "http://cdn.example.com/logo.svg",
                        w=800, h=800),
                   _res("rose", "http://cdn.example.com/x.jpg")]
        _ws, out, extras, _n = self._fill(html, results=results)
        self.assertTrue(all(e[0].endswith((".jpg", ".png")) for e in extras),
                        str(extras))
        self.assertIn('src="assets/images/', out)

    def test_img_floor_css_injected_on_plain_pages(self):
        html = '<html><body><img src="IMG:red rose" alt="r"></body></html>'
        _ws, out, _e, _n = self._fill(html)
        self.assertIn('id="nova-img-floor"', out)
        self.assertIn(":where(img){max-width:100%;height:auto}", out)
        self.assertIn("</style></body>", out.replace("\n", ""))

    def test_img_floor_css_skipped_on_floor_pages(self):
        html = ('<html><head><link rel="stylesheet" '
                'href="css/nova-ui.css"></head><body>'
                '<img src="IMG:red rose" alt="r"></body></html>')
        ws = Path(tempfile.mkdtemp())
        _write(ws / "index.html", html)
        _write(ws / "css" / "nova-ui.css", "/* floor */")   # REALLY there
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[_res("red rose",
                                                  "http://cdn.example.com/"
                                                  "x.jpg")]), \
             mock.patch.object(nova_images, "_bing_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_openverse_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_commons_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_ns_mod", _FakeNet(
                 {"http://cdn.example.com/x.jpg": _jpg_bytes(1600, 900)})):
            nova_images.fill_html_images(ws, ["index.html"])
        out = (ws / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("nova-img-floor", out)

    def test_img_floor_css_injected_when_floor_link_is_dead(self):
        # v7.4 audit: legacy nested pages link nova-ui.css that is NOT on
        # disk - the marker alone used to suppress the img guard
        html = ('<html><head><link rel="stylesheet" '
                'href="nova-ui.css"></head><body>'
                '<img src="IMG:red rose" alt="r"></body></html>')
        ws, out, _e, _n = self._fill(html)     # no css file created
        self.assertIn('id="nova-img-floor"', out)

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_remote_jpeg_normalized_png_kept(self):
        net = _FakeNet({
            "https://img.example.com/photo.jpg": _jpg_bytes(2400, 1600),
            "https://img.example.com/mark.png": _png_bytes(500, 500),
        })
        html = ('<html><body>'
                '<img src="https://img.example.com/photo.jpg" alt="a">'
                '<img src="https://img.example.com/mark.png" alt="b">'
                '</body></html>')
        ws, out, extras, _n = self._fill(html, net=net)
        from PIL import Image as I
        jpgs = [e for e in extras if e[0].endswith(".jpg")]
        pngs = [e for e in extras if e[0].endswith(".png")]
        self.assertEqual(len(jpgs), 1)
        self.assertEqual(len(pngs), 1)
        with I.open(io.BytesIO(jpgs[0][1])) as im:
            self.assertEqual(im.size, (1600, 1067),
                             "2400x1600 (1.5) -> capped to 1600 wide")
        self.assertEqual(pngs[0][1], _png_bytes(500, 500),
                         "png graphic byte-identical")

    def test_floor_page_attrs_still_added(self):
        html = ('<html><head><link rel="stylesheet" '
                'href="css/nova-ui.css"></head><body>'
                '<img src="IMG:red rose" alt="r"></body></html>')
        _ws, out, _e, _n = self._fill(html)
        self.assertIn('src="assets/images/', out)


# --------------------------------------------------------------------------
# 5. round-6 audit regression pins (image side)
# --------------------------------------------------------------------------
class TestAuditRegressionImages(unittest.TestCase):
    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_tiny_remote_jpeg_does_not_kill_the_page(self):
        """v7.4 audit HIGH: a known-tiny remote jpeg used to crash the
        whole page fill (TypeError on None bytes) - the page stayed
        untouched and earlier photos became orphans."""
        net = _FakeNet({
            "https://img.example.com/tiny.jpg": _jpg_bytes(100, 80),
            "https://cdn.example.com/x.jpg": _jpg_bytes(1600, 900),
        })
        html = ('<html><body>'
                '<img src="https://img.example.com/tiny.jpg" alt="t">'
                '<img src="IMG:red rose" alt="r">'
                '</body></html>')
        ws, out, extras, notes = _run_fill(
            html, net=net,
            results=[_res("red rose", "http://cdn.example.com/x.jpg")])
        self.assertFalse(any("skipped (TypeError" in n for n in notes),
                         str(notes))
        self.assertIn('src="assets/images/', out,
                      "the IMG: tag was still filled")
        self.assertNotIn("https://img.example.com/tiny.jpg", out,
                         "the tiny remote was replaced by a real photo")

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_existing_asset_never_overwritten(self):
        """v7.4 audit: a re-fill with a lost cache used to overwrite a
        pre-existing asset and hand /undo a delete ticket for a file
        Nova never created."""
        net = _FakeNet({"http://cdn.example.com/x.jpg": _jpg_bytes(1600, 900)})
        ws = Path(tempfile.mkdtemp())
        _write(ws / "index.html",
               '<html><body><img src="IMG:red rose" alt="r"></body></html>')
        results = [_res("red rose", "http://cdn.example.com/x.jpg")]
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=results), \
             mock.patch.object(nova_images, "_ns_mod", net):
            extras1, _n = nova_images.fill_html_images(ws, ["index.html"])
            self.assertEqual(len(extras1), 1)
            asset = ws / extras1[0][0]
            asset.write_bytes(b"USER REPLACED THIS PHOTO")
            # cache lost - the fill must still find the file on disk
            with mock.patch.object(nova_images, "_load_cache",
                                   return_value={}):
                extras2, _n2 = nova_images.fill_html_images(ws,
                                                            ["index.html"])
        self.assertEqual(extras2, [],
                         "an existing asset must never be re-downloaded "
                         "or overwritten")
        self.assertEqual(asset.read_bytes(), b"USER REPLACED THIS PHOTO")

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_css_sized_tag_gets_no_attr_dims(self):
        """v7.4 audit: style='height:220px' + added width attr = a
        stretched box; dims must be skipped when inline css sizes it."""
        html = ('<html><body><img src="IMG:red rose" alt="r" '
                'style="height:220px;border-radius:8px"></body></html>')
        _ws, out, _e, _n = _run_fill(html)
        self.assertNotRegex(out, r'width="\d+"[^>]*style=',
                            "no attribute box on a css-sized tag")
        self.assertIn('src="assets/images/', out)

    def test_chart_compound_words_are_not_gated(self):
        self.assertTrue(nova_images._candidate_ok(
            _res(title="Chart-topping hits collection"), strict=True))
        self.assertTrue(nova_images._candidate_ok(
            _res(title="the chart-topping artist portrait",
                 url="http://a/chart-topping-star.jpg"), strict=True))
        # a bare 'chart' title is still gated
        self.assertFalse(nova_images._candidate_ok(
            _res(title="sales chart"), strict=True))

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_remote_budget_separate_from_fill_budget(self):
        """v7.4 audit: one shared counter meant 5 ordinary fills starved
        live remote pins (and vice versa)."""
        net = _FakeNet({
            f"http://dead.example.com/{i}.jpg": None for i in range(5)
        })
        net.payloads["http://cdn.example.com/x.jpg"] = _jpg_bytes(1600, 900)
        imgs = "".join(
            f'<img src="http://dead.example.com/{i}.jpg" alt="d{i}">'
            for i in range(5))
        imgs += '<img src="IMG:red rose" alt="r">'
        html = f"<html><body>{imgs}</body></html>"
        ws, out, extras, notes = _run_fill(
            html, net=net,
            results=[_res("red rose", "http://cdn.example.com/x.jpg")])
        self.assertIn('src="assets/images/', out,
                      "the search fill still ran after 5 dead remotes")

    def test_floor_css_spliced_at_last_body_close(self):
        """v7.4 audit: the first </body> can live inside a script string
        - the splice corrupted the JS."""
        html = ('<html><body><script>var s = "</body> is a string";'
                "</script><img src=\"IMG:red rose\" alt=\"r\"></body></html>")
        _ws, out, _e, _n = _run_fill(html)
        self.assertIn("var s = \"</body> is a string\";", out,
                      "the script string must stay intact")
        self.assertIn('id="nova-img-floor"', out)
        self.assertLess(out.index('id="nova-img-floor"'),
                        out.rindex("</body>"),
                        "the style sits right before the REAL close")

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_url_query_cache_keys_are_normalized(self):
        """v7.4 audit: writers kept '?v=2' in the u-cache keys while the
        reader stripped it - the same URL was downloaded twice."""
        net = _FakeNet({
            "http://cdn.example.com/rose.jpg?v=2": _jpg_bytes(1600, 900),
        })
        ws = Path(tempfile.mkdtemp())
        _write(ws / "a.html",
               '<html><body><img '
               'src="http://cdn.example.com/rose.jpg?v=2" alt="r">'
               "</body></html>")
        _write(ws / "b.html",
               '<html><body><img '
               'src="http://cdn.example.com/rose.jpg" alt="r"></body></html>')
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[]), \
             mock.patch.object(nova_images, "_ns_mod", net):
            nova_images.fill_html_images(ws, ["a.html"])
            first = len(net.calls)
            nova_images.fill_html_images(ws, ["b.html"])
        self.assertEqual(len(net.calls), first,
                         "the same URL (query stripped) must hit the cache")

    def test_imgdl_cache_entry_reused_by_fill(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"https://x.example.com/p.jpg": JPG_BYTES})
        with mock.patch.object(nova_images, "_ns_mod", net):
            rel, _m = nova_images.save_from_url("https://x.example.com/p.jpg",
                                                ws, name="pic")
            _write(ws / "a.html",
                   '<html><body><img '
                   'src="https://x.example.com/p.jpg" alt="r"></body></html>')
            with mock.patch.object(nova_images, "_ddg_search",
                                   return_value=[]):
                nova_images.fill_html_images(ws, ["a.html"])
        self.assertEqual(len(net.calls), 1,
                         "fill must reuse the /imgdl download")

    def test_long_query_relaxes_instead_of_placeholder(self):
        """v7.4: 'red roses bouquet hero' (4 words) comes back EMPTY from
        every provider - the fill must relax to 'red roses bouquet'
        before falling back to placeholder art."""
        calls = []

        def fake_search(q, limit=6, deadline=None):
            calls.append(q)
            return [_res("rose", "http://cdn.example.com/x.jpg")] \
                if len(q.split()) <= 3 else []

        html = ('<html><body><img src="IMG:red roses bouquet hero" '
                'alt="r"></body></html>')
        with mock.patch.object(nova_images, "search_images",
                               side_effect=fake_search):
            _ws, out, extras, _n = _run_fill(html)
        self.assertTrue(any("bouquet hero" == " ".join(c.split()[-2:])
                            for c in calls), calls)
        self.assertIn("red roses bouquet", calls,
                      "the relaxed query must be tried")
        self.assertTrue(extras and extras[0][0].endswith(".jpg"),
                        "a real photo, not a placeholder")

    def test_pick_and_save_relaxes_long_queries(self):
        calls = []

        def fake_search(q, limit=6, deadline=None):
            calls.append(q)
            return [_res("damavand", "http://a/1.jpg")] \
                if len(q.split()) <= 2 else []

        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"http://a/1.jpg": JPG_BYTES})
        with mock.patch.object(nova_images, "search_images",
                               side_effect=fake_search), \
             mock.patch.object(nova_images, "_ns_mod", net):
            rel, _s, _m = nova_images.pick_and_save(
                "mount damavand iran panorama", ws)
        self.assertIsNotNone(rel)
        self.assertIn("mount damavand iran", calls,
                      "relaxed word-by-word (never below 2 words)")


# --------------------------------------------------------------------------
# 4. tools API consistency
# --------------------------------------------------------------------------
class TestToolsApiQuality(unittest.TestCase):
    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_pick_and_save_normalizes(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"http://a/1.jpg": _jpg_bytes(2400, 1600)})
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=[_res("rose", "http://a/1.jpg")]), \
             mock.patch.object(nova_images, "_ns_mod", net):
            rel, _s, meta = nova_images.pick_and_save("rose", ws)
        self.assertIsNotNone(rel)
        self.assertEqual(meta["w"], 1600)
        self.assertEqual(meta["h"], 1067)
        with open(ws / rel, "rb") as fh:
            self.assertTrue(fh.read(3).startswith(b"\xff\xd8"))

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_pick_and_save_skips_tiny_candidates(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"http://a/1.jpg": _jpg_bytes(100, 80),
                        "http://a/2.jpg": _jpg_bytes(1200, 800)})
        results = [_res("thumb", "http://a/1.jpg", w=1200, h=800),
                   _res("good", "http://a/2.jpg")]
        with mock.patch.object(nova_images, "_ddg_search",
                               return_value=results), \
             mock.patch.object(nova_images, "_ns_mod", net):
            rel, _s, _m = nova_images.pick_and_save("rose", ws)
        self.assertIsNotNone(rel)
        self.assertIn("http://a/1.jpg", net.calls[0],
                      "tiny candidate fetched first...")
        self.assertIn("http://a/2.jpg", net.calls[1],
                      "...rejected by the normalizer, next one tried")
        from PIL import Image as I
        with I.open(ws / rel) as im:
            self.assertEqual(im.size, (1200, 800),
                             "the saved photo is the GOOD one")

    def test_imgdl_stays_literal(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"https://x.example.com/p.jpg": JPG_BYTES})
        with mock.patch.object(nova_images, "_ns_mod", net):
            rel, _m = nova_images.save_from_url("https://x.example.com/p.jpg",
                                                ws, name="pic")
        self.assertIsNotNone(rel)
        self.assertEqual((ws / rel).read_bytes(), JPG_BYTES,
                         "/imgdl must keep the exact bytes")

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_save_result_normalizes(self):
        ws = Path(tempfile.mkdtemp())
        net = _FakeNet({"http://a/1.jpg": _jpg_bytes(1600, 900)})
        with mock.patch.object(nova_images, "_ns_mod", net):
            rel, meta = nova_images.save_result(
                {"title": "rose", "url": "http://a/1.jpg",
                 "width": 1600, "height": 900}, ws)
        self.assertIsNotNone(rel)
        self.assertEqual((meta["w"], meta["h"]), (1350, 900),
                         "16:9 source center-cropped to the 3:2 default")


if __name__ == "__main__":
    unittest.main()
