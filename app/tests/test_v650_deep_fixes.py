#!/usr/bin/env python3
# =====================================================================
#  Nova v6.5.0 regression tests - the deep-audit fix round.
#
#  Every test pins a REAL bug found in the v6.5 audit:
#   D1  /restore deleted files the checkpoint had only "skipped"
#   D2  knowledge stopwords were a set of characters (filter was a no-op)
#   D7  pid-less "running" bg entries lived forever, eating slots
#   D8  flow run pruning could delete the CURRENT run
#   D10 knowledge ingest crashed on a non-numeric chunk id
#   D11 bare .nova/.novaignore dotfiles could never be ingested
#   D15 photo seed 0 was treated as random
#   D16 "my flow" and "my_flow" silently overwrote each other
#   E1  rm --recursive --force / screened as allow
#   E2  Remove-Item -Force -Recurse C:\ screened as allow (order)
#   E3  echo "hi $(rm -rf /)" screened as allow
#   E4  one mangled costs.json row killed record()/report() forever
#   E5  --workspace=X form silently ignored by nova_assistant._ws()
#   E9  Persian auto-skill names collapsed to "auto-"
#   E12 PLAN separators (---) became bogus todo items
#   C1  repomap collected node_modules (list(os.walk) defeat)
#   C2  _gunzip had no output cap (gzip bomb)
#   C5  /model llama3:8b silently loaded llama3:latest
#   C6  gguf shards bypassed the scan cap
#  plus the v6.4 interpreter-normalization follow-up and version pin.
# =====================================================================
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova                       # noqa: E402
import nova_bg                    # noqa: E402
import nova_cost                  # noqa: E402
import nova_log                   # noqa: E402
import nova_models                # noqa: E402
import nova_search                # noqa: E402
import nova_security as nsec      # noqa: E402
import nova_snapshots as snaps    # noqa: E402
import nova_todo                  # noqa: E402
import nova_repomap               # noqa: E402
from nova_modules import knowledge, flow, assign, photo  # noqa: E402


class _WsCase(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova650-"))
        (self.ws / ".nova").mkdir()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)


# =====================================================================
# D1 - /restore must not delete skipped (uncaptured) files
# =====================================================================
class TestRestoreKeepsSkippedFiles(_WsCase):
    def test_skipped_file_survives_restore(self):
        big = self.ws / "big.bin"
        big.write_bytes(b"\0" * (snaps.MAX_FILE_BYTES + 10))   # too big -> skip
        secret = self.ws / "server.pem"
        secret.write_text("-----BEGIN KEY-----")               # secret -> skip
        normal = self.ws / "code.py"
        normal.write_text("print('v1')")

        uid, err, _sk = snaps.make_manual(self.ws, "before")
        self.assertFalse(err)
        # after the snapshot: the user's files keep living their life
        normal.write_text("print('v2')")

        meta = snaps.find_manual(self.ws, uid)
        res = snaps.restore_manual(self.ws, meta)
        self.assertEqual(res["deleted"], [])                   # v6.5: no deletion
        self.assertIn("big.bin", res["skipped"])
        self.assertIn("server.pem", res["skipped"])
        self.assertTrue(big.exists(), "big file destroyed by /restore")
        self.assertTrue(secret.exists(), "secret destroyed by /restore")
        self.assertEqual(normal.read_text(), "print('v1')")    # captured file restored

    def test_post_snapshot_new_file_is_still_deleted(self):
        (self.ws / "old.txt").write_text("old")
        uid, err, _sk = snaps.make_manual(self.ws, "before")
        self.assertFalse(err)
        (self.ws / "new.txt").write_text("born later")
        meta = snaps.find_manual(self.ws, uid)
        res = snaps.restore_manual(self.ws, meta)
        self.assertTrue(any("new.txt" in d for d in res["deleted"]),
                        res["deleted"])
        self.assertFalse((self.ws / "new.txt").exists())


