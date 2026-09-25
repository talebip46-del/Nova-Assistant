#!/usr/bin/env python3
# =====================================================================
#  Nova Code - request economy layer (v6.6)
#
#  The user's law for cloud brains: "خیلی خیلی خیلی توکن، کردیت و
#  درخواست کمتر" - WAY fewer tokens, credits and requests. This module
#  is the part of Nova that actively enforces it, before and after each
#  model call:
#
#    1. RESPONSE CACHE   utility-section calls (commit/PR text, compact
#       summaries, verify judges) are pure functions of their prompt.
#       An identical prompt is answered from the local cache - ZERO
#       tokens, ZERO credits, ZERO requests. Hits are counted so the
#       user SEES what they saved (/saver).
#    2. DAILY BUDGETS    a per-provider USD and/or token budget checked
#       BEFORE every cloud request - a runaway loop is stopped locally
#       instead of silently draining the account.
#    3. COUNTERS         requests_saved / tokens_saved / cache_hits /
#       blocked - persisted per workspace, reset each day.
#
#  (The token-side savings themselves live in nova.py: cloud prompt
#  budgeting, per-section max-token caps, Anthropic prompt caching -
#  all configured through .nova/providers.json.)
#
#  Pure standard library. Atomic writes. Fail-soft: a broken cache file
#  must never break a chat turn. The cache NEVER stores API keys - only
#  prompts and answers of the utility sections.
# =====================================================================
import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from nova_policy import NOVA_DIR

try:
    import nova_atomic as natom
except Exception:
    natom = None

CACHE_FILE = "responses_cache.json"
VERSION = 1
MAX_ANSWER_CHARS = 60_000          # one cached answer, capped
# v6.7: must stay ABOVE the worst case (64 entries x 60k chars + JSON
# overhead ~ 4.5MB). At 2MB the normal full store exceeded the cap, _load
# degraded to empty() and the next cache_put WIPED the cache AND the day's
# counters (the /saver stats silently reset to zero).
MAX_CACHE_FILE_BYTES = 8_000_000   # whole store, capped
DEFAULT_TTL = 7 * 86400
DEFAULT_MAX_ENTRIES = 64
CHARS_PER_TOKEN = 3.2              # matches nova_cost's estimate

_LOCK = threading.Lock()


def cache_path(ws):
    return Path(ws) / NOVA_DIR / CACHE_FILE


# --------------------------------------------------------------- key
def cache_key(provider, model, messages, temperature):
    """Stable key for one utility request. The FULL messages list is
    part of the key - a changed system prompt or history is a different
    request and must never be served stale. Temperature is rounded so
    0.2 and 0.20000001 hash the same."""
    try:
        norm = json.dumps(
            [str(provider or ""), str(model or ""),
             round(float(temperature or 0), 3),
             [(m.get("role", ""), str(m.get("content", ""))) for m in messages
              if isinstance(m, dict)]],
            ensure_ascii=False, sort_keys=True).encode("utf-8")
    except Exception:
        return ""
    return hashlib.sha256(norm).hexdigest()


# --------------------------------------------------------------- persistence
def _empty():
    return {"v": VERSION, "day": datetime.now().strftime("%Y-%m-%d"),
            "counters": {"cache_hits": 0, "requests_saved": 0,
                         "tokens_saved": 0, "blocked": 0},
            "cache": []}


def _reset_counters(c):
    c["day"] = datetime.now().strftime("%Y-%m-%d")
    c["counters"] = {"cache_hits": 0, "requests_saved": 0,
                     "tokens_saved": 0, "blocked": 0}
    return c


