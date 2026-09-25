#!/usr/bin/env python3
"""v7.3.0 tests: Nova FONTS - the local font library + context-aware
pairing engine.

"یک عالمه فونت زیبا مخصوص انواع زبان‌ها (بیشتر انگلیسی و فارسی) دانلود
 کن و بزار توی فایل‌های نوا و کاری کن بستگی به موقعیت ایجنت بتونه
 بینشون انتخاب کنه" + "هوش مصنوعی و نوا بتونن کد خلاقانه درست کنن و
 روی قالب خاص قفل نباشن"

Every test pins one layer (all NETWORK-FREE - the library is local):

  - library: index integrity, every file on disk, find by name/slug
  - detect_script / detect_mood: conservative matching (فروشگاه != فروش,
    'ai' != 'email'), all six moods reachable
  - pick_fonts: fa/en by language, mood-driven pairing, seed-stable,
    seed-varied (creativity, not lock-in), kill-switch, empty library
  - parse_font_meta + resolve_choice: key=value + short forms, unknown
    names fall back per slot, attr order independence
  - fonts_css: @font-face per family, unicode-range subsets, :root
    tokens, zero-specificity :where defaults (the model's CSS always
    wins), fa Vazirmatn fallback, CSS lint clean
  - _ensure_rtl / _inject_link: dir="rtl" added to Persian pages only,
    link after the last stylesheet link, idempotent
  - install_pass: binaries + nova-fonts.css + link + rtl, idempotent
    re-apply, meta override, model-font-ready pages untouched, nested
    pages get ../ hrefs, NOVA_NO_FONTS=1 kills everything
  - _font_install_hook + offer_apply: extras ride the SAME undo unit
    (/undo removes fonts + css again)
  - registry: /fonts exactly once in TOOLS + help payload + HELP_FA
  - contract: fonts clause + structure-freedom clause byte-pinned
"""
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_fonts      # noqa: E402
import nova_design     # noqa: E402
import nova_quality    # noqa: E402


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fa_page(extra_head="", body=None):
    body = body or ("<h1>گل‌فروشی نوا</h1><p>بوکه‌های دست‌ساز برای هر "
                    "مناسبت با ارسال همان روز در تهران، تازه و خوش‌عطر.</p>")
    return ("<!doctype html><html lang=\"fa\"><head><meta charset=\"utf-8\">"
            + extra_head + "</head><body>" + body + "</body></html>")


def _en_page(extra_head=""):
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            + extra_head + "</head><body><h1>Modern Studio</h1>"
            "<p>A clean portfolio with real projects and case studies.</p>"
            "</body></html>")


# --------------------------------------------------------------------------
class TestLibrary(unittest.TestCase):
    def test_index_loads_and_is_big(self):
        lib = nova_fonts.library()
        self.assertGreaterEqual(len(lib), 50)
        fa = [f for f in lib.values() if f.get("script") == "fa"]
        en = [f for f in lib.values() if f.get("script") == "en"]
        self.assertGreaterEqual(len(fa), 25)
        self.assertGreaterEqual(len(en), 25)

    def test_every_indexed_file_exists(self):
        for slug, f in nova_fonts._index().items():
            for w in f.get("weights", {}).values():
                for rel in w.values():
                    self.assertTrue((nova_fonts.FONTS_DIR / rel).is_file(),
                                    f"{slug}: {rel} missing")

    def test_find_by_name_slug_casefold(self):
        self.assertIsNotNone(nova_fonts.find("Vazirmatn"))
        self.assertIsNotNone(nova_fonts.find("vazirmatn"))
        self.assertIsNotNone(nova_fonts.find("VAZIRMATN"))
        self.assertIsNotNone(nova_fonts.find("markazi-text"))
        self.assertIsNone(nova_fonts.find("No Such Font"))
        self.assertIsNone(nova_fonts.find(""))

    def test_weights_are_numeric_and_have_files(self):
        for f in nova_fonts.library().values():
            for w, subs in f.get("weights", {}).items():
                self.assertTrue(w.isdigit(), w)
                self.assertTrue(subs)
                for sub, rel in subs.items():
                    self.assertIn(sub, ("arabic", "latin", "all"))
                    self.assertTrue(rel.endswith(".woff2"))

    def test_license_notice_and_licenses_shipped(self):
        notice = nova_fonts.FONTS_DIR / "LICENSE-NOTICE.md"
        self.assertTrue(notice.is_file())
        text = notice.read_text(encoding="utf-8")
        self.assertIn("SIL", text)
        lics = list((nova_fonts.FONTS_DIR / "licenses").glob("*.txt"))
        self.assertGreaterEqual(len(lics), 50)


