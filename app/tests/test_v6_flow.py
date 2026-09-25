#!/usr/bin/env python3
"""v6.0 tests: Nova Flow - validation, templating, branching, loop
guards, the crew node, persistence - all with a FAKE chat function
(no model, no network)."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova_modules import flow, ModuleError


def fake_chat(system, text):
    return "FAKE:" + (text or "")[:40]


class TestValidate(unittest.TestCase):
    def test_ok(self):
        f = flow.validate({"name": "my flow", "steps": [
            {"id": "a", "type": "prompt", "with": {"text": "hi"}}]})
        self.assertEqual(f["name"], "my flow")

    def test_name_rules(self):
        for bad in ("", None, "x" * 60, "bad/name", {"x": 1}):
            with self.assertRaises(ModuleError):
                flow.validate({"name": bad, "steps": [
                    {"id": "a", "type": "delay", "with": {"seconds": 0}}]})

    def test_steps_rules(self):
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": []})
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": [{"id": "a", "type": "nope"}]})
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": [
                {"id": "a", "type": "delay"}, {"id": "a", "type": "delay"}]})
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": [{"id": "bad id!", "type": "delay"}]})
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": [
                {"id": "a", "type": "prompt", "with": {"text": ""}}]})
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": [
                {"id": "a", "type": "delay", "with": {"x": [1, 2]}}]})   # list not ok
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": [
                {"id": "a", "type": "condition", "with": {"op": "explode"}}]})

    def test_step_cap(self):
        steps = [{"id": "s%d" % i, "type": "delay", "with": {"seconds": 0}}
                 for i in range(60)]
        with self.assertRaises(ModuleError):
            flow.validate({"name": "f", "steps": steps})


class TestTemplating(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(flow.substitute("hello {{a}}!", {"a": {"text": "world"}}),
                         "hello world!")

    def test_path_traversal(self):
        self.assertEqual(flow.substitute("{{a.b.c}}",
                                         {"a": {"b": {"c": "deep"}}}), "deep")

    def test_unknown_stays(self):
        self.assertEqual(flow.substitute("keep {{nope}}", {}), "keep {{nope}}")

    def test_dollar_and_braces_safe(self):
        # no eval anywhere: nasty content stays literal text
        nasty = {"a": {"text": "'.__import__('os').system('id').'"}}
        self.assertEqual(flow.substitute("{{a}}", nasty),
                         "'.__import__('os').system('id').'")

    def test_fill(self):
        out = flow._fill({"t": "x {{a}}", "n": 5}, {"a": {"text": "y"}})
        self.assertEqual(out, {"t": "x y", "n": 5})


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nova_fl_"))

    def test_transform_and_vars(self):
        snap = flow.run(self.ws, {"name": "t1", "steps": [
            {"id": "a", "type": "transform", "with": {"text": "one"}},
            {"id": "b", "type": "transform", "with": {"text": "got {{a}}"}}]},
            chat_fn=fake_chat)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["vars"]["b"]["text"], "got one")

    def test_inputs(self):
        snap = flow.run(self.ws, {"name": "t2", "steps": [
            {"id": "a", "type": "transform", "with": {"text": "hi {{name}}"}}]},
            inputs={"name": "nova"}, chat_fn=fake_chat)
        self.assertEqual(snap["vars"]["a"]["text"], "hi nova")
        # junk inputs are dropped, not crashed on
        snap = flow.run(self.ws, {"name": "t3", "steps": [
            {"id": "a", "type": "transform", "with": {"text": "x"}}]},
            inputs={"bad id": [1], "ok": "yes"}, chat_fn=fake_chat)
        self.assertEqual(snap["status"], "done")

    def test_branch_goto_skips(self):
        snap = flow.run(self.ws, {"name": "t4", "steps": [
            {"id": "c", "type": "condition",
             "with": {"left": "yes", "op": "eq", "right": "yes", "goto": "z"}},
            {"id": "m", "type": "transform", "with": {"text": "SKIPPED"}},
            {"id": "z", "type": "transform", "with": {"text": "target"}}]},
            chat_fn=fake_chat)
        self.assertEqual(snap["status"], "done")
        # jumped over 'm': never executed, never in vars
        self.assertNotIn("m", snap["vars"])
        self.assertIn("z", snap["vars"])
        self.assertIn("jump", snap["steps"][0]["detail"])

    def test_branch_false_continues(self):
        snap = flow.run(self.ws, {"name": "t5", "steps": [
            {"id": "c", "type": "condition",
             "with": {"left": "", "op": "not_empty"}},
            {"id": "z", "type": "transform", "with": {"text": "reached"}}]},
            chat_fn=fake_chat)
        self.assertIn("z", snap["vars"])

    def test_unknown_jump_fails_cleanly(self):
        snap = flow.run(self.ws, {"name": "t6", "steps": [
            {"id": "c", "type": "condition",
             "with": {"op": "not_empty", "left": "x", "goto": "ghost"}}]},
            chat_fn=fake_chat)
        self.assertEqual(snap["status"], "failed")
        self.assertIn("ghost", snap["error"])

    def test_loop_guard(self):
        snap = flow.run(self.ws, {"name": "t7", "steps": [
            {"id": "a", "type": "condition",
             "with": {"op": "not_empty", "left": "x", "goto": "a"}}]},
            chat_fn=fake_chat)
        self.assertEqual(snap["status"], "failed")
        self.assertIn("loop", snap["error"].lower())

    def test_crew(self):
        calls = []

        def chat(system, text):
            calls.append(system or "")
            return "answer"
        snap = flow.run(self.ws, {"name": "t8", "steps": [
            {"id": "team", "type": "crew",
             "with": {"roles": "planner: make a plan\ncritic: judge it",
                      "text": "build a birdhouse"}}]}, chat_fn=chat)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["vars"]["team"]["text"], "answer")
        self.assertEqual(len(snap["vars"]["team"]["answers"]), 2)

    def test_pixel_and_voice_nodes(self):
        snap = flow.run(self.ws, {"name": "t9", "steps": [
            {"id": "p", "type": "pixel",
             "with": {"prompt": "invader sprite", "size": 16}},
            {"id": "v", "type": "voice",
             "with": {"text": "ready", "engine": "offline"}}]},
            chat_fn=fake_chat)
        self.assertEqual(snap["status"], "done")
        self.assertTrue(Path(snap["vars"]["p"]["path"]).is_file())
        self.assertTrue(Path(snap["vars"]["v"]["path"]).is_file())

    def test_knowledge_node(self):
        (self.ws / "note.md").write_text("the launch code is nova-42 " * 30,
                                         encoding="utf-8")
        from nova_modules import knowledge as kb
        kb.ingest(self.ws, ["note.md"])
        snap = flow.run(self.ws, {"name": "t10", "steps": [
            {"id": "k", "type": "knowledge",
             "with": {"query": "launch code", "k": 2}}]}, chat_fn=fake_chat)
        self.assertEqual(snap["status"], "done")
        self.assertIn("nova-42", snap["vars"]["k"]["text"])

    def test_http_node(self):
        snap = flow.run(self.ws, {"name": "t11", "steps": [
            {"id": "h", "type": "http", "with": {"url": "file:///etc/passwd"}}]},
            chat_fn=fake_chat)
        self.assertEqual(snap["status"], "failed")
        self.assertIn("http(s)", snap["error"])

    def test_step_failure_logged(self):
        snap = flow.run(self.ws, {"name": "t12", "steps": [
            {"id": "ok", "type": "transform", "with": {"text": "fine"}},
            {"id": "bad", "type": "voice", "with": {"text": ""}},   # empty -> fail
            {"id": "never", "type": "transform", "with": {"text": "x"}}]},
            chat_fn=fake_chat)
        self.assertEqual(snap["status"], "failed")
        self.assertEqual(snap["steps"][0]["status"], "done")
        self.assertEqual(snap["steps"][1]["status"], "failed")
        self.assertEqual(len(snap["steps"]), 2)      # engine stops at failure

    def test_persistence(self):
        flow.save(self.ws, {"name": "saved flow", "steps": [
            {"id": "a", "type": "delay", "with": {"seconds": 0}}]})
        names = [f["name"] for f in flow.list_flows(self.ws)]
        self.assertIn("saved flow", names)
        got = flow.get(self.ws, "saved flow")
        self.assertEqual(got["steps"][0]["type"], "delay")
        self.assertTrue(flow.delete(self.ws, "saved flow"))
        self.assertIsNone(flow.get(self.ws, "saved flow"))

    def test_corrupt_flow_file_ignored(self):
        d = flow.flows_dir(self.ws)
        (d / "broken.json").write_text("{oops", encoding="utf-8")
        self.assertEqual([f for f in flow.list_flows(self.ws) if f["name"] == "broken"],
                         [])

    def test_async_run(self):
        rid, snap = flow.run_async(self.ws, {"name": "t13", "steps": [
            {"id": "a", "type": "delay", "with": {"seconds": 0.1}},
            {"id": "b", "type": "transform", "with": {"text": "done"}}]},
            chat_fn=fake_chat)
        self.assertTrue(rid)
        deadline = time.time() + 10
        while time.time() < deadline:
            st = flow.run_status(self.ws, rid)
            if st and st["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(st["status"], "done")
        self.assertEqual(flow.run_status(self.ws, "no-such-run"), None)

    def test_json_safe_vars(self):
        snap = flow.run(self.ws, {"name": "t14", "steps": [
            {"id": "p", "type": "pixel", "with": {"prompt": "sprite", "size": 16}}]},
            chat_fn=fake_chat)
        json.dumps(snap["vars"])      # must not raise

    def test_sample_valid(self):
        f = flow.validate(flow.SAMPLE)
        self.assertEqual(f["name"], "idea-to-art")


class TestChatFnSelection(unittest.TestCase):
    def test_unusable_backend_message(self):
        ws = Path(tempfile.mkdtemp())
        from nova_modules import assign as A
        A.save_module(ws, "assistant",
                      {"backend": "cloud", "model": "nosuchprovider:xyz"})
        snap = flow.run(ws, {"name": "t15", "steps": [
            {"id": "a", "type": "prompt", "with": {"text": "x"}}]},
            chat_fn=None)          # lazy: the failure must surface IN the run
        self.assertEqual(snap["status"], "failed")
        self.assertTrue(snap["error"])

    def test_offline_flow_needs_no_brain(self):
        """The lazy chat_fn contract: an offline-only flow runs with NO
        Ollama, NO platforms, NO cloud keys at all."""
        ws = Path(tempfile.mkdtemp())
        snap = flow.run(ws, {"name": "t16", "steps": [
            {"id": "p", "type": "pixel",
             "with": {"prompt": "invader", "size": 16}}]},
            chat_fn=None)
        self.assertEqual(snap["status"], "done")

    def test_cloud_backend_bad_provider(self):
        import os
        ws = Path(tempfile.mkdtemp())
        os.environ["NOVA_PROVIDER"] = ""
        try:
            from nova_modules import assign as A
            A.save_module(ws, "assistant", {"backend": "cloud", "model": "nope:xyz"})
            with self.assertRaises(ModuleError):
                flow._default_chat_fn(ws)
        finally:
            os.environ.pop("NOVA_PROVIDER", None)


if __name__ == "__main__":
    unittest.main()
