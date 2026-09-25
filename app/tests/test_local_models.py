#!/usr/bin/env python3
"""v5.2 tests: LOCAL MODEL FILES (the second way to pick a local brain).

Covers the pure nova_localmodels module (GGUF header parser, folder
scan, shard grouping, model dirs, ollama naming, llama.cpp server
lifecycle with injectable seams), the nova.py wiring (scan cache,
/mode table with continuous numbering, selection, startup resolution,
import, stream_chat routing) and the web face (/api/info local_models,
/api/settings file: switching) - all offline: Ollama is faked at
http_get_json / list_installed_models, llama-server at popen/poll."""
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova
import nova_localmodels as lm
import web_server

TAGS_OK = {"models": [
    {"name": "qwen2.5-coder:3b", "size": 1_900_000_000,
     "details": {"family": "qwen2", "parameter_size": "3.2B",
                 "quantization_level": "Q4_K_M"}},
    {"name": "llama3:8b", "size": 4_700_000_000,
     "details": {"family": "llama", "parameter_size": "8B"}},
]}


def tags_for(names):
    return {"models": [{"name": n, "size": 1_000_000,
                        "details": {"family": "f", "parameter_size": "1B"}}
                       for n in names]}


def fake_get_json(payload, fail=False):
    def fake(path, timeout=10):
        if fail:
            raise OSError("connection refused")
        return payload
    return fake


# ----------------------------------------------------------- GGUF builder
def gguf_bytes(kvs=(), version=3, tensor_count=0, tail=b"\x00" * 64):
    """Craft a minimal but VALID GGUF header for the parser tests.
    kvs: list of (key, kind, value) with kind in
    str/u32/u64/bool/f32/arr_str/arr_u32."""
    buf = b"GGUF" + struct.pack("<I", version) \
        + struct.pack("<Q", tensor_count) + struct.pack("<Q", len(kvs))
    for key, kind, val in kvs:
        kb = key.encode("utf-8")
        buf += struct.pack("<Q", len(kb)) + kb
        if kind == "str":
            vb = val.encode("utf-8")
            buf += struct.pack("<I", 8) + struct.pack("<Q", len(vb)) + vb
        elif kind == "u32":
            buf += struct.pack("<I", 4) + struct.pack("<I", val)
        elif kind == "u64":
            buf += struct.pack("<I", 10) + struct.pack("<Q", val)
        elif kind == "bool":
            buf += struct.pack("<I", 7) + struct.pack("<B", 1 if val else 0)
        elif kind == "f32":
            buf += struct.pack("<I", 6) + struct.pack("<f", val)
        elif kind == "arr_str":
            buf += struct.pack("<I", 9) + struct.pack("<I", 8) \
                + struct.pack("<Q", len(val))
            for s in val:
                sb = s.encode("utf-8")
                buf += struct.pack("<Q", len(sb)) + sb
        elif kind == "arr_u32":
            buf += struct.pack("<I", 9) + struct.pack("<I", 4) \
                + struct.pack("<Q", len(val))
            for v in val:
                buf += struct.pack("<I", v)
    return buf + tail


def write_gguf(path, **kw):
    kw.setdefault("tail", b"\x00" * 2048)   # > MIN_MODEL_BYTES: 'runnable'
    path.write_bytes(gguf_bytes(**kw))
    return path


GOOD_KVS = [
    ("general.architecture", "str", "llama"),
    ("general.name", "str", "My Fancy Model"),
    ("general.file_type", "u32", 15),          # Q4_K_M
    ("llama.context_length", "u64", 8192),
    ("general.size_label", "str", "7B"),
    ("tokenizer.ggml.tokens", "arr_str", ["<s>", "</s>", "hello"]),
    ("tokenizer.ggml.scores", "arr_u32", [1, 2, 3]),
]


