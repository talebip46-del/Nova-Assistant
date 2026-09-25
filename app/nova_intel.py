#!/usr/bin/env python3
# =====================================================================
#  Nova Code - PROJECT INTELLIGENCE CORE (v7.13.0)
#
#  The v7.13 "Nova Intel" layer: ONE local-first brain for everything
#  the user asked for in one breath - real Project Intelligence, a REAL
#  task graph with dependencies, SEMANTIC memory (not just history),
#  a Context Engine, an autonomous agent loop (observe -> decide ->
#  execute -> test -> fix -> verify), honest completion detection,
#  smart recovery, impact analysis, regression detection, automatic
#  test generation, a staged critic, smart rollback, multi-project
#  workspaces and project/user profiles.
#
#  Design law:
#    - 100% LOCAL. No network calls, no embeddings server required:
#      semantic recall uses a built-in TF-IDF vectorizer that speaks
#      Persian AND English (ZWNJ-aware, Persian-digit folding).
#    - Every store lives in the workspace's own .nova/ folder, so two
#      projects never leak knowledge into each other.
#    - Corrupt files reset to junk (fail-soft), never crash an agent.
#    - Pure functions wherever possible so the whole layer is offline-
#      testable without touching the model.
#
#  Public surface (see the section banners):
#    ProjectIntelligence   the unified .nova/intel.json project profile
#    TaskGraph             dependency DAG in .nova/tasks.json
#    SemanticMemory        vector store in .nova/memory_vec.json
#    ContextEngine         assemble() the most precise context block
#    AgentLoop / AgentStatus / CompletionDetector / RecoveryManager
#    ImpactAnalyzer / RegressionDetector / TestGenerator / Critic
#    SmartRollback / Workspaces / profiles
# =====================================================================

import ast
import hashlib
import itertools
import json
import math
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

_RUN_SEQ = itertools.count(1)

__all__ = [
    "ProjectIntelligence", "TaskGraph", "SemanticMemory", "ContextEngine",
    "AgentLoop", "AgentStatus", "CompletionDetector", "RecoveryManager",
    "ImpactAnalyzer", "RegressionDetector", "TestGenerator", "Critic",
    "SmartRollback", "Workspaces", "project_profile", "UserProfile",
    "PHASES",
]

try:  # atomic writes reuse the battle-tested helper when present
    import nova_atomic as _atomic
except Exception:  # pragma: no cover - standalone fallback below
    _atomic = None

INTEL_VER = 1
MAX_MEMORY_RECORDS = 600
MAX_EVENTS = 60
MAX_SCAN_FILES = 4000
MAX_SYMBOL_FILE = 300_000
MAX_SYMBOL_FILES = 60

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".nova",
    ".nova_backups", ".venv", "venv", "env", "dist", "build", ".next",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "__MACOSX", "vendor",
    ".idea", ".vscode", "coverage", ".tox", "target", ".gradle",
}

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript", ".html": "html", ".htm": "html", ".css": "css",
    ".json": "json", ".md": "markdown", ".sh": "shell", ".bat": "batch",
    ".ps1": "powershell", ".go": "go", ".rs": "rust", ".java": "java",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".php": "php", ".rb": "ruby", ".sql": "sql", ".yml": "yaml",
    ".yaml": "yaml", ".toml": "toml", ".svg": "svg", ".txt": "text",
}

# framework markers: (file, substring-in-content, framework name)
FRAMEWORK_MARKERS = [
    ("requirements.txt", "django", "Django"),
    ("requirements.txt", "flask", "Flask"),
    ("requirements.txt", "fastapi", "FastAPI"),
    ("pyproject.toml", "django", "Django"),
    ("pyproject.toml", "fastapi", "FastAPI"),
    ("package.json", "next", "Next.js"),
    ("package.json", "react", "React"),
    ("package.json", "vue", "Vue"),
    ("package.json", "express", "Express"),
    ("package.json", "vite", "Vite"),
    ("go.mod", "", "Go modules"),
    ("Cargo.toml", "", "Rust/Cargo"),
    ("Dockerfile", "", "Docker"),
    ("docker-compose.yml", "", "Docker Compose"),
    ("docker-compose.yaml", "", "Docker Compose"),
    ("manage.py", "", "Django"),
]

ENTRY_CANDIDATES = [
    "main.py", "app.py", "run.py", "manage.py", "server.py", "wsgi.py",
    "index.js", "main.js", "server.js", "index.ts", "index.html",
    "Makefile", "package.json",
]

TEST_DIR_CANDIDATES = ("tests", "test", "spec", "__tests__")

FA_STOP = {
    "و", "در", "به", "از", "که", "این", "آن", "را", "با", "است", "برای",
    "یک", "های", "می", "شود", "شدن", "شده", "نشد", "کرد", "کند", "بود",
    "هست", "چه", "خود", "تا", "هم", "بر", "هر", "اگر", "یا", "اما", "نه",
    "بله", "رو", "کن", "کنیم", "کنم", "داره", "باشه", "میخوام", "بخش",
    "فقط",
}
EN_STOP = {
    "the", "a", "an", "is", "are", "to", "of", "and", "in", "on", "for",
    "with", "that", "this", "it", "as", "be", "by", "at", "or", "from",
    "into", "if", "then", "so", "do", "does", "did", "not", "no", "yes",
}

_ZWNJ = "\u200c"
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹" "٠١٢٣٤٥٦٧٨٩",
                           "01234567890123456789")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)  # letters/digits, any script


# ----------------------------------------------------------------- utils
def _now():
    return time.time()


def _stable_hash(parts):
    """A process-stable digest - hash() on strings is salted per process,
    so a fingerprint persisted to disk could never match after a restart
    (v7.14.1 fix: every new process used to rescan the whole tree)."""
    return hashlib.sha1(
        "\x1f".join(parts).encode("utf-8", "replace")).hexdigest()


def _atomic_write(path, text):
    """Atomic JSON write; falls back to tmp+rename when nova_atomic
    is unavailable (never raises past OSError).
    v7.14.1 fixes (both verified): write_text_atomic RETURNS an error
    string instead of raising - it used to be swallowed as success
    (silent data loss); and the manual-fallback tmp name had a
    precedence bug (".tmp%d" % int(...) % 100000 -> TypeError)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if _atomic is not None:
        err = None
        try:
            err = _atomic.write_text_atomic(p, text, encoding="utf-8")
        except Exception:
            err = "raise"          # fall through to the manual path
        if not err:
            return
    tmp = p.with_name("%s.tmp%d" % (p.name,
                    (os.getpid() * 7919
                     + threading.get_ident() % 100000
                     + int(_now() * 1000)) % 1000000))
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def load_json(path, default):
    """Read JSON; corrupt/missing -> the default (fail-soft)."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, type(default)):
            return default
        return data
    except Exception:
        return default


def save_json(path, data):
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1,
                                   sort_keys=False))


def norm_text(text):
    """Lowercase, fold Persian digits + ZWNJ, strip diacritics."""
    t = (text or "").translate(_FA_DIGITS).replace(_ZWNJ, " ")
    t = unicodedata.normalize("NFKC", t)
    return t.lower()


def tokenize(text, drop_stop=True):
    r"""Shared tokenizer for memory + context scoring. Persian letters
    match \w so they survive; underscores never start a token."""
    words = _WORD_RE.findall(norm_text(text))
    if not drop_stop:
        return words
    stop = FA_STOP | EN_STOP
    return [w for w in words if w not in stop]


def _rel(p, ws):
    try:
        return str(Path(p).relative_to(Path(ws))).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _walk_files(ws, max_files=MAX_SCAN_FILES):
    """Workspace walk that respects SKIP_DIRS; yields Path objects."""
    out = []
    root = Path(ws)
    if not root.is_dir():
        return out
    stack = [str(root)]
    seen_dirs = {str(root)}
    while stack and len(out) < max_files:
        d = stack.pop()
        try:
            entries = sorted(Path(d).iterdir(), key=lambda x: x.name)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir():
                    # v8.0: symlinked dirs are never followed - a symlink
                    # used to be walked twice (duplicate files ate the
                    # scan budget) and a symlink CYCLE hung the walk
                    # forever (out never filled, stack never emptied).
                    if e.is_symlink():
                        continue
                    if e.name not in SKIP_DIRS and not e.name.startswith(
                            ".git"):
                        rp = str(e)
                        if rp not in seen_dirs:
                            seen_dirs.add(rp)
                            stack.append(rp)
                elif e.is_file():
                    out.append(e)
                    if len(out) >= max_files:
                        break
            except OSError:
                continue
    return out