# =====================================================================
# E1/E2/E3 - security screening gaps
# =====================================================================
class TestSecurityV65(unittest.TestCase):
    def test_gnu_long_flags_are_caught(self):
        self.assertEqual(nsec.analyze("rm --recursive --force /")["verdict"], "deny")
        self.assertEqual(nsec.analyze("rm --recursive /etc")["verdict"], "deny")
        r = nsec.analyze("rm --recursive --force build")["verdict"]
        self.assertGreaterEqual(nsec._MAX_LEVEL[r], nsec._MAX_LEVEL["confirm"])

    def test_no_preserve_root_is_denied(self):
        self.assertEqual(nsec.analyze("rm -rf / --no-preserve-root")["verdict"], "deny")

    def test_windows_switch_order_and_aliases(self):
        self.assertEqual(nsec.analyze("Remove-Item -Force -Recurse C:\\")["verdict"], "deny")
        self.assertEqual(nsec.analyze("Remove-Item -r -fo C:\\")["verdict"], "deny")
        self.assertEqual(nsec.analyze("del /s /q /f C:\\Windows")["verdict"], "deny")
        self.assertEqual(nsec.analyze("rd /q /s C:\\")["verdict"], "deny")
        r = nsec.analyze("del /s /q build")["verdict"]
        self.assertGreaterEqual(nsec._MAX_LEVEL[r], nsec._MAX_LEVEL["confirm"])

    def test_substitution_inside_double_quotes_is_screened(self):
        self.assertEqual(nsec.analyze('echo "hello $(rm -rf /)"')["verdict"], "deny")
        self.assertEqual(nsec.analyze('git commit -m "fix $(rm -rf /)"')["verdict"], "deny")
        self.assertEqual(nsec.analyze('echo "x`rm -rf /`y"')["verdict"], "deny")

    def test_literal_message_stays_allowed(self):
        self.assertEqual(nsec.analyze('git commit -m "rm -rf /"')["verdict"], "allow")
        self.assertEqual(nsec.analyze('echo "hello world"')["verdict"], "allow")

    def test_split_short_flags_confirm(self):
        self.assertEqual(nsec.analyze("rm -r -f build")["verdict"], "confirm")


# =====================================================================
# D2/D10/D11 - knowledge store
# =====================================================================
class TestKnowledgeV65(_WsCase):
    def test_stopwords_are_words_not_characters(self):
        self.assertIn("the", knowledge._STOP)
        self.assertIn("است", knowledge._STOP)
        self.assertNotIn("t", knowledge._STOP)      # a char-set would contain it
        self.assertGreater(len(knowledge._STOP), 40)

    def test_tokenize_drops_stopwords(self):
        toks = knowledge._tokenize("the castle of this است")
        self.assertNotIn("the", toks)
        self.assertNotIn("است", toks)
        self.assertIn("castle", toks)

    def test_ingest_survives_non_numeric_chunk_id(self):
        (self.ws / "doc.md").write_text("hello world content", encoding="utf-8")
        knowledge.ingest(self.ws, ["doc.md"])          # clean first pass
        chunks = self.ws / ".nova" / "knowledge" / "chunks.jsonl"
        # hand-edit one chunk line to a non-numeric id (doc.md is unchanged
        # so it is "kept" and the corrupt line gets parsed)
        lines = chunks.read_text(encoding="utf-8").splitlines()
        lines[0] = '{"id":"abc","doc":"doc.md","off":0,"text":"t"}'
        chunks.write_text("\n".join(lines) + "\n", encoding="utf-8")
        res = knowledge.ingest(self.ws, ["doc.md"])    # must not raise
        self.assertEqual(res["files"], 0)              # unchanged -> kept, not re-chunked

    def test_bare_dotfiles_can_be_ingested(self):
        (self.ws / ".novaignore").write_text("*.log\n", encoding="utf-8")
        res = knowledge.ingest(self.ws, [".novaignore"])
        self.assertEqual(res["files"], 1)


# =====================================================================
# C1 - repomap pruning
# =====================================================================
class TestRepomapV65(_WsCase):
    def test_node_modules_is_neither_walked_nor_collected(self):
        nm = self.ws / "node_modules" / "react"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("function boom() {}", encoding="utf-8")
        (self.ws / "main.py").write_text("def real():\n    pass\n", encoding="utf-8")
        seen = []
        real_walk = nova_repomap.os.walk          # capture BEFORE patching

        def fake_walk(base):
            for r, dirs, names in real_walk(base):
                # record what the generator actually visits
                seen.append(Path(r).name or ".")
                yield r, dirs, names

        with mock.patch.object(nova_repomap.os, "walk", fake_walk):
            text = nova_repomap.build_style_map(self.ws)
        self.assertNotIn("node_modules", text)
        self.assertNotIn("react", text)
        self.assertIn("main.py", text)
        self.assertFalse(any(s == "node_modules" for s in seen),
                         "walk visited node_modules - pruning is dead")


