"""v8.12.0 «master switch» - regression tests for the final-assurance
sweep. Every test here pins a REAL bug found by the zero-to-one-hundred
audit (each one reproduced live before the fix, per project law):

 1. apply_approved (web Approve) ran the guardian gate even when the
    user had turned the fleet OFF - the same batch applied in the
    terminal was refused in the browser.
 2. _draft_valid gave the guardian a vote even with the fleet OFF.
 3. preview_target hijacked interpreter-led commands that merely END
    in .html ('python gen.py out.html' never ran - a phantom stop).
 4. probe.json with ZERO valid keys claimed custom=True (the v8.11
    anti-freeze law was applied to guardian/vision/ctx but skipped
    the hunter).
 5. 'deep on / wiring off' silently disabled the pre-apply gate (the
    deep sweep was post-apply-only).
 6. parse_layers('shadow=²') raised ValueError (isdigit() says True
    for superscripts) - the documented 'never raises' contract broke.
 7. sorted(root.rglob('*')) walked the ENTIRE tree (including .git and
    node_modules) before the max_files cap could ever apply.
 8. NOVA_PROBE_TIMEOUT=nan|inf silently disabled the smoke timeout.
 9. /api/settings fired the destructive *_reset on ANY truthy value
    (the string 'no' wiped the saved settings file).
10. non-bool confirm_changes/explain/autotest/autofix were silently
    dropped while the panel toasted 'saved' (now: 400).
11. keys for a MISSING engine layer were silently dropped with
    ok:true (now: 501, the /api/rag convention).
13. a stale sess.batch_refused from an earlier turn could make /auto
    believe a fresh unrelated batch was gate-refused.
"""
import contextlib
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova  # noqa: E402
import nova_probe  # noqa: E402
import nova_guardian  # noqa: E402
import nova_design  # noqa: E402
import web_server  # noqa: E402


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield


@contextlib.contextmanager
def _env_off(name):
    """Set a kill-switch env var for the block, restore after."""
    old = os.environ.get(name)
    os.environ[name] = "0"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


BAD_GO = 'package main\nfunc main() {\nprintln("x")\n'