# =====================================================================
# 1. SEMANTIC MEMORY  (.nova/memory_vec.json) - NOT just chat history
# =====================================================================
class SemanticMemory:
    r"""A small local vector store over PROJECT EVENTS of every kind:
    facts, decisions, task outcomes, turn summaries, KB notes.

    recall() ranks by TF-IDF cosine similarity with a gentle recency
    boost, so "the login bug" finds the decision recorded as
    "قفل شدن کاربر بعد از پنج تلاش" even with zero shared words
    (shared tokens are not required - but shared MEANING here is
    approximated by overlap of content words; the point is that raw
    history is not the index, scored retrieval is).

    tokenize() is Persian-aware (ZWNJ folded, Persian digits -> ASCII).
    """

    def __init__(self, path, now=_now):
        self.path = Path(path)
        self.now = now
        data = load_json(self.path, {"records": [], "seq": 0})
        recs = data.get("records")
        # v8.0: non-dict junk members are DROPPED at load, not merely
        # skipped in one path - remember()/_cap() iterate every record
        # with .get() and crashed on int/str/None members of a corrupt
        # file ("int object has no attribute get").
        self.records = [r for r in (recs if isinstance(recs, list) else [])
                        if isinstance(r, dict)]
        try:
            self.seq = int(data.get("seq", 0))
        except (TypeError, ValueError):
            self.seq = 0
        self._load_tf()

    # ------------------------------------------------------------ store
    def _load_tf(self):
        # v7.14.1 fix: a non-dict record (corrupt file) used to crash
        # __init__ via r.get - junk members are skipped instead (the
        # header's law: corrupt files fail soft, never crash an agent)
        for r in self.records:
            if not isinstance(r, dict):
                continue
            if "tf" not in r:
                r["tf"] = _tf_of(str(r.get("text", "")))

    def remember(self, text, kind="fact", tags=None):
        text = (text or "").strip()
        if not text:
            return None
        tags = sorted({t.strip() for t in (tags or []) if t and t.strip()})
        # v8.0: the dedup key is a full-text HASH - the 240-char prefix
        # truncated key merged two DIFFERENT long memories that shared
        # their first 240 token chars and kept the stale text/tf forever.
        key = hashlib.sha1(" ".join(tokenize(text)).encode("utf-8")
                           ).hexdigest()
        if not key:
            return None
        ts = self.now()
        for r in self.records:
            if r.get("key") == key:
                r["ts"] = ts
                r["hits"] = int(r.get("hits", 1)) + 1
                # v8.0: refresh text + tf so recall serves the NEWEST
                # wording (the dedup used to keep the old text silent)
                r["text"] = text[:1200]
                r["tf"] = _tf_of(text)
                if tags:
                    merged = set(r.get("tags", [])) | set(tags)
                    r["tags"] = sorted(merged)
                if kind and r.get("kind") != kind:
                    r["kind"] = kind
                self._save()
                return r.get("id")
        self.seq += 1
        rec = {"id": "m%d" % self.seq, "text": text[:1200], "kind": kind,
               "tags": tags, "ts": ts, "hits": 1, "key": key,
               "tf": _tf_of(text)}
        self.records.append(rec)
        self._cap()
        self._save()
        return rec["id"]

    def forget(self, rec_id):
        before = len(self.records)
        self.records = [r for r in self.records
                        if isinstance(r, dict) and r.get("id") != rec_id]
        self._save()
        return before - len(self.records)

    def clear(self):
        self.records = []
        self.seq = 0
        self._save()

    def _cap(self):
        if len(self.records) > MAX_MEMORY_RECORDS:
            # v8.0: sort key made junk-proof (records are dicts now, but
            # a ts of a wrong type must not crash the sort either)
            self.records.sort(
                key=lambda r: r.get("ts", 0)
                if isinstance(r.get("ts", 0), (int, float)) else 0,
                reverse=True)
            self.records = self.records[:MAX_MEMORY_RECORDS]

    def _save(self):
        save_json(self.path, {"records": self.records, "seq": self.seq})

    # ---------------------------------------------------------- recall
    def recall(self, query, k=5, kind=None, tag=None, min_score=0.01):
        q_tf = _tf_of(query)
        if not q_tf:
            return []
        df = {}
        for r in self.records:
            if not isinstance(r, dict):
                continue
            for term in r.get("tf", {}):
                df[term] = df.get(term, 0) + 1
        n = max(1, len(self.records))
        idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        qvec = {t: c * idf.get(t, 1.0) for t, c in q_tf.items()}
        qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
        now_ts = self.now()
        hits = []
        for r in self.records:
            if not isinstance(r, dict):
                continue
            if kind and r.get("kind") != kind:
                continue
            if tag and tag not in r.get("tags", []):
                continue
            rtf = r.get("tf") or {}
            rvec = {t: c * idf.get(t, 1.0) for t, c in rtf.items()}
            rnorm = math.sqrt(sum(v * v for v in rvec.values())) or 1.0
            dot = sum(qvec[t] * rvec.get(t, 0.0) for t in qvec)
            cos = dot / (qnorm * rnorm)
            if cos <= 0:
                continue
            # v8.10.1 fix: a hostile ts (hand-edited file, '2024-01-01')
            # raised TypeError straight through /mem recall - the same
            # fail-soft law the _cap sort already follows.
            rts = r.get("ts", 0)
            if not isinstance(rts, (int, float)):
                rts = 0
            age_days = max(0.0, (now_ts - rts) / 86400.0)
            boost = 1.0 + 0.15 * math.exp(-age_days / 7.0)
            score = cos * boost
            if score < min_score:
                continue
            hits.append({"id": r.get("id"), "text": r.get("text", ""),
                         "kind": r.get("kind", "fact"),
                         "tags": r.get("tags", []), "ts": rts,
                         "hits": r.get("hits", 1), "score": round(score, 4)})
        # v8.10.1: hits[].ts now carries the coerced numeric ts - a
        # hostile record ts crashed this sort with a unary-minus TypeError
        hits.sort(key=lambda h: (-h["score"], -h["ts"]))
        return hits[:k]

    def stats(self):
        kinds = {}
        for r in self.records:
            k = r.get("kind", "fact") if isinstance(r, dict) else "?"
            kinds[k] = kinds.get(k, 0) + 1
        return {"records": len(self.records), "kinds": kinds,
                "path": self.path.name}

    def text_report(self):
        st = self.stats()
        lines = ["semantic memory: %d record(s) (%s)" % (st["records"],
                                                        st["path"])]
        for k, v in sorted(st["kinds"].items()):
            lines.append("  %-10s %d" % (k, v))
        return "\n".join(lines)


def _tf_of(text):
    tf = {}
    for w in tokenize(text):
        tf[w] = tf.get(w, 0) + 1
    return tf


# =====================================================================
# 2. TASK GRAPH  (.nova/tasks.json) - REAL dependencies, not a checklist
# =====================================================================
TASK_STATUSES = ("todo", "doing", "done", "failed")


