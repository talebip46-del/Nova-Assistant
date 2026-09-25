#!/usr/bin/env python3
# =====================================================================
#  Nova v8.11.0 "stability sweep" regression tests - the full audit pass
#  over every file. Each test pins ONE real bug found and fixed in the
#  v8.7 audit (the false-reject quartet, the web-approval gate hole,
#  the vision tracker staleness, and the silent-data-loss family).
#  Everything is offline and deterministic.
# =====================================================================
import ast
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nova                                  # noqa: E402
import nova_think                            # noqa: E402
import nova_ctxengine as ctxengine           # noqa: E402
import nova_guardian as gd                   # noqa: E402
import nova_probe as pb                      # noqa: E402
import nova_providers as providers           # noqa: E402
import nova_vision as vis                    # noqa: E402


def _clean_env(**vals):
    return mock.patch.dict(os.environ, vals, clear=False)


# =====================================================================
# 1. the false-reject quartet (gates refused HEALTHY code)
# =====================================================================
class TestFalseRejects(unittest.TestCase):
    def test_probe_inline_script_handlers_are_definitions(self):
        # v8.7: a single-file page defining its handler in an inline
        # <script> used to be rejected as "dead handler".
        html = ('<button onclick="go()">x</button>\n'
                '<script>\nfunction go(){ alert(1); }\n</script>\n')
        w = pb.wiring_check([("index.html", html)])
        self.assertEqual(w["errors"], [])

    def test_probe_match_statement_captures_bind(self):
        # v8.7: `case {"op": op}:` bindings used to be reported as
        # guaranteed NameError on perfectly valid python.
        py = ('def run(cmd):\n'
              '    match cmd:\n'
              '        case {"op": op, "x": xval}:\n'
              '            print(op, xval)\n'
              '        case [first, second]:\n'
              '            print(first, second)\n'
              '    return True\n')
        findings = pb.static_check([("c.py", py)])
        self.assertEqual([f for f in findings if "NameError" in str(f[2])],
                         [])

    def test_smoke_deliberate_exit_is_not_a_crash(self):
        # v8.7: sys.exit("usage: ...") is a guard, not a runtime crash.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "cli.py").write_text(
                "import sys\nsys.exit('usage: cli <file>')\n",
                encoding="utf-8")
            r = pb.smoke_one(Path(td), "cli.py")
            self.assertEqual(r["level"], "warn", r)

    def test_smoke_real_crash_still_errors(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "boom.py").write_text("raise ValueError('nope')\n",
                                              encoding="utf-8")
            r = pb.smoke_one(Path(td), "boom.py")
            self.assertEqual(r["level"], "error", r)
            self.assertIn("ValueError", r["msg"])

    def test_rust_lifetimes_pass_the_structure_floor(self):
        # (pinned in v840 too; kept here as the audit's own guard)
        rust = "struct S<'a> { name: &'a str }\nfn main() {}\n"
        self.assertEqual(gd.validate("m.rs", rust)["errors"], [])


