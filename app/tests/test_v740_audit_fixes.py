#!/usr/bin/env python3
"""v7.4.0 tests: ROUND-6 AUDIT REGRESSION PINS (non-image findings).

Every test pins one execution-PROVEN finding from the 4-agent audit:

  design (nova_design):
    - a NESTED page links ../nova-ui.css / ../nova-ui.js (used to be
      root-relative -> 404 floor + motion js dead forever)
    - a legacy nested page with a root-relative nova-ui.js link gets a
      real copy at pages/nova-ui.js on the self-heal pass
    - WCAG AA: every palette's BUTTON gradient (--grad-btn) carries the
      white bold text at >=4.5:1 on every stop - even after the hover
      brightness(1.06) - while the decorative --grad stays vibrant
  fonts (nova_fonts + the hooks in nova.py):
    - a foreign (user's own) file at a library path is never
      overwritten, so /undo can never delete it
    - a <meta name="nova-fonts"> override on an ALREADY-STAMPED page
      regenerates nova-fonts.css declaring the requested family (used
      to copy dead binaries and skip the sheet)
    - the model's own batch writing nova-fonts.css is not touched by
      the font hook (the double undo entry resurrected it on /undo)
    - 'ساخت سایت فروشگاه' is minimal-clean, not creative-artistic
  web (web_server):
    - a GET with a Content-Length body no longer smuggles a pipelined
      request (the body is drained; exactly ONE response comes back)
    - an https:// origin on a matching port is rejected (RFC 6454)
  modules:
    - knowledge._unpack_vec returns None on a corrupt blob (was a
      NameError that silently disabled dense hybrid search)
  commands:
    - /img with n > results prints the ACTUAL pick number it downloads
"""
import io
import os
import re
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_design     # noqa: E402
import nova_fonts      # noqa: E402
import web_server      # noqa: E402


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _contrast(a, b):
    return nova_design._wcag_contrast(a, b)


