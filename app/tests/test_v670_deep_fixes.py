#!/usr/bin/env python3
# =====================================================================
#  Nova v6.7.0 regression tests - the "search every file, fix every bug"
#  round: dead HTTPS pinning, screening bypasses, recycled-pid kills,
#  snapshot byte-corruption, vault tmp collisions, skills slug collapse,
#  provider discovery/economy fixes, cross-process locks, web fixes.
#  Everything is offline: network calls are monkeypatched, never opened.
# =====================================================================
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# APP dir must always resolve relative to THIS file - never hardcode a
# machine-specific absolute path (that broke the suite on every new host).
_APP_DIR = Path(__file__).resolve().parent.parent

import nova_search as ns                       # noqa: E402
import nova_security as nsec                   # noqa: E402
import nova_snapshots as snaps                 # noqa: E402
import nova_atomic as natom                    # noqa: E402
import nova_economy as econ                    # noqa: E402
import nova_providers as providers             # noqa: E402
import nova_skills as skills                   # noqa: E402
import nova_bg                                 # noqa: E402
import nova_council as council                 # noqa: E402
import nova                                    # noqa: E402


def _reset_cfg():
    providers._ACTIVE["name"] = None
    providers._MODEL_OVERRIDES.clear()
    with providers._CFG_LOCK:
        providers._CFG.update({"ws": None, "keys": {}, "custom": [],
                               "routing": {}, "economy": {},
                               "discovered": {}})


class _WSTestCase(unittest.TestCase):
    def setUp(self):
        _reset_cfg()
        self._env = mock.patch.dict("os.environ", {}, clear=True)
        self._env.start()
        self.ws = Path(tempfile.mkdtemp(prefix="nova_v670_"))
        providers.load_config(self.ws)

    def tearDown(self):
        self._env.stop()
        _reset_cfg()


# =====================================================================
# 1. CRITICAL: the HTTPS pinned connection was dead since v6.5
#    (borrowed connect() bound super() to the wrong class -> TypeError
#    on EVERY https fetch)
# =====================================================================
class TestHttpsPinnedConnection(unittest.TestCase):
    def test_connect_reaches_https_base_not_typeerror(self):
        called = []
        orig = http.client.HTTPSConnection.connect

        def fake_base(self):
            called.append("base")
            raise OSError("stop here - base was reached")
        http.client.HTTPSConnection.connect = fake_base
        try:
            c = ns._PinnedHTTPSConnection("example.com")
            with self.assertRaises(OSError):
                c.connect()
        finally:
            http.client.HTTPSConnection.connect = orig
        self.assertEqual(called, ["base"])

    def test_http_variant_still_works(self):
        called = []
        orig = http.client.HTTPConnection.connect

        def fake_base(self):
            called.append("base")
            raise OSError("stop here")
        http.client.HTTPConnection.connect = fake_base
        try:
            c = ns._PinnedHTTPConnection("example.com")
            with self.assertRaises(OSError):
                c.connect()
        finally:
            http.client.HTTPConnection.connect = orig
        self.assertEqual(called, ["base"])


# =====================================================================
# 2. CRITICAL: command screening bypasses
# =====================================================================
class TestScreeningBypasses(unittest.TestCase):
    def test_sh_c_double_quoted_payload_is_screened(self):
        self.assertEqual(nsec.screen('sh -c "rm -rf /"')["verdict"], "deny")
        self.assertEqual(nsec.screen('bash -c "echo hi && rm -rf /"')["verdict"],
                         "deny")

    def test_cmd_and_powershell_dquote_payload_screened(self):
        self.assertNotEqual(nsec.screen('cmd /c "rd /s /q C:\\"')["verdict"],
                            "allow")
        self.assertNotEqual(
            nsec.screen('powershell -Command "Remove-Item -Recurse -Force C:\\"')
            ["verdict"], "allow")
        self.assertNotEqual(nsec.screen('pwsh -command "rm -rf /"')["verdict"],
                            "allow")

    def test_backslash_before_closing_quote_no_longer_hides_tail(self):
        # "\\" used to swallow the real closing quote -> whole tail vanished
        r = nsec.screen('echo "a\\\\" && rm -rf /')
        self.assertEqual(r["verdict"], "deny")

    def test_benign_commands_still_allow(self):
        for c in ('git commit -m "rm -rf /"', 'echo "hello world"',
                  'python test_invite.py', 'npm run invite', 'ls -la',
                  'git log --oneline', 'rmdir build', 'rm -r old_dir'):
            self.assertEqual(nsec.screen(c)["verdict"], "allow", c)

    def test_powershell_delete_aliases_dash_flags(self):
        for c in ("rmdir -Recurse -Force C:\\", "del -Recurse -Force C:\\",
                  "rd -Recurse -Force C:\\", "rm -Recurse -Force C:\\"):
            self.assertEqual(nsec.screen(c)["verdict"], "deny", c)
        # POSIX rm without force stays unflagged
        self.assertEqual(nsec.screen("rm -r old_dir")["verdict"], "allow")


# =====================================================================
# 3. HIGH: nova_bg - recycled pid kill guard, zombie liveness,
#    secure-mode web gate, concurrency race
# =====================================================================
class TestBgSafety(unittest.TestCase):
    def test_kill_refuses_recycled_pid(self):
        """The recorded pid (our own process here) no longer matches the
        task's command -> nothing is signalled, the task is marked died."""
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_bg_"))
        with mock.patch.object(nova_bg, "_PROCS", {}):
            meta = {"id": "b9001", "cmd": "sleep 999", "pid": __import__("os").getpid(),
                    "status": "running", "started": int(time.time())}
            nova_bg._write_meta(ws, meta)
            msg = nova_bg.kill(ws, "b9001")
            self.assertIn("no longer matches", msg)
            self.assertEqual(nova_bg.get_task(ws, "b9001")["status"], "died")

    def test_pid_matches_cmd_positive_and_negative(self):
        if not Path("/proc/self/cmdline").is_file():
            self.skipTest("/proc not available")
        import os as _os
        import subprocess as _sp
        p = _sp.Popen(["sleep", "99"])
        try:
            self.assertTrue(nova_bg._pid_matches_cmd(p.pid, "sleep 99"))
        finally:
            p.kill()
            p.wait()
        self.assertFalse(nova_bg._pid_matches_cmd(10 ** 7, "anything"))

    def test_alive_false_for_nonexistent_pid(self):
        self.assertFalse(nova_bg._alive(10 ** 7))

    def test_web_origin_confirm_blocked_in_secure_mode(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_bg2_"))
        old = nsec.set_secure(True, ws=ws)
        try:
            tid, err = nova_bg.start(ws, "rm -rf build", origin="web",
                                     approved=True)
            self.assertEqual(tid, "")
            self.assertIn("secure mode", err)
        finally:
            nsec.set_secure(old, ws=ws)


# =====================================================================
# 4. HIGH: snapshots corrupted every text file on restore
# =====================================================================
class TestSnapshotByteExactness(unittest.TestCase):
    def _roundtrip(self, ws):
        uid, err, _sk = snaps.make_manual(ws, "t")
        self.assertEqual(err, "")
        meta = snaps.find_manual(ws, uid)
        res = snaps.restore_manual(ws, meta)
        self.assertEqual(res["errors"], [])
        return res

    def test_crlf_survives_roundtrip(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_sn_"))
        (ws / "win.txt").write_bytes(b"line1\r\nline2\r\n")
        self._roundtrip(ws)
        self.assertEqual((ws / "win.txt").read_bytes(), b"line1\r\nline2\r\n")

    def test_non_utf8_text_survives_roundtrip(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_sn2_"))
        raw = b"caf\xe9 na\xefve\n"
        (ws / "latin.txt").write_bytes(raw)
        self._roundtrip(ws)
        self.assertEqual((ws / "latin.txt").read_bytes(), raw)

    def test_cap_overflow_files_not_deleted_by_restore(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_sn3_"))
        for i in range(3):
            (ws / ("f%d.txt" % i)).write_text("x" * 10)
        # a file that exists at snapshot time but lands beyond the cap:
        # v6.7 records it as a skip entry, so /restore must NOT delete it
        (ws / "capped.txt").write_text("existed at snapshot time")
        with mock.patch.object(snaps, "MAX_CHECKPOINT_FILES", 1):
            uid, err, skipped = snaps.make_manual(ws, "cap")
            self.assertEqual(err, "")
            self.assertTrue(any("file cap" in s for s in skipped))
        # a genuinely new file IS deleted (honest back-in-time semantics)
        (ws / "newer.txt").write_text("created after")
        res = snaps.restore_manual(ws, snaps.find_manual(ws, uid))
        self.assertTrue((ws / "capped.txt").exists())
        self.assertFalse((ws / "newer.txt").exists())

    def test_metaless_units_pruned(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_sn4_"))
        dead = snaps.root(ws, snaps.MANUAL_KIND) / "20200101_000000_0000"
        dead.mkdir(parents=True)
        import os
        old = time.time() - 2 * 86400
        os.utime(dead, (old, old))
        snaps._prune(ws)
        self.assertFalse(dead.exists())


# =====================================================================
# 5. HIGH: fixed .tmp names could publish torn vaults across processes
# =====================================================================
class TestAtomicWrites(unittest.TestCase):
    def test_tmp_names_unique(self):
        seen = {natom.tmp_name(Path("/x/a.json")) for _ in range(50)}
        self.assertEqual(len(seen), 50)

    def test_write_text_atomic_roundtrip_and_no_leftovers(self):
        d = Path(tempfile.mkdtemp(prefix="nova_v670_at_"))
        p = d / "store.json"
        self.assertEqual(natom.write_text_atomic(p, '{"a": 1}'), "")
        self.assertEqual(p.read_text(), '{"a": 1}')
        self.assertEqual([q.name for q in d.iterdir()], ["store.json"])

    def test_file_lock_mutual_exclusion(self):
        d = Path(tempfile.mkdtemp(prefix="nova_v670_lk_"))
        lockp = d / "l.lock"
        counter = {"n": 0}
        gate = threading.Lock()

        def worker():
            with natom.file_lock(lockp, timeout=5.0):
                with gate:
                    counter["n"] += 1
                    peak = counter["n"]
                time.sleep(0.02)
                with gate:
                    counter["n"] -= 1
                    self.assertEqual(peak, 1)

        ts = [threading.Thread(target=worker) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(counter["n"], 0)

    def test_provider_vault_save_leaves_no_tmp(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_vlt_"))
        providers.load_config(ws)
        self.assertEqual(providers.set_economy(ws, {"cache": False}), "")
        nova_dir = ws / ".nova"
        leftovers = [p.name for p in nova_dir.glob("providers.*tmp*")]
        self.assertEqual(leftovers, [])
        # the vault is still valid JSON
        json.loads((nova_dir / "providers.json").read_text())


# =====================================================================
# 6. nova_economy: cap conflict no longer wipes the cache + LRU
# =====================================================================
class TestEconomyCapAndLRU(unittest.TestCase):
    def test_store_over_old_cap_keeps_counters(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_eco_"))
        econ.bump(ws, "cache_hits", 7)
        # a store much larger than the old 2MB cap must still load
        big = "x" * 90_000
        for i in range(30):
            econ.cache_put(ws, "k%d" % i, big)
        st = econ.stats(ws)
        self.assertEqual(st["counters"]["cache_hits"], 7)
        self.assertEqual(st["cache_entries"], 30)

    def test_size_cap_trims_oldest_not_counters(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_eco2_"))
        econ.bump(ws, "tokens_saved", 99)
        with mock.patch.object(econ, "MAX_CACHE_FILE_BYTES", 50_000):
            for i in range(10):
                econ.cache_put(ws, "k%d" % i, "y" * 9_000)
        st = econ.stats(ws)
        self.assertLess(st["cache_entries"], 10)
        self.assertEqual(st["counters"]["tokens_saved"], 99)

    def test_hit_refreshes_recency(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_eco3_"))
        econ.cache_put(ws, "a", "A", max_entries=2)
        econ.cache_put(ws, "b", "B", max_entries=2)
        self.assertIsNotNone(econ.cache_get(ws, "a"))   # refresh a
        econ.cache_put(ws, "c", "C", max_entries=2)      # evicts b
        self.assertIsNotNone(econ.cache_get(ws, "a"))
        self.assertIsNone(econ.cache_get(ws, "b"))
        self.assertIsNotNone(econ.cache_get(ws, "c"))


# =====================================================================
# 7. nova_providers: discovery / customs / anthropic caching
# =====================================================================
class TestProviderDiscovery(unittest.TestCase):
    def test_empty_fetch_keeps_stale_cache(self):
        providers._ACTIVE["name"] = None
        with providers._CFG_LOCK:
            providers._CFG["ws"] = None
            providers._CFG["keys"]["openai"] = "sk-test"
            providers._CFG["discovered"]["openai"] = {
                "ts": int(time.time()) - 100, "models": ["gpt-old"]}
        with mock.patch.object(providers, "_get_json",
                               return_value={"data": []}):
            out = providers._discover_fetch("openai", time.time(),
                                            ["gpt-old"], 1)
        self.assertEqual(out, ["gpt-old"])
        with providers._CFG_LOCK:
            self.assertEqual(providers._CFG["discovered"]["openai"]["models"],
                             ["gpt-old"])

    def test_pagination_params_present(self):
        url_a, _ = providers._models_endpoint(
            {"kind": "anthropic", "base": "https://api.anthropic.com",
             "key": "k"})
        self.assertIn("limit=1000", url_a)
        url_g, _ = providers._models_endpoint(
            {"kind": "gemini", "base": "https://generativelanguage.googleapis.com/v1beta",
             "key": "k"})
        self.assertIn("pageSize=1000", url_g)

    def test_get_json_read_is_capped(self):
        src = Path(providers.__file__).read_text()
        self.assertIn("read(4_000_000)", src)


class TestCustomProviders(_WSTestCase):
    def test_add_custom_rejects_model_the_loader_would_drop(self):
        err = providers.add_custom(self.ws, "relay1", "https://x.example/v1",
                                   model="llama 3.1 (latest)")
        self.assertTrue(err)
        # a good model still saves
        self.assertEqual(providers.add_custom(
            self.ws, "relay2", "https://x.example/v1", model="qwen2.5:7b"), "")

    def test_loader_keeps_provider_strips_bad_model(self):
        cleaned = providers._clean_custom_list(
            [{"name": "relay3", "base": "https://x.example/v1",
              "kind": "openai", "model": "bad (model)", "label": ""}])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["model"], "")


class TestAnthropicCacheSplit(unittest.TestCase):
    def test_split_returns_three_parts(self):
        system, rest, split_at = providers._anthropic_split([
            {"role": "system", "content": "STABLE" + "DYNAMIC",
             "cache_split_at": 6},
            {"role": "user", "content": "hi"}])
        self.assertEqual(system, "STABLE" + "DYNAMIC")
        self.assertEqual(split_at, 6)
        self.assertEqual(len(rest), 1)

    def test_stream_builds_stable_plus_dynamic_blocks(self):
        captured = {}

        def fake_request(url, payload, headers):
            captured["payload"] = payload
            return url

        class FakeResp:
            def __enter__(self):
                return iter([b"data: {\"type\":\"content_block_delta\","
                             b"\"delta\":{\"type\":\"text_delta\","
                             b"\"text\":\"ok\"}}\n\n"])

            def __exit__(self, *a):
                return False

        with mock.patch.object(providers, "_request", fake_request), \
                mock.patch.object(providers.urllib.request, "urlopen",
                                  lambda req, timeout=None: FakeResp()):
            cfg = {"kind": "anthropic", "name": "anthropic",
                   "base": "https://api.anthropic.com", "key": "k"}
            out = list(providers._anthropic_stream(
                cfg, "claude-x",
                [{"role": "system", "content": "CORE" + "MAPSTUFF",
                  "cache_split_at": 4},
                 {"role": "user", "content": "hi"}], 0.2, 5))
        self.assertEqual(out, ["ok"])
        blocks = captured["payload"]["system"]
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["text"], "CORE")
        self.assertIn("cache_control", blocks[0])
        self.assertEqual(blocks[1]["text"], "MAPSTUFF")
        self.assertNotIn("cache_control", blocks[1])


# =====================================================================
# 8. nova_council: vault keys + custom providers as partner
# =====================================================================
class TestCouncilPartner(_WSTestCase):
    def test_default_partner_sees_vault_key(self):
        with providers._CFG_LOCK:
            providers._CFG["keys"]["groq"] = "gsk_test"
        name, model, label = council.resolve_partner(
            "", "ollama", "llama3", providers)
        self.assertEqual(name, "groq")
        self.assertTrue(model)

    def test_custom_provider_spec_resolves(self):
        providers.add_custom(self.ws, "myrelay", "https://r.example/v1",
                             model="qwen:7b")
        name, model, _label = council.resolve_partner(
            "myrelay", "ollama", "llama3", providers)
        self.assertEqual(name, "myrelay")
        self.assertEqual(model, "qwen:7b")


# =====================================================================
# 9. nova.py: local-server budget exemption + server-hint matching
# =====================================================================
class TestNovaHelpers(unittest.TestCase):
    def test_is_free_local(self):
        self.assertTrue(nova._is_free_local({"kind": "ollama"}))
        self.assertTrue(nova._is_free_local(
            {"kind": "openai", "base": "http://127.0.0.1:8080/v1"}))
        self.assertTrue(nova._is_free_local(
            {"kind": "openai", "base": "http://localhost:1234/v1"}))
        self.assertFalse(nova._is_free_local(
            {"kind": "openai", "base": "https://api.example.com/v1"}))

    def test_looks_like_server_word_boundaries(self):
        self.assertFalse(nova._looks_like_server("python test_invite.py"))
        self.assertFalse(nova._looks_like_server("npm run invite"))
        self.assertTrue(nova._looks_like_server("vite dev"))
        self.assertTrue(nova._looks_like_server("npm run dev"))
        self.assertTrue(nova._looks_like_server(
            "python -m http.server 8000"))

    def test_prompt_ctx_follows_coding_route(self):
        sess = nova.Session.__new__(nova.Session)
        stub = SimpleNamespace(resolve_route=lambda s: (
            {"kind": "groq"}, "m") if s == "coding" else (None, ""))
        old_providers = nova.providers
        nova.providers = stub
        try:
            self.assertEqual(sess._prompt_ctx(),
                             max(2048, nova._envint("NOVA_CLOUD_CTX", 16384)))
        finally:
            nova.providers = old_providers

    def test_custom_cmd_kind_argument_reaches_add(self):
        captured = {}

        class StubProviders:
            def customs(self):
                return []
            def key_status(self, n):
                return (False, "")
            def add_custom(self, ws, name, base, model="", kind="openai"):
                captured.update(name=name, base=base, model=model, kind=kind)
                return ""
            def del_custom(self, ws, n):
                return ""
        old = nova.providers
        nova.providers = StubProviders()
        try:
            sess = SimpleNamespace(ws=Path(tempfile.mkdtemp()))
            nova.cmd_custom(sess, "add relay https://x.example/v1 "
                                  "my-model anthropic")
        finally:
            nova.providers = old
        self.assertEqual(captured.get("kind"), "anthropic")
        self.assertEqual(captured.get("model"), "my-model")


# =====================================================================
# 10. nova_skills: Persian auto-skills no longer collapse to one name
# =====================================================================
class TestSkillsSlug(unittest.TestCase):
    def test_distinct_persian_requests_make_distinct_skills(self):
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_sk_"))
        old = skills.AUTO_THRESHOLD
        skills.AUTO_THRESHOLD = 1
        try:
            r1 = skills.record_success(ws, "ساخت صفحه لاگین برای سایت")
            r2 = skills.record_success(ws, "افزودن جستجو به فروشگاه")
            n1 = r1.split(":", 1)[1]
            n2 = r2.split(":", 1)[1]
            self.assertNotEqual(n1, n2)
            self.assertTrue(n1.startswith("auto-"))
        finally:
            skills.AUTO_THRESHOLD = old


# =====================================================================
# 11. nova_log is actually wired into the session
# =====================================================================
class TestLogWiring(unittest.TestCase):
    def test_session_init_configures_log_sink(self):
        import nova_log
        src = Path(nova.__file__).read_text()
        self.assertIn("nova_log.configure(self.ws)", src)
        self.assertIn("nova_log.configure(p)", src)


# =====================================================================
# 12. flow: CLI runs keep a real id; knowledge: dirs + reset lock
# =====================================================================
class TestFlowAndKnowledge(unittest.TestCase):
    def test_persist_allocates_run_id(self):
        from nova_modules import flow
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_fl_"))
        r = SimpleNamespace(flow={"name": "f"}, status="failed", error="",
                            log=[], vars={}, started=1)
        snap = flow._persist(ws, r, run_id=None)
        self.assertTrue(snap["id"])
        self.assertTrue((flow.runs_dir(ws) / (snap["id"] + ".json")).is_file())

    def test_knowledge_ingest_accepts_directory(self):
        from nova_modules import knowledge
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_kn_"))
        (ws / "docs").mkdir()
        (ws / "docs" / "a.md").write_text("hello world " * 50)
        r = knowledge.ingest(ws, ["docs"])
        self.assertEqual(r["files"], 1)
        self.assertGreaterEqual(len(knowledge.search(ws, "hello world")), 1)

    def test_knowledge_reset_clears_everything(self):
        from nova_modules import knowledge
        ws = Path(tempfile.mkdtemp(prefix="nova_v670_kn2_"))
        (ws / "a.txt").write_text("abc " * 100)
        knowledge.ingest(ws, ["a.txt"])
        self.assertEqual(knowledge.reset(ws)["removed"], 2)
        self.assertEqual(knowledge.stats(ws)["chunks"], 0)

    def test_flow_run_failed_exits_nonzero(self):
        src = (_APP_DIR / "nova_assistant.py").read_text()
        self.assertIn('snap.get("status") == "failed"', src)


# =====================================================================
# 13. web layer: workspace keying + run guard + routing select
# =====================================================================
class TestWebFace(unittest.TestCase):
    def _index(self):
        return (_APP_DIR / "web" / "index.html").read_text(encoding="utf-8")

    def test_history_keyed_on_full_workspace_path(self):
        self.assertIn('info.workspace || info.workspace_name', self._index())

    def test_refreshinfo_rejects_error_bodies(self):
        self.assertIn("if(!res.ok){ throw new Error", self._index())

    def test_run_command_guards_against_talk_busy(self):
        src = self._index()
        self.assertLess(src.index("async function runCommand"),
                        src.index("talkBusy){ showError", src.index(
                            "async function runCommand")))

    def test_pending_notice_survives_finally(self):
        src = self._index()
        self.assertIn("pendingNote", src)
        self.assertIn("if(pendingNote){", src)

    def test_routing_select_keeps_saved_model(self):
        self.assertIn("(ذخیره‌شده)", self._index())

    def test_typed_keys_preserved_across_reload(self):
        self.assertIn("prevKeys", self._index())

    def test_security_headers_on_favicon_route(self):
        src = (_APP_DIR / "web_server.py").read_text()
        favicon_pos = src.index('/favicon.ico')
        headers_pos = src.index("self._security_headers()", favicon_pos)
        self.assertLess(favicon_pos, headers_pos)

    def test_workspace_name_is_display_only(self):
        src = (_APP_DIR / "web_server.py").read_text()
        self.assertIn("workspace_name", src)
        self.assertIn("str(sess.ws)", src)


# =====================================================================
# 14. novacode entry routing (serve / modules / repl)
# =====================================================================
class TestNovacodeEntry(unittest.TestCase):
    def test_routing_matrix(self):
        import novacode_entry
        import nova_assistant
        called = []
        old_nova_main, old_assistant_main = nova.main, nova_assistant.main
        nova.main = lambda: called.append("nova")
        nova_assistant.main = lambda: called.append("assistant")
        try:
            for argv, expect in (
                    (["novacode.exe", "serve"], "assistant"),
                    (["novacode.exe", "flow"], "assistant"),
                    (["novacode.exe", "photo"], "assistant"),
                    (["novacode.exe"], "nova"),
                    (["novacode.exe", "--list-models"], "nova"),
                    (["novacode.exe", "myws"], "nova")):
                called.clear()
                with mock.patch.object(sys, "argv", list(argv)):
                    novacode_entry.main()
                self.assertEqual(called, [expect], argv)
        finally:
            nova.main, nova_assistant.main = old_nova_main, old_assistant_main


# =====================================================================
# 15. security helpers: monotonic clocks + screening structure
# =====================================================================
class TestSecurityInternals(unittest.TestCase):
    def test_masked_keep_dq_variant(self):
        self.assertIn("rm -rf", nsec._masked('sh -c "rm -rf /"',
                                             keep_dq=True))

    def test_rate_limiter_buckets_recover(self):
        # v8.11.0: deterministic fake monotonic clock. The real-clock
        # sleep(0.05) version flaked whenever the scheduler stalled
        # >=1 s between the deny and the refill assert (refill is 1/s).
        rl = nsec.RateLimiter(per_minute=60, burst=2)
        clock = {"t": 1000.0}
        with mock.patch.object(nsec, "time") as ft:
            ft.monotonic.side_effect = lambda: clock["t"]
            rl2 = nsec.RateLimiter(per_minute=60, burst=2)
            self.assertTrue(rl2.allow("a"))
            self.assertTrue(rl2.allow("a"))
            self.assertFalse(rl2.allow("a"))
            clock["t"] += 0.05                   # tiny refill at 1/s is not
            self.assertFalse(rl2.allow("a"))     # enough - bucket honest
            rl2.reset("a")
            self.assertTrue(rl2.allow("a"))
            clock["t"] += 60                     # a full minute refills
            self.assertTrue(rl2.allow("a"))
        # the untouched (real-clock) limiter still works
        self.assertTrue(rl.allow("b"))

    def test_interpreter_rx_matches_variants(self):
        for c in ("bash -lc 'x'", "cmd.exe /c dir", "powershell -Command x",
                  "pwsh -c x", "sh -c x"):
            self.assertIsNotNone(nsec._INTERPRETER_RX.search(c), c)
        # NOTE: a bare 'bash -c' with no payload also matches - harmless,
        # over-showing is the stated safe direction for this guard.
        for c in ("echo -c x", "cat file", "npm --version"):
            self.assertIsNone(nsec._INTERPRETER_RX.search(c), c)


if __name__ == "__main__":
    unittest.main()
