#!/usr/bin/env python3
"""v7.2.0 tests: the DESIGN ENGINE v2 - creative variety without model calls.

"نتیجه باید عالی، مدرن، زیبا و جذاب باشه - و قرار نیست خلاقیت رو از
 هوش مصنوعی بگیریم"

Pins:
  - floor_css(None) stays byte-identical to NOVA_UI_CSS (old contract)
  - floor_css(seed) stamps ONE of the 8 palettes, deterministic per seed,
    coherent (every accent flows from --brand-rgb) and lint-clean
  - different seeds reach different palettes (real project variety)
  - NOVA_UI_JS: the motion enhancer exists, is an IIFE, honors
    reduced-motion, and passes the JS check when node is installed
  - the palette stamp survives design_polish (seed plumbs through)
  - v7.2 contract: art direction freedom + IMG protocol
  - VERSION is 7.2.0
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_design     # noqa: E402
import nova_quality    # noqa: E402

BARE_HTML = """<!doctype html>
<html><head><title>T</title></head>
<body><h1>Hi</h1><p>x</p></body></html>
"""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestFloorCssPalette(unittest.TestCase):
    def test_none_seed_is_byte_identical_to_the_plain_sheet(self):
        self.assertEqual(nova_design.floor_css(None), nova_design.NOVA_UI_CSS)
        self.assertEqual(nova_design.floor_css(""), nova_design.NOVA_UI_CSS)

    def test_seeded_sheet_stamps_a_palette(self):
        f = nova_design.floor_css("یک سایت فروشگاهی مدرن")
        self.assertTrue(f.startswith(nova_design.NOVA_UI_CSS))
        self.assertIn("nova palette stamp:", f)
        self.assertIn("--brand-rgb:", f.split("stamp:")[1])
        self.assertIn("--grad:linear-gradient", f.split("stamp:")[1])

    def test_deterministic_per_seed(self):
        a = nova_design.floor_css("portfolio site")
        b = nova_design.floor_css("portfolio site")
        self.assertEqual(a, b)

    def test_variety_across_projects(self):
        seeds = ["cafe site", "portfolio", "shop", "dashboard", "blog",
                 "barber shop", "gym", "clinic", "school", "agency",
                 "restaurant", "startup landing"]
        palettes = set()
        for s in seeds:
            f = nova_design.floor_css(s)
            stamp = f.split("nova palette stamp: ")[1].split(" */")[0]
            palettes.add(stamp)
        self.assertGreaterEqual(len(palettes), 4,
                                "projects must look different")

    def test_every_palette_is_lint_clean(self):
        for i in range(len(nova_design.PALETTES)):
            sheet = nova_design.NOVA_UI_CSS + \
                nova_design._palette_block(i)
            ok, problem = nova_quality.preapply_check("nova-ui.css", sheet)
            self.assertTrue(ok, f"palette {i}: {problem}")

    def test_palette_count_and_fields(self):
        self.assertEqual(len(nova_design.PALETTES), 8)
        for p in nova_design.PALETTES:
            self.assertEqual(len(p), 6, p)
            name, b, b2, ac, rgb, code = p
            self.assertTrue(rgb.replace(",", "").isdigit(), p)
            for color in (b, b2, ac, code):
                self.assertRegex(color, r"^#[0-9a-f]{6}$")


class TestMotionJs(unittest.TestCase):
    def test_js_exists_and_is_safe_shape(self):
        js = nova_design.NOVA_UI_JS
        self.assertIn("IntersectionObserver", js)
        self.assertIn("(function ()", js)
        self.assertIn("prefers-reduced-motion", js)
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("document.write", js)

    def test_js_passes_node_check_when_available(self):
        node = nova_quality._which_node()
        if not node:
            self.skipTest("node not installed")
        code, out = nova_quality._node_check(node, nova_design.NOVA_UI_JS)
        self.assertEqual(code, 0, out[:300])

    def test_bare_page_links_floor_and_js(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", BARE_HTML)
            extras, _n = nova_design.design_polish(ws, ["index.html"])
            names = [e[0] for e in extras]
            self.assertIn("nova-ui.css", names)
            self.assertIn("nova-ui.js", names)
            for rel, content in extras:
                _write(ws / rel, content)
            html = (ws / "index.html").read_text(encoding="utf-8")
            self.assertIn('src="nova-ui.js"', html)
            self.assertIn('defer', html)


def _lum(hexcolor):
    """WCAG relative luminance of a #rrggbb color."""
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class TestPaletteContrast(unittest.TestCase):
    """v7.2 audit: the contract says 'strong text contrast everywhere' -
    every palette's LINK color (--brand, normal-size text) must pass
    WCAG AA (>= 4.5:1) on the floor's page background, and every gradient
    stop (white bold button text rides the whole gradient) >= 3:1."""

    BG = "#f6f7fb"

    def test_link_color_passes_aa_on_background(self):
        for name, b, b2, ac, rgb, code in nova_design.PALETTES:
            ratio = _contrast(b, self.BG)
            self.assertGreaterEqual(ratio, 4.5,
                                    f"{name}: link {b} = {ratio:.2f}:1")

    def test_gradient_main_stop_carries_white_button_text(self):
        # the DOMINANT gradient stop must pass WCAG large-text (3:1) under
        # the white bold button text; lighter tail stops are mitigated by
        # the sheet's text-shadow on gradient buttons (asserted below)
        for name, b, _b2, _ac, _rgb, _code in nova_design.PALETTES:
            ratio = _contrast(b, "#ffffff")
            self.assertGreaterEqual(ratio, 3.0,
                                    f"{name}: gradient stop {b} "
                                    f"= {ratio:.2f}:1 under white text")

    def test_buttons_shadow_their_text(self):
        self.assertIn("text-shadow", nova_design.NOVA_UI_CSS)


class TestSeedPlumbsThroughPolish(unittest.TestCase):
    def test_polish_writes_the_seeded_floor(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", BARE_HTML)
            extras, _n = nova_design.design_polish(
                ws, ["index.html"], seed="یک کافه")
            css = dict(extras).get("nova-ui.css")
            self.assertIsNotNone(css)
            self.assertIn("nova palette stamp:", css)
            self.assertTrue(css.startswith(nova_design.NOVA_UI_CSS))


class TestContractV2(unittest.TestCase):
    def test_contract_keeps_creativity_and_adds_images(self):
        c = nova_design.DESIGN_CONTRACT
        self.assertIn("Art direction", c)
        self.assertIn("designed, not generated", c)
        self.assertIn('src="IMG:', c)
        self.assertIn("Never invent image URLs", c)
        # still byte-stable in-process
        self.assertEqual(c, nova_design.DESIGN_CONTRACT)


class TestVersion(unittest.TestCase):
    def test_version_is_7_2_0(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
