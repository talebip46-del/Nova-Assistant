#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - Nova Knowledge (v6.0)
#
#  A local, private document brain (the AnythingLLM / PrivateGPT slot
#  in the Nova toolbox) - WITHOUT embeddings, WITHOUT a vector DB,
#  WITHOUT any dependency:
#
#    ingest   .txt .md .py .js .ts .css .html .json .csv .log .nova*
#            -> chunked (overlap) into .nova/knowledge/chunks.jsonl
#    search   TF-IDF cosine over chunks - pure Python, Persian-aware
#            tokenizer (\\w+ + Arabic block), small stopword list
#    context  top hits packed into one prompt-ready block with source
#            tags, for injection into Flow prompt nodes or /load
#
#  Crash-safe writes (tmp + replace), hard caps everywhere, and a
#  rebuild path that tolerates a torn last line (crash mid-append).
# =====================================================================
import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:
    natom = None

from nova_modules import ModuleError

MAX_FILE = 300_000              # bytes per document
MAX_FILES = 80                  # per ingest run
MAX_CHUNKS = 6000
CHUNK = 700                     # chars
OVERLAP = 100
ALLOWED = {".txt", ".md", ".py", ".js", ".ts", ".css", ".html", ".json",
           ".csv", ".log", ".yml", ".yaml", ".xml", ".sh", ".bat",
           ".nova", ".novaignore"}

_TOKEN_RE = re.compile(r"[0-9A-Za-z_\u00C0-\u024F\u0400-\u04FF\u0600-\u06FF]+",
                       re.UNICODE)
# v6.5 fix: the closing paren used to sit INSIDE the string
# ("... های).split()"), so set() received one giant string and _STOP became
# a set of 41 individual CHARACTERS - the stopword filter was a no-op and
# every stopword stayed in the TF/DF vectors, drowning the real signal.
_STOP = set(("the a an and or of to in on for with is are was were be been "
             "it its this that these those as at by from if then else not no "
             "yes do does did done can could should would will just very "
             "و به از که در این با را است برای روی یک تا هم می شدن شد بود "
             "کرد کنید باشد اما یا آخر های").split())

_PATH_SAFE = re.compile(r"^[\w./\\ \-\u0600-\u06FF]+$")


def _paths(ws):
    d = Path(ws) / ".nova" / "knowledge"
    return d, d / "docs.json", d / "chunks.jsonl"


def _tokenize(text):
    return [t.lower() for t in _TOKEN_RE.findall(text or "")
            if len(t) > 1 and t.lower() not in _STOP]