# =====================================================================
# 2. the web-approval gate hole (apply_approved never met the fleet)
# =====================================================================
class TestApplyApprovedGates(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.ws = Path(self.td.name)
        self.sess = nova.Session(self.ws)
        self.sess.confirm_changes = True
        nova.NONINTERACTIVE = True
        self._env = _clean_env(NOVA_GUARDIAN="1", NOVA_PROBE="1")
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.sess.confirm_changes = False
        nova.NONINTERACTIVE = False
        self.sess.pending_apply = None
        self.td.cleanup()

    def test_guardian_gate_refuses_web_approved_batch(self):
        # a genuinely unbalanced rust file: quality.preapply_check has
        # no rust lint (lint passes), the guardian fleet must refuse it.
        answer = "=== FILE: lib.rs ===\nfn broken() {\n=== END ===\n"
        files, unnamed = nova.parse_files(answer)
        nova.offer_apply(self.sess, files, unnamed, edits=[], auto=True)
        pend = self.sess.pending_apply
        self.assertIsNotNone(pend)
        ok, result = nova.apply_approved(self.sess, pend["id"], ["lib.rs"], {})
        self.assertFalse(ok)
        self.assertIn("guardian", result["error"].lower())
        self.assertFalse((self.ws / "lib.rs").exists(), "zero bytes law")

    def test_probe_gate_refuses_web_approved_dead_wiring(self):
        answer = ('=== FILE: page.html ===\n'
                  '<button onclick="ghost_fn()">x</button>\n'
                  '=== END ===\n')
        files, unnamed = nova.parse_files(answer)
        nova.offer_apply(self.sess, files, unnamed, edits=[], auto=True)
        pend = self.sess.pending_apply
        self.assertIsNotNone(pend)
        ok, result = nova.apply_approved(self.sess, pend["id"],
                                         ["page.html"], {})
        self.assertFalse(ok)
        # v8.12: the message now says "bug-hunter gate" (the gate also
        # fires for the deep sweep, not only wiring) - same refusal,
        # same zero-bytes law.
        self.assertIn("bug-hunter gate refused", result["error"].lower())
        self.assertFalse((self.ws / "page.html").exists())

    def test_healthy_web_approved_batch_still_applies(self):
        answer = ('=== FILE: ok.html ===\n'
                  '<button onclick="hi()">x</button>\n'
                  '<script>function hi(){ alert(1); }</script>\n'
                  '=== END ===\n')
        files, unnamed = nova.parse_files(answer)
        nova.offer_apply(self.sess, files, unnamed, edits=[], auto=True)
        pend = self.sess.pending_apply
        ok, result = nova.apply_approved(self.sess, pend["id"],
                                         ["ok.html"], {})
        self.assertTrue(ok, result)
        self.assertTrue((self.ws / "ok.html").exists())


# =====================================================================
# 3. the vision tracker staleness (wrong brain asked about photos)
# =====================================================================
class TestVisionTracker(unittest.TestCase):
    def test_name_re_needs_a_word_boundary(self):
        self.assertIsNone(vis.NAME_RE.search("supervision-setup"))
        self.assertIsNone(vis.NAME_RE.search("revision3"))
        self.assertIsNotNone(vis.NAME_RE.search("llava:7b"))
        self.assertIsNotNone(vis.NAME_RE.search("my-vision-model"))

    def test_detect_cache_key_covers_the_base(self):
        vis._CACHE.clear()
        calls = []

        def fake_impl(kind, name, base, path, show_fn):
            calls.append((kind, name, base))
            return {"vision": len(calls) == 1, "via": "test", "detail": ""}

        with mock.patch.object(vis, "_detect_impl", side_effect=fake_impl):
            r1 = vis.detect("ollama", "m1", base="http://h1")
            r2 = vis.detect("ollama", "m1", base="http://h2")
        self.assertTrue(r1["vision"])
        self.assertFalse(r2["vision"], "host B must not reuse host A's verdict")
        self.assertEqual(len(calls), 2)


# =====================================================================
# 4. the ctx engine (custom gate + env bounds)
# =====================================================================
class TestCtxEngine(unittest.TestCase):
    def test_junk_settings_file_is_not_custom(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / ".nova"
            d.mkdir(parents=True)
            (d / "context.json").write_text('{"note": "junk"}',
                                            encoding="utf-8")
            with _clean_env(NOVA_NUM_CTX="8192"):
                st = ctxengine.load_settings(td)
            self.assertFalse(st["custom"])
            self.assertEqual(st["local_ctx"], 8192)

    def test_env_values_are_clamped(self):
        with tempfile.TemporaryDirectory() as td:
            with _clean_env(NOVA_NUM_CTX="0"):
                self.assertGreaterEqual(
                    ctxengine.load_settings(td)["local_ctx"], 512)
            with _clean_env(NOVA_NUM_CTX="-500"):
                self.assertGreaterEqual(
                    ctxengine.load_settings(td)["local_ctx"], 512)


# =====================================================================
# 5. the provider env override (stale NOVA_MODEL must not rename brains)
# =====================================================================
class TestProviderEnv(unittest.TestCase):
    def test_env_model_fills_empty_but_never_stomps(self):
        with _clean_env(NOVA_MODEL="ghost-model", GROQ_API_KEY="sk-test"):
            # a provider with a built-in default keeps it
            self.assertEqual(providers.resolve("groq")["model"],
                             providers.entry("groq")["model"])
            # an empty-model provider (custom) still gets filled
            with _clean_env(NOVA_BASE_URL="http://localhost:1234/v1"):
                self.assertEqual(providers.resolve("custom")["model"],
                                 "ghost-model")


# =====================================================================
# 6. the intel TaskGraph (a rejected set() must not mutate the task)
# =====================================================================
class TestTaskGraph(unittest.TestCase):
    def test_rejected_deps_leave_the_task_untouched(self):
        import nova_intel as intel
        with tempfile.TemporaryDirectory() as td:
            g = intel.TaskGraph(Path(td) / "tasks.json")
            a = g.add("task A")
            with self.assertRaises(ValueError):
                g.set(a, status="doing", deps=["nonexistent"])
            self.assertEqual(g.get(a)["status"], "todo")
            self.assertEqual(g.get(a)["deps"], [])


# =====================================================================
# 7. project-wide hygiene pins
# =====================================================================
class TestHygiene(unittest.TestCase):
    def test_no_duplicate_dict_keys_anywhere(self):
        # the «نانوا» bug class: a repeated dict key silently keeping
        # the LAST value (bakery scenes instead of baker portraits).
        root = Path(__file__).resolve().parents[1]
        files = sorted(root.glob("*.py")) + \
            sorted(root.glob("nova_modules/*.py"))
        self.assertTrue(files)
        dups = []
        for f in files:
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    seen = set()
                    for k in node.keys:
                        if k is None:
                            continue
                        key = ast.dump(k)
                        if key in seen:
                            dups.append(f"{f.name}:{k.lineno}")
                        seen.add(key)
        self.assertEqual(dups, [])

    def test_help_provider_count_is_honest(self):
        self.assertIn("۳۰", nova.HELP_FA["/provider"])

    def test_interrupt_flag_exists_and_resets(self):
        self.assertFalse(nova._LAST_STREAM_INTERRUPT)
        import inspect
        src = inspect.getsource(nova.stream_chat)
        self.assertIn("_LAST_STREAM_INTERRUPT = False", src)

    def test_version_pins(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(nova.CODENAME, "master switch")
        self.assertEqual(nova_think.VERSION, "8.12.0")


if __name__ == "__main__":
    unittest.main()