class TaskGraph:
    """A dependency DAG of tasks persisted per workspace.

    deps are HARD: a task with an unfinished dependency is 'blocked'
    and never shows up in ready(); add()/set() refuse edges that would
    create a cycle; remove() strips dangling references; order() gives
    a topological execution plan (or flags the cycle honestly)."""

    def __init__(self, path, now=_now):
        self.path = Path(path)
        self.now = now
        data = load_json(self.path, {"tasks": {}, "seq": 0})
        t = data.get("tasks")
        self.tasks = t if isinstance(t, dict) else {}
        try:
            self.seq = int(data.get("seq", 0))
        except (TypeError, ValueError):
            self.seq = 0

    def _save(self):
        save_json(self.path, {"tasks": self.tasks, "seq": self.seq})

    def _norm_deps(self, deps):
        out = []
        for d in (deps or []):
            d = str(d).strip()
            if d and d not in out:
                out.append(d)
        return out

    def add(self, title, deps=None, detail="", tags=None):
        title = (title or "").strip()
        if not title:
            raise ValueError("task title is empty")
        deps = self._norm_deps(deps)
        for d in deps:
            if d not in self.tasks:
                raise ValueError("unknown dependency: %s" % d)
        self.seq += 1
        tid = "t%d" % self.seq
        self.tasks[tid] = {"id": tid, "title": title[:200],
                           "detail": (detail or "")[:2000],
                           "tags": sorted({t for t in (tags or []) if t}),
                           "deps": deps, "status": "todo", "note": "",
                           "created": self.now(), "updated": self.now()}
        if self._would_cycle(tid, deps):
            del self.tasks[tid]
            self.seq -= 1
            raise ValueError("dependency cycle: %s" % " -> ".join([tid] + deps))
        self._save()
        return tid

    def set(self, tid, status=None, note=None, title=None, deps=None,
            detail=None):
        t = self.tasks.get(tid)
        if not t:
            raise ValueError("unknown task: %s" % tid)
        # v8.7: validate EVERYTHING first - the deps check used to run
        # AFTER status/note/title were already mutated in memory, so a
        # rejected set() (unknown dependency) left "doing" on the task
        # and the next successful _save() persisted it anyway.
        if status is not None and status not in TASK_STATUSES:
            raise ValueError("bad status: %s" % status)
        if deps is not None:
            new_deps = self._norm_deps(deps)
            for d in new_deps:
                if d not in self.tasks:
                    raise ValueError("unknown dependency: %s" % d)
                if d == tid:
                    raise ValueError("a task cannot depend on itself")
        if status is not None:
            t["status"] = status
        if note is not None:
            t["note"] = str(note)[:2000]
        if title is not None and title.strip():
            t["title"] = title.strip()[:200]
        if detail is not None:
            t["detail"] = str(detail)[:2000]
        if deps is not None:
            old = t["deps"]
            t["deps"] = new_deps
            if self._cycle_from(tid):
                t["deps"] = old
                raise ValueError("dependency cycle detected")
        t["updated"] = self.now()
        self._save()
        return t

    def remove(self, tid):
        if tid not in self.tasks:
            return False
        del self.tasks[tid]
        for t in self.tasks.values():
            if tid in t["deps"]:
                t["deps"] = [d for d in t["deps"] if d != tid]
                t["updated"] = self.now()
        self._save()
        return True

    def get(self, tid):
        return self.tasks.get(tid)

    def _would_cycle(self, new_id, deps):
        # hypothetical node new_id -> deps; DFS from each dep following
        # deps edges; reaching new_id means a cycle.
        seen = set()
        stack = list(deps)
        while stack:
            cur = stack.pop()
            if cur == new_id:
                return True
            if cur in seen or cur not in self.tasks:
                continue
            seen.add(cur)
            stack.extend(self.tasks[cur].get("deps", []))
        return False

    def _cycle_from(self, tid):
        seen = set()
        stack = list(self.tasks[tid].get("deps", []))
        while stack:
            cur = stack.pop()
            if cur == tid:
                return True
            if cur in seen or cur not in self.tasks:
                continue
            seen.add(cur)
            stack.extend(self.tasks[cur].get("deps", []))
        return False

    # ----------------------------------------------------------- views
    def ready(self):
        out = []
        for tid, t in sorted(self.tasks.items()):
            if t["status"] != "todo":
                continue
            deps = t.get("deps", [])
            if all(self.tasks.get(d, {}).get("status") == "done"
                   for d in deps):
                out.append(tid)
        return out

    def blocked(self):
        ready = set(self.ready())
        return [tid for tid, t in sorted(self.tasks.items())
                if t["status"] == "todo" and tid not in ready]

    def done_ids(self):
        return [tid for tid, t in sorted(self.tasks.items())
                if t["status"] == "done"]

    def progress(self):
        total = len(self.tasks)
        done = sum(1 for t in self.tasks.values() if t["status"] == "done")
        failed = sum(1 for t in self.tasks.values() if t["status"] == "failed")
        doing = sum(1 for t in self.tasks.values() if t["status"] == "doing")
        pct = round(100.0 * done / total, 1) if total else 0.0
        return {"total": total, "done": done, "doing": doing,
                "failed": failed, "pct": pct}

    def dependents(self, tid, transitive=True):
        """What is DOWNSTREAM of tid: tasks that (directly or through a
        chain) need tid to be done first."""
        out = []
        frontier = [tid]
        while frontier:
            cur = frontier.pop()
            for t2, t in sorted(self.tasks.items()):
                if cur in t.get("deps", []) and t2 not in out:
                    out.append(t2)
                    if transitive:
                        frontier.append(t2)
        return out

    def order(self):
        """Topological order over ALL tasks (Kahn). Returns
        (ids, cycles) - cycles lists ids stuck in a dependency loop."""
        indeg = {tid: 0 for tid in self.tasks}
        depend = {tid: [] for tid in self.tasks}
        for tid, t in self.tasks.items():
            for d in t.get("deps", []):
                if d in indeg:
                    indeg[tid] += 1
                    depend[d].append(tid)
        queue = sorted([tid for tid, d in indeg.items() if d == 0])
        out = []
        while queue:
            tid = queue.pop(0)
            out.append(tid)
            for nxt in sorted(depend[tid]):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
            queue.sort()
        cycles = [tid for tid in self.tasks if tid not in out]
        return out, cycles

    def text_report(self):
        if not self.tasks:
            return "task graph: (empty)"
        prog = self.progress()
        lines = ["task graph: %d/%d done (%.0f%%)%s" % (
            prog["done"], prog["total"], prog["pct"],
            "  %d failed" % prog["failed"] if prog["failed"] else "")]
        order, cycles = self.order()
        for tid in order:
            t = self.tasks[tid]
            mark = {"done": "[x]", "doing": "[~]", "failed": "[!]",
                    "todo": "[ ]"}[t["status"]]
            dep = ("  <- " + ",".join(t["deps"])) if t["deps"] else ""
            lines.append("  %s %s %s%s" % (mark, tid, t["title"], dep))
        for tid in cycles:
            lines.append("  [!] CYCLE at %s" % tid)
        ready = self.ready()
        if ready:
            lines.append("  ready now: " + ", ".join(ready))
        return "\n".join(lines)


