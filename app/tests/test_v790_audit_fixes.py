#!/usr/bin/env python3
# =====================================================================
# v7.9.0 audit-fix pins - every finding from the 2-agent word-by-word
# audit, pinned by a test so it can NEVER come back quietly:
#   20-a #1  price_of longest-prefix (override no longer reprices
#            sibling models; empty key never matches)
#   20-a #2  council partner rounds record REAL usage
#   20-a #3  anthropic cache tokens fold into billed input-equivalents
#   20-a #4  /cost reset surfaces the error instead of lying
#   20-a #5  reset() refuses to unlink when the cross-process lock
#            degraded (no resurrection of pre-reset rows)
#   20-a #6  501 is a transient retry code (pinned)
#   20-b F1  set_route persists the CANONICAL provider/model
#   20-b F2  council partner spec canonizes the alias before recording
#   20-b F5  _absorb_usage keeps a valid field beside a junk sibling
#   20-b F6  the web clear-ledger click asks confirm() (js probe 20b)
# =====================================================================
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nova_cost
import nova_providers as providers
import nova_council


class _WSTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="nova_v79fix_")
        self.ws = Path(self._tmp).resolve()
        providers.load_config(self.ws)          # seed the provider state
        self.addCleanup(providers.load_config, None)
        self.addCleanup(self._clean)

    def _clean(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


    def _write_override(self, obj):
        d = Path(self.ws) / ".nova"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / nova_cost.PRICING_OVERRIDE_FILE, "w") as f:
            json.dump(obj, f)


class TestPriceOfLongestPrefix(_WSTestCase):
    """20-a #1: a pricing.json override must not reprice its siblings."""

    def test_override_prefix_no_longer_shadows_sibling(self):
        self._write_override({"gpt-4o": [3.00, 12.00]})
        self.assertEqual(nova_cost.price_of(self.ws, "openai", "gpt-4o"),
                         (3.00, 12.00, True))          # the override itself
        self.assertEqual(nova_cost.price_of(self.ws, "openai", "gpt-4o-mini"),
                         (0.15, 0.60, True))           # sibling untouched
        # ledger pricing follows
        self.assertEqual(
            nova_cost.cost_of(self.ws, "openai", "gpt-4o-mini", 1_000_000, 0),
            0.15)

    def test_empty_override_key_matches_nothing(self):
        self._write_override({"": [9.99, 9.99]})
        self.assertEqual(nova_cost.price_of(self.ws, "openai", "zzz-model"),
                         (0.0, 0.0, False))

    def test_longest_prefix_inside_the_base_table(self):
        self.assertEqual(nova_cost.price_of(self.ws, "openai", "gpt-4o"),
                         (2.50, 10.00, True))
        self.assertEqual(nova_cost.price_of(self.ws, "openai", "gpt-4o-mini"),
                         (0.15, 0.60, True))


class TestCouncilRealUsage(_WSTestCase):
    """20-a #2 + 20-b F2: council rounds are booked with REAL tokens
    under the CANONICAL provider name."""

    def test_collect_provider_passes_usage_into_stream_chunks(self):
        captured = {}

        class FakeProviders:
            @staticmethod
            def stream_chunks(cfg, model, messages, temperature,
                              timeout=1800, max_tokens=0, usage=None):
                captured["usage_arg"] = usage
                if usage is not None:
                    usage["prompt_tokens"] = 111
                    usage["completion_tokens"] = 22
                    usage["actual"] = True
                yield "سلام"

        text, usage = nova_council.collect_provider(
            {"kind": "openai"}, "m", [{"role": "user", "content": "x"}],
            0.2, 5, FakeProviders())
        self.assertEqual(text, "سلام")
        self.assertIs(captured["usage_arg"], usage)   # same dict flows back
        self.assertEqual((usage["prompt_tokens"],
                          usage["completion_tokens"],
                          usage["actual"]), (111, 22, True))

    def test_partner_spec_alias_canonizes(self):
        prov, model, label = nova_council.resolve_partner(
            "b.ai:gpt-4o", "ollama", "qwen2.5-coder", providers)
        self.assertEqual(prov, "bai")        # never the raw 'b.ai'
        self.assertEqual(model, "gpt-4o")
        self.assertIn("b.ai", label.lower())


class TestAnthropicCacheTokens(unittest.TestCase):
    """20-a #3: cache_creation/read are billed tokens - they must reach
    the ledger as input equivalents (1.25x write, 0.1x read)."""

    def test_message_start_folds_cache_tokens(self):
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        start = json.dumps({
            "type": "message_start",
            "message": {"usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 2000,
                "cache_read_input_tokens": 4000}}})
        delta = json.dumps({"type": "message_delta",
                            "usage": {"output_tokens": 300}})
        pieces = (providers._anthropic_parse(start, usage)
                  + providers._anthropic_parse(delta, usage))
        self.assertEqual(pieces, [])
        # 100 + 2000*1.25 + 4000*0.1 = 100 + 2500 + 400 = 3000
        self.assertEqual(usage["prompt_tokens"], 3000)
        self.assertEqual(usage["completion_tokens"], 300)
        self.assertTrue(usage["actual"])

    def test_cache_fields_absent_still_works(self):
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        providers._anthropic_parse(json.dumps({
            "type": "message_start",
            "message": {"usage": {"input_tokens": 50}}}), usage)
        self.assertEqual(usage["prompt_tokens"], 50)


