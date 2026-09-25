#!/usr/bin/env python3
"""v6.1 tests: categorized model folders (local/, local/code, local/voice,
local/photo), the new voice engines (Coqui/Mozilla + Bark), piper file:
voices, Flow file: brains, category-aware assignment, /api/models_all
categories + the extended platform presets."""
import json
import struct
import sys
import tempfile
import threading
import unittest
import urllib.request
import wave
import io
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_localmodels as lmodels
import nova_platforms as platforms
from nova_modules import assign, voice, ModuleError


# ----------------------------------------------------------- helpers
def gguf_bytes(name="m", arch="llama", file_type=15):
    """A minimal VALID GGUF header (metadata only, no tensors)."""
    kvs = [("general.name", 8, name), ("general.architecture", 8, arch),
           ("general.file_type", 4, file_type)]
    buf = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) \
        + struct.pack("<Q", len(kvs))
    for key, kind, val in kvs:
        kb = key.encode()
        buf += struct.pack("<Q", len(kb)) + kb
        if kind == 8:
            vb = val.encode()
            buf += struct.pack("<I", 8) + struct.pack("<Q", len(vb)) + vb
        else:
            buf += struct.pack("<I", 4) + struct.pack("<I", val)
    return buf + b"\x00" * 64


def make_wav(seconds=0.2, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return buf.getvalue()


class FakeEngine(BaseHTTPRequestHandler):
    """Coqui TTS + bark-server on one port; records the last request."""
    last = {"path": None, "body": None}

    def _wav(self):
        raw = make_wav()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0) or 0)
        FakeEngine.last = {"path": self.path,
                           "body": self.rfile.read(ln).decode("utf-8", "replace")}
        self._wav()

    def log_message(self, *a):
        pass