def parse_store(payload, now=None, ttl=DEFAULT_TTL):
    """Raw JSON -> (counters, live_entries). Pure. Junk degrades to
    empty; expired entries are dropped here (the only place that drops)."""
    if not isinstance(payload, dict):
        return dict(_empty()["counters"]), []
    today = datetime.now().strftime("%Y-%m-%d")
    counters = dict(_empty()["counters"])
    raw = payload.get("counters")
    if isinstance(raw, dict):
        for k in counters:
            v = raw.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                counters[k] = int(v)
    if payload.get("day") != today:
        counters = dict(_empty()["counters"])   # new day -> fresh counters
    now = time.time() if now is None else now
    entries = []
    seen = set()
    raw_cache = payload.get("cache")
    if isinstance(raw_cache, list):
        for e in raw_cache:
            if not isinstance(e, dict):
                continue
            k = e.get("k")
            ts = e.get("ts")
            answer = e.get("answer")
            if not isinstance(k, str) or not k or not isinstance(answer, str):
                continue
            if not isinstance(ts, (int, float)) or ts <= 0 \
                    or (now - ts) > ttl or k in seen:
                continue
            seen.add(k)
            entries.append({"k": k[:80], "ts": float(ts),
                            "answer": answer[:MAX_ANSWER_CHARS]})
    return counters, entries


def _load(ws):
    try:
        p = cache_path(ws)
        if not p.is_file() or p.stat().st_size > MAX_CACHE_FILE_BYTES:
            return _empty()
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return _empty()


def _save(ws, data):
    tmp = None
    try:
        p = cache_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        # v6.7: unique tmp name - the fixed ".tmp" collided across
        # processes (REPL + web server share the workspace): writer B's
        # truncate between A's write and A's os.replace published
        # truncated bytes and the whole store degraded to empty.
        tmp = p.with_name("%s.%d.%d.tmp" % (
            p.stem, os.getpid(), threading.get_ident() % 100000))
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        tmp = None
        return ""
    except OSError:
        return "save-failed"
    except Exception:
        return "save-failed"
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except Exception:
                pass


def _mutate(ws, fn):
    """v7.9: run a load->mutate->save cycle under the CROSS-PROCESS file
    lock. The REPL and the web server share one workspace; plain atomic
    replaces were last-writer-wins, so process A's save could erase the
    counters/cache entries process B had just written (proven: 2 x 30
    bumps lost one). Degrades to the in-process lock when file_lock is
    unavailable - the same documented fail-open as nova_cost."""
    with _LOCK:
        if natom is not None and ws is not None:
            try:
                with natom.file_lock(cache_path(ws).parent / "economy.lock",
                                     timeout=8.0):
                    return fn()
            except Exception:
                pass                      # degraded path: in-process lock
        return fn()


# --------------------------------------------------------------- public API
def cache_get(ws, key, ttl=DEFAULT_TTL):
    """Cached answer for one request key, or None. Counts nothing here -
    the caller counts a hit (so near-misses stay invisible). A hit also
    refreshes the entry's recency (v6.7: the store is LRU-capped and the
    eviction below pops from the FRONT, so a hot entry used to age out
    while one-shot answers survived)."""
    if not key or ws is None:
        return None

    def op():
        counters, entries = parse_store(_load(ws), ttl=ttl)
        for idx, e in enumerate(entries):
            if e["k"] == key:
                if idx != len(entries) - 1:            # refresh recency
                    entries.append(entries.pop(idx))
                    _save(ws, {"v": VERSION, "day": _empty()["day"],
                               "counters": counters, "cache": entries})
                return e["answer"]
        return None
    return _mutate(ws, op)


def cache_put(ws, key, answer, ttl=DEFAULT_TTL, max_entries=DEFAULT_MAX_ENTRIES):
    """Store one utility answer (LRU-capped, TTL-cleaned). Returns ''. """
    if not key or ws is None or not (answer or "").strip():
        return ""

    def op():
        counters, entries = parse_store(_load(ws), ttl=ttl)
        entries = [e for e in entries if e["k"] != key]
        entries.append({"k": key, "ts": time.time(),
                        "answer": str(answer)[:MAX_ANSWER_CHARS]})
        while len(entries) > max(1, int(max_entries or DEFAULT_MAX_ENTRIES)):
            entries.pop(0)
        # v6.7: hard size cap - drop the OLDEST entries until the store
        # fits, so a burst of huge answers can never push the file over
        # MAX_CACHE_FILE_BYTES (which _load would treat as corrupt).
        # v6.8.1: measure BYTES (utf-8), not characters - the on-disk file
        # is utf-8 and Persian/CJK answers take 2-3 bytes per char, so the
        # char estimate could undercount 3x and the store still crossed
        # the cap (next _load then discarded the cache + daily counters).
        while entries and len(entries) > 1 and \
                sum(len(e["answer"].encode("utf-8")) + len(e["k"]) + 40
                    for e in entries) > MAX_CACHE_FILE_BYTES - 4096:
            entries.pop(0)
        return _save(ws, {"v": VERSION, "day": _empty()["day"],
                          "counters": counters, "cache": entries})
    return _mutate(ws, op)