# --------------------------------------------------------------- parser
class TestGgufHeader(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nova_gguf_"))

    def parse(self, data, name="m.gguf"):
        p = self.tmp / name
        p.write_bytes(data)
        return lm.parse_gguf_header(p)

    def test_valid_header_all_fields(self):
        out = self.parse(gguf_bytes(GOOD_KVS))
        self.assertEqual(out["error"], "")
        self.assertEqual(out["name"], "My Fancy Model")
        self.assertEqual(out["arch"], "llama")
        self.assertEqual(out["quant"], "Q4_K_M")
        self.assertEqual(out["ctx"], 8192)
        self.assertEqual(out["size_label"], "7B")
        self.assertEqual(out["version"], 3)

    def test_version_2_ok(self):
        out = self.parse(gguf_bytes(GOOD_KVS[:3], version=2))
        self.assertEqual(out["error"], "")
        self.assertEqual(out["arch"], "llama")

    def test_not_gguf(self):
        self.assertEqual(self.parse(b"PLAIN TEXT NOT GGUF AT ALL...."),
                         dict(lm.parse_gguf_header(self.tmp / "nope.gguf"))
                         if False else self.parse(b"PLAIN TEXT NOT GGUF AT ALL....") | {})
        out = self.parse(b"PLAIN TEXT NOT GGUF AT ALL....")
        self.assertEqual(out["error"], "not_gguf")

    def test_truncated_magic(self):
        out = self.parse(b"GG")
        self.assertEqual(out["error"], "not_gguf")

    def test_v1_rejected_cleanly(self):
        out = self.parse(gguf_bytes((), version=1))
        self.assertEqual(out["error"], "gguf_v1_or_unknown")

    def test_unknown_future_version(self):
        out = self.parse(gguf_bytes((), version=9))
        self.assertEqual(out["error"], "gguf_v1_or_unknown")

    def test_truncated_header(self):
        data = gguf_bytes(GOOD_KVS)
        out = self.parse(data[:20])          # cut inside the kv block
        self.assertEqual(out["error"], "truncated_header")

    def test_oversize_string_does_not_hang_or_crash(self):
        # declares a 1 GB string; the buffer is tiny -> parser must stop
        evil = [(b"general.name", 8, None)]  # built by hand below
        buf = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) \
            + struct.pack("<Q", 1)
        buf += struct.pack("<Q", len("general.name")) + b"general.name"
        buf += struct.pack("<I", 8) + struct.pack("<Q", 1 << 30)  # huge len
        out = self.parse(buf + b"tiny buffer")
        self.assertIn("error", out)          # degraded, never raised

    def test_missing_file_never_raises(self):
        out = lm.parse_gguf_header(self.tmp / "does_not_exist.gguf")
        self.assertTrue(out["error"].startswith("unreadable"))

    def test_empty_kvs(self):
        out = self.parse(gguf_bytes(()))
        self.assertEqual(out["error"], "")
        self.assertEqual(out["name"], "")


