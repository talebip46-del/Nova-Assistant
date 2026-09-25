#!/usr/bin/env python3
"""v6.0 tests: platform discovery (LocalAI / Shimmy / LM Studio / vLLM /
llama.cpp - all via the OpenAI-compatible /v1/models probe)."""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_platforms as platforms


class _FakeOpenAI(BaseHTTPRequestHandler):
    models = {"data": [{"id": "llama-3"}, {"id": "qwen2.5-coder"}]}

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            body = json.dumps(self.models).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


class TestParsers(unittest.TestCase):
    def test_openai_shape(self):
        self.assertEqual(
            platforms.parse_models_payload({"data": [{"id": "b"}, {"id": "a"}]}),
            ["b", "a"])

    def test_bare_list_and_junk(self):
        self.assertEqual(platforms.parse_models_payload(["x", 5, None, {"id": "y"}]),
                         ["x", "y"])
        self.assertEqual(platforms.parse_models_payload({"models": ["m1"]}), ["m1"])
        self.assertEqual(platforms.parse_models_payload(None), [])
        self.assertEqual(platforms.parse_models_payload("nope"), [])
        self.assertEqual(platforms.parse_models_payload({"data": "junk"}), [])

    def test_dupes_and_len(self):
        out = platforms.parse_models_payload({"data": [{"id": "a"}, {"id": "a"},
                                                       {"id": "x" * 300}]})
        self.assertEqual(out, ["a"])

    def test_clean_base(self):
        self.assertEqual(platforms.clean_base("http://127.0.0.1:8080/v1/"),
                         "http://127.0.0.1:8080/v1")
        for bad in ("file:///etc/passwd", "ftp://x", "http://x y", "",
                    None, "javascript:alert(1)", 123):
            self.assertEqual(platforms.clean_base(bad), "")

    def test_clean_name(self):
        self.assertEqual(platforms.clean_name(" my local-ai "), "my local-ai")
        self.assertEqual(platforms.clean_name(""), "")
        self.assertEqual(platforms.clean_name("x" * 100), "")
        self.assertEqual(platforms.clean_name(5), "")

    def test_normalize(self):
        self.assertEqual(platforms.normalize_platform({"name": "n", "base": "http://x/v1"}),
                         {"name": "n", "base": "http://x/v1"})
        self.assertIsNone(platforms.normalize_platform({"name": "n"}))
        self.assertIsNone(platforms.normalize_platform("nope"))


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_plat_"))

    def test_save_load_roundtrip(self):
        saved = platforms.save_config(self.ws, [
            {"name": "localai", "base": "http://127.0.0.1:8080/v1"},
            {"name": "junk", "base": "gopher://x"},
            {"name": "localai", "base": "http://127.0.0.1:8080/v1"},   # dupe
        ])
        self.assertEqual(len(saved), 1)
        self.assertEqual(platforms.load_config(self.ws), saved)

    def test_save_rejects_all_junk(self):
        with self.assertRaises(platforms.PlatformError):
            platforms.save_config(self.ws, [{"name": "junk", "base": "nope"}])
        with self.assertRaises(platforms.PlatformError):
            platforms.save_config(self.ws, "not-a-list")

    def test_env_platforms(self):
        os.environ["NOVA_PLATFORMS"] = "a@http://h1:1/v1, junk@nope, b@http://h2:2/v1"
        try:
            names = [p["name"] for p in platforms.env_platforms()]
            self.assertEqual(names, ["a", "b"])
        finally:
            del os.environ["NOVA_PLATFORMS"]

    def test_all_platforms_dedupe(self):
        os.environ["NOVA_PLATFORMS"] = "a@http://h1:1/v1"
        try:
            platforms.save_config(self.ws, [{"name": "a2", "base": "http://h1:1/v1"}])
            merged = platforms.all_platforms(self.ws)
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["name"], "a")
        finally:
            del os.environ["NOVA_PLATFORMS"]

    def test_load_tolerates_corrupt(self):
        (self.ws / ".nova").mkdir()
        (self.ws / ".nova" / "platforms.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(platforms.load_config(self.ws), [])


class TestProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
        cls.port = cls.httpd.server_address[1]
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_probe_live(self):
        r = platforms.probe("http://127.0.0.1:%d/v1" % self.port, timeout=3)
        self.assertTrue(r["ok"])
        self.assertEqual(r["models"], ["llama-3", "qwen2.5-coder"])

    def test_probe_dead(self):
        r = platforms.probe("http://127.0.0.1:1/v1", timeout=1.5)
        self.assertFalse(r["ok"])
        self.assertTrue(r["note"])

    def test_probe_bad_url(self):
        r = platforms.probe("file:///etc")
        self.assertFalse(r["ok"])

    def test_scan_with_fake_prober(self):
        def prober(p):
            if p["base"].endswith("8081/v1"):
                return {"ok": True, "models": ["m1"]}
            return {"ok": False, "note": "dead"}
        results = platforms.scan(prober=prober)
        by_name = {r["name"]: r for r in results}
        self.assertTrue(by_name["llamacpp"]["ok"])
        self.assertEqual(by_name["llamacpp"]["models"], ["m1"])
        self.assertFalse(by_name["localai"]["ok"])

    def test_models_by_platform(self):
        out = platforms.models_by_platform([
            {"name": "a", "ok": True, "models": ["m"]},
            {"name": "b", "ok": False, "models": []}])
        self.assertEqual(list(out.keys()), ["a|"])


if __name__ == "__main__":
    unittest.main()
