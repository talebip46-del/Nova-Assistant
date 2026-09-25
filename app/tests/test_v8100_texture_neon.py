#!/usr/bin/env python3
"""v8.11.0 tests: the TEXTURE / GLOW layers - film grain, neon edges,
aurora wash (the model's menu grows; everything stays optional).

"مثلاً بافت/گرین یا حاشیه‌های نئونی و هر چی که توی دیزاین کمک میکنه رو
 اضافه کن و دقت کن باید اختیاری باشه و نباید خلاقیت رو از هوش مصنوعی
 بگیریم"

Pins:
  - parse_layers: the new keys parse exactly like the old ones (words,
    digits, Persian digits, clamps, bare keys, bare 'neon-text',
    per-key 'off', 'all' sensible defaults)
  - _implied_layers: .nv-grain-N / .nv-neon-N / .nv-neon-text /
    .nv-aurora-N classes opt in without any meta
  - _merge_specs: the union knows all six layer keys
  - layers_css: grain (monochrome inline SVG noise, soft-light blend,
    pointer-events:none, @supports + print self-hiding, site mood on
    html::after - an element pages never style), neon (3 levels, the
    declared alias, .nv-neon-text, --nv-neon recolor token, print
    guard), aurora (element wash over background-image, site mood on
    body with base color untouched, the 26s drift behind the usual
    reduced-motion guard, print guard); deterministic, lint-clean,
    only requested layers, byte-identical round-trips
  - design_polish integration: one sheet per batch, cascade link,
    idempotent, union never shrinks, user-made sheet untouched,
    fragments sheet-only, kill switch, honest labels
  - the contract: the menu grows, options-never-rules survives
  - VERSION is 8.11.0, CODENAME is "texture & neon"
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

STYLED_PAGE = ('<!doctype html><html><head>'
               '<meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width, '
               'initial-scale=1">'
               '<title>t</title>'
               '<link rel="stylesheet" href="css/style.css"></head>'
               '<body><h1>x</h1></body></html>')

BARE_PAGE = ('<!doctype html><html><head><title>T</title></head>'
             '<body><h1>Hi</h1><p>x</p></body></html>\n')


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _spec(**kw):
    """A full six-key spec (grain/neon/aurora default to untouched)."""
    s = nova_design._empty_spec()
    s.update(kw)
    return s


# --------------------------------------------------------------------------
# 1. the parser - the menu grows, the grammar stays forgiving
# --------------------------------------------------------------------------
class TestParseNewLayers(unittest.TestCase):
    def test_full_spec_with_new_keys(self):
        s = nova_design.parse_layers(
            "grain=film; neon=glow, aurora=dream")
        self.assertEqual(s, _spec(grain=2, neon=2, aurora=2))

    def test_digits_and_words_mix(self):
        s = nova_design.parse_layers(
            "grain=heavy neon=dramatic aurora=vivid")
        self.assertEqual((s["grain"], s["neon"], s["aurora"]), (4, 3, 3))

    def test_persian_digits_and_clamps(self):
        s = nova_design.parse_layers("grain=۳ neon=۹ aurora=۱")
        self.assertEqual((s["grain"], s["neon"], s["aurora"]), (3, 3, 1))
        s2 = nova_design.parse_layers("grain=0")
        self.assertIsNone(s2["grain"])          # 0 = not wanted

    def test_bare_keys_mean_utilities(self):
        s = nova_design.parse_layers("grain neon-text aurora")
        self.assertEqual((s["grain"], s["neon"], s["aurora"]), (0, 0, 0))

    def test_bare_neon_text_opt_into_neon(self):
        s = nova_design.parse_layers("neon-text")
        self.assertEqual(s["neon"], 0)
        self.assertIsNone(s["grain"])
        self.assertIsNone(s["aurora"])

    def test_per_key_off(self):
        s = nova_design.parse_layers(
            "grain=off neon=none aurora=no")
        self.assertEqual((s["grain"], s["neon"], s["aurora"]),
                         (None, None, None))

    def test_all_covers_the_new_layers(self):
        s = nova_design.parse_layers("all")
        self.assertEqual((s["grain"], s["neon"], s["aurora"]), (2, 1, 1))
        self.assertEqual(s["shadow"], 3)
        self.assertEqual(s["glass"], 2)

    def test_unknown_keys_still_ignored(self):
        s = nova_design.parse_layers("sparkle=9 glitter")
        self.assertEqual(s, _spec())

    def test_never_raises(self):
        self.assertEqual(nova_design.parse_layers(None)["grain"], None)
        self.assertEqual(nova_design.parse_layers(12345)["neon"], None)
        self.assertEqual(nova_design.parse_layers("")["aurora"], None)


class TestImpliedNewLayers(unittest.TestCase):
    def test_grain_class_implies_grain(self):
        spec = nova_design._implied_layers(
            '<section class="nv-grain-2">x</section>')
        self.assertEqual(spec, _spec(grain=0))

    def test_neon_classes_imply_neon(self):
        spec = nova_design._implied_layers(
            '<div class="card nv-neon-3">x</div>'
            '<h1 class="nv-neon-text">y</h1>')
        self.assertEqual(spec, _spec(neon=0))

    def test_aurora_class_implies_aurora(self):
        spec = nova_design._implied_layers(
            '<div class="nv-aurora-1">x</div>')
        self.assertEqual(spec, _spec(aurora=0))

    def test_levels_of_new_classes_are_read(self):
        spec = nova_design._implied_layers(
            '<i class="nv-grain-4 nv-neon-1 nv-aurora-3">')
        self.assertEqual(spec, _spec(grain=0, neon=0, aurora=0))

    def test_meta_declares_only_what_it_says(self):
        # layers_meta reads the META only; the class-implied part is
        # design_polish's union (see the polish tests below)
        html = ('<meta name="nova-layers" content="grain=film">'
                '<div class="nv-neon-2">x</div>')
        spec = nova_design.layers_meta(html)
        self.assertIsNotNone(spec)
        self.assertEqual(spec["grain"], 2)
        self.assertIsNone(spec["neon"])
        self.assertIsNone(spec["aurora"])


class TestMergeNewLayers(unittest.TestCase):
    def test_union_covers_all_six_keys(self):
        merged = nova_design._merge_specs(
            _spec(shadow=2, grain=1), _spec(glass=3, neon=2, aurora=1))
        self.assertEqual(merged, _spec(shadow=2, glass=3, grain=1,
                                       neon=2, aurora=1))

    def test_declared_beats_implied_for_new_layers(self):
        merged = nova_design._merge_specs(
            _spec(grain=3, neon=1), _spec(grain=0, neon=0, aurora=0))
        self.assertEqual(merged["grain"], 3)
        self.assertEqual(merged["neon"], 1)
        self.assertEqual(merged["aurora"], 0)


# --------------------------------------------------------------------------
# 2. the sheet - the new sections
# --------------------------------------------------------------------------
class TestGrainCss(unittest.TestCase):
    def test_utilities_are_safe_overlays(self):
        sheet = nova_design.layers_css(_spec(grain=0))
        self.assertIn("/* nova layer: grain - film texture scale", sheet)
        for i in (1, 2, 3, 4):
            self.assertIn(f".nv-grain-{i}{{position:relative}}", sheet)
            self.assertIn(f".nv-grain-{i}::after{{opacity:", sheet)
        self.assertIn("pointer-events:none", sheet)
        self.assertIn("mix-blend-mode:soft-light", sheet)
        self.assertIn("background-image:url(\"data:image/svg+xml,", sheet)
        self.assertIn("border-radius:inherit", sheet)

    def test_noise_is_inline_and_monochrome(self):
        sheet = nova_design.layers_css(_spec(grain=1))
        self.assertIn("feTurbulence", sheet)
        self.assertIn("feColorMatrix", sheet)      # saturate 0 -> gray
        self.assertNotIn("http://", sheet.replace(
            "http://www.w3.org/2000/svg", ""))     # zero requests

    def test_site_mood_is_an_html_overlay(self):
        sheet = nova_design.layers_css(_spec(grain=3))
        self.assertIn("nova layer: grain mood 3", sheet)
        self.assertIn("@media screen{html::after{", sheet)
        self.assertIn("opacity:0.13", sheet)
        self.assertNotIn("body::after", sheet)     # never the busy one

    def test_self_hiding_fallbacks(self):
        sheet = nova_design.layers_css(_spec(grain=2))
        self.assertIn("@supports not (mix-blend-mode:soft-light){", sheet)
        self.assertIn("@media print{", sheet)
        self.assertIn("display:none", sheet)

    def test_mood_opacities_are_ordered(self):
        for lvl, op in ((1, "0.04"), (2, "0.08"), (3, "0.13"),
                        (4, "0.19")):
            sheet = nova_design.layers_css(_spec(grain=lvl))
            self.assertIn("opacity:" + op, sheet)


class TestNeonCss(unittest.TestCase):
    def test_three_levels_and_hover(self):
        sheet = nova_design.layers_css(_spec(neon=0))
        self.assertIn("/* nova layer: neon - glowing edge scale", sheet)
        for i in (1, 2, 3):
            self.assertIn(f".nv-neon-{i}{{border:", sheet)
            self.assertIn(f".nv-neon-{i}:hover{{box-shadow:", sheet)
        self.assertIn(".nv-neon-text{color:rgb(var(--nv-neon,91,91,214))",
                      sheet)

    def test_recolor_token(self):
        sheet = nova_design.layers_css(_spec(neon=2))
        self.assertIn("var(--nv-neon,91,91,214)", sheet)
        self.assertNotIn("--brand", sheet)         # independent of palette

    def test_alias_only_when_declared(self):
        sheet = nova_design.layers_css(_spec(neon=0))
        self.assertNotIn(".nv-neon{", sheet)
        sheet2 = nova_design.layers_css(_spec(neon=2))
        self.assertIn("nova layer: neon alias 2", sheet2)
        self.assertIn(".nv-neon{", sheet2)
        self.assertIn("border:1px solid", sheet2)  # level-2 rule

    def test_print_guard(self):
        sheet = nova_design.layers_css(_spec(neon=1))
        self.assertIn("@media print{.nv-neon-1,.nv-neon-2,.nv-neon-3,"
                      ".nv-neon-text{box-shadow:none;text-shadow:none}}",
                      sheet)

    def test_dramatic_level_is_thicker(self):
        sheet = nova_design.layers_css(_spec(neon=3))
        self.assertIn(".nv-neon-3{border:2px solid", sheet)


class TestAuroraCss(unittest.TestCase):
    def test_element_wash(self):
        sheet = nova_design.layers_css(_spec(aurora=0))
        self.assertIn("/* nova layer: aurora - ambient gradient wash",
                      sheet)
        for i in (1, 2, 3):
            self.assertIn(f".nv-aurora-{i}{{background-image:", sheet)
        self.assertIn("var(--nv-aurora,91,91,214)", sheet)
        self.assertIn("var(--nv-aurora2,14,165,233)", sheet)
        self.assertNotIn("--brand", sheet)

    def test_site_mood_keeps_the_base_color(self):
        sheet = nova_design.layers_css(_spec(aurora=2))
        self.assertIn("nova layer: aurora mood 2", sheet)
        self.assertIn("body{background-image:", sheet)
        self.assertNotIn("background-color", sheet)   # base untouched
        self.assertIn("background-size:140% 140%", sheet)

    def test_drift_is_reduced_motion_guarded(self):
        sheet = nova_design.layers_css(_spec(aurora=1))
        self.assertIn("nv-aurora-drift 26s ease-in-out infinite alternate",
                      sheet)
        self.assertIn("@media (prefers-reduced-motion:no-preference){"
                      "body{animation:nv-aurora-drift", sheet)
        self.assertIn("@media print{body{animation:none;"
                      "background-image:none}}", sheet)


class TestSheetAssembly(unittest.TestCase):
    SPECS = [
        _spec(grain=3, neon=None, aurora=None),
        _spec(grain=0, neon=2),
        _spec(neon=1, aurora=3),
        _spec(shadow=5, glass=2, grain=4, neon=3, aurora=1,
              motion={"float", "pop"}),
        _spec(grain=0, neon=0, aurora=0),
    ]

    def test_deterministic_and_headered(self):
        for spec in self.SPECS:
            a = nova_design.layers_css(spec)
            self.assertEqual(a, nova_design.layers_css(spec))
            self.assertTrue(a.startswith("/* nova-layers.css"))

    def test_every_new_spec_is_lint_clean(self):
        for spec in self.SPECS:
            ok, problem = nova_quality.preapply_check(
                "nova-layers.css", nova_design.layers_css(spec))
            self.assertTrue(ok, f"{spec}: {problem}")

    def test_only_requested_layers_are_emitted(self):
        sheet = nova_design.layers_css(_spec(grain=2))
        self.assertIn("nova layer: grain", sheet)
        for other in ("nova layer: shadow", "nova layer: glass",
                      "nova layer: neon", "nova layer: aurora",
                      "nova layer: motion"):
            self.assertNotIn(other, sheet)

    def test_roundtrip_through_the_marker_parser(self):
        for spec in self.SPECS:
            sheet = nova_design.layers_css(spec)
            back = nova_design._spec_from_sheet(sheet)
            self.assertEqual(back, spec, spec)
            self.assertEqual(nova_design.layers_css(back), sheet)

    def test_old_sheets_still_round_trip(self):
        # a v8.9-made sheet (no new sections) reads back with the new
        # keys untouched - the union merge never invents layers
        old = nova_design.layers_css({"shadow": 2, "glass": 1,
                                      "motion": {"glow"},
                                      "grain": None, "neon": None,
                                      "aurora": None})
        back = nova_design._spec_from_sheet(old)
        self.assertEqual(back, {"shadow": 2, "glass": 1,
                                "motion": {"glow"},
                                "grain": None, "neon": None,
                                "aurora": None})

    def test_spec_label_includes_new_layers(self):
        self.assertEqual(
            nova_design._spec_label(_spec(grain=2, neon=3, aurora=0)),
            "grain 2/4, neon 3/3, aurora utilities")


# --------------------------------------------------------------------------
# 3. design_polish integration
# --------------------------------------------------------------------------
class TestDesignPolishNewLayers(unittest.TestCase):
    def test_meta_page_gets_sheet_and_link(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   STYLED_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="grain=heavy; '
                       'neon=glow; aurora=dream"></head>'))
            _write(ws / "css" / "style.css", "body{color:teal}")
            extras, notes = nova_design.design_polish(
                ws, ["index.html", "css/style.css"])
            self.assertIn("nova-layers.css", [e[0] for e in extras])
            sheet = dict(extras)["nova-layers.css"]
            self.assertIn("grain mood 4", sheet)
            self.assertIn("neon alias 2", sheet)
            self.assertIn("aurora mood 2", sheet)
            html = (ws / "index.html").read_text(encoding="utf-8")
            i_css = html.index("css/style.css")
            i_layers = html.index("nova-layers.css")
            self.assertLess(i_css, i_layers)
            self.assertLess(i_layers, html.index("</head>"))
            self.assertTrue(any("linked" in n for n in notes))

    def test_implied_new_classes_get_utilities_only(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   STYLED_PAGE.replace("<body><h1>x</h1>",
                       '<body><div class="nv-grain-2 nv-neon-1 nv-aurora-3">'
                       "<h1>x</h1></div>"))
            _write(ws / "css" / "style.css", "body{color:red}")
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            sheet = dict(extras)["nova-layers.css"]
            self.assertIn(".nv-grain-2{", sheet)
            self.assertIn(".nv-neon-1{", sheet)
            self.assertIn(".nv-aurora-3{", sheet)
            self.assertNotIn("grain mood", sheet)
            self.assertNotIn("neon alias", sheet)
            self.assertNotIn("aurora mood", sheet)

    def test_union_grows_across_runs(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "a.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="grain=film">'
                       "</head>"))
            extras, _ = nova_design.design_polish(ws, ["a.html"])
            for rel, content in extras:
                _write(ws / rel, content)
            _write(ws / "b.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="neon=dramatic, '
                       'aurora=vivid"></head>'))
            extras2, notes2 = nova_design.design_polish(ws, ["b.html"])
            sheet2 = dict(extras2)["nova-layers.css"]
            self.assertIn("grain mood 2", sheet2)      # kept
            self.assertIn("neon alias 3", sheet2)      # added
            self.assertIn("aurora mood 3", sheet2)     # added
            self.assertTrue(any("updated" in n for n in notes2))
            extras3, notes3 = nova_design.design_polish(ws, ["a.html"])
            self.assertEqual(extras3, [])
            self.assertEqual(notes3, [])

    def test_user_made_sheet_is_never_touched(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "nova-layers.css",
                   "/* my own layers */ .fancy{color:red}")
            _write(ws / "index.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="grain=heavy">'
                       "</head>"))
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            self.assertNotIn("nova-layers.css", [e[0] for e in extras])
            self.assertTrue((ws / "nova-layers.css").read_text(
                encoding="utf-8").startswith("/* my own layers */"))

    def test_manual_link_with_new_classes(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   '<!doctype html><html><head><title>t</title>'
                   '<link rel="stylesheet" href="nova-layers.css">'
                   '</head><body><div class="nv-grain-3">x</div></body>'
                   "</html>")
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            sheet = dict(extras)["nova-layers.css"]
            self.assertIn(".nv-grain-3{", sheet)
            # classes imply UTILITIES only (level 0) - a mood needs the
            # meta to declare it; and when classes are present the
            # implied branch answers the whole request (v8.9 branch
            # order, untouched): no shadow/glass baseline here
            self.assertNotIn("grain mood", sheet)
            self.assertNotIn(".nv-shadow-1{", sheet)

    def test_fragment_gets_sheet_but_no_link(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "frag.html",
                   '<div class="nv-neon-2">'
                   '<meta name="nova-layers" content="neon=glow">hi</div>')
            extras, _ = nova_design.design_polish(ws, ["frag.html"])
            self.assertIn("nova-layers.css", [e[0] for e in extras])
            self.assertNotIn("<link",
                             (ws / "frag.html").read_text(encoding="utf-8"))

    def test_no_optin_no_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", STYLED_PAGE)
            _write(ws / "css" / "style.css", "body{color:red}")
            extras, notes = nova_design.design_polish(
                ws, ["index.html", "css/style.css"])
            self.assertEqual(extras, [])
            self.assertEqual(notes, [])
            self.assertFalse((ws / "nova-layers.css").exists())

    def test_kill_switch_covers_new_layers(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="grain=4; '
                       'neon=3; aurora=3"></head>'))
            old = os.environ.get("NOVA_NO_DESIGN")
            os.environ["NOVA_NO_DESIGN"] = "1"
            try:
                extras, notes = nova_design.design_polish(
                    ws, ["index.html"])
                self.assertEqual(extras, [])
                self.assertEqual(notes, [])
            finally:
                if old is None:
                    os.environ.pop("NOVA_NO_DESIGN", None)
                else:
                    os.environ["NOVA_NO_DESIGN"] = old


# --------------------------------------------------------------------------
# 4. the contract - the menu grows, the freedom stays
# --------------------------------------------------------------------------
class TestContractNewLayers(unittest.TestCase):
    def test_contract_teaches_the_new_layers(self):
        c = nova_design.DESIGN_CONTRACT
        self.assertIn("grain=1..4", c)
        self.assertIn("neon=1..3", c)
        self.assertIn("aurora=1..3", c)
        self.assertIn(".nv-grain-1..4", c)
        self.assertIn(".nv-neon-1..3", c)
        self.assertIn(".nv-neon-text", c)
        self.assertIn(".nv-aurora-1..3", c)
        self.assertIn("--nv-neon:R,G,B", c)

    def test_contract_keeps_them_optional(self):
        c = nova_design.DESIGN_CONTRACT
        self.assertIn("options, never rules", c)
        self.assertIn("skip freely", c)
        self.assertIn("may omit the tag", c)
        self.assertIn("Choose levels by the site's mood", c)

    def test_creativity_wording_survives(self):
        c = nova_design.DESIGN_CONTRACT
        self.assertIn("Art direction", c)
        self.assertIn("designed, not generated", c)
        self.assertIn("NEVER repeat one template", c)
        self.assertIn("prefers-reduced-motion", c)
        self.assertIn("ONE bold idea for THIS site", c)

    def test_contract_still_teaches_the_v89_layers(self):
        c = nova_design.DESIGN_CONTRACT
        self.assertIn("shadow=1..5", c)
        self.assertIn("glass=1..4", c)
        self.assertIn("motion=float,fade-down", c)
        self.assertIn(".nv-stagger", c)


# --------------------------------------------------------------------------
# 5. version pin
# --------------------------------------------------------------------------
class TestVersion(unittest.TestCase):
    def test_version_is_8_10_0(self):
        self.assertEqual(nova.VERSION, "8.12.0")

    def test_codename_is_texture_neon(self):
        self.assertEqual(nova.CODENAME, "master switch")


if __name__ == "__main__":
    unittest.main()
