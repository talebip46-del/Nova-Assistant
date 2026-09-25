#!/usr/bin/env python3
"""v6.2.1 regression tests - every test here pins one REAL bug found in
the v6.2 audit and fixed in this release:

  - ctx window: the final fallback could go DEAD (guard `200 < room`) so
    the prompt still overflowed exactly when it was most over budget
  - build_map: "... and N more files" was unreachable (walk broke early)
  - flow.delete: path traversal (name was never validated)
  - web /api/flow*: a ModuleError used to escape -> connection DROPPED
    with no HTTP response at all
  - nova_bg: timeout never fired while a silent child was alive
  - snapshots: binary files were silently corrupted (utf-8 + replace) and
    /restore deleted dotfiles/novaignored files it never captured
  - search: NOVA_ALLOW_PRIVATE_FETCH=1 could not unlock localhost
  - providers: _anthropic_split raised a raw KeyError on missing content
  - cost: a hand-edited ts=null row crashed /cost and record()
  - pixelart: PNG gallery never pruned
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova


APP = Path(__file__).resolve().parent.parent


class TestCtxFallbackAlwaysFires(unittest.TestCase):
    """The old guard `200 < room` made step 8 DEAD when the system core
    alone exceeded the budget (e.g. NOVA_NUM_CTX=2048): the oversized
    prompt was sent anyway and llama.cpp dropped the OLDEST tokens."""

    def test_tiny_window_still_trims_the_user_message(self):
        old_ctx = nova.NUM_CTX
        nova.NUM_CTX = 2048          # the value /disk itself recommends!
        try:
            with tempfile.TemporaryDirectory() as td:
                sess = nova.Session(Path(td))
                huge = ("=== FILE: big.py ===\n" + "x" * 60_000
                        + "\n=== END ===")
                msgs = sess.build_messages(huge)
                sent = msgs[-1]["content"]
                self.assertLess(len(sent), len(huge) / 2,
                                "even with a tiny window the user message "
                                "must be trimmed, never sent raw")
        finally:
            nova.NUM_CTX = old_ctx


class TestBuildMapOverflowNote(unittest.TestCase):
    def test_extra_files_are_counted_and_disclosed(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            for i in range(nova.MAP_MAX_FILES + 7):
                (ws / f"f{i:03d}.py").write_text("x = %d\n" % i,
                                                 encoding="utf-8")
            m = nova.build_map(ws)
            self.assertIn("and 7 more files", m)


class TestFlowDeleteTraversal(unittest.TestCase):
    def test_delete_rejects_invalid_names(self):
        from nova_modules import flow, ModuleError
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            victim = ws / "victim.json"
            victim.write_text("{}", encoding="utf-8")
            for bad in ("../../victim", "../victim", "", "a/b", "..",
                        "../../../../../etc/passwd"):
                with self.assertRaises(ModuleError):
                    flow.delete(ws, bad)
            self.assertTrue(victim.exists(), "no file outside the flows "
                                             "dir may ever be removed")
            # a legit name still works (and a missing one returns False)
            self.assertFalse(flow.delete(ws, "does-not-exist"))

    def test_get_rejects_empty_name(self):
        from nova_modules import flow, ModuleError
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ModuleError):
                flow.get(Path(td), "")


class TestWebFlowEndpointsFailClean(unittest.TestCase):
    """A ModuleError must become a 400 JSON response - not a dropped
    connection with zero bytes."""

    @classmethod
    def setUpClass(cls):
        import web_server
        import threading
        # v6.8.2: enable the modules - these tests pin the REAL /api/flow*
        # error paths, not the kill-switch 403 (see test_v682).
        os.environ["NOVA_DISABLED_MODULES"] = ""
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_v621_"))
        web_server.nova = nova
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        cls.httpd = web_server._make_server(args)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        import urllib.request, urllib.error
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def _post(self, path, obj):
        import urllib.request, urllib.error
        req = urllib.request.Request(
            self.base + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_flow_list_with_empty_name_returns_400(self):
        code, body = self._get("/api/flow")
        self.assertEqual(code, 400)
        self.assertIn("error", body)

    def test_flow_list_with_traversal_name_returns_400(self):
        code, body = self._get("/api/flow?name=" + "../..%2F..")
        self.assertEqual(code, 400)

    def test_flow_run_with_invalid_name_returns_400(self):
        code, body = self._post("/api/flow/run", {})
        self.assertEqual(code, 400)
        self.assertIn("error", body)

    def test_flow_delete_with_traversal_returns_400(self):
        code, body = self._post("/api/flow/delete",
                                {"name": "../../victim"})
        self.assertEqual(code, 400)


class TestBgTimeoutActuallyFires(unittest.TestCase):
    def test_silent_child_is_killed_at_deadline(self):
        import nova_bg
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            t0 = time.time()
            tid, err = nova_bg.start(ws, "sleep 5 && echo done", timeout=1)
            self.assertEqual(err, "")
            deadline = t0 + 12
            status = "running"
            while time.time() < deadline:
                m = nova_bg.get_task(ws, tid)
                status = m.get("status")
                if status != "running":
                    break
                time.sleep(0.1)
            self.assertNotEqual(status, "running",
                                "the timeout must fire even while the "
                                "child produces no output")
            self.assertLess(time.time() - t0, 5.0,
                            "a 1s timeout must not take ~5s")
            m = nova_bg.get_task(ws, tid)
            self.assertEqual(m.get("status"), "failed")
            self.assertIn("timeout", "\n".join(
                (nova_bg._log_path(ws, tid).read_text(
                    encoding="utf-8", errors="replace")).splitlines()[-1:]))


class TestSnapshotsBinaryAndSweep(unittest.TestCase):
    def test_binary_file_roundtrips_byte_exact(self):
        import nova_snapshots as snaps
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            png = ws / "img.png"
            original = bytes(range(256)) * 8 + b"\x89PNG\r\n\x1a\n\x00\x01"
            png.write_bytes(original)
            uid, err, _sk = snaps.make_manual(ws, label="t")
            self.assertEqual(err, "")
            png.write_bytes(b"corrupted \x00\x01\x02")
            meta = snaps.find_manual(ws, uid)
            res = snaps.restore_manual(ws, meta)
            self.assertIn("img.png", res["written"])
            self.assertEqual(png.read_bytes(), original,
                             "binary content must survive a checkpoint "
                             "round-trip byte-exact")

    def test_restore_never_deletes_dotfiles_or_ignored_files(self):
        import nova_snapshots as snaps
        from nova_policy import NovaIgnore
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "keep.txt").write_text("v1", encoding="utf-8")
            uid, err, _sk = snaps.make_manual(ws, label="t")
            self.assertEqual(err, "")
            ts = time.time() + 2
            os.utime(ws / "keep.txt", (ts, ts))
            # files the checkpoint NEVER captures - /restore must leave
            # them alone even though they are newer than the snapshot
            secret = ws / ".env"
            secret.write_text("SECRET=1", encoding="utf-8")
            os.utime(secret, (ts, ts))
            (ws / ".novaignore").write_text("data.csv\n", encoding="utf-8")
            ignored = ws / "data.csv"
            ignored.write_text("a,b\n1,2\n", encoding="utf-8")
            os.utime(ignored, (ts, ts))
            nm = ws / "node_modules"
            nm.mkdir()
            (nm / "lib.js").write_text("x", encoding="utf-8")
            meta = snaps.find_manual(ws, uid)
            res = snaps.restore_manual(ws, meta,
                                       ignore=NovaIgnore.load(ws))
            self.assertTrue(secret.exists(), ".env must survive /restore")
            self.assertEqual(secret.read_text(encoding="utf-8"), "SECRET=1")
            self.assertTrue(ignored.exists(),
                            ".novaignore-matched files must survive")
            self.assertTrue((nm / "lib.js").exists())
            self.assertIn("keep.txt", res["written"])

    def test_failed_undo_keeps_the_unit(self):
        import nova_snapshots as snaps
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            f = ws / "a.txt"
            f.write_text("original", encoding="utf-8")
            target_backup = ws / ".nova_backups" / "sim.bak"
            target_backup.parent.mkdir(parents=True, exist_ok=True)
            target_backup.write_text("original", encoding="utf-8")
            uid, err = snaps.push_auto_unit(ws, [(f, target_backup)])
            self.assertEqual(err, "")
            # the copy INSIDE the unit disappears (disk issue / tampering)
            unit = snaps.root(ws, snaps.AUTO_KIND) / uid
            for p in unit.iterdir():
                if p.name != "meta.json":
                    p.unlink()
            res = snaps.undo_units(ws, 1)
            self.assertTrue(res["errors"], "the missing backup must be "
                                           "reported, not swallowed")
            units = snaps.list_units(ws, snaps.AUTO_KIND)
            self.assertEqual(len(units), 1,
                             "a failed unit must stay retryable")


class TestSearchSsrfEscapeHatch(unittest.TestCase):
    def test_env_var_unlocks_localhost(self):
        import nova_search as ns
        old = os.environ.get("NOVA_ALLOW_PRIVATE_FETCH")
        try:
            os.environ["NOVA_ALLOW_PRIVATE_FETCH"] = "1"
            self.assertFalse(ns._host_is_private("localhost"))
            self.assertFalse(ns._host_is_private("127.0.0.1"))
        finally:
            if old is None:
                os.environ.pop("NOVA_ALLOW_PRIVATE_FETCH", None)
            else:
                os.environ["NOVA_ALLOW_PRIVATE_FETCH"] = old
        self.assertTrue(ns._host_is_private("localhost"))


class TestAnthropicSplitDegrades(unittest.TestCase):
    def test_missing_content_is_empty_string_not_keyerror(self):
        import nova_providers as providers
        # v6.7: _anthropic_split now returns (system, rest, split_at)
        sys_text, rest, split_at = providers._anthropic_split(
            [{"role": "system"}, {"role": "user", "content": "hi"}])
        self.assertEqual(sys_text, "")
        self.assertEqual(len(rest), 1)
        self.assertEqual(split_at, 0)


class TestCostRowWithBrokenTs(unittest.TestCase):
    def test_null_ts_row_does_not_crash(self):
        import nova_cost as nc
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            p = nc.costs_path(ws)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"log": [
                {"ts": None, "provider": "ollama", "model": "m",
                 "ptok": 1, "ctok": 1, "actual": False, "ok": True,
                 "dur": 1.0, "cost": 0.0},
            ], "archived": []}), encoding="utf-8")
            stats = nc.report(ws)
            self.assertTrue("today" in stats or "all" in stats or
                            isinstance(stats, dict))
            nc.record(ws, "ollama", "m", 2, 2, dur_s=1.0)   # archive path
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(data["log"]) + len(data["archived"]), 1)


class TestPixelGalleryPruned(unittest.TestCase):
    def test_png_count_is_capped_like_grid_json(self):
        from nova_modules import pixelart
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            for i in range(pixelart.SAVED_GRIDS + 3):
                pixelart.generate(ws, "castle %d" % i, size=8,
                                  seed="s%d" % i, scale=1)
            base = pixelart.module_data_dir(ws, "pixel", create=False)
            self.assertLessEqual(len(list(base.glob("pixel-*.png"))),
                                 pixelart.SAVED_GRIDS,
                                 "the pixel PNG gallery must be pruned")
            self.assertLessEqual(len(list(base.glob("pixel-*.json"))),
                                 pixelart.SAVED_GRIDS)


class TestNovaWorkspaceEnvHonored(unittest.TestCase):
    def test_main_terminal_default_reads_env(self):
        # the agent face and the module face must agree on the workspace
        old = os.environ.get("NOVA_WORKSPACE")
        try:
            os.environ["NOVA_WORKSPACE"] = "from-env"
            src = (APP / "nova.py").read_text(encoding="utf-8")
            self.assertIn('os.environ.get("NOVA_WORKSPACE"', src,
                          "nova.py must honor NOVA_WORKSPACE like the "
                          "modules do")
        finally:
            if old is None:
                os.environ.pop("NOVA_WORKSPACE", None)
            else:
                os.environ["NOVA_WORKSPACE"] = old


class TestEscHtmlQuote(unittest.TestCase):
    def test_index_escapes_single_quotes(self):
        html = (APP / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("&#39;", html,
                      "escHtml must escape single quotes (attribute XSS)")


if __name__ == "__main__":
    unittest.main()