# --------------------------------------------------------------- scan
class TestScanDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nova_scan_"))

    def scan(self):
        return lm.scan_dirs([( "test", self.tmp, True )])

    def test_single_gguf_entry(self):
        write_gguf(self.tmp / "qwen2.5-3b-q4.gguf", kvs=GOOD_KVS)
        out = self.scan()
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(e["id"], "file:qwen2.5-3b-q4")
        self.assertEqual(e["name"], "qwen2.5-3b-q4")
        self.assertTrue(e["runnable"])
        self.assertEqual(e["format"], "gguf")
        self.assertEqual(e["arch"], "llama")
        self.assertEqual(e["quant"], "Q4_K_M")

    def test_shards_grouped_into_one(self):
        write_gguf(self.tmp / "big-00001-of-00003.gguf", kvs=GOOD_KVS[:1])
        write_gguf(self.tmp / "big-00002-of-00003.gguf", kvs=GOOD_KVS[:1])
        write_gguf(self.tmp / "big-00003-of-00003.gguf", kvs=GOOD_KVS[:1])
        out = self.scan()
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(e["name"], "big")
        self.assertEqual(e["parts"], 3)
        self.assertEqual(e["part_total"], 3)
        self.assertEqual(e["size"],
                         sum((self.tmp / f).stat().st_size
                             for f in ("big-00001-of-00003.gguf",
                                       "big-00002-of-00003.gguf",
                                       "big-00003-of-00003.gguf")))

    def test_broken_gguf_listed_but_not_runnable(self):
        (self.tmp / "broken.gguf").write_bytes(b"junk junk junk" * 100)
        out = self.scan()
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0]["runnable"])
        self.assertIn("not a valid GGUF", out[0]["note"])

    def test_safetensors_listed_not_runnable(self):
        (self.tmp / "model.safetensors").write_bytes(b"\x00" * 4096)
        out = self.scan()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["format"], "safetensors")
        self.assertFalse(out[0]["runnable"])
        self.assertIn("GGUF", out[0]["note"])

    def test_subdirs_scanned_and_skip_dirs_respected(self):
        sub = self.tmp / "family"
        sub.mkdir()
        write_gguf(sub / "inner.gguf", kvs=GOOD_KVS[:1])
        node = self.tmp / "node_modules"
        node.mkdir()
        write_gguf(node / "hidden.gguf", kvs=GOOD_KVS[:1])
        git = self.tmp / ".git"
        git.mkdir()
        write_gguf(git / "secrets.gguf", kvs=GOOD_KVS[:1])
        names = [e["name"] for e in self.scan()]
        self.assertEqual(names, ["inner"])

    def test_symlink_dir_not_followed(self):
        real = self.tmp / "real"
        real.mkdir()
        write_gguf(real / "real.gguf", kvs=GOOD_KVS[:1])
        try:
            os.symlink(real, self.tmp / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        names = [e["name"] for e in self.scan()]
        # 'real' is a genuine folder and IS scanned; the 'link' symlink
        # directory must be pruned (its content must NOT appear twice)
        self.assertEqual(names, ["real"])

    def test_sorted_by_name_and_capped(self):
        for i in range(30):
            write_gguf(self.tmp / f"m{i:03d}.gguf", kvs=GOOD_KVS[:1])
        out = lm.scan_dirs([("t", self.tmp, True)], max_entries=10)
        self.assertEqual(len(out), 10)
        names = [e["name"] for e in out]
        self.assertEqual(names, sorted(names))

    def test_missing_dir_yields_empty(self):
        self.assertEqual(lm.scan_dirs([("x", self.tmp / "nope", False)]), [])

    def test_tiny_file_skipped(self):
        (self.tmp / "tiny.gguf").write_bytes(b"GGUF" + b"\x00" * 10)
        out = self.scan()
        self.assertEqual(len(out), 1)     # listed...
        self.assertFalse(out[0]["runnable"])  # ...but honestly broken


# --------------------------------------------------------------- dirs
class TestModelDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nova_dirs_"))
        self.old_env = os.environ.get("NOVA_MODELS_DIR")

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("NOVA_MODELS_DIR", None)
        else:
            os.environ["NOVA_MODELS_DIR"] = self.old_env

    def test_env_override_multi_path(self):
        a = self.tmp / "a"; a.mkdir()
        os.environ["NOVA_MODELS_DIR"] = str(a) + os.pathsep + str(self.tmp / "b")
        out = lm.model_dirs()
        labels = [lab for lab, _p, _e in out]
        paths = [str(p) for _l, p, _e in out]
        self.assertIn("NOVA_MODELS_DIR", labels)
        self.assertIn(str(a), paths)

    def test_home_default_present(self):
        out = lm.model_dirs()
        self.assertTrue(any(p == Path.home() / ".nova" / "models"
                            for _l, p, _e in out))

    def test_project_dir_added_with_ws(self):
        out = lm.model_dirs(self.tmp)
        self.assertTrue(any(p == self.tmp / ".nova" / "models"
                            for _l, p, _e in out))

    def test_dedupe_same_path(self):
        a = self.tmp / "a"; a.mkdir()
        os.environ["NOVA_MODELS_DIR"] = str(a)
        out = lm.model_dirs(self.tmp)      # ws dir differs - no dupes of a
        paths = [str(p.resolve()) for _l, p, _e in out]
        self.assertEqual(len(paths), len(set(paths)))


# --------------------------------------------------------------- names
class TestNames(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(lm.sanitize_model_name("Qwen 2.5 (7B) [Q4]"),
                         "Qwen-2.5-7B-Q4")
        self.assertEqual(lm.sanitize_model_name("   "), "model")
        self.assertEqual(lm.sanitize_model_name("...---..."), "model")
        self.assertEqual(lm.sanitize_model_name("a" * 100), "a" * 48)

    def test_import_name_deterministic_and_distinct(self):
        tmp = Path(tempfile.mkdtemp(prefix="nova_name_"))
        a = tmp / "qwen2.5-7b-q4_k_m.gguf"
        a.write_bytes(gguf_bytes(GOOD_KVS))
        n1 = lm.ollama_import_name(a)
        n2 = lm.ollama_import_name(a)
        self.assertEqual(n1, n2)
        self.assertTrue(n1.startswith("local-qwen2.5-7b-q4_k_m-"))
        self.assertLessEqual(len(n1), 64)
        b = tmp / "llama3-8b.gguf"
        b.write_bytes(gguf_bytes(GOOD_KVS))
        self.assertNotEqual(lm.ollama_import_name(a), lm.ollama_import_name(b))

    def test_import_name_strips_shard_suffix(self):
        tmp = Path(tempfile.mkdtemp(prefix="nova_name_"))
        a = tmp / "big-00001-of-00003.gguf"
        a.write_bytes(gguf_bytes(GOOD_KVS))
        self.assertTrue(lm.ollama_import_name(a).startswith("local-big-"))


# --------------------------------------------------------------- llama.cpp
class _FakeProc:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.waited = 0
        self.args = None

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        # v6.2.1: fakes are now faithful Popen doubles - _reap() waits
        # after terminate(); return 0 (exited) so no kill escalation
        self.waited += 1
        return 0


class TestLlamaServer(unittest.TestCase):
    def setUp(self):
        lm._RUNNING.clear()

    def tearDown(self):
        lm.stop_all()

    def test_find_none_when_absent(self):
        orig = lm.shutil.which
        try:
            lm.shutil.which = lambda name: None
            self.assertIsNone(lm.find_llama_server())
        finally:
            lm.shutil.which = orig

    def test_start_ok_with_injected_popen_and_poll(self):
        proc = _FakeProc()
        h = lm.start_llama_server("/tmp/fake.gguf", exe="/usr/bin/llama-server",
                                  wait_s=5, popen=lambda args: proc,
                                  poll=lambda base, dl: True)
        self.assertTrue(h["base"].endswith("/v1"))
        self.assertTrue(h["port"], "port assigned")
        self.assertIs(lm.get_running("/tmp/fake.gguf"), h)

    def test_start_stops_previous_server_one_slot_policy(self):
        p1, p2 = _FakeProc(), _FakeProc()
        lm.start_llama_server("/tmp/a.gguf", exe="x", wait_s=5,
                              popen=lambda args: p1, poll=lambda b, d: True)
        lm.start_llama_server("/tmp/b.gguf", exe="x", wait_s=5,
                              popen=lambda args: p2, poll=lambda b, d: True)
        self.assertTrue(p1.terminated)
        self.assertFalse(p2.terminated)
        self.assertIn(str(Path("/tmp/b.gguf").resolve()), lm._RUNNING)

    def test_start_failure_raises_and_cleans_up(self):
        proc = _FakeProc()
        with self.assertRaises(lm.LocalModelError):
            lm.start_llama_server("/tmp/c.gguf", exe="x", wait_s=5,
                                  popen=lambda args: proc,
                                  poll=lambda b, d: False)
        self.assertTrue(proc.terminated)
        self.assertEqual(lm._RUNNING, {})

    def test_openai_cfg_shape(self):
        cfg = lm.openai_cfg({"base": "http://127.0.0.1:9/v1"})
        self.assertEqual(cfg["kind"], "openai")
        self.assertEqual(cfg["base"], "http://127.0.0.1:9/v1")
        self.assertEqual(cfg["key"], "")

    def test_wait_health_with_real_tiny_server(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            self.assertTrue(lm._wait_health(base, 5))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_wait_health_timeout(self):
        # a closed port -> connection refused -> False after the deadline
        self.assertFalse(lm._wait_health("http://127.0.0.1:1", 1))


# --------------------------------------------------------------- nova wiring
def _entry(tmp, name="qwen-file", gguf=True):
    p = tmp / (name + (".gguf" if gguf else ".bin"))
    if gguf:
        write_gguf(p, kvs=GOOD_KVS)
    else:
        p.write_bytes(b"\x00" * 4096)
    return lm._entry_for(p)


class TestNovaWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nova_wire_"))
        self.sess = nova.Session(self.tmp)
        nova._LOCAL_SCAN.update(at=0.0, key=None, list=[])

    def tearDown(self):
        nova._LOCAL_SCAN.update(at=0.0, key=None, list=[])

    def test_list_local_models_caches_until_forced(self):
        calls = {"n": 0}
        orig = lm.scan_dirs
        def counting(dirs, **kw):
            calls["n"] += 1
            return [_entry(self.tmp)]
        lm.scan_dirs = counting
        try:
            a = nova.list_local_models(self.sess.ws)
            b = nova.list_local_models(self.sess.ws)
            self.assertEqual(calls["n"], 1)
            self.assertEqual(len(a), 1)
            self.assertEqual(a, b)
            nova.list_local_models(self.sess.ws, force=True)
            self.assertEqual(calls["n"], 2)
        finally:
            lm.scan_dirs = orig

    def test_find_local_entry_by_id_name_and_filename(self):
        e = _entry(self.tmp, "mymodel")
        nova._LOCAL_SCAN.update(at=__import__("time").time(),
                                key=str(self.sess.ws), list=[e])
        self.assertIs(nova._find_local_entry("file:mymodel", [e]), e)
        self.assertIs(nova._find_local_entry("mymodel", [e]), e)
        self.assertIs(nova._find_local_entry("mymodel.gguf", [e]), e)
        self.assertIsNone(nova._find_local_entry("other", [e]))

    def test_match_local_entry_continuous_numbers(self):
        e1 = _entry(self.tmp, "one")
        e2 = _entry(self.tmp, "two")
        # ollama rows 1..2 -> local rows are 3..4 (CONTINUOUS numbering)
        self.assertIsNone(nova._match_local_entry("1", [e1, e2], installed_count=2))
        self.assertIsNone(nova._match_local_entry("2", [e1, e2], installed_count=2))
        self.assertIs(nova._match_local_entry("3", [e1, e2], installed_count=2), e1)
        self.assertIs(nova._match_local_entry("4", [e1, e2], installed_count=2), e2)
        self.assertIsNone(nova._match_local_entry("5", [e1, e2], installed_count=2))
        # with an EMPTY ollama library the locals start at row 1
        self.assertIs(nova._match_local_entry("1", [e1, e2], installed_count=0), e1)
        self.assertIs(nova._match_local_entry("2", [e1, e2], installed_count=0), e2)
        self.assertIsNone(nova._match_local_entry("3", [e1, e2], installed_count=0))

    def test_resolve_session_model_file_model_found(self):
        e = _entry(self.tmp, "kept")
        orig = nova.http_get_json
        scan_orig = nova._LOCAL_SCAN.copy()
        try:
            nova.http_get_json = fake_get_json(TAGS_OK)
            nova._LOCAL_SCAN.update(at=__import__("time").time(),
                                    key=str(self.sess.ws), list=[e])
            self.sess.model = "file:kept"
            self.assertEqual(nova.resolve_session_model(self.sess, quiet=True),
                             "file:kept")
        finally:
            nova.http_get_json = orig
            nova._LOCAL_SCAN.update(**scan_orig)

    def test_resolve_session_model_file_model_missing_falls_back(self):
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json(TAGS_OK)
            nova._LOCAL_SCAN.update(at=__import__("time").time(),
                                    key=str(self.sess.ws), list=[])
            self.sess.model = "file:ghost"
            self.assertEqual(nova.resolve_session_model(self.sess, quiet=True),
                             "qwen2.5-coder:3b")
        finally:
            nova.http_get_json = orig

    def test_resolve_session_model_ollama_empty_uses_local_file(self):
        e = _entry(self.tmp, "onlybrain")
        orig = nova.http_get_json
        try:
            nova.http_get_json = fake_get_json({"models": []})   # up, EMPTY
            nova._LOCAL_SCAN.update(at=__import__("time").time(),
                                    key=str(self.sess.ws), list=[e])
            self.sess.model = ""
            self.assertEqual(nova.resolve_session_model(self.sess, quiet=True),
                             "file:onlybrain")
        finally:
            nova.http_get_json = orig

    def _with_env_models(self, names):
        """Create REAL .gguf files and point NOVA_MODELS_DIR at them,
        so the force-scan inside /model genuinely discovers them."""
        for n in names:
            write_gguf(self.tmp / (n + ".gguf"), kvs=GOOD_KVS)
        self._old_env = os.environ.get("NOVA_MODELS_DIR")
        os.environ["NOVA_MODELS_DIR"] = str(self.tmp)

    def _drop_env_models(self):
        if self._old_env is None:
            os.environ.pop("NOVA_MODELS_DIR", None)
        else:
            os.environ["NOVA_MODELS_DIR"] = self._old_env

    def test_cmd_model_table_two_sections_and_number_switch(self):
        orig = nova.http_get_json
        ensure_orig = nova.ensure_local_model
        try:
            self._with_env_models(["fileone", "filetwo"])
            nova.http_get_json = fake_get_json(TAGS_OK)   # 2 ollama models
            nova.ensure_local_model = lambda sess=None, entry=None, quiet=False: \
                ("ollama", "local-fileone-deadbe")
            out = io.StringIO()
            with redirect_stdout(out):
                nova.cmd_model(self.sess, "")             # the table
            text = out.getvalue()
            self.assertIn("Ollama models (2)", text)
            self.assertIn("Local model files (2)", text)
            self.assertIn("fileone", text)
            out = io.StringIO()
            with redirect_stdout(out):
                nova.cmd_model(self.sess, "3")            # first LOCAL row
            self.assertEqual(self.sess.model, "file:fileone")
            out = io.StringIO()
            with redirect_stdout(out):
                nova.cmd_model(self.sess, "filetwo")      # by name
            self.assertEqual(self.sess.model, "file:filetwo")
            out = io.StringIO()
            with redirect_stdout(out):
                nova.cmd_model(self.sess, "2")            # still ollama row 2
            self.assertEqual(self.sess.model, "llama3:8b")
        finally:
            nova.http_get_json = orig
            nova.ensure_local_model = ensure_orig
            self._drop_env_models()
            nova._LOCAL_SCAN.update(at=0.0, key=None, list=[])

    def test_cmd_model_unknown_name_helps(self):
        orig = nova.http_get_json
        try:
            self._with_env_models([])
            nova.http_get_json = fake_get_json(TAGS_OK)
            self.sess.model = "qwen2.5-coder:3b"      # as if resolved earlier
            out = io.StringIO()
            with redirect_stdout(out):
                nova.cmd_model(self.sess, "mystery")
            self.assertIn("matches no Ollama model", out.getvalue())
            self.assertEqual(self.sess.model, "qwen2.5-coder:3b")
        finally:
            nova.http_get_json = orig
            self._drop_env_models()
            nova._LOCAL_SCAN.update(at=0.0, key=None, list=[])

    def test_select_local_file_pins_profile(self):
        e = _entry(self.tmp, "pinned")
        orig = nova.ensure_local_model
        try:
            nova.ensure_local_model = lambda sess=None, entry=None, quiet=False: \
                ("ollama", "local-pinned-123456")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertTrue(nova._select_local_file(self.sess, e, quiet=True))
            self.assertEqual(self.sess.model, "file:pinned")
            prof = nova.nproj.load_profile(self.sess.ws)
            self.assertEqual(prof.get("model"), "file:pinned")
        finally:
            nova.ensure_local_model = orig

    def test_select_local_file_failure_prints_reason(self):
        e = _entry(self.tmp, "norun")
        orig = nova.ensure_local_model
        try:
            nova.ensure_local_model = lambda sess=None, entry=None, quiet=False: \
                (None, "no runtime available")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertFalse(nova._select_local_file(self.sess, e, quiet=True))
            self.assertIn("no runtime available", out.getvalue())
        finally:
            nova.ensure_local_model = orig

    def test_import_gguf_runs_ollama_create_once(self):
        e = _entry(self.tmp, "importme")
        cmds = []
        class R:
            returncode = 0
            stdout, stderr = "", ""
        orig_sub = nova.subprocess.run
        orig_installed = nova.list_installed_models
        nova.list_installed_models = lambda: []      # nothing imported yet
        def fake_run(cmd, **kw):
            cmds.append(cmd)
            return R()
        nova.subprocess.run = fake_run
        try:
            name = nova.import_gguf_to_ollama(e, ws=self.sess.ws, quiet=True)
            self.assertIsNotNone(name)
            self.assertTrue(name.startswith("local-importme-"))
            self.assertEqual(len(cmds), 1)
            self.assertIn("create", cmds[0])
            self.assertIn(name, cmds[0])
            self.assertIn("-f", cmds[0])
            # second call: already installed -> NO second subprocess
            nova.list_installed_models = lambda: [name]
            name2 = nova.import_gguf_to_ollama(e, ws=self.sess.ws, quiet=True)
            self.assertEqual(name2, name)
            self.assertEqual(len(cmds), 1)
            # cache remembers the mapping
            self.assertEqual(nova._local_cache_get(self.sess.ws, e["file"]), name)
        finally:
            nova.subprocess.run = orig_sub
            nova.list_installed_models = orig_installed

    def test_import_failure_returns_none(self):
        e = _entry(self.tmp, "failimp")
        class R:
            returncode = 1
            stdout, stderr = "", "boom: bad file"
        orig_sub = nova.subprocess.run
        orig_installed = nova.list_installed_models
        nova.list_installed_models = lambda: []
        nova.subprocess.run = lambda cmd, **kw: R()
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertIsNone(nova.import_gguf_to_ollama(e, ws=self.sess.ws))
            self.assertIn("ollama create failed", out.getvalue())
            self.assertIn("boom", out.getvalue())
        finally:
            nova.subprocess.run = orig_sub
            nova.list_installed_models = orig_installed

    def test_ensure_prefers_cached_ollama_import(self):
        e = _entry(self.tmp, "cached")
        nova._local_cache_set(self.sess.ws, e["file"], "local-cached-abc")
        orig_installed = nova.list_installed_models
        nova.list_installed_models = lambda: ["local-cached-abc"]
        try:
            mode, val = nova.ensure_local_model(self.sess, entry=e, quiet=True)
            self.assertEqual(mode, "ollama")
            self.assertEqual(val, "local-cached-abc")
        finally:
            nova.list_installed_models = orig_installed

    def test_ensure_non_runnable_gives_clean_reason(self):
        e = _entry(self.tmp, "tens", gguf=False)
        mode, msg = nova.ensure_local_model(self.sess, entry=e, quiet=True)
        self.assertIsNone(mode)
        self.assertIn("GGUF", msg)

    def test_ensure_no_runtime_clean_error(self):
        e = _entry(self.tmp, "noruntime")
        orig_alive = nova._ollama_alive
        orig_start = lm.start_llama_server
        nova._ollama_alive = lambda timeout=4: False
        def boom(*a, **kw):
            raise lm.LocalModelError("llama-server not found - install llama.cpp")
        lm.start_llama_server = boom
        try:
            mode, msg = nova.ensure_local_model(self.sess, entry=e, quiet=True)
            self.assertIsNone(mode)
            self.assertIn("llama-server", msg)
        finally:
            nova._ollama_alive = orig_alive
            lm.start_llama_server = orig_start

    def test_route_note_without_side_effects(self):
        e = _entry(self.tmp, "noted")
        nova._LOCAL_SCAN.update(at=__import__("time").time(),
                                key=str(self.sess.ws), list=[e])
        self.sess.model = "file:noted"
        self.assertIn("runtime resolves on first use", nova._model_route_note(self.sess))
        nova._local_cache_set(self.sess.ws, e["file"], "local-noted-xyz")
        self.assertIn("via Ollama as local-noted-xyz", nova._model_route_note(self.sess))
        self.sess.model = "file:ghost"
        self.assertIn("missing", nova._model_route_note(self.sess))

    def test_branding_constants(self):
        self.assertEqual(nova.AGENT_NAME, "Nova Assistant")
        self.assertEqual(nova.CODING_BRAND, "Nova Code")
        self.assertEqual(nova.VERSION, "8.12.0")


class _FakeResp:
    """urlopen() stand-in: iterating yields pre-built byte lines."""
    def __init__(self, lines):
        self._lines = [l if isinstance(l, bytes) else l.encode() for l in lines]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


class TestStreamChatRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nova_stream_"))
        self.sess = nova.Session(self.tmp)
        nova._LOCAL_SCAN.update(at=__import__("time").time(),
                                key=str(self.tmp), list=[_entry(self.tmp, "brain")])

    def tearDown(self):
        nova._LOCAL_SCAN.update(at=0.0, key=None, list=[])

    def test_file_model_routes_through_ollama_with_imported_name(self):
        orig_ensure = nova.ensure_local_model
        orig_urlopen = nova.urllib.request.urlopen
        captured = {}
        nova.ensure_local_model = lambda sess=None, entry=None, quiet=False: \
            ("ollama", "local-brain-dead00")
        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _FakeResp([json.dumps({
                "message": {"content": "hi "}, "done": False}),
                json.dumps({"message": {"content": "there"}, "done": True,
                            "prompt_eval_count": 3, "eval_count": 2})])
        nova.urllib.request.urlopen = fake_urlopen
        try:
            self.sess.model = "file:brain"
            text, complete = nova.stream_chat(
                self.sess.model, [{"role": "user", "content": "ping"}],
                0.4, sess=self.sess)
            self.assertEqual(text, "hi there")
            self.assertTrue(complete)
            self.assertEqual(captured["body"]["model"], "local-brain-dead00")
        finally:
            nova.ensure_local_model = orig_ensure
            nova.urllib.request.urlopen = orig_urlopen

    def test_file_model_unrunnable_surfaces_clean_error(self):
        nova._LOCAL_SCAN.update(at=__import__("time").time(), key=str(self.tmp),
                                list=[_entry(self.tmp, "sft", gguf=False)])
        self.sess.model = "file:sft"
        text, complete = nova.stream_chat(
            self.sess.model, [{"role": "user", "content": "ping"}], 0.4,
            sess=self.sess)
        self.assertEqual(text, "")
        self.assertFalse(complete)

    def test_llamacpp_route_uses_openai_stream(self):
        orig_ensure = nova.ensure_local_model
        orig_urlopen = nova.urllib.request.urlopen
        nova.ensure_local_model = lambda sess=None, entry=None, quiet=False: \
            ("llamacpp", {"kind": "openai", "name": "llamacpp",
                          "label": "llama.cpp (local GGUF)",
                          "base": "http://127.0.0.1:1/v1", "key": ""})
        def fail_urlopen(req, timeout=None):
            raise urllib.error.URLError("no server in tests")
        nova.urllib.request.urlopen = fail_urlopen
        try:
            self.sess.model = "file:brain"
            text, complete = nova.stream_chat(
                self.sess.model, [{"role": "user", "content": "ping"}], 0.4,
                sess=self.sess)
            # the llama route went through the OPENAI adapter (URLError ->
            # ProviderError message path) instead of the Ollama NDJSON one
            self.assertEqual(text, "")
            self.assertFalse(complete)
        finally:
            nova.ensure_local_model = orig_ensure
            nova.urllib.request.urlopen = orig_urlopen


# --------------------------------------------------------------- web face
class TestWebLocalModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web_server.nova = nova
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_lweb_"))
        cls.entry_tmp = Path(tempfile.mkdtemp(prefix="nova_lweb_m_"))
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        cls.httpd = web_server._make_server(args)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def post(self, path, obj):
        data = json.dumps(obj).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def setUp(self):
        self._patches = []

    def tearDown(self):
        for orig, target in self._patches:
            if target == "llm":
                nova.list_local_models = orig
            elif target == "ensure":
                nova.ensure_local_model = orig
            elif target == "find":
                nova._find_local_entry = orig
            elif target == "tags":
                nova.http_get_json = orig

    def patch(self, target, orig, fake):
        self._patches.append((orig, target))
        if target == "llm":
            nova.list_local_models = fake
        elif target == "ensure":
            nova.ensure_local_model = fake
        elif target == "find":
            nova._find_local_entry = fake
        elif target == "tags":
            nova.http_get_json = fake

    def test_info_includes_local_models_and_dirs(self):
        e = _entry(self.entry_tmp, "webmodel")
        self.patch("llm", nova.list_local_models, lambda ws=None, force=False: [e])
        self.patch("tags", nova.http_get_json, fake_get_json(TAGS_OK))
        code, info = self.get("/api/info")
        self.assertEqual(code, 200)
        self.assertEqual(len(info["local_models"]), 1)
        lm0 = info["local_models"][0]
        self.assertEqual(lm0["id"], "file:webmodel")
        self.assertTrue(lm0["runnable"])
        self.assertTrue(isinstance(info["models_dirs"], list))
        self.assertGreater(len(info["models_dirs"]), 0)

    def test_info_without_local_models(self):
        self.patch("llm", nova.list_local_models, lambda ws=None, force=False: [])
        self.patch("tags", nova.http_get_json, fake_get_json(TAGS_OK))
        code, info = self.get("/api/info")
        self.assertEqual(code, 200)
        self.assertEqual(info["local_models"], [])

    def test_settings_file_model_switch(self):
        e = _entry(self.entry_tmp, "webpick")
        self.patch("llm", nova.list_local_models, lambda ws=None, force=False: [e])
        self.patch("find", nova._find_local_entry, lambda mid, ents=None: e)
        self.patch("ensure", nova.ensure_local_model,
                   lambda sess=None, entry=None, quiet=False:
                   ("ollama", "local-webpick-abc123"))
        code, res = self.post("/api/settings", {"model": "file:webpick"})
        self.assertEqual(code, 200)
        self.assertEqual(res["model"], "file:webpick")
        self.assertEqual(res["via"], "ollama")
        self.assertEqual(web_server.STATE.sess.model, "file:webpick")

    def test_settings_file_model_missing_404(self):
        self.patch("llm", nova.list_local_models, lambda ws=None, force=False: [])
        self.patch("find", nova._find_local_entry, lambda mid, ents=None: None)
        code, res = self.post("/api/settings", {"model": "file:ghost"})
        self.assertEqual(code, 404)

    def test_settings_file_model_no_runtime_502(self):
        e = _entry(self.entry_tmp, "webrt")
        self.patch("llm", nova.list_local_models, lambda ws=None, force=False: [e])
        self.patch("find", nova._find_local_entry, lambda mid, ents=None: e)
        self.patch("ensure", nova.ensure_local_model,
                   lambda sess=None, entry=None, quiet=False:
                   (None, "no runtime available"))
        code, res = self.post("/api/settings", {"model": "file:webrt"})
        self.assertEqual(code, 502)
        self.assertIn("no runtime", res["error"])


if __name__ == "__main__":
    unittest.main()