class TestAbsorbUsagePerField(unittest.TestCase):
    """20-b F5: one junk field no longer discards its valid sibling."""

    def test_nan_prompt_keeps_valid_completion(self):
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        providers._absorb_usage(usage, float("nan"), 3)
        self.assertEqual(usage["completion_tokens"], 3)
        self.assertEqual(usage["prompt_tokens"], 0)
        self.assertTrue(usage["actual"])

    def test_inf_prompt_keeps_valid_completion(self):
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
        providers._absorb_usage(usage, float("inf"), 7)
        self.assertEqual(usage["completion_tokens"], 7)


class TestSetRouteCanonical(_WSTestCase):
    """20-b F1: the stored route is the canonical 'provider/model'."""

    def test_alias_target_stored_canonical(self):
        err = providers.set_route(self.ws, "talk", "b.ai/gpt-4o")
        self.assertEqual(err, "")
        routing = providers.routing()
        self.assertEqual(routing.get("talk"), "bai/gpt-4o")

    def test_bare_alias_stored_canonical(self):
        err = providers.set_route(self.ws, "coding", "b.ai")
        self.assertEqual(err, "")
        self.assertEqual(providers.routing().get("coding"), "bai")

    def test_resolve_route_still_resolves(self):
        providers.set_route(self.ws, "talk", "b.ai/gpt-4o")
        providers.set_key(self.ws, "bai", "sk-test-bai")
        cfg, model = providers.resolve_route("talk")
        self.assertEqual((cfg.get("name"), model), ("bai", "gpt-4o"))


class TestCostResetHonesty(_WSTestCase):
    """20-a #4 + #5: reset() is honest about failures and never
    resurrects pre-reset rows."""

    def test_reset_clears_rows(self):
        nova_cost.record(self.ws, "openai", "gpt-4o", 10, 5, actual=True)
        self.assertEqual(nova_cost.reset(self.ws), "")
        s = nova_cost.usage_summary(self.ws)
        self.assertEqual(s["total"]["requests"], 0)

    def test_reset_refuses_when_the_cross_process_lock_is_taken(self):
        import nova_atomic as natom
        nova_cost.record(self.ws, "openai", "gpt-4o", 10, 5, actual=True)
        with natom.file_lock(Path(self.ws) / ".nova" / "costs.lock",
                             timeout=0.5):
            err = nova_cost.reset(self.ws)
            self.assertTrue(err, "a taken lock must yield a busy error")
        # ...and a retry once the lock is free works
        self.assertEqual(nova_cost.reset(self.ws), "")
        self.assertEqual(nova_cost.usage_summary(self.ws)["total"]["requests"],
                         0)

    def test_reset_reports_unlink_errors(self):
        nova_cost.record(self.ws, "openai", "gpt-4o", 10, 5, actual=True)
        real_unlink = Path.unlink

        def boom(self, *a, **k):
            raise PermissionError(13, "nope")

        with mock.patch.object(Path, "unlink", boom):
            err = nova_cost.reset(self.ws)
        self.assertTrue(err)
        self.assertIn("nope", err)


class TestTransient501(unittest.TestCase):
    """20-a #6: the whole 5xx family is transient - 501 included."""

    def test_501_is_transient(self):
        import nova
        self.assertTrue(nova._transient_provider_error(
            providers.ProviderError("HTTP 501 - not implemented")))
        self.assertFalse(nova._transient_provider_error(
            providers.ProviderError("HTTP 401 - bad key")))


class TestCostCmdSurfacesResetError(_WSTestCase):
    """20-a #4: /cost reset must not print 'cleared' on failure."""

    def test_failed_reset_prints_the_error(self):
        import io
        import contextlib
        with mock.patch.object(nova_cost, "reset",
                               return_value="disk on fire"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                nova_cost_session = type("S", (), {"ws": self.ws})()
                import nova
                nova.cmd_cost(nova_cost_session, "reset")
        out = buf.getvalue()
        self.assertIn("could not clear", out)
        self.assertIn("disk on fire", out)
        self.assertNotIn("cleared", out)


class TestWebStateMigrationNote(_WSTestCase):
    """20-b F3: a v7.8 b.ai key stranded on the blackbox row gets a
    user-visible hint."""

    def test_note_when_blackbox_keyed_but_bai_not(self):
        import nova
        providers.set_key(self.ws, "blackbox", "sk-old-bai-key")
        sess = type("S", (), {"ws": self.ws})()
        st = nova.web_providers_state(sess)
        self.assertTrue(any("Blackbox" in n for n in st.get("notes", [])),
                        json.dumps(st.get("notes", []), ensure_ascii=False))

    def test_no_note_when_bai_also_keyed(self):
        import nova
        providers.set_key(self.ws, "blackbox", "sk-old")
        providers.set_key(self.ws, "bai", "sk-new")
        sess = type("S", (), {"ws": self.ws})()
        st = nova.web_providers_state(sess)
        self.assertEqual([n for n in st.get("notes", [])
                          if "Blackbox" in n], [])


class TestVersion(unittest.TestCase):
    def test_version(self):
        import nova
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
