#!/usr/bin/env python3
"""v6.0 tests: the module layer - nova_png, PixelArt, Voice (offline),
Photo (offline), Knowledge, per-module assignment."""
import io
import json
import struct
import sys
import tempfile
import unittest
import wave
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_png
from nova_modules import assign, knowledge, photo, pixelart, voice
from nova_modules import ModuleError, spec, module_data_dir


def decode_png_dims(blob):
    """Parse OUR pngs back: (w, h) via IHDR + verify IDAT inflates."""
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", blob[16:24])
    # find IDAT and inflate it
    off = 8
    idat = b""
    while off < len(blob):
        ln = struct.unpack(">I", blob[off:off + 4])[0]
        typ = blob[off + 4:off + 8]
        data = blob[off + 8:off + 8 + ln]
        if typ == b"IDAT":
            idat += data
        off += 12 + ln
    raw = zlib.decompress(idat)
    assert len(raw) == h * (1 + w * 3)
    return w, h


class TestPngWriter(unittest.TestCase):
    def test_encode_roundtrip(self):
        rows = [b"\x00" + bytes([(y * 10) % 256, 30, 40]) * 4 for y in range(4)]
        blob = nova_png.encode_png(4, 4, rows)
        self.assertEqual(decode_png_dims(blob), (4, 4))

    def test_rejects_bad_rows(self):
        with self.assertRaises(ValueError):
            nova_png.encode_png(4, 4, [b"\x00" + b"\x01" * 11])   # missing row
        with self.assertRaises(ValueError):
            nova_png.encode_png(4, 4, [b"\x01" + b"\x00" * 12])   # filter != 0
        with self.assertRaises(ValueError):
            nova_png.encode_png(0, 0, [])

    def test_write_png_atomic(self):
        ws = Path(tempfile.mkdtemp())
        p = ws / "sub" / "x.png"
        n = nova_png.write_png(str(p), 2, 2,
                               [b"\x00" + b"\x00\x00\x00" * 2] * 2)
        self.assertGreater(n, 0)
        self.assertTrue(p.is_file())
        self.assertFalse(Path(str(p) + ".part").exists())
        self.assertEqual(nova_png.read_png_meta(str(p)),
                         {"width": 2, "height": 2, "alpha": False})

    def test_read_png_meta_junk(self):
        self.assertIsNone(nova_png.read_png_meta("/nonexistent/x.png"))


class TestPixelArt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_px_"))

    def test_deterministic(self):
        a = pixelart.generate(self.ws, "space invader", size=16, seed="7")
        b = pixelart.generate(self.ws, "space invader", size=16, seed="7")
        self.assertEqual(Path(a["path"]).read_bytes(), Path(b["path"]).read_bytes())

    def test_subjects_and_palettes(self):
        for prompt in ("sunset mountain scene", "castle", "rocket launch",
                       "cat creature", "ocean waves", "forest tree",
                       "portrait face", "abstract fire"):
            r = pixelart.generate(self.ws, prompt, size=16)
            self.assertTrue(Path(r["path"]).is_file())
            self.assertTrue(Path(r["path"]).suffix == ".png")

    def test_explicit_palette(self):
        r = pixelart.generate(self.ws, "sprite", palette="gameboy", size=16)
        self.assertEqual(r["plan"]["palette"], "gameboy")

    def test_grid_json_saved(self):
        r = pixelart.generate(self.ws, "invader sprite", size=16)
        js = Path(r["path"]).with_suffix(".json")
        self.assertTrue(js.is_file())
        data = json.loads(js.read_text(encoding="utf-8"))
        self.assertEqual(len(data["grid"]), 16)

    def test_upscale(self):
        r = pixelart.generate(self.ws, "sprite", size=16, scale=2)
        path, size_b = pixelart.render_from_grid(self.ws, r["name"], 4)
        meta = nova_png.read_png_meta(path)
        self.assertEqual((meta["width"], meta["height"]), (64, 64))
        with self.assertRaises(ModuleError):
            pixelart.render_from_grid(self.ws, "no-such-grid", 4)
        with self.assertRaises(ModuleError):
            pixelart.render_from_grid(self.ws, r["name"], 999)

    def test_bad_params(self):
        with self.assertRaises(ModuleError):
            pixelart.generate(self.ws, "x", size=4)          # too small
        with self.assertRaises(ModuleError):
            pixelart.generate(self.ws, "x", size=99999)      # too big

    def test_gallery(self):
        for prompt in ("gallery invader", "gallery castle", "gallery rocket"):
            pixelart.generate(self.ws, prompt, size=16)
        items = pixelart.list_gallery(self.ws)
        self.assertGreaterEqual(len(items), 3)
        self.assertLessEqual(len(items), 60)


class TestVoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_vc_"))

    def test_offline_wav(self):
        r = voice.synthesize(self.ws, "سلام نوا", {"backend": "offline"})
        self.assertEqual(r["fmt"], "wav")
        raw = Path(r["path"]).read_bytes()
        self.assertEqual(raw[:4], b"RIFF")
        with wave.open(io.BytesIO(raw)) as w:
            self.assertEqual(w.getframerate(), 22050)
            self.assertGreater(w.getnframes(), 2000)

    def test_validation(self):
        with self.assertRaises(ModuleError):
            voice.synthesize(self.ws, "", {"backend": "offline"})
        with self.assertRaises(ModuleError):
            voice.synthesize(self.ws, "x" * 6000, {"backend": "offline"})
        with self.assertRaises(ModuleError):
            voice.synthesize(self.ws, "hi", {"backend": "nope"})

    def test_http_engine_errors_are_clean(self):
        with self.assertRaises(ModuleError) as cm:
            voice.synthesize(self.ws, "hi", {"backend": "openai_compat",
                                             "url": "file:///x"})
        self.assertIn("URL", str(cm.exception))
        with self.assertRaises(ModuleError):
            voice.synthesize(self.ws, "hi", {"backend": "openai_compat",
                                             "url": "http://127.0.0.1:1/v1"})
        with self.assertRaises(ModuleError):
            voice.synthesize(self.ws, "hi", {"backend": "piper"})   # no model

    def test_sniff_format(self):
        self.assertEqual(voice.sniff_format(b"RIFF1234WAVE"), "wav")
        self.assertEqual(voice.sniff_format(b"ID3\x04"), "mp3")
        self.assertEqual(voice.sniff_format(b"OggS"), "ogg")
        self.assertEqual(voice.sniff_format(b"\x00\x00"), "bin")

    def test_wav_info(self):
        raw = voice.tts_offline(None, "x")[0]
        info = voice.wav_info(raw)
        self.assertIsNotNone(info)
        self.assertGreater(info["seconds"], 0.5)
        self.assertIsNone(voice.wav_info(b"notawav" * 20))

    def test_transcribe_validation(self):
        with self.assertRaises(ModuleError):
            voice.transcribe(self.ws, b"\x00" * 50)            # too small
        with self.assertRaises(ModuleError):
            voice.transcribe(self.ws, b"\x00" * 20_000_000)    # too big
        with self.assertRaises(ModuleError):
            voice.transcribe(self.ws, b"junkjunkjunk" * 20)    # bad format

    def test_history(self):
        voice.synthesize(self.ws, "دو", {"backend": "offline"})
        voice.synthesize(self.ws, "سه", {"backend": "offline"})
        items = voice.list_history(self.ws)
        self.assertGreaterEqual(len(items), 2)


class TestPhotoOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_ph_"))

    def test_offline_deterministic_and_valid_png(self):
        a = photo.generate(self.ws, "a lonely mountain at dusk", engine="offline")
        b = photo.generate(self.ws, "a lonely mountain at dusk", engine="offline")
        self.assertEqual(Path(a["path"]).read_bytes(), Path(b["path"]).read_bytes())
        w, h = decode_png_dims(Path(a["path"]).read_bytes())
        self.assertEqual((w, h), (512, 512))

    def test_unknown_engine(self):
        with self.assertRaises(ModuleError):
            photo.generate(self.ws, "x", engine="nope")
        with self.assertRaises(ModuleError):
            photo.generate(self.ws, "")

    def test_a1111_clean_error_on_dead(self):
        with self.assertRaises(ModuleError):
            photo.generate(self.ws, "x", cfg={"backend": "a1111",
                                              "url": "http://127.0.0.1:1"}, engine="a1111")

    def test_gallery(self):
        photo.generate(self.ws, "golden valley", engine="offline")
        photo.generate(self.ws, "blue ocean", engine="offline")
        self.assertGreaterEqual(len(photo.list_gallery(self.ws)), 2)


