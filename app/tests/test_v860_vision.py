#!/usr/bin/env python3
# =====================================================================
#  Nova v8.11.0 "bug net + vision" regression tests:
#   - nova_vision SETTINGS: .nova/vision.json roundtrip + validation
#     (invalid/hand-edited fields never poison), reset, oversize file,
#     enabled() fail-soft, DEFAULTS (approve on / strict off).
#   - nova_vision DETECTION (the 100% automatic ladder):
#     ollama /api/show parse (capabilities / families / projector /
#     honest text-only / unknown shape), the real GGUF header scan
#     (built binaries: vision keys, plain keys, arrays, corrupt,
#     old version), the mmproj sidecar rung, the llamacpp rung, the
#     name-regex LAST rung (honestly labelled), caching per model +
#     clear_cache + the NOVA_VISION_SHOW=0 escape hatch, state_payload.
#   - nova.py GATE: _vision_capability (kind mapping, file: path
#     resolution, fail-soft), _vision_selection_gate (the whole
#     decision matrix: approve-off / cloud / local vision / strict
#     refuse / non-strict pass / broken gate never bricks), the
#     _img_ai_verify prompt override + local-first verdict (mocked
#     ollama round-trips), _img_verify_human (approve-off + its own
#     integrity prompt), the hook installation (AI_GATE_HOOK).
#   - nova.py COMMANDS: /img pick approval (AI rejection is honest,
#     never a silent save), /imgdl human gate, success paths.
#   - nova.py INTEGRATION: version pins, /vision in TOOLS, /status
#     line, web_vision_state shape, web surface pins (web_server
#     vision block + index.html panel ids), cmd wiring source pins.
#  Everything is offline: NOVA_VISION_SHOW=0 is pinned (detection
#  via show is exercised with an injected fake show_fn).
# =====================================================================
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["NOVA_VISION_SHOW"] = "0"      # the suite is offline
os.environ["NOVA_GUARDIAN_WEB"] = "0"

import nova                    # noqa: E402
import nova_think              # noqa: E402
import nova_vision as vis      # noqa: E402

APP = Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _gguf(kv_pairs):
    """A real (tiny) GGUF header builder: magic + v3 header + KVs.
    str values ride type 8 (string), ints ride type 4 (uint32)."""
    buf = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) \
        + struct.pack("<Q", len(kv_pairs))
    for key, val in kv_pairs:
        kb = key.encode("utf-8")
        buf += struct.pack("<Q", len(kb)) + kb
        if isinstance(val, str):
            vb = val.encode("utf-8")
            buf += struct.pack("<I", 8) + struct.pack("<Q", len(vb)) + vb
        else:
            buf += struct.pack("<I", 4) + struct.pack("<I", int(val))
    return buf