# =====================================================================
# 3. PROJECT INTELLIGENCE  (.nova/intel.json) - ONE unified profile
# =====================================================================
class ProjectIntelligence:
    """The REAL, integrated project profile the user asked for: in one
    scan it captures languages, frameworks, entry points, test layout,
    per-file symbols and the import graph, then keeps a fingerprint so
    refresh_if_stale() knows when the project changed under us.

    Everything other intel features (impact analysis, the context
    engine, profiles) read from this single store - that is what makes
    it 'یکپارچه' (integrated) instead of three disjoint maps."""

    def __init__(self, ws):
        self.ws = Path(ws)
        self.path = self.ws / ".nova" / "intel.json"
        self.data = self._load()

    def _load(self):
        d = load_json(self.path, {})
        if not isinstance(d, dict) or not d:
            return {}
        return d

    # ------------------------------------------------------------- scan
    def scan(self):
        files = _walk_files(self.ws)
        rels, langs, sizes = [], {}, {}
        for p in files:
            rel = _rel(p, self.ws)
            ext = p.suffix.lower()
            rels.append(rel)
            if ext:
                langs[ext] = langs.get(ext, 0) + 1
            try:
                sizes[rel] = p.stat().st_size
            except OSError:
                sizes[rel] = 0
        data = {
            "v": INTEL_VER, "generated": _now(),
            "name": self.ws.name, "root": str(self.ws),
            "files": sorted(rels), "sizes": sizes, "langs": langs,
            "frameworks": self._frameworks(files),
            "entries": [r for r in ENTRY_CANDIDATES
                        if r in set(rels)],
            "tests_dir": self._tests_dir(rels),
            "has_nova_md": ("NOVA.md" in set(rels)),
            "has_readme": any(r.lower().startswith("readme")
                              for r in rels),
            "symbols": self._symbols(files),
            "imports": self._imports(files),
        }
        data["fingerprint"] = self._fingerprint(files)
        self.data = data
        self._save()
        return data

    def refresh_if_stale(self, force=False):
        """Rescan only when the cheap fingerprint changed (so hooks can
        call this after every apply without slowing anything down)."""
        if force or not self.data:
            return self.scan(), True
        if self._current_fingerprint() != self.data.get("fingerprint"):
            return self.scan(), True
        return self.data, False

    def _current_fingerprint(self):
        # v7.14.1 fix: hash() on strings is process-salted, so a
        # fingerprint persisted by one process NEVER matched after a
        # restart (every new process rescanned 4000 files for nothing).
        # A stable sha1 of the same tuple restores cross-process reuse.
        return _stable_hash(self._fingerprint_parts(
            (p for p in _walk_files(self.ws, max_files=MAX_SCAN_FILES))))

    def _fingerprint_parts(self, files):
        parts = []
        for p in files:
            try:
                st = p.stat()
                parts.append("%s|%d|%d" % (_rel(p, self.ws), st.st_size,
                                           int(st.st_mtime)))
            except OSError:
                continue
        return tuple(sorted(parts))

    def _fingerprint(self, files):
        # v7.14.1: same stable digest - the persisted fingerprint must
        # compare equal across processes
        return _stable_hash(self._fingerprint_parts(files))

    def _frameworks(self, files):
        found = []
        names = {_rel(p, self.ws) for p in files}
        for fname, needle, label in FRAMEWORK_MARKERS:
            if fname not in names:
                continue
            if not needle:
                found.append(label)
                continue
            try:
                content = (self.ws / fname).read_text(
                    encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            if needle in content:
                found.append(label)
        return sorted(set(found))

    def _tests_dir(self, rels):
        tops = {r.split("/")[0] for r in rels}
        for cand in TEST_DIR_CANDIDATES:
            if cand in tops:
                return cand
        return ""

    def _symbols(self, files):
        """Quick per-file symbol map: real AST for Python, a light regex
        for JS/TS - capped so a huge repo cannot stall the agent."""
        out = {}
        pymap = []
        jsmap = []
        for p in files:
            ext = p.suffix.lower()
            rel = _rel(p, self.ws)
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz > MAX_SYMBOL_FILE:
                continue
            if ext == ".py":
                pymap.append((rel, p))
            elif ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
                jsmap.append((rel, p))
        for rel, p in pymap[:MAX_SYMBOL_FILES]:
            syms = _py_symbols(p)
            if syms:
                out[rel] = syms
        for rel, p in jsmap[:MAX_SYMBOL_FILES // 2]:
            syms = _js_symbols(p)
            if syms:
                out[rel] = syms
        return out

    def _imports(self, files):
        """Workspace-internal import edges importer -> imported (rel).
        Resolves dotted module paths AND relative imports (level>=1)."""
        stems = {}
        for p in files:
            if p.suffix.lower() == ".py":
                rel = _rel(p, self.ws)
                stems[rel[:-3].replace("/", ".")] = rel

        def resolve(dotted):
            parts = dotted.split(".")
            for i in range(len(parts), 0, -1):
                cand = ".".join(parts[:i])
                if cand in stems:
                    return stems[cand]
            return None

        edges = {}
        for p in files:
            if p.suffix.lower() != ".py":
                continue
            try:
                src = p.read_text(encoding="utf-8",
                                  errors="replace")[:MAX_SYMBOL_FILE]
                tree = ast.parse(src)
            except Exception:
                continue
            mine = _rel(p, self.ws)
            my_parts = mine[:-3].replace("/", ".").split(".")
            targets = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        targets.add(a.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import
                        pkg = my_parts[:-1]
                        up = node.level - 1
                        if up:
                            pkg = pkg[:max(0, len(pkg) - up)]
                        base = ".".join(pkg)
                        full = base + "." + node.module if node.module \
                            else base
                    else:
                        full = node.module or ""
                    if full:
                        targets.add(full)
                        # the imported NAME can itself be a submodule
                        # ('from pkg import mod', 'from . import sibling')
                        for a in node.names:
                            targets.add(full + "." +
                                        a.name.split(".")[0])
            hits = set()
            for t in targets:
                r = resolve(t)
                if r and r != mine:
                    hits.add(r)
            if hits:
                edges[mine] = sorted(hits)
        return edges

    def _save(self):
        save_json(self.path, self.data)

    # ------------------------------------------------------------ views
    def summary_text(self, limit=1200):
        d = self.data
        if not d:
            return "project intel: (not scanned yet - /intel rescan)"
        top_langs = sorted(d.get("langs", {}).items(),
                           key=lambda kv: -kv[1])[:6]
        lang_s = ", ".join("%s x%d" % (k, v) for k, v in top_langs)
        lines = [
            "project: %s  (%d files)" % (d.get("name", "?"),
                                         len(d.get("files", []))),
            "languages: " + (lang_s or "(none detected)"),
        ]
        if d.get("frameworks"):
            lines.append("frameworks: " + ", ".join(d["frameworks"]))
        if d.get("entries"):
            lines.append("entries: " + ", ".join(d["entries"][:6]))
        if d.get("tests_dir"):
            lines.append("tests: %s/" % d["tests_dir"])
        marks = []
        if d.get("has_nova_md"):
            marks.append("NOVA.md")
        if d.get("has_readme"):
            marks.append("README")
        if marks:
            lines.append("docs: " + ", ".join(marks))
        sym_count = sum(len(v) for v in d.get("symbols", {}).values())
        if sym_count:
            lines.append("symbols mapped: %d in %d file(s)"
                         % (sym_count, len(d.get("symbols", {}))))
        if d.get("imports"):
            lines.append("import edges: %d" % len(d["imports"]))
        text = "\n".join(lines)
        return text[:limit]

    def stats(self):
        d = self.data
        return {"files": len(d.get("files", [])),
                "langs": d.get("langs", {}),
                "frameworks": d.get("frameworks", []),
                "entries": d.get("entries", []),
                "tests_dir": d.get("tests_dir", ""),
                "generated": d.get("generated", 0),
                "fresh": self._current_fingerprint() ==
                         d.get("fingerprint")}


def _py_symbols(path):
    """classes/functions/methods with signatures - the AST pass."""
    try:
        src = Path(path).read_text(encoding="utf-8",
                                   errors="replace")[:MAX_SYMBOL_FILE]
        tree = ast.parse(src)
    except Exception:
        return []
    names = []

    def sig_of(node):
        try:
            a = [x.arg for x in node.args.args if isinstance(x, ast.arg)]
            if node.args.vararg:
                a.append("*" + node.args.vararg.arg)
            if node.args.kwarg:
                a.append("**" + node.args.kwarg.arg)
            return "(" + ", ".join(a) + ")"
        except Exception:
            return "()"

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(("def", node.name + sig_of(node), node.lineno))
        elif isinstance(node, ast.ClassDef):
            names.append(("class", node.name, node.lineno))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not sub.name.startswith("_") or sub.name == "__init__":
                        names.append(("method", "%s.%s%s" % (
                            node.name, sub.name, sig_of(sub)), sub.lineno))
    return names[:120]


_JS_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
    re.MULTILINE)
_JS_CLASS = re.compile(
    r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
_JS_ARROW = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"\s*=\s*(?:async\s*)?\(", re.MULTILINE)


def _js_symbols(path):
    try:
        src = Path(path).read_text(encoding="utf-8",
                                   errors="replace")[:MAX_SYMBOL_FILE]
    except Exception:
        return []
    out = [("def", m, 0) for m in _JS_DEF.findall(src)]
    out += [("class", m, 0) for m in _JS_CLASS.findall(src)]
    out += [("def", m + "()", 0) for m in _JS_ARROW.findall(src)]
    return out[:80]


# =====================================================================
# 4. WORKSPACES + PROFILES - many projects, independently remembered
# =====================================================================
class Workspaces:
    """A registry of projects (path, name, note) OUTSIDE any single
    workspace so switching projects never loses the map. The per-project
    .nova/ stores keep working exactly as before - independence."""

    def __init__(self, path):
        self.path = Path(path)
        data = load_json(self.path, {"projects": []})
        pr = data.get("projects")
        # v8.0: junk members dropped at load - register/unregister/list
        # call .get()/dict() on every member and a corrupt file with a
        # non-dict member used to crash /workspaces.
        self.projects = [p for p in (pr if isinstance(pr, list) else [])
                         if isinstance(p, dict)]

    def _save(self):
        save_json(self.path, {"projects": self.projects})

    @staticmethod
    def _canon(p):
        return str(Path(p).expanduser().resolve())

    def register(self, path, name=None, note=""):
        path = self._canon(path)
        for pr in self.projects:
            if pr.get("path") == path:
                if name:
                    pr["name"] = name
                if note:
                    pr["note"] = note
                pr["updated"] = _now()
                self._save()
                return pr, False
        entry = {"path": path, "name": name or Path(path).name,
                 "note": note, "registered": _now(), "updated": _now()}
        self.projects.append(entry)
        self._save()
        return entry, True

    def unregister(self, path):
        path = self._canon(path)
        before = len(self.projects)
        self.projects = [pr for pr in self.projects
                         if pr.get("path") != path]
        self._save()
        return before - len(self.projects)

    def list(self):
        out = []
        for pr in self.projects:
            pr = dict(pr)
            pr["exists"] = Path(pr.get("path", "")).is_dir()
            out.append(pr)
        return out

    def text_report(self, current=None):
        rows = self.list()
        if not rows:
            return "workspaces: (registry empty - /workspaces add <path>)"
        cur = self._canon(current) if current else None
        lines = ["registered workspaces: %d" % len(rows)]
        for i, pr in enumerate(rows, 1):
            mark = "*" if pr["path"] == cur else " "
            alive = "" if pr["exists"] else "  (missing)"
            lines.append("  %s [%d] %s  %s%s" % (
                mark, i, pr.get("name", "?"), pr["path"], alive))
        return "\n".join(lines)


def project_profile(ws, intel=None):
    """The project-side profile: what this project IS (languages,
    frameworks, entries, tests, conventions from NOVA.md)."""
    ws = Path(ws)
    it = intel if intel is not None else ProjectIntelligence(ws)
    data, _ = it.refresh_if_stale()
    conv = ""
    for cand in ("NOVA.md", "CLAUDE.md", "README.md"):
        p = ws / cand
        if p.is_file():
            try:
                conv = p.read_text(encoding="utf-8",
                                   errors="replace")[:500]
            except OSError:
                conv = ""
            break
    return {"name": data.get("name", ws.name), "root": str(ws),
            "files": len(data.get("files", [])),
            "languages": data.get("langs", {}),
            "frameworks": data.get("frameworks", []),
            "entries": data.get("entries", []),
            "tests_dir": data.get("tests_dir", ""),
            "conventions_head": conv}


class UserProfile:
    """The user-side profile: stable preferences remembered across
    projects (language, tone, favorite providers, recurring goals)."""

    def __init__(self, path):
        self.path = Path(path)
        d = load_json(self.path, {"language": "fa", "prefs": {},
                                  "facts": [], "updated": 0})
        self.data = d if isinstance(d, dict) else {}

    def _save(self):
        self.data["updated"] = _now()
        save_json(self.path, self.data)

    def set_pref(self, key, value):
        self.data.setdefault("prefs", {})[str(key)[:60]] = str(value)[:300]
        self._save()

    def get_pref(self, key, default=None):
        return self.data.get("prefs", {}).get(str(key), default)

    def add_fact(self, text):
        text = (text or "").strip()
        if not text:
            return
        facts = self.data.setdefault("facts", [])
        if text[:240] not in [f["text"] for f in facts if isinstance(f, dict)]:
            facts.append({"text": text[:240], "ts": _now()})
            self.data["facts"] = facts[-50:]
            self._save()

    def brief(self, limit=600):
        prefs = ["%s=%s" % (k, v)
                 for k, v in sorted(self.data.get("prefs", {}).items())]
        facts = [f.get("text", "") for f in self.data.get("facts", [])
                 if isinstance(f, dict)][-8:]
        lines = ["user profile:"]
        if prefs:
            lines.append("  prefs: " + ", ".join(prefs))
        for f in facts:
            lines.append("  - " + f)
        out = "\n".join(lines)
        return out[:limit]


# =====================================================================
# 5. CONTEXT ENGINE - assemble the MOST PRECISE context, automatically
# =====================================================================
class ContextEngine:
    """Given a query, pick the few MOST relevant pieces from every
    intel store and compress them into ONE budgeted context block:

      1. TASK GRAPH   what is ready now / blocked / the progress
      2. PROJECT      the unified project profile (languages, entries)
      3. MEMORY       semantic recall over everything Nova experienced
      4. KB           the user's saved knowledge entries (keyword fit)
      5. DECISIONS    recorded decisions worth re-reading

    Blocks are added by priority until the character budget is spent;
    a block that does not earn its place (empty or irrelevant) is
    dropped. Deterministic, local, and cheap enough to run every turn."""

    PRIORITIES = ("tasks", "project", "memory", "kb", "decisions")

    def __init__(self, ws, intel=None, tasks=None, memory=None,
                 kb_path=None):
        self.ws = Path(ws)
        self.intel = intel or ProjectIntelligence(self.ws)
        self.tasks = tasks or TaskGraph(self.ws / ".nova" / "tasks.json")
        self.memory = memory or SemanticMemory(
            self.ws / ".nova" / "memory_vec.json")
        self.kb_path = Path(kb_path) if kb_path else (
            self.ws / ".nova" / "kb.json")

    def _tasks_block(self, query):
        if not self.tasks.tasks:
            return ""
        prog = self.tasks.progress()
        lines = ["progress: %d/%d done (%.0f%%)"
                 % (prog["done"], prog["total"], prog["pct"])]
        ready = self.tasks.ready()
        if ready:
            lines.append("ready now: " + "; ".join(
                "%s %s" % (tid, self.tasks.get(tid)["title"])
                for tid in ready[:5]))
        blocked = self.tasks.blocked()
        if blocked:
            lines.append("blocked: " + ", ".join(blocked[:6]))
        if prog["failed"]:
            lines.append("FAILED tasks: %d - revisit before new work"
                         % prog["failed"])
        return "\n".join(lines)

    def _project_block(self, query):
        try:
            self.intel.refresh_if_stale()
        except Exception:
            pass
        if not self.intel.data.get("files"):
            return ""  # an empty project contributes no context
        return self.intel.summary_text(limit=700)

    def _memory_block(self, query):
        hits = self.memory.recall(query, k=5, min_score=0.05)
        if not hits:
            return ""
        lines = []
        for h in hits:
            lines.append("- [%s] %s" % (h["kind"], h["text"][:220]))
        return "\n".join(lines)

    @staticmethod
    def _kb_entries_any(kb_path):
        """Read the knowledge base in EITHER shape: the real text blocks
        nova_search.kb_append writes (=== KNOWLEDGE: topic | saved: ... ===)
        or the legacy JSON list of {topic, text}. v7.14.1 fix: the text
        shape is what production writes - load_json() used to silently
        return [] for it and the whole KB context block was dead."""
        try:
            raw = Path(kb_path).read_text(encoding="utf-8",
                                          errors="replace")
        except OSError:
            return []
        if "=== KNOWLEDGE:" in raw:
            entries = []
            for m in re.finditer(r"=== KNOWLEDGE:\s*(.+?)\s*\|\s*saved:"
                                 r".*?===\n(.*?)\n?[ \t]*={2,}[ \t]*END"
                                 r"[ \t]*={2,}", raw, re.S):
                entries.append({"topic": m.group(1).strip(),
                                "text": m.group(2).strip()})
            if entries:
                return entries
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (TypeError, ValueError):
            return []

    def _kb_block(self, query):
        entries = self._kb_entries_any(self.kb_path)
        if not isinstance(entries, list) or not entries:
            return ""
        q_tokens = set(tokenize(query, drop_stop=False))
        scored = []
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            e_tokens = set(tokenize(
                "%s %s" % (e.get("topic", ""), e.get("text", "")),
                drop_stop=False))
            overlap = len(q_tokens & e_tokens)
            if overlap:
                scored.append((overlap, i, e))
        if not scored:
            return ""
        scored.sort(key=lambda t: (-t[0], t[1]))
        lines = []
        for overlap, _i, e in scored[:3]:
            lines.append("- %s: %s" % (e.get("topic", "?"),
                                       e.get("text", "")[:200]))
        return "\n".join(lines)

    def _decisions_block(self, query):
        hits = self.memory.recall(query, k=3, kind="decision",
                                  min_score=0.03)
        if not hits:
            # no query fit - fall back to the newest decisions regardless
            decs = [r for r in self.memory.records
                    if isinstance(r, dict) and r.get("kind") == "decision"]
            # v8.10.1 fix: same corrupt-ts law as recall/_cap - a wrong-typed
            # ts used to crash the sort (and with it the whole block)
            decs.sort(key=lambda r: -r.get("ts", 0)
                      if isinstance(r.get("ts", 0), (int, float)) else 0)
            hits = [{"text": r["text"]} for r in decs[:3]]
        if not hits:
            return ""
        return "\n".join("- " + h["text"][:200] for h in hits)

    def assemble(self, query, budget=5000):
        """Returns (text, sources) - the budgeted context block and the
        list of block names actually included."""
        gen = {
            "tasks": self._tasks_block,
            "project": self._project_block,
            "memory": self._memory_block,
            "kb": self._kb_block,
            "decisions": self._decisions_block,
        }
        parts, sources, used = [], [], 0
        for name in self.PRIORITIES:
            try:
                block = gen[name](query)
            except Exception:
                block = ""
            if not block:
                continue
            head = "== %s ==\n" % name.upper()
            remaining = budget - used
            if remaining <= len(head) + 40:
                break
            take = block[:remaining - len(head) - 1]
            if len(take) < len(block):
                take = take.rsplit("\n", 1)[0]  # cut at a line boundary
            if not take.strip():
                continue
            parts.append(head + take)
            sources.append(name)
            used += len(head) + len(take) + 2
        return ("\n\n".join(parts), sources) if parts else ("", [])


# =====================================================================
# 6. AGENT STATUS - the LIVE dashboard feed (.nova/agent_status.json)
# =====================================================================
class AgentStatus:
    """What is the agent doing RIGHT NOW, why, what comes next, and
    what has been tested - persisted so the web dashboard can show it
    live without polling Python objects."""

    def __init__(self, ws, now=_now):
        self.ws = Path(ws)
        self.path = self.ws / ".nova" / "agent_status.json"
        self.now = now

    def read(self):
        d = load_json(self.path, {})
        return d if isinstance(d, dict) else {}

    def set(self, phase=None, goal=None, task=None, why=None, next=None,
            tested=None, event=None):
        d = self.read()
        updates = {"phase": phase, "goal": goal, "task": task, "why": why,
                   "next": next, "tested": tested}
        for k, v in updates.items():
            if v is not None:
                d[k] = str(v)[:400]
        d["updated"] = self.now()
        events = d.get("events")
        if not isinstance(events, list):
            events = []
        if event:
            events.append({"t": self.now(), "msg": str(event)[:300]})
            events = events[-MAX_EVENTS:]
        d["events"] = events
        save_json(self.path, d)
        return d

    def clear(self):
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass


# =====================================================================
# 7. AGENT LOOP - Observe -> Decide -> Execute -> Test -> Fix -> Verify
# =====================================================================
PHASES = ("observe", "decide", "execute", "test", "fix", "verify",
          "done", "failed")


class AgentLoop:
    """An explicit, PERSISTED phase machine around one unit of work.

    Every phase transition is recorded (with the reason) into
    .nova/agent_runs/<run>.json and mirrored to AgentStatus, so the
    dashboard can answer: what is happening, why, what was tested.

    finish(ok=True) is HONEST BY CONSTRUCTION: CompletionDetector
    refuses a 'done' without verification evidence (lint/tests/run all
    fail-soft None or False) unless a reason was explicitly waived."""

    def __init__(self, ws, status=None, now=_now, emit=None):
        self.ws = Path(ws)
        self.now = now
        self.status = status or AgentStatus(ws, now=now)
        self.emit = emit  # callback(obj) for live UI events
        runs_dir = self.ws / ".nova" / "agent_runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # v8.0: the sequence number counts same-second files, so two
        # loops created in the same second (REPL + web are separate
        # processes) got identical run_ids and overwrote each other's
        # persisted runs. The pid suffix keeps ids collision-free.
        existing = len(list(runs_dir.glob("%s-*.json" % stamp)))
        # v8.0: the process-global counter ALSO makes ids unique for
        # same-process same-second loops (files are not written until
        # start(), so glob counting alone collides within one process).
        self.run_id = "%s-%03d-%d-%d" % (stamp, existing + 1,
                                         os.getpid() % 10000,
                                         next(_RUN_SEQ))
        self.run_path = runs_dir / (self.run_id + ".json")
        self.run = {"id": self.run_id, "goal": "", "phase": "observe",
                    "phases": [], "log": [], "started": self.now(),
                    "finished": 0, "result": None, "evidence": None,
                    "attempts": 0}

    def _persist(self):
        save_json(self.run_path, self.run)

    def _emit(self, obj):
        if self.emit:
            try:
                self.emit(obj)
            except Exception:
                pass

    def start(self, goal):
        self.run["goal"] = (goal or "")[:400]
        self.run["phases"].append({"phase": "observe", "why": "run start",
                                   "ts": self.now()})
        self.run["log"].append("[start] %s" % self.run["goal"])
        self.status.set(phase="observe", goal=self.run["goal"],
                        why="task accepted",
                        event="run %s started: %s"
                              % (self.run_id, self.run["goal"][:80]))
        self._persist()
        self._emit({"t": "agent", "run": self.run_id,
                    "phase": "observe", "goal": self.run["goal"]})
        return self.run

    def phase(self, name, why="", task=None, next=None, tested=None):
        if name not in PHASES:
            raise ValueError("unknown phase: %s" % name)
        self.run["phase"] = name
        self.run["phases"].append({"phase": name, "why": why[:300],
                                   "ts": self.now()})
        self.run["log"].append("[%s] %s" % (name, why))
        if len(self.run["log"]) > 200:
            self.run["log"] = self.run["log"][-200:]
        self.status.set(phase=name, why=why or None, task=task,
                        next=next, tested=tested,
                        event="%s: %s" % (name, why[:120]))
        self._persist()
        self._emit({"t": "agent", "run": self.run_id, "phase": name,
                    "why": why})
        return self.run

    def record(self, msg):
        self.run["log"].append(str(msg)[:400])
        if len(self.run["log"]) > 200:
            self.run["log"] = self.run["log"][-200:]
        self._persist()

    def attempt(self):
        self.run["attempts"] = int(self.run.get("attempts", 0)) + 1
        self._persist()

    def finish(self, ok, evidence=None, note=""):
        """Honest completion: ok=True needs real evidence or a waiver."""
        ev = CompletionDetector.normalize(evidence)
        allowed, reason = CompletionDetector.evaluate(ev)
        if ok and not allowed:
            ok = False
            note = (note + " " if note else "") + \
                "success claim rejected: %s" % reason
        self.run["result"] = "done" if ok else "failed"
        self.run["evidence"] = ev
        self.run["finished"] = self.now()
        if note:
            self.run["log"].append("[note] " + note[:400])
        self.run["phase"] = self.run["result"]
        self.run["phases"].append({"phase": self.run["result"],
                                   "why": note[:300] or reason or "",
                                   "ts": self.now()})
        self.status.set(phase=self.run["result"],
                        why=note[:300] or None,
                        event="run %s -> %s" % (self.run_id,
                                                self.run["result"]))
        self._persist()
        self._emit({"t": "agent", "run": self.run_id,
                    "phase": self.run["result"], "evidence": ev})
        return self.run

    @staticmethod
    def latest_run(ws):
        runs = sorted((Path(ws) / ".nova" / "agent_runs").glob("*.json"))
        return runs[-1] if runs else None


class CompletionDetector:
    """The anti-false-success guard: a run may only claim success when
    at least ONE concrete verification passed (lint / tests / run), or
    when the operator waived verification with a stated reason."""

    FIELDS = ("lint_ok", "tests_ok", "run_ok")

    @staticmethod
    def normalize(evidence):
        ev = dict(evidence or {})
        out = {}
        for f in CompletionDetector.FIELDS:
            v = ev.get(f)
            # v8.0 honesty fix: bool(v) mapped ANY non-empty string to
            # True - evidence like {"lint_ok": "failed"} or
            # {"run_ok": "no"} was accepted as a PASSING verification
            # and defeated the anti-false-success gate. Only strict
            # booleans (and real numbers) count; everything else is n/a.
            if isinstance(v, bool):
                out[f] = v
            elif isinstance(v, (int, float)):
                out[f] = bool(v)
            else:
                out[f] = None
        # v7.14.1 fix: a non-string waived (bool/number from JSON
        # evidence) used to raise AttributeError through finish()
        w = ev.get("waived")
        if isinstance(w, str):
            out["waived"] = w.strip()
        elif w:
            out["waived"] = "yes"
        else:
            out["waived"] = ""
        return out

    @staticmethod
    def evaluate(ev):
        ev = CompletionDetector.normalize(ev)
        if any(ev[f] is True for f in CompletionDetector.FIELDS):
            return True, "verification evidence present"
        if ev["waived"]:
            return True, "waived: %s" % ev["waived"]
        return False, "no verification evidence (lint/tests/run all " \
                      "unset or failed)"

    @staticmethod
    def summarize(ev):
        ev = CompletionDetector.normalize(ev)
        bits = ["%s=%s" % (f, "pass" if ev[f] else
                           ("fail" if ev[f] is False else "n/a"))
                for f in CompletionDetector.FIELDS]
        if ev["waived"]:
            bits.append("waived(%s)" % ev["waived"][:60])
        return ", ".join(bits)


# =====================================================================
# 8. RECOVERY MANAGER - classify the failure, choose the next move
# =====================================================================
class RecoveryManager:
    """Smart recovery after errors: classify the failure from its text,
    then pick a bounded, escalating strategy instead of blind retries.

    plan() is DETERMINISTIC (no random backoff) so tests can pin the
    whole ladder; delays follow a doubling sequence capped at 30s."""

    PATTERNS = (
        ("syntax", ("syntaxerror", "indentationerror", "invalid syntax",
                    "unexpected token", "expected ';'", "taberror")),
        ("import", ("modulenotfounderror", "importerror",
                    "no module named", "cannot find module",
                    "unresolved import")),
        ("timeout", ("timeoutexpired", "timed out", "timeout",
                     "deadline exceeded")),
        ("permission", ("permissionerror", "eacces", "access denied",
                        "permission denied")),
        ("net", ("connectionerror", "getaddrinfo failed",
                 "connection refused", "http error", "ssl:", "eof occurred")),
        ("test", ("assertionerror", "assert ", "failed", "1 failed",
                  "test failed", "expect(")),
        ("runtime", ("traceback (most recent call last)", "runtimeerror",
                     "typeerror", "nameerror", "valueerror",
                     "attributeerror", "keyerror", "indexerror",
                     "zerodivisionerror", "unhandled", "segmentation fault")),
    )

    LADDER = {
        # attempt (1-based) -> action
        "syntax": ((1, "fix_targeted"), (2, "fix_targeted"),
                   (3, "split"), (4, "stop")),
        "import": ((1, "fix_targeted"), (2, "retry"), (3, "split"),
                   (4, "stop")),
        "timeout": ((1, "retry"), (2, "split"), (3, "stop")),
        "permission": ((1, "fix_targeted"), (2, "stop")),
        "net": ((1, "retry"), (2, "retry"), (3, "stop")),
        "test": ((1, "fix_targeted"), (2, "fix_targeted"), (3, "rollback"),
                 (4, "stop")),
        "runtime": ((1, "fix_targeted"), (2, "split"), (3, "rollback"),
                    (4, "stop")),
        "unknown": ((1, "retry"), (2, "fix_targeted"), (3, "stop")),
    }

    NOTES = {
        "retry": "transient or flaky - try the same step again",
        "fix_targeted": "read the failing file around the reported line "
                        "and patch exactly that spot",
        "split": "the step is too big - break it into smaller pieces",
        "rollback": "the last change made things worse - restore the "
                    "previous snapshot before continuing",
        "stop": "attempts exhausted - report honestly and ask for "
                "direction instead of guessing",
    }

    @classmethod
    def classify(cls, error_text):
        t = norm_text(error_text or "")
        if not t:
            return "unknown"
        for kind, needles in cls.PATTERNS:
            for n in needles:
                if n in t:
                    return kind
        return "unknown"

    @classmethod
    def plan(cls, kind, attempt):
        ladder = cls.LADDER.get(kind, cls.LADDER["unknown"])
        action = "stop"
        for at, act in ladder:
            if attempt <= at:
                action = act
                break
        delay = 0 if action in ("stop", "fix_targeted", "split",
                                "rollback") else min(2 ** max(1, attempt), 30)
        return {"kind": kind, "attempt": attempt, "action": action,
                "delay": delay, "note": cls.NOTES[action]}

    @classmethod
    def handle(cls, error_text, attempt):
        return cls.plan(cls.classify(error_text), attempt)


# =====================================================================
# 9. IMPACT ANALYZER - what will this file change break?
# =====================================================================
class ImpactAnalyzer:
    """BEFORE a file changes: who imports it (transitively), which
    symbols it defines, and which test files exercise it. The agent
    prints one honest warning line instead of discovering the blast
    radius after the user clicks Run."""

    def __init__(self, ws, intel=None):
        self.ws = Path(ws)
        self.intel = intel or ProjectIntelligence(self.ws)
        data, _ = self.intel.refresh_if_stale()
        self.data = data

    def _reverse_edges(self):
        rev = {}
        for importer, imported in (self.data.get("imports") or {}).items():
            for target in imported:
                rev.setdefault(target, [])
                if importer not in rev[target]:
                    rev[target].append(importer)
        return rev

    def _test_files(self):
        return [rel for rel in self.data.get("files", [])
                if Path(rel).name.startswith(("test_", "_test.")) or
                "/test_" in rel or rel.startswith("tests/") and
                Path(rel).name.startswith("test")]

    def analyze(self, paths):
        """paths: rel paths (or names) about to change. Returns a dict:
        affected (transitive importers), symbols, tests, risk."""
        rev = self._reverse_edges()
        known = set(self.data.get("files", []))
        wanted = set()
        for p in paths or []:
            p = str(p).replace("\\", "/")
            if p in known or (self.ws / p).is_file():
                wanted.add(p)
            else:
                continue  # not part of this project - nothing to weigh
            stem = Path(p).stem
            for rel in self.data.get("files", []):
                if rel == p:
                    continue
                if Path(rel).stem == stem and rel not in wanted:
                    wanted.add(rel)  # same stem elsewhere (a/x.py vs b/x.py)
        affected, frontier = set(), list(wanted)
        while frontier and len(affected) < 100:
            cur = frontier.pop()
            for nxt in rev.get(cur, []):
                if nxt not in affected and nxt not in wanted:
                    affected.add(nxt)
                    frontier.append(nxt)
        symbols = {}
        for rel in wanted:
            syms = (self.data.get("symbols") or {}).get(rel)
            if syms:
                symbols[rel] = [s for _k, s, _ln in syms]
        stem_tokens = {Path(p).stem for p in wanted}
        tests = []
        for t in self._test_files():
            try:
                text = (self.ws / t).read_text(
                    encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                continue
            for stem in stem_tokens:
                if stem in text:
                    tests.append(t)
                    break
        risk = "high" if (affected or tests) else (
            "low" if wanted else "none")
        return {"targets": sorted(wanted), "affected": sorted(affected),
                "symbols": symbols, "tests": sorted(set(tests)),
                "risk": risk}

    def text_report(self, paths):
        rep = self.analyze(paths)
        if not rep["targets"]:
            return "impact: nothing to analyze (no matching files)"
        lines = ["impact analysis - risk: %s" % rep["risk"]]
        lines.append("  changing: " + ", ".join(rep["targets"][:6]))
        if rep["affected"]:
            lines.append("  %d file(s) import these: %s" % (
                len(rep["affected"]),
                ", ".join(rep["affected"][:8])))
        else:
            lines.append("  no workspace file imports them directly")
        if rep["symbols"]:
            for rel, syms in list(rep["symbols"].items())[:3]:
                lines.append("  symbols in %s: %s" % (
                    rel, ", ".join(syms[:6])))
        if rep["tests"]:
            lines.append("  test files exercising them: " +
                         ", ".join(rep["tests"][:5]))
        else:
            lines.append("  (no test file references them - /gentests?)")
        return "\n".join(lines)


# =====================================================================
# 10. REGRESSION DETECTOR - did the change break something?
# =====================================================================
class RegressionDetector:
    """AFTER a change: compare the test suite against a stored baseline.
    baseline() stores the passing state; check() re-runs and honestly
    reports new_fail / fixed / stable / no-tests. The runner is
    injected (nova_feedback.run_tests) so this module stays pure."""

    def __init__(self, ws, runner, path=None):
        self.ws = Path(ws)
        self.runner = runner  # callable() -> {"ok": bool, "cmd": str|None, ...}
        self.path = Path(path) if path else (
            self.ws / ".nova" / "regression.json")

    def baseline(self):
        try:
            res = self.runner() or {}
            res.pop("_runner_error", None)
        except Exception as e:
            res = {"ok": None, "cmd": None, "report": "(runner failed: %s)"
                   % e}
        return self._store(res)

    def _store(self, res):
        """Persist a runner result as the new baseline WITHOUT re-running
        anything (v8.0: check() used to call baseline() on green verdicts
        and so ran the whole suite a second time)."""
        res = dict(res or {})
        res.pop("_runner_error", None)
        data = {"ts": _now(), "ok": res.get("ok"),
                "cmd": res.get("cmd"),
                "report_head": (res.get("report") or "")[:400]}
        save_json(self.path, data)
        return data

    def check(self):
        base = load_json(self.path, {})
        if not base:
            return {"verdict": "no-baseline",
                    "note": "run /regress baseline first"}
        try:
            res = self.runner() or {}
        except Exception as e:
            return {"verdict": "error", "before": base.get("ok"),
                    "after": None,
                    "note": "the test runner itself crashed",
                    "report_head": "(runner failed: %s)" % e}
        before, after = base.get("ok"), res.get("ok")
        if after is None and not res.get("cmd"):
            return {"verdict": "no-tests", "before": before, "after": after,
                    "note": "no runnable test command was detected"}
        if before is False and after is True:
            verdict, note = "fixed", "tests are green again"
        elif before is True and after is False:
            verdict, note = "new-fail", "the suite PASSED at baseline and " \
                                        "FAILS now - regression!"
        elif after is False:
            verdict, note = "still-failing", "suite was failing and still " \
                                             "fails (same or other tests)"
        elif after is True:
            verdict, note = "stable", "suite still green"
        else:
            verdict, note = "unknown", "runner produced no verdict"
        out = {"verdict": verdict, "before": before, "after": after,
               "cmd": res.get("cmd"), "note": note,
               "report_head": (res.get("report") or "")[:400]}
        if verdict in ("fixed", "stable"):
            self._store(res)  # the new green becomes the reference
                               # (v8.0: no second suite run)
        return out


# =====================================================================
# 11. TEST GENERATOR - runnable pytest skeletons from the code itself
# =====================================================================
class TestGenerator:
    """AST-driven skeleton generation for CHANGED/NEW files:

      Python -> tests/test_gen_<stem>.py with, per public function:
        - an existence pin (catches accidental renames)
        - a smoke test that pytest.SKIPs until a human fills it
      JS     -> tests/gen_<stem>.test.js with node:test todo entries

    Never overwrites an existing generated file - honest regeneration
    means deleting the old one yourself."""

    def __init__(self, ws, intel=None):
        self.ws = Path(ws)
        self.intel = intel or ProjectIntelligence(self.ws)
        data, _ = self.intel.refresh_if_stale()
        self.data = data

    def gen_for_file(self, rel):
        rel = str(rel).replace("\\", "/")
        p = self.ws / rel
        if not p.is_file():
            return {"ok": False, "error": "file not found: %s" % rel}
        ext = p.suffix.lower()
        if ext == ".py":
            return self._gen_py(rel, p)
        if ext in (".js", ".mjs", ".cjs", ".ts"):
            return self._gen_js(rel, p)
        return {"ok": False,
                "error": "skeletons support .py and .js/.ts (got %s)" % ext}

    def _out_path(self, rel):
        stem = Path(rel).stem.replace("-", "_")
        return self.ws / "tests" / ("test_gen_%s.py" % stem)

    def _gen_py(self, rel, p):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8",
                                         errors="replace")
                             [:MAX_SYMBOL_FILE])
        except SyntaxError as e:
            return {"ok": False, "error": "cannot parse %s: %s" % (rel, e)}
        funcs, classes = [], []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    funcs.append(node.name)
            elif isinstance(node, ast.ClassDef):
                methods = [s.name for s in node.body
                           if isinstance(s, (ast.FunctionDef,
                                             ast.AsyncFunctionDef))
                           and not s.name.startswith("_")]
                classes.append((node.name, methods))
        if not funcs and not classes:
            return {"ok": False,
                    "error": "no public functions/classes in %s" % rel}
        out = self._out_path(rel)
        if out.exists():
            return {"ok": False, "error": "already exists: %s" %
                    out.name, "path": str(out)}
        dotted = rel[:-3].replace("/", ".").replace("-", "_")
        lines = [
            '"""Generated by Nova intel test-gen - SKELETONS.',
            "Source under test: %s" % rel,
            'Fill the real assertions, then delete the skips."""',
            "import importlib",
            "import pytest",
            "",
            "MOD = importlib.import_module(%r)" % dotted,
            "",
        ]
        count = 0
        for fn in funcs:
            lines += [
                "",
                "def test_%s_exists():" % fn,
                "    assert hasattr(MOD, %r)" % fn,
                "",
                "",
                "@pytest.mark.skip('fill real assertions for %s')" % fn,
                "def test_%s_smoke():" % fn,
                "    ...",
                "",
            ]
            count += 2
        for cls, methods in classes:
            lines += [
                "",
                "def test_%s_exists():" % cls,
                "    assert hasattr(MOD, %r)" % cls,
                "",
            ]
            count += 1
            for m in methods[:8]:
                lines += [
                    "",
                    "@pytest.mark.skip('fill real assertions for %s.%s')"
                    % (cls, m),
                    "def test_%s_%s_smoke():" % (cls, m),
                    "    ...",
                    "",
                ]
                count += 1
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out, "\n".join(lines) + "\n")
        return {"ok": True, "path": str(out), "cases": count,
                "language": "python"}

    def _gen_js(self, rel, p):
        syms = _js_symbols(p)
        names = [s for _k, s, _l in syms if "(" not in s]
        if not names:
            return {"ok": False,
                    "error": "no exported/class symbols found in %s" % rel}
        stem = Path(rel).stem.replace("-", "_")
        out = self.ws / "tests" / ("gen_%s.test.js" % stem)
        if out.exists():
            return {"ok": False, "error": "already exists: %s" %
                    out.name, "path": str(out)}
        rel_js = rel.replace("\\", "/")
        lines = [
            "// Generated by Nova intel test-gen - TODO skeletons",
            "// Source under test: %s" % rel_js,
            'import test from "node:test";',
            "",
        ]
        for n in names[:12]:
            lines.append("test.todo('%s - fill real assertions');" % n)
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out, "\n".join(lines) + "\n")
        return {"ok": True, "path": str(out), "cases": len(names[:12]),
                "language": "javascript"}


