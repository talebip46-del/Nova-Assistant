#!/usr/bin/env python3
# =====================================================================
#  Nova Code - REAL SEMANTIC RAG for the codebase (v7.5.0)
#
#  Real embeddings (Ollama /api/embeddings), NOT hashing vectors: the
#  model's meaning space is used for similarity, so "the login check"
#  finds auth code even with zero shared words. When no embedding
#  backend answers, a lexical TF-IDF fallback keeps /rag usable
#  (never the old hash trick - it could not generalize at all).
#
#  Design guards:
#  - chunked (<= ~900 chars), persisted to .nova/rag_index.json with a
#    per-chunk content hash so unchanged chunks are never re-embedded;
#  - respects the workspace ignore rules (novaignore) + binary dirs;
#  - bounded (files, size, dims) for 4 GB machines;
#  - build runs in a DAEMON thread, every search fails soft to [].
# =====================================================================
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

INDEX_FILE = "rag_index.json"
MAX_FILES = 400          # workspace files indexed per build
MAX_FILE_BYTES = 220_000
MAX_CHUNKS = 1500
CHUNK_CHARS = 900
CHUNK_OVERLAP_LINES = 4
DIM = 768                # nomic-embed-text family; any dim is accepted
TIMEOUT = 20

TEXT_EXT = (".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt",
            ".sh", ".bat", ".yml", ".yaml", ".toml", ".ini", ".cfg",
            ".sql", ".nova")
SKIP_DIRS = (".git", ".nova", ".nova_backups", "node_modules", "__pycache__",
             "fonts", "assets/images", "venv", ".venv", "dist", "build")

_word_re = re.compile(r"[a-zA-Z_\u0600-\u06FF][a-zA-Z0-9_\u0600-\u06FF]+")

# module state
_lock = threading.Lock()
_state = {"building": False, "last_error": "", "last_built": 0.0}


# ----------------------------------------------------------------- http
def ollama_base():
    base = os.environ.get("NOVA_OLLAMA_URL", "") or \
        os.environ.get("OLLAMA_HOST", "")
    if base and not base.startswith("http"):
        base = "http://" + base
    return (base or "http://127.0.0.1:11434").rstrip("/")


