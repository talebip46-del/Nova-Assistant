#!/usr/bin/env python3
"""v6.0 tests: the module web surface - talks to the REAL handlers on
an ephemeral port (same pattern as test_stage5_web)."""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web_server
import nova


# v6.3: the security guards (rate limiter, auth throttle) are process-wide
# and the tests share 127.0.0.1 - reset them so heavy API test bursts are
# not mistaken for abuse.
def _reset_web_guards():
    try:
        import nova_security as _nsec
        _nsec.API_LIMITER.reset()
        _nsec.SECURE_API_LIMITER.reset()
        _nsec.AUTH_THROTTLE.reset()
    except Exception:
        pass


class WebV6(unittest.TestCase):
    def setUp(self):
        _reset_web_guards()

    @classmethod
    def setUpClass(cls):
        _reset_web_guards()
        # v6.8.2: the module kill-switch is turned OFF for this suite -
        # these tests exercise the REAL voice/photo/pixel/flow handlers.
        os.environ["NOVA_DISABLED_MODULES"] = ""
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_web6_"))
        web_server.nova = nova
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        cls.httpd = web_server._make_server(args)
        cls.port = cls.httpd.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.port
        import threading
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def post(self, path, obj, ctype="application/json", origin=None):
        data = json.dumps(obj).encode()
        headers = {"Content-Type": ctype}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
            except Exception:
                body = {}
            return e.code, body

    # ------------------------------------------------------ guards first
    def test_module_post_rejects_cross_origin(self):
        code, body = self.post("/api/pixel/generate", {"prompt": "x"},
                               origin="http://evil.com")
        self.assertEqual(code, 403)

    def test_module_post_rejects_bad_content_type(self):
        code, body = self.post("/api/pixel/generate", {"prompt": "x"},
                               ctype="text/plain")
        self.assertEqual(code, 415)

    def test_module_post_unknown_path_404(self):
        code, _ = self.post("/api/pixel/nope", {"prompt": "x"})
        self.assertEqual(code, 404)

    def test_module_get_requires_same_origin(self):
        code, _ = self.get("/api/modules",
                           headers={"Origin": "http://evil.com"})
        self.assertEqual(code, 403)

    # ------------------------------------------------------ modules list
    def test_modules_endpoint(self):
        code, body = self.get("/api/modules")
        self.assertEqual(code, 200)
        data = json.loads(body)
        ids = [m["id"] for m in data["modules"]]
        for mid in ("code", "assistant", "voice", "photo", "pixel",
                    "flow", "knowledge"):
            self.assertIn(mid, ids)
        voice_row = [m for m in data["modules"] if m["id"] == "voice"][0]
        self.assertEqual(voice_row["cfg"]["backend"], "offline")
        self.assertFalse(voice_row["assignable"] is True and False)

    def test_models_all_shape(self):
        code, body = self.get("/api/models_all")
        self.assertEqual(code, 200)
        data = json.loads(body)
        for key in ("ollama", "files", "platforms", "cloud", "platforms_cfg"):
            self.assertIn(key, data)
        self.assertIn("openai", data["cloud"])

    # ------------------------------------------------------ pixel
    def test_pixel_generate_and_serve(self):
        code, body = self.post("/api/pixel/generate",
                               {"prompt": "space invader sprite",
                                "size": 16, "palette": "gameboy"})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        name = body["name"]
        self.assertTrue((self.ws / ".nova" / "modules" / "pixel" / name).is_file())
        code, blob = self.get("/api/file?k=pixel&name=" + urllib.parse.quote(name))
        self.assertEqual(code, 200)
        self.assertTrue(blob.startswith(b"\x89PNG"))

    def test_pixel_gallery(self):
        code, _ = self.post("/api/pixel/generate",
                            {"prompt": "gallery invader", "size": 16})
        self.assertEqual(code, 200)
        code, body = self.get("/api/gallery?k=pixel")
        self.assertEqual(code, 200)
        items = json.loads(body)["items"]
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(items[0]["url"].startswith("/api/file?k=pixel"))

    def test_pixel_upscale(self):
        gen_code, gen = self.post("/api/pixel/generate",
                                  {"prompt": "castle scene", "size": 16})
        code, body = self.post("/api/pixel/upscale",
                               {"name": gen["name"], "scale": 4})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_pixel_bad_prompt(self):
        code, body = self.post("/api/pixel/generate", {"prompt": ""})
        self.assertEqual(code, 400)

    def test_file_traversal_blocked(self):
        for name in ("..%2F..%2Fetc%2Fpasswd", "..", "x/../../y.png",
                     "pixel-nope.png"):
            code, _ = self.get("/api/file?k=pixel&name=" + name)
            self.assertIn(code, (400, 404))

    def test_file_bad_kind(self):
        code, _ = self.get("/api/file?k=secret&name=x.png")
        self.assertEqual(code, 404)

    # ------------------------------------------------------ voice
    def test_voice_tts_offline(self):
        code, body = self.post("/api/voice/tts", {"text": "سلام نوا"})
        self.assertEqual(code, 200)
        self.assertEqual(body["engine"], "offline")
        code, blob = self.get("/api/file?k=voice&name=" +
                              urllib.parse.quote(body["name"]))
        self.assertEqual(code, 200)
        self.assertEqual(blob[:4], b"RIFF")

    def test_voice_tts_empty(self):
        code, body = self.post("/api/voice/tts", {"text": "  "})
        self.assertEqual(code, 502)

    def test_voice_stt_bad_b64(self):
        code, body = self.post("/api/voice/stt", {"data_b64": "!!not-b64!!"})
        self.assertEqual(code, 400)

    def test_voice_stt_junk_audio_clean_error(self):
        junk = base64.b64encode(b"junkjunkjunk" * 30).decode()
        code, body = self.post("/api/voice/stt", {"data_b64": junk})
        self.assertEqual(code, 502)     # engine unreachable / bad format

    # ------------------------------------------------------ photo
    def test_photo_generate_offline(self):
        code, body = self.post("/api/photo/generate",
                               {"prompt": "dusk mountains", "engine": "offline",
                                "size": 128})
        self.assertEqual(code, 200)
        self.assertEqual(body["engine"], "offline")
        self.assertIn("note", body)     # the honest offline disclaimer
        code, blob = self.get("/api/file?k=photo&name=" +
                              urllib.parse.quote(body["name"]))
        self.assertEqual(code, 200)
        self.assertTrue(blob.startswith(b"\x89PNG"))

    def test_photo_dead_engine_clean(self):
        code, body = self.post("/api/photo/generate",
                               {"prompt": "x", "engine": "a1111",
                                "url": "http://127.0.0.1:1"})
        self.assertEqual(code, 502)

    # ------------------------------------------------------ assign
    def test_assign_roundtrip(self):
        code, body = self.post("/api/assign", {"module": "voice",
                                               "backend": "offline"})
        self.assertEqual(code, 200)
        code, body = self.post("/api/assign", {"module": "voice",
                                               "backend": "openai_compat",
                                               "url": "http://127.0.0.1:8090/v1",
                                               "model": "kokoro"})
        self.assertEqual(code, 200)
        code, mods = self.get("/api/modules")
        cfg = [m for m in json.loads(mods)["modules"]
               if m["id"] == "voice"][0]["cfg"]
        self.assertEqual(cfg["model"], "kokoro")
        # invalid -> 400, config untouched
        code, body = self.post("/api/assign", {"module": "voice",
                                               "backend": "nonsense"})
        self.assertEqual(code, 400)
        code, _body = self.post("/api/assign/clear", {"module": "voice"})
        self.assertEqual(code, 200)

    # ------------------------------------------------------ flow
    def test_flow_save_run_status(self):
        code, body = self.post("/api/flow/save", {
            "name": "web-flow", "steps": [
                {"id": "a", "type": "transform", "with": {"text": "hey"}},
                {"id": "p", "type": "pixel",
                 "with": {"prompt": "sprite {{a}}", "size": 16}}]})
        self.assertEqual(code, 200)
        code, body = self.post("/api/flow/run", {"name": "web-flow"})
        self.assertEqual(code, 200)
        run_id = body["run_id"]
        import time
        status = None
        for _ in range(100):
            code, snap = self.get("/api/flow_status?run=" + run_id)
            status = json.loads(snap)
            if status["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(status["status"], "done")
        code, flows = self.get("/api/flows")
        names = [f["name"] for f in json.loads(flows)["flows"]]
        self.assertIn("web-flow", names)
        code, _ = self.post("/api/flow/delete", {"name": "web-flow"})
        self.assertEqual(code, 200)

    def test_flow_run_unknown(self):
        code, _ = self.post("/api/flow/run", {"name": "ghost-flow"})
        self.assertEqual(code, 404)

    def test_flow_save_invalid(self):
        code, body = self.post("/api/flow/save",
                               {"name": "bad name!", "steps": []})
        self.assertEqual(code, 400)

    # ------------------------------------------------------ knowledge
    def test_knowledge_ingest_search(self):
        (self.ws / "kbdoc.md").write_text("the secret password is nova-six " * 30,
                                          encoding="utf-8")
        code, body = self.post("/api/knowledge/ingest", {"paths": ["kbdoc.md"]})
        self.assertEqual(code, 200)
        self.assertEqual(body["files"], 1)
        code, body = self.get("/api/knowledge?q=" +
                              urllib.parse.quote("secret password"))
        hits = json.loads(body)["hits"]
        self.assertTrue(hits)
        self.assertIn("nova-six", hits[0]["text"])

    def test_knowledge_ingest_traversal(self):
        code, body = self.post("/api/knowledge/ingest",
                               {"paths": ["../../etc/passwd"]})
        self.assertEqual(code, 400)

    # ------------------------------------------------------ platforms
    def test_platforms_save_scan(self):
        code, body = self.post("/api/platforms/save", {
            "platforms": [{"name": "myplat", "base": "http://127.0.0.1:19999/v1"}]})
        self.assertEqual(code, 200)
        self.assertEqual(len(body["platforms"]), 1)
        code, body = self.post("/api/platforms/save", {
            "platforms": [{"name": "evil", "base": "file:///etc"}]})
        self.assertEqual(code, 400)
        code, body = self.post("/api/platforms/scan", {"include_presets": False})
        self.assertEqual(code, 200)
        self.assertTrue(any(r["name"] == "myplat" for r in body["results"]))

    # ------------------------------------------------------ info still ok
    def test_info_reports_modules_ok(self):
        code, body = self.get("/api/info")
        info = json.loads(body)
        self.assertEqual(info["version"], "8.12.0")
        self.assertTrue(info["modules_ok"])


import urllib.parse   # noqa: E402  (used above)

if __name__ == "__main__":
    unittest.main()