# =====================================================================
# 12. CRITIC - the staged self-review of one apply batch
# =====================================================================
class Critic:
    """STAGED self-review after an apply batch. Four stages, each with
    a verdict, then one score + one overall verdict:

      protocol  - the batch left no unnamed leftovers (files listed)
      syntax    - the internal linter found nothing
      impact    - high-risk change got tests/review attention
      tests     - the suite (when runnable) still passes

    Verdicts: ship (>=85, nothing broken) / fix (something to patch)
    / rollback (syntax AND tests broken - undo is kinder)."""

    @classmethod
    def review(cls, evidence):
        ev = evidence or {}
        stages = []
        files = ev.get("files") or []
        stages.append({"stage": "protocol",
                       "ok": bool(files),
                       "note": "%d file(s) in batch" % len(files)
                               if files else "no files recorded"})
        syntax = ev.get("syntax") or []
        stages.append({"stage": "syntax",
                       "ok": not syntax,
                       "note": "clean" if not syntax else
                       "%d syntax problem(s)" % len(syntax)})
        impact = ev.get("impact") or {}
        impact_ok = impact.get("risk", "none") != "high" or \
            bool(impact.get("tests"))
        stages.append({"stage": "impact",
                       "ok": impact_ok,
                       "note": "risk %s, %d related test file(s)"
                               % (impact.get("risk", "none"),
                                  len(impact.get("tests") or []))})
        tests = ev.get("tests")
        if tests is None:
            stages.append({"stage": "tests", "ok": None,
                           "note": "not run (autotest off or no runner)"})
            tests_pen, tests_ok = 20, None
        elif tests.get("cmd") is None:
            stages.append({"stage": "tests", "ok": None,
                           "note": "no test command detected"})
            tests_pen, tests_ok = 5, None
        elif tests.get("ok"):
            stages.append({"stage": "tests", "ok": True,
                           "note": "suite passed"})
            tests_pen, tests_ok = 0, True
        else:
            stages.append({"stage": "tests", "ok": False,
                           "note": (tests.get("report") or
                                    "suite failed")[:200]})
            tests_pen, tests_ok = 30, False
        score = 100
        score -= min(45, 15 * len(syntax))
        score -= min(20, 10 * len(ev.get("lint") or []))
        score -= tests_pen
        if impact.get("risk") == "high" and not impact_ok:
            score -= 10
        score = max(0, score)
        if syntax and tests_ok is False:
            verdict = "rollback"
        elif syntax or tests_ok is False or score < 70:
            verdict = "fix"
        elif tests_ok is None and (syntax or ev.get("lint")):
            verdict = "fix"
        elif score >= 85:
            verdict = "ship"
        else:
            verdict = "fix"
        return {"stages": stages, "score": score, "verdict": verdict}

    @classmethod
    def text_report(cls, evidence):
        rep = cls.review(evidence)
        lines = ["critic: score %d/100 -> %s" % (rep["score"],
                                                 rep["verdict"].upper())]
        for s in rep["stages"]:
            mark = {True: "[ok]", False: "[!!]", None: "[--]"}[s["ok"]]
            lines.append("  %s %-9s %s" % (mark, s["stage"], s["note"]))
        if rep["verdict"] == "rollback":
            lines.append("  (smart rollback suggested: /undo restores "
                         "the last snapshot)")
        return "\n".join(lines)


