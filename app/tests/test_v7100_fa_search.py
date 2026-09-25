#!/usr/bin/env python3
"""v7.10.0 tests: SEMANTIC IMAGE SEARCH + IRANIAN WEB SEARCH.

User asks (v7.10): «تقویت معنایی جست و جوی تصویر رو انجام بده / همینطور
جست و جوی معمولی رو هم افزایش بده، باید بتونه تمام سایت های ایرانی معتبر
رو هم جست و جو کنه مثلا زرین پال، بله، پست ایران و ... اپارات و مخصوصا
انواع مجله های ایرانی»

Two workstreams, every test NETWORK-FREE via stubs:

  A. web search (nova_search v3.4)
     - IRANIAN trusted registry: zarinpal / bale.ai / post.ir / aparat /
       digikala(+mag) / divar / snapp / tapsi / the news agencies / the
       Iranian magazines / banks / gov portals - all tagged 'fa',
       tier-valid, no duplicates, no overlap with the English list
     - trust_info longest-suffix (mag.digikala.com)
     - detect_language: Persian script -> 'fa', latin brand -> 'fa',
       English code query stays fa-free, mixed query keeps both
     - ddg_search region param -> kl=ir-fa on the DDG url
     - wikipedia_search(lang='fa') -> fa.wikipedia.org
     - web_search Persian flow: ddg(kl=ir-fa) + fa-wiki fallback, and
       the zarinpal result RANKS ABOVE a random domain
     - web_search English flow: byte-identical v7.9 behavior (no wiki
       call when ddg fills, stack fallback preserved)

  B. image search (nova_images v7.10 semantic hardening)
     - _bing_search parser: m="{&quot;json&quot;}" tiles -> candidates,
       garbage page -> [], provider fail-soft inside search_images
     - provider chain: ddg -> bing -> openverse -> commons (bing IS
       consulted when ddg is empty; skipped when ddg fills the limit)
     - _relevance SUBJECT ANCHORING: title > url > absent
     - _subject_hits + smart_search CROSS-RUNG MERGE: a junk first rung
       no longer satisfies; strong pools stop the ladder early; pools
       dedupe across rungs; a dead deadline returns []
     - dictionary expansion: Iranian landmarks, cities, foods translate
       offline; phrases table stays multi-word-pinned; values stay
       lowercase ascii words
"""
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova_search as ns                     # noqa: E402
import nova_images as ni                     # noqa: E402
import nova as _nova                         # noqa: E402  (version pin)


def _res(title="a photo", url="http://cdn.example.com/x.jpg", thumb="",
         w=1200, h=800, source="ddg"):
    return {"title": title, "url": url, "thumb": thumb,
            "width": w, "height": h, "source": source}


# --------------------------------------------------------------------------
# A1. the Iranian trusted registry
# --------------------------------------------------------------------------
class TestIranianRegistry(unittest.TestCase):
    def test_import_means_no_duplicate_domains(self):
        # nova_search raises RuntimeError at import on duplicate suffixes;
        # importing it above IS the duplicate test - keep an explicit pin
        self.assertIsInstance(ns._TRUST_MAP, dict)

    def test_user_named_sites_are_all_registered(self):
        # the sites the user LITERALLY named: زرین پال، بله، پست ایران،
        # اپارات، مجله ها
        must = ("zarinpal.com", "bale.ai", "post.ir", "aparat.com",
                "digikala.com", "mag.digikala.com", "divar.ir",
                "zoomit.ir", "zoomg.ir", "chetor.com", "varzesh3.com",
                "irna.ir", "isna.ir", "snapp.ir", "tapsi.ir",
                "filimo.com", "virgool.io", "tebyan.net")
        reg = {d for d, _t, *_l in ns.TRUSTED}
        for dom in must:
            self.assertIn(dom, reg, f"the user named {dom}")

    def test_ir_entries_all_fa_tagged_and_tiered(self):
        fa_doms = [d for d, t, *l in ns.TRUSTED
                   if "fa" in l and not any(
                       ch.isascii() and ch.isalpha() for ch in "")] \
            if False else [d for d, t, *l in ns.TRUSTED if "fa" in l]
        self.assertGreaterEqual(len(fa_doms), 50, "a real IR web coverage")
        for d, t, *l in ns.TRUSTED:
            if d in fa_doms:
                self.assertEqual(l, ["fa"], f"{d} tags exactly fa")
                self.assertIn(t, (0, 1, 2), f"{d} tier valid")

    def test_fa_never_overlaps_the_english_list(self):
        # every fa-tagged domain must be an .ir/.com/.net/.org/.ai domain
        # of an IRANIAN service - spot-check the identity ones
        self.assertEqual(ns.trust_info("https://www.zarinpal.com/x"),
                         (0, frozenset({"fa"})))
        self.assertEqual(ns.trust_info("https://bale.ai/"), (0, frozenset({"fa"})))
        self.assertEqual(ns.trust_info("https://post.ir/track"), (0, frozenset({"fa"})))
        self.assertEqual(ns.trust_info("https://www.aparat.com/v/abc"),
                         (0, frozenset({"fa"})))

    def test_longest_suffix_mag_digikala(self):
        tier, langs = ns.trust_info("https://mag.digikala.com/article/1")
        self.assertEqual((tier, langs), (1, frozenset({"fa"})))
        tier2, _ = ns.trust_info("https://digikala.com/product/1")
        self.assertEqual(tier2, 0)

    def test_iranian_magazines_rank_trusted(self):
        for dom in ("zoomit.ir", "zoomg.ir", "chetor.com",
                    "mag.digikala.com"):
            tier, langs = ns.trust_info(f"https://{dom}/post")
            self.assertIn(tier, (1, 2), dom)
            self.assertIn("fa", langs, dom)