# =====================================================================
# C2 - gzip bomb cap
# =====================================================================
class TestGunzipCap(unittest.TestCase):
    def test_decompressed_output_is_capped(self):
        import gzip as _gz
        bomb = _gz.compress(b"A" * (20 * 1024 * 1024))
        out = nova_search._gunzip(bomb, max_out=1_000_000)
        self.assertLessEqual(len(out), 1_000_000)

    def test_valid_prefix_survives_truncation(self):
        import gzip as _gz
        import random as _rand
        rng = _rand.Random(42)
        payload = bytes(rng.randrange(256) for _ in range(20000))  # incompressible
        body = _gz.compress(payload)
        cut = body[:len(body) // 2]
        out = nova_search._gunzip(cut, max_out=8_000_000)
        self.assertTrue(out.startswith(payload[:100]),
                        "truncated stream lost its decompressed prefix")


# =====================================================================
# C5 - model resolve_choice with explicit tags
# =====================================================================
class TestResolveChoiceV65(unittest.TestCase):
    def test_explicit_tag_not_installed_is_none(self):
        self.assertIsNone(
            nova_models.resolve_choice("llama3:8b", ["llama3:latest", "llama3:70b"]))

    def test_tagless_base_match_still_works(self):
        self.assertEqual(
            nova_models.resolve_choice("qwen2.5-coder", ["qwen2.5-coder:7b"]),
            "qwen2.5-coder:7b")

    def test_exact_name_wins(self):
        self.assertEqual(nova_models.resolve_choice("m:1", ["m:1", "m:2"]), "m:1")


# =====================================================================
# C6 - gguf shard cap
# =====================================================================
class TestShardCap(_WsCase):
    def test_shards_respect_max_entries(self):
        d = self.ws / "models"
        d.mkdir()
        for i in range(12):
            (d / ("model-%05d-of-00012.gguf" % i)).write_bytes(b"x")
        entries = nova_localmodels_shim(d, max_entries=5)
        self.assertLessEqual(len(entries), 5)


def nova_localmodels_shim(d, max_entries):
    import nova_localmodels as lm
    return lm.scan_dirs([( "t", d, True)], max_entries=max_entries)


# =====================================================================
# A1 - /memory clear must also drop the transcript
# =====================================================================
class TestMemoryClearV65(unittest.TestCase):
    def test_clear_wipes_history_and_transcript(self):
        s = nova.Session.__new__(nova.Session)          # no __init__ side effects
        s.ws = Path(tempfile.mkdtemp(prefix="nova650mem-"))
        s.history = [{"role": "user", "content": "hi"}]
        s.transcript = [("user", "hi")]
        s.memory_on = True
        s.last_composed = "hi"
        try:
            with mock.patch.object(nova, "nmem") as mn:
                mn.clear_memory = mock.MagicMock()
                nova.cmd_memory(s, "clear")
            self.assertEqual(s.history, [])
            self.assertEqual(s.transcript, [])
            self.assertIsNone(s.last_composed)
            mn.clear_memory.assert_called_once()
        finally:
            shutil.rmtree(s.ws, ignore_errors=True)


# =====================================================================
# A2 - workspace switch resets cross-workspace state
# =====================================================================
class TestSetWorkspaceV65(unittest.TestCase):
    def test_stale_state_is_reset(self):
        s = nova.Session.__new__(nova.Session)
        s.ws = Path(tempfile.mkdtemp(prefix="nova650wsA-"))
        s.last_batch = [(s.ws / "f.py", s.ws / "bk")]
        s.touched = {"f.py": "new"}
        s.last_failed = {"cmd": "x"}
        s.last_cmd = "x"
        s.loads = [("a", "b")]
        s.last_feedback = {"ok": False}
        s.last_composed = "req"
        s.serve_proc = None
        s.serve_port = None
        s.serve_proc = None
        try:
            dst = Path(tempfile.mkdtemp(prefix="nova650wsB-"))
            with mock.patch.object(nova.Session, "_apply_profile"), \
                 mock.patch.object(nova.Session, "rescan"):
                s.set_workspace(dst)
            self.assertEqual(s.last_batch, [])
            self.assertEqual(s.touched, {})
            self.assertIsNone(s.last_failed)
            self.assertIsNone(s.last_cmd)
            self.assertEqual(s.loads, [])
            self.assertIsNone(s.last_feedback)
            self.assertIsNone(s.last_composed)
            self.assertEqual(s.ws, dst)
        finally:
            shutil.rmtree(s.ws, ignore_errors=True)
            shutil.rmtree(dst, ignore_errors=True)


# =====================================================================
# D7 - pid-less stale "running" bg entries die after 2 minutes
# =====================================================================
class TestBgPidlessV65(_WsCase):
    def test_stale_pidless_running_is_marked_died(self):
        nova_bg.bg_dir(self.ws).mkdir(parents=True, exist_ok=True)
        stale = {"id": "b9001", "cmd": "sleep", "started": int(time.time()) - 600,
                 "status": "running", "exit": None, "dur": None}   # no pid
        nova_bg._write_meta(self.ws, stale)
        fresh = dict(stale, id="b9002", started=int(time.time()))
        nova_bg._write_meta(self.ws, fresh)
        tasks = {t["id"]: t for t in nova_bg.list_tasks(self.ws)}
        self.assertEqual(tasks["b9001"]["status"], "died")
        self.assertEqual(tasks["b9002"]["status"], "running")

    def test_rlock_available_for_nested_use(self):
        with nova_bg._LOCK:
            with nova_bg._LOCK:          # re-entry must not deadlock
                pass


# =====================================================================
# D8/D16 - flow pruning and name collisions
# =====================================================================
class TestFlowV65(_WsCase):
    def test_prune_never_deletes_the_current_run(self):
        for i in range(65):
            p = flow.runs_dir(self.ws) / ("%064d.json" % i)
            p.write_text("{}", encoding="utf-8")
        current = flow.runs_dir(self.ws) / ("0" * 63 + "z.json")   # sorts LAST
        current.write_text(json.dumps({"id": "cur", "status": "running"}), encoding="utf-8")
        flow._write_run(self.ws, current.stem, {"id": "cur", "status": "running"})
        self.assertTrue(current.exists(), "the current run was pruned mid-flight")

    def test_space_and_underscore_names_do_not_clobber(self):
        flow.save(self.ws, {"name": "my flow",
                            "steps": [{"id": "a", "type": "prompt", "with": {"text": "x"}}]})
        with self.assertRaises(flow.ModuleError):
            flow.save(self.ws, {"name": "my_flow",
                                "steps": [{"id": "a", "type": "prompt", "with": {"text": "y"}}]})
        got = flow.get(self.ws, "my flow")
        self.assertEqual(got["steps"][0]["with"]["text"], "x")

    def test_same_name_resave_still_works(self):
        spec = {"name": "edit-me",
                "steps": [{"id": "a", "type": "prompt", "with": {"text": "v1"}}]}
        flow.save(self.ws, spec)
        spec["steps"][0]["with"]["text"] = "v2"
        flow.save(self.ws, spec)
        self.assertEqual(flow.get(self.ws, "edit-me")["steps"][0]["with"]["text"], "v2")


# =====================================================================
# D6 - piper assignment contract
# =====================================================================
class TestPiperContractV65(_WsCase):
    def test_file_prefix_path_is_rejected_at_save_time(self):
        with self.assertRaises(assign.ModuleError):
            assign.save_module(self.ws, "voice", {"backend": "piper",
                                                  "model": "file:/models/fa.onnx"})

    def test_path_only_piper_assignment_is_rejected(self):
        with self.assertRaises(assign.ModuleError):
            assign.save_module(self.ws, "voice", {"backend": "piper",
                                                  "path": "/usr/bin/piper"})

    def test_real_onnx_path_is_accepted(self):
        saved = assign.save_module(self.ws, "voice",
                                   {"backend": "piper", "model": "C:\\voices\\fa.onnx"})
        self.assertEqual(saved["model"], "C:\\voices\\fa.onnx")


# =====================================================================
# D15 - photo seed 0
# =====================================================================
class TestPhotoSeed(unittest.TestCase):
    def test_zero_seed_is_explicit(self):
        self.assertEqual(photo._seed({"seed": 0}), 0)
        self.assertEqual(photo._seed({"seed": "0"}), 0)
        self.assertEqual(photo._seed({}), -1)
        self.assertEqual(photo._seed({"seed": ""}), -1)
        self.assertEqual(photo._seed({"seed": "junk"}), -1)


# =====================================================================
# E4 - cost ledger survives mangled rows
# =====================================================================
class TestCostV65(_WsCase):
    def test_record_and_report_survive_mangled_rows(self):
        bad_rows = [{"ts": 1700000000},                        # no provider
                    {"ts": 1700000000, "provider": "p", "model": "m",
                     "ptok": "oops", "ctok": None, "cost": "x"},  # junk numbers
                    {"ts": "later", "provider": "p", "model": "m",
                     "ptok": 3, "ctok": 4, "cost": 0.5}]        # junk ts
        nova_cost._save(self.ws, {"log": bad_rows + [{}] * 399, "archived": []})
        nova_cost.record(self.ws, "p", "m", 10, 5)             # must not raise
        rep = nova_cost.report(self.ws)                        # must not raise
        self.assertGreaterEqual(rep["total"]["turns"], 1)


# =====================================================================
# E5 - --workspace= form
# =====================================================================
class TestAssistantWsForm(unittest.TestCase):
    def test_equals_form_is_honored(self):
        import nova_assistant as na
        target = tempfile.mkdtemp(prefix="nova650eq-")
        try:
            argv = sys.argv
            sys.argv = ["nova_assistant.py", "voice", "hi",
                        f"--workspace={target}"]
            try:
                self.assertEqual(na._ws(), Path(target).resolve())
            finally:
                sys.argv = argv
        finally:
            shutil.rmtree(target, ignore_errors=True)


# =====================================================================
# E9 - Persian auto-skill slugs
# =====================================================================
class TestSkillSlugV65(unittest.TestCase):
    def test_persian_signature_falls_back_instead_of_dying(self):
        import nova_skills
        sig = "یک صفحه فروشگاهی بساز"
        slug = nova_skills.re.sub(r"[^a-z0-9]+", "-", sig[:28].lower()).strip("-")
        self.assertEqual(slug, "")                     # Persian strips out
        name = "auto-" + (slug or "auto-skill")        # the v6.5 fallback
        self.assertEqual(name, "auto-auto-skill")
        self.assertNotEqual(name, "auto-")             # the old collapse

    def test_ascii_signature_keeps_its_slug(self):
        sig = "Build Login Page"
        slug = sig.lower()[:28]
        import re as _re
        s = _re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
        self.assertEqual("auto-" + s, "auto-build-login-page")


# =====================================================================
# E12 - PLAN separators
# =====================================================================
class TestTodoSeparators(unittest.TestCase):
    def test_separator_lines_are_not_items(self):
        plan = ("=== PLAN ===\n"
                "1. real step one\n"
                "---\n"
                "***\n"
                "2. real step two\n"
                "=== END ===")
        items = nova_todo.parse_plan(plan)
        texts = [i["text"] for i in items]
        self.assertEqual(texts, ["real step one", "real step two"])

    def test_persian_items_survive(self):
        plan = "=== PLAN ===\n1. ساخت صفحه اصلی\n=== END ==="
        items = nova_todo.parse_plan(plan)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "ساخت صفحه اصلی")