def cache_clear(ws):
    """Wipe the response cache (counters stay). Returns ''. """
    def op():
        counters, _entries = parse_store(_load(ws))
        return _save(ws, {"v": VERSION, "day": _empty()["day"],
                          "counters": counters, "cache": []})
    return _mutate(ws, op)


def bump(ws, counter, n=1):
    """+n on one counter (day-rolled). Fail-soft. v7.9: cross-process safe
    (see _mutate - two processes used to lose each other's increments)."""
    if ws is None or counter not in ("cache_hits", "requests_saved",
                                     "tokens_saved", "blocked"):
        return
    try:
        n = max(0, int(n))
    except (TypeError, ValueError):
        return

    def op():
        data = _load(ws)
        counters, entries = parse_store(data)
        counters[counter] += n
        return _save(ws, {"v": VERSION, "day": _empty()["day"],
                          "counters": counters, "cache": entries})
    _mutate(ws, op)


def bump_tokens_saved(ws, n):
    bump(ws, "tokens_saved", n)


def stats(ws):
    """Live counters + cache size (for /saver and /api/providers)."""
    with _LOCK:
        counters, entries = parse_store(_load(ws))
    return {"counters": counters, "cache_entries": len(entries),
            "tokens_saved_est": counters["tokens_saved"],
            "usd_saved_est": None}     # priced per provider; left to the UI


# --------------------------------------------------------------- budgets
def _today_per_provider(ws):
    """{provider: {"cost": usd, "ptok": n, "ctok": n}} for TODAY, from
    the cost ledger. Fail-soft -> {} when the ledger is missing/broken."""
    try:
        import nova_cost
        rep = nova_cost.report(ws)
        out = {}
        for key, v in (rep.get("today", {}).get("per_model") or {}).items():
            prov = str(key).split(" :: ")[0].strip().lower()
            if not prov:
                continue
            b = out.setdefault(prov, {"cost": 0.0, "ptok": 0, "ctok": 0})
            b["cost"] += float(v.get("cost", 0) or 0)
            b["ptok"] += int(v.get("ptok", 0) or 0)
            b["ctok"] += int(v.get("ctok", 0) or 0)
        return out
    except Exception:
        return {}


def budget_block(ws, provider):
    """None when the request may go out, or a short human reason when the
    provider hit its daily budget. Called BEFORE every cloud request -
    blocking locally is the cheapest request of all."""
    if ws is None or not provider:
        return None
    try:
        import nova_providers as providers
        eco = providers.economy()
    except Exception:
        eco = {}
    usd_cap = float(eco.get("daily_budget_usd", 0) or 0)
    tok_cap = int(eco.get("daily_token_budget", 0) or 0)
    if usd_cap <= 0 and tok_cap <= 0:
        return None
    today = _today_per_provider(ws).get(str(provider).strip().lower())
    if not today:
        return None
    if usd_cap > 0 and today["cost"] >= usd_cap:
        return (f"daily budget reached for '{provider}' "
                f"(${today['cost']:.2f} >= ${usd_cap:.2f} today). "
                f"Raise it:  /saver budget <usd>  (0 = unlimited)")
    if tok_cap > 0 and (today["ptok"] + today["ctok"]) >= tok_cap:
        used = today["ptok"] + today["ctok"]
        return (f"daily token budget reached for '{provider}' "
                f"({used:,} >= {tok_cap:,} tokens today). "
                f"Raise it:  /saver tokens <n>  (0 = unlimited)")
    return None