# --------------------------------------------------------------------------
class TestScriptAndMood(unittest.TestCase):
    def test_script_detection(self):
        self.assertEqual(nova_fonts.detect_script(
            "یک سایت فروشگاه آنلاین گل بساز"), "fa")
        self.assertEqual(nova_fonts.detect_script(
            "a modern dashboard for our sales team"), "en")
        self.assertEqual(nova_fonts.detect_script(""), "fa")

    def test_mood_all_reachable(self):
        cases = [
            ("یک سایت فروش برای تخفیف کمپین", "bold-display"),
            ("مجله خبری آنلاین با مقاله", "elegant-editorial"),
            ("سایت آموزش کودکان با بازی شاد", "friendly-playful"),
            ("داشبورد هوش مصنوعی برای استارتاپ", "modern-tech"),
            ("پورتفولیو آژانس طراحی هنری", "creative-artistic"),
            ("یک سایت ساده و مینیمال", "minimal-clean"),
            ("a luxury magazine blog", "elegant-editorial"),
            ("modern saas landing for ai startup", "modern-tech"),
            ("fun colorful kids game site", "friendly-playful"),
            ("bold poster for a fitness gym", "bold-display"),
            ("creative art studio portfolio", "creative-artistic"),
            ("simple minimal resume cv", "minimal-clean"),
        ]
        for text, want in cases:
            self.assertEqual(nova_fonts.detect_mood(text), want, text)

    def test_no_false_positive_from_substrings(self):
        # Persian: فروش must NOT match inside فروشگاه
        self.assertNotIn("فروش", nova_fonts.detect_mood("فروشگاه"),
                         "bare substring match - token check broken")
        self.assertEqual(nova_fonts.detect_mood("فروشگاه"), "minimal-clean")
        # latin: ai must NOT match inside email/main/domain
        self.assertNotEqual(nova_fonts.detect_mood(
            "send me an email about the update"), "modern-tech")
        # art must NOT match inside article
        self.assertNotEqual(nova_fonts.detect_mood(
            "write an article about health"), "creative-artistic")

    def test_zwnj_keywords_stay_one_token(self):
        self.assertEqual(nova_fonts.detect_mood("یک کسب‌وکار شرکتی"),
                         "minimal-clean")


