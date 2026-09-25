"""Unit tests for nova.parse_args(). Pure function, zero I/O - safe to
run anywhere (no Ollama, no network)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402


class TestParseArgs(unittest.TestCase):
    def test_defaults(self):
        opts = nova.parse_args([])
        self.assertEqual(opts["workspace"], "")
        self.assertFalse(opts["web"])
        self.assertEqual(opts["host"], "127.0.0.1")
        self.assertEqual(opts["port"], 8765)
        self.assertEqual(opts["provider"], "")
        self.assertFalse(opts["help"])
        self.assertFalse(opts["version"])

    def test_positional_workspace(self):
        opts = nova.parse_args(["my-project"])
        self.assertEqual(opts["workspace"], "my-project")

    def test_web_flag(self):
        opts = nova.parse_args(["--web"])
        self.assertTrue(opts["web"])

    def test_host_and_port(self):
        opts = nova.parse_args(["--web", "--host", "0.0.0.0", "--port", "9999"])
        self.assertEqual(opts["host"], "0.0.0.0")
        self.assertEqual(opts["port"], 9999)

    def test_port_must_be_numeric(self):
        with self.assertRaises(ValueError):
            nova.parse_args(["--port", "abc"])

    def test_port_range(self):
        with self.assertRaises(ValueError):
            nova.parse_args(["--port", "0"])
        with self.assertRaises(ValueError):
            nova.parse_args(["--port", "70000"])

    def test_host_needs_value(self):
        with self.assertRaises(ValueError):
            nova.parse_args(["--host"])

    def test_empty_host_is_rejected(self):
        # '--host ""' used to bind 0.0.0.0 while auth treated it as loopback
        for bad in ("", "   "):
            with self.assertRaises(ValueError):
                nova.parse_args(["--web", "--host", bad])

    def test_workspace_flag(self):
        opts = nova.parse_args(["--workspace", "foo"])
        self.assertEqual(opts["workspace"], "foo")

    def test_workspace_given_twice_is_error(self):
        with self.assertRaises(ValueError):
            nova.parse_args(["--workspace", "foo", "bar"])

    def test_too_many_positional_args(self):
        with self.assertRaises(ValueError):
            nova.parse_args(["foo", "bar"])

    def test_unknown_option(self):
        with self.assertRaises(ValueError):
            nova.parse_args(["--nope"])

    def test_provider_flag(self):
        opts = nova.parse_args(["--provider", "openai"])
        self.assertEqual(opts["provider"], "openai")

    def test_help_and_version_flags(self):
        self.assertTrue(nova.parse_args(["-h"])["help"])
        self.assertTrue(nova.parse_args(["--help"])["help"])
        self.assertTrue(nova.parse_args(["-V"])["version"])
        self.assertTrue(nova.parse_args(["--version"])["version"])


if __name__ == "__main__":
    unittest.main()
