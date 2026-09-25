#!/usr/bin/env python3
"""v8.11.0 tests: the OPTIONAL DESIGN LAYERS - the model's own menu.

"بیا nova design رو پیشرفته کنیم و برای دیزاین چند لایه اختیاری اضافه
 کنیم که هوش مصنوعی خودش انتخاب کنه اینها رو اضافه کنه یا خیر و یا اصلا
 چه جاهایی اضافه کند ... نباید خلاقیت رو از هوش مصنوعی گرفت و اینها
 گزینه هستن و قانون نیستند"

Pins:
  - parse_layers: the forgiving opt-in grammar (words/digits/Persian
    digits, ':' or '=', commas/semicolons/spacing, bare keys, 'all',
    per-key and whole-spec 'off', unknown things ignored)
  - layers_meta: the <meta name="nova-layers"> reader (fail-soft)
  - _implied_layers: using the nv- classes IS opting in (no meta needed)
  - _merge_specs: declared mood beats implied, stronger mood wins
  - layers_css: deterministic, lint-clean, only requested layers, each
    behind a stable 'nova layer:' marker; round-trips through
    _spec_from_sheet byte-identically
  - the shadow scale (5 levels + hover lift + site-wide mood remap),
    the frosted glass scale (4 levels, color/font-free tint token,
    @supports fallback), the motion presets (reduced-motion guards,
    entrances run once, stagger helper)
  - design_polish integration: sheet written once per batch, link
    injected before </head> AFTER the floor (cascade), idempotent,
    nested-page ../ prefix, wrong-folder copy, manual link = request,
    user-made sheet never touched, Nova-made sheet grows (union never
    shrinks), fragments get the sheet but no link, kill switch
  - the contract: options, never rules + the creativity wording
  - VERSION is 8.11.0
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


# --------------------------------------------------------------------------
# 1. the parser - forgiving by design (options, never rules)
# --------------------------------------------------------------------------
class TestParseLayers(unittest.TestCase):
    def test_full_spec(self):
        s = nova_design.parse_layers(
            "shadow=dramatic; glass=2, motion=float,fade-down")
        self.assertEqual(s, {"shadow": 5, "glass": 2,
                             "motion": {"float", "fade-down"},
                                 "grain": None, "neon": None, "aurora": None})

    def test_colon_separators_and_words(self):
        s = nova_design.parse_layers("shadow:subtle glass:mist motion:pop")
        self.assertEqual(s, {"shadow": 1, "glass": 4, "motion": {"pop"},
            "grain": None, "neon": None, "aurora": None})

    def test_digits_clamp_into_range(self):
        s = nova_design.parse_layers("shadow=9 glass=0")
        self.assertEqual(s, {"shadow": 5, "glass": None, "motion": set(),
            "grain": None, "neon": None, "aurora": None})

    def test_persian_digits(self):
        s = nova_design.parse_layers("shadow=۴ glass=۳")
        self.assertEqual(s, {"shadow": 4, "glass": 3, "motion": set(),
            "grain": None, "neon": None, "aurora": None})

    def test_bare_keys_mean_utilities(self):
        s = nova_design.parse_layers("shadow glass motion")
        self.assertEqual(s, {"shadow": 0, "glass": 0,
                             "motion": set(nova_design._MOTION_PRESETS),
                                 "grain": None, "neon": None, "aurora": None})

    def test_bare_preset_name_is_motion_shorthand(self):
        s = nova_design.parse_layers("float")
        self.assertEqual(s, {"shadow": None, "glass": None,
                             "motion": {"float"},
                                 "grain": None, "neon": None, "aurora": None})

    def test_all_means_sensible_defaults(self):
        s = nova_design.parse_layers("all")
        self.assertEqual(s, {"shadow": 3, "glass": 2,
                             "motion": set(nova_design._MOTION_PRESETS),
                             "grain": 2, "neon": 1, "aurora": 1})
        s2 = nova_design.parse_layers("motion=all")
        self.assertEqual(s2["motion"], set(nova_design._MOTION_PRESETS))

    def test_off_and_empty_mean_nothing(self):
        empty = {"shadow": None, "glass": None, "motion": set(),
            "grain": None, "neon": None, "aurora": None}
        for raw in ("", "off", "none", "false", "no", "0",
                    "shadow=off glass=none motion=off", "fancy=stuff"):
            self.assertEqual(nova_design.parse_layers(raw), empty, raw)

    def test_plus_separated_motion_list(self):
        s = nova_design.parse_layers("motion=float+fade-up+pop")
        self.assertEqual(s["motion"], {"float", "fade-up", "pop"})

    def test_case_insensitive_and_never_raises(self):
        self.assertEqual(nova_design.parse_layers("SHADOW=Dramatic")["shadow"],
                         5)
        self.assertEqual(nova_design.parse_layers(None)["shadow"], None)
        self.assertEqual(nova_design.parse_layers(12345)["shadow"], None)


class TestLayersMeta(unittest.TestCase):
    def test_reads_the_tag(self):
        html = ('<!doctype html><html><head>'
                '<meta name="nova-layers" '
                'content="shadow=dramatic; glass=2"></head><body></body>'
                "</html>")
        self.assertEqual(nova_design.layers_meta(html),
                         {"shadow": 5, "glass": 2, "motion": set(),
                             "grain": None, "neon": None, "aurora": None})

    def test_attribute_order_is_free(self):
        html = '<meta content="glass=sharp" name="nova-layers">'
        self.assertEqual(nova_design.layers_meta(html)["glass"], 1)

    def test_absent_or_empty_meta_is_none(self):
        for html in ("<p>nothing</p>", "",
                     '<meta name="nova-layers" content="off">',
                     '<meta name="nova-layers">',
                     '<meta name="other" content="shadow=5">'):
            self.assertIsNone(nova_design.layers_meta(html), html)

    def test_only_the_nova_layers_tag_is_read(self):
        html = ('<meta name="nova-layers" content="shadow=deep">'
                '<meta name="nova-fonts" content="heading=Lalezar">')
        spec = nova_design.layers_meta(html)
        self.assertEqual(spec["shadow"], 4)


class TestImpliedLayers(unittest.TestCase):
    def test_classes_imply_their_layer(self):
        spec = nova_design._implied_layers(
            '<div class="nv-glass-3">x</div>'
            '<span class="nv-anim-float nv-anim-pop">y</span>')
        self.assertEqual(spec, {"shadow": None, "glass": 0,
                                "motion": {"float", "pop"},
                                    "grain": None, "neon": None,
                                    "aurora": None})

    def test_shadow_utilities_and_hover_lift(self):
        spec = nova_design._implied_layers(
            '<table class="nv-shadow-2">')
        self.assertEqual(spec["shadow"], 0)
        spec2 = nova_design._implied_layers('<a class="nv-hover-lift">')
        self.assertEqual(spec2["shadow"], 0)

    def test_floor_motion_classes_imply_nothing(self):
        spec = nova_design._implied_layers(
            '<section class="nv-reveal nv-in">')
        self.assertEqual(spec, {"shadow": None, "glass": None,
                                "motion": set(),
                                    "grain": None, "neon": None,
                                    "aurora": None})

    def test_unknown_anim_names_ignored(self):
        spec = nova_design._implied_layers('<i class="nv-anim-wobble">')
        self.assertEqual(spec["motion"], set())


class TestMergeSpecs(unittest.TestCase):
    def test_declared_beats_implied(self):
        merged = nova_design._merge_specs(
            {"shadow": 5, "glass": None, "motion": set(),
                "grain": None, "neon": None, "aurora": None},
            {"shadow": 0, "glass": 2, "motion": set(),
                "grain": None, "neon": None, "aurora": None})
        self.assertEqual(merged, {"shadow": 5, "glass": 2, "motion": set(),
            "grain": None, "neon": None, "aurora": None})

    def test_stronger_mood_wins(self):
        merged = nova_design._merge_specs(
            {"shadow": 2, "glass": 1, "motion": set(),
                "grain": None, "neon": None, "aurora": None},
            {"shadow": 4, "glass": 3, "motion": set(),
                "grain": None, "neon": None, "aurora": None})
        self.assertEqual(merged["shadow"], 4)
        self.assertEqual(merged["glass"], 3)

    def test_motion_unions(self):
        merged = nova_design._merge_specs(
            {"shadow": None, "glass": None, "motion": {"float"},
                "grain": None, "neon": None, "aurora": None},
            {"shadow": None, "glass": None, "motion": {"pop", "glow"},
                "grain": None, "neon": None, "aurora": None})
        self.assertEqual(merged["motion"], {"float", "pop", "glow"})


# --------------------------------------------------------------------------
# 2. the sheet - deterministic, lint-clean, only what was asked for
# --------------------------------------------------------------------------
class TestLayersCss(unittest.TestCase):
    SPECS = [
        {"shadow": 5, "glass": None, "motion": set(),
            "grain": None, "neon": None, "aurora": None},
        {"shadow": 0, "glass": 4, "motion": set(),
            "grain": None, "neon": None, "aurora": None},
        {"shadow": None, "glass": None, "motion": {"glow"},
            "grain": None, "neon": None, "aurora": None},
        {"shadow": 1, "glass": 1,
         "motion": {"float", "fade-down", "fade-up", "slide-in", "pop",
                    "glow"}, "grain": None, "neon": None, "aurora": None},
    ]

    def test_deterministic_and_headered(self):
        a = nova_design.layers_css(self.SPECS[3])
        b = nova_design.layers_css(self.SPECS[3])
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("/* nova-layers.css"))

    def test_every_realistic_spec_is_lint_clean(self):
        for spec in self.SPECS:
            ok, problem = nova_quality.preapply_check(
                "nova-layers.css", nova_design.layers_css(spec))
            self.assertTrue(ok, f"{spec}: {problem}")

    def test_only_requested_layers_are_emitted(self):
        sheet = nova_design.layers_css({"shadow": None, "glass": None,
                                        "motion": {"float"},
                                            "grain": None, "neon": None,
                                            "aurora": None})
        self.assertIn("/* nova layer: motion - float */", sheet)
        self.assertNotIn("nova layer: shadow", sheet)
        self.assertNotIn("nova layer: glass", sheet)
        self.assertNotIn(".nv-glass-1{", sheet)

    def test_shadow_scale_and_hover_lift(self):
        sheet = nova_design.layers_css({"shadow": 0, "glass": None,
                                        "motion": set(),
                                            "grain": None, "neon": None,
                                            "aurora": None})
        for i in range(1, 6):
            self.assertIn(f".nv-shadow-{i}{{", sheet)
            self.assertIn(f"--nv-shadow-{i}:", sheet)
        self.assertIn(".nv-hover-lift{", sheet)
        self.assertIn(".nv-hover-lift:hover{", sheet)
        self.assertNotIn("--shadow:", sheet)   # no mood remap at level 0

    def test_shadow_mood_remaps_the_floor_tokens(self):
        sheet = nova_design.layers_css({"shadow": 4, "glass": None,
                                        "motion": set(),
                                            "grain": None, "neon": None,
                                            "aurora": None})
        self.assertIn("nova layer: shadow mood 4", sheet)
        self.assertIn(":root{--shadow:var(--nv-shadow-4);"
                      "--shadow-lg:var(--nv-shadow-5)}", sheet)

    def test_glass_scale_is_color_and_font_free(self):
        sheet = nova_design.layers_css({"shadow": None, "glass": 2,
                                        "motion": set(),
                                            "grain": None, "neon": None,
                                            "aurora": None})
        for i, blur in ((1, 4), (2, 8), (3, 14), (4, 22)):
            self.assertIn(f".nv-glass-{i}{{", sheet)
            self.assertIn(f"blur({blur}px)", sheet)
        self.assertIn("--nv-glass-tint:255,255,255", sheet)
        self.assertIn("backdrop-filter", sheet)
        self.assertIn("@supports not ((backdrop-filter:blur(1px))", sheet)
        self.assertIn(".nv-glass{", sheet)     # the declared alias
        self.assertNotIn("--font", sheet)      # fonts stay out
        self.assertNotIn("--brand", sheet)     # color stays out

    def test_glass_alias_only_when_declared(self):
        sheet = nova_design.layers_css({"shadow": None, "glass": 0,
                                        "motion": set(),
                                            "grain": None, "neon": None,
                                            "aurora": None})
        self.assertIn(".nv-glass-1{", sheet)
        self.assertNotIn(".nv-glass{", sheet)

    def test_motion_guards_and_entrances(self):
        sheet = nova_design.layers_css(
            {"shadow": None, "glass": None,
             "motion": {"float", "fade-down", "fade-up", "slide-in",
                        "pop", "glow"},
                            "grain": None, "neon": None, "aurora": None})
        self.assertEqual(
            sheet.count("@media (prefers-reduced-motion: no-preference)"),
            7)                                  # 6 presets + stagger
        self.assertIn("animation:nv-float 6s ease-in-out infinite", sheet)
        self.assertIn("animation:nv-fade-down .7s ease-out both", sheet)
        self.assertIn("animation:nv-pop .5s ease-out both", sheet)
        self.assertIn(".nv-stagger>*:nth-child(1){", sheet)
        self.assertNotIn("innerHTML", sheet)

    def test_roundtrip_through_the_marker_parser(self):
        for spec in self.SPECS:
            sheet = nova_design.layers_css(spec)
            back = nova_design._spec_from_sheet(sheet)
            self.assertEqual(back, spec, spec)
            self.assertEqual(nova_design.layers_css(back), sheet)

    def test_spec_label(self):
        self.assertEqual(
            nova_design._spec_label({"shadow": 4, "glass": 0,
                                     "motion": {"float", "pop"},
                                         "grain": None,
                                         "neon": None, "aurora": None}),
            "shadow 4/5, glass utilities, motion float+pop")


# --------------------------------------------------------------------------
# 3. design_polish integration
# --------------------------------------------------------------------------
class TestDesignPolishLayers(unittest.TestCase):
    def test_meta_page_gets_sheet_and_link_in_cascade_order(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   STYLED_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="shadow=dramatic; '
                       'glass=2; motion=float,fade-down"></head>'))
            _write(ws / "css" / "style.css", "body{color:teal}")
            extras, notes = nova_design.design_polish(
                ws, ["index.html", "css/style.css"])
            self.assertIn("nova-layers.css", [e[0] for e in extras])
            sheet = dict(extras)["nova-layers.css"]
            self.assertIn("shadow mood 5", sheet)
            self.assertIn("glass alias 2", sheet)
            self.assertIn(".nv-anim-float{", sheet)
            html = (ws / "index.html").read_text(encoding="utf-8")
            i_css = html.index("css/style.css")
            i_layers = html.index("nova-layers.css")
            i_close = html.index("</head>")
            self.assertLess(i_css, i_layers)
            self.assertLess(i_layers, i_close)
            self.assertTrue(any("linked" in n for n in notes))

    def test_idempotent_second_run(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   STYLED_PAGE.replace("</head>",
                       '<meta name="nova-layers" '
                       'content="shadow=soft"></head>'))
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            for rel, content in extras:
                _write(ws / rel, content)
            before = (ws / "index.html").read_text(encoding="utf-8")
            extras2, notes2 = nova_design.design_polish(ws, ["index.html"])
            self.assertEqual(extras2, [])
            self.assertEqual(notes2, [])
            self.assertEqual(
                (ws / "index.html").read_text(encoding="utf-8"), before)

    def test_page_without_optin_is_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html", STYLED_PAGE)
            _write(ws / "css" / "style.css", "body{color:red}")
            extras, notes = nova_design.design_polish(
                ws, ["index.html", "css/style.css"])
            self.assertEqual(extras, [])
            self.assertEqual(notes, [])
            self.assertFalse((ws / "nova-layers.css").exists())

    def test_implied_classes_get_utilities_without_mood(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   STYLED_PAGE.replace("<body><h1>x</h1>",
                       '<body><div class="nv-glass-3 nv-anim-pop">'
                       "<h1>x</h1></div>"))
            _write(ws / "css" / "style.css", "body{color:red}")
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            sheet = dict(extras)["nova-layers.css"]
            self.assertIn(".nv-glass-3{", sheet)
            self.assertIn(".nv-anim-pop{", sheet)
            self.assertNotIn("glass alias", sheet)
            self.assertNotIn("nova layer: shadow", sheet)

    def test_nested_page_links_up_the_tree(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "pages" / "about.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="glass=mist">'
                       "</head>"))
            extras, _ = nova_design.design_polish(ws, ["pages/about.html"])
            self.assertIn("nova-layers.css", [e[0] for e in extras])
            html = (ws / "pages" / "about.html").read_text(
                encoding="utf-8")
            self.assertIn('href="../nova-layers.css"', html)

    def test_sheet_grows_never_shrinks(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "a.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="shadow=soft">'
                       "</head>"))
            extras, _ = nova_design.design_polish(ws, ["a.html"])
            for rel, content in extras:
                _write(ws / rel, content)
            _write(ws / "b.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="motion=pop">'
                       "</head>"))
            extras2, notes2 = nova_design.design_polish(ws, ["b.html"])
            sheet2 = dict(extras2)["nova-layers.css"]
            self.assertIn("shadow mood 2", sheet2)
            self.assertIn(".nv-anim-pop{", sheet2)
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
                       '<meta name="nova-layers" content="glass=2">'
                       "</head>"))
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            self.assertNotIn("nova-layers.css", [e[0] for e in extras])
            self.assertTrue((ws / "nova-layers.css").read_text(
                encoding="utf-8").startswith("/* my own layers */"))

    def test_manual_link_counts_as_a_request_and_floor_stays_out(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   '<!doctype html><html><head><title>t</title>'
                   '<link rel="stylesheet" href="nova-layers.css">'
                   '</head><body>x</body></html>')
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            names = [e[0] for e in extras]
            self.assertIn("nova-layers.css", names)
            self.assertNotIn("nova-ui.css", names,
                             "the floor must never fill a layers link")
            sheet = dict(extras)["nova-layers.css"]
            self.assertIn(".nv-shadow-1{", sheet)
            self.assertIn(".nv-glass-1{", sheet)
            self.assertNotIn("shadow mood", sheet)

    def test_wrong_folder_link_gets_a_copy(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "pages" / "x.html",
                   '<!doctype html><html><head><title>t</title>'
                   '<link rel="stylesheet" href="nova-layers.css">'
                   '</head><body>x</body></html>')
            extras, _ = nova_design.design_polish(ws, ["pages/x.html"])
            names = sorted(e[0] for e in extras)
            self.assertIn("nova-layers.css", names)
            self.assertIn("pages/nova-layers.css", names)

    def test_fragment_gets_sheet_but_no_link(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "frag.html",
                   '<div class="card">'
                   '<meta name="nova-layers" content="motion=glow">hi</div>')
            extras, _ = nova_design.design_polish(ws, ["frag.html"])
            self.assertIn("nova-layers.css", [e[0] for e in extras])
            self.assertNotIn("<link",
                             (ws / "frag.html").read_text(encoding="utf-8"))

    def test_bare_page_floor_link_comes_before_layers_link(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="shadow=3">'
                       "</head>"))
            extras, _ = nova_design.design_polish(ws, ["index.html"])
            names = [e[0] for e in extras]
            for need in ("nova-ui.css", "nova-ui.js", "nova-layers.css"):
                self.assertIn(need, names)
            html = (ws / "index.html").read_text(encoding="utf-8")
            self.assertLess(html.index("nova-ui.css"),
                            html.index("nova-layers.css"))

    def test_two_pages_union_into_one_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "a.html",
                   STYLED_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="glass=1">'
                       "</head>"))
            _write(ws / "b.html",
                   STYLED_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="motion=float">'
                       "</head>"))
            _write(ws / "css" / "style.css", "body{color:red}")
            extras, _ = nova_design.design_polish(
                ws, ["a.html", "b.html", "css/style.css"])
            self.assertEqual([e[0] for e in extras].count("nova-layers.css"),
                             1, "exactly ONE sheet per batch")
            sheet = dict(extras)["nova-layers.css"]
            self.assertIn(".nv-glass{", sheet)
            self.assertIn(".nv-anim-float{", sheet)

    def test_kill_switch_covers_layers(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            _write(ws / "index.html",
                   BARE_PAGE.replace("</head>",
                       '<meta name="nova-layers" content="all"></head>'))
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
# 4. the contract - options, never rules
# --------------------------------------------------------------------------
class TestContractLayers(unittest.TestCase):
    def test_contract_teaches_the_layers_menu(self):
        c = nova_design.DESIGN_CONTRACT
        self.assertIn("nova-layers", c)
        self.assertIn("shadow=1..5", c)
        self.assertIn("glass=1..4", c)
        self.assertIn("motion=float,fade-down", c)
        self.assertIn(".nv-shadow-1..5", c)
        self.assertIn(".nv-glass-1..4", c)
        self.assertIn(".nv-stagger", c)

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

    def test_contract_byte_stable_in_process(self):
        self.assertEqual(nova_design.DESIGN_CONTRACT,
                         nova_design.DESIGN_CONTRACT)


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