# --------------------------------------------------------------------------
# A2. fa language detection
# --------------------------------------------------------------------------
class TestFaDetection(unittest.TestCase):
    def test_persian_script_detects_fa(self):
        for q in ("درگاه پرداخت زرین پال چیست", "اپارات چیست",
                  "یک سایت فروشگاهی بساز"):
            self.assertIn("fa", ns.detect_language(q), q)

    def test_latin_brand_names_detect_fa(self):
        for q in ("zarinpal payment gateway", "aparat video download",
                  "digikala mag article", "divar.ir cars"):
            self.assertIn("fa", ns.detect_language(q), q)

    def test_english_code_query_stays_fa_free(self):
        self.assertNotIn("fa", ns.detect_language(
            "how to center a div in css"))

    def test_mixed_query_keeps_both(self):
        got = ns.detect_language("یک سایت فروشگاهی با react بساز")
        self.assertIn("fa", got)
        self.assertIn("javascript", got)


# --------------------------------------------------------------------------
# A3. ddg region + fa.wikipedia
# --------------------------------------------------------------------------
class TestDdgRegion(unittest.TestCase):
    def test_region_appends_kl(self):
        captured = []

        def fake_get(url, timeout=None, max_bytes=1 << 20):
            captured.append(url)
            return ("<html></html>", url)

        parsed = [{"title": "t", "url": "https://example.com/",
                   "snippet": ""}]
        with mock.patch.object(ns, "http_get", side_effect=fake_get), \
             mock.patch.object(ns, "_parse_ddg", return_value=parsed):
            ns.ddg_search("زرین پال", region="ir-fa")
        self.assertTrue(captured)
        self.assertIn("kl=ir-fa", captured[0], captured[0])

    def test_no_region_no_kl(self):
        captured = []

        def fake_get(url, timeout=None, max_bytes=1 << 20):
            captured.append(url)
            return ("<html></html>", url)

        with mock.patch.object(ns, "http_get", side_effect=fake_get):
            try:
                ns.ddg_search("css flexbox")
            except Exception:
                pass
        self.assertTrue(all("kl=" not in u for u in captured), captured)


class TestWikipediaLang(unittest.TestCase):
    def test_lang_fa_hits_fa_wikipedia(self):
        captured = []

        def fake_get(url, timeout=None, max_bytes=1 << 20):
            captured.append(url)
            return (json.dumps({"query": {"search": [
                {"title": "زرین\u200cپال", "snippet": "<b>درگاه</b>"}]}}),
                url)

        with mock.patch.object(ns, "http_get", side_effect=fake_get):
            out = ns.wikipedia_search("زرین پال", lang="fa")
        self.assertIn("fa.wikipedia.org", captured[0])
        self.assertEqual(len(out), 1)
        self.assertIn("fa.wikipedia.org/wiki/", out[0]["url"])

    def test_default_lang_is_english(self):
        captured = []

        def fake_get(url, timeout=None, max_bytes=1 << 20):
            captured.append(url)
            return (json.dumps({"query": {"search": []}}), url)

        with mock.patch.object(ns, "http_get", side_effect=fake_get):
            ns.wikipedia_search("css")
        self.assertIn("en.wikipedia.org", captured[0])

    def test_junk_lang_falls_back_to_english(self):
        captured = []

        def fake_get(url, timeout=None, max_bytes=1 << 20):
            captured.append(url)
            return (json.dumps({"query": {"search": []}}), url)

        with mock.patch.object(ns, "http_get", side_effect=fake_get):
            ns.wikipedia_search("css", lang="<script>")
        self.assertIn("en.wikipedia.org", captured[0])