class TestKnowledge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_kb_"))
        (cls.ws / "docs").mkdir()
        (cls.ws / "docs" / "a.md").write_text(
            "نوا یک دستیار لوکال است.\n\n" + "Nova runs local models. " * 40,
            encoding="utf-8")
        (cls.ws / "docs" / "b.py").write_text("def hello():\n    return 'nova'\n" * 60,
                                              encoding="utf-8")

    def test_ingest_and_search(self):
        r = knowledge.ingest(self.ws, ["docs/a.md", "docs/b.py"])
        self.assertEqual(r["files"], 2)
        hits = knowledge.search(self.ws, "دستیار لوکال")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["doc"], str(Path("docs") / "a.md"))

    def test_unchanged_reingest_keeps_chunks(self):
        before = knowledge.stats(self.ws)["chunks"]
        r = knowledge.ingest(self.ws, ["docs/a.md", "docs/b.py"])
        self.assertEqual(r["chunks"], 0)                     # nothing new
        self.assertEqual(knowledge.stats(self.ws)["chunks"], before)

    def test_changed_doc_rechunks(self):
        import os
        p = self.ws / "docs" / "c.txt"
        p.write_text("word " * 50, encoding="utf-8")
        knowledge.ingest(self.ws, ["docs/c.txt"])
        n1 = knowledge.stats(self.ws)["chunks"]
        p.write_text("totally different nova content " * 50, encoding="utf-8")
        st = p.stat()
        os.utime(p, (st.st_atime + 10, st.st_mtime + 10))   # force new mtime
        knowledge.ingest(self.ws, ["docs/c.txt"])
        self.assertGreater(knowledge.stats(self.ws)["chunks"], n1)

    def test_traversal_blocked(self):
        with self.assertRaises(ModuleError):
            knowledge.ingest(self.ws, ["../../etc/passwd"])
        with self.assertRaises(ModuleError):
            knowledge.ingest(self.ws, ["/etc/passwd"])

    def test_search_empty_state(self):
        ws2 = Path(tempfile.mkdtemp())
        self.assertEqual(knowledge.search(ws2, "anything"), [])
        self.assertEqual(knowledge.context(ws2, "anything"), "")

    def test_context_and_reset(self):
        knowledge.ingest(self.ws, ["docs/a.md"])       # self-sufficient
        c = knowledge.context(self.ws, "local models", budget=900)
        self.assertIn("src:", c)
        st = knowledge.stats(self.ws)
        self.assertGreater(st["docs"], 0)
        knowledge.reset(self.ws)
        self.assertEqual(knowledge.stats(self.ws)["chunks"], 0)


class TestAssign(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_as_"))

    def test_defaults(self):
        self.assertEqual(assign.resolve(self.ws, "voice")["backend"], "offline")
        self.assertEqual(assign.resolve(self.ws, "pixel")["backend"], "offline")
        self.assertEqual(assign.resolve(self.ws, "nope"), {})

    def test_save_and_persist(self):
        assign.save_module(self.ws, "photo", {"backend": "a1111"})
        assign.save_module(self.ws, "voice", {"backend": "openai_compat",
                                              "url": "http://127.0.0.1:9000/v1",
                                              "model": "kokoro"})
        self.assertEqual(assign.resolve(self.ws, "photo")["url"],
                         "http://127.0.0.1:7860")            # default injected
        self.assertEqual(assign.resolve(self.ws, "voice")["model"], "kokoro")
        # a NEW resolve on the same ws must see the persisted file
        self.assertEqual(assign.load_all(self.ws)["voice"]["backend"],
                         "openai_compat")

    def test_rejections(self):
        with self.assertRaises(ModuleError):
            assign.save_module(self.ws, "nope", {"backend": "offline"})
        with self.assertRaises(ModuleError):
            assign.save_module(self.ws, "pixel", {"backend": "a1111"})   # not allowed
        with self.assertRaises(ModuleError):
            assign.save_module(self.ws, "voice", {"backend": "openai_compat"})  # no url
        with self.assertRaises(ModuleError):
            assign.save_module(self.ws, "voice", {"backend": "ollama"})  # no model

    def test_injection_resistance(self):
        assign.save_module(self.ws, "voice", {
            "backend": "offline", "model": "x\nDROP", "url": "javascript:alert(1)"})
        cfg = assign.resolve(self.ws, "voice")
        self.assertNotIn("model", cfg)        # junk dropped
        self.assertNotIn("url", cfg)

    def test_clear(self):
        assign.save_module(self.ws, "voice", {"backend": "offline"})
        self.assertTrue(assign.clear_module(self.ws, "voice"))
        self.assertFalse(assign.clear_module(self.ws, "voice"))
        self.assertEqual(assign.resolve(self.ws, "voice")["backend"], "offline")

    def test_registry_sanity(self):
        ids = set()
        for m in __import__("nova_modules").MODULES:
            ids.add(m["id"])
            self.assertIsInstance(m["backends"], list)
            self.assertTrue(spec(m["id"]) is not None)
        self.assertIn("code", ids)
        self.assertIn("flow", ids)


if __name__ == "__main__":
    unittest.main()
