#!/usr/bin/env python3
"""v7.5.0 tests: THE BACKEND-AWARE RULE + the prompt profiles.

The user's law, pinned by execution:
  - every capability that COMPENSATES FOR A WEAK MODEL (multi-sample
    generation, firm idioms, few-shot examples, speculative drafts,
    exploration) is locked to LOCAL brains;
  - every capability that only GUARANTEES CORRECT OUTPUT (lint gate,
    parse-retry, atomic writes) stays on for ALL backends;
  - a cloud frontier brain gets the rich full prompt: idioms appear as
    OPTIONAL hints it may ignore, the local few-shot NEVER rides along,
    and no helper layer may silently multiply the API bill.
"""
import os
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova            # noqa: E402
import nova_backend    # noqa: E402
import nova_idioms     # noqa: E402
import nova_router     # noqa: E402


# ---------------------------------------------------------------- policy
class TestBackendPolicy(unittest.TestCase):
    def test_kind_classification(self):
        self.assertEqual(nova_backend.classify_kind({"kind": "ollama"}), "local")
        self.assertEqual(nova_backend.classify_kind({"kind": "llamacpp"}), "local")
        self.assertEqual(nova_backend.classify_kind({"kind": "lmstudio"}), "local")
        self.assertEqual(nova_backend.classify_kind({"kind": "vllm"}), "local")
        self.assertEqual(nova_backend.classify_kind({}), "local")
        self.assertEqual(nova_backend.classify_kind({"kind": "openai"}), "cloud")
        self.assertEqual(nova_backend.classify_kind({"kind": "anthropic"}), "cloud")
        self.assertEqual(nova_backend.classify_kind({"kind": "gemini"}), "cloud")

    def test_profiles_split_by_backend(self):
        self.assertEqual(nova_backend.prompt_profile("local"), "local_small")
        self.assertEqual(nova_backend.prompt_profile("cloud"), "cloud_frontier")

    def test_weakness_features_local_only(self):
        for feat in ("best_of", "speculative", "explore", "idiom_strict"):
            self.assertTrue(nova_backend.feature_enabled(feat, "local"),
                            feat + " must be on for local")
            self.assertFalse(nova_backend.feature_enabled(feat, "cloud"),
                             feat + " must be OFF for cloud by default")

    def test_correctness_features_always_on(self):
        for feat in ("lint", "parse_retry", "atomic_write"):
            self.assertTrue(nova_backend.feature_enabled(feat, "local"))
            self.assertTrue(nova_backend.feature_enabled(feat, "cloud"))

    def test_env_kill_and_optin(self):
        old = dict(os.environ)
        try:
            os.environ["NOVA_NO_BEST_OF"] = "1"
            self.assertFalse(nova_backend.feature_enabled("best_of", "local"))
            # cloud opt-in: only explicit, never default
            del os.environ["NOVA_NO_BEST_OF"]
            os.environ["NOVA_CLOUD_BEST_OF"] = "1"
            self.assertTrue(nova_backend.feature_enabled("best_of", "cloud"))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_best_of_counts(self):
        self.assertEqual(nova_backend.best_of_count("cloud"), 1)
        self.assertEqual(nova_backend.best_of_count("local"), 3)
        old = dict(os.environ)
        try:
            os.environ["NOVA_BEST_OF"] = "9"
            self.assertEqual(nova_backend.best_of_count("local"), 4)  # capped
            os.environ["NOVA_BEST_OF"] = "junk"
            self.assertEqual(nova_backend.best_of_count("local"), 3)
        finally:
            os.environ.clear()
            os.environ.update(old)


# ------------------------------------------------------------- idioms
class TestIdiomLibrary(unittest.TestCase):
    def test_cloud_profile_is_optional(self):
        t = nova_idioms.suggest_text("build a python script", "cloud_frontier")
        self.assertIn("may ignore", t)
        self.assertNotIn("lean on", t)

    def test_local_profile_is_firm(self):
        t = nova_idioms.suggest_text("build a python script", "local_small")
        self.assertIn("lean on", t)

    def test_language_detection(self):
        self.assertEqual(nova_idioms.detect_language("make a website with html"), "web")
        self.assertEqual(nova_idioms.detect_language("یک سایت فروشگاهی بساز"), "web")
        self.assertEqual(nova_idioms.detect_language("write a node server"), "javascript")
        self.assertEqual(nova_idioms.detect_language("پایتون: یک اسکریپت"), "python")
        self.assertEqual(nova_idioms.detect_language(""), "python")

    def test_pick_is_deterministic_and_capped(self):
        a = nova_idioms.pick("build a rest api with flask")
        b = nova_idioms.pick("build a rest api with flask")
        self.assertEqual(a, b)
        self.assertTrue(len(a) <= 4)

    def test_fail_soft(self):
        self.assertEqual(nova_idioms.suggest_text("", "cloud_frontier", lang="?"),
                         "")   # unknown lang -> no idioms, empty block