def _chunks_of(text):
    """Overlap chunking on paragraph boundaries when possible."""
    text = (text or "").strip()
    if len(text) <= CHUNK:
        return [text] if text else []
    out = []
    start = 0
    n = len(text)
    while start < n and len(out) < MAX_CHUNKS:
        end = min(n, start + CHUNK)
        if end < n:
            brk = text.rfind("\n", start + CHUNK // 2, end)
            if brk > start:
                end = brk + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        start = max(end - OVERLAP, start + 1)
    return out


def _safe_join(ws, raw):
    """Resolve a user path INSIDE the workspace, or None. Guards the
    absolute / traversal cases; symlinks resolve too (containment)."""
    if not raw or not _PATH_SAFE.match(str(raw)):
        return None
    wsr = Path(ws).resolve()
    p = (wsr / raw).resolve()
    try:
        p.relative_to(wsr)
    except ValueError:
        return None
    return p


# --------------------------------------------------------------- ingest
# v6.2.1 fix: ingest is a read-modify-write over docs.json + chunks.jsonl
# and runs from BOTH the threaded web server and the REPL. Two overlapping
# ingests used to read the same base and the last writer erased the
# other's chunks (docs.json claimed chunks that no longer existed).
_INGEST_LOCK = threading.Lock()


def ingest(ws, paths, relative=True):
    """Ingest workspace files -> {files, chunks, skipped:[...]} (thread-safe
    wrapper - see _INGEST_LOCK above).
    v6.7: the read-modify-write is now also guarded ACROSS processes
    (REPL + web server share the store) via an advisory lock file."""
    with _INGEST_LOCK:
        d = _paths(ws)[0]
        if natom is not None:
            with natom.file_lock(d / "ingest.lock", timeout=8.0):
                return _ingest_impl(ws, paths, relative=relative)
        return _ingest_impl(ws, paths, relative=relative)


def _ingest_impl(ws, paths, relative=True):
    """Ingest workspace files -> {files, chunks, skipped:[...]}.
    v6.7: a DIRECTORY argument is expanded into its ingestable files
    (the /knowledge usage text always promised <file|dir> but a dir
    failed with 'nothing ingested')."""
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise ModuleError("no paths given")
    wsr = Path(ws).resolve()
    docs, seen = [], set()
    skipped = []
    expanded = []
    for raw in paths[:MAX_FILES]:
        d = _safe_join(ws, raw)
        if d is not None and d.is_dir():
            try:
                for f in sorted(d.rglob("*")):
                    if len(expanded) >= MAX_FILES:
                        break
                    if f.is_file() and "/.nova" not in f.as_posix() \
                            and not f.name.startswith("."):
                        expanded.append(f.relative_to(wsr).as_posix())
            except OSError:
                skipped.append(str(raw)[:120] + " (dir read error)")
            continue
        expanded.append(raw)
    for raw in expanded[:MAX_FILES]:
        p = _safe_join(ws, raw)
        if p is None or not p.is_file():
            skipped.append(str(raw)[:120])
            continue
        if p.name.lower() in (".nova", ".novaignore"):
            pass                          # allow-listed bare dotfiles (no suffix)
        elif p.suffix.lower() not in ALLOWED:
            skipped.append(p.name + " (type)")
            continue
        try:
            if p.stat().st_size > MAX_FILE:
                skipped.append(p.name + " (size)")
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(p.name + " (read error)")
            continue
        rel = str(p.relative_to(wsr)) if relative else str(p)
        if rel in seen:
            continue
        seen.add(rel)
        try:
            mt = p.stat().st_mtime
        except OSError:
            mt = 0
        docs.append({"path": rel, "mtime": mt, "bytes": len(text), "text": text})
    if not docs:
        raise ModuleError("nothing ingested (missing files / types / sizes): "
                          + "; ".join(skipped[:5]))
    d, docs_p, chunks_p = _paths(ws)
    d.mkdir(parents=True, exist_ok=True)
    old_docs = {}
    try:
        old_docs = {e["path"]: e for e in json.loads(
            docs_p.read_text(encoding="utf-8")).get("docs", [])
            if isinstance(e, dict) and e.get("path")}
    except Exception as e:
        # v6.3: logged instead of vanishing - a corrupt docs.json used to be
        # indistinguishable from an empty one when debugging.
        try:
            import nova_log
            nova_log.soft("knowledge.ingest.docs_json", e)
        except Exception:
            pass
        old_docs = {}
    # docs whose mtime did not change are NOT re-chunked - but their
    # stored chunks MUST survive (that is the whole point of the check)
    changed = [d2 for d2 in docs
               if old_docs.get(d2["path"], {}).get("mtime") != d2["mtime"]]
    changed_paths = {d2["path"] for d2 in changed}
    kept = [e for e in old_docs.values() if e["path"] not in changed_paths]
    cid = 0
    # read old chunk lines that belong to kept docs (unchanged + absent)
    old_lines = []
    try:
        for ln in chunks_p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue                   # torn last line: skip
            if isinstance(e, dict) and e.get("doc") in {k["path"] for k in kept}:
                old_lines.append(ln)
                # v6.5: a hand-edited/corrupt non-numeric id must not crash
                # the whole ingest (the outer try only catches OSError)
                try:
                    cid = max(cid, int(e.get("id", 0)) + 1)
                except (TypeError, ValueError):
                    continue
    except OSError:
        pass
    new_lines = []
    for doc in changed:
        for off, ch in enumerate(_chunks_of(doc["text"])):
            new_lines.append(json.dumps({"id": cid, "doc": doc["path"],
                                         "off": off, "text": ch},
                                        ensure_ascii=False))
            cid += 1
    meta_out = kept + [{"path": d2["path"], "mtime": d2["mtime"],
                        "bytes": d2["bytes"]} for d2 in changed]
    tmp_c = chunks_p.with_suffix(".jsonl.part")
    tmp_c.write_text("\n".join(old_lines + new_lines) + ("\n" if old_lines + new_lines else ""),
                     encoding="utf-8")
    tmp_c.replace(chunks_p)
    tmp_d = docs_p.with_suffix(".json.part")
    tmp_d.write_text(json.dumps({"docs": meta_out}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    tmp_d.replace(docs_p)
    # v6.3: deterministic cache invalidation - two ingests within one
    # filesystem mtime tick would otherwise serve the OLD chunk list.
    with _CACHE_LOCK:
        _CHUNK_CACHE["key"] = None
        _CHUNK_CACHE["chunks"] = []
    return {"files": len(changed), "chunks": len(new_lines),
            "total_chunks": len(old_lines) + len(new_lines), "skipped": skipped}


def _load_chunks(ws):
    _d, _docs_p, chunks_p = _paths(ws)
    # v6.3 RAM/CPU: searches run on every chat turn that touches knowledge;
    # re-parsing up to 6000 chunks each time was the hot path. One-entry
    # cache keyed by (workspace, file mtime) - an ingest (or any write)
    # changes the mtime and invalidates it. Bounded: exactly one entry.
    try:
        mtime = chunks_p.stat().st_mtime
    except OSError:
        return []
    with _CACHE_LOCK:
        cached = _CHUNK_CACHE.get("key")
        if cached == (str(chunks_p), mtime):
            return _CHUNK_CACHE["chunks"]
    try:
        raw = chunks_p.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for ln in raw.splitlines():
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"]:
            out.append(e)
        if len(out) >= MAX_CHUNKS:
            break
    with _CACHE_LOCK:
        _CHUNK_CACHE["key"] = (str(chunks_p), mtime)
        _CHUNK_CACHE["chunks"] = out
    return out


_CHUNK_CACHE = {"key": None, "chunks": []}
_CACHE_LOCK = threading.Lock()


# --------------------------------------------------------------- search
def _doc_mtimes(ws):
    """{path: mtime} from docs.json - powers the recency boost. Empty on
    any problem (old workspaces without docs.json still search fine)."""
    _d, docs_p, _chunks_p = _paths(ws)
    try:
        return {e.get("path", ""): float(e.get("mtime") or 0)
                for e in json.loads(docs_p.read_text(encoding="utf-8"))
                .get("docs", []) if isinstance(e, dict)}
    except Exception:
        return {}


def _snippet(text, q_tokens, width=600):
    """v6.3: center the returned window on the FIRST query-term hit
    instead of always chopping the head of the chunk - the useful part of
    a 700-char chunk is usually in the middle."""
    if len(text) <= width:
        return text
    low = text.lower()
    pos = -1
    for t in q_tokens:
        pos = low.find(t)
        if pos >= 0:
            break
    if pos < 0:
        return text[:width]
    start = max(0, pos - width // 3)
    out = text[start:start + width]
    return ("..." if start > 0 else "") + out + ("..." if start + width < len(text) else "")


def search(ws, query, k=6):
    """HYBRID ranking over chunks (v6.8 upgrade):
      - TF-IDF cosine (as in v6.3, with phrase bonus + recency boost);
      - PLUS a dense vector score: each chunk is embedded as a
        normalized 256-dim hashing vector (word tokens + character
        3-grams) stored in a LOCAL sqlite file - the sqlite-vec slot,
        zero requests, zero dependencies. Char-ngrams give partial-word
        / typo / morphological matching that exact-token TF-IDF misses.
      final score = tfidf + 0.35 * dense_cosine.
    Returns [{doc, score, text}] (best first). An empty/degenerate state
    returns [] - never raises."""
    query = str(query or "").strip()
    if not query:
        return []
    chunks = _load_chunks(ws)
    if not chunks:
        return []
    q_tokens = _tokenize(query)[:30]
    if not q_tokens:
        return []
    N = len(chunks)
    tf_docs, df = [], {}
    for ch in chunks:
        toks = _tokenize(ch["text"])
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        tf_docs.append(tf)
        for t in tf:
            df[t] = df.get(t, 0) + 1
    k = min(max(int(k or 6), 1), 20)
    scores = []
    qset = {}
    for t in q_tokens:
        qset[t] = qset.get(t, 0) + 1
    # v6.3 phrase + recency setup
    phrase = " ".join(q_tokens)
    now = time.time()
    mtimes = _doc_mtimes(ws)
    # v6.8 dense layer (fail-soft: any sqlite problem just skips it)
    dense = _dense_scores(ws, chunks, query)
    for i, ch in enumerate(chunks):
        tf = tf_docs[i]
        num = 0.0
        for t, qf in qset.items():
            if t in tf:
                idf = math.log(1 + N / (1 + df[t]))
                num += qf * tf[t] * idf * idf
        d1 = math.sqrt(sum(v * v for v in tf.values())) or 1.0
        d2 = math.sqrt(sum(v * v for v in qset.values())) or 1.0
        score = num / (d1 * d2)
        if dense:
            score = score + 0.35 * dense.get(i, 0.0)
        low = ch["text"].lower()
        if score > 0 and phrase in low:
            score *= 1.25                      # exact phrase: strong signal
        if score > 0:
            age_days = (now - mtimes.get(ch.get("doc", ""), 0)) / 86400.0
            if mtimes and age_days < 7:
                score *= 1.05                  # fresh knowledge, small boost
            elif mtimes and age_days < 30:
                score *= 1.02
        scores.append((score, i))
    scores.sort(key=lambda s: -s[0])
    out = []
    for score, i in scores[:k]:
        if score <= 0:
            break
        ch = chunks[i]
        out.append({"doc": ch.get("doc", ""), "score": round(score, 4),
                    "text": _snippet(ch["text"], q_tokens)})
    return out


# --------------------------------------------------------------- v6.8: dense vectors
import sqlite3 as _sqlite3          # stdlib; local import keeps other
import struct as _struct            # import paths leaner

EMB_DIM = 256
_DENSE_W = 0.35                    # dense weight inside the hybrid score


def _vec_path(ws):
    return Path(ws) / ".nova" / "knowledge" / "vectors.db"


def _embed_hash(text, dim=EMB_DIM):
    """Normalized dense hashing embedding: word tokens (weight 1.0 each
    occurrence, sublinear) + character 3-grams of every token (weight
    0.35). Blake2b picks the index AND a signed magnitude bit, so the
    vector is dense-ish and cheap. Pure stdlib, deterministic."""
    v = [0.0] * dim

    def _bump(key, w):
        h = hashlib.blake2b(key.encode("utf-8", "ignore"),
                            digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if (h[4] & 1) else -1.0
        v[idx] += sign * w

    for tok in _tokenize(text)[:400]:
        _bump("w:" + tok, 1.0)
        low = tok.lower()
        if len(low) >= 3:
            for j in range(len(low) - 2):
                _bump("c:" + low[j:j + 3], 0.35)
    norm = math.sqrt(sum(x * x for x in v))
    if norm > 0:
        v = [x / norm for x in v]
    return v


def _pack_vec(v):
    return _struct.pack("<%df" % len(v), *v)


def _unpack_vec(blob, dim=EMB_DIM):
    try:
        return list(_struct.unpack("<%df" % dim, blob))
    except (_struct.error, TypeError, ValueError):
        return None


def _open_vecdb(ws):
    """sqlite connection for the vector store (created on demand).
    A fresh connection per operation - sqlite locks make this safe for
    the REPL + web-server double life, and it cannot leak handles."""
    d = _paths(ws)[0]
    d.mkdir(parents=True, exist_ok=True)
    conn = _sqlite3.connect(str(_vec_path(ws)), timeout=5)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS vec ("
                     "chunk_id INTEGER PRIMARY KEY, dim INTEGER, v BLOB)")
        conn.commit()
    except _sqlite3.Error:
        pass
    return conn


def _dense_scores(ws, chunks, query):
    """{chunk_index: cosine} from the local vector store; {} when the
    store is unavailable. Syncs missing vectors as a side effect
    (incremental: only NEW chunk ids get embedded)."""
    try:
        ids = []
        for i, ch in enumerate(chunks):
            try:
                ids.append((i, int(ch.get("id", -1))))
            except (TypeError, ValueError):
                ids.append((i, -1))
        valid = [(i, cid) for i, cid in ids if cid >= 0]
        if not valid:
            return {}
        conn = _open_vecdb(ws)
        try:
            rows = {}
            for cid, blob in conn.execute(
                    "SELECT chunk_id, v FROM vec"):
                rows[cid] = blob
            # sync: embed what is missing, drop what vanished
            have = set(rows)
            want = {cid for _i, cid in valid}
            stale = [cid for cid in have if cid not in want]
            missing = [(i, cid) for i, cid in valid if cid not in have]
            if missing or stale:
                try:
                    with conn:
                        if stale:
                            conn.executemany("DELETE FROM vec WHERE chunk_id=?",
                                             [(c,) for c in stale[:MAX_CHUNKS]])
                        for _i, cid in missing[:MAX_CHUNKS]:
                            conn.execute("INSERT OR REPLACE INTO vec "
                                         "(chunk_id, dim, v) VALUES (?,?,?)",
                                         (cid, EMB_DIM,
                                          _pack_vec(_embed_hash(
                                              chunks[_i]["text"]))))
                    rows = {cid: blob for cid, blob in
                            conn.execute("SELECT chunk_id, v FROM vec")}
                except _sqlite3.Error:
                    pass
        finally:
            conn.close()
        qv = _embed_hash(query)
        out = {}
        for i, cid in valid:
            v = _unpack_vec(rows.get(cid) or b"")
            if not v:
                continue
            out[i] = sum(a * b for a, b in zip(qv, v))
        return out
    except Exception:
        return {}


def context(ws, query, budget=2000, k=6):
    """Top hits packed as ONE prompt-ready block (source-tagged)."""
    hits = search(ws, query, k=k)
    if not hits:
        return ""
    parts, used = [], 0
    for h in hits:
        block = "[src: %s]\n%s" % (h["doc"], h["text"])
        if used + len(block) > budget:
            break
        parts.append(block)
        used += len(block)
    return "\n---\n".join(parts)


def stats(ws):
    chunks = _load_chunks(ws)
    docs = set(c.get("doc", "") for c in chunks)
    return {"docs": len(docs), "chunks": len(chunks)}


def reset(ws):
    # v6.7 fix: reset() unlinked the store WITHOUT the ingest lock - a
    # concurrent ingest's final os.replace() resurrected the "reset"
    # chunks right after the wipe (web exposes reset + ingest together).
    # v8.0: the CROSS-PROCESS advisory lock is taken too (reset only held
    # the in-process lock; a REPL ingest + web reset could still
    # interleave and resurrect chunks) - same pattern as ingest().
    with _INGEST_LOCK:
        d = _paths(ws)[0]
        if natom is not None:
            with natom.file_lock(d / "ingest.lock", timeout=8.0):
                return _reset_impl(ws)
        return _reset_impl(ws)


def _reset_impl(ws):
    _d, docs_p, chunks_p = _paths(ws)
    removed = 0
    for p in (docs_p, chunks_p, _vec_path(ws)):
        if p.is_file():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    # v6.3: a deleted chunks file must not leave stale chunks in the cache
    with _CACHE_LOCK:
        _CHUNK_CACHE["key"] = None
        _CHUNK_CACHE["chunks"] = []
    return {"removed": removed}
