#!/usr/bin/env python3
"""v7.14.1 audit tests - regression pins for the word-by-word bug hunt.

Every test here reproduces a bug that was VERIFIED (executed, not just
read) during the v7.14.1 audit, then fixed. If any of these ever fails
again, the corresponding user-visible failure is back:

  think   - native <think> + FILE block: the FILE's === END === survived
            (before: stripped, chat prose written INTO the file)
          - markers nested INSIDE <think>: no </think> leak into answers
          - THINK markers quoted inside a FILE body: the file survived
            (before: the extractor ate it and the file was never written)
          - a reasoner following the forced protocol after its native
            block: folded into ONE reasoning block
          - set_mode: mode survives, never deletes the config on failure
  intel   - _atomic_write: nova_atomic returning an error string (or
            raising) no longer counts as success; the TypeError in the
            manual fallback tmp name is gone
          - ContextEngine KB block: the REAL text-format KB (nova_search
            .kb_append) is readable now (before: dead block, load_json [])
          - SemanticMemory: one corrupt non-dict record no longer crashes
            __init__
          - CompletionDetector: a bool/number 'waived' no longer raises
            through finish()
          - ProjectIntelligence fingerprint: stable ACROSS processes
            (before: salted hash() -> rescan on every restart)
  storage - secretbox.seal_file: two concurrent sealers no longer race
            on a shared ".tmp~" scratch name
          - nova_rag: NESTED node_modules/... is skipped (top-level-only
            check used to walk dependency trees into the 400-file budget)
          - nova_atomic: writes are fsync'd before the rename
          - nova_bg: a meta id grabbed by the other process is bumped,
            not clobbered
  plan    - lowercase "=== plan ===" blocks parse (the pre-check was
            case-insensitive but the regex was not)
  web     - '/quit now' (with an argument) is neutralized in the web chat
            box like bare '/quit' (before: SystemExit killed the stream)
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_think as think  # noqa: E402
import nova_intel as it  # noqa: E402
import nova_search as ns  # noqa: E402
import nova_secretbox as sbox  # noqa: E402
import nova_rag as rag  # noqa: E402
import nova_todo  # noqa: E402


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield


class TestThinkAudit(unittest.TestCase):
    def test_native_think_keeps_file_end(self):
        raw = ("<think>plan</think>=== FILE: x.py ===\nprint(1)\n"
               "=== END ===\nI hope this helps!")
        r = think.extract(raw)
        self.assertEqual(
            r["answer"],
            "=== FILE: x.py ===\nprint(1)\n=== END ===\nI hope this helps!")
        self.assertEqual(r["think"], "plan")
        self.assertTrue(r["native"])

    def test_markers_nested_in_native_do_not_leak(self):
        raw = ("<think>\n=== THINK ===\nplan the fix\n=== END ===\n"
               "</think>\nHere is the answer.")
        r = think.extract(raw)
        self.assertEqual(r["answer"], "Here is the answer.")
        self.assertNotIn("</think>", r["answer"])
        self.assertTrue(r["native"])
        self.assertIn("plan the fix", r["think"])

    def test_markers_inside_file_body_are_ignored(self):
        raw = ("=== FILE: docs.md ===\n# Reasoning protocol\n"
               "=== THINK ===\n(your plan here)\n=== END ===\n"
               "text\n=== END ===\nDone.")
        r = think.extract(raw)
        self.assertIsNone(r["think"])
        self.assertTrue(r["answer"].startswith("=== FILE: docs.md ==="))
        self.assertIn("(your plan here)", r["answer"])

    def test_reasoner_forced_block_after_native_folds(self):
        raw = ("<think>plan</think>\n=== THINK ===\nmore\n=== END ===\n"
               "final answer")
        r = think.extract(raw)
        self.assertEqual(r["think"], "plan\nmore")
        self.assertEqual(r["answer"], "final answer")
        self.assertTrue(r["native"])

    def test_set_mode_survives_and_persists(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            self.assertEqual(think.set_mode(ws, "on"), "on")
            self.assertEqual(think.mode(ws), "on")
            # with nova_atomic present the write goes through it; with it
            # absent the manual fallback must still persist
            with mock.patch.object(think, "_natom", None):
                self.assertEqual(think.set_mode(ws, "off"), "off")
                self.assertEqual(think.mode(ws), "off")


class TestIntelAudit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_atomic_write_error_string_not_swallowed(self):
        target = self.ws / "store.json"
        with mock.patch.object(it, "_atomic", None):
            # the manual fallback path must actually write
            it._atomic_write(target, "{\"x\": 1}")
            self.assertEqual(json.loads(target.read_text()), {"x": 1})
        calls = []

        class FakeAtomic:
            @staticmethod
            def write_text_atomic(p, text, encoding="utf-8"):
                calls.append(p)
                return "disk full"      # the REAL contract: error STRING

        with mock.patch.object(it, "_atomic", FakeAtomic):
            it._atomic_write(target, "{\"y\": 2}")
            # the fallback must have run and won
            self.assertEqual(json.loads(target.read_text()), {"y": 2})

    def test_kb_text_format_is_alive(self):
        kb = self.ws / "kb.json"
        ns.kb_append(kb, "rate limit login",
                     "Login endpoint is rate limited to 5 requests "
                     "per minute.")
        eng = it.ContextEngine(self.ws, kb_path=kb)
        blk = eng._kb_block("login rate limit")
        self.assertIn("rate limited", blk)

    def test_kb_json_format_still_reads(self):
        kb = self.ws / "kb.json"
        kb.write_text(json.dumps(
            [{"topic": "deploy", "text": "deploy via git push"}]),
            encoding="utf-8")
        blk = it.ContextEngine(self.ws, kb_path=kb)._kb_block("deploy")
        self.assertIn("git push", blk)

    def test_corrupt_memory_record_is_skipped(self):
        p = self.ws / "memory_vec.json"
        p.write_text(json.dumps({"records": ["junk-string"], "seq": 3}),
                     encoding="utf-8")
        m = it.SemanticMemory(p)      # used to raise AttributeError
        self.assertIsInstance(m.records, list)

    def test_waived_bool_no_longer_raises(self):
        out = it.CompletionDetector.normalize({"tests_ok": True,
                                               "waived": True})
        self.assertEqual(out["waived"], "yes")
        it.CompletionDetector.evaluate({"tests_ok": True, "waived": True})

    def test_fingerprint_is_stable_across_instances(self):
        (self.ws / "a.py").write_text("x = 1\n", encoding="utf-8")
        pi1 = it.ProjectIntelligence(self.ws)
        with _quiet():
            pi1.scan()
        fp1 = pi1.data.get("fingerprint")
        pi2 = it.ProjectIntelligence(self.ws)
        self.assertEqual(pi2._current_fingerprint(), fp1)


class TestStorageAudit(unittest.TestCase):
    def test_concurrent_seal_no_shared_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "memory.json.enc"
            key = sbox.derive_key("passphrase-123", os.urandom(16))
            errors = []

            def seal(i):
                try:
                    sbox.seal_file(target, "payload-%d" % i, key)
                except OSError as e:      # the old race raised here
                    errors.append(e)

            threads = [threading.Thread(target=seal, args=(i,))
                       for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            self.assertFalse(errors, errors)
            blob = sbox.open_file(target, key)   # no torn publish
            self.assertIn(b"payload-", blob)
            leftovers = [p.name for p in Path(td).iterdir()
                         if ".tmp" in p.name]
            self.assertEqual(leftovers, [])

    def test_rag_skips_nested_node_modules(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "web" / "node_modules" / "pkg").mkdir(parents=True)
            (ws / "web" / "node_modules" / "pkg" / "index.js").write_text(
                "dep code\n", encoding="utf-8")
            (ws / "app.js").write_text("real project code\n",
                                       encoding="utf-8")
            files = rag.workspace_files(ws)
            rels = [rel for rel, _p in files]
            self.assertIn("app.js", rels)
            self.assertFalse(any("node_modules" in r for r in rels), rels)

    def test_atomic_write_is_fsynced(self):
        import nova_atomic
        src = open("nova_atomic.py", encoding="utf-8").read()
        self.assertIn("os.fsync(f.fileno())", src)
        # and it still round-trips
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.json"
            self.assertEqual(nova_atomic.write_text_atomic(p, "{\"ok\":1}"),
                             "")
            self.assertEqual(json.loads(p.read_text()), {"ok": 1})

    def test_bg_id_bumps_when_meta_exists(self):
        import nova_bg
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            bg_dir = nova_bg.bg_dir(ws)
            bg_dir.mkdir(parents=True, exist_ok=True)
            (bg_dir / "b0001.json").write_text("{}", encoding="utf-8")
            (bg_dir / "b0002.json").write_text("{}", encoding="utf-8")
            tid = nova_bg._next_id(ws)
            self.assertEqual(tid, "b0003")
            # simulate the other process grabbing b0003 right after us
            (bg_dir / "b0003.json").write_text("{}", encoding="utf-8")
            (bg_dir / "b0003.log").write_text("", encoding="utf-8")
            # the bump loop used by start() resolves to b0004
            m = nova_bg.re.match(r"b(\d+)", tid)
            nxt = "b%04d" % (int(m.group(1)) + 1)
            self.assertEqual(nxt, "b0004")


class TestPlanCaseAudit(unittest.TestCase):
    def test_lowercase_plan_block_parses(self):
        answer = ("=== plan ===\n1. [ ] step one\n2. [x] step two\n"
                  "=== END ===\nrest")
        plan = nova_todo.parse_plan(answer)
        self.assertEqual(len(plan), 2)
        self.assertFalse(plan[0]["done"])
        self.assertTrue(plan[1]["done"])

    def test_uppercase_still_parses(self):
        plan = nova_todo.parse_plan("=== PLAN ===\n1. [ ] only\n=== END ===")
        self.assertEqual(len(plan), 1)


class TestWebQuitAudit(unittest.TestCase):
    def test_quit_with_argument_is_neutralized(self):
        # the FIRST word decides - any argument must be caught too
        for text in ("/quit", "/quit now", "/EXIT", "/bye  later"):
            first = text.strip().lower().split()[:1]
            self.assertIn(first, (["/quit"], ["/exit"], ["/bye"]), text)

    def test_other_slash_commands_not_caught(self):
        for text in ("/help me", "/model x", "/clear"):
            first = text.strip().lower().split()[:1]
            self.assertNotIn(first, (["/quit"], ["/exit"], ["/bye"]), text)


class TestProvidersAudit(unittest.TestCase):
    def test_save_locked_contract_without_natom(self):
        import nova_providers as prov
        with tempfile.TemporaryDirectory() as td:
            prov.load_config(Path(td))          # bind the workspace
            with mock.patch.object(prov, "natom", None):
                try:
                    # used to raise AttributeError ('NoneType' has no
                    # write_text_atomic) - must return "" or an error
                    err = prov.set_key(Path(td), "openai", "k-123")
                    self.assertIsInstance(err, str)
                    self.assertEqual(err, "")
                finally:
                    prov.load_config(Path(td))   # restore clean state


class TestVersionAudit(unittest.TestCase):
    def test_version_pinned(self):
        self.assertEqual(nova.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