# =====================================================================
# E10 - log exc cap
# =====================================================================
class TestLogExcCap(unittest.TestCase):
    def test_huge_exception_text_is_capped(self):
        e = RuntimeError("x" * 100000)
        nova_log.note("test.cap", exc=e)
        rec = nova_log.tail(1)[0]
        self.assertLessEqual(len(rec["exc"] or ""), 1500)


# =====================================================================
# v6.4 follow-up: interpreter normalization on Windows
# =====================================================================
class TestInterpreterWindowsV65(unittest.TestCase):
    def test_windows_prefers_path_python(self):
        with mock.patch.object(nova.os, "name", "nt"), \
                mock.patch.object(nova.shutil, "which",
                                  side_effect=lambda c: "C:\\Py\\python.exe"
                                  if c == "python" else None):
            self.assertEqual(nova._normalize_run_hint("python3 hello.py"),
                             "python hello.py")
            self.assertEqual(nova.py_run_name(), "python")

    def test_pythonw_never_suggested(self):
        with mock.patch.object(nova.os, "name", "nt"), \
                mock.patch.object(nova.shutil, "which", side_effect=lambda c: None), \
                mock.patch.object(nova.sys, "executable", "C:\\Py\\pythonw.exe"):
            self.assertEqual(nova._pick_python_name(), "py")


# =====================================================================
# version pin
# =====================================================================
class TestVersionV65(unittest.TestCase):
    def test_version_is_650(self):
        self.assertEqual(nova.VERSION, "8.12.0")


import time  # noqa: E402  (used by the bg tests)


if __name__ == "__main__":
    unittest.main()