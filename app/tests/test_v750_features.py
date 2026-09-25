#!/usr/bin/env python3
"""v7.5.0 tests: the seven NEW POWER FEATURES, pinned by execution.

  - speculative draft-then-verify: valid draft wins, broken draft escalates
  - parallel multi-solution explore: best candidate wins, diff compare,
    all-fail falls back to the normal path
  - semantic RAG: chunking, cosine search with fake embeddings, lexical
    fallback, ignore rules, cache reuse
  - style profile: detection (indent/quotes/naming/comments), persistence,
    prompt injection, kill switch
  - git-native commit-per-edit: the managed .nova/history.git repo takes
    commits for NON-repo workspaces (user repo untouched)
  - the visual timeline restore math (undo everything newer than a unit)
  - the lint gate stays ALWAYS on (correctness features never gated)
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

os.environ.setdefault("NOVA_DISABLED_MODULES", "")

import nova             # noqa: E402
import nova_backend     # noqa: E402
import nova_explore     # noqa: E402
import nova_rag         # noqa: E402
import nova_snapshots   # noqa: E402
import nova_style       # noqa: E402
import nova_commitmsg   # noqa: E402


GOOD_ANSWER = """I'll create the file.
=== FILE: hello.py ===
print("hi")
=== END ===
Run: python hello.py"""

BROKEN_ANSWER = """=== FILE: broken.py ===
def f(::
=== END ===
Run: python broken.py"""


# --------------------------------------------------------- speculative
class TestSpeculative(unittest.TestCase):
    def test_good_draft_is_accepted(self):
        self.assertTrue(nova._draft_valid(GOOD_ANSWER))

    def test_broken_syntax_draft_is_refused(self):
        self.assertFalse(nova._draft_valid(BROKEN_ANSWER))

    def test_prose_only_draft_refused(self):
        self.assertFalse(nova._draft_valid("Here is how you do it: ..."))

    def test_no_run_line_refused(self):
        self.assertFalse(nova._draft_valid(
            "=== FILE: hello.py ===\nprint('hi')\n=== END ==="))

    def test_unnamed_blocks_refused(self):
        self.assertFalse(nova._draft_valid(
            "```python\nprint('x')\n```\nRun: python x.py"))

    def test_empty_refused(self):
        self.assertFalse(nova._draft_valid(""))
        self.assertFalse(nova._draft_valid(None))


# ------------------------------------------------------------- explore
class TestExplore(unittest.TestCase):
    def test_scoring_prefers_complete_answer(self):
        s_good = nova_explore.score_answer(GOOD_ANSWER)
        s_bad = nova_explore.score_answer(BROKEN_ANSWER)
        s_none = nova_explore.score_answer("just prose, no files")
        self.assertGreater(s_good, s_none)
        self.assertGreater(s_none, 0)
        self.assertLess(s_bad, s_good)

    def test_empty_answer_scores_zero(self):
        self.assertEqual(nova_explore.score_answer(""), 0)
        self.assertEqual(nova_explore.score_answer(None), 0)

    def test_explore_picks_the_best_candidate(self):
        answers = [BROKEN_ANSWER, GOOD_ANSWER, "prose only"]
        calls = []

        def fetch(temp):
            calls.append(temp)
            return answers[len(calls) - 1], True

        exp = nova_explore.explore(fetch, 0.7, k=3)
        self.assertEqual(exp["best"], 1)      # GOOD_ANSWER wins
        self.assertEqual(exp["ranked"][exp["best"]]["text"], GOOD_ANSWER)

    def test_explore_all_fail_raises(self):
        def fetch(temp):
            raise OSError("server down")
        with self.assertRaises(RuntimeError):
            nova_explore.explore(fetch, 0.7, k=2)

    def test_candidate_diffs_between_answers(self):
        a1 = GOOD_ANSWER.replace('print("hi")', 'print("hello")')
        a2 = GOOD_ANSWER
        ranked = [{"text": a1, "score": 80}, {"text": a2, "score": 60}]
        diffs = nova_explore.candidate_diffs(ranked, chosen=0)
        self.assertTrue(diffs)
        self.assertEqual(diffs[0][0], "hello.py")

    def test_cloud_never_explores(self):
        # policy pin: best_of_count(cloud) == 1 -> chat_turn's explore
        # branch can never fire for a cloud backend
        self.assertEqual(nova_backend.best_of_count("cloud"), 1)


# ----------------------------------------------------------------- rag
class TestSemanticRag(unittest.TestCase):
    def _ws(self, td):
        ws = Path(td)
        (ws / "auth.py").write_text(
            "def check_login(user, password):\n"
            "    if not verify_password(user, password):\n"
            "        raise PermissionError('bad login')\n"
            "    return True\n",
            encoding="utf-8")
        (ws / "math.py").write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8")
        return ws

    def test_chunking_with_overlap(self):
        text = "\n".join(f"line {i}" for i in range(80))
        chunks = nova_rag.chunk_file("x.txt", text)
        self.assertTrue(chunks)
        self.assertTrue(all(c[1] for c in chunks))
        self.assertTrue(chunks[0][0] >= 1)    # line numbers start at 1

    def test_workspace_files_skip_bins_and_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            (ws / ".nova").mkdir()
            (ws / ".nova" / "junk.py").write_text("x=1", encoding="utf-8")
            (ws / "blob.bin").write_bytes(b"\x00\x01\x02")
            files = [rel for rel, _p in nova_rag.workspace_files(ws)]
            self.assertIn("auth.py", files)
            self.assertNotIn("blob.bin", files)
            self.assertNotIn(".nova/junk.py", files)

    def test_lexical_index_and_search(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            # no embedder available in tests -> the lexical mode must work
            n, mode, err = nova_rag.build(ws)
            self.assertGreater(n, 0)
            self.assertEqual(mode, "lexical")
            hits = nova_rag.search(ws, "check_login password verify", k=2)
            self.assertTrue(hits)
            self.assertEqual(hits[0][0], "auth.py")

    def test_semantic_mode_with_fake_embedder(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            # inject a pre-built semantic index with hand-made vectors:
            # auth chunk ~ query, math chunk orthogonal
            vec_auth = [1.0, 0.0]
            vec_math = [0.0, 1.0]
            idx = {"mode": "semantic", "model": "fake", "dim": 2,
                   "built": 0.0,
                   "chunks": [
                       {"file": "auth.py", "line": 1,
                        "hash": "a", "text": "login check", "vec": vec_auth},
                       {"file": "math.py", "line": 1,
                        "hash": "b", "text": "add numbers", "vec": vec_math},
                   ]}
            p = nova_rag.index_path(ws)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(idx), encoding="utf-8")
            hits = nova_rag.search(ws, "login check", k=2)
            self.assertEqual(hits[0][0], "auth.py")
            self.assertGreater(hits[0][2], 0.9)

    def test_relevant_code_block(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td)
            nova_rag.build(ws)
            block = nova_rag.relevant_code_text(ws, "check_login password")
            self.assertIn("auth.py", block)
            self.assertIn("semantic search", block)

    def test_search_never_raises(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(nova_rag.search(td, "anything"), [])
            self.assertEqual(nova_rag.search(td, ""), [])


# --------------------------------------------------------------- style
class TestStyleProfile(unittest.TestCase):
    def test_detection(self):
        acc = {}
        nova_style.analyze_text("app.py",
                                "def get_data():\n"
                                "    url = 'http://x'\n"
                                "    return url\n",
                                acc)
        prof = nova_style._summarize(acc)
        self.assertEqual(prof["indent"], "spaces")
        self.assertEqual(prof["indent_width"], 4)
        self.assertEqual(prof["quotes"], "single")
        self.assertEqual(prof["naming"], "snake_case")

    def test_tabs_and_camel(self):
        acc = {}
        nova_style.analyze_text("util.js",
                                "function getUserData() {\n"
                                "\treturn 1;\n"
                                "}\n",
                                acc)
        prof = nova_style._summarize(acc)
        self.assertEqual(prof["indent"], "tabs")
        self.assertEqual(prof["naming"], "camelCase")

    def test_persian_comments_detected(self):
        acc = {}
        nova_style.analyze_text("app.py",
                                "# این تابع داده برمی‌گرداند\n"
                                "def get_data():\n    return 1\n"
                                "# باز هم فارسی\n",
                                acc)
        prof = nova_style._summarize(acc)
        self.assertEqual(prof["comment_lang"], "fa")

    def test_save_load_inject_and_clear(self):
        with tempfile.TemporaryDirectory() as td:
            prof = {"indent": "spaces", "indent_width": 2, "quotes": "single",
                    "naming": "camelCase", "comment_lang": "en",
                    "max_line": 88, "frameworks": ["flask"]}
            self.assertEqual(nova_style.save(td, prof), "")
            self.assertEqual(nova_style.load(td), prof)
            text = nova_style.inject_text(td)
            self.assertIn("Match the user's coding style", text)
            self.assertIn("indent: spaces 2", text)
            self.assertIn("flask", text)
            # clear
            nova_style.style_path(td).unlink()
            self.assertEqual(nova_style.inject_text(td), "")

    def test_refresh_from_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "main.py").write_text(
                "def run():\n    x = \"double\"\n    return x\n",
                encoding="utf-8")
            prof, err = nova_style.refresh(td)
            self.assertEqual(err, "")
            self.assertEqual(prof["quotes"], "double")

    def test_kill_switch(self):
        with tempfile.TemporaryDirectory() as td:
            nova_style.save(td, {"indent": "tabs", "indent_width": 4,
                                 "quotes": "single", "naming": "snake_case",
                                 "comment_lang": "en", "max_line": 80,
                                 "frameworks": []})
            old = os.environ.get("NOVA_NO_STYLE")
            try:
                os.environ["NOVA_NO_STYLE"] = "1"
                self.assertEqual(nova_style.inject_text(td), "")
            finally:
                if old is None:
                    os.environ.pop("NOVA_NO_STYLE", None)
                else:
                    os.environ["NOVA_NO_STYLE"] = old


# ------------------------------------------------- git commit-per-edit
class TestGitHistory(unittest.TestCase):
    def test_managed_history_repo_commits(self):
        with tempfile.TemporaryDirectory() as td:
            if not nova_commitmsg.git_available():
                self.skipTest("git not installed")
            (Path(td) / "app.py").write_text("print('v1')\n", encoding="utf-8")
            mode = nova_commitmsg.history_mode(td)
            self.assertEqual(mode, "nova")     # not a repo -> managed history
            ok, detail = nova_commitmsg.nova_auto_commit(
                td, "nova: new app.py", [str(Path(td) / "app.py")])
            self.assertTrue(ok, detail)
            rows = nova_commitmsg.nova_log(td)
            self.assertEqual(len(rows), 1)
            self.assertIn("nova: new app.py", rows[0][1])
            # second edit -> second commit
            (Path(td) / "app.py").write_text("print('v2')\n", encoding="utf-8")
            ok, _d = nova_commitmsg.nova_auto_commit(
                td, "nova: edit app.py", [str(Path(td) / "app.py")])
            self.assertTrue(ok)
            self.assertEqual(len(nova_commitmsg.nova_log(td)), 2)
            # the project itself stays CLEAN: no .git dir in the workspace
            self.assertFalse((Path(td) / ".git").exists())
            self.assertTrue(nova_commitmsg.nova_repo_ready(td))

    def test_user_repo_wins(self):
        with tempfile.TemporaryDirectory() as td:
            if not nova_commitmsg.git_available():
                self.skipTest("git not installed")
            nova_commitmsg._git(td, ["init", "--quiet"])
            self.assertEqual(nova_commitmsg.history_mode(td), "repo")
            (Path(td) / "a.py").write_text("x=1\n", encoding="utf-8")
            ok, mode, _detail = nova_commitmsg.commit_any(
                td, "nova: a.py", [str(Path(td) / "a.py")])
            self.assertEqual(mode, "repo")     # routed to the USER's repo
            # the managed history repo was never created
            self.assertFalse(nova_commitmsg.nova_repo_ready(td))

    def test_bookkeeping_never_tracked(self):
        with tempfile.TemporaryDirectory() as td:
            if not nova_commitmsg.git_available():
                self.skipTest("git not installed")
            (Path(td) / "a.py").write_text("x=1\n", encoding="utf-8")
            ok, _ = nova_commitmsg.nova_auto_commit(
                td, "nova: a.py", [str(Path(td) / "a.py")])
            self.assertTrue(ok)
            # .nova is excluded by the history repo's info/exclude
            code, out = nova_commitmsg._nova_git(td, ["status", "--porcelain"])
            self.assertNotIn(".nova", out)


# ------------------------------------------------------------- timeline
class TestTimelineRestoreMath(unittest.TestCase):
    def test_restore_to_unit_undoes_newer_only(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            f1 = ws / "a.txt"; f2 = ws / "b.txt"; f3 = ws / "c.txt"
            f1.write_text("one", encoding="utf-8")
            u1, err = nova_snapshots.push_auto_unit(
                ws, [(f1, None)], note="first")
            self.assertEqual(err, "")
            f2.write_text("two", encoding="utf-8")
            u2, err = nova_snapshots.push_auto_unit(
                ws, [(f2, None)], note="second")
            f3.write_text("three", encoding="utf-8")
            u3, err = nova_snapshots.push_auto_unit(
                ws, [(f3, None)], note="third")
            units = nova_snapshots.list_units(ws)          # newest first
            idx_u2 = units.index(next(m for m in units if m["id"] == u2))
            # restore to u2 == undo the 1 newer unit (u3)
            res = nova_snapshots.undo_units(ws, idx_u2)
            self.assertIn(u3, res["undone"])
            self.assertFalse(f3.exists())
            self.assertTrue(f2.exists())     # u2's content still applied
            self.assertTrue(f1.exists())


# ------------------------------------------------- session-level wiring
class TestSessionWiring(unittest.TestCase):
    def test_turn_query_and_profile_reach_the_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            nova_style.save(td, {"indent": "tabs", "indent_width": 4,
                                 "quotes": "single", "naming": "snake_case",
                                 "comment_lang": "en", "max_line": 80,
                                 "frameworks": []})
            sess = nova.Session(Path(td))
            sess._turn_query = "build a python script"
            # v8.7: system_parts returns (core, nova_sec, map_sec, kb_sec,
            # extra) - the learned-knowledge section is a REAL member of
            # the tuple again (it used to be silently dropped in v7.5).
            core, _nova_sec, _map_sec, _kb_sec, extra = sess.system_parts()
            # style block rides along (all backends)
            self.assertIn("Match the user's coding style", extra)

    def test_correctness_gate_not_gated(self):
        # the lint gate call site is unconditional: pin the policy itself
        self.assertTrue(nova_backend.feature_enabled("lint", "cloud"))
        self.assertTrue(nova_backend.feature_enabled("lint", "local"))


# --------------------------------------- chat_turn orchestration (v7.5)
class TestTurnOrchestration(unittest.TestCase):
    def setUp(self):
        self._old_stream = nova.stream_chat
        self._old_installed = nova.list_installed_models
        self._old_ni = nova.NONINTERACTIVE
        nova.NONINTERACTIVE = True
        # v8.4: park the code guardian fleet - these tests assert the
        # EXACT set of brains that served a turn (speculative/explore),
        # and the post-apply fleet review would add its own local call.
        # v8.5: the bug hunter's completeness probe adds ONE deliberate
        # local call per apply too - parked at its kill-switch likewise.
        self._env_patcher = mock.patch.dict(
            "os.environ", {"NOVA_GUARDIAN": "0", "NOVA_PROBE": "0"})
        self._env_patcher.start()

    def tearDown(self):
        self._env_patcher.stop()
        nova.stream_chat = self._old_stream
        nova.list_installed_models = self._old_installed
        nova.NONINTERACTIVE = self._old_ni

    def _sess(self, td, model="big:7b"):
        sess = nova.Session(Path(td))
        sess.model = model
        sess._local_brain = lambda: True
        return sess

    def test_speculative_draft_accepted_skips_main_brain(self):
        with tempfile.TemporaryDirectory() as td:
            served = []

            def fake_stream(model, msgs, mode, sess=None, section=None,
                            quiet=False, **_kwargs):
                served.append((model, quiet))
                if model == "tiny:1b":
                    return GOOD_ANSWER, True       # the draft is clean
                return BROKEN_ANSWER, True

            nova.stream_chat = fake_stream
            nova.list_installed_models = lambda: ["tiny:1b", "big:7b"]
            sess = self._sess(td)
            res = nova.chat_turn(sess, "fix typo in print", auto=True)
            self.assertEqual(res["applied"], ["hello.py"])
            self.assertEqual((ws_file := (Path(td) / "hello.py"))
                             .read_text(encoding="utf-8"), 'print("hi")')
            # ONLY the draft served - the big brain stayed cold
            self.assertEqual([m for m, _q in served], ["tiny:1b"])
            self.assertTrue(all(q for _m, q in served))

    def test_broken_draft_escalates_to_main_brain(self):
        with tempfile.TemporaryDirectory() as td:
            served = []

            def fake_stream(model, msgs, mode, sess=None, section=None,
                            quiet=False, **_kwargs):
                served.append(model)
                if model == "tiny:1b":
                    return BROKEN_ANSWER, True     # the draft is broken
                return GOOD_ANSWER, True

            nova.stream_chat = fake_stream
            nova.list_installed_models = lambda: ["tiny:1b", "big:7b"]
            sess = self._sess(td)
            res = nova.chat_turn(sess, "fix typo in print", auto=True)
            self.assertEqual(res["applied"], ["hello.py"])
            self.assertIn((Path(td) / "hello.py").read_text(encoding="utf-8"),
                          ['print("hi")'])
            # draft AND main brain both served (escalation happened)
            self.assertIn("tiny:1b", served)
            self.assertIn("big:7b", served)

    def test_explore_medium_wins_and_applies_best(self):
        with tempfile.TemporaryDirectory() as td:
            old = dict(os.environ)
            os.environ["NOVA_EXPLORE_MEDIUM"] = "1"
            try:
                answers = iter([BROKEN_ANSWER, GOOD_ANSWER])

                def fake_stream(model, msgs, mode, sess=None, section=None,
                                quiet=False, **_kwargs):
                    return next(answers), True

                nova.stream_chat = fake_stream
                nova.list_installed_models = lambda: []
                sess = self._sess(td)
                res = nova.chat_turn(sess, "add a login form to the app",
                                     auto=True)
                ex = res.get("explore")
                self.assertIsNotNone(ex)
                self.assertEqual(ex["k"], 3)
                # the broken candidate scored below the good one...
                self.assertEqual(ex["scores"].index(max(ex["scores"])),
                                 ex["chosen"])
                # ...and the WINNER'S content is what landed on disk
                self.assertIn('print("hi")',
                              (Path(td) / "hello.py").read_text(encoding="utf-8"))
            finally:
                os.environ.clear()
                os.environ.update(old)

    def test_medium_task_stays_single_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []

            def fake_stream(model, msgs, mode, sess=None, section=None,
                            quiet=False, **_kwargs):
                calls.append(1)
                return GOOD_ANSWER, True

            nova.stream_chat = fake_stream
            nova.list_installed_models = lambda: []
            sess = self._sess(td)
            res = nova.chat_turn(sess, "add a login form to the app",
                                 auto=True)
            self.assertIsNone(res.get("explore"))
            self.assertEqual(len(calls), 1)    # exactly one generation

    def test_cloud_backend_never_explores(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            old = dict(os.environ)
            os.environ["NOVA_EXPLORE_MEDIUM"] = "1"
            try:
                def fake_stream(model, msgs, mode, sess=None, section=None,
                                quiet=False, **_kwargs):
                    calls.append(1)
                    return GOOD_ANSWER, True

                nova.stream_chat = fake_stream
                nova.list_installed_models = lambda: []
                sess = self._sess(td)
                sess._local_brain = lambda: False      # CLOUD brain
                res = nova.chat_turn(sess, "refactor the authentication "
                                           "architecture", auto=True)
                self.assertIsNone(res.get("explore"))
                self.assertEqual(len(calls), 1)        # 1 answer, no 3-4x bill
            finally:
                os.environ.clear()
                os.environ.update(old)


# ------------------------------------------------------ web endpoints
class TestWebEndpointsV750(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        import urllib.request
        import urllib.error
        import web_server
        cls.ws = Path(tempfile.mkdtemp(prefix="nova_v750_web_"))
        web_server.nova = nova
        args = {"host": "127.0.0.1", "port": 0, "workspace": str(cls.ws)}
        web_server.STATE = web_server._State(cls.ws)
        web_server.AUTH_TOKEN = None
        cls.httpd = web_server._make_server(args)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()
        (cls.ws / "app.py").write_text("def run():\n    return 1\n",
                                       encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.ws, ignore_errors=True)

    def get(self, path):
        import urllib.request
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return (r.status, json.loads(r.read().decode()))
        except urllib.error.HTTPError as e:
            return (e.code, json.loads(e.read().decode()))

    def post(self, path, obj):
        import urllib.request
        import urllib.error
        data = json.dumps(obj).encode()
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return (r.status, json.loads(r.read().decode()))
        except urllib.error.HTTPError as e:
            return (e.code, json.loads(e.read().decode()))

    def test_info_carries_v750_flags(self):
        code, info = self.get("/api/info")
        self.assertEqual(code, 200)
        for key in ("backend", "explore", "rag", "style", "git_history"):
            self.assertIn(key, info)
        self.assertIn(info["backend"], ("local", "cloud"))

    def test_style_rebuild_via_web(self):
        code, res = self.post("/api/style", {"op": "rebuild"})
        self.assertEqual(code, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["profile"]["indent"], "spaces")
        code, res = self.post("/api/style", {"op": "clear"})
        self.assertEqual(code, 200)
        self.assertTrue(res["cleared"])

    def test_route_map_via_web(self):
        code, res = self.post("/api/route", {"fast": "m-fast",
                                             "strong": "m-strong"})
        self.assertEqual(code, 200)
        self.assertEqual(res["map"].get("fast"), "m-fast")
        code, res = self.post("/api/route", {"off": True})
        self.assertEqual(code, 200)
        self.assertEqual(res["map"], {})

    def test_rag_query_and_empty_guard(self):
        code, res = self.post("/api/rag", {"q": ""})
        self.assertEqual(code, 400)
        # no index built -> clean empty hit list, never a crash
        code, res = self.post("/api/rag", {"q": "run"})
        self.assertEqual(code, 200)
        self.assertEqual(res["hits"], [])

    def test_timeline_restore_invalid_and_undo(self):
        code, res = self.post("/api/timeline/restore", {"id": "does-not-exist"})
        self.assertEqual(code, 404)
        # plain undo is a clean, well-formed no-op regardless of history
        # (other tests in this class may have pushed units already)
        code, res = self.post("/api/timeline/restore", {"op": "undo"})
        self.assertEqual(code, 200)
        self.assertIn("ok", res)

    def test_timeline_payload_files_are_strings_and_restore_works(self):
        # build a REAL unit via a real apply-shaped snapshot push
        f = self.ws / "tl_sample.txt"
        f.write_text("v1", encoding="utf-8")
        uid, err = nova_snapshots.push_auto_unit(self.ws, [(f, None)],
                                                 note="tl test")
        self.assertEqual(err, "")
        code, payload = self.get("/api/timeline")
        self.assertEqual(code, 200)
        unit = next(u for u in payload["units"] if u["id"] == uid)
        self.assertEqual(unit["files"], ["tl_sample.txt"])   # plain strings
        self.assertIn("kind", unit)
        # a SECOND unit, then restore to the first -> the newer one undone
        f2 = self.ws / "tl_sample2.txt"
        f2.write_text("v2", encoding="utf-8")
        uid2, _err = nova_snapshots.push_auto_unit(self.ws, [(f2, None)],
                                                   note="tl test 2")
        code, res = self.post("/api/timeline/restore", {"id": uid})
        self.assertEqual(code, 200)
        self.assertTrue(res["ok"])
        self.assertFalse(f2.exists())      # the newer unit was undone
        self.assertTrue(f.exists())


if __name__ == "__main__":
    unittest.main()