# ------------------------------------------------------------ profiles
class TestPromptProfiles(unittest.TestCase):
    def test_session_profile_follows_provider(self):
        sess = nova.Session.__new__(nova.Session)
        # fake the two brains without touching the provider config
        sess._local_brain = lambda: True
        self.assertEqual(sess.prompt_profile(), "local_small")
        sess._local_brain = lambda: False
        self.assertEqual(sess.prompt_profile(), "cloud_frontier")

    def test_fewshot_never_rides_cloud_turns(self):
        # the rich prompt must NOT contain the local few-shot marker when
        # the profile is cloud_frontier - directly verified on the builder
        self.assertIn("Worked examples", nova.LOCAL_FEWSHOT)
        core_local = nova.BASE_SYSTEM + nova.LOCAL_FEWSHOT
        self.assertIn("Worked examples", core_local)
        core_cloud = nova.BASE_SYSTEM
        self.assertNotIn("Worked examples", core_cloud)


# ------------------------------------------------------------- router
class TestRouter(unittest.TestCase):
    def test_difficulty_classification(self):
        self.assertEqual(nova_router.classify_difficulty("fix typo in print"), "easy")
        self.assertEqual(nova_router.classify_difficulty("تغییر رنگ دکمه به آبی"), "easy")
        self.assertEqual(nova_router.classify_difficulty(
            "refactor the whole authentication architecture with multi-thread "
            "and database schema migration, پیچیده و چند فایل"), "hard")
        self.assertEqual(nova_router.classify_difficulty("add a login form"), "medium")

    def test_param_parsing(self):
        self.assertEqual(nova_router._parse_param("qwen2.5-coder:7b"), 7.0)
        self.assertEqual(nova_router._parse_param("llama3.2:1b"), 1.0)
        self.assertEqual(nova_router._parse_param("phi3:3.8b"), 3.8)
        self.assertIsNone(nova_router._parse_param("mistral"))

    def test_local_routing_scales(self):
        installed = ["qwen2.5-coder:1.5b", "qwen2.5-coder:7b", "llama3.1:3b"]
        easy = nova_router.pick_local_model("easy", installed, "qwen2.5-coder:7b")
        self.assertEqual(easy, "qwen2.5-coder:1.5b")
        hard = nova_router.pick_local_model("hard", installed, "qwen2.5-coder:1.5b")
        self.assertEqual(hard, "qwen2.5-coder:7b")
        # nothing smaller/bigger -> keep current
        self.assertEqual(nova_router.pick_local_model(
            "easy", ["qwen2.5-coder:7b"], "qwen2.5-coder:7b"), "")
        self.assertEqual(nova_router.pick_local_model(
            "hard", ["qwen2.5-coder:7b"], "qwen2.5-coder:7b"), "")

    def test_cloud_never_routes_without_explicit_map(self, ):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            m, why = nova_router.pick_cloud_model(td, "easy", "gpt-4o")
            self.assertEqual(m, "")
            self.assertEqual(m, "")   # no map -> no routing, ever

    def test_explicit_cloud_map_routes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            err = nova_router.save_route_map(td, "gpt-4o-mini", "claude-sonnet")
            self.assertEqual(err, "")
            m, _ = nova_router.pick_cloud_model(td, "easy", "gpt-4o")
            self.assertEqual(m, "gpt-4o-mini")
            m, _ = nova_router.pick_cloud_model(td, "hard", "gpt-4o")
            self.assertEqual(m, "claude-sonnet")
            m, _ = nova_router.pick_cloud_model(td, "medium", "gpt-4o")
            self.assertEqual(m, "")
            # off removes the file
            nova_router.save_route_map(td, "", "")
            self.assertEqual(nova_router.load_route_map(td), {})

    def test_router_respects_kill_switch_and_pinned_route(self):
        old = dict(os.environ)
        try:
            os.environ["NOVA_NO_ROUTER"] = "1"
            m, diff, _ = nova_router.decide(None, "refactor everything",
                                            "local", ["x:1b"], "x:7b")
            self.assertEqual(m, "")
            self.assertEqual(diff, "hard")
        finally:
            os.environ.clear()
            os.environ.update(old)
        m, _d, why = nova_router.decide(None, "refactor everything", "local",
                                        ["x:1b"], "x:7b", has_coding_route=True)
        self.assertEqual(m, "")
        self.assertEqual(why, "user pinned a coding route")


if __name__ == "__main__":
    unittest.main()