def _embed_one(text, model, timeout=TIMEOUT):
    """One real embedding from Ollama. Returns [float] or None."""
    try:
        payload = json.dumps({"model": model, "prompt": text[:2000]}).encode()
        req = urllib.request.Request(
            ollama_base() + "/api/embeddings", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        vec = data.get("embedding")
        if isinstance(vec, list) and vec:
            return [float(x) for x in vec]
    except Exception:
        return None
    return None


def embed_model(ws):
    """Which embedding model to use: NOVA_EMBED_MODEL, then a known tiny
    embedder if installed, else the active local chat model (it still
    embeds - just slower). None when nothing is available (offline)."""
    forced = os.environ.get("NOVA_EMBED_MODEL", "").strip()
    if forced:
        return forced
    try:
        import nova
        names = set(nova.list_installed_models() or [])
    except Exception:
        names = set()
    for cand in ("nomic-embed-text", "all-minilm", "mxbai-embed-large"):
        if cand in names:
            return cand
    try:
        import nova
        cfg_name = ""
        if nova.providers is not None:
            cfg, mdl = nova.providers.resolve_route("coding")
            if cfg is not None and (cfg.get("kind") == "ollama"):
                cfg_name = mdl or ""
        return cfg_name or (nova.list_installed_models() or [""])[0]
    except Exception:
        return None


# ------------------------------------------------------------- chunking
def _is_binary_head(head):
    return b"\x00" in head[:2048]


def workspace_files(ws, ignore=None):
    """Bounded list of text files worth indexing."""
    out = []
    ws = Path(ws)
    try:
        for p in sorted(ws.rglob("*")):
            if len(out) >= MAX_FILES:
                break
            # v8.0: symlinks are never indexed - on Python <= 3.12 rglob
            # descends into symlinked dirs with no cycle protection, so a
            # symlink used to pull OUTSIDE files into the (shareable)
            # rag_index.json, eat the budget with duplicates, or hang on
            # a symlink cycle.
            if p.is_symlink():
                continue
            if not p.is_file():
                continue
            rel = p.relative_to(ws).as_posix()
            # v7.14.1 fix: the old top-level-only check (rel == d or
            # rel.startswith(d + "/")) let NESTED dirs through - e.g.
            # web/node_modules/pkg/x.js - so dependency trees were walked
            # into the 400-file budget. Match ANY path part instead.
            # v8.0: multi-part entries like "assets/images" match as a
            # path PREFIX too (parts never contain "/", so that entry
            # was dead before).
            parts = rel.split("/")
            if any(part in SKIP_DIRS for part in parts):
                continue
            if any(rel == d2 or rel.startswith(d2 + "/")
                   for d2 in SKIP_DIRS if "/" in d2):
                continue
            if p.suffix.lower() not in TEXT_EXT and p.name != "NOVA.md":
                continue
            if ignore is not None:
                try:
                    if ignore.matches(rel):
                        continue
                except Exception:
                    pass
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                with p.open("rb") as fh:
                    head = fh.read(2048)
                if _is_binary_head(head):
                    continue
                out.append((rel, p))
            except OSError:
                continue
    except Exception:
        pass
    return out


def chunk_file(rel, text):
    """[(line_no, chunk_text)] - line-aware windows with small overlap."""
    lines = text.splitlines()
    if not lines:
        return []
    chunks, buf, start = [], [], 1
    size = 0
    for i, ln in enumerate(lines, 1):
        buf.append(ln)
        size += len(ln) + 1
        if size >= CHUNK_CHARS or i == len(lines):
            chunks.append((start, "\n".join(buf).strip()))
            buf = buf[-CHUNK_OVERLAP_LINES:]
            start = max(1, i - len(buf) + 1)
            size = sum(len(x) + 1 for x in buf)
    return [(n, c) for n, c in chunks if c][:80]


# ------------------------------------------------------------ tf-idf (fallback)
def _vec_lex(text, dim=384):
    """Deterministic TF-IDF-style sparse weights over a FIXED index
    (the token's own hash slot) - used ONLY as the fallback when no
    embedding model answers. Cosine on normalized weights."""
    v = [0.0] * dim
    toks = _word_re.findall(str(text).lower())
    if not toks:
        return v
    for t in toks:
        h = int(hashlib.sha1(t.encode("utf-8", "ignore")).hexdigest()[:8], 16)
        v[h % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# --------------------------------------------------------------- search
def _cosine(a, b):
    try:
        num = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return num / (na * nb)
    except Exception:
        return 0.0


def index_path(ws):
    return Path(ws) / ".nova" / INDEX_FILE


def load_index(ws):
    try:
        p = index_path(ws)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("chunks") else None
    except Exception:
        return None


def search(ws, query, k=5):
    """Top-k [(file, line, score, snippet)] - semantic when vectors exist,
    lexical otherwise. Never raises; [] on any problem."""
    try:
        q = str(query or "").strip()
        if not q:
            return []
        idx = load_index(ws)
        if not idx:
            return []
        mode = idx.get("mode", "lexical")
        if mode == "semantic":
            qv = _embed_one(q, idx.get("model", ""), timeout=10)
            if qv is None:
                mode = "lexical"   # server went away mid-life
            else:
                scored = []
                for ch in idx.get("chunks", []):
                    v = ch.get("vec")
                    if isinstance(v, list) and v:
                        scored.append((_cosine(qv, v), ch))
                scored.sort(key=lambda t: -t[0])
                return [(c["file"], c["line"], round(s, 4), c["text"][:240])
                        for s, c in scored[:max(1, int(k))]]
        # lexical fallback: cosine over tf-idf weights (also the path for
        # a semantic index whose embedder went away mid-life)
        qv = _vec_lex(q)
        scored = []
        for ch in idx.get("chunks", []):
            scored.append((_cosine(qv, _vec_lex(ch["text"])), ch))
        scored.sort(key=lambda t: -t[0])
        return [(c["file"], c["line"], round(s, 4), c["text"][:240])
                for s, c in scored[:max(1, int(k))]]
    except Exception:
        return []


def relevant_code_text(ws, query, k=2, cap_chars=700):
    """The small context block injected into coding turns ('' = nothing)."""
    try:
        hits = search(ws, query, k=k)
        if not hits:
            return ""
        rows = []
        for f, ln, s, snip in hits:
            if s < 0.05:
                continue
            rows.append(f"- {f}:{ln} (match {s:.2f})\n  {snip}")
        if not rows:
            return ""
        return ("## Relevant code found by semantic search (read-only hints)\n"
                + "\n".join(rows))[:cap_chars]
    except Exception:
        return ""


# ---------------------------------------------------------------- build
def build(ws, ignore=None, progress=None):
    """Build/refresh the index. Real embeddings when a local model can
    embed; otherwise the lexical mode (still better than nothing, never
    pretending). Returns (n_chunks, mode, error)."""
    with _lock:
        if _state["building"]:
            return (0, "busy", "build already running")
        _state["building"] = True
    try:
        return _build_inner(ws, ignore, progress)
    finally:
        with _lock:
            _state["building"] = False
            _state["last_built"] = time.time()


def _build_inner(ws, ignore, progress):
    import nova   # late import: circular at module load time
    files = workspace_files(ws, ignore)
    if not files:
        return (0, "", "workspace has no indexable text files")
    model = embed_model(ws)
    chunks, error = [], ""
    old = load_index(ws) or {}
    old_by_key = {}
    for c in old.get("chunks", []):
        old_by_key[(c.get("file"), c.get("line"), c.get("hash"))] = c.get("vec")
    mode = "lexical"
    if model:
        # probe once: a model that cannot embed -> lexical mode for all
        probe = _embed_one("nova embedding probe", model, timeout=8)
        if probe is not None:
            mode = "semantic"
        else:
            error = "embedder did not answer - lexical mode"
    else:
        error = "no local model for embeddings - lexical mode"
    dim = len(probe) if mode == "semantic" else 384
    for rel, p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ln, ch in chunk_file(rel, text):
            if len(chunks) >= MAX_CHUNKS:
                break
            h = hashlib.sha1(ch.encode("utf-8", "ignore")).hexdigest()[:16]
            vec = old_by_key.get((rel, ln, h))
            if vec is None and mode == "semantic":
                vec = _embed_one(ch, model)
            chunks.append({"file": rel, "line": ln, "hash": h,
                           "text": ch[:400], "vec": vec})
        if len(chunks) >= MAX_CHUNKS:
            break
        if progress:
            try:
                progress(rel)
            except Exception:
                pass
    try:
        p = index_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        # v7.14.1: atomic write (the build runs in a daemon thread - a
        # crash mid-write used to publish a truncated index which then
        # silently disabled RAG until the next build)
        payload = json.dumps({"mode": mode, "model": model or "",
                              "dim": dim, "built": time.time(),
                              "chunks": chunks},
                             ensure_ascii=False)
        try:
            import nova_atomic
            err = nova_atomic.write_text_atomic(p, payload,
                                                encoding="utf-8")
            if err:
                p.write_text(payload, encoding="utf-8")
        except ImportError:
            p.write_text(payload, encoding="utf-8")
        _state["last_error"] = error
        return (len(chunks), mode, error)
    except OSError as e:
        return (0, "", str(e))


def build_async(ws, ignore=None):
    """Background rebuild (daemon) - fire and forget, for post-apply."""
    def run():
        try:
            build(ws, ignore)
        except Exception:
            pass
    try:
        t = threading.Thread(target=run, daemon=True, name="nova-rag-build")
        t.start()
        return True
    except Exception:
        return False


def status(ws):
    """Small dict for /api/info + /rag status."""
    idx = load_index(ws)
    return {"built": bool(idx), "mode": (idx or {}).get("mode", ""),
            "chunks": len((idx or {}).get("chunks", []) if idx else []),
            "building": _state["building"], "error": _state["last_error"]}
