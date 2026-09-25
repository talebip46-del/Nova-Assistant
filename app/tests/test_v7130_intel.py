#!/usr/bin/env python3
"""v7.13 tests: NOVA INTEL - the project intelligence core the user
asked for ("Project Intelligence واقعی و یکپارچه، Task Graph واقعی،
Memory معنایی، Context Engine، Agent Loop خودمختارتر، ...").

Pinned here (phase A - the data core):
  - tokenizer: Persian + English, ZWNJ folding, Persian digits
  - SemanticMemory: remember/recall/dedup/kind+tag filters/persistence/
    corrupt-file fail-soft/cap
  - TaskGraph: add/validate deps/cycle rejection/ready/blocked/order/
    dependents/remove-strips-refs/progress/persistence
  - ProjectIntelligence: scan (langs/frameworks/entries/tests/symbols/
    import edges incl. dotted + relative)/fingerprint staleness
  - Workspaces registry + project_profile + UserProfile

Everything is offline and hermetic (tmp_path workspaces, no network,
no model calls). Phases B/C/D/E append their own classes below.
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nova_intel as it  # noqa: E402
import nova  # noqa: E402


def _ws():
    return Path(tempfile.mkdtemp(prefix="nova_intel_"))


class FakeClock:
    def __init__(self, start=1_000_000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, days=0.0, seconds=0.0):
        self.t += days * 86400.0 + seconds


# =====================================================================
# 1. tokenizer
# =====================================================================
class TestTokenizer(unittest.TestCase):
    def test_english_words(self):
        self.assertEqual(it.tokenize("The Login Bug!"), ["login", "bug"])

    def test_persian_words(self):
        toks = it.tokenize("قفل شدن کاربر")
        self.assertEqual(toks, ["قفل", "کاربر"])  # شدن is a stopword

    def test_zwnj_folded(self):
        self.assertEqual(it.tokenize("جست‌وجوی عمیق"), ["جست", "وجوی",
                                                        "عمیق"])

    def test_persian_digits_fold(self):
        self.assertEqual(it.tokenize("سال ۱۴۰۴"), ["سال", "1404"])

    def test_stopwords_dropped_both_languages(self):
        self.assertEqual(it.tokenize("the cat and the dog"), ["cat", "dog"])
        self.assertEqual(it.tokenize("این و آن برای تست"), ["تست"])

    def test_underscores_split(self):
        self.assertEqual(it.tokenize("foo_bar baz"), ["foo", "bar", "baz"])

    def test_norm_text_digits_and_zwnj(self):
        t = it.norm_text("قیمت ۱۲۳ و جست‌وجو")
        self.assertIn("123", t)
        self.assertNotIn("\u200c", t)

    def test_empty_is_empty(self):
        self.assertEqual(it.tokenize(""), [])
        self.assertEqual(it.tokenize("   "), [])


# =====================================================================
# 2. SemanticMemory - REAL semantic recall, not raw history
# =====================================================================
class TestSemanticMemory(unittest.TestCase):
    def test_remember_returns_id_and_persists(self):
        ws = _ws()
        p = ws / ".nova" / "memory_vec.json"
        mem = it.SemanticMemory(p)
        mid = mem.remember("postgres port changed to 5433", kind="decision")
        self.assertTrue(mid)
        mem2 = it.SemanticMemory(p)
        self.assertEqual(len(mem2.records), 1)
        self.assertEqual(mem2.records[0]["id"], mid)

    def test_recall_finds_persian_with_persian(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json")
        mem.remember("قفل شدن کاربر بعد از پنج تلاش ورود", kind="decision")
        hits = mem.recall("مشکل قفل شدن ورود کاربر")
        self.assertTrue(hits)
        self.assertIn("قفل", hits[0]["text"])

    def test_recall_english_over_persian_content(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json")
        mem.remember("قفل شدن کاربر بعد از پنج تلاش ورود")
        mem.remember("the build server moved to debian 12", kind="fact")
        hits = mem.recall("build server debian")
        self.assertEqual(hits[0]["kind"], "fact")

    def test_recall_kind_and_tag_filters(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json")
        mem.remember("deploy checklist updated", kind="fact", tags=["ci"])
        mem.remember("deploy checklist v2", kind="decision", tags=["ops"])
        hits = mem.recall("deploy checklist", kind="decision")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["tags"], ["ops"])
        hits_t = mem.recall("deploy checklist", tag="ci")
        self.assertEqual(len(hits_t), 1)

    def test_dedup_updates_instead_of_duplicating(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json",
                                now=FakeClock())
        mem.remember("same thought", kind="fact")
        clock = mem.now
        clock.advance(seconds=60)
        mid = mem.remember("same thought", kind="fact")
        self.assertEqual(len(mem.records), 1)
        self.assertEqual(mid, mem.records[0]["id"])
        self.assertEqual(mem.records[0]["hits"], 2)

    def test_recency_boost_prefers_fresh(self):
        clock = FakeClock()
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json", now=clock)
        mem.remember("redis cache eviction policy changed")
        clock.advance(days=60)
        mem.remember("redis cache eviction policy restored")
        hits = mem.recall("redis cache eviction policy")
        self.assertIn("restored", hits[0]["text"])

    def test_corrupt_file_failsoft(self):
        ws = _ws()
        p = ws / ".nova" / "m.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{broken json!!", encoding="utf-8")
        mem = it.SemanticMemory(p)
        self.assertEqual(mem.records, [])
        mem.remember("fresh start after corruption")
        self.assertEqual(len(it.SemanticMemory(p).records), 1)

    def test_cap_keeps_most_recent(self):
        clock = FakeClock()
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json", now=clock)
        for i in range(it.MAX_MEMORY_RECORDS + 40):
            mem.remember("record number %d unique %d" % (i, i))
            clock.advance(seconds=1)  # distinct timestamps
        self.assertEqual(len(mem.records), it.MAX_MEMORY_RECORDS)
        kept_texts = " ".join(r["text"] for r in mem.records)
        self.assertIn("record number %d" % (it.MAX_MEMORY_RECORDS + 39),
                      kept_texts)
        self.assertNotIn("record number 0 unique 0", kept_texts)

    def test_forget_and_clear(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json")
        a = mem.remember("alpha beta")
        b = mem.remember("gamma delta")
        self.assertEqual(mem.forget(a), 1)
        self.assertEqual([r["id"] for r in mem.records], [b])
        mem.clear()
        self.assertEqual(mem.records, [])
        self.assertEqual(mem.seq, 0)

    def test_empty_remember_is_none(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json")
        self.assertIsNone(mem.remember(""))
        self.assertIsNone(mem.remember("   "))

    def test_stats_and_text_report(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json")
        mem.remember("one", kind="fact")
        mem.remember("two", kind="decision")
        rep = mem.text_report()
        self.assertIn("2 record(s)", rep)
        self.assertIn("decision", rep)

    def test_older_record_without_shared_words_not_returned(self):
        mem = it.SemanticMemory(_ws() / ".nova" / "m.json")
        mem.remember("completely unrelated gardening tips about roses")
        self.assertEqual(mem.recall("kubernetes ingress controller"), [])


# =====================================================================
# 3. TaskGraph - REAL dependencies
# =====================================================================
class TestTaskGraph(unittest.TestCase):
    def test_add_and_ready_respects_deps(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("build auth")
        b = tg.add("test auth", deps=[a])
        self.assertEqual(tg.ready(), [a])
        self.assertEqual(tg.blocked(), [b])
        tg.set(a, status="done")
        self.assertEqual(tg.ready(), [b])

    def test_unknown_dep_rejected(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        with self.assertRaises(ValueError):
            tg.add("x", deps=["t999"])

    def test_cycle_rejected_on_set(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("a")
        b = tg.add("b", deps=[a])
        c = tg.add("c", deps=[b])
        # a -> c would close the loop a -> c -> b -> a
        with self.assertRaises(ValueError):
            tg.set(a, deps=[c])
        # the failed set left the graph intact
        self.assertEqual(tg.get(a)["deps"], [])
        order, cycles = tg.order()
        self.assertEqual(cycles, [])

    def test_self_dep_rejected(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("solo")
        with self.assertRaises(ValueError):
            tg.set(a, deps=[a])

    def test_set_validations(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("a")
        with self.assertRaises(ValueError):
            tg.set("t999", status="done")
        with self.assertRaises(ValueError):
            tg.set(a, status="half-done")
        tg.set(a, status="doing", note="half way")
        self.assertEqual(tg.get(a)["status"], "doing")
        self.assertEqual(tg.get(a)["note"], "half way")

    def test_topological_order(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("a")
        b = tg.add("b", deps=[a])
        c = tg.add("c", deps=[b])
        order, cycles = tg.order()
        self.assertEqual(order, [a, b, c])
        self.assertEqual(cycles, [])

    def test_dependents_transitive(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("a")
        b = tg.add("b", deps=[a])
        c = tg.add("c", deps=[b])
        self.assertEqual(tg.dependents(a), [b, c])
        self.assertEqual(tg.dependents(c), [])

    def test_remove_strips_refs(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("a")
        b = tg.add("b", deps=[a])
        self.assertTrue(tg.remove(a))
        self.assertEqual(tg.get(b)["deps"], [])
        self.assertFalse(tg.remove(a))

    def test_progress(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("a")
        tg.add("b")
        tg.set(a, status="done")
        prog = tg.progress()
        self.assertEqual(prog["done"], 1)
        self.assertEqual(prog["total"], 2)
        self.assertEqual(prog["pct"], 50.0)

    def test_persistence_and_corrupt_failsoft(self):
        ws = _ws()
        p = ws / ".nova" / "tasks.json"
        tg = it.TaskGraph(p)
        a = tg.add("persisted")
        tg2 = it.TaskGraph(p)
        self.assertIn(a, tg2.tasks)
        p.write_text("not json at all", encoding="utf-8")
        tg3 = it.TaskGraph(p)
        self.assertEqual(tg3.tasks, {})

    def test_text_report_shows_marks_and_ready(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        a = tg.add("first")
        b = tg.add("second", deps=[a])
        tg.set(a, status="done")
        rep = tg.text_report()
        self.assertIn("[x]", rep)
        self.assertIn("[ ]", rep)
        self.assertIn("ready now", rep)
        self.assertIn("50%", rep)

    def test_empty_report(self):
        tg = it.TaskGraph(_ws() / ".nova" / "tasks.json")
        self.assertIn("(empty)", tg.text_report())


# =====================================================================
# 4. ProjectIntelligence - the ONE integrated scan
# =====================================================================
def _make_project(ws):
    ws = Path(ws)
    (ws / "pkg").mkdir(parents=True, exist_ok=True)
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (ws / "pkg" / "core.py").write_text(
        "import json\n"
        "from pkg.util import helper\n"
        "from . import sibling as sib\n\n"
        "def calc(a, b):\n    '''add two numbers'''\n"
        "    return a + b\n\n"
        "class Box:\n"
        "    def __init__(self, x):\n        self.x = x\n"
        "    def open(self):\n        return self.x\n",
        encoding="utf-8")
    (ws / "pkg" / "util.py").write_text(
        "def helper():\n    return 42\n", encoding="utf-8")
    (ws / "pkg" / "sibling.py").write_text("Y = 2\n", encoding="utf-8")
    (ws / "pkg" / "decoy.py").write_text("Z = 3\n", encoding="utf-8")
    (ws / "app.py").write_text(
        "from pkg.core import calc\n\nprint(calc(1, 2))\n",
        encoding="utf-8")
    (ws / "tests" / "test_core.py").write_text(
        "from pkg.core import calc\n\ndef test_calc():\n"
        "    assert calc(1, 1) == 2\n", encoding="utf-8")
    (ws / "requirements.txt").write_text(
        "flask==3.0.0\nrequests\n", encoding="utf-8")
    (ws / "README.md").write_text("# demo project\n", encoding="utf-8")
    (ws / "styles.css").write_text("body{margin:0}\n", encoding="utf-8")
    return ws


class TestProjectIntelligence(unittest.TestCase):
    def test_scan_languages_and_files(self):
        d = it.ProjectIntelligence(_make_project(_ws())).scan()
        self.assertGreaterEqual(d["langs"][".py"], 6)
        self.assertIn("pkg/core.py", d["files"])
        self.assertIn("README.md", d["files"])
        self.assertNotIn("pkg/__pycache__/x.pyc", d["files"])

    def test_frameworks_detected(self):
        d = it.ProjectIntelligence(_make_project(_ws())).scan()
        self.assertIn("Flask", d["frameworks"])

    def test_entries_and_tests_dir(self):
        d = it.ProjectIntelligence(_make_project(_ws())).scan()
        self.assertIn("app.py", d["entries"])
        self.assertEqual(d["tests_dir"], "tests")
        self.assertTrue(d["has_readme"])

    def test_symbols_python_ast(self):
        d = it.ProjectIntelligence(_make_project(_ws())).scan()
        syms = dict((n, k) for k, n, _ln in d["symbols"]["pkg/core.py"])
        self.assertIn("calc(a, b)", syms)
        self.assertIn("Box", syms)
        self.assertIn("Box.open(self)", syms)
        self.assertNotIn("Box.__init__(self)", syms)  # dunder excluded

    def test_import_edges_dotted_and_relative(self):
        d = it.ProjectIntelligence(_make_project(_ws())).scan()
        self.assertEqual(d["imports"]["pkg/core.py"],
                         ["pkg/sibling.py", "pkg/util.py"])
        self.assertEqual(d["imports"]["app.py"], ["pkg/core.py"])
        self.assertNotIn("pkg/decoy.py", str(d["imports"]))

    def test_fingerprint_staleness(self):
        ws = _make_project(_ws())
        intel = it.ProjectIntelligence(ws)
        intel.scan()
        self.assertTrue(intel.stats()["fresh"])
        time.sleep(0.01)
        (ws / "new_file.py").write_text("x = 1\n", encoding="utf-8")
        self.assertFalse(intel.stats()["fresh"])
        data, changed = intel.refresh_if_stale()
        self.assertTrue(changed)
        self.assertIn("new_file.py", data["files"])
        _, changed2 = intel.refresh_if_stale()
        self.assertFalse(changed2)

    def test_persistence(self):
        ws = _make_project(_ws())
        intel = it.ProjectIntelligence(ws)
        intel.scan()
        intel2 = it.ProjectIntelligence(ws)
        self.assertIn("files", intel2.data)

    def test_corrupt_intel_file_failsoft(self):
        ws = _make_project(_ws())
        p = ws / ".nova" / "intel.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("]]corrupt[[", encoding="utf-8")
        intel = it.ProjectIntelligence(ws)
        self.assertEqual(intel.data, {})
        data, changed = intel.refresh_if_stale()
        self.assertTrue(changed)
        self.assertIn("files", data)

    def test_summary_text(self):
        intel = it.ProjectIntelligence(_make_project(_ws()))
        intel.scan()
        s = intel.summary_text()
        self.assertIn("languages", s)
        self.assertIn("Flask", s)
        self.assertIn("tests: tests/", s)
        self.assertIn("import edges", s)

    def test_empty_ws_scan(self):
        d = it.ProjectIntelligence(_ws()).scan()
        self.assertEqual(d["files"], [])
        self.assertEqual(d["frameworks"], [])


# =====================================================================
# 5. Workspaces + profiles
# =====================================================================
class TestWorkspacesAndProfiles(unittest.TestCase):
    def test_register_dedup_and_list(self):
        reg = it.Workspaces(_ws() / "workspaces.json")
        ws_a, ws_b = _ws(), _ws()
        e1, created1 = reg.register(ws_a, name="shop")
        e2, created2 = reg.register(ws_a)  # same path -> update, not dup
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(len(reg.projects), 1)
        reg.register(ws_b, note="second project")
        rows = reg.list()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["exists"] for r in rows))

    def test_unregister(self):
        reg = it.Workspaces(_ws() / "workspaces.json")
        ws_a = _ws()
        reg.register(ws_a)
        self.assertEqual(reg.unregister(ws_a), 1)
        self.assertEqual(reg.projects, [])

    def test_missing_project_flagged(self):
        reg = it.Workspaces(_ws() / "workspaces.json")
        reg.register(_ws())
        # a project dir deleted after registration:
        ghost = _ws()
        reg.register(ghost)
        import shutil
        shutil.rmtree(ghost)
        rows = reg.list()
        alive = [r for r in rows if r["exists"]]
        gone = [r for r in rows if not r["exists"]]
        self.assertEqual(len(alive), 1)
        self.assertEqual(len(gone), 1)

    def test_text_report_marks_current(self):
        reg = it.Workspaces(_ws() / "workspaces.json")
        ws_a = _ws()
        reg.register(ws_a, name="shop")
        rep = reg.text_report(current=ws_a)
        self.assertIn("shop", rep)
        self.assertIn("*", rep)

    def test_project_profile_fields(self):
        ws = _make_project(_ws())
        (ws / "NOVA.md").write_text("use persian comments\n",
                                    encoding="utf-8")
        prof = it.project_profile(ws)
        self.assertGreater(prof["files"], 5)
        self.assertIn("Flask", prof["frameworks"])
        self.assertIn("persian comments", prof["conventions_head"])
        self.assertEqual(prof["tests_dir"], "tests")

    def test_user_profile(self):
        upath = _ws() / "user.json"   # ONE path for writer and reader
        up = it.UserProfile(upath)
        up.set_pref("provider", "bai")
        up.add_fact("user prefers compact answers")
        up.add_fact("user prefers compact answers")  # dedup
        up2 = it.UserProfile(upath)
        self.assertEqual(up2.get_pref("provider"), "bai")
        self.assertEqual(len(up2.data["facts"]), 1)
        self.assertIn("provider=bai", up2.brief())
        self.assertIn("compact answers", up2.brief())


# =====================================================================
# 6. ContextEngine - the MOST precise context, budgeted
# =====================================================================
class TestContextEngine(unittest.TestCase):
    def _engine(self, ws, populate=True):
        intel = it.ProjectIntelligence(ws)
        intel.scan()
        tasks = it.TaskGraph(ws / ".nova" / "tasks.json")
        mem = it.SemanticMemory(ws / ".nova" / "memory_vec.json",
                                now=FakeClock())
        kb = ws / ".nova" / "kb.json"
        if populate:
            a = tasks.add("build the auth module")
            tasks.add("test the auth module", deps=[a])
            mem.remember("the auth token lives in env NOVA_TOKEN",
                         kind="fact")
            mem.remember("we decided postgres over sqlite for the shop",
                         kind="decision")
            it.save_json(kb, [
                {"topic": "api notes", "text": "the REST API is versioned "
                 "under /api/v1 and needs Bearer auth", "saved": "now"}])
        return it.ContextEngine(ws, intel=intel, tasks=tasks, memory=mem,
                                kb_path=kb)

    def test_assemble_includes_relevant_blocks(self):
        eng = self._engine(_make_project(_ws()))
        text, sources = eng.assemble("auth module token")
        self.assertIn("TASKS", text)
        self.assertIn("PROJECT", text)
        self.assertIn("MEMORY", text)
        self.assertIn("NOVA_TOKEN", text)
        for s in ("tasks", "project", "memory"):
            self.assertIn(s, sources)

    def test_kb_keyword_fit(self):
        eng = self._engine(_make_project(_ws()))
        text, sources = eng.assemble("rest api bearer auth")
        self.assertIn("KB", text)
        self.assertIn("/api/v1", text)

    def test_irrelevant_query_drops_kb_and_memory(self):
        eng = self._engine(_make_project(_ws()))
        text, sources = eng.assemble("quantum xylophone zanzibar")
        self.assertNotIn("KB", text)
        self.assertNotIn("MEMORY", text)

    def test_budget_is_respected(self):
        eng = self._engine(_make_project(_ws()))
        text, sources = eng.assemble("auth module", budget=400)
        self.assertLessEqual(len(text), 400)

    def test_empty_workspace_returns_empty(self):
        eng = it.ContextEngine(_ws())
        text, sources = eng.assemble("anything")
        self.assertEqual(text, "")
        self.assertEqual(sources, [])

    def test_decisions_fallback_newest(self):
        eng = self._engine(_make_project(_ws()))
        # a query that matches nothing but decisions exist
        text, sources = eng.assemble("zzz unrelated zzz")
        self.assertIn("DECISIONS", text)
        self.assertIn("postgres", text)


# =====================================================================
# 7. AgentStatus - live dashboard feed
# =====================================================================
class TestAgentStatus(unittest.TestCase):
    def test_set_and_read(self):
        st = it.AgentStatus(_ws())
        st.set(phase="execute", goal="build login", task="t1",
               why="first step", event="started")
        d = st.read()
        self.assertEqual(d["phase"], "execute")
        self.assertEqual(d["goal"], "build login")
        self.assertEqual(d["events"][0]["msg"], "started")

    def test_partial_update_keeps_other_fields(self):
        st = it.AgentStatus(_ws())
        st.set(phase="test", goal="g", tested="pytest 3 passed")
        st.set(phase="verify", why="checking evidence")
        d = st.read()
        self.assertEqual(d["phase"], "verify")
        self.assertEqual(d["goal"], "g")
        self.assertEqual(d["tested"], "pytest 3 passed")

    def test_events_ring_capped(self):
        st = it.AgentStatus(_ws())
        for i in range(it.MAX_EVENTS + 20):
            st.set(event="event %d" % i)
        d = st.read()
        self.assertEqual(len(d["events"]), it.MAX_EVENTS)
        self.assertIn("event %d" % (it.MAX_EVENTS + 19),
                      d["events"][-1]["msg"])

    def test_corrupt_status_failsoft(self):
        ws = _ws()
        p = ws / ".nova" / "agent_status.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("nope{", encoding="utf-8")
        st = it.AgentStatus(ws)
        st.set(phase="observe")
        self.assertEqual(st.read()["phase"], "observe")

    def test_clear(self):
        st = it.AgentStatus(_ws())
        st.set(phase="observe")
        st.clear()
        self.assertEqual(st.read(), {})


# =====================================================================
# 8. AgentLoop + CompletionDetector - the honest phase machine
# =====================================================================
class TestAgentLoop(unittest.TestCase):
    def test_full_happy_path_phases(self):
        ws = _ws()
        emitted = []
        loop = it.AgentLoop(ws, emit=emitted.append)
        loop.start("build the settings page")
        for ph in ("decide", "execute", "test", "fix", "verify"):
            loop.phase(ph, why="moving on")
        loop.finish(ok=True, evidence={"tests_ok": True})
        self.assertEqual(loop.run["result"], "done")
        names = [p["phase"] for p in loop.run["phases"]]
        for want in ("observe", "decide", "execute", "test", "fix",
                     "verify", "done"):
            self.assertIn(want, names)
        self.assertTrue(emitted)
        self.assertEqual(emitted[-1]["phase"], "done")
        # run file persisted and reloadable
        data = json.loads(loop.run_path.read_text(encoding="utf-8"))
        self.assertEqual(data["result"], "done")

    def test_false_success_is_rejected(self):
        loop = it.AgentLoop(_ws())
        loop.start("break nothing")
        loop.finish(ok=True, evidence={})   # claims success with NOTHING
        self.assertEqual(loop.run["result"], "failed")
        self.assertIn("success claim rejected",
                      " ".join(loop.run["log"]))

    def test_failure_with_failing_evidence_is_honest_failure(self):
        loop = it.AgentLoop(_ws())
        loop.start("task")
        loop.finish(ok=False, evidence={"tests_ok": False})
        self.assertEqual(loop.run["result"], "failed")
        self.assertEqual(loop.run["evidence"]["tests_ok"], False)

    def test_waived_verification_allows_done_but_marked(self):
        loop = it.AgentLoop(_ws())
        loop.start("docs only change")
        loop.finish(ok=True, evidence={"waived": "markdown only"})
        self.assertEqual(loop.run["result"], "done")
        self.assertEqual(loop.run["evidence"]["waived"], "markdown only")

    def test_unknown_phase_rejected(self):
        loop = it.AgentLoop(_ws())
        with self.assertRaises(ValueError):
            loop.phase("daydream")

    def test_status_mirrors_loop(self):
        ws = _ws()
        loop = it.AgentLoop(ws)
        loop.start("goal A")
        loop.phase("execute", why="writing files", task="t1")
        d = it.AgentStatus(ws).read()
        self.assertEqual(d["phase"], "execute")
        self.assertEqual(d["goal"], "goal A")
        self.assertEqual(d["task"], "t1")

    def test_latest_run_finder(self):
        ws = _ws()
        loop = it.AgentLoop(ws)
        loop.start("find me")
        loop.finish(ok=False)
        found = it.AgentLoop.latest_run(ws)
        self.assertIsNotNone(found)
        self.assertEqual(found.stem, loop.run_id)

    def test_log_capped(self):
        loop = it.AgentLoop(_ws())
        loop.start("spam")
        for i in range(300):
            loop.record("line %d" % i)
        self.assertLessEqual(len(loop.run["log"]), 200)


class TestCompletionDetector(unittest.TestCase):
    def test_evidence_matrix(self):
        ok, _ = it.CompletionDetector.evaluate({"tests_ok": True})
        self.assertTrue(ok)
        ok, _ = it.CompletionDetector.evaluate({"lint_ok": True})
        self.assertTrue(ok)
        ok, _ = it.CompletionDetector.evaluate({"run_ok": True})
        self.assertTrue(ok)
        ok, _ = it.CompletionDetector.evaluate({})
        self.assertFalse(ok)
        ok, _ = it.CompletionDetector.evaluate({"tests_ok": False})
        self.assertFalse(ok)
        ok, _ = it.CompletionDetector.evaluate(
            {"tests_ok": False, "waived": "docs only"})
        self.assertTrue(ok)

    def test_normalize_coerces_and_strips(self):
        # v8.0 honesty contract: only booleans and REAL numbers count as
        # evidence - strings like "yes"/"failed" are n/a (None). The old
        # bool(v) coercion accepted {"lint_ok": "failed"} as a PASS.
        ev = it.CompletionDetector.normalize(
            {"tests_ok": 1, "lint_ok": 0, "run_ok": "yes",
             "waived": "  because  "})
        self.assertIs(ev["tests_ok"], True)
        self.assertIs(ev["lint_ok"], False)
        self.assertIs(ev["run_ok"], None)      # strings are NOT evidence
        self.assertIs(it.CompletionDetector.normalize(
            {"run_ok": "failed"})["run_ok"], None)
        self.assertIs(it.CompletionDetector.normalize(
            {"run_ok": False})["run_ok"], False)
        self.assertEqual(ev["waived"], "because")

    def test_summarize(self):
        s = it.CompletionDetector.summarize({"tests_ok": True,
                                             "lint_ok": False})
        self.assertIn("tests_ok=pass", s)
        self.assertIn("lint_ok=fail", s)
        self.assertIn("run_ok=n/a", s)


# =====================================================================
# 9. RecoveryManager - classify + deterministic ladder
# =====================================================================
class TestRecoveryManager(unittest.TestCase):
    def test_classification(self):
        cases = [
            ("SyntaxError: invalid syntax", "syntax"),
            ("ModuleNotFoundError: No module named 'flask'", "import"),
            ("subprocess.TimeoutExpired: timed out", "timeout"),
            ("PermissionError: [Errno 13] Permission denied",
             "permission"),
            ("ConnectionError: getaddrinfo failed", "net"),
            ("AssertionError: assert 3 == 4", "test"),
            ("Traceback (most recent call last): ... TypeError",
             "runtime"),
            ("", "unknown"),
            ("something completely novel happened", "unknown"),
        ]
        for text, want in cases:
            self.assertEqual(it.RecoveryManager.classify(text), want,
                             text)

    def test_ladder_escalates(self):
        for attempt, want in ((1, "fix_targeted"), (2, "fix_targeted"),
                              (3, "split"), (4, "stop"), (9, "stop")):
            plan = it.RecoveryManager.plan("syntax", attempt)
            self.assertEqual(plan["action"], want, attempt)

    def test_retry_delays_double_and_cap(self):
        p1 = it.RecoveryManager.plan("net", 1)
        p2 = it.RecoveryManager.plan("net", 2)
        p3 = it.RecoveryManager.plan("net", 3)
        self.assertEqual(p1["action"], "retry")
        self.assertEqual(p1["delay"], 2)
        self.assertEqual(p2["delay"], 4)
        self.assertEqual(p3["action"], "stop")
        self.assertEqual(p3["delay"], 0)

    def test_test_failures_lead_to_rollback_on_third(self):
        p = it.RecoveryManager.plan("test", 3)
        self.assertEqual(p["action"], "rollback")

    def test_handle_combines_classify_and_plan(self):
        h = it.RecoveryManager.handle("AssertionError: boom", 2)
        self.assertEqual(h["kind"], "test")
        self.assertEqual(h["action"], "fix_targeted")
        self.assertTrue(h["note"])


# =====================================================================
# 10. ImpactAnalyzer - the blast radius BEFORE the change
# =====================================================================
class TestImpactAnalyzer(unittest.TestCase):
    def test_direct_and_transitive_importers(self):
        ws = _make_project(_ws())
        # pkg/util.py is imported by pkg/core.py, which is imported by
        # app.py - touching util must reach BOTH transitively.
        rep = it.ImpactAnalyzer(ws).analyze(["pkg/util.py"])
        self.assertIn("pkg/core.py", rep["affected"])
        self.assertIn("app.py", rep["affected"])
        self.assertEqual(rep["risk"], "high")

    def test_test_files_exercising_the_target(self):
        ws = _make_project(_ws())
        rep = it.ImpactAnalyzer(ws).analyze(["pkg/core.py"])
        self.assertIn("tests/test_core.py", rep["tests"])
        self.assertEqual(rep["risk"], "high")
        self.assertIn("calc(a, b)", rep["symbols"]["pkg/core.py"])

    def test_orphan_file_is_low_risk(self):
        ws = _make_project(_ws())
        rep = it.ImpactAnalyzer(ws).analyze(["pkg/decoy.py"])
        self.assertEqual(rep["affected"], [])
        self.assertEqual(rep["risk"], "low")

    def test_unknown_path_is_none_risk(self):
        rep = it.ImpactAnalyzer(_make_project(_ws())).analyze(["nope.py"])
        self.assertEqual(rep["risk"], "none")

    def test_text_report_lines(self):
        ws = _make_project(_ws())
        text = it.ImpactAnalyzer(ws).text_report(["pkg/util.py"])
        self.assertIn("risk: high", text)
        self.assertIn("pkg/core.py", text)
        self.assertIn("gentests", text)  # honest hint when no tests


# =====================================================================
# 11. RegressionDetector - honest before/after comparison
# =====================================================================
class TestRegressionDetector(unittest.TestCase):
    def test_stable_when_still_green(self):
        ws = _ws()
        rd = it.RegressionDetector(ws, runner=lambda: {
            "ok": True, "cmd": "pytest -q", "report": "10 passed"})
        rd.baseline()
        out = rd.check()
        self.assertEqual(out["verdict"], "stable")
        # a stable run re-baselines silently
        self.assertEqual(it.load_json(rd.path, {}).get("ok"), True)

    def test_new_fail_detected(self):
        ws = _ws()
        rd = it.RegressionDetector(ws, runner=lambda: {
            "ok": True, "cmd": "pytest -q", "report": "10 passed"})
        rd.baseline()
        rd.runner = lambda: {"ok": False, "cmd": "pytest -q",
                             "report": "2 failed"}
        out = rd.check()
        self.assertEqual(out["verdict"], "new-fail")

    def test_fixed_detected_and_rebaselined(self):
        ws = _ws()
        rd = it.RegressionDetector(ws, runner=lambda: {
            "ok": False, "cmd": "pytest -q", "report": "2 failed"})
        rd.baseline()
        rd.runner = lambda: {"ok": True, "cmd": "pytest -q",
                             "report": "10 passed"}
        self.assertEqual(rd.check()["verdict"], "fixed")
        self.assertEqual(it.load_json(rd.path, {}).get("ok"), True)

    def test_no_baseline_is_honest(self):
        rd = it.RegressionDetector(_ws(), runner=lambda: {"ok": True})
        self.assertEqual(rd.check()["verdict"], "no-baseline")

    def test_no_tests_detected(self):
        ws = _ws()
        rd = it.RegressionDetector(ws, runner=lambda: {
            "ok": None, "cmd": None, "report": "no test setup"})
        rd.baseline()
        self.assertEqual(rd.check()["verdict"], "no-tests")

    def test_runner_crash_failsoft(self):
        ws = _ws()
        rd = it.RegressionDetector(ws, runner=lambda: {
            "ok": True, "cmd": "pytest"})
        rd.baseline()
        def boom():
            raise RuntimeError("boom")
        rd.runner = boom
        out = rd.check()
        self.assertIn("runner failed", out["report_head"])


# =====================================================================
# 12. TestGenerator - runnable skeletons, never overwriting
# =====================================================================
class TestTestGenerator(unittest.TestCase):
    def test_python_skeleton(self):
        ws = _make_project(_ws())
        gen = it.TestGenerator(ws)
        out = gen.gen_for_file("pkg/core.py")
        self.assertTrue(out["ok"])
        self.assertEqual(out["cases"], 4)  # calc x2 + Box + Box.open
        text = (ws / out["path"]).read_text(encoding="utf-8")
        self.assertIn("import_module('pkg.core')", text)
        self.assertIn("def test_calc_exists():", text)
        self.assertIn("pytest.mark.skip", text)
        self.assertIn("def test_Box_open_smoke():", text)
        # the existence pins actually RUN green
        import subprocess
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(ws / out["path"]),
             "-k", "exists", "--no-header", "-p", "no:cacheprovider"],
            capture_output=True, text=True, cwd=str(ws))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_no_overwrite(self):
        ws = _make_project(_ws())
        gen = it.TestGenerator(ws)
        first = gen.gen_for_file("pkg/core.py")
        again = gen.gen_for_file("pkg/core.py")
        self.assertTrue(first["ok"])
        self.assertFalse(again["ok"])
        self.assertIn("already exists", again["error"])

    def test_js_todo_skeleton(self):
        ws = _ws()
        (ws / "widget.js").write_text(
            "export function render(x) { return x; }\n"
            "export class Widget { start() {} }\n", encoding="utf-8")
        gen = it.TestGenerator(ws)
        out = gen.gen_for_file("widget.js")
        self.assertTrue(out["ok"])
        self.assertEqual(out["language"], "javascript")
        text = (ws / out["path"]).read_text(encoding="utf-8")
        self.assertIn("test.todo('render", text)
        self.assertIn("test.todo('Widget", text)

    def test_unparseable_python_honest_error(self):
        ws = _ws()
        (ws / "broken.py").write_text("def f(:\n", encoding="utf-8")
        out = it.TestGenerator(ws).gen_for_file("broken.py")
        self.assertFalse(out["ok"])
        self.assertIn("cannot parse", out["error"])

    def test_missing_file_and_bad_ext(self):
        gen = it.TestGenerator(_make_project(_ws()))
        self.assertFalse(gen.gen_for_file("ghost.py")["ok"])
        self.assertFalse(gen.gen_for_file("README.md")["ok"])

    def test_no_public_symbols(self):
        ws = _ws()
        (ws / "only_private.py").write_text("def _hidden(): pass\n",
                                            encoding="utf-8")
        out = it.TestGenerator(ws).gen_for_file("only_private.py")
        self.assertFalse(out["ok"])


# =====================================================================
# 13. Critic - staged self-review
# =====================================================================
class TestCritic(unittest.TestCase):
    def test_clean_batch_ships(self):
        rep = it.Critic.review({"files": ["a.py"], "syntax": [],
                                "lint": [],
                                "impact": {"risk": "low", "tests": []},
                                "tests": {"ok": True, "cmd": "pytest"}})
        self.assertEqual(rep["verdict"], "ship")
        self.assertGreaterEqual(rep["score"], 85)
        stages = [s["stage"] for s in rep["stages"]]
        self.assertEqual(stages, ["protocol", "syntax", "impact",
                                  "tests"])

    def test_syntax_fail_means_fix(self):
        rep = it.Critic.review({"files": ["a.py"],
                                "syntax": [("a.py", "bad")], "lint": [],
                                "impact": {"risk": "low"},
                                "tests": {"ok": True, "cmd": "pytest"}})
        self.assertEqual(rep["verdict"], "fix")
        self.assertLess(rep["score"], 100)

    def test_tests_fail_means_fix(self):
        rep = it.Critic.review({"files": ["a.py"], "syntax": [],
                                "lint": [],
                                "impact": {"risk": "low"},
                                "tests": {"ok": False, "cmd": "pytest",
                                          "report": "1 failed"}})
        self.assertEqual(rep["verdict"], "fix")

    def test_syntax_plus_tests_fail_means_rollback(self):
        rep = it.Critic.review({"files": ["a.py"],
                                "syntax": [("a.py", "bad")],
                                "lint": [],
                                "impact": {"risk": "high", "tests": []},
                                "tests": {"ok": False, "cmd": "pytest",
                                          "report": "3 failed"}})
        self.assertEqual(rep["verdict"], "rollback")

    def test_high_impact_without_tests_penalized(self):
        rep = it.Critic.review({"files": ["core.py"], "syntax": [],
                                "lint": [],
                                "impact": {"risk": "high", "tests": []},
                                "tests": {"ok": True, "cmd": "pytest"}})
        self.assertLess(rep["score"], 100)
        impact_stage = [s for s in rep["stages"]
                        if s["stage"] == "impact"][0]
        self.assertFalse(impact_stage["ok"])

    def test_no_tests_run_costs_points_but_not_death(self):
        rep = it.Critic.review({"files": ["a.py"], "syntax": [],
                                "lint": [], "impact": {"risk": "low"},
                                "tests": None})
        self.assertLess(rep["score"], 100)
        self.assertEqual(rep["verdict"], "fix")

    def test_text_report_shape(self):
        text = it.Critic.text_report({"files": ["a.py"], "syntax": [],
                                      "lint": [], "impact": {"risk": "low"},
                                      "tests": {"ok": True,
                                                "cmd": "pytest"}})
        self.assertIn("SHIP", text)
        self.assertIn("[ok] syntax", text)


# =====================================================================
# 14. SmartRollback - decision + locator
# =====================================================================
class TestSmartRollback(unittest.TestCase):
    def test_should_rules(self):
        do, why = it.SmartRollback.should("rollback")
        self.assertTrue(do)
        self.assertIn("critic", why)
        do, _ = it.SmartRollback.should("fix", "new-fail")
        self.assertTrue(do)
        do, _ = it.SmartRollback.should("ship", "stable")
        self.assertFalse(do)
        do, _ = it.SmartRollback.should("fix", None)
        self.assertFalse(do)

    def test_newest_snapshot_locator(self):
        ws = _ws()
        auto = ws / ".nova" / "snapshots" / "auto"
        auto.mkdir(parents=True)
        (auto / "aaa").mkdir()
        (auto / "bbb").mkdir()
        snap = it.SmartRollback.newest_snapshot(ws)
        self.assertEqual(snap, auto / "bbb")

    def test_no_snapshots_is_none(self):
        self.assertIsNone(it.SmartRollback.newest_snapshot(_ws()))

    def test_plan_includes_snapshot_when_rolling(self):
        ws = _ws()
        auto = ws / ".nova" / "snapshots" / "auto"
        auto.mkdir(parents=True)
        (auto / "s1").mkdir()
        plan = it.SmartRollback.plan(ws, "rollback")
        self.assertTrue(plan["rollback"])
        self.assertTrue(plan["snapshot"].endswith("s1"))
        self.assertIn("/undo", plan["note"])

    def test_plan_no_rollback_no_note(self):
        plan = it.SmartRollback.plan(_ws(), "ship")
        self.assertFalse(plan["rollback"])
        self.assertEqual(plan["note"], "")


# =====================================================================
# 15. the nova.py wiring (commands + TOOLS + hooks + version)
# =====================================================================
class TestNovaWiring(unittest.TestCase):
    def test_version_is_7130(self):
        self.assertEqual(nova.VERSION, "8.12.0")

    def test_intel_module_loaded(self):
        self.assertIsNotNone(nova.intel)
        self.assertIs(nova.intel, it)

    def test_tools_registry_has_intel_commands(self):
        cmds = {t["cmd"] for t in nova.TOOLS}
        for want in ("/intel", "/tasks", "/mem", "/ctx", "/impact",
                     "/regress", "/gentests", "/critic", "/workspaces",
                     "/loop"):
            self.assertIn(want, cmds, want)

    def test_model_briefed_tools(self):
        briefed = {t["cmd"] for t in nova.TOOLS if t.get("model")}
        for want in ("/tasks", "/mem", "/ctx", "/impact", "/gentests",
                     "/loop"):
            self.assertIn(want, briefed, want)

    def test_help_groups_contain_intel(self):
        groups = [g[0] for g in nova.HELP_GROUPS]
        self.assertIn("intel", groups)
        cmds = [c for g in nova.HELP_GROUPS if g[0] == "intel" for c in
                g[2]]
        self.assertIn("/tasks", cmds)
        self.assertIn("/loop", cmds)

    def test_command_smoke_on_fake_session(self):
        import contextlib
        import io
        import tempfile as tf
        s = type("S", (), {})()
        s.ws = Path(tf.mkdtemp(prefix="nova_wiring_"))
        (s.ws / "hello.py").write_text("def hi():\n    return 1\n",
                                       encoding="utf-8")
        s.kb_path = s.ws / ".nova" / "kb.json"
        s.touched = {}
        s.autotest = False
        for line in ("/intel", "/tasks add write hello",
                     "/tasks", "/mem remember we use sqlite",
                     "/mem recall sqlite", "/ctx hello module",
                     "/impact hello.py", "/regress baseline",
                     "/gentests hello.py", "/critic", "/workspaces"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                nova.dispatch(s, line)
            self.assertNotIn("unknown command", buf.getvalue(), line)
            self.assertNotIn("nova_intel.py missing", buf.getvalue(),
                             line)

    def test_rescan_refreshes_intel(self):
        import tempfile as tf
        s = type("S", (), {})()
        s.ws = Path(tf.mkdtemp(prefix="nova_rescan_"))
        (s.ws / "a.py").write_text("X = 1\n", encoding="utf-8")
        s.ignore = None
        s._load_nova_md = lambda: None
        nova.Session.rescan(s, silent=True)  # fake-session rescan call
        data = it.load_json(s.ws / ".nova" / "intel.json", {})
        self.assertIn("a.py", data.get("files", []))


# =====================================================================
# 16. the web face: web_intel_state / web_intel_action + real server
# =====================================================================
class TestWebIntelState(unittest.TestCase):
    def test_state_blocks_all_present(self):
        import tempfile as tf
        ws = _make_project(Path(tf.mkdtemp(prefix="nova_webst_")))
        tg = it.TaskGraph(ws / ".nova" / "tasks.json")
        a = tg.add("first")
        tg.add("second", deps=[a])
        mem = it.SemanticMemory(ws / ".nova" / "memory_vec.json")
        mem.remember("the deploy key rotates monthly", kind="fact")
        it.AgentStatus(ws).set(phase="execute", goal="demo")
        sess = type("S", (), {"ws": ws, "kb_path": ws / ".nova" /
                              "kb.json"})()
        st = nova.web_intel_state(sess)
        self.assertTrue(st["available"])
        self.assertEqual(st["version"], "8.12.0")
        self.assertIn("pkg/core.py", st["project"].get("files", 0) and
                      it.load_json(ws / ".nova" / "intel.json", {})
                      .get("files", []))
        self.assertEqual(st["tasks"]["progress"]["total"], 2)
        self.assertEqual(st["tasks"]["ready"], [a])
        self.assertGreaterEqual(st["memory"]["stats"]["records"], 1)
        self.assertEqual(st["status"]["phase"], "execute")
        self.assertIsNone(st["last_run"])

    def test_state_without_intel_module(self):
        sess = type("S", (), {"ws": _ws(), "kb_path": None})()
        saved = nova.intel
        try:
            nova.intel = None
            st = nova.web_intel_state(sess)
            self.assertFalse(st["available"])
        finally:
            nova.intel = saved


class TestWebIntelAction(unittest.TestCase):
    def _sess(self):
        ws = _make_project(_ws())
        return type("S", (), {"ws": ws, "kb_path": ws / ".nova" /
                              "kb.json"})()

    def test_unknown_action_400(self):
        ok, payload, status = nova.web_intel_action(self._sess(),
                                                    {"action": "nope"})
        self.assertFalse(ok)
        self.assertEqual(status, 400)
        self.assertIn("actions", payload)

    def test_rescan_action(self):
        ok, payload, status = nova.web_intel_action(self._sess(),
                                                    {"action": "rescan"})
        self.assertTrue(ok)
        self.assertGreater(payload["files"], 5)

    def test_task_add_set_del_roundtrip(self):
        sess = self._sess()
        ok, p, s = nova.web_intel_action(
            sess, {"action": "task_add", "title": "wire the panel",
                   "deps": [], "tags": ["ui"]})
        self.assertTrue(ok)
        tid = p["id"]
        ok, p2, _ = nova.web_intel_action(
            sess, {"action": "task_set", "id": tid, "status": "done"})
        self.assertTrue(ok)
        self.assertEqual(p2["task"]["status"], "done")
        ok, p3, _ = nova.web_intel_action(sess, {"action": "task_del",
                                                 "id": tid})
        self.assertTrue(ok)
        self.assertTrue(p3["ok"])

    def test_task_add_requires_title(self):
        ok, _p, s = nova.web_intel_action(self._sess(),
                                          {"action": "task_add"})
        self.assertFalse(ok)
        self.assertEqual(s, 400)

    def test_mem_remember_and_forget(self):
        sess = self._sess()
        ok, p, _ = nova.web_intel_action(
            sess, {"action": "mem_remember", "text": "cache ttl is 300s",
                   "kind": "decision"})
        self.assertTrue(ok)
        mid = p["id"]
        ok, p2, _ = nova.web_intel_action(sess, {"action": "mem_forget",
                                                 "id": mid})
        self.assertTrue(ok)
        self.assertTrue(p2["ok"])

    def test_ctx_and_impact_actions(self):
        sess = self._sess()
        ok, p, s = nova.web_intel_action(
            sess, {"action": "ctx", "query": "flask project"})
        self.assertTrue(ok)
        self.assertIn("sources", p)
        ok, p2, _ = nova.web_intel_action(
            sess, {"action": "impact", "paths": ["pkg/core.py"]})
        self.assertTrue(ok)
        self.assertEqual(p2["report"]["risk"], "high")

    def test_gentests_action_and_error(self):
        sess = self._sess()
        ok, p, _ = nova.web_intel_action(
            sess, {"action": "gentests", "path": "pkg/util.py"})
        self.assertTrue(ok)
        self.assertTrue(p["result"]["ok"])
        ok2, p2, s2 = nova.web_intel_action(
            sess, {"action": "gentests", "path": "ghost.py"})
        self.assertFalse(ok2)
        self.assertEqual(s2, 400)

    def test_regress_actions(self):
        sess = self._sess()
        ok, _p, _s = nova.web_intel_action(sess,
                                           {"action": "regress_baseline"})
        self.assertTrue(ok)
        ok2, p2, _ = nova.web_intel_action(sess,
                                           {"action": "regress_check"})
        self.assertTrue(ok2)
        self.assertIn("verdict", p2["result"])


import http.client  # noqa: E402
import threading  # noqa: E402

import web_server  # noqa: E402


def _reset_web_guards():
    try:
        import nova_security as _nsec
        _nsec.API_LIMITER.reset()
        _nsec.SECURE_API_LIMITER.reset()
        _nsec.AUTH_THROTTLE.reset()
    except Exception:
        pass


class _ServerCase(unittest.TestCase):
    def setUp(self):
        _reset_web_guards()
        self._tmpdir = tempfile.TemporaryDirectory()
        workspace = Path(self._tmpdir.name)
        web_server.STATE = web_server._State(workspace)
        web_server.AUTH_TOKEN = None
        self.httpd = web_server._make_server({"host": "127.0.0.1",
                                              "port": 0})
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self._conns = []
        self.ws = str(workspace)

    def tearDown(self):
        for c in self._conns:
            try:
                c.close()
            except Exception:
                pass
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        web_server.STATE = None
        web_server.AUTH_TOKEN = None
        self._tmpdir.cleanup()

    def conn(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        self._conns.append(c)
        return c

    def _get(self, path):
        c = self.conn()
        c.request("GET", path)
        r = c.getresponse()
        return r.status, json.loads(r.read().decode("utf-8"))

    def _post(self, path, body):
        c = self.conn()
        c.request("POST", path, body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read().decode("utf-8"))


class TestIntelServerFlow(_ServerCase):
    def test_get_intel_empty_workspace(self):
        status, data = self._get("/api/intel")
        self.assertEqual(status, 200)
        self.assertTrue(data["available"])
        self.assertEqual(data["tasks"]["list"], [])
        self.assertEqual(data["memory"]["stats"]["records"], 0)

    def test_post_task_then_visible_in_get(self):
        status, data = self._post("/api/intel",
                                  {"action": "task_add",
                                   "title": "build the shop cart",
                                   "deps": []})
        self.assertEqual(status, 200)
        tid = data["id"]
        status2, data2 = self._get("/api/intel")
        self.assertEqual(status2, 200)
        ids = [t["id"] for t in data2["tasks"]["list"]]
        self.assertIn(tid, ids)
        row = [t for t in data2["tasks"]["list"] if t["id"] == tid][0]
        self.assertEqual(row["status"], "todo")

    def test_post_remember_then_state_shows_it(self):
        self._post("/api/intel", {"action": "mem_remember",
                                  "text": "the api token rotates weekly",
                                  "kind": "fact"})
        _s, data = self._get("/api/intel")
        texts = " ".join(r["text"] for r in
                         data["memory"]["recent"])
        self.assertIn("api token", texts)

    def test_post_unknown_action_400(self):
        status, data = self._post("/api/intel", {"action": "hack"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_post_bad_json_400(self):
        c = self.conn()
        c.request("POST", "/api/intel", body="not-json",
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        self.assertEqual(r.status, 400)

    def test_status_clear_empties_events(self):
        self._post("/api/intel", {"action": "task_add", "title": "x"})
        self._post("/api/intel", {"action": "status_clear"})
        _s, data = self._get("/api/intel")
        self.assertEqual(data["status"], {})


class TestIntelUIPins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parent.parent /
                    "web" / "index.html").read_text(encoding="utf-8")

    def test_intel_tab_button(self):
        self.assertIn('data-view="intel"', self.html)
        self.assertIn("هوش", self.html)

    def test_intel_panel_and_outputs(self):
        for el_id in ("panel-intel", "intelAgentOut", "intelAgentEvents",
                      "intelTasksOut", "intelTaskRows", "intelMemOut",
                      "intelProjectOut", "intelRegOut"):
            self.assertIn(el_id, self.html)

    def test_intel_js_functions_wired(self):
        for fn in ("refreshIntel", "renderIntelAgent", "renderIntelTasks",
                   "renderIntelMemory", "renderIntelProject",
                   "renderIntelRegression", "intelAction"):
            self.assertIn("function " + fn, self.html) if fn.startswith(
                "render") or fn == "refreshIntel" else None
        self.assertIn('intel: () => refreshIntel()', self.html)
        self.assertIn('"/api/intel"', self.html)
        self.assertIn("action: \"task_add\"", self.html)
        self.assertIn("action: \"regress_check\"", self.html)

    def test_view_loader_registered_and_tab_active(self):
        # intel is NOT in the disabled views
        self.assertNotIn('"intel": "', self.html)
        self.assertIn('data-view="intel" type="button"',
                      self.html.replace(' data-view="intel"',
                                        ' data-view="intel"'))


if __name__ == "__main__":
    unittest.main()
