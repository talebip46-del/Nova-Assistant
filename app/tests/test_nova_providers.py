"""Unit tests for nova_providers.py. Everything here is pure / offline -
no socket is ever opened (streaming itself needs a real server and is
out of scope for an offline suite)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_providers as providers  # noqa: E402


class TestRegistry(unittest.TestCase):
    def test_ollama_is_first_in_names(self):
        self.assertEqual(providers.names()[0], "ollama")

    def test_every_provider_has_required_fields(self):
        for name, cfg in providers.PROVIDERS.items():
            for field in ("kind", "base", "model", "label"):
                self.assertIn(field, cfg, f"{name} missing {field}")


class TestResolve(unittest.TestCase):
    def setUp(self):
        # isolate from any real environment / prior test's global state
        self._env_patch = mock.patch.dict("os.environ", {}, clear=True)
        self._env_patch.start()
        providers._ACTIVE["name"] = None
        providers._MODEL_OVERRIDES.clear()

    def tearDown(self):
        self._env_patch.stop()
        providers._ACTIVE["name"] = None
        providers._MODEL_OVERRIDES.clear()

    def test_default_is_ollama_needs_no_key(self):
        cfg = providers.resolve()
        self.assertEqual(cfg["name"], "ollama")
        self.assertEqual(cfg["key"], "")

    def test_unknown_provider_raises(self):
        with self.assertRaises(providers.ProviderError):
            providers.resolve("not-a-real-provider")

    def test_cloud_provider_without_key_raises(self):
        with self.assertRaises(providers.ProviderError):
            providers.resolve("openai")

    def test_cloud_provider_with_key_resolves(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            cfg = providers.resolve("openai")
            self.assertEqual(cfg["key"], "sk-test")
            self.assertEqual(cfg["kind"], "openai")

    def test_custom_provider_needs_base_url(self):
        with self.assertRaises(providers.ProviderError):
            providers.resolve("custom")

    def test_custom_provider_key_is_optional(self):
        with mock.patch.dict("os.environ", {"NOVA_BASE_URL": "http://localhost:1234/v1",
                                             "NOVA_MODEL": "qwen2.5-coder-7b"}):
            cfg = providers.resolve("custom")
            self.assertEqual(cfg["base"], "http://localhost:1234/v1")
            self.assertTrue(cfg["key_optional"])

    def test_env_overrides_model_globally_base_only_custom(self):
        # v4.1: NOVA_MODEL still overrides every provider, but NOVA_BASE_URL
        # is now restricted to 'custom' - on a fixed provider it would have
        # silently redirected that provider's traffic (and its key!) elsewhere
        with mock.patch.dict("os.environ", {"NOVA_BASE_URL": "http://x/v1",
                                             "NOVA_MODEL": "foo"}):
            cfg = providers.resolve("ollama")
            self.assertEqual(cfg["base"], "http://localhost:11434",
                             "NOVA_BASE_URL must not hijack a fixed provider")
            self.assertEqual(cfg["model"], "foo")


class TestSetProvider(unittest.TestCase):
    def setUp(self):
        self._env_patch = mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True)
        self._env_patch.start()
        providers._ACTIVE["name"] = None
        providers._MODEL_OVERRIDES.clear()

    def tearDown(self):
        self._env_patch.stop()
        providers._ACTIVE["name"] = None
        providers._MODEL_OVERRIDES.clear()

    def test_switch_and_current(self):
        providers.set_provider("openai")
        self.assertEqual(providers.current()["name"], "openai")
        self.assertEqual(providers.current_name(), "openai")

    def test_switch_with_model_override(self):
        cfg = providers.set_provider("openai", "gpt-4o")
        self.assertEqual(cfg["model"], "gpt-4o")
        self.assertEqual(providers.default_model(providers.current()), "gpt-4o")

    def test_failed_switch_keeps_previous_provider(self):
        providers.set_provider("openai")
        with self.assertRaises(providers.ProviderError):
            providers.set_provider("does-not-exist")
        self.assertEqual(providers.current_name(), "openai")


class TestSseParsing(unittest.TestCase):
    def test_yields_data_payloads_only(self):
        lines = [
            b": OPENROUTER PROCESSING\n",
            b"\n",
            b"data: {\"a\":1}\n",
            b"not-sse-noise\n",
            b"data: [DONE]\n",
        ]
        out = list(providers._sse_data_lines(lines))
        self.assertEqual(out, ['{"a":1}', "[DONE]"])


class TestHttpMessage(unittest.TestCase):
    def test_plain_text_detail(self):
        class FakeErr:
            code = 500

            def read(self):
                return b"boom"

        msg = providers._http_message(FakeErr())
        self.assertIn("HTTP 500", msg)
        self.assertIn("boom", msg)

    def test_auth_hint_on_401(self):
        class FakeErr:
            code = 401

            def read(self):
                return b""

        msg = providers._http_message(FakeErr())
        self.assertIn("API key", msg)


if __name__ == "__main__":
    unittest.main()