class _WsCase(unittest.TestCase):
    """A throwaway workspace + session per test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.ws = Path(self._td.name)
        self.sess = nova.Session(self.ws)
        self.sess.confirm_changes = True
        nova.NONINTERACTIVE = True

    def tearDown(self):
        nova.NONINTERACTIVE = False
        self._td.cleanup()


# =====================================================================
# 1 + 2. the master switch is honored on EVERY guardian path
# =====================================================================
class TestGuardianMasterSwitchParity(_WsCase):
    def test_settings_off_terminal_applies_and_web_applies_too(self):
        # the fleet is OFF via the panel settings - both doors must agree
        # (NONINTERACTIVE stages the batch, so the web door is the one
        # that applies - exactly the path the bug lived on)
        self.sess.guardian_settings = {"on": False}
        answer = "=== FILE: bad.go ===\n" + BAD_GO + "\n=== END ===\n"
        files, _ = nova.parse_files(answer)
        with _quiet():
            nova.offer_apply(self.sess, files, [], auto=True)
        pend = self.sess.pending_apply
        self.assertIsNotNone(pend)
        calls = {"n": 0}
        orig = nova.guardian.review_batch

        def spy(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)
        nova.guardian.review_batch = spy
        try:
            ok, result = nova.apply_approved(self.sess, pend["id"],
                                             ["bad.go"], {})
        finally:
            nova.guardian.review_batch = orig
        self.assertTrue(ok, result)
        self.assertEqual(calls["n"], 0, "disabled fleet must not even run")
        self.assertTrue((self.ws / "bad.go").exists())

    def test_env_off_web_approve_matches_terminal(self):
        with _env_off("NOVA_GUARDIAN"):
            answer = ("=== FILE: bad.go ===\n" + BAD_GO +
                      "\n=== END ===\n")
            files, _ = nova.parse_files(answer)
            with _quiet():
                nova.offer_apply(self.sess, files, [], auto=True)
            pend = self.sess.pending_apply
            self.assertIsNotNone(pend)
            ok, result = nova.apply_approved(self.sess, pend["id"],
                                             ["bad.go"], {})
            self.assertTrue(ok, result)
        self.assertTrue((self.ws / "bad.go").exists())

    def test_env_off_draft_gate_skips_the_vote(self):
        # the body must pass the CORE lint and fail only the FLEET -
        # 'var x = {;' dies in quality.preapply_check before the
        # guardian block is ever reached (a vacuous spy count).
        # bad.go passes the core lint (no go linter there) and fails
        # the fleet's bracket scanner - exactly the class the fix
        # governs.
        draft = ("=== FILE: lib.go ===\n" + BAD_GO + "\n=== END ===\n"
                 "Run: go run lib.go")
        self.sess.guardian_settings = {"on": False}
        calls = {"n": 0}
        orig = nova.guardian.review_batch

        def spy(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)
        nova.guardian.review_batch = spy
        try:
            ok_off = nova._draft_valid(draft, self.sess)
        finally:
            nova.guardian.review_batch = orig
        self.assertEqual(calls["n"], 0, "a disabled fleet never votes")
        self.assertTrue(ok_off, "fleet OFF: the draft wins the race")

    def test_fleet_on_still_votes_in_the_draft_gate(self):
        # the mirror of the fix: with the fleet ON the same draft loses
        # the race (the fleet votes it down) - the vote is alive.
        draft = ("=== FILE: lib.go ===\n" + BAD_GO + "\n=== END ===\n"
                 "Run: go run lib.go")
        calls = {"n": 0}
        orig = nova.guardian.review_batch

        def spy(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)
        nova.guardian.review_batch = spy
        try:
            ok_on = nova._draft_valid(draft, self.sess)
        finally:
            nova.guardian.review_batch = orig
        self.assertEqual(calls["n"], 1, "the fleet votes")
        self.assertFalse(ok_on, "fleet ON: the draft loses the race")

    def test_fleet_on_still_refuses_web_approved_batch(self):
        # the v8.7 behavior is preserved when the fleet is ON
        answer = "=== FILE: lib.rs ===\nfn broken() {\n=== END ===\n"
        files, _ = nova.parse_files(answer)
        with _quiet():
            nova.offer_apply(self.sess, files, [], auto=True)
        pend = self.sess.pending_apply
        ok, result = nova.apply_approved(self.sess, pend["id"],
                                         ["lib.rs"], {})
        self.assertFalse(ok)
        self.assertIn("guardian", result["error"].lower())
        self.assertFalse((self.ws / "lib.rs").exists(), "zero bytes law")


# =====================================================================
# 3. preview_target vs interpreter-led commands
# =====================================================================
class TestPreviewTargetScoping(_WsCase):
    def test_generator_command_is_not_a_preview(self):
        self.assertIsNone(nova.preview_target(self.ws,
                                              "python gen.py out.html"))
        self.assertIsNone(nova.preview_target(self.ws,
                                              "node gen.js page.html"))
        self.assertIsNone(nova.preview_target(self.ws,
                                              "pytest test_page.html"))
        self.assertIsNone(nova.preview_target(self.ws,
                                              "python3 build.py x.html"))

    def test_real_document_previews_still_intercepted(self):
        for cmd in ("index.html", "start index.html",
                    "cmd /c start index.html", "xdg-open index.html",
                    "start /min \"\" index.html"):
            self.assertIsNotNone(nova.preview_target(self.ws, cmd), cmd)

    def test_document_named_like_code_is_still_a_document(self):
        # only the FIRST token decides - 'node.js.html' is a file name
        self.assertIsNotNone(nova.preview_target(self.ws, "node.js.html"))


# =====================================================================
# 4. probe settings honesty (custom=True needs at least one valid key)
# =====================================================================
class TestProbeSettingsCustom(_WsCase):
    def _write(self, payload):
        d = self.ws / ".nova"
        d.mkdir(parents=True, exist_ok=True)
        (d / "probe.json").write_text(json.dumps(payload),
                                      encoding="utf-8")

    def test_garbage_file_does_not_claim_custom(self):
        self._write({"junk": 1, "on": "false"})
        st = nova_probe.load_settings(self.ws)
        self.assertFalse(st.get("custom"))
        self.assertTrue(st.get("on"), "defaults survive garbage")

    def test_valid_file_still_claims_custom(self):
        self._write({"on": False})
        st = nova_probe.load_settings(self.ws)
        self.assertTrue(st.get("custom"))
        self.assertFalse(st.get("on"))


# =====================================================================
# 5. deep-on / wiring-off still runs the pre-apply gate
# =====================================================================
class TestDeepGateIndependentOfWiring(_WsCase):
    def test_offer_apply_calls_gate_with_wiring_off_deep_on(self):
        nova.NONINTERACTIVE = False   # exercise the real auto-apply path
        self.sess.probe_settings = {"on": True, "wiring": False,
                                    "deep": True, "reject_wiring": True,
                                    "reject_deep": True}
        calls = {"n": 0}
        orig = nova_probe.pre_apply_gate

        def spy(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)
        nova_probe.pre_apply_gate = spy
        try:
            files, _ = nova.parse_files(
                "=== FILE: app.py ===\nprint(undefined_name)\n=== END ===\n")
            with _quiet():
                nova.offer_apply(self.sess, files, [], auto=True)
        finally:
            nova_probe.pre_apply_gate = orig
        self.assertEqual(calls["n"], 1, "the gate must fire for deep")

    def test_gate_with_wiring_off_skips_wiring_probe_but_keeps_deep(self):
        called = {"wiring": 0}
        orig = nova_probe.wiring_check

        def wspy(*a, **k):
            called["wiring"] += 1
            return orig(*a, **k)
        nova_probe.wiring_check = wspy
        try:
            rep = nova_probe.pre_apply_gate(
                [("app.py", "print(undefined_name)")],
                cfg={"on": True, "wiring": False, "deep": True,
                     "reject_wiring": True, "reject_deep": True})
        finally:
            nova_probe.wiring_check = wspy
        self.assertEqual(called["wiring"], 0,
                         "wiring off = wiring probe off")
        self.assertTrue(rep["reject"], "the deep sweep still rejects")
        self.assertTrue(rep["static"]["errors"])


# =====================================================================
# 6. parse_layers never raises (superscripts, Persian digits)
# =====================================================================
class TestParseLayersNeverRaises(_WsCase):
    def test_superscript_digit_does_not_raise(self):
        self.assertIsNone(nova_design.parse_layers("shadow=²").get("shadow"))

    def test_persian_and_ascii_digits_still_parse(self):
        self.assertEqual(nova_design.parse_layers("shadow=۲")["shadow"], 2)
        self.assertEqual(nova_design.parse_layers("shadow=2")["shadow"], 2)
        self.assertEqual(nova_design.parse_layers("glass=٤")["glass"], 4)

    def test_grammar_still_tolerant(self):
        self.assertEqual(nova_design.parse_layers("shadow=soft")["shadow"], 2)
        self.assertIsNone(nova_design.parse_layers("off")["shadow"])


# =====================================================================
# 7. the workspace walk is pruned and capped
# =====================================================================
class TestWorkspaceWalkBounded(_WsCase):
    def test_audit_skips_git_and_node_modules(self):
        for junk in (".git", "node_modules", "__pycache__"):
            (self.ws / junk).mkdir(parents=True)
            for i in range(500):
                (self.ws / junk / f"junk{i}.js").write_text(
                    "var a = 1;\n", encoding="utf-8")
        (self.ws / "app.js").write_text("var a = ;\n", encoding="utf-8")
        res = nova_guardian.audit_workspace(self.ws)
        files = [r["file"] for r in res]
        self.assertTrue(all(f == "app.js" for f in files), files)

    def test_ws_pool_ignores_ignored_dirs(self):
        (self.ws / "node_modules" / "lib").mkdir(parents=True)
        (self.ws / "node_modules" / "lib" / "x.js").write_text(
            "var b=2;\n", encoding="utf-8")
        (self.ws / "site.js").write_text("var b = 2;\n", encoding="utf-8")
        pool = nova_probe._ws_pool(self.ws)
        rels = [r for r, _b in pool]
        self.assertIn("site.js", rels)
        self.assertFalse(any(r.startswith("node_modules") for r in rels))


# =====================================================================
# 8. the smoke timeout survives nan/inf env values
# =====================================================================
class TestTimeoutFinite(_WsCase):
    def test_env_float_rejects_nonfinite(self):
        os.environ["NOVA_PROBE_TIMEOUT"] = "nan"
        try:
            self.assertEqual(nova_probe._env_float("NOVA_PROBE_TIMEOUT",
                                                   8.0), 8.0)
            os.environ["NOVA_PROBE_TIMEOUT"] = "inf"
            self.assertEqual(nova_probe._env_float("NOVA_PROBE_TIMEOUT",
                                                   8.0), 8.0)
        finally:
            os.environ.pop("NOVA_PROBE_TIMEOUT", None)

    def test_smoke_runs_normally_with_nan_timeout(self):
        (self.ws / "x.py").write_text("print('hi')\n", encoding="utf-8")
        os.environ["NOVA_PROBE_TIMEOUT"] = "nan"
        try:
            r = nova_probe.smoke_one(self.ws, "x.py", False, False)
        finally:
            os.environ.pop("NOVA_PROBE_TIMEOUT", None)
        self.assertEqual(r.get("level"), "pass", r)


# =====================================================================
# 9 + 10 + 11. /api/settings honesty (real server, loopback only)
# =====================================================================
def _reset_web_guards():
    try:
        import nova_security as _nsec
        _nsec.API_LIMITER.reset()
        _nsec.SECURE_API_LIMITER.reset()
        _nsec.AUTH_THROTTLE.reset()
    except Exception:
        pass


class TestSettingsHonesty(unittest.TestCase):
    def setUp(self):
        _reset_web_guards()
        self._td = tempfile.TemporaryDirectory()
        workspace = Path(self._td.name)
        self.gfile = workspace / ".nova" / "guardian.json"
        self.gfile.parent.mkdir(parents=True, exist_ok=True)
        self.gfile.write_text(json.dumps({"on": True}), encoding="utf-8")
        web_server.STATE = web_server._State(workspace)
        web_server.AUTH_TOKEN = None
        self.httpd = web_server._make_server({"host": "127.0.0.1",
                                              "port": 0})
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=5)
        finally:
            web_server.STATE = None
            web_server.AUTH_TOKEN = None
            self._td.cleanup()

    def post(self, payload):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(payload)
        c.request("POST", "/api/settings", body=body, headers={
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:%d" % self.port})
        r = c.getresponse()
        out = (r.status, r.read().decode("utf-8"))
        c.close()
        return out

    def test_truthy_string_never_fires_the_reset(self):
        status, body = self.post({"guardian_reset": "no"})
        self.assertEqual(status, 400, body)
        self.assertTrue(self.gfile.exists(),
                        "garbage must not wipe the settings")

    def test_real_boolean_still_resets(self):
        status, _body = self.post({"guardian_reset": True})
        self.assertEqual(status, 200)
        self.assertFalse(self.gfile.exists(), "a real true resets")

    def test_non_bool_session_toggle_is_rejected(self):
        status, body = self.post({"confirm_changes": "true"})
        self.assertEqual(status, 400, body)
        self.assertIn("must be a boolean", body)

    def test_missing_layer_answers_501(self):
        saved = web_server.nova.ctxengine
        web_server.nova.ctxengine = None
        try:
            status, body = self.post({"ctx_local": 4096})
            self.assertEqual(status, 501, body)
            self.assertIn("unavailable", body)
        finally:
            web_server.nova.ctxengine = saved

    def test_valid_toggle_still_round_trips(self):
        status, _body = self.post({"guardian_on": False})
        self.assertEqual(status, 200)
        saved = json.loads(self.gfile.read_text(encoding="utf-8"))
        self.assertFalse(saved["on"], "the panel toggle persists")


# =====================================================================
# 13. the loop-guard flag starts fresh on every offer_apply call
# =====================================================================
class TestBatchRefusedFresh(_WsCase):
    def test_successful_apply_clears_a_stale_flag(self):
        self.sess.batch_refused = True    # stale from an earlier turn
        files, _ = nova.parse_files(
            "=== FILE: ok.js ===\nvar a = 1;\n=== END ===\n")
        with _quiet():
            nova.offer_apply(self.sess, files, [], auto=True)
        self.assertFalse(getattr(self.sess, "batch_refused", None),
                         "a fresh batch is not a refusal")

    def test_a_real_refusal_still_sets_the_flag(self):
        nova.NONINTERACTIVE = False   # the refusal lives on the apply path
        files, _ = nova.parse_files(
            "=== FILE: broken.py ===\ndef f(:\n=== END ===\n")
        with _quiet():
            nova.offer_apply(self.sess, files, [], auto=True)
        self.assertTrue(getattr(self.sess, "batch_refused", False),
                        "a real gate refusal keeps the guard honest")


# =====================================================================
# release pins
# =====================================================================
class TestReleasePins(unittest.TestCase):
    def test_version(self):
        self.assertEqual(nova.VERSION, "8.12.0")
        self.assertEqual(nova.CODENAME, "master switch")


if __name__ == "__main__":
    unittest.main()