# --------------------------------------------------------------------------
# design
# --------------------------------------------------------------------------
class TestDesignNestedFloor(unittest.TestCase):
    def test_nested_page_gets_resolvable_floor_links(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "pages" / "about.html",
                   "<html><head><title>t</title></head><body><p>hi</p>"
                   "</body></html>")
            extras, notes = nova_design.design_polish(ws, ["pages/about.html"],
                                                      seed="a site")
            rels = [e[0] for e in extras]
            self.assertIn("nova-ui.css", rels)
            self.assertIn("nova-ui.js", rels)
            # apply the extras to disk, then verify the page RESOLVES them
            for rel, data in extras:
                _write(ws / rel, data)
            html = (ws / "pages" / "about.html").read_text(encoding="utf-8")
            m = re.search(r'href="([^"]*nova-ui\.css)"', html)
            self.assertIsNotNone(m)
            self.assertTrue((ws / "pages" / m.group(1)).is_file(),
                            "the css link must resolve from the nested page")
            self.assertNotEqual(m.group(1), "nova-ui.css",
                                "root-relative link from a nested page = 404")
            sm = re.search(r'src="([^"]*nova-ui\.js)"', html)
            self.assertIsNotNone(sm)
            self.assertTrue((ws / "pages" / sm.group(1)).is_file(),
                            "the js link must resolve from the nested page")

    def test_legacy_nested_script_self_heals(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            # a v7.0-7.3 style nested page: root-relative css+js links,
            # neither file anywhere on disk
            _write(ws / "pages" / "old.html",
                   '<html><head><link rel="stylesheet" href="nova-ui.css">'
                   '<script src="nova-ui.js" defer></script></head>'
                   "<body><p>x</p></body></html>")
            extras, _n = nova_design.design_polish(ws, ["pages/old.html"],
                                                   seed=None)
            rels = [e[0] for e in extras]
            self.assertIn("pages/nova-ui.css", rels,
                          "case-1 fills the css at the page-relative path")
            self.assertIn("pages/nova-ui.js", rels,
                          "v7.4 self-heal: the motion js gets a real copy")

    def test_button_gradient_passes_wcag_in_every_palette(self):
        stop_re = re.compile(r"(#[0-9a-fA-F]{6})")
        for idx in range(len(nova_design.PALETTES)):
            name = nova_design.PALETTES[idx][0]
            block = nova_design._palette_block(idx)
            m = re.search(r"--grad-btn:linear-gradient\(135deg,"
                          r"(#.{6}) 0%,(#.{6}) 55%,(#.{6}) 100%\)", block)
            self.assertIsNotNone(m, name)
            for stop in m.groups():
                self.assertGreaterEqual(_contrast(stop, "#ffffff"), 4.5,
                                        f"{name}: {stop} under white")
                # the hover filter brightens by 1.06 - must STILL pass
                r, g, b = (int(stop[i:i + 2], 16) for i in (1, 3, 5))
                bright = "#{:02x}{:02x}{:02x}".format(
                    min(255, int(r * 1.06)), min(255, int(g * 1.06)),
                    min(255, int(b * 1.06)))
                self.assertGreaterEqual(_contrast(bright, "#ffffff"), 4.5,
                                        f"{name}: {stop} hovered")
            # the decorative gradient keeps the ORIGINAL vibrant colors
            self.assertIn(nova_design.PALETTES[idx][1], block)

    def test_base_sheet_carries_grad_btn(self):
        self.assertIn("--grad-btn", nova_design.NOVA_UI_CSS)
        self.assertIn("background:var(--grad-btn)",
                      nova_design.NOVA_UI_CSS)

    def test_weak_model_cards_alias_is_a_real_grid(self):
        """v7.4: weak models keep inventing .cards - the floor now gives
        the name a real 3-column grid with proper collapse."""
        css = nova_design.NOVA_UI_CSS
        self.assertIn(".cards{display:grid", css)
        self.assertIn(".cards{grid-template-columns:repeat(2,1fr)}", css,
                      "tablet collapse")
        self.assertIn(".cards{grid-template-columns:1fr}", css,
                      "mobile stack")


# --------------------------------------------------------------------------
# fonts
# --------------------------------------------------------------------------
class TestFontsAuditFixes(unittest.TestCase):
    WS_PAGE = ("<html><head><title>t</title></head><body><h1>سلام</h1>"
               "<p>متن آزمایشی</p></body></html>")

    def test_foreign_file_at_library_path_never_touched(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", self.WS_PAGE)
            got = nova_fonts.find("Vazirmatn")
            self.assertIsNotNone(got, "library must contain Vazirmatn")
            entry = got[1]
            rel = next(iter(entry["weights"].values()))
            dest_rel = "fonts/" + next(iter(rel.values())).replace("\\", "/")
            victim = ws / dest_rel
            _write(victim, "")                      # empty -> different size
            victim.write_bytes(b"USER'S OWN FONT FILE")
            extras, notes = nova_fonts.install_pass(ws, ["index.html"],
                                                    request_text="یک سایت")
            self.assertIn(dest_rel, [e[0] for e in extras] +
                          [dest_rel])               # either way:
            self.assertEqual(victim.read_bytes(), b"USER'S OWN FONT FILE",
                             "the user's own file must survive byte-identical")
            self.assertNotIn((dest_rel, victim.read_bytes()), extras)

    def test_meta_override_on_stamped_page_regenerates_css(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            page = _write(ws / "index.html", self.WS_PAGE)
            extras, _n = nova_fonts.install_pass(ws, ["index.html"],
                                                 request_text="یک سایت")
            for rel, data in extras:                # apply turn 1
                target = ws / rel
                if isinstance(data, bytes):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                else:
                    _write(target, data)
            # turn 2: the model adds its own meta override
            text = page.read_text(encoding="utf-8")
            text = text.replace(
                "<title>",
                '<meta name="nova-fonts" '
                'content="heading=Lalezar; body=Vazirmatn"><title>')
            _write(page, text)
            extras2, notes2 = nova_fonts.install_pass(ws, ["index.html"],
                                                      request_text="یک سایت")
            self.assertTrue(extras2 or any("Lalezar" in n for n in notes2),
                            "the override must produce SOMETHING")
            # prefer the JUST-GENERATED sheet (the disk copy is turn 1's)
            css = next((d for r, d in extras2
                        if r == "nova-fonts.css"), "")
            if not css and (ws / "nova-fonts.css").is_file():
                css = (ws / "nova-fonts.css").read_text(encoding="utf-8")
            self.assertIn("Lalezar", css,
                          "the requested family must be DECLARED now")

    def test_hook_never_touches_model_batch_files(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            model_css = "/* my own fonts */ body { font-family: X; }"
            target = _write(ws / "nova-fonts.css", model_css)

            class FakeSession:
                pass

            fake = FakeSession()
            fake.ws = ws
            fake.touched = {}
            fake.last_batch = []

            snap_batch = []
            applied = ["nova-fonts.css"]        # the model wrote it
            with mock.patch.object(nova_fonts, "install_pass",
                                   return_value=(
                                       [("nova-fonts.css",
                                         "/* nova sheet */")],
                                       ["fonts: note"])):
                nova._font_install_hook(fake, applied, snap_batch)
            self.assertEqual(target.read_text(encoding="utf-8"), model_css,
                             "the model's file must stay untouched")
            self.assertEqual(snap_batch, [], "no undo entry, no resurrection")

    def test_sakht_verb_is_not_a_mood(self):
        self.assertEqual(nova_fonts.detect_mood("ساخت سایت فروشگاه"),
                         "minimal-clean")
        # the AI-app request is modern-tech ('هوش مصنوعی') - the point is
        # that the bare verb 'ساخت' never drags it to creative-artistic
        mood = nova_fonts.detect_mood("ساخت اپ هوش مصنوعی")
        self.assertNotEqual(mood, "creative-artistic")
        self.assertEqual(mood, "modern-tech")
        # a REAL creative request still matches
        self.assertEqual(nova_fonts.detect_mood("یک گالری هنری خلاق"),
                         "creative-artistic")


# --------------------------------------------------------------------------
# web server
# --------------------------------------------------------------------------
class TestWebServerAuditFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import nova_security as _nsec
            _nsec.API_LIMITER.reset()
            _nsec.SECURE_API_LIMITER.reset()
            _nsec.AUTH_THROTTLE.reset()
        except Exception:
            pass
        os.environ["NOVA_DISABLED_MODULES"] = ""
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_web74_"))
        web_server.nova = nova
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        cls.httpd = web_server._make_server(
            {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)})
        cls.port = cls.httpd.server_address[1]
        t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_get_with_body_no_smuggling(self):
        """The v6.9 class fix covered POST-4xx; a GET with a body used to
        desync the keep-alive loop (2 responses, second = smuggled)."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) \
                as s:
            smuggled = (b"GET /favicon.ico HTTP/1.1\r\nHost: x\r\n\r\n")
            req = (b"GET /api/info HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                   b"Content-Length: " + str(len(smuggled)).encode()
                   + b"\r\n\r\n" + smuggled)
            s.sendall(req)
            s.settimeout(3)
            buf = b""
            try:
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if buf.count(b"HTTP/1.1 ") >= 2:
                        break
            except socket.timeout:
                pass
        self.assertEqual(buf.count(b"HTTP/1.1 "), 1,
                         "exactly ONE response - the body was drained")

    def test_https_origin_on_matching_port_rejected(self):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(
            self.base_url() + "/api/info",
            headers={"Origin": f"https://127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 403,
                         "scheme+host+port origin: https != http server")

    def base_url(self):
        return "http://127.0.0.1:%d" % self.port


class TestKnowledgeUnpack(unittest.TestCase):
    def test_corrupt_blob_returns_none(self):
        from nova_modules import knowledge as k
        self.assertIsNone(k._unpack_vec(b"ab"))
        self.assertEqual(len(k._unpack_vec(b"\x00" * (k.EMB_DIM * 4))),
                         k.EMB_DIM)


class TestImgPickMessage(unittest.TestCase):
    def test_fallback_prints_actual_pick(self):
        old_si = nova.imgsys.search_images
        old_sr = nova.imgsys.save_result

        def fake_search(q, limit=8, deadline=None):
            return [{"title": "a", "url": "http://a/1.jpg", "thumb": "",
                     "width": 1000, "height": 700, "source": "ddg"},
                    {"title": "b", "url": "http://a/2.jpg", "thumb": "",
                     "width": 900, "height": 600, "source": "ddg"}]

        def fake_save(result, ws, deadline=None):
            return "assets/images/x.jpg", {"bytes": 1024}

        nova.imgsys.search_images = fake_search
        nova.imgsys.save_result = fake_save
        try:
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                sess.ws = Path(td)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    nova.cmd_img(sess, "red rose 5")
                out = buf.getvalue()
        finally:
            nova.imgsys.search_images = old_si
            nova.imgsys.save_result = old_sr
        self.assertIn("using [1]", out)
        self.assertIn("pick [1]", out)
        self.assertNotIn("pick [5]", out,
                         "the message must name the ACTUAL download")


if __name__ == "__main__":
    unittest.main()