# --------------------------------------------------------------------------
class TestPickFonts(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.get("NOVA_NO_FONTS")
        os.environ["NOVA_NO_FONTS"] = ""

    def tearDown(self):
        if self._env is None:
            os.environ.pop("NOVA_NO_FONTS", None)
        else:
            os.environ["NOVA_NO_FONTS"] = self._env

    def test_fa_request_gives_fa_pairing(self):
        c = nova_fonts.pick_fonts("یک سایت فروشگاه آنلاین گل بساز",
                                  seed="seed-1")
        self.assertIsNotNone(c)
        self.assertEqual(c.script, "fa")
        self.assertEqual(nova_fonts.find(c.body)[1].get("script"), "fa")

    def test_en_request_gives_en_pairing(self):
        c = nova_fonts.pick_fonts("a clean corporate landing page",
                                  seed="seed-1")
        self.assertEqual(c.script, "en")
        self.assertEqual(nova_fonts.find(c.body)[1].get("script"), "en")

    def test_seed_stable(self):
        c1 = nova_fonts.pick_fonts("سایت استارتاپ هوش مصنوعی", seed="abc")
        c2 = nova_fonts.pick_fonts("سایت استارتاپ هوش مصنوعی", seed="abc")
        self.assertEqual((c1.display, c1.body, c1.mono),
                         (c2.display, c2.body, c2.mono))

    def test_seed_variety_not_locked_to_one_template(self):
        picks = set()
        for i in range(16):
            c = nova_fonts.pick_fonts("یک سایت ورزشی و باشگاه",
                                      seed=f"seed-{i}")
            picks.add((c.display, c.body))
        self.assertGreaterEqual(len(picks), 2,
                                "every project got the same pairing - "
                                "the agent is template-locked")

    def test_mono_is_real_font(self):
        c = nova_fonts.pick_fonts("a tech blog", seed="m1")
        got = nova_fonts.find(c.mono)
        self.assertIsNotNone(got)
        self.assertEqual(got[1].get("category"), "mono")

    def test_kill_switch(self):
        with mock.patch.dict(os.environ, {"NOVA_NO_FONTS": "1"}):
            self.assertFalse(nova_fonts.enabled())
            self.assertIsNone(nova_fonts.pick_fonts("سایت", seed="x"))

    def test_empty_library_degrades(self):
        with mock.patch.object(nova_fonts, "_INDEX", {}):
            self.assertIsNone(nova_fonts.pick_fonts("سایت", seed="x"))
            extras, notes = nova_fonts.install_pass(
                Path(tempfile.mkdtemp()), ["index.html"], request_text="سایت")
            self.assertEqual(extras, [])


# --------------------------------------------------------------------------
class TestFontMeta(unittest.TestCase):
    def test_key_value_form(self):
        html = '<meta name="nova-fonts" content="heading=Lalezar; ' \
               'body=Vazirmatn; mono=JetBrains Mono">'
        self.assertEqual(nova_fonts.parse_font_meta(html),
                         {"display": "Lalezar", "body": "Vazirmatn",
                          "mono": "JetBrains Mono"})

    def test_short_comma_form(self):
        html = '<meta name="nova-fonts" content="Lalezar, Vazirmatn">'
        self.assertEqual(nova_fonts.parse_font_meta(html),
                         {"display": "Lalezar", "body": "Vazirmatn"})

    def test_absent_and_empty(self):
        self.assertEqual(nova_fonts.parse_font_meta("<head></head>"), {})
        self.assertEqual(nova_fonts.parse_font_meta(
            '<meta name="nova-fonts" content="">'), {})
        self.assertEqual(nova_fonts.parse_font_meta(
            '<meta name="other" content="x">'), {})

    def test_attr_order_independent(self):
        html = '<meta content="heading=Estedad; body=Shabnam" ' \
               'name="nova-fonts">'
        self.assertEqual(nova_fonts.parse_font_meta(html),
                         {"display": "Estedad", "body": "Shabnam"})

    def test_resolve_overrides_valid_slots_only(self):
        auto = nova_fonts.pick_fonts("یک سایت", seed="r1")
        got = nova_fonts.resolve_choice(
            {"display": "Lalezar", "body": "No Such Font"}, auto)
        self.assertEqual(got.display, "Lalezar")
        self.assertEqual(got.body, auto.body)
        self.assertEqual(got.source, "model")

    def test_resolve_all_invalid_keeps_auto(self):
        auto = nova_fonts.pick_fonts("یک سایت", seed="r2")
        got = nova_fonts.resolve_choice(
            {"display": "Comic Sans", "body": "Foo Bar"}, auto)
        self.assertIs(got, auto)

    def test_placeholder_meta_falls_back_to_auto(self):
        # the contract's example uses placeholders - a model that copies
        # it verbatim must NOT lock every project to one pairing
        auto = nova_fonts.pick_fonts("یک سایت", seed="r3")
        got = nova_fonts.resolve_choice(
            {"display": "FontName", "body": "FontName"}, auto)
        self.assertIs(got, auto)


# --------------------------------------------------------------------------
class TestFontsCss(unittest.TestCase):
    def setUp(self):
        self.choice = nova_fonts.Choice("Lalezar", "Estedad",
                                        "JetBrains Mono", "modern-tech",
                                        "fa", "auto")

    def test_font_faces_for_all_families(self):
        css = nova_fonts.fonts_css(self.choice)
        for fam in ("Lalezar", "Estedad", "JetBrains Mono"):
            self.assertIn(f"@font-face{{font-family:'{fam}'", css)

    def test_vazirmatn_fallback_included_for_fa(self):
        css = nova_fonts.fonts_css(self.choice)
        self.assertIn("font-family:'Vazirmatn'", css)

    def test_unicode_ranges_and_none_for_all(self):
        css = nova_fonts.fonts_css(self.choice)
        self.assertIn("unicode-range:U+0600-06FF", css)     # arabic subset
        shabnam = nova_fonts.Choice("Shabnam", "Shabnam",
                                    "Fira Code", "minimal-clean", "fa")
        css2 = nova_fonts.fonts_css(shabnam)
        face = [l for l in css2.splitlines()
                if "font-family:'Shabnam'" in l][0]
        self.assertNotIn("unicode-range", face)             # 'all' subset

    def test_root_tokens_and_where_defaults(self):
        css = nova_fonts.fonts_css(self.choice)
        self.assertIn("--font-display:'Lalezar'", css)
        self.assertIn("--font-body:'Estedad'", css)
        self.assertIn("--font:var(--font-body)", css)
        self.assertIn(":where(body){font-family:var(--font-body)}", css)
        self.assertIn(":where(h1,h2,h3,h4,h5,h6,legend,summary,th)"
                      "{font-family:var(--font-display)}", css)
        self.assertIn(":where(code,kbd,pre,samp)"
                      "{font-family:var(--font-mono)}", css)

    def test_prefix_flows_into_urls(self):
        css = nova_fonts.fonts_css(self.choice, prefix="../")
        self.assertIn("url('../fonts/fa/lalezar/", css)
        css2 = nova_fonts.fonts_css(self.choice, prefix="")
        self.assertIn("url('fonts/fa/lalezar/", css2)

    def test_css_passes_lint(self):
        self.assertEqual(
            nova_quality.preapply_check("nova-fonts.css",
                                        nova_fonts.fonts_css(self.choice)),
            (True, None))

    def test_none_choice_gives_empty(self):
        self.assertEqual(nova_fonts.fonts_css(None), "")


# --------------------------------------------------------------------------
class TestRtlAndLink(unittest.TestCase):
    def test_rtl_added_to_persian_page(self):
        text, added = nova_fonts._ensure_rtl(_fa_page())
        self.assertTrue(added)
        self.assertIn('dir="rtl"', text)

    def test_rtl_not_duplicated(self):
        page = _fa_page().replace("<html lang=\"fa\">",
                                  "<html lang=\"fa\" dir=\"rtl\">")
        text, added = nova_fonts._ensure_rtl(page)
        self.assertFalse(added)
        self.assertEqual(text.count("dir="), 1)

    def test_rtl_not_added_to_english(self):
        text, added = nova_fonts._ensure_rtl(_en_page())
        self.assertFalse(added)

    def test_rtl_needs_enough_persian(self):
        text, added = nova_fonts._ensure_rtl(
            "<html><head></head><body><p>hello world page</p></body></html>")
        self.assertFalse(added)

    def test_link_after_last_stylesheet(self):
        page = _fa_page('<link rel="stylesheet" href="css/style.css">')
        text, added = nova_fonts._inject_link(page, "nova-fonts.css")
        self.assertTrue(added)
        self.assertGreater(text.index("css/style.css"),
                           -1)
        self.assertGreater(text.index("nova-fonts.css"),
                           text.index("css/style.css"))

    def test_link_idempotent(self):
        page = _fa_page('<link rel="stylesheet" href="nova-fonts.css">')
        text, added = nova_fonts._inject_link(page, "nova-fonts.css")
        self.assertFalse(added)
        self.assertEqual(text.count("nova-fonts.css"), 1)

    def test_link_before_head_close_when_no_links(self):
        text, added = nova_fonts._inject_link(_fa_page(), "nova-fonts.css")
        self.assertTrue(added)
        self.assertIn('<link rel="stylesheet" href="nova-fonts.css">',
                      text)


# --------------------------------------------------------------------------
class TestInstallPass(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.get("NOVA_NO_FONTS")
        os.environ["NOVA_NO_FONTS"] = ""
        self.ws = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self._env is None:
            os.environ.pop("NOVA_NO_FONTS", None)
        else:
            os.environ["NOVA_NO_FONTS"] = self._env

    def _apply(self, page, names=("index.html",), request="یک سایت گل"):
        _write(self.ws / "index.html", page) if "index.html" in names \
            else [_write(self.ws / n, page) for n in names]
        return nova_fonts.install_pass(self.ws, list(names),
                                       request_text=request)

    def test_fa_page_gets_fonts_css_link_and_rtl(self):
        extras, notes = self._apply(_fa_page())
        rels = [r for r, _d in extras]
        self.assertTrue(any(r.startswith("fonts/") for r in rels),
                        rels)
        self.assertIn("nova-fonts.css", rels)
        css = (self.ws / "nova-fonts.css")
        self.assertFalse(css.is_file(),
                         "install_pass returns extras, the HOOK writes them")
        page = (self.ws / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="nova-fonts.css"', page)
        self.assertIn('dir="rtl"', page)

    def test_en_page_no_rtl(self):
        extras, _notes = self._apply(_en_page(), request="a clean portfolio")
        page = (self.ws / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('dir="rtl"', page)
        self.assertTrue(any(r.startswith("fonts/en/") for r, _d in extras)
                        or any(r.startswith("fonts/fa/") for r, _d in extras),
                        [r for r, _d in extras])

    def test_hook_writes_binaries_and_css(self):
        sess = mock.Mock()
        sess.ws = self.ws
        sess.last_request = "یک سایت گل‌فروشی"
        sess.touched = {}
        sess.last_batch = []
        _write(self.ws / "index.html", _fa_page())
        applied = ["index.html"]
        snap_batch = []
        nova._font_install_hook(sess, applied, snap_batch)
        css = self.ws / "nova-fonts.css"
        self.assertTrue(css.is_file())
        self.assertIn("@font-face", css.read_text(encoding="utf-8"))
        fonts = list(self.ws.glob("fonts/*/*/*.woff2"))
        self.assertTrue(fonts)
        self.assertIn("index.html", applied)
        snap_rels = {t.name for t, _bk in snap_batch}
        self.assertIn("nova-fonts.css", snap_rels)
        # in-place page rewrites (link/rtl) are design-hook style: the page
        # was already touched by the apply itself, extras get 'touched'
        self.assertTrue(sess.touched)
        page = (self.ws / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="nova-fonts.css"', page)

    def test_idempotent_second_pass(self):
        sess = mock.Mock()
        sess.ws = self.ws
        sess.last_request = "یک سایت گل‌فروشی"
        sess.touched = {}
        sess.last_batch = []
        _write(self.ws / "index.html", _fa_page())
        nova._font_install_hook(sess, ["index.html"], [])
        fonts_after_1 = sorted(str(p) for p in
                               self.ws.glob("fonts/*/*/*.woff2"))
        page_after_1 = (self.ws / "index.html").read_text(encoding="utf-8")
        sess2 = mock.Mock()
        sess2.ws = self.ws
        sess2.last_request = "یک سایت گل‌فروشی"
        sess2.touched = {}
        sess2.last_batch = []
        nova._font_install_hook(sess2, ["index.html"], [])
        fonts_after_2 = sorted(str(p) for p in
                               self.ws.glob("fonts/*/*/*.woff2"))
        self.assertEqual(fonts_after_1, fonts_after_2)
        self.assertEqual(page_after_1,
                         (self.ws / "index.html").read_text(encoding="utf-8"))

    def test_meta_override_installs_requested_font(self):
        page = _fa_page('<meta name="nova-fonts" content="heading=Lalezar; '
                        'body=Vazirmatn">')
        extras, notes = self._apply(page, request="anything at all")
        css = [d for r, d in extras if r == "nova-fonts.css"][0]
        self.assertIn("font-family:'Lalezar'", css)
        self.assertIn("font-family:'Vazirmatn'", css)
        self.assertTrue(any("lalezar" in r for r, _d in extras))

    def test_page_with_own_fontface_left_alone(self):
        page = _fa_page("<style>@font-face{font-family:'X';"
                        "src:url('x.woff2')}</style>")
        extras, _n = self._apply(page)
        self.assertNotIn("nova-fonts.css", [r for r, _d in extras])
        out = (self.ws / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("nova-fonts.css", out)

    def test_google_fonts_page_untouched(self):
        page = _en_page('<link href="https://fonts.googleapis.com/css2'
                        '?family=Inter" rel="stylesheet">')
        extras, _n = self._apply(page, request="a modern english site")
        self.assertNotIn("nova-fonts.css", [r for r, _d in extras])

    def test_nested_page_gets_parent_href(self):
        _write(self.ws / "pages" / "about.html", _fa_page())
        extras, _n = nova_fonts.install_pass(
            self.ws, ["pages/about.html"], request_text="یک سایت")
        self.assertIn("nova-fonts.css", [r for r, _d in extras])
        out = (self.ws / "pages" / "about.html").read_text(
            encoding="utf-8")
        self.assertIn('href="../nova-fonts.css"', out)

    def test_non_html_noop(self):
        extras, notes = self._apply(None, names=(), request="x")
        _write(self.ws / "app.py", "print('hi')")
        extras, notes = nova_fonts.install_pass(
            self.ws, ["app.py"], request_text="سایت")
        self.assertEqual(extras, [])

    def test_kill_switch_noop(self):
        with mock.patch.dict(os.environ, {"NOVA_NO_FONTS": "1"}):
            _write(self.ws / "index.html", _fa_page())
            extras, _n = nova_fonts.install_pass(
                self.ws, ["index.html"], request_text="سایت")
            self.assertEqual(extras, [])


# --------------------------------------------------------------------------
class TestRegistryAndContract(unittest.TestCase):
    def test_fonts_command_registered_once(self):
        cmds = [t["cmd"] for t in nova.TOOLS]
        self.assertEqual(cmds.count("/fonts"), 1)
        entry = next(t for t in nova.TOOLS if t["cmd"] == "/fonts")
        self.assertTrue(callable(entry["fn"]))

    def test_help_payload_covers_fonts(self):
        payload = nova.web_help_payload()
        cmds = [item["cmd"] for g in payload["groups"]
                for item in g["items"]]
        self.assertEqual(cmds.count("/fonts"), 1)
        # the registry-wide invariant: every command exactly once
        registry = [t["cmd"] for t in nova.TOOLS]
        for c in registry:
            self.assertEqual(cmds.count(c), 1, c)
        self.assertIn("/fonts", nova.HELP_FA)

    def test_fonts_command_runs(self):
        sess = mock.Mock()
        with mock.patch("sys.stdout", new=io.StringIO()):
            nova.cmd_fonts(sess, "fa")
        self.assertTrue(True)   # must not raise

    def test_nova_imports_fontsys(self):
        self.assertIsNotNone(nova.fontsys)

    def test_contract_teaches_fonts_and_freedom(self):
        c = nova_design.DESIGN_CONTRACT
        self.assertIn("nova-fonts", c)
        self.assertIn('dir="rtl"', c)
        self.assertIn("Structure freedom", c)
        self.assertIn(".bento", c)
        self.assertIn(".split", c)
        self.assertIn("NEVER repeat one template", c)
        self.assertIn("IMG:", c)

    def test_floor_has_column_helpers(self):
        css = nova_design.NOVA_UI_CSS
        self.assertIn(".bento{", css)
        self.assertIn(".split{", css)
        self.assertEqual(nova_quality.preapply_check("x.css", css),
                         (True, None))


# --------------------------------------------------------------------------
class TestApplyIntegration(unittest.TestCase):
    """e2e through offer_apply: fonts ride the SAME undo unit."""

    WEAK = """باشه، یک سایت گل‌فروشی می‌سازم.

=== FILE: index.html ===
<!doctype html>
<html lang="fa">
<head><link rel="stylesheet" href="css/style.css"></head>
<body>
  <h1>گل‌فروشی نوا</h1>
  <p>بوکه‌های تازه برای هر مناسبت با ارسال همان روز در تهران.</p>
  <img src="IMG:red roses bouquet" alt="بوکه رز">
</body>
</html>
=== END ===
Preview: index.html"""

    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_ni = nova.NONINTERACTIVE
        self._old_design = os.environ.get("NOVA_NO_DESIGN")
        self._old_fonts = os.environ.get("NOVA_NO_FONTS")
        self._old_images = os.environ.get("NOVA_NO_IMAGES")
        os.environ["NOVA_NO_DESIGN"] = ""
        os.environ["NOVA_NO_FONTS"] = ""
        os.environ["NOVA_NO_IMAGES"] = "1"     # keep THIS suite network-free
        nova.NONINTERACTIVE = True
        self.ws = Path(tempfile.mkdtemp())

    def tearDown(self):
        nova.stream_chat = self._old_stream
        nova.NONINTERACTIVE = self._old_ni
        for k, v in (("NOVA_NO_DESIGN", self._old_design),
                     ("NOVA_NO_FONTS", self._old_fonts),
                     ("NOVA_NO_IMAGES", self._old_images)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _turn(self, text):
        nova.stream_chat = lambda *a, **k: (self.WEAK, True)
        sess = nova.Session(self.ws)
        res = nova.chat_turn(sess, text, auto=True)
        return sess, res

    def test_apply_installs_fonts_with_floor(self):
        sess, res = self._turn("یک سایت گل‌فروشی زیبا بساز")
        self.assertIn("index.html", res["applied"])
        css = self.ws / "nova-fonts.css"
        self.assertTrue(css.is_file(), "nova-fonts.css must be written")
        self.assertIn("@font-face", css.read_text(encoding="utf-8"))
        fonts = list(self.ws.glob("fonts/*/*/*.woff2"))
        self.assertGreaterEqual(len(fonts), 2)
        page = (self.ws / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="nova-fonts.css"', page)
        self.assertIn('dir="rtl"', page)
        # the floor sheet too (the model forgot css/style.css)
        self.assertTrue((self.ws / "css" / "style.css").is_file())

    def test_undo_removes_font_files_and_css(self):
        sess, _res = self._turn("یک سایت گل‌فروشی زیبا بساز")
        fonts = list(self.ws.glob("fonts/*/*/*.woff2"))
        self.assertTrue(fonts)
        old_out = sys.stdout
        sys.stdout = io.StringIO()
        try:
            nova.cmd_undo(sess, "")
        finally:
            sys.stdout = old_out
        self.assertFalse((self.ws / "nova-fonts.css").is_file())
        self.assertFalse(list(self.ws.glob("fonts/*/*/*.woff2")),
                         "font binaries must leave with the undo unit")
        # the (now empty) fonts/ dir itself may remain - files must not

    def test_second_apply_same_project_stays_clean(self):
        sess, _res = self._turn("یک سایت گل‌فروشی زیبا بساز")
        fonts_1 = sorted(str(p) for p in self.ws.glob("fonts/*/*/*.woff2"))
        nova.stream_chat = lambda *a, **k: (
            self.WEAK.replace("گل‌فروشی نوا", "گل‌فروشی نوا ۲"), True)
        sess2 = nova.Session(self.ws)
        nova.chat_turn(sess2, "بخش تماس را هم اضافه کن", auto=True)
        fonts_2 = sorted(str(p) for p in self.ws.glob("fonts/*/*/*.woff2"))
        self.assertEqual(fonts_1, fonts_2)


# --------------------------------------------------------------------------
class TestAuditFixes(unittest.TestCase):
    """Regression pins for the v7.3 audit findings (7-a..7-d)."""

    def setUp(self):
        self._env = os.environ.get("NOVA_NO_FONTS")
        os.environ["NOVA_NO_FONTS"] = ""
        self.ws = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self._env is None:
            os.environ.pop("NOVA_NO_FONTS", None)
        else:
            os.environ["NOVA_NO_FONTS"] = self._env

    def test_rtl_detected_despite_style_script_latin(self):
        # HIGH: latin chars inside <style>/<script> are NOT visible text -
        # a Persian page with its own CSS/JS must still get dir="rtl"
        page = ('<!doctype html><html lang="fa"><head><meta charset="utf-8">'
                '<style>.hero{background:linear-gradient(90deg,#fff,#eee);'
                'font-family:Vazirmatn}</style>'
                '<script>var x = "just some javascript latin text";</script>'
                '</head><body><h1>گل‌فروشی نوا</h1>'
                '<p>بوکه‌های دست‌ساز برای هر مناسبت با ارسال همان روز در '
                'تهران، تازه و خوش‌عطر و زیبا.</p></body></html>')
        text, added = nova_fonts._ensure_rtl(page)
        self.assertTrue(added, "latin in style/script must not hide Persian")
        self.assertIn('dir="rtl"', text)

    def test_non_utf8_page_never_corrupted(self):
        # HIGH: a cp1252 page that cannot decode is skipped, never
        # re-encoded with U+FFFD replacement chars
        page = ('<!doctype html><html><head></head><body>'
                '<h1>Caf\xe9 \u2013 \u201cBistro\u201d</h1></body></html>')
        target = self.ws / "index.html"
        target.write_bytes(page.encode("cp1252"))
        extras, notes = nova_fonts.install_pass(
            self.ws, ["index.html"], request_text="a bistro site")
        raw = target.read_bytes()
        self.assertNotIn(b"\xef\xbf\xbd", raw,
                         "U+FFFD must never be written into the page")
        self.assertEqual(page.encode("cp1252"), raw,
                         "an undecodable page must stay byte-identical")
        self.assertTrue(any("not UTF-8" in n for n in notes), notes)

    def test_every_declared_fontface_url_has_a_binary(self):
        # MEDIUM: multi-meta batches must never declare families the cap
        # could not install (declared-but-absent url == guaranteed 404)
        families = ["Lalezar", "Amiri", "Reem Kufi", "Shabnam", "Sahel"]
        for i, fam in enumerate(families):
            page = (f'<!doctype html><html lang="fa"><head>'
                    f'<meta charset="utf-8"><meta name="nova-fonts" '
                    f'content="heading={fam}; body=Vazirmatn">'
                    f'</head><body><h{1}>عنوان {i}</h1>'
                    f'<p>متن آزمایشی برای صفحه شماره {i} که کاملاً فارسی '
                    f'است و کافی طولانی می‌باشد.</p></body></html>')
            _write(self.ws / f"p{i}.html", page)
        extras, _n = nova_fonts.install_pass(
            self.ws, [f"p{i}.html" for i in range(len(families))],
            request_text="سایت")
        css = next(d for r, d in extras if r == "nova-fonts.css")
        declared = re.findall(r"url\('([^']+)'\)", css)
        copied = {r for r, _d in extras if r.startswith("fonts/")}
        self.assertTrue(declared)
        for url in declared:
            self.assertIn(url, copied,
                          f"css declares {url} but no binary was queued")

    def _hook(self, names, request):
        sess = mock.Mock()
        sess.ws = self.ws
        sess.last_request = request
        sess.touched = {}
        sess.last_batch = []
        nova._font_install_hook(sess, list(names), [])

    def test_followup_meta_adds_families_never_reskins(self):
        # MEDIUM: turn 2's <meta nova-fonts> must ADD families; the
        # turn-1 project stamp keeps the tokens (no re-skin)
        _write(self.ws / "index.html", _fa_page())
        self._hook(["index.html"], "یک سایت گل‌فروشی")
        css1 = (self.ws / "nova-fonts.css").read_text(encoding="utf-8")
        m1 = re.search(r"display=([^;]+); body=([^;]+)", css1)
        turn1_display, turn1_body = m1.group(1), m1.group(2)
        # turn 2: a NEW page that requests a different heading font
        page2 = ('<!doctype html><html lang="fa"><head><meta charset="utf-8">'
                 '<meta name="nova-fonts" content="heading=Lalezar">'
                 '</head><body><h1>تماس با ما</h1>'
                 '<p>فرم تماس با شماره تلفن و آدرس ایمیل فروشگاه.</p>'
                 '</body></html>')
        _write(self.ws / "contact.html", page2)
        self._hook(["contact.html"], "بخش تماس را اضافه کن")
        css2 = (self.ws / "nova-fonts.css").read_text(encoding="utf-8")
        self.assertIn(f"display={turn1_display}", css2,
                      "project stamp display must survive turn 2")
        self.assertIn(f"body={turn1_body}", css2)
        self.assertIn("font-family:'Lalezar'",
                      css2, "meta family must be ADDED to @font-face")
        # and the turn-1 display family is still declared
        self.assertIn(f"font-family:'{turn1_display}'", css2)

    def test_huge_page_skipped_with_note(self):
        # LOW: an oversized page is skipped LOUDLY, not silently
        big = ('<!doctype html><html><head></head><body><p>'
               + ('بهترین فروشگاه شهر ' * 90000) + '</p></body></html>')
        _write(self.ws / "big.html", big)
        _extras, notes = nova_fonts.install_pass(
            self.ws, ["big.html"], request_text="سایت")
        self.assertTrue(any("page > 3 MB" in n for n in notes), notes)

    def test_fragment_left_alone(self):
        # LOW: fragments (no doctype/<html>) get no link at position 0,
        # no rtl - same rule as the design floor
        frag = '<div class="card"><p>متن کارت زیبا</p></div>'
        _write(self.ws / "frag.html", frag)
        extras, notes = nova_fonts.install_pass(
            self.ws, ["frag.html"], request_text="سایت")
        out = (self.ws / "frag.html").read_text(encoding="utf-8")
        self.assertEqual(frag, out, "fragment must stay untouched")
        self.assertTrue(any("fragment" in n for n in notes), notes)
        self.assertNotIn("nova-fonts.css", [r for r, _d in extras])

    def test_absolute_path_outside_workspace_refused(self):
        # LOW: public API - absolute paths outside the ws are refused
        outside = Path(tempfile.mkdtemp()) / "evil.html"
        outside.write_text(_fa_page(), encoding="utf-8")
        _extras, notes = nova_fonts.install_pass(
            self.ws, [str(outside)], request_text="سایت")
        self.assertTrue(any("outside the workspace" in n for n in notes),
                        notes)
        self.assertEqual(outside.read_text(encoding="utf-8"), _fa_page(),
                         "the outside page must stay untouched")

    def test_crf_pages_keep_their_line_endings(self):
        # LOW: a CRLF page is never line-normalized by the font pass
        page = _fa_page().replace(">", ">\n").replace("\n", "\r\n")
        target = self.ws / "index.html"
        target.write_bytes(page.encode("utf-8"))
        nova_fonts.install_pass(self.ws, ["index.html"],
                                request_text="یک سایت گل")
        out = target.read_bytes().decode("utf-8")
        self.assertIn("\r\n", out, "original CRLF endings must survive")
        self.assertIn('href="nova-fonts.css"', out)
        self.assertIn('dir="rtl"', out)

    def test_inject_link_exact_href_match(self):
        # LOW: an existing 'css/nova-fonts.css' link is a DIFFERENT file
        # and must not suppress the root sheet link
        page = _fa_page('<link rel="stylesheet" href="css/nova-fonts.css">')
        text, added = nova_fonts._inject_link(page, "nova-fonts.css")
        self.assertTrue(added)
        self.assertEqual(text.count('href="nova-fonts.css"'), 1)

    def test_corrupt_index_not_cached(self):
        # LOW: a corrupt index.json must not poison the process cache -
        # a repaired file is picked up by the next call
        orig = nova_fonts.FONTS_DIR / "index.json"
        backup = orig.read_text(encoding="utf-8")
        try:
            orig.write_text("{not json", encoding="utf-8")
            nova_fonts._INDEX = None
            self.assertEqual(nova_fonts._index(), {})
            self.assertEqual(nova_fonts.library(), {})
            # the failed read is NOT cached: after the repair the very
            # next call (same _INDEX=None) reads the healthy index again
            orig.write_text(backup, encoding="utf-8")     # repaired
            self.assertGreater(len(nova_fonts._index()), 0,
                               "a repaired index must be picked up")
        finally:
            orig.write_text(backup, encoding="utf-8")
            nova_fonts._INDEX = None

    def test_self_closing_html_tag_rtl(self):
        # LOW: '<html lang="fa"/>' must not become 'lang="fa"/ dir="rtl"'
        page = ('<!doctype html><html lang="fa"/><head></head>'
                '<body><p>بوکه‌های دست‌ساز برای هر مناسبت با ارسال '
                'همان روز در تهران.</p></body></html>')
        text, added = nova_fonts._ensure_rtl(page)
        self.assertTrue(added)
        self.assertNotIn("/ dir=", text)

    def test_no_fonts_needed_no_binaries(self):
        # a page that handles fonts itself (google link) AND has no meta
        # must not get binaries copied for nothing
        page = _en_page('<link href="https://fonts.googleapis.com/css2'
                        '?family=Inter&display=swap" rel="stylesheet">')
        _write(self.ws / "index.html", page)
        extras, _n = nova_fonts.install_pass(
            self.ws, ["index.html"],
            request_text="a modern english site")
        self.assertEqual([r for r, _d in extras
                          if r.startswith("fonts/")], [])
        self.assertNotIn("nova-fonts.css", [r for r, _d in extras])


if __name__ == "__main__":
    unittest.main(verbosity=1)