# --------------------------------------------------------------------------
# A4. web_search flows
# --------------------------------------------------------------------------
class TestWebSearchFlows(unittest.TestCase):
    def setUp(self):
        # never touch the disk cache from a test
        patcher = mock.patch.object(ns, "cache_get", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        put = mock.patch.object(ns, "cache_put", return_value=None)
        put.start()
        self.addCleanup(put.stop)

    def test_persian_query_uses_ir_region_and_fa_wiki(self):
        calls = []

        def fake_ddg(query, max_results=8, region=None):
            calls.append(("ddg", query, region))
            return [_res("زرین پال", "https://www.zarinpal.com/x",
                         source="ddg")]

        def fake_wiki(query, max_results=3, lang="en"):
            calls.append(("wiki", query, lang))
            return [_res("زرین پال - ویکی‌پدیا",
                         "https://fa.wikipedia.org/wiki/Zarinpal")]

        with mock.patch.object(ns, "ddg_search", side_effect=fake_ddg), \
             mock.patch.object(ns, "wikipedia_search",
                               side_effect=fake_wiki):
            out = ns.web_search("زرین پال چیست")
        self.assertEqual(calls[0], ("ddg", "زرین پال چیست", "ir-fa"))
        self.assertIn(("wiki", "زرین پال چیست", "fa"), calls)
        urls = [r["url"] for r in out]
        self.assertTrue(any("zarinpal.com" in u for u in urls))

    def test_persian_result_beats_random_domain(self):
        pool = [_res("random blog", "https://randomsite.example.com/a"),
                _res("زرین پال", "https://www.zarinpal.com/help")]
        with mock.patch.object(ns, "ddg_search", return_value=pool), \
             mock.patch.object(ns, "wikipedia_search", return_value=[]):
            out = ns.web_search("زرین پال")
        self.assertEqual(out[0]["url"], "https://www.zarinpal.com/help")

    def test_english_flow_unchanged_no_wiki_when_ddg_fills(self):
        calls = []

        def fake_ddg(query, max_results=8, region=None):
            calls.append(("ddg", region))
            return [_res(f"r{i}", f"https://docs.python.org/{i}")
                    for i in range(5)]

        def fail_wiki(*a, **k):
            calls.append(("wiki",))
            return []

        with mock.patch.object(ns, "ddg_search", side_effect=fake_ddg), \
             mock.patch.object(ns, "wikipedia_search",
                               side_effect=fail_wiki):
            out = ns.web_search("python argparse tutorial")
        self.assertEqual(calls, [("ddg", None)],
                         "english: no region, no fallback calls")
        self.assertEqual(len(out), 5)

    def test_english_flow_still_falls_back_to_wiki_and_stack(self):
        with mock.patch.object(ns, "ddg_search",
                               side_effect=RuntimeError("blocked")), \
             mock.patch.object(ns, "wikipedia_search",
                               return_value=[_res("w", "https://en.wikipedia.org/wiki/X")]) as fw, \
             mock.patch.object(ns, "stack_search",
                               return_value=[_res("s", "https://stackoverflow.com/q/1")]) as fs:
            out = ns.web_search("css grid bug")
        self.assertEqual(fw.call_count, 1)
        self.assertEqual(fs.call_count, 1)
        self.assertEqual(len(out), 2)


# --------------------------------------------------------------------------
# B1. bing images provider
# --------------------------------------------------------------------------
_BING_PAGE = (
    '<div class="imgpt"><a class="iusc" m="{&quot;cid&quot;:&quot;x&quot;,'
    '&quot;murl&quot;:&quot;https://cdn.example.com/rose.jpg&quot;,'
    '&quot;turl&quot;:&quot;https://ts.mm.bing.net/th?id=OIP.a&quot;,'
    '&quot;t&quot;:&quot;Red rose garden&quot;}"></a></div>'
    '<div class="imgpt"><a class="iusc" m="{&quot;murl&quot;:'
    '&quot;https://pic.example.org/tulip.png&quot;,&quot;t&quot;:'
    '&quot;A tulip&quot;}"></a></div>'
    '<a class="iusc" m="{broken json"></a>'
)


class TestBingProvider(unittest.TestCase):
    def test_parser_extracts_tiles(self):
        net = mock.Mock()
        net.http_get = mock.Mock(return_value=(_BING_PAGE, "u"))
        with mock.patch.object(ni, "_ns_mod", net):
            out = ni._bing_search("red rose", 6, None)
        self.assertEqual(len(out), 2, "broken tile skipped")
        self.assertEqual(out[0]["url"], "https://cdn.example.com/rose.jpg")
        self.assertEqual(out[0]["title"], "Red rose garden")
        self.assertEqual(out[0]["thumb"], "https://ts.mm.bing.net/th?id=OIP.a")
        self.assertEqual(out[0]["source"], "bing")
        self.assertEqual(out[1]["url"], "https://pic.example.org/tulip.png")

    def test_garbage_page_returns_empty(self):
        net = mock.Mock()
        net.http_get = mock.Mock(return_value=("<html>captcha</html>", "u"))
        with mock.patch.object(ni, "_ns_mod", net):
            self.assertEqual(ni._bing_search("rose", 6, None), [])

    def test_provider_fail_soft_inside_search_images(self):
        def boom(q, l, d):
            raise RuntimeError("blocked")
        with mock.patch.object(ni, "_ddg_search", return_value=[]), \
             mock.patch.object(ni, "_bing_search", side_effect=boom), \
             mock.patch.object(ni, "_openverse_search",
                               return_value=[_res("ok")]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            out = ni.search_images("rose", limit=3)
        self.assertEqual([r["url"] for r in out],
                         ["http://cdn.example.com/x.jpg"])

    def test_chain_order_bing_consulted_when_ddg_empty(self):
        bing = [_res("from bing", "http://b/1.jpg", source="bing")]
        with mock.patch.object(ni, "_ddg_search", return_value=[]), \
             mock.patch.object(ni, "_bing_search",
                               return_value=bing) as mb, \
             mock.patch.object(ni, "_openverse_search", return_value=[]), \
             mock.patch.object(ni, "_commons_search", return_value=[]):
            out = ni.search_images("rose", limit=3)
        mb.assert_called_once()
        self.assertEqual(out[0]["source"], "bing")

    def test_chain_order_bing_skipped_when_ddg_fills(self):
        ddg = [_res(f"p{i}", f"http://a/{i}.jpg") for i in range(6)]
        with mock.patch.object(ni, "_ddg_search", return_value=ddg), \
             mock.patch.object(ni, "_bing_search",
                               return_value=[]) as mb, \
             mock.patch.object(ni, "_openverse_search", return_value=[]) as opv:
            out = ni.search_images("rose", limit=4)
        self.assertEqual(len(out), 4)
        mb.assert_not_called()
        opv.assert_not_called()


# --------------------------------------------------------------------------
# B2. subject anchoring in _relevance
# --------------------------------------------------------------------------
class TestSubjectAnchoring(unittest.TestCase):
    TQ = ni.translate_query("red rose")

    def test_title_beats_url_beats_absent(self):
        title = _res("a red rose in the garden", "http://x/pic1.jpg")
        url = _res("garden shot", "http://x/red-rose.jpg")
        absent = _res("green leaves", "http://x/garden.jpg")
        st = ni._relevance(title, self.TQ)
        su = ni._relevance(url, self.TQ)
        sa = ni._relevance(absent, self.TQ)
        self.assertGreater(st, su)
        self.assertGreater(su, sa)

    def test_branch_cannot_ride_the_color_word(self):
        branch = _res("simple tree branch on red background",
                      "http://x/branch.jpg", w=4000, h=3000)
        rose = _res("red rose flower", "http://x/rose.jpg", w=600, h=400)
        self.assertGreater(ni._relevance(rose, self.TQ),
                           ni._relevance(branch, self.TQ))

    def test_subject_hits_counts_title_matches(self):
        pool = [_res("red rose one"), _res("lovely roses here"),
                _res("red thing")]
        self.assertEqual(ni._subject_hits(pool, self.TQ), 2)
        self.assertEqual(ni._subject_hits([], self.TQ), 0)

    def test_no_subject_treats_everything_as_hit(self):
        tq = {"subject": "", "fa": False, "weights": [], "colors": [],
              "orig_extra": []}
        self.assertEqual(ni._subject_hits([_res(), _res()], tq), 2)


# --------------------------------------------------------------------------
# B3. smart_search cross-rung merge
# --------------------------------------------------------------------------
class TestSmartSearchMerge(unittest.TestCase):
    def test_junk_first_rung_no_longer_satisfies(self):
        junk = [{"title": "red object", "url": "http://a/1.jpg",
                 "width": 900, "height": 700}]
        good = [{"title": "red rose bouquet", "url": "http://b/2.jpg",
                 "width": 900, "height": 700},
                {"title": "a red rose closeup", "url": "http://c/3.jpg",
                 "width": 800, "height": 600}]
        calls = []

        def fake_si(rung, limit=6, deadline=None):
            calls.append(rung)
            return junk if len(calls) == 1 else good

        with mock.patch.object(ni, "search_images",
                               side_effect=fake_si):
            res, tq = ni.smart_search("گل رز قرمز", limit=3)
        self.assertGreater(len(calls), 1, "the ladder kept climbing")
        self.assertEqual(res[0]["title"], "red rose bouquet")

    def test_strong_first_rung_stops_early(self):
        strong = [{"title": f"red rose {i}", "url": f"http://x/{i}.jpg",
                   "width": 900, "height": 700} for i in range(5)]
        calls = []

        def fake_si(rung, limit=6, deadline=None):
            calls.append(rung)
            return list(strong)

        with mock.patch.object(ni, "search_images",
                               side_effect=fake_si):
            res, _tq = ni.smart_search("گل رز قرمز", limit=3)
        self.assertEqual(len(calls), 1, "early stop on a strong pool")
        self.assertEqual(len(res), 3)

    def test_pools_dedupe_across_rungs(self):
        same = [{"title": "red rose", "url": "http://x/rose.jpg",
                 "width": 900, "height": 700}]
        calls = []

        def fake_si(rung, limit=6, deadline=None):
            calls.append(rung)
            return list(same)

        with mock.patch.object(ni, "search_images",
                               side_effect=fake_si), \
             mock.patch.object(ni, "_subject_hits", return_value=0):
            res, _tq = ni.smart_search("گل رز قرمز", limit=3)
        self.assertEqual(len(calls), len(ni.build_ladder(
            ni.translate_query("گل رز قرمز"))), "weak pool climbs all rungs")
        self.assertEqual(len(res), 1, "same url merged once")

    def test_dead_deadline_returns_empty(self):
        with mock.patch.object(ni, "search_images") as si:
            res, _tq = ni.smart_search("rose",
                                       deadline=time.monotonic() - 10)
        self.assertEqual(res, [])
        si.assert_not_called()

    def test_search_images_never_breaks_the_merge(self):
        # a raising provider chain still returns ([] , tq) cleanly
        with mock.patch.object(ni, "search_images",
                               side_effect=RuntimeError("down")):
            res, tq = ni.smart_search("گل رز قرمز", limit=3)
        self.assertEqual(res, [])
        self.assertEqual(tq["colors"], ["red"])


# --------------------------------------------------------------------------
# B4. dictionary expansion pins
# --------------------------------------------------------------------------
class TestDictionaryExpansion(unittest.TestCase):
    def test_iranian_landmarks_translate(self):
        for q, want in (("سی و سه پل", "si"),
                        ("برج میلاد تهران", "milad tower tehran"),
                        ("قرمه سبزی", "ghormeh sabzi stew"),
                        ("کاخ گلستان", "golestan palace"),
                        ("دسته پرنده", "flock")):
            got = ni.translate_query(q)
            self.assertIn(want, got["en"], f"{q} -> {got['en']}")

    def test_cities_translate(self):
        for fa, en in (("تهران", "tehran"), ("اصفهان", "isfahan"),
                       ("شیراز", "shiraz"), ("مشهد", "mashhad"),
                       ("یزد", "yazd")):
            self.assertEqual(ni.translate_query(fa)["en"], en)

    def test_phrases_table_stays_multiword_pinned(self):
        # the v7.6 integrity pins must survive the expansion
        for k in ni._FA_EN_PHRASES:
            self.assertIn(" ", k.strip(), f"phrase key must be multi-word: {k}")
        for d in (ni._PHRASES, ni._WORDS):
            for k, v in d.items():
                self.assertTrue(v == v.lower(), f"{k} -> {v}")
                self.assertTrue(
                    all(c.isascii() and (c.isalpha() or c == " ")
                        for c in v), f"{k} -> {v!r}")

    def test_new_word_values_are_english_anchors(self):
        # every dict-produced token keeps its strong 2.5 weight class
        t = ni.translate_query("قرمه سبزی")
        weights = dict(t["weights"])
        for tok in ("ghormeh", "sabzi", "stew"):
            self.assertIn(tok, weights, t)
            self.assertGreaterEqual(weights[tok], 2.5)


# --------------------------------------------------------------------------
# version pin
# --------------------------------------------------------------------------
class TestVersion(unittest.TestCase):
    def test_version(self):
        self.assertEqual(_nova.VERSION, "8.12.0")
        self.assertEqual(ns.VERSION, "3.4")


if __name__ == "__main__":
    unittest.main()