# =====================================================================
# 1. settings
# =====================================================================
class TestVisionSettings(unittest.TestCase):
    def setUp(self):
        vis.clear_cache()

    def test_defaults_when_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            st = vis.load_settings(td)
            self.assertTrue(st["approve"])
            self.assertFalse(st["strict"])
            self.assertFalse(st["custom"])

    def test_roundtrip_and_custom_flag(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(vis.save_settings(
                td, {"approve": False, "strict": True}), "")
            st = vis.load_settings(td)
            self.assertFalse(st["approve"])
            self.assertTrue(st["strict"])
            self.assertTrue(st["custom"])
            self.assertTrue((Path(td) / ".nova" / "vision.json").is_file())

    def test_invalid_fields_never_poison(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(vis.save_settings(
                td, {"approve": "yes", "strict": 1, "evil": True}), "")
            st = vis.load_settings(td)
            self.assertTrue(st["approve"])       # the default survived
            self.assertFalse(st["strict"])
            self.assertNotIn("evil", st)

    def test_hand_edited_garbage_means_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".nova" / "vision.json"
            p.parent.mkdir(parents=True)
            p.write_text('{"approve": null, "oops": []}', encoding="utf-8")
            st = vis.load_settings(td)
            self.assertTrue(st["approve"])
            self.assertFalse(st["strict"])

    def test_oversized_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".nova" / "vision.json"
            p.parent.mkdir(parents=True)
            p.write_text("x" * (vis.MAX_SETTINGS_BYTES + 1),
                         encoding="utf-8")
            self.assertFalse(vis.load_settings(td)["custom"])

    def test_reset_removes_the_file(self):
        with tempfile.TemporaryDirectory() as td:
            vis.save_settings(td, {"strict": True})
            self.assertEqual(vis.reset_settings(td), "")
            self.assertFalse(vis.load_settings(td)["custom"])

    def test_enabled_fail_soft(self):
        self.assertTrue(vis.enabled(None, "approve"))
        self.assertTrue(vis.enabled("junk", "approve"))   # the default
        self.assertFalse(vis.enabled({}, "strict"))
        self.assertTrue(vis.enabled({"strict": True}, "strict"))


# =====================================================================
# 2. detection
# =====================================================================
class TestShowParse(unittest.TestCase):
    def test_capabilities_vision_is_the_truth(self):
        self.assertEqual(vis._parse_show(
            {"capabilities": ["completion", "vision"]}),
            (True, "ollama-show", mock.ANY))

    def test_families_clip_projector(self):
        ok, via, _ = vis._parse_show(
            {"details": {"families": ["llama", "clip"]}})
        self.assertTrue(ok)
        self.assertEqual(via, "ollama-families")

    def test_model_info_projector_key(self):
        ok, via, _ = vis._parse_show(
            {"model_info": {"llava.projector.vision": True}})
        self.assertTrue(ok)
        self.assertEqual(via, "ollama-projector")

    def test_successful_show_without_vision_is_text_only(self):
        ok, via, _ = vis._parse_show(
            {"capabilities": ["completion"],
             "details": {"families": ["llama"]},
             "model_info": {"general.architecture": "llama"}})
        self.assertFalse(ok)
        self.assertEqual(via, "ollama-show")

    def test_unknown_shape_keeps_looking(self):
        self.assertIsNone(vis._parse_show({}))
        self.assertIsNone(vis._parse_show("junk"))
        self.assertIsNone(vis._parse_show(None))


class TestGgufScan(unittest.TestCase):
    def test_vision_key_is_true(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.gguf"
            p.write_bytes(_gguf([("general.architecture", "llama"),
                                 ("clip.has_vision_encoder", 1)]))
            self.assertIs(vis._gguf_vision_keys(p), True)

    def test_plain_keys_are_false(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.gguf"
            p.write_bytes(_gguf([("general.architecture", "llama"),
                                 ("general.name", "tiny coder")]))
            self.assertIs(vis._gguf_vision_keys(p), False)

    def test_mmproj_in_a_key_counts(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.gguf"
            p.write_bytes(_gguf([("adapter.mmproj.file", "mmproj.gguf")]))
            self.assertIs(vis._gguf_vision_keys(p), True)

    def test_string_arrays_are_skipped_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.gguf"
            buf = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) \
                + struct.pack("<Q", 1)
            kb = b"tokenizer.tokens"
            buf += struct.pack("<Q", len(kb)) + kb
            buf += struct.pack("<I", 9)          # array
            buf += struct.pack("<I", 8)          # of strings
            buf += struct.pack("<Q", 2)          # count 2
            for s in ("a", "b"):
                buf += struct.pack("<Q", len(s)) + s.encode()
            p.write_bytes(buf)
            self.assertIs(vis._gguf_vision_keys(p), False)

    def test_corrupt_and_non_gguf_are_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.gguf"
            p.write_bytes(b"GGUF" + b"\x03\x00\x00\x00" + b"trunc")
            self.assertIsNone(vis._gguf_vision_keys(p))
            p2 = Path(td) / "nope.bin"
            p2.write_bytes(b"NOTG" + b"\x00" * 32)
            self.assertIsNone(vis._gguf_vision_keys(p2))
            self.assertIsNone(vis._gguf_vision_keys(Path(td) / "ghost"))

    def test_old_version_is_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "v1.gguf"
            p.write_bytes(b"GGUF" + struct.pack("<I", 1) + b"\x00" * 32)
            self.assertIsNone(vis._gguf_vision_keys(p))


class TestDetectionLadder(unittest.TestCase):
    def setUp(self):
        vis.clear_cache()

    def test_name_rung_families(self):
        for name in ("llava:13b", "qwen2-vl", "qwen2.5vl:7b", "gemma3",
                     "moondream", "minicpm-v", "MiniCPM-V", "pixtral",
                     "internvl2", "bakllava", "llama-vision"):
            self.assertTrue(vis.name_looks_vision(name), name)
        for name in ("qwen2.5-coder", "llama3:8b", "mistral", "phi3",
                     "deepseek-coder-v2", ""):
            self.assertFalse(vis.name_looks_vision(name), name)

    def test_show_fn_is_rung_one(self):
        calls = []

        def fake_show(base, model):
            calls.append((base, model))
            return {"capabilities": ["vision"]}

        r = vis.detect("ollama", "my-model:7b", "http://x", None, fake_show)
        self.assertTrue(r["vision"])
        self.assertEqual(r["via"], "ollama-show")
        self.assertEqual(calls, [("http://x", "my-model:7b")])

    def test_successful_show_text_only_beats_a_vision_name(self):
        """A SUCCESSFUL show is THE truth - even llava-named models are
        text-only when ollama says so (renamed models exist)."""
        r = vis.detect("ollama", "llava:7b", "http://x", None,
                       lambda b, m: {"capabilities": ["completion"]})
        self.assertFalse(r["vision"])
        self.assertEqual(r["via"], "ollama-show")

    def test_show_unreachable_falls_to_honest_name(self):
        r = vis.detect("ollama", "llava:7b", "http://x", None,
                       lambda b, m: None)
        self.assertTrue(r["vision"])
        self.assertEqual(r["via"], "name")
        self.assertIn("unreachable", r["detail"])

    def test_show_env_off_skips_the_default_network_call(self):
        """NOVA_VISION_SHOW=0 kills the DEFAULT /api/show path (an
        injected probe still works - it is not the network)."""
        old = os.environ.get("NOVA_VISION_SHOW")
        os.environ["NOVA_VISION_SHOW"] = "0"
        try:
            def boom(base, model):
                raise AssertionError("the default show must be skipped")
            with mock.patch.object(vis, "_show_default", boom):
                r = vis.detect("ollama", "llava:7b", "http://x", None)
        finally:
            if old is None:
                os.environ.pop("NOVA_VISION_SHOW", None)
            else:
                os.environ["NOVA_VISION_SHOW"] = old
        self.assertTrue(r["vision"])
        self.assertEqual(r["via"], "name")

    def test_gguf_rung_for_file_brains(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "coder.gguf"
            p.write_bytes(_gguf([("general.architecture", "llama")]))
            r = vis.detect("ollama", "file:coder.gguf", "http://x", p,
                           lambda b, m: None)
            self.assertFalse(r["vision"])
            self.assertEqual(r["via"], "gguf")
            p2 = Path(td) / "seer.gguf"
            p2.write_bytes(_gguf([("clip.has_vision_encoder", 1)]))
            r2 = vis.detect("ollama", "file:seer.gguf", "http://x", p2,
                            lambda b, m: None)
            self.assertTrue(r2["vision"])
            self.assertEqual(r2["via"], "gguf-keys")

    def test_mmproj_sidecar_rung(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.gguf"
            p.write_bytes(_gguf([("general.architecture", "llama")]))
            (Path(td) / "mmproj-model.gguf").write_bytes(b"GGUF")
            r = vis.detect("ollama", "file:m.gguf", "http://x", p, None)
            self.assertTrue(r["vision"])
            self.assertEqual(r["via"], "mmproj")

    def test_llamacpp_is_text_only_without_mmproj(self):
        r = vis.detect("llamacpp", "qwen2.5", "http://x", None, None)
        self.assertFalse(r["vision"])
        self.assertEqual(r["via"], "llamacpp")
        self.assertIn("--mmproj", r["detail"])

    def test_unknown_kind_still_gets_the_name_rung(self):
        self.assertTrue(vis.detect("?", "some-llava", None, None,
                                   None)["vision"])
        self.assertFalse(vis.detect("?", "phi3", None, None, None)["vision"])

    def test_detection_is_cached_per_model(self):
        calls = []

        def fake_show(base, model):
            calls.append(model)
            return {"capabilities": ["vision"]}

        vis.detect("ollama", "cached:1b", "http://x", None, fake_show)
        vis.detect("ollama", "cached:1b", "http://x", None, fake_show)
        self.assertEqual(len(calls), 1)
        vis.clear_cache()
        vis.detect("ollama", "cached:1b", "http://x", None, fake_show)
        self.assertEqual(len(calls), 2)

    def test_force_bypasses_the_cache(self):
        calls = []

        def fake_show(base, model):
            calls.append(model)
            return {"capabilities": ["vision"]}

        vis.detect("ollama", "forced:1b", "http://x", None, fake_show)
        vis.detect("ollama", "forced:1b", "http://x", None, fake_show,
                   force=True)
        self.assertEqual(len(calls), 2)

    def test_detect_never_raises(self):
        for args in (("", "", None, None, None),
                     ("ollama", None, "http://x", 12345, "junk"),
                     ("weird", object(), object(), object(), None)):
            r = vis.detect(*args)
            self.assertIn("vision", r)

    def test_state_payload_shape(self):
        p = vis.state_payload({"vision": True, "via": "gguf-keys",
                               "detail": "d", "model": "m"},
                              {"approve": False, "strict": True,
                               "custom": True}, model="mm",
                              backend="local")
        for key in ("model", "backend", "vision", "via", "detail",
                    "approve", "strict", "custom", "show_env_off"):
            self.assertIn(key, p)
        self.assertTrue(p["vision"])
        self.assertFalse(p["approve"])
        self.assertTrue(p["strict"])


# =====================================================================
# 3. the nova.py gate + verdict pipeline
# =====================================================================
class TestCapabilityAndGate(unittest.TestCase):
    def setUp(self):
        vis.clear_cache()

    def test_capability_maps_kinds_and_paths(self):
        with mock.patch.object(nova, "lmodels", None), \
             mock.patch.object(vis, "detect",
                               return_value={"vision": True}) as det:
            cap = nova._vision_capability(
                {"kind": "ollama", "model": "llava:7b"}, "llava:7b")
            self.assertTrue(cap["vision"])
            args, kwargs = det.call_args
            self.assertEqual(args[:2], ("ollama", "llava:7b"))
            self.assertIsNone(kwargs.get("path"))
            cap2 = nova._vision_capability(
                {"kind": "llamacpp", "model": "x"}, "x")
            self.assertEqual(det.call_args_list[1][0][:2],
                             ("llamacpp", "x"))
            self.assertTrue(cap2["vision"])

    def test_capability_resolves_file_paths(self):
        entry = {"file": "/models/mini-vl.gguf"}
        with mock.patch.object(nova, "lmodels", mock.Mock()) as lm, \
             mock.patch.object(nova, "_find_local_entry",
                               return_value=entry) as find, \
             mock.patch.object(nova, "_VISION_ACTIVE",
                               {"ws": None, "model": None}), \
             mock.patch.object(vis, "detect",
                               return_value={"vision": True}) as det:
            lm.LOCAL_PREFIX = "file:"
            nova._vision_capability({"kind": "ollama",
                                     "model": "file:mini-vl.gguf"})
            find.assert_called_once_with("file:mini-vl.gguf")
            self.assertEqual(det.call_args[1].get("path"),
                             "/models/mini-vl.gguf")

    def test_capability_prefers_the_active_brain(self):
        # v8.7: with no explicit model argument, the _VISION_ACTIVE
        # tracker (the session's ACTUAL local brain) outranks the
        # provider config's often-empty model field.
        entry = {"file": "/models/mini-vl.gguf"}
        with mock.patch.object(nova, "lmodels", mock.Mock()) as lm, \
             mock.patch.object(nova, "_find_local_entry",
                               return_value=entry) as find, \
             mock.patch.object(nova, "_VISION_ACTIVE",
                               {"ws": None, "model": "file:active.gguf"}), \
             mock.patch.object(vis, "detect",
                               return_value={"vision": True}) as det:
            lm.LOCAL_PREFIX = "file:"
            nova._vision_capability({"kind": "ollama",
                                     "model": "file:stale.gguf"})
            find.assert_called_once_with("file:active.gguf")

    def test_capability_fail_soft_without_the_module(self):
        old = nova.vision
        nova.vision = None
        try:
            cap = nova._vision_capability({"kind": "ollama",
                                           "model": "x"})
            self.assertFalse(cap["vision"])
            self.assertEqual(cap["via"], "missing")
        finally:
            nova.vision = old

    def _gate(self, **patches):
        defaults = {"settings": {}, "cfg": {"kind": "ollama",
                                            "model": "m"},
                    "local": True, "cap": {"vision": False}}
        defaults.update(patches)
        with mock.patch.object(nova, "_vision_settings_now",
                               return_value=defaults["settings"]), \
             mock.patch.object(nova, "_provider_cfg",
                               return_value=defaults["cfg"]), \
             mock.patch.object(nova, "_is_free_local",
                               return_value=defaults["local"]), \
             mock.patch.object(nova, "_vision_capability",
                               return_value=defaults["cap"]):
            return nova._vision_selection_gate("a red rose")

    def test_gate_matrix(self):
        # approve off -> open (the user opted out)
        ok, note = self._gate(settings={"approve": False})
        self.assertTrue(ok)
        self.assertEqual(note, "approval-off")
        # cloud brain -> open (the v8.1 cloud gate verifies)
        ok, note = self._gate(local=False,
                              cfg={"kind": "openai", "model": "gpt"})
        self.assertTrue(ok)
        self.assertEqual(note, "cloud-gate")
        # local brain with vision -> open
        ok, note = self._gate(cap={"vision": True})
        self.assertTrue(ok)
        self.assertEqual(note, "local-vision-on")
        # local text-only + strict -> REFUSE (placeholders only)
        ok, note = self._gate(settings={"strict": True})
        self.assertFalse(ok)
        self.assertIn("cannot see", note)
        # local text-only, not strict -> open with an honest note
        ok, note = self._gate()
        self.assertTrue(ok)
        self.assertEqual(note, "local-text-only")

    def test_broken_gate_never_bricks(self):
        with mock.patch.object(nova, "_vision_settings_now",
                               side_effect=RuntimeError("boom")):
            ok, note = nova._vision_selection_gate("q")
        self.assertTrue(ok)

    def test_gate_hook_is_installed(self):
        self.assertIs(nova.imgsys.AI_GATE_HOOK,
                      nova._vision_selection_gate)


class TestVerdictPipeline(unittest.TestCase):
    def setUp(self):
        vis.clear_cache()
        old = os.environ.get("NOVA_NO_IMG_AI")
        os.environ.pop("NOVA_NO_IMG_AI", None)
        self._old_noai = old

    def tearDown(self):
        if self._old_noai is not None:
            os.environ["NOVA_NO_IMG_AI"] = self._old_noai

    def test_local_vision_approves_and_rejects(self):
        answers = ['Sure! {"ok": true} - looks great',
                   '{"ok": false, "reason": "not a rose"}']
        with mock.patch.object(nova, "_provider_cfg",
                               return_value={"kind": "ollama",
                                             "model": "llava:7b"}), \
             mock.patch.object(nova, "_is_free_local", return_value=True), \
             mock.patch.object(nova, "_vision_capability",
                               return_value={"vision": True}), \
             mock.patch.object(nova, "_ollama_once",
                               side_effect=answers):
            ok, tail = nova._img_ai_verify("red rose", b"jpeg-bytes")
            self.assertTrue(ok)
            self.assertEqual(tail, "local-approved")
            ok, tail = nova._img_ai_verify("red rose", b"jpeg-bytes")
            self.assertFalse(ok)
            self.assertEqual(tail, "not a rose")

    def test_text_only_local_falls_to_cloud_gate(self):
        with mock.patch.object(nova, "_provider_cfg",
                               return_value={"kind": "ollama",
                                             "model": "coder:7b"}), \
             mock.patch.object(nova, "_is_free_local", return_value=True), \
             mock.patch.object(nova, "_vision_capability",
                               return_value={"vision": False}), \
             mock.patch.object(nova, "_img_ai_cloud",
                               return_value=(None, "")):
            ok, tail = nova._img_ai_verify("red rose", b"jpeg")
        self.assertTrue(ok)          # no cloud gate -> fail soft, pass

    def test_local_unreachable_is_a_timed_pass(self):
        with mock.patch.object(nova, "_provider_cfg",
                               return_value={"kind": "ollama",
                                             "model": "llava:7b"}), \
             mock.patch.object(nova, "_is_free_local", return_value=True), \
             mock.patch.object(nova, "_vision_capability",
                               return_value={"vision": True}), \
             mock.patch.object(nova, "_ollama_once",
                               side_effect=OSError("down")):
            ok, tail = nova._img_ai_verify("red rose", b"jpeg")
        self.assertTrue(ok)
        self.assertEqual(tail, "local-unavailable")

    def test_human_gate_uses_its_own_prompt(self):
        seen = {}

        def fake_verify(q, jpeg, prompt=None):
            seen["prompt"] = prompt
            return True, "local-approved"

        with mock.patch.object(nova, "_img_ai_verify",
                               side_effect=fake_verify), \
             mock.patch.object(nova, "_vision_settings_now",
                               return_value={"approve": True}):
            ok, tail = nova._img_verify_human(b"jpeg")
        self.assertTrue(ok)
        self.assertEqual(seen["prompt"], nova._IMG_HUMAN_GATE_PROMPT)

    def test_human_gate_approve_off_passes(self):
        with mock.patch.object(nova, "_vision_settings_now",
                               return_value={"approve": False}):
            ok, tail = nova._img_verify_human(b"jpeg")
        self.assertTrue(ok)
        self.assertEqual(tail, "approval-off")


# =====================================================================
# 4. the /img and /imgdl commands
# =====================================================================
class TestImageCommands(unittest.TestCase):
    def _sess(self):
        return nova.Session(Path(tempfile.mkdtemp()))

    def test_img_pick_rejection_is_honest(self):
        sess = self._sess()
        events = []
        captured = {}
        results = [{"url": "https://x/1.jpg", "thumb": "",
                    "title": "rose", "source": "openverse",
                    "width": 100, "height": 100}]

        def fake_save(result, ws, deadline=None, verify=None):
            captured["verify"] = verify
            return "", {"ai_rejected": 1, "ai_reason": "not a rose"}

        old_sink = nova.EVENT_SINK
        nova.EVENT_SINK = events.append
        try:
            with mock.patch.object(nova.imgsys, "search_images",
                                   return_value=results), \
                 mock.patch.object(nova.imgsys, "save_result",
                                   side_effect=fake_save), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                nova.cmd_img(sess, "red rose")
        finally:
            nova.EVENT_SINK = old_sink
        text = out.getvalue()
        self.assertIn("REJECTED", text)
        self.assertIn("not a rose", text)
        self.assertTrue(callable(captured["verify"]))
        # the verify lambda rides the full verdict pipeline
        with mock.patch.object(nova, "_img_ai_verify",
                               return_value=(False, "no")) as v:
            ok, why = captured["verify"](b"jpeg")
        v.assert_called_once_with("red rose", b"jpeg")
        self.assertFalse(ok)

    def test_img_pick_success_still_prints_the_reference(self):
        sess = self._sess()
        results = [{"url": "https://x/1.jpg", "thumb": "",
                    "title": "rose", "source": "openverse",
                    "width": 100, "height": 100}]
        with mock.patch.object(nova.imgsys, "search_images",
                               return_value=results), \
             mock.patch.object(nova.imgsys, "save_result",
                               return_value=("assets/images/rose_l.jpg",
                                             {"bytes": 2048,
                                              "source": "openverse"})), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            nova.cmd_img(sess, "red rose")
        self.assertIn("assets/images/rose_l.jpg", out.getvalue())
        self.assertIn('<img src="assets/images/rose_l.jpg"',
                      out.getvalue())

    def test_imgdl_rejection_never_saves(self):
        sess = self._sess()
        events = []

        def fake_save(url, ws, name=None, verify=None):
            return "", {"ai_rejected": 1, "ai_reason": "broken file"}

        old_sink = nova.EVENT_SINK
        nova.EVENT_SINK = events.append
        try:
            with mock.patch.object(nova.imgsys, "save_from_url",
                                   side_effect=fake_save), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                nova.cmd_imgdl(sess, "https://x/pic.jpg")
        finally:
            nova.EVENT_SINK = old_sink
        self.assertIn("REJECTED", out.getvalue())
        self.assertIn("broken file", out.getvalue())
        self.assertTrue(any("rejected" in str(e.get("text", ""))
                            for e in events))

    def test_imgdl_success_path(self):
        sess = self._sess()
        with mock.patch.object(nova.imgsys, "save_from_url",
                               return_value=("assets/images/pic.jpg",
                                             {"bytes": 4096})), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            nova.cmd_imgdl(sess, "https://x/pic.jpg cute")
        self.assertIn("assets/images/pic.jpg", out.getvalue())


# =====================================================================
# 5. integration surface
# =====================================================================
class TestNovaIntegration(unittest.TestCase):
    def test_version_pins(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(nova.CODENAME, "master switch")
        self.assertEqual(nova_think.VERSION, "8.12.0")
        self.assertTrue(any("Version 8.12.0" in ln
                            for ln in _src("nova.py").splitlines()[:8]))

    def test_deep_sweep_surface(self):
        """v8.6 part A: the deep sweep (bugs beyond buttons - a simple
        function, extra code, missing code) is wired through the whole
        surface: /probe subcommands, the report line, the web payload,
        the settings handler and the panel."""
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            st = nova.web_probe_state(sess)
            for key in ("deep", "reject_deep"):
                self.assertIn(key, st)
                self.assertTrue(st[key])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                nova.cmd_probe(sess, "deep off")
            self.assertIn("updated", out.getvalue())
            self.assertFalse(sess.probe_settings["deep"])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                nova.cmd_probe(sess, "")
            self.assertIn("deep sweep", out.getvalue())
            ws = _src("web_server.py")
            self.assertIn('("probe_deep", "deep")', ws)
            self.assertIn('("probe_rejectdeep", "reject_deep")', ws)
            html = _src("web/index.html")
            for eid in ("probeDeep", "probeRejectDeep"):
                self.assertIn(eid, html)

    def test_vision_registered_in_tools(self):
        entry = next((t for t in nova.TOOLS if t["cmd"] == "/vision"),
                     None)
        self.assertIsNotNone(entry)
        self.assertIs(entry["fn"], nova.cmd_vision)

    def test_vision_command_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                nova.cmd_vision(sess, "")
            self.assertIn("Vision layer", out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                nova.cmd_vision(sess, "strict on")
            st = vis.load_settings(sess.ws)
            self.assertTrue(st["strict"])
            self.assertTrue(st["custom"])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                nova.cmd_vision(sess, "check")
            self.assertIn("fresh look", out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                nova.cmd_vision(sess, "reset")
            self.assertFalse(vis.load_settings(sess.ws)["custom"])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                nova.cmd_vision(sess, "nonsense")
            self.assertIn("unknown subcommand", out.getvalue())

    def test_settings_survive_the_command_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            with contextlib.redirect_stdout(io.StringIO()):
                nova.cmd_vision(sess, "approve off")
            self.assertFalse(sess.vision_settings["approve"])
            with contextlib.redirect_stdout(io.StringIO()):
                nova.cmd_vision(sess, "approve on")
            self.assertTrue(sess.vision_settings["approve"])

    def test_session_carries_the_settings_and_tracker(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            self.assertIn("approve", sess.vision_settings)
            self.assertEqual(nova._VISION_ACTIVE["ws"], sess.ws)
            sess.save_profile_field("model", "llava:7b")
            self.assertEqual(nova._VISION_ACTIVE["model"], "llava:7b")

    def test_web_vision_state_shape(self):
        with tempfile.TemporaryDirectory() as td:
            sess = nova.Session(Path(td))
            st = nova.web_vision_state(sess)
            for key in ("vision", "via", "detail", "approve", "strict",
                        "custom", "model", "backend", "env_off"):
                self.assertIn(key, st)
            self.assertTrue(st["approve"])
            self.assertFalse(st["strict"])

    def test_web_server_and_panel_surface(self):
        ws = _src("web_server.py")
        self.assertIn('"vision": _state_safe', ws)
        self.assertIn('("vision_approve", "approve")', ws)
        self.assertIn('"vision_reset"', ws)
        html = _src("web/index.html")
        for eid in ("visionState", "visionApprove", "visionStrict",
                    "visionSave", "visionReset", "renderVisionPanel"):
            self.assertIn(eid, html)

    def test_cmd_wiring_source_pins(self):
        src = _src("nova.py")
        self.assertIn("verify=lambda raw: _img_ai_verify(query, raw)",
                      src)                    # /img pick approval
        self.assertIn("verify=_img_verify_human", src)   # /imgdl gate
        self.assertIn("imgsys.AI_GATE_HOOK = _vision_selection_gate",
                      src)                    # the selection gate
        self.assertNotIn("_IMG_VISION_RE", src)  # the dead regex is gone
        self.assertIn("vision=", _src("nova.py")
                      .split("def cmd_status")[1].split("def cmd_export")[0])

    def test_nova_images_gate_ladder_pins(self):
        src = _src("nova_images.py")
        self.assertIn("AI_GATE_HOOK = None", src)
        self.assertIn("ok_g, gnote = _ai_gate_ok(qn)", src)
        self.assertIn("ok_g, gnote = _ai_gate_ok(query)", src)

    def test_vision_module_fail_soft_when_missing(self):
        old = nova.vision
        nova.vision = None
        try:
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                self.assertEqual(sess.vision_settings, {})
                self.assertTrue(nova._vision_selection_gate("q")[0])
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    nova.cmd_vision(sess, "")
                self.assertIn("missing", out.getvalue())
        finally:
            nova.vision = old


if __name__ == "__main__":
    unittest.main()