# =====================================================================
# 13. SMART ROLLBACK - the decision + the locator (restore = /undo)
# =====================================================================
class SmartRollback:
    """Decides WHEN a rollback is the kindest move and WHERE the last
    snapshot lives. The actual restore stays in nova_snapshots (/undo)
    on purpose: one writer per mechanism, no double-headed undo."""

    @classmethod
    def should(cls, critic_verdict, regression_verdict=None):
        if critic_verdict == "rollback":
            return True, "critic verdict: rollback (syntax and tests " \
                         "both broken)"
        if regression_verdict in ("new-fail",):
            return True, "regression: the suite was green and now fails"
        return False, ""

    @staticmethod
    def newest_snapshot(ws):
        """The newest auto-snapshot dir under .nova/snapshots/auto, or
        the newest overall - whatever exists."""
        root = Path(ws) / ".nova" / "snapshots"
        if not root.is_dir():
            return None
        for sub in ("auto", ""):
            base = root / sub if sub else root
            if base.is_dir():
                dirs = sorted([d for d in base.iterdir() if d.is_dir()])
                if dirs:
                    return dirs[-1]
        return None

    @classmethod
    def plan(cls, ws, critic_verdict, regression_verdict=None):
        do, why = cls.should(critic_verdict, regression_verdict)
        snap = cls.newest_snapshot(ws)
        return {"rollback": do, "why": why,
                "snapshot": str(snap) if snap else None,
                "note": "restore with /undo (or copy the snapshot back)"
                        if snap and do else ""}

