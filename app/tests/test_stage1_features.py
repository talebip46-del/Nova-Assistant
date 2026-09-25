#!/usr/bin/env python3
"""Stage-1 feature tests: .novaignore, command policy, profiles,
cross-run memory, cost tracker. Pure stdlib, temp dirs, no network."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_policy as npol
import nova_project as nproj
import nova_memory as nmem
import nova_cost as ncost


class TempWS(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_t1_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)


# ------------------------------------------------- .novaignore
class TestNovaIgnore(TempWS):
    def _ig(self, text):
        (self.ws / ".novaignore").write_text(text, encoding="utf-8")
        return npol.NovaIgnore.load(self.ws)

    def test_no_file_no_ignores(self):
        ig = npol.NovaIgnore.load(self.ws)
        self.assertFalse(ig.matches("anything.py"))
        self.assertEqual(ig.error, "")

    def test_basename_any_depth(self):
        ig = self._ig("*.log\n")
        self.assertTrue(ig.matches("debug.log"))
        self.assertTrue(ig.matches("a/b/c/debug.log"))
        self.assertFalse(ig.matches("a/main.py"))

    def test_dir_any_depth_with_content(self):
        ig = self._ig("build/\n")
        self.assertTrue(ig.matches("build", is_dir=True))
        self.assertTrue(ig.matches("build/out.o"))
        self.assertTrue(ig.matches("sub/build/out.o"))
        self.assertFalse(ig.matches("build.py"))       # file, not the dir
        self.assertFalse(ig.matches("builder/x.js"))   # prefix must not match

    def test_anchored_path(self):
        ig = self._ig("/secret.txt\ndata/raw/\n")
        self.assertTrue(ig.matches("secret.txt"))
        self.assertFalse(ig.matches("sub/secret.txt"))  # anchored = root only
        self.assertTrue(ig.matches("data/raw/a.csv"))
        self.assertTrue(ig.matches("data/raw", is_dir=True))
        self.assertFalse(ig.matches("data"))

    def test_anchored_inner_slash(self):
        ig = self._ig("assets/img\n")
        self.assertTrue(ig.matches("assets/img/logo.png"))
        self.assertFalse(ig.matches("other/assets/img/logo.png"))

    def test_negation_last_wins(self):
        ig = self._ig("*.log\n!important.log\n")
        self.assertTrue(ig.matches("a.log"))
        self.assertFalse(ig.matches("important.log"))
        ig = self._ig("!keep.txt\n*.txt\n")            # reversed order
        self.assertTrue(ig.matches("keep.txt"))

    def test_comments_blank_and_broken_rules(self):
        ig = self._ig("# comment\n\n   \n[*\nmain.py\n")
        self.assertTrue(ig.matches("main.py"))
        self.assertFalse(ig.matches("x.py"))

    def test_crlf_and_backslashes(self):
        ig = self._ig("*.log\r\n")
        self.assertTrue(ig.matches("x.log"))

    def test_rule_cap(self):
        ig = self._ig("\n".join(["f%d.txt" % i for i in range(500)]))
        self.assertLessEqual(len(ig.rules), npol.MAX_RULES)
        self.assertTrue(ig.matches("f0.txt"))

    def test_dir_named_like_ignore_file(self):
        p = self.ws / ".novaignore"
        p.mkdir()  # a DIRECTORY where the file should be -> treated as absent
        ig = npol.NovaIgnore.load(self.ws)
        self.assertEqual(ig.error, "")
        self.assertFalse(ig.matches("x.py"))


# ------------------------------------------------- command policy
class TestCommandPolicy(TempWS):
    def test_defaults(self):
        pol = npol.load_policy(self.ws)
        self.assertEqual(npol.check_command(pol, "python main.py"), "ask")
        self.assertEqual(pol["default"], "ask")

    def test_allow_and_deny(self):
        npol.save_policy(self.ws, {"default": "ask",
                                   "allow": ["python *", "pytest"],
                                   "deny": ["rm -rf *", "sudo"]})
        pol = npol.load_policy(self.ws)
        self.assertEqual(npol.check_command(pol, "python main.py"), "allow")
        self.assertEqual(npol.check_command(pol, "pytest -q tests/"), "allow")
        self.assertEqual(npol.check_command(pol, "rm -rf /"), "deny")
        self.assertEqual(npol.check_command(pol, "sudo apt install x"), "deny")
        # deny beats allow
        npol.save_policy(self.ws, {"default": "allow",
                                   "allow": ["git *"], "deny": ["git push*"]})
        pol = npol.load_policy(self.ws)
        self.assertEqual(npol.check_command(pol, "git push origin main"), "deny")
        self.assertEqual(npol.check_command(pol, "git status"), "allow")

    def test_prefix_semantics_of_plain_rule(self):
        pol = {"default": "ask", "allow": ["pytest"], "deny": []}
        self.assertEqual(npol.check_command(pol, "pytest"), "allow")
        self.assertEqual(npol.check_command(pol, "pytest -q"), "allow")
        self.assertEqual(npol.check_command(pol, "pytestfoo"), "ask")

    def test_case_insensitive(self):
        npol.save_policy(self.ws, {"default": "ask", "allow": [],
                                   "deny": ["RM -RF *"]})
        pol = npol.load_policy(self.ws)   # normalization lowercases patterns
        self.assertEqual(npol.check_command(pol, "rm -rf /tmp/x"), "deny")
        # even an UNNORMALIZED dict must behave the same (defense in depth)
        raw = {"default": "ask", "allow": [], "deny": ["RM -RF *"]}
        self.assertEqual(npol.check_command(raw, "rm -rf /tmp/x"), "deny")

    def test_corrupt_file_falls_back(self):
        d = self.ws / ".nova"
        d.mkdir(exist_ok=True)
        (d / "policy.json").write_text("{not json", encoding="utf-8")
        pol = npol.load_policy(self.ws)
        self.assertEqual(pol["default"], "ask")
        self.assertEqual(pol["allow"], [])

    def test_oversized_and_malformed_patterns_cleaned(self):
        npol.save_policy(self.ws, {"default": "banana",
                                   "allow": ["ok *" + "x" * 500, 42, "", "fine"],
                                   "deny": ["bad" * 100]})
        pol = npol.load_policy(self.ws)
        self.assertEqual(pol["default"], "ask")
        self.assertEqual(pol["allow"], ["fine"])
        self.assertEqual(pol["deny"], [])


# ------------------------------------------------- profile
class TestProfile(TempWS):
    def test_save_load_roundtrip(self):
        err = nproj.save_profile(self.ws, {"provider": "OPENAI", "model": "gpt-4o-mini",
                                           "mode": "code", "run_timeout": 300,
                                           "autotest": True})
        self.assertEqual(err, "")
        prof = nproj.load_profile(self.ws)
        self.assertEqual(prof["provider"], "openai")   # normalized lowercase
        self.assertEqual(prof["model"], "gpt-4o-mini")
        self.assertEqual(prof["run_timeout"], 300)
        self.assertTrue(prof["autotest"])

    def test_merges(self):
        nproj.save_profile(self.ws, {"provider": "groq"})
        nproj.save_profile(self.ws, {"model": "llama-3.3-70b-versatile"})
        prof = nproj.load_profile(self.ws)
        self.assertEqual(prof["provider"], "groq")
        self.assertEqual(prof["model"], "llama-3.3-70b-versatile")

    def test_clearing_fields(self):
        nproj.save_profile(self.ws, {"provider": "groq", "model": "x"})
        nproj.save_profile(self.ws, {"provider": None})
        self.assertNotIn("provider", nproj.load_profile(self.ws))

    def test_unknown_fields_and_bad_values_dropped(self):
        nproj.save_profile(self.ws, {"hax": "x", "run_timeout": 999999,
                                     "mode": "chaos", "model": "m" * 500})
        prof = nproj.load_profile(self.ws)
        self.assertNotIn("hax", prof)
        self.assertNotIn("run_timeout", prof)
        self.assertNotIn("mode", prof)
        self.assertNotIn("model", prof)

    def test_corrupt_file(self):
        p = nproj.profile_path(self.ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[[[", encoding="utf-8")
        self.assertEqual(nproj.load_profile(self.ws), {})

    def test_clear_profile(self):
        nproj.save_profile(self.ws, {"provider": "groq"})
        nproj.clear_profile(self.ws)
        self.assertEqual(nproj.load_profile(self.ws), {})


# ------------------------------------------------- memory
class TestMemory(TempWS):
    def test_roundtrip(self):
        hist = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        tr = [["user", "hello"], ["nova", "hi"]]
        nmem.save_memory(self.ws, hist, tr, extra={"model": "nova-code"})
        h2, t2, meta = nmem.load_memory(self.ws)
        self.assertEqual(h2, hist)
        self.assertEqual(t2, tr)
        self.assertEqual(meta.get("model"), "nova-code")

    def test_bounds_applied(self):
        hist = [{"role": "user", "content": "x" * 9000} for _ in range(100)]
        tr = [["user", "y" * 9000] for _ in range(500)]
        nmem.save_memory(self.ws, hist, tr)
        h2, t2, _ = nmem.load_memory(self.ws)
        self.assertLessEqual(len(h2), nmem.MAX_HISTORY)
        self.assertLessEqual(len(t2), nmem.MAX_TRANSCRIPT)
        for m in h2:
            self.assertLessEqual(len(m["content"]), nmem.MAX_ENTRY_CHARS)

    def test_file_size_cap(self):
        hist = [{"role": "user", "content": "z" * 8000} for _ in range(60)]
        nmem.save_memory(self.ws, hist, [])
        p = nmem.memory_path(self.ws)
        self.assertLessEqual(p.stat().st_size, nmem.MAX_FILE_BYTES + 100)

    def test_bad_rows_dropped(self):
        junk = [{"role": "hack", "content": "x"}, {"role": "user"},
                {"role": "user", "content": "good"},
                ["not", "a", "dict"]]
        nmem.save_memory(self.ws, junk, [["user", "ok-t"], ["weird", "no"]])
        h2, t2, _ = nmem.load_memory(self.ws)
        self.assertEqual(h2, [{"role": "user", "content": "good"}])
        self.assertEqual(t2, [["user", "ok-t"]])

    def test_corrupt_file_fresh_start(self):
        p = nmem.memory_path(self.ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("garbage{", encoding="utf-8")
        h, t, m = nmem.load_memory(self.ws)
        self.assertEqual((h, t, m), ([], [], {}))

    def test_clear(self):
        nmem.save_memory(self.ws, [{"role": "user", "content": "a"}], [])
        self.assertTrue(nmem.clear_memory(self.ws) == "")
        self.assertFalse(nmem.has_memory(self.ws))


# ------------------------------------------------- cost
class TestCost(TempWS):
    def test_ollama_free_and_known(self):
        pin, pout, known = ncost.price_of(self.ws, "ollama", "nova-code")
        self.assertEqual((pin, pout, known), (0.0, 0.0, True))

    def test_prefix_pricing(self):
        pin, pout, known = ncost.price_of(self.ws, "openai", "gpt-4o-mini-2024-07-18")
        self.assertEqual((pin, pout), (0.15, 0.60))
        self.assertTrue(known)
        _, _, known2 = ncost.price_of(self.ws, "openai", "brand-new-model")
        self.assertFalse(known2)

    def test_override_file(self):
        d = self.ws / ".nova"
        d.mkdir(exist_ok=True)
        (d / "pricing.json").write_text(json.dumps(
            {"my-model": [0.5, 1.5], "bad": [1, 2, 3], "neg": [-1, 2]}), encoding="utf-8")
        pin, pout, known = ncost.price_of(self.ws, "custom", "My-Model-v2")
        self.assertEqual((pin, pout, known), (0.5, 1.5, True))
        _, _, known2 = ncost.price_of(self.ws, "custom", "neg")
        self.assertFalse(known2)          # negative price rejected

    def test_record_and_report(self):
        ncost.record(self.ws, "openai", "gpt-4o-mini", 1000, 2000,
                     actual=False, dur_s=2.0)
        ncost.record(self.ws, "ollama", "nova-code", 500, 700, actual=True, dur_s=10.0)
        rep = ncost.report(self.ws)
        self.assertEqual(rep["today"]["turns"], 2)
        self.assertEqual(rep["total"]["ptok"], 1500)
        self.assertEqual(rep["total"]["ctok"], 2700)
        # openai: 1000/1e6*0.15 + 2000/1e6*0.6 = 0.00135
        self.assertAlmostEqual(rep["total"]["cost"], 0.00135, places=5)
        self.assertEqual(rep["total"]["estimated_rows"], 1)   # ollama was actual
        self.assertTrue(rep["total"]["tok_per_sec"] > 0)

    def test_archive_rollup(self):
        for _ in range(ncost.MAX_LOG_ENTRIES + 50):
            ncost.record(self.ws, "openai", "gpt-4o-mini", 100, 100, dur_s=1.0)
        data = ncost._load(self.ws)
        self.assertLessEqual(len(data["log"]), ncost.MAX_LOG_ENTRIES)
        self.assertTrue(data["archived"])
        rep = ncost.report(self.ws)
        self.assertEqual(rep["total"]["turns"], ncost.MAX_LOG_ENTRIES + 50)

    def test_estimate_turn(self):
        e = ncost.estimate_turn(self.ws, 3200, "openai", "gpt-4o-mini",
                                expected_out_chars=1600)
        self.assertEqual(e["prompt_tokens"], ncost.est_tokens("x" * 3200))
        self.assertEqual(e["out_tokens"], ncost.est_tokens("x" * 1600))
        pt, ct = e["prompt_tokens"], e["out_tokens"]
        self.assertAlmostEqual(e["cost_usd"], (pt * 0.15 + ct * 0.6) / 1e6, places=6)
        self.assertTrue(e["price_known"])
        self.assertIsNone(e["est_seconds"])    # no speed history yet

    def test_estimate_speed_learned(self):
        ncost.record(self.ws, "ollama", "nova-code", 1000, 1000, actual=True, dur_s=10.0)
        e = ncost.estimate_turn(self.ws, 3200, "ollama", "nova-code",
                                expected_out_chars=3200)
        self.assertIsNotNone(e["tok_per_sec"])
        self.assertIsNotNone(e["est_seconds"])

    def test_reset(self):
        ncost.record(self.ws, "openai", "gpt-4o-mini", 10, 10)
        ncost.reset(self.ws)
        rep = ncost.report(self.ws)
        self.assertEqual(rep["total"]["turns"], 0)

    def test_record_survives_junk_inputs(self):
        ncost.record(self.ws, "openai", "m", "abc", None, dur_s=-5)
        rep = ncost.report(self.ws)
        self.assertEqual(rep["total"]["ptok"], 0)


if __name__ == "__main__":
    unittest.main()
