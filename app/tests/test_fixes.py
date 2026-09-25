"""Regression tests for the v4.1 hardening pass (offline, no network).

Covers the fixes from the full audit:
  - sanitize_parts / safe_join: traversal, control chars, symlink escape
  - is_secret_path: credential files blocked from the model context
  - extract_run_hint: last 'Run:' OUTSIDE file blocks wins
  - find_model_action: standalone-line rule, first-in-text wins
  - parse_edits: malformed (8-arrow) hunks refused, well-formed kept
  - _attach: one attachment cap for every path + secret guard
  - build_messages: oversized user message is trimmed, not overflowed
  - providers: non-dict JSON / string errors -> clean ProviderError,
    network failures converted, NOVA_BASE_URL now custom-only
  - nova_search: truncated-gzip fallback runs, private hosts blocked,
    DDG link/snippet pairing stays aligned
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_providers as providers  # noqa: E402
import nova_search as ns  # noqa: E402


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


class TestSanitizeAndSafeJoin(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())

    def test_traversal_still_blocked(self):
        for bad in ("../x", "a/../../b", "..\\.\\x"):
            with self.assertRaises(ValueError):
                nova.safe_join(self.ws, bad)

    def test_drive_letter_is_stripped_not_escaped(self):
        # C:\Windows\x is re-based into the workspace (drive letters are
        # stripped by design) - it must NOT write to C:\Windows
        p = nova.safe_join(self.ws, "C:\\Windows\\x")
        self.assertTrue(str(p).startswith(str(self.ws)))

    def test_absolute_path_is_rebased_into_workspace(self):
        # documented design: an absolute path is re-based onto the workspace
        p = nova.safe_join(self.ws, "/etc/passwd")
        self.assertTrue(str(p).startswith(str(self.ws)))

    def test_control_characters_are_sanitized(self):
        # a NUL used to crash open() MID-APPLY, leaving a half-applied batch
        parts = nova.sanitize_parts("a\x00b/line\nbreak.txt")
        joined = "/".join(parts)
        self.assertNotIn("\x00", joined)
        self.assertNotIn("\n", joined)

    def test_symlink_escape_is_blocked(self):
        outside = Path(tempfile.mkdtemp()) / "secret.txt"
        outside.write_text("top secret")
        (self.ws / "link").symlink_to(outside.parent)
        with self.assertRaises(ValueError):
            nova.safe_join(self.ws, "link/secret.txt")

    def test_normal_path_still_works(self):
        p = nova.safe_join(self.ws, "css/style.css")
        self.assertTrue(str(p).startswith(str(self.ws)))


class TestSecretPaths(unittest.TestCase):
    def test_blocked(self):
        for rel in (".env", ".env.local", "creds/.env", ".git/config",
                    ".ssh/id_rsa", "keys/server.pem", "id_ed25519",
                    "vault/api.key", ".aws/credentials"):
            self.assertTrue(nova.is_secret_path(rel), rel)

    def test_allowed(self):
        for rel in ("main.py", "src/app.js", "css/style.css", "key.py",
                    "docs/keys.md", "web: Some Page", "web research: css grid"):
            self.assertFalse(nova.is_secret_path(rel), rel)

    def test_action_read_refuses_env_file(self):
        sess = mock.Mock()
        sess.ws = Path(tempfile.mkdtemp())
        (sess.ws / ".env").write_text("SECRET=top")
        out = nova._action_read(sess, ".env")
        self.assertIn("REFUSED", out)
        self.assertNotIn("SECRET", out)


class TestRunHintAndToolTokens(unittest.TestCase):
    def test_run_hint_ignores_file_blocks(self):
        answer = ("Here is the project:\n"
                  "=== FILE: Makefile ===\n"
                  "run: main.py\n\tpython main.py\n"
                  "=== END ===\n"
                  "Run: python3 main.py")
        self.assertEqual(nova.extract_run_hint(answer), "python3 main.py")

    def test_run_hint_takes_last_standalone(self):
        answer = "Run: wrong idea\n...actually:\nPreview: npx serve ."
        self.assertEqual(nova.extract_run_hint(answer), "npx serve .")

    def test_run_hint_none(self):
        self.assertIsNone(nova.extract_run_hint("no hint here"))

    def test_token_in_prose_is_ignored(self):
        self.assertIsNone(
            nova.find_model_action("You can use [READ: src/x.py] to inspect it."))

    def test_standalone_token_fires(self):
        found = nova.find_model_action("Let me look first.\n[READ: src/x.py]")
        self.assertIsNotNone(found)
        self.assertEqual(found[1], "src/x.py")

    def test_trailing_punctuation_is_tolerated(self):
        found = nova.find_model_action("[READ: main.py].")
        self.assertIsNotNone(found)

    def test_first_in_text_wins(self):
        answer = "x\n[READ: a.py]\nthen search:\n[SEARCH: q]"
        found = nova.find_model_action(answer)
        self.assertEqual(found[0]["name"], "READ")


class TestParseEdits(unittest.TestCase):
    def test_wellformed_hunks_parse(self):
        txt = ("=== EDIT: app.py ===\n"
               "<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE\n"
               "=== END ===")
        edits = nova.parse_edits(txt)
        self.assertEqual(edits, [("app.py", [("old line", "new line")])])

    def test_empty_replace_still_parses(self):
        txt = ("=== EDIT: app.py ===\n"
               "<<<<<<< SEARCH\nkill me\n=======\n\n>>>>>>> REPLACE\n"
               "=== END ===")
        edits = nova.parse_edits(txt)
        self.assertEqual(edits, [("app.py", [("kill me", "")])])

    def test_eight_arrow_hunk_is_refused(self):
        txt = ("=== EDIT: app.py ===\n"
               "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>>> REPLACE\n"
               "=== END ===")
        edits = nova.parse_edits(txt)
        self.assertEqual(edits, [("app.py", [])])

    def test_multiline_file_name_impossible(self):
        # the name group can no longer span newlines under re.DOTALL
        files, _ = nova.parse_files("=== FILE: foo\nbar.py ===\nx\n=== END ===")
        self.assertEqual(files, [])


class TestAttach(unittest.TestCase):
    def setUp(self):
        self.sess = mock.Mock()
        self.sess.ws = Path(tempfile.mkdtemp())
        self.sess.loads = []
        self.sess.ignore = None    # v5.0: no .novaignore rules in this test

    def test_cap_is_enforced(self):
        nova.MAX_ATTACHMENTS = 2
        try:
            for i in range(2):
                self.assertTrue(nova._attach(self.sess, f"f{i}.py", "x"))
            self.assertFalse(nova._attach(self.sess, "f9.py", "x"))
            self.assertEqual(len(self.sess.loads), 2)
        finally:
            nova.MAX_ATTACHMENTS = 8

    def test_secret_files_blocked(self):
        self.assertFalse(nova._attach(self.sess, ".env", "SECRET=x"))
        self.assertEqual(self.sess.loads, [])


class TestBuildMessagesTrim(unittest.TestCase):
    def test_oversized_user_message_is_trimmed(self):
        old_ctx = nova.NUM_CTX
        nova.NUM_CTX = 4096
        try:
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                huge = ("=== FILE: big.py ===\n" + "x" * 60_000 + "\n=== END ===")
                msgs = sess.build_messages(huge)
                sent = msgs[-1]["content"]
                self.assertLess(len(sent), len(huge),
                                "the oversized user message must be trimmed")
                self.assertTrue(any(m["role"] == "system" for m in msgs))
        finally:
            nova.NUM_CTX = old_ctx


class TestProviderParsers(unittest.TestCase):
    def test_openai_non_dict_payload_is_tolerated(self):
        self.assertEqual(providers._openai_parse('[1,2,3]'), [])
        self.assertEqual(providers._openai_parse('"just a string"'), [])

    def test_openai_string_error(self):
        with self.assertRaises(providers.ProviderError):
            providers._openai_parse('{"error": "boom"}')

    def test_anthropic_non_dict_and_string_error(self):
        self.assertEqual(providers._anthropic_parse('[1,2]'), [])
        with self.assertRaises(providers.ProviderError):
            providers._anthropic_parse('{"type": "error", "error": "boom"}')

    def test_gemini_non_dict_and_junk_candidates(self):
        self.assertEqual(providers._gemini_parse('[1,2]'), [])
        self.assertEqual(providers._gemini_parse(
            '{"candidates": ["junk", {"content": {"parts": [{"text": "hi"}]}}]}'),
            ["hi"])

    def test_network_errors_become_provider_error(self):
        cfg = {"kind": "openai", "base": "https://unit-test.invalid",
               "key": "k", "name": "openai"}
        gen = providers._openai_stream(cfg, "m", [{"role": "user", "content": "x"}], 0.4, 1)
        with self.assertRaises(providers.ProviderError):
            next(gen)

    def test_base_url_override_is_custom_only(self):
        old = os.environ.get("NOVA_BASE_URL")
        old_key = os.environ.get("OPENAI_API_KEY")
        try:
            os.environ["NOVA_BASE_URL"] = "http://elsewhere:1234/v1"
            os.environ["OPENAI_API_KEY"] = "sk-test"
            cfg = providers.resolve("openai")
            self.assertEqual(cfg["base"], "https://api.openai.com/v1",
                             "NOVA_BASE_URL must not hijack a fixed provider")
        finally:
            if old is None:
                os.environ.pop("NOVA_BASE_URL", None)
            else:
                os.environ["NOVA_BASE_URL"] = old
            if old_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_key


class TestSearchHardening(unittest.TestCase):
    def test_truncated_gzip_falls_back(self):
        data = gzip_compress(b"hello world nova test " * 1000)
        out = ns._gunzip(data[:-8])          # cut mid-stream -> EOFError path
        self.assertTrue(out.startswith(b"hello world"))

    def test_garbage_gzip_returns_raw(self):
        self.assertEqual(ns._gunzip(b"\x1f\x8b-not-really-gzip"), b"\x1f\x8b-not-really-gzip")

    def test_private_hosts_are_blocked(self):
        self.assertIsNone(ns.safe_url("http://127.0.0.1:11434/api"))
        self.assertIsNone(ns.safe_url("http://localhost/x"))
        self.assertIsNone(ns.safe_url("http://169.254.169.254/latest/meta-data"))
        self.assertIsNone(ns.safe_url("http://user:pw@example.com/"))

    @mock.patch.object(ns.socket, "getaddrinfo")
    def test_public_host_allowed(self, ga):
        ga.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        self.assertIsNotNone(ns.safe_url("https://example.com/doc"))

    @mock.patch.object(ns.socket, "getaddrinfo")
    def test_unresolvable_host_fails_closed(self, ga):
        ga.side_effect = OSError("no dns")
        self.assertIsNone(ns.safe_url("https://no-such-host.invalid/x"))

    def test_ddg_results_keep_their_own_snippets(self):
        html = ('<a class="result__a" href="https://a.example/1">One</a>'
                '<a class="result__snippet" href="#">snippet one</a>'
                '<a class="result__a" href="https://b.example/2">Two</a>'
                '<a class="result__snippet" href="#">snippet two</a>')
        out = ns._parse_ddg(html)
        self.assertEqual([r["snippet"] for r in out], ["snippet one", "snippet two"])

    def test_ddg_result_without_snippet_keeps_empty(self):
        html = ('<a class="result__a" href="https://a.example/1">One</a>'
                '<a class="result__a" href="https://b.example/2">Two</a>'
                '<a class="result__snippet" href="#">snippet two</a>')
        out = ns._parse_ddg(html)
        self.assertEqual(out[0]["snippet"], "")
        self.assertEqual(out[1]["snippet"], "snippet two")


def gzip_compress(data):
    import gzip as gz
    return gz.compress(data)


if __name__ == "__main__":
    unittest.main()