class TempRootCase(unittest.TestCase):
    """A clean models root + NOVA_MODELS_DIR pointed at it."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="nova_cat_"))
        self.ws = Path(tempfile.mkdtemp(prefix="nova_ws_"))
        self.old_env = os.environ.get("NOVA_MODELS_DIR")
        os.environ["NOVA_MODELS_DIR"] = str(self.root)
        for sub in ("code", "voice", "photo"):
            (self.root / sub).mkdir()

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("NOVA_MODELS_DIR", None)
        else:
            os.environ["NOVA_MODELS_DIR"] = self.old_env

    def scan(self):
        return lmodels.scan_dirs(lmodels.model_dirs(self.ws))


# ----------------------------------------------------------- categories
class TestCategoryPure(TempRootCase):
    def test_category_for_names_and_aliases(self):
        self.assertEqual(lmodels.category_for(("code", "x.gguf")), "code")
        self.assertEqual(lmodels.category_for(("CODER", "x.gguf")), "code")
        self.assertEqual(lmodels.category_for(("tts", "a.onnx")), "voice")
        self.assertEqual(lmodels.category_for(("speech", "a.onnx")), "voice")
        self.assertEqual(lmodels.category_for(("images", "a.safetensors")),
                         "photo")
        self.assertEqual(lmodels.category_for(("sd", "a.safetensors")), "photo")
        self.assertEqual(lmodels.category_for(("my-stuff", "a.gguf")),
                         "general")
        self.assertEqual(lmodels.category_for(()), "general")
        self.assertEqual(lmodels.category_for(None), "general")

    def test_module_cats_map(self):
        self.assertIn("code", lmodels.MODULE_CATS["code"])
        self.assertIn("general", lmodels.MODULE_CATS["code"])
        self.assertNotIn("photo", lmodels.MODULE_CATS["code"])
        self.assertNotIn("photo", lmodels.MODULE_CATS["voice"])
        self.assertNotIn("voice", lmodels.MODULE_CATS["photo"])
        self.assertEqual(set(lmodels.MODULE_CATS["flow"]),
                         {"code", "voice", "photo", "general"})
        self.assertIn("code", lmodels.MODULE_CATS["assistant"])

    def test_allowed_for_module(self):
        rows = [{"name": "a", "category": "code"},
                {"name": "b", "category": "voice"},
                {"name": "c", "category": "photo"},
                {"name": "d", "category": "general"}]
        self.assertEqual([e["name"] for e in
                          lmodels.allowed_for_module(rows, "code")], ["a", "d"])
        self.assertEqual([e["name"] for e in
                          lmodels.allowed_for_module(rows, "voice")],
                         ["b", "d"])
        self.assertEqual([e["name"] for e in
                          lmodels.allowed_for_module(rows, "photo")],
                         ["c", "d"])
        self.assertEqual([e["name"] for e in
                          lmodels.allowed_for_module(rows, "flow")],
                         ["a", "b", "c", "d"])
        self.assertEqual([e["name"] for e in
                          lmodels.allowed_for_module(rows, "nope")], ["d"])

    def test_categories_of_shape(self):
        rows = [{"name": "a", "category": "code"},
                {"name": "d", "category": "general"}]
        cats = lmodels.categories_of(rows)
        self.assertEqual(cats["code"][0]["name"], "a")
        self.assertEqual(cats["general"][0]["name"], "d")
        self.assertEqual(cats["voice"], [])

    def test_prepare_local_dirs(self):
        self.assertTrue(hasattr(lmodels, "app_local_dir"))
        base = Path(tempfile.mkdtemp(prefix="nova_local_"))
        orig = lmodels.app_local_dir
        try:
            lmodels.app_local_dir = lambda: base / "local"
            made = lmodels.prepare_local_dirs()
            self.assertEqual(len(made), 4)
            for cat in ("code", "voice", "photo"):
                self.assertTrue((base / "local" / cat).is_dir())
                self.assertTrue((base / "local" / cat / "README.txt").is_file())
            made2 = lmodels.prepare_local_dirs()      # idempotent
            self.assertEqual(len(made2), 4)
        finally:
            lmodels.app_local_dir = orig


# ----------------------------------------------------------- scanning
class TestScanCategories(TempRootCase):
    def test_entries_carry_categories(self):
        (self.root / "m.gguf").write_bytes(gguf_bytes())
        (self.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        (self.root / "photo" / "art.safetensors").write_bytes(b"0" * 4096)
        (self.root / "voice" / "fa-voice.onnx").write_bytes(b"0" * 4096)
        entries = self.scan()
        cats = {e["name"]: e["category"] for e in entries}
        self.assertEqual(cats["m"], "general")
        self.assertEqual(cats["coder"], "code")
        self.assertEqual(cats["art"], "photo")
        self.assertEqual(cats["fa-voice"], "voice")

    def test_onnx_is_voice_not_llm(self):
        (self.root / "voice" / "fa-voice.onnx").write_bytes(b"0" * 4096)
        (self.root / "fa2.onnx").write_bytes(b"0" * 4096)   # general folder
        entries = {e["name"]: e for e in self.scan()}
        v = entries["fa-voice"]
        self.assertEqual(v["format"], "onnx")
        self.assertFalse(v["runnable"])
        self.assertIn("voice", v["note"])
        self.assertEqual(v["category"], "voice")
        # an .onnx outside any category folder still counts as a voice model
        self.assertEqual(entries["fa2"]["category"], "voice")

    def test_safetensors_notes_by_category(self):
        (self.root / "photo" / "sd15.safetensors").write_bytes(b"0" * 4096)
        (self.root / "m7.safetensors").write_bytes(b"0" * 4096)
        entries = {e["name"]: e for e in self.scan()}
        self.assertIn("image model", entries["sd15"]["note"])
        self.assertEqual(entries["sd15"]["category"], "photo")
        # outside the photo folder the generic honest note stays
        self.assertIn("convert to GGUF", entries["m7"]["note"])
        self.assertEqual(entries["m7"]["category"], "general")

    def test_shards_keep_category(self):
        for part in ("x-00001-of-00002.gguf", "x-00002-of-00002.gguf"):
            (self.root / "code" / part).write_bytes(gguf_bytes())
        entries = self.scan()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["category"], "code")
        self.assertEqual(entries[0]["part_total"], 2)

    def test_model_dirs_includes_app_local(self):
        dirs = lmodels.model_dirs(self.ws)
        labels = [lb for lb, _p, _e in dirs]
        self.assertIn("local", labels)
        self.assertIn("default", labels)
        self.assertIn("project", labels)
        # app local dir sits next to this very file's module
        self.assertTrue(str(lmodels.app_local_dir()).endswith("local"))

    def test_clean_id_name_strips_onnx(self):
        self.assertEqual(lmodels._clean_id_name("fa-voice.onnx"), "fa-voice")
        self.assertEqual(lmodels._clean_id_name("m-00001-of-00003.gguf"), "m")


# ----------------------------------------------------------- assignment
class TestAssignCategoryValidation(TempRootCase):
    def test_photo_model_rejected_for_assistant(self):
        (self.root / "photo" / "art.gguf").write_bytes(gguf_bytes())
        with self.assertRaises(ModuleError) as cm:
            assign.save_module(self.ws, "assistant",
                               {"backend": "file", "model": "file:art"})
        self.assertIn("photo", str(cm.exception))
        # a safetensors image model is rejected even earlier: not an LLM
        (self.root / "photo" / "v1-5.safetensors").write_bytes(b"0" * 4096)
        with self.assertRaises(ModuleError) as cm2:
            assign.save_module(self.ws, "assistant",
                               {"backend": "file", "model": "file:v1-5"})
        self.assertIn("not a runnable", str(cm2.exception))

    def test_code_model_ok_for_assistant(self):
        (self.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        cfg = assign.save_module(self.ws, "assistant",
                                 {"backend": "file", "model": "coder"})
        self.assertEqual(cfg["model"], "file:coder")

    def test_unknown_file_rejected(self):
        with self.assertRaises(ModuleError):
            assign.save_module(self.ws, "assistant",
                               {"backend": "file", "model": "ghost"})
        # junk file that fails the GGUF parse is also not assignable
        (self.root / "broken.gguf").write_bytes(b"NOTGGUF" + b"\x00" * 100)
        with self.assertRaises(ModuleError):
            assign.save_module(self.ws, "assistant",
                               {"backend": "file", "model": "broken"})

    def test_piper_voice_resolution(self):
        (self.root / "voice" / "fa-voice.onnx").write_bytes(b"0" * 4096)
        cfg = assign.save_module(self.ws, "voice",
                                 {"backend": "piper", "model": "fa-voice"})
        self.assertEqual(cfg["model"], "file:fa-voice")
        (self.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        with self.assertRaises(ModuleError) as cm:
            assign.save_module(self.ws, "voice",
                               {"backend": "piper", "model": "coder"})
        self.assertIn(".onnx", str(cm.exception))
        with self.assertRaises(ModuleError):
            assign.save_module(self.ws, "voice",
                               {"backend": "piper", "model": "ghost"})
        # real path passes through untouched
        p = str(self.root / "voice" / "fa-voice.onnx")
        cfg = assign.save_module(self.ws, "voice",
                                 {"backend": "piper", "model": p})
        self.assertEqual(cfg["model"], p)

    def test_new_voice_backends_accepted_with_default_urls(self):
        cfg = assign.save_module(self.ws, "voice",
                                 {"backend": "coqui", "model": "tts_models/fa"})
        self.assertEqual(cfg["url"], "http://127.0.0.1:5002")
        cfg = assign.save_module(self.ws, "voice", {"backend": "bark"})
        self.assertEqual(cfg["url"], "http://127.0.0.1:8010")
        assign.clear_module(self.ws, "voice")


# ----------------------------------------------------------- voice engines
class TestVoiceEngines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), FakeEngine)
        cls.port = cls.httpd.server_address[1]
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_voice61_"))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_coqui_engine_posts_api_tts(self):
        out = voice.synthesize(self.ws, "سلام دنیا",
                               {"backend": "coqui",
                                "url": "http://127.0.0.1:%d" % self.port,
                                "model": "tts_models/fa", "lang": "fa"})
        self.assertEqual(out["engine"], "coqui")
        self.assertEqual(out["fmt"], "wav")
        self.assertGreater(out["bytes"], 100)
        self.assertEqual(FakeEngine.last["path"], "/api/tts")
        body = json.loads(FakeEngine.last["body"])
        self.assertEqual(body["text"], "سلام دنیا")
        self.assertEqual(body["model_id"], "tts_models/fa")

    def test_bark_engine_posts_v1_generate(self):
        out = voice.synthesize(self.ws, "hello",
                               {"backend": "bark",
                                "url": "http://127.0.0.1:%d" % self.port,
                                "voice": "en_speaker_6"})
        self.assertEqual(out["engine"], "bark")
        self.assertEqual(FakeEngine.last["path"], "/v1/generate")
        body = json.loads(FakeEngine.last["body"])
        self.assertEqual(body["text"], "hello")
        self.assertEqual(body["history_prompt"], "en_speaker_6")

    def test_engine_specs_listed(self):
        from nova_modules import spec
        self.assertIn("coqui", spec("voice")["backends"])
        self.assertIn("bark", spec("voice")["backends"])
        self.assertIn("piper", spec("voice")["backends"])

    def test_piper_uses_resolved_file(self):
        root = Path(tempfile.mkdtemp(prefix="nova_piper_"))
        (root / "voice").mkdir()
        (root / "code").mkdir()
        (root / "voice" / "fa-voice.onnx").write_bytes(b"0" * 4096)
        (root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        old_env = os.environ.get("NOVA_MODELS_DIR")
        os.environ["NOVA_MODELS_DIR"] = str(root)
        try:
            calls = {}

            def fake_run(cmd, **kw):
                calls["cmd"] = cmd
                out = Path(cmd[cmd.index("--output_file") + 1])
                out.write_bytes(make_wav())

                class R:
                    returncode = 0
                    stderr = b""

                return R()

            import subprocess
            orig = subprocess.run
            subprocess.run = fake_run
            try:
                out = voice.synthesize(self.ws, "سلام",
                                       {"backend": "piper",
                                        "model": "file:fa-voice"})
                self.assertEqual(out["engine"], "piper")
                self.assertEqual(calls["cmd"][calls["cmd"].index("--model") + 1],
                                 str(root / "voice" / "fa-voice.onnx"))
            finally:
                subprocess.run = orig
            # an LLM file must NOT be handed to piper
            with self.assertRaises(ModuleError):
                voice.synthesize(self.ws, "سلام",
                                 {"backend": "piper", "model": "file:coder"})
            # unknown file: id -> clean error
            with self.assertRaises(ModuleError):
                voice.synthesize(self.ws, "سلام",
                                 {"backend": "piper", "model": "file:ghost"})
        finally:
            if old_env is None:
                os.environ.pop("NOVA_MODELS_DIR", None)
            else:
                os.environ["NOVA_MODELS_DIR"] = old_env


# ----------------------------------------------------------- photo
class TestPhotoModelResolution(TempRootCase):
    def test_resolve_photo_model_from_local_photo(self):
        (self.root / "photo" / "v1-5.safetensors").write_bytes(b"0" * 4096)
        from nova_modules import photo
        self.assertEqual(photo._resolve_photo_model(self.ws, "file:v1-5"),
                         "v1-5.safetensors")
        self.assertEqual(photo._resolve_photo_model(self.ws, "v1-5.safetensors"),
                         "v1-5.safetensors")
        self.assertIsNone(photo._resolve_photo_model(self.ws, "ghost"))
        self.assertIsNone(photo._resolve_photo_model(self.ws, "/abs/path.bin"))


# ----------------------------------------------------------- flow file brain
class TestFlowFileBrain(TempRootCase):
    def test_unknown_file_raises_clean(self):
        from nova_modules import flow
        with self.assertRaises(ModuleError):
            flow._file_chat_fn(self.ws, "file:ghost")

    def test_not_runnable_raises_clean(self):
        from nova_modules import flow
        (self.root / "photo" / "art.safetensors").write_bytes(b"0" * 4096)
        with self.assertRaises(ModuleError) as cm:
            flow._file_chat_fn(self.ws, "file:art")
        self.assertIn("not a runnable", str(cm.exception))

    def test_ollama_import_route(self):
        from nova_modules import flow
        (self.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        import nova
        import nova_modules.flow as fl
        orig_import = nova.import_gguf_to_ollama
        orig_chat = fl._ollama_chat
        seen = {}
        try:
            nova.import_gguf_to_ollama = lambda entry, ws=None, quiet=False: \
                "local-coder-abc123"

            def fake_chat(model, msgs, **kw):
                seen["model"] = model
                return "OK"

            fl._ollama_chat = fake_chat
            chat = flow._file_chat_fn(self.ws, "file:coder")
            self.assertEqual(chat("sys", "hi"), "OK")
            self.assertEqual(seen["model"], "local-coder-abc123")
        finally:
            nova.import_gguf_to_ollama = orig_import
            fl._ollama_chat = orig_chat

    def test_llama_server_fallback(self):
        from nova_modules import flow
        (self.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        import nova
        import nova_localmodels as lm
        import nova_modules.flow as fl
        orig_import = nova.import_gguf_to_ollama
        orig_start = lm.start_llama_server
        orig_chat = fl._openai_chat
        seen = {}
        try:
            nova.import_gguf_to_ollama = lambda entry, ws=None, quiet=False: None
            lm.start_llama_server = lambda path, **kw: \
                {"base": "http://127.0.0.1:9999/v1", "port": 9999}

            def fake_chat(base, model, key, msgs, **kw):
                seen["base"] = base
                return "HEY"

            fl._openai_chat = fake_chat
            chat = flow._file_chat_fn(self.ws, "file:coder")
            self.assertEqual(chat("", "yo"), "HEY")
            self.assertEqual(seen["base"], "http://127.0.0.1:9999/v1")
        finally:
            nova.import_gguf_to_ollama = orig_import
            lm.start_llama_server = orig_start
            fl._openai_chat = orig_chat

    def test_both_routes_dead_gives_one_clean_error(self):
        from nova_modules import flow
        (self.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        import nova
        import nova_localmodels as lm
        orig_import = nova.import_gguf_to_ollama
        orig_start = lm.start_llama_server
        try:
            nova.import_gguf_to_ollama = lambda entry, ws=None, quiet=False: None
            def boom(path, **kw):
                raise lm.LocalModelError("llama-server not found")
            lm.start_llama_server = boom
            with self.assertRaises(ModuleError) as cm:
                flow._file_chat_fn(self.ws, "file:coder")
            self.assertIn("llama-server not found", str(cm.exception))
        finally:
            nova.import_gguf_to_ollama = orig_import
            lm.start_llama_server = orig_start

    def test_default_chat_fn_routes_file_backend(self):
        from nova_modules import flow
        (self.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        import nova
        import nova_modules.flow as fl
        orig_import = nova.import_gguf_to_ollama
        orig_chat = fl._ollama_chat
        try:
            nova.import_gguf_to_ollama = lambda entry, ws=None, quiet=False: \
                "local-coder-abc123"
            fl._ollama_chat = lambda model, msgs, **kw: "OK"
            chat = flow._default_chat_fn(
                self.ws, {"backend": "file", "model": "file:coder"})
            self.assertEqual(chat("", "hi"), "OK")
        finally:
            nova.import_gguf_to_ollama = orig_import
            fl._ollama_chat = orig_chat


# ----------------------------------------------------------- platforms
class TestPlatformPresets(unittest.TestCase):
    def test_ten_presets_all_valid(self):
        self.assertGreaterEqual(len(platforms.PRESETS), 10)
        names = set()
        for p in platforms.PRESETS:
            self.assertTrue(platforms.clean_name(p["name"]))
            self.assertTrue(platforms.clean_base(p["base"]))
            self.assertTrue(p["base"].endswith("/v1"))
            names.add(p["name"])
        for expected in ("localai", "shimmy", "lmstudio", "vllm", "llamacpp",
                         "ollama-openai", "koboldcpp", "tgwebui", "jan",
                         "gpt4all"):
            self.assertIn(expected, names)

    def test_scan_threads_presets_through(self):
        results = platforms.scan(prober=lambda p: {"ok": True, "models": ["m"]})
        self.assertEqual(len(results), len(platforms.PRESETS))
        self.assertTrue(all(r["ok"] and r["models"] == ["m"] for r in results))


# ----------------------------------------------------------- web surface
class TestModelsAllWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_web61_"))
        cls.root = Path(tempfile.mkdtemp(prefix="nova_web61m_"))
        (cls.root / "code").mkdir()
        (cls.root / "code" / "coder.gguf").write_bytes(gguf_bytes())
        (cls.root / "voice").mkdir()
        (cls.root / "voice" / "fa.onnx").write_bytes(b"0" * 4096)
        cls.old_env = os.environ.get("NOVA_MODELS_DIR")
        os.environ["NOVA_MODELS_DIR"] = str(cls.root)
        import web_server
        import nova
        web_server.nova = nova
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        cls.httpd = web_server._make_server(args)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if cls.old_env is None:
            os.environ.pop("NOVA_MODELS_DIR", None)
        else:
            os.environ["NOVA_MODELS_DIR"] = cls.old_env

    def get(self, path):
        req = urllib.request.Request(self.base + path,
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def test_models_all_has_categories_and_folders(self):
        data = self.get("/api/models_all")
        self.assertIn("by_category", data)
        self.assertIn("folders", data)
        self.assertIn("categories", data)
        self.assertEqual(data["by_category"]["code"][0]["name"], "coder")
        self.assertEqual(data["by_category"]["voice"][0]["name"], "fa")
        self.assertEqual(data["by_category"]["voice"][0]["format"], "onnx")
        labels = [f["label"] for f in data["folders"]]
        self.assertIn("local", labels)
        # runnable files list still works (onnx excluded, gguf included)
        names = [f["name"] for f in data["files"]]
        self.assertIn("coder", names)
        self.assertNotIn("fa", names)

    def test_modules_endpoint_voice_backends(self):
        data = self.get("/api/modules")
        voice_row = [m for m in data["modules"] if m["id"] == "voice"][0]
        for b in ("offline", "openai_compat", "xtts", "coqui", "bark", "piper"):
            self.assertIn(b, voice_row["backends"])


if __name__ == "__main__":
    unittest.main()
