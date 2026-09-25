#!/usr/bin/env python3
"""v7.6.0 tests: the IMAGE RELEVANCE ENGINE.

"عکسا رو قشنگ پیدا نمیکنه - قرار بود عکس رز قرمز رو پیدا کنه، به جاش عکس
یک شاخه ی درخت خیلی ساده با پس زمینه قرمز پیدا کرده"

The user asked for a RED ROSE and got a bare tree branch on a red
background. Root causes found by live reproduction:

  - «رز» alone is the ARABIC word for rice -> DDG returns rice recipes;
  - a bare color («قرمز») returns ANY red object;
  - the v7.4 ranking was size-only (_quality_key) - a big "branch on
    red background" photo could outrank real roses forever;
  - nothing verified the downloaded photo actually looks like the query.

Every test pins one layer (all NETWORK-FREE via stubs):

  - dictionary integrity: no empty/garbage translations, no stopword
    keys, colors all have pixel specs
  - translate_query: the rice-trap fix («رز» -> rose), the user's exact
    phrase («رز قرمز» / «گل رز قرمز» -> red rose), filler stripping
    (عکس/یک/بذار/پیدا کن), ZWNJ phrases (دسته‌گل), English passthrough
    (never reordered - that scrambled 'red roses bouquet' once),
    tail-trim (background never becomes the subject)
  - build_ladder: Persian searches ENGLISH FIRST, keeps the original as
    a later rung; English keeps the exact v7.4 tail-drop sequence the
    legacy fill/pick tests pin
  - _relevance: rose beats branch, title beats url, stems match
    (roses/rose), Persian candidates match the original words, the
    Arabic-recipe penalty, never raises
  - search_images: relevance reorders inside the tier guarantee
  - _passes_color: real Pillow pixels - red passes, green/white fail,
    unreadable/soft-gate never rejects
  - fill_html_images + pick_and_save: color-gated end-to-end with the
    color-softened fallback (never emptier than v7.5)
  - watermark hardening: tarh.ir, 'products_watwermark' paths, Persian
    stock markers («کد فایل»)
  - IMG_PROTOCOL_NOTE teaches subject+color English descriptions
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova_images as ni                     # noqa: E402
import nova as _nova                         # noqa: E402  (version pin)

PIL_OK = importlib.util.find_spec("PIL") is not None
if PIL_OK:
    from PIL import Image                    # noqa: E402

_PHRASES_SRC = dict(ni._FA_EN_PHRASES)   # noqa: E402


def _res(title="a photo", url="http://cdn.example.com/x.jpg", thumb="",
         w=1200, h=800, source="ddg"):
    return {"title": title, "url": url, "thumb": thumb,
            "width": w, "height": h, "source": source}


def _jpg_bytes(w=1200, h=800, color=(180, 60, 60)):
    if not PIL_OK:
        return b"\xff\xd8\xff\xe0" + b"\x00" * 64
    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _png_bytes(w=64, h=64, color=(200, 30, 30)):
    im = Image.new("RGB", (w, h), color)
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


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run_fill(html, name="index.html", results=None, payloads=None,
              search_calls=None):
    """fill_html_images with stubbed providers; optionally records every
    query handed to the (stubbed) search layer. Callers own workspace
    cleanup (addCleanup(shutil.rmtree, ws, True))."""
    ws = Path(tempfile.mkdtemp())
    _write(ws / name, html)
    res = results if results is not None else [
        _res("red rose", "http://cdn.example.com/rose.jpg")]
    payloads = payloads if payloads is not None else {
        "http://cdn.example.com/rose.jpg": _jpg_bytes(1600, 900,
                                                      (190, 40, 40))}

    def fake_search(q, limit=6, deadline=None):
        if search_calls is not None:
            search_calls.append(q)
        return res

    net = _FakeNet(payloads)
    with mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""}), \
         mock.patch.object(ni, "_ddg_search", side_effect=fake_search), \
         mock.patch.object(ni, "_bing_search",
                           return_value=[]), \
         mock.patch.object(ni, "_openverse_search", return_value=[]), \
         mock.patch.object(ni, "_commons_search", return_value=[]), \
         mock.patch.object(ni, "_ns_mod", net):
        extras, notes = ni.fill_html_images(ws, [name])
    out = (ws / name).read_text(encoding="utf-8") \
        if (ws / name).is_file() else ""
    return ws, out, extras, notes, net


def color_share(raw, name):
    """share of pixels matching one _COLOR_SPECS entry (64x64 HSV)"""
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGB").resize((64, 64))
    px = list(im.convert("HSV").getdata())
    hlo, hhi, slo, shi, vlo, vhi, _m = ni._COLOR_SPECS[name]
    cnt = sum(1 for h, s, v in px
              if ((hlo <= h <= hhi) if hlo <= hhi else (h >= hlo or h <= hhi))
              and slo <= s <= shi and vlo <= v <= vhi)
    return cnt / (len(px) or 1)


# --------------------------------------------------------------------------
# 1. dictionary integrity
# --------------------------------------------------------------------------
class TestDictionaries(unittest.TestCase):
    def test_keys_survive_and_values_are_english(self):
        # source phrases must be multi-word (the de-spaced _PHRASES
        # duplicates serve ZWNJ-typed compounds and are checked below)
        for k, v in _PHRASES_SRC.items():
            self.assertTrue(k and " " in k, f"source phrase key: {k!r}")
        for d in (ni._PHRASES, ni._WORDS):
            for k, v in d.items():
                self.assertTrue(k, "empty key")
                self.assertTrue(v and v == v.lower())
                self.assertTrue(all(c.isascii() and (c.isalpha() or c == " ")
                                    for c in v), f"value: {v!r}")

    def test_no_stopword_keys(self):
        for k in list(ni._PHRASES) + list(ni._WORDS):
            # the de-spaced form is what ZWNJ-typed queries hit; a key
            # whose whole folded form is a stopword is a dead entry
            self.assertNotIn(k.replace(" ", ""), ni._FA_STOP,
                             f"dead stopword dict key: {k!r}")
            if " " not in k:
                self.assertNotIn(k, ni._FA_STOP,
                                 f"single-word stopword key: {k!r}")

    def test_colors_have_pixel_specs(self):
        for c in ("red", "green", "blue", "yellow", "pink", "purple",
                  "orange", "brown", "golden", "silver", "gray",
                  "black", "white"):
            self.assertIn(c, ni._COLOR_SPECS, c)
        for spec in ni._COLOR_SPECS.values():
            hlo, hhi, slo, shi, vlo, vhi, mins = spec
            self.assertTrue(0 <= hlo <= 255 and 0 <= hhi <= 255)
            self.assertTrue(0 <= slo <= shi <= 255)
            self.assertTrue(0 <= vlo <= vhi <= 255)
            self.assertGreater(mins, 0.0)
            self.assertLess(mins, 1.0)

    def test_en_known_registry_built(self):
        self.assertIn("rose", ni._EN_KNOWN)
        self.assertIn("flower", ni._EN_KNOWN)
        self.assertNotIn("quux", ni._EN_KNOWN)

    def test_fa_norm_folds_arabic_and_zwnj(self):
        self.assertEqual(ni._fa_norm("رز\u200cقرمز"), "رزقرمز",
                         "ZWNJ is removed so compounds fold onto keys")
        self.assertEqual(ni._fa_norm("کتاب"), ni._fa_norm("كتاب"))
        self.assertEqual(ni._fa_norm("  A   B "), "a b")


# --------------------------------------------------------------------------
# 2. translate_query - the rice trap and the user's phrase
# --------------------------------------------------------------------------
class TestTranslateQuery(unittest.TestCase):
    def test_user_exact_phrase(self):
        t = ni.translate_query("گل رز قرمز")
        self.assertTrue(t["fa"])
        self.assertEqual(t["en"], "red rose")
        self.assertEqual(t["subject"], "rose")
        self.assertEqual(t["colors"], ["red"])

    def test_rice_trap_short_form(self):
        t = ni.translate_query("رز قرمز")
        self.assertEqual(t["en"], "red rose")
        t2 = ni.translate_query("رز")
        self.assertEqual(t2["en"], "rose", "«رز» must never become rice")

    def test_bare_color_stays_color(self):
        t = ni.translate_query("قرمز")
        self.assertEqual(t["colors"], ["red"])
        self.assertEqual(t["subject"], "red")

    def test_english_passthrough_never_reordered(self):
        t = ni.translate_query("red roses bouquet")
        self.assertFalse(t["fa"])
        self.assertEqual(t["en"], "red roses bouquet",
                         "english word order must be preserved")
        self.assertEqual(t["subject"], "bouquet")

    def test_fillers_stripped(self):
        t = ni.translate_query("عکس یک گل رز قرمز زیبا بذار")
        self.assertEqual(t["en"], "red rose")
        t2 = ni.translate_query("لطفا پیدا کن عکس گربه")
        self.assertEqual(t2["en"], "cat")

    def test_zwnj_phrases(self):
        t = ni.translate_query("دسته\u200cگل")
        self.assertEqual(t["en"], "flower bouquet")
        # the ZWNJ-folded 2-gram «دسته‌گل» + «رز» even re-joins the
        # 3-word source phrase دسته گل رز -> rose bouquet
        t2 = ni.translate_query("می\u200cخوام عکس دسته\u200cگل رز")
        self.assertEqual(t2["en"], "rose bouquet")

    def test_tail_trim_keeps_subject(self):
        t = ni.translate_query("red rose background")
        self.assertEqual(t["subject"], "rose")
        self.assertNotIn("background", t["en"])

    def test_unknown_tokens_pass_through(self):
        t = ni.translate_query("quux zorg")
        self.assertEqual(t["en"], "quux zorg")
        self.assertFalse(t["fa"])

    def test_weights_strength_classes(self):
        t = ni.translate_query("گل رز قرمز quux")
        ws = dict(t["weights"])
        self.assertEqual(ws["rose"], 2.5)      # dict noun - strong anchor
        self.assertEqual(ws["red"], 2.0)       # color
        self.assertEqual(ws["quux"], 1.0)      # unknown - weak

    def test_fa_subject_is_head_noun_not_color(self):
        # v7.6 audit fix: core[-1] made the COLOR the subject for every
        # persian noun+color query that is not an exact phrase key
        t = ni.translate_query("گربه سیاه")
        self.assertEqual(t["subject"], "cat")
        self.assertEqual(t["en"], "black cat")
        l = ni.build_ladder(t)
        self.assertIn("black cat", l)
        self.assertNotIn("black black", l, "no junk rung")
        self.assertEqual(ni.translate_query("لاله زرد")["subject"], "tulip")
        self.assertEqual(ni.translate_query("آسمان آبی")["subject"], "sky")
        self.assertEqual(ni.translate_query("رز سرخ")["en"], "red rose")

    def test_lion_not_milk(self):
        # v7.6 audit fix: duplicated «شیر» key silently kept 'milk'
        self.assertEqual(ni.translate_query("شیر")["en"], "lion")
        self.assertIn("lion", ni._EN_KNOWN)

    def test_orig_extra_only_for_fa(self):
        self.assertEqual(ni.translate_query("red rose")["orig_extra"], [])
        self.assertTrue(ni.translate_query("گل رز قرمز")["orig_extra"])

    def test_mixed_script(self):
        t = ni.translate_query("گل rose quux")
        self.assertTrue(t["fa"])
        self.assertIn("rose", t["en"])


# --------------------------------------------------------------------------
# 3. build_ladder
# --------------------------------------------------------------------------
class TestBuildLadder(unittest.TestCase):
    def test_persian_searches_english_first(self):
        l = ni.build_ladder(ni.translate_query("گل رز قرمز"))
        self.assertEqual(l[0], "red rose", "english must go first")
        self.assertIn("گل رز قرمز", l, "original kept as a later rung")
        self.assertLess(l.index("red rose"), l.index("گل رز قرمز"))

    def test_english_tail_drop_sequence_pinned(self):
        l = ni.build_ladder(
            ni.translate_query("mount damavand iran panorama"))
        self.assertEqual(l[0], "mount damavand iran panorama")
        self.assertIn("mount damavand iran", l)
        self.assertIn("mount damavand", l)

    def test_fill_legacy_sequence(self):
        l = ni.build_ladder(ni.translate_query("red roses bouquet hero"))
        self.assertEqual(l[0], "red roses bouquet hero")
        self.assertIn("red roses bouquet", l)
        self.assertTrue(all(len(q.split()) >= 2 for q in l),
                        "never relax below 2 words")

    def test_ladder_never_empty(self):
        for q in ("", "  "):
            self.assertIsInstance(ni.build_ladder(ni.translate_query(q)),
                                  list)
        self.assertEqual(ni.build_ladder(ni.translate_query("x")), ["x"],
                         "a 1-char query has only itself as a rung")
        for q in ("رز", "گل رز قرمز"):
            l = ni.build_ladder(ni.translate_query(q))
            self.assertTrue(l)
            self.assertTrue(all(q2 and len(q2) >= 2 for q2 in l),
                            f"rungs are non-empty for {q!r}: {l}")

    def test_ladder_dedup_and_cap(self):
        l = ni.build_ladder(ni.translate_query("رز رز رز قرمز"))
        self.assertEqual(len(l), len(set(l)))
        self.assertLessEqual(len(l), 5)


# --------------------------------------------------------------------------
# 4. _relevance - branch can never beat rose again
# --------------------------------------------------------------------------
class TestRelevance(unittest.TestCase):
    TQ = ni.translate_query("red rose")

    def test_rose_beats_branch(self):
        branch = _res("simple tree branch on red background",
                      "http://x/branch-red-bg.jpg", w=4000, h=3000)
        rose = _res("red rose flower macro",
                    "http://x/red-rose-flower.jpg", w=600, h=400)
        self.assertGreater(ni._relevance(rose, self.TQ),
                           ni._relevance(branch, self.TQ))

    def test_title_beats_url(self):
        t = _res("plain title", "http://x/red-rose.jpg")
        u = _res("red rose", "http://x/nothing-here.jpg")
        self.assertGreater(ni._relevance(u, self.TQ),
                           ni._relevance(t, self.TQ))

    def test_stems_match(self):
        r = _res("three red roses in a vase", "http://x/roses.jpg")
        self.assertGreater(ni._relevance(r, self.TQ), 3.0)

    def test_persian_candidate_matches_original_words(self):
        tq = ni.translate_query("گل رز قرمز")
        good = _res("عکس های گل رز قرمز",
                    "https://i1.delgarm.com/images/qX.jpg")
        self.assertGreater(ni._relevance(good, tq), 3.0)

    def test_arabic_rice_penalized(self):
        # pure-arabic title («أرز» = rice, NOT the persian letter-equal
        # «رز») so the <2.0 penalty branch really fires: score < 0
        tq = ni.translate_query("رز")           # persian rose
        rice = _res("طريقة عمل الأرز بالشعيرية",
                    "http://yummy.awicdn.com/rice-recipe.jpg")
        prose = _res("عکس گل رز قرمز", "http://x/red-rose.jpg")
        sr = ni._relevance(rice, tq)
        self.assertLess(sr, 0.0, "arabic lookalike must be penalized")
        self.assertLess(sr, ni._relevance(prose, tq))

    def test_never_raises_on_junk(self):
        for junk in ({}, {"title": None, "url": None},
                     {"title": 42, "url": ""}, {"url": "http://x/a.jpg"}):
            self.assertIsInstance(ni._relevance(junk, self.TQ), float)

    def test_unknown_token_is_a_weak_anchor(self):
        tq = ni.translate_query("quux rose")
        r1 = _res("red rose", "http://x/rose.jpg")
        r2 = _res("quux thing", "http://x/quux.jpg")
        self.assertGreater(ni._relevance(r1, tq), ni._relevance(r2, tq))


# --------------------------------------------------------------------------
# 5. search_images ranking integration
# --------------------------------------------------------------------------
class TestSearchRanking(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_relevance_reorders_within_tier(self):
        branch = _res("simple tree branch on red background",
                      "http://x/branch.jpg", w=4000, h=3000)
        rose = _res("red rose flower", "http://x/rose.jpg", w=600, h=400)
        # feed branch FIRST so only relevance can demote it
        with mock.patch.object(ni, "_ns_mod", object()), \
             mock.patch.object(ni, "_ddg_search",
                               return_value=[branch, rose]), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            out = ni.search_images("red rose", limit=2)
        self.assertEqual(out[0]["url"], "http://x/rose.jpg")

    def test_no_crash_with_empty_results(self):
        with mock.patch.object(ni, "_ns_mod", object()), \
             mock.patch.object(ni, "_ddg_search", return_value=[]), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            self.assertEqual(ni.search_images("گل رز قرمز", limit=3), [])


# --------------------------------------------------------------------------
# 6. _passes_color - pixel verification
# --------------------------------------------------------------------------
@unittest.skipUnless(PIL_OK, "Pillow not installed")
class TestColorGate(unittest.TestCase):
    def test_red_passes_red(self):
        raw = _png_bytes(64, 64, (200, 30, 30))
        self.assertTrue(ni._passes_color(raw, "png", ["red"]))

    def test_green_fails_red(self):
        raw = _png_bytes(64, 64, (40, 190, 60))
        self.assertFalse(ni._passes_color(raw, "png", ["red"]))

    def test_white_fails_red_passes_white(self):
        raw = _png_bytes(64, 64, (245, 245, 245))
        self.assertFalse(ni._passes_color(raw, "png", ["red"]))
        self.assertTrue(ni._passes_color(raw, "png", ["white"]))

    def test_black_and_gray(self):
        self.assertTrue(ni._passes_color(
            _png_bytes(64, 64, (10, 10, 10)), "png", ["black"]))
        self.assertTrue(ni._passes_color(
            _png_bytes(64, 64, (128, 128, 128)), "png", ["gray"]))
        self.assertFalse(ni._passes_color(
            _png_bytes(64, 64, (128, 128, 128)), "png", ["black"]))

    def test_mixed_photo_partial_red(self):
        # a rose on green leaves: ~40% red pixels still passes
        im = Image.new("RGB", (80, 80), (40, 160, 50))
        for x in range(32):
            for y in range(80):
                im.putpixel((x, y), (205, 25, 35))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        self.assertTrue(ni._passes_color(buf.getvalue(), "png", ["red"]))
        # ~4% red: below the 6% share threshold -> rejected
        im2 = Image.new("RGB", (80, 80), (40, 160, 50))
        for x in range(3):
            for y in range(80):
                im2.putpixel((x, y), (205, 25, 35))
        buf2 = io.BytesIO()
        im2.save(buf2, "PNG")
        self.assertFalse(ni._passes_color(buf2.getvalue(), "png", ["red"]),
                         "3.75% red is below the 6% share threshold")

    def test_soft_gate_never_rejects(self):
        self.assertTrue(ni._passes_color(b"junk", "jpg", ["red"]))
        self.assertTrue(ni._passes_color(b"\x89PNG" + b"00" * 8, "png",
                                         ["red"]))
        self.assertTrue(ni._passes_color(_png_bytes(), "gif", ["red"]))
        self.assertTrue(ni._passes_color(_png_bytes(), "png", []))
        self.assertTrue(ni._passes_color(_png_bytes(), "png",
                                         ["chartreuse"]))


# --------------------------------------------------------------------------
# 7. fill_html_images end-to-end with the color gate
# --------------------------------------------------------------------------
class TestFillColorGate(unittest.TestCase):
    def setUp(self):
        # the fill tests must pass even on a box with the kill switch set
        self._env = mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_color_gate_picks_the_matching_photo(self):
        branch = _res("simple tree branch on red background",
                      "http://x/branch.jpg", w=2000, h=1400)
        rose = _res("red rose flower", "http://x/rose.jpg", w=1400, h=1000)
        ws, out, extras, notes, net = _run_fill(
            '<html><body><img src="IMG:red rose" alt="گل رز"></body></html>',
            results=[branch, rose],
            payloads={"http://x/rose.jpg": _jpg_bytes(1600, 1000,
                                                      (195, 30, 35)),
                      "http://x/branch.jpg": _jpg_bytes(2000, 1400,
                                                        (40, 170, 60))})
        self.addCleanup(shutil.rmtree, ws, True)
        self.assertTrue(extras and extras[0][0].endswith(".jpg"))
        # the branch's ASSET HASH must be absent from the page - a file
        # name alone proves nothing (it derives from the query)
        branch_asset = ni.image_name("http://x/branch.jpg", "red rose l",
                                     "jpg")
        self.assertNotIn(branch_asset, out,
                         "the green branch photo must never be stored")
        self.assertNotIn("_ph-", out, "no placeholder")
        # and the stored photo really IS red
        raw = extras[0][1]
        self.assertGreaterEqual(color_share(raw, "red"), 0.06)

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_color_softened_fallback_still_a_photo(self):
        """v8.0.1 re-pin: the SOFT GATE survives for SUBJECT-ANCHORED
        candidates - a real rose photo without enough red pixels still
        ships (color softened) instead of a placeholder."""
        rose = _res("red rose flower", "http://x/rose.jpg",
                    w=2000, h=1400)
        ws, out, extras, notes, net = _run_fill(
            '<html><body><img src="IMG:red rose" alt="r"></body></html>',
            results=[rose],
            payloads={"http://x/rose.jpg": _jpg_bytes(2000, 1400,
                                                      (40, 170, 60))})
        self.assertTrue(extras, "photo even when the color is missing")
        self.assertNotIn("_ph-", out, "NEVER a placeholder when a real "
                                      "subject photo exists (soft gate)")
        self.assertTrue(any("color softened" in n for n in notes), notes)

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_subject_orphan_gets_placeholder_not_wrong_photo(self):
        """v8.0.1 SUBJECT ORPHAN GATE: 'green plant branches' for a
        'red rose' slot is a WRONG photo - the old pin shipped it
        softened; the coffe8/coffee81 reports (a DVD poster as a cafe
        hero, a random man as a croissant) prove a wrong photo is worse
        than the clean subject-labelled art placeholder. Orphans are
        skipped; when nothing anchored survives the slot goes
        placeholder."""
        branch = _res("green plant branches", "http://x/branch.jpg",
                      w=2000, h=1400)
        ws, out, extras, notes, net = _run_fill(
            '<html><body><img src="IMG:red rose" alt="r"></body></html>',
            results=[branch],
            payloads={"http://x/branch.jpg": _jpg_bytes(2000, 1400,
                                                        (40, 170, 60))})
        self.assertNotIn("branch.jpg", out,
                         "a subject-orphan must never be embedded")
        self.assertIn("_ph-red-rose-", out, "placeholder carries the "
                                             "subject label")
        # the placeholder joins the undo unit as the slot's asset
        self.assertEqual([e[0] for e in extras],
                         ["assets/images/_ph-red-rose-7ec743ff.svg"])

    def test_persian_query_searches_english_first(self):
        calls = []
        ws, out, extras, notes, net = _run_fill(
            '<html><body><img src="IMG:گل رز قرمز" alt="گل"></body></html>',
            search_calls=calls)
        self.assertTrue(calls)
        self.assertEqual(calls[0], "red rose",
                         "the rice trap can never fire again")
        self.assertTrue(extras and extras[0][0].endswith(".jpg"))


# --------------------------------------------------------------------------
# 8. pick_and_save with the relevance engine
# --------------------------------------------------------------------------
class TestPickAndSaveV76(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_persian_query_picks_subject_matched_photo(self):
        ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ws, True)
        rice = _res("طريقة عمل الأرز بالشعيرية", "http://x/rice.jpg")
        rose = _res("red rose", "http://x/rose.jpg")
        net = _FakeNet({"http://x/rose.jpg": _jpg_bytes(1600, 1000,
                                                        (190, 40, 40)),
                        "http://x/rice.jpg": _jpg_bytes(1600, 1000,
                                                        (240, 230, 210))})
        with mock.patch.object(ni, "_ddg_search",
                               return_value=[rice, rose]), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]), \
             mock.patch.object(ni, "_ns_mod", net):
            rel, _s, _m = ni.pick_and_save("رز قرمز", ws)
        self.assertIsNotNone(rel)
        self.assertIn("red-rose", rel,
                      "asset named after the ENGLISH query")
        self.assertNotIn("http://x/rice.jpg", net.calls,
                         "the rice candidate must lose the ranking")

    @unittest.skipUnless(PIL_OK, "Pillow not installed")
    def test_color_softened_meta_and_cache(self):
        ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ws, True)
        only_green = _res("green leaves", "http://x/g.jpg")
        net = _FakeNet({"http://x/g.jpg": _jpg_bytes(1600, 1000,
                                                     (40, 170, 60))})
        with mock.patch.object(ni, "_ddg_search",
                               return_value=[only_green]), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]), \
             mock.patch.object(ni, "_ns_mod", net):
            rel, _s, meta = ni.pick_and_save("گل رز قرمز", ws)
        self.assertIsNotNone(rel, "soft fallback still saves a photo")
        self.assertTrue(meta.get("color_softened"))
        # cache: the SAME original query must hit without searching again
        with mock.patch.object(ni, "_ddg_search",
                               side_effect=AssertionError("no re-search")):
            rel2, source, _m2 = ni.pick_and_save("گل رز قرمز", ws)
        self.assertEqual(rel2, rel)
        self.assertEqual(source, "cache")

    def test_empty_query(self):
        ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ws, True)
        rel, _s, meta = ni.pick_and_save("   ", ws)
        self.assertIsNone(rel)
        self.assertIn("error", meta)


# --------------------------------------------------------------------------
# 9. watermark / stock hardening (v7.6)
# --------------------------------------------------------------------------
class TestWatermarkHardening(unittest.TestCase):
    def test_tarh_ir_host_gated(self):
        self.assertTrue(ni._host_bad("https://tarh.ir/storage/p.jpg"))
        self.assertTrue(ni._host_bad(
            "http://www.tarh.ir/storage/products_watwermark/x.webp"))

    def test_watwermark_typo_path_gated(self):
        r = _res("گل رز", "https://tarh.ir/storage/products_watwermark/"
                          "Tarhir_P_1786.webp")
        self.assertTrue(ni._text_bad(r))

    def test_persian_stock_markers_gated(self):
        for blob in ("تصویر باکیفیت انگور قرمز | طرح دات آی آر",
                     "https://x.com/f/کد فایل 1466279.jpg",
                     "https://x.com/f/واترمارک.png"):
            self.assertTrue(ni._text_bad(_res(blob, blob)))

    def test_clean_persian_title_not_gated(self):
        r = _res("عکس های گل رز قرمز",
                 "https://i1.delgarm.com/images/newsread/x.jpg")
        self.assertFalse(ni._text_bad(r))


# --------------------------------------------------------------------------
# 10. smart_search + protocol note + version
# --------------------------------------------------------------------------
class TestSmartSearch(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"NOVA_NO_IMAGES": ""})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_returns_results_and_tq(self):
        tq_expected = ni.translate_query("گل رز قرمز")
        with mock.patch.object(ni, "_ns_mod", object()), \
             mock.patch.object(ni, "_ddg_search",
                               return_value=[_res("red rose",
                                                  "http://x/rose.jpg")]), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            results, tq = ni.smart_search("گل رز قرمز", limit=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(tq["en"], tq_expected["en"])
        self.assertEqual(tq["colors"], ["red"])

    def test_walks_the_ladder_until_results(self):
        calls = []

        def ddg(q, limit, deadline):
            calls.append(q)
            return [_res("damavand", "http://a/1.jpg")] \
                if len(q.split()) <= 2 else []

        with mock.patch.object(ni, "_ns_mod", object()), \
             mock.patch.object(ni, "_ddg_search", side_effect=ddg), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            results, _tq = ni.smart_search("mount damavand iran panorama",
                                           limit=3)
        self.assertEqual(len(results), 1)
        self.assertIn("mount damavand", calls)

    def test_all_rungs_empty(self):
        with mock.patch.object(ni, "_ns_mod", object()), \
             mock.patch.object(ni, "_ddg_search", return_value=[]), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]), \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            results, tq = ni.smart_search("گل رز قرمز", limit=3)
        self.assertEqual(results, [])
        self.assertEqual(tq["colors"], ["red"])

    def test_protocol_note_teaches_english_subject_color(self):
        note = ni.IMG_PROTOCOL_NOTE.lower()
        self.assertIn("img:", note)
        self.assertIn("english", note)
        self.assertIn("red rose", note)
        self.assertIn("never", note)

    def test_version(self):
        self.assertEqual(_nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
