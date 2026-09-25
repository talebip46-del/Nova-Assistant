#!/usr/bin/env python3
# =====================================================================
#  Nova Code - token & cost tracker for cloud providers (v5.0)
#
#  Local Ollama tokens are free; cloud tokens are not. Every chat turn
#  records what it spent into .nova/costs.json (per workspace):
#    - REAL counts when the provider reports usage (Ollama's final chunk
#      carries prompt_eval_count / eval_count),
#    - a conservative CHARACTER ESTIMATE everywhere else (marked as such).
#
#  From the ledger, /cost prints session/today/total costs per model and
#  /estimate prices the NEXT big request BEFORE you send it - including a
#  duration guess learned from the measured tokens/second of this very
#  machine + model ( priceless on slow hardware).
#
#  v7.9 usage panel: the user asked to SEE what the clouds consumed -
#  "بتونم ببینم چقدر توکن-درخواست-کردیت مصرف کردم و چقدر context".
#  usage_summary() aggregates the ledger into exactly that:
#    requests (turns), prompt/completion tokens, USD cost, a CREDIT
#    estimate (B.AI's documented law: 1 USD = 1,000,000 Credits and
#    X Credits/Token == X USD/1M tokens - so the USD price doubles as
#    the credit rate for every provider), and the CONTEXT the last
#    request used vs the model's context window (CONTEXT_TOKENS).
#
#  Prices are APPROXIMATE public list prices in USD per 1M tokens
#  (input, output), matched by model-name PREFIX. They drift - override
#  or extend them per workspace with .nova/pricing.json:
#      {"my-model": [0.5, 1.5], "gpt-4o-mini": [0.15, 0.6]}
#  Unknown models cost $0 and are REPORTED as unknown - never invented.
#
#  Pure standard library, atomic writes, fail-soft: tracking problems
#  must never break a chat turn.
# =====================================================================
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

# v6.8.1: record() is a load->append->save cycle that runs from BOTH the
# REPL and the threaded web server (and /agent fires several in
# parallel). Without a lock, two racing records read the same file and
# the second save ERASES the first turn's row - a silently under-counted
# money ledger. In-process lock + cross-process advisory file lock.
_LEDGER_LOCK = threading.RLock()

COSTS_FILE = "costs.json"
PRICING_OVERRIDE_FILE = "pricing.json"
VERSION = 1
MAX_LOG_ENTRIES = 400          # detailed per-turn rows kept in the file
CHARS_PER_TOKEN = 3.2          # estimate for mixed code/EN/FA text

# USD per 1M tokens: (input, output) - approximate public list prices.
PRICING = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4-turbo": (10.00, 30.00),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
    "claude-3-opus": (15.00, 75.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "llama-3.3-70b": (0.59, 0.59),
    "llama-3.1-70b": (0.59, 0.59),
    "llama-3.1-8b": (0.05, 0.08),
    "qwen/qwen-2.5-coder-32b": (0.09, 0.24),
    "qwen2.5-coder": (0.09, 0.24),
    "mistral-large": (2.00, 6.00),
}

# v7.9 - B.AI's documented credit law (docs.b.ai / pricing-and-usage):
#   "1 USD = 1,000,000 Credits" and "a price of X Credits/Token is
#   numerically equivalent to a standard reference price of
#   USD X / 1M Tokens". So the USD price table doubles as the credit
#   rate for B.AI - and as a fair credit EQUIVALENT for every other
#   provider (the unit the user actually pays in on b.ai).
CREDITS_PER_USD = 1_000_000

# Approximate context windows (tokens) by model-name PREFIX - they only
# feed the "how full is my context" gauge; unknown models simply show
# tokens without a percentage instead of inventing a limit.
CONTEXT_TOKENS = {
    "gpt-5": (400_000, 128_000),
    "gpt-4.1": (1_000_000, 32_000),
    "gpt-4o": (128_000, 16_000),
    "gpt-4-turbo": (128_000, 4_000),
    "o3": (200_000, 100_000),
    "o4-mini": (200_000, 100_000),
    "claude-opus-4": (200_000, 32_000),
    "claude-sonnet-4": (200_000, 64_000),
    "claude-3-7": (200_000, 64_000),
    "claude-3-5": (200_000, 8_000),
    "claude-3-opus": (200_000, 4_000),
    "gemini-2.5-pro": (1_048_576, 65_536),
    "gemini-2.5-flash": (1_048_576, 65_536),
    "gemini-2.0-flash": (1_048_576, 8_000),
    "gemini-1.5-pro": (2_097_152, 8_000),
    "gemini-1.5-flash": (1_048_576, 8_000),
    "deepseek-chat": (131_072, 8_000),
    "deepseek-reasoner": (131_072, 64_000),
    "deepseek": (131_072, 8_000),
    "llama-3.3": (131_072, 8_000),
    "llama-3.1": (131_072, 8_000),
    "kimi": (262_144, 8_000),
    "qwen": (131_072, 32_000),
    "glm-4": (131_072, 8_000),
    "glm": (131_072, 8_000),
    "grok": (131_072, 8_000),
    "mistral-large": (131_072, 8_000),
    "command": (256_000, 8_000),
    "sonar": (127_000, 4_000),
    "blackboxai": (131_072, 8_000),
}


# --------------------------------------------------------------- pricing
def _load_override(ws):
    try:
        p = Path(ws) / NOVA_DIR / PRICING_OVERRIDE_FILE
        if not p.is_file():
            return {}
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(obj, dict):
            return {}
        out = {}
        for k, v in obj.items():
            # v7.9: exclude bools - isinstance(True, int) is True in Python,
            # so a pricing.json [true, false] silently priced tokens at $1/1M.
            if isinstance(v, (list, tuple)) and len(v) == 2 \
                    and all(isinstance(x, (int, float))
                            and not isinstance(x, bool) and x >= 0 for x in v):
                out[str(k).lower()] = (float(v[0]), float(v[1]))
        return out
    except Exception:
        return {}


def price_of(ws, provider, model):
    """(in_usd_per_1M, out_usd_per_1M, known) for provider+model.
    ollama (local) is always (0, 0, True).

    v7.9 audit fix: LONGEST-PREFIX wins (ctx_limit's rule). First-match
    used to let a pricing.json override whose key is a prefix of another
    model silently reprice that sibling - {"gpt-4o": [3, 12]} turned
    every gpt-4o-mini turn into a $3.00/1M lie (20x the real $0.15).
    An override also beats the base table on equal length, and an empty
    / whitespace key never matches anything."""
    if provider == "ollama":
        return (0.0, 0.0, True)
    model_l = str(model or "").lower()
    best = None                       # (prefix_len, (in, out))
    for table in (_load_override(ws), PRICING):
        for prefix, pair in table.items():
            pfx = str(prefix or "").strip().lower()
            if not pfx or not model_l.startswith(pfx):
                continue
            if best is None or len(pfx) > best[0]:
                best = (len(pfx), (pair[0], pair[1]))
    if best is None:
        return (0.0, 0.0, False)
    return (best[1][0], best[1][1], True)


def est_tokens(text, factor=CHARS_PER_TOKEN):
    """Conservative token estimate for one text blob."""
    return int(len(str(text or "")) / factor) + (1 if text else 0)


def ctx_limit(model):
    """(context_window, max_output) for a model name, or (None, None)
    when unknown. Matched by prefix, longest prefix wins so 'gpt-4.1'
    beats 'gpt-4' style overlaps (the table only holds real prefixes,
    but the longest-wins rule keeps custom overrides safe too)."""
    m = str(model or "").lower()
    best = ""
    for prefix in CONTEXT_TOKENS:
        if m.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    if not best:
        return (None, None)
    pair = CONTEXT_TOKENS[best]
    return (int(pair[0]), int(pair[1]))


def credits_of(usd):
    """USD -> B.AI-style credits (1 USD = 1M credits). The ledger stores
    USD; the panel shows both."""
    try:
        return float(usd or 0) * CREDITS_PER_USD
    except (TypeError, ValueError):
        return 0.0


def cost_of(ws, provider, model, ptok, ctok):
    """USD cost of one usage pair (1M-token pricing -> actual tokens)."""
    pin, pout, _ = price_of(ws, provider, model)
    return (ptok / 1e6) * pin + (ctok / 1e6) * pout


# --------------------------------------------------------------- ledger
def costs_path(ws):
    return Path(ws) / NOVA_DIR / COSTS_FILE


def _empty():
    return {"v": VERSION, "log": [], "archived": []}


def _load(ws):
    try:
        p = costs_path(ws)
        if not p.is_file():
            return _empty()
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(obj, dict):
            return _empty()
        out = _empty()
        if isinstance(obj.get("log"), list):
            out["log"] = [e for e in obj["log"] if isinstance(e, dict)]
        if isinstance(obj.get("archived"), list):
            out["archived"] = [e for e in obj["archived"] if isinstance(e, dict)]
        return out
    except Exception:
        return _empty()


def _save(ws, data):
    try:
        p = costs_path(ws)
        # v6.7: unique scratch name - the fixed ".tmp" collided across
        # processes (REPL + web share one ledger) and could publish a
        # torn, truncated ledger file.
        if natom is not None:
            return natom.write_text_atomic(
                p, json.dumps(data, ensure_ascii=False))
        # v8.0: unique scratch name in the degraded fallback too
        tmp = p.with_name("%s.%d.%d.tmp" % (
            p.stem, os.getpid(), int(time.time() * 1000) % 1000000))
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)

def record(ws, provider, model, prompt_tokens, completion_tokens,
           actual=False, dur_s=None, ok=True):
    """One turn of usage into the ledger. `actual` marks REAL counts from
    the provider (vs character estimates). Bounded, atomic, fail-soft,
    thread- AND process-safe (v6.8.1)."""
    try:
        ptok = max(0, int(prompt_tokens or 0))
        ctok = max(0, int(completion_tokens or 0))
    except (TypeError, ValueError, OverflowError):
        return
    # v7.9 hardening: a lying provider (or a hostile usage chunk) can
    # report absurd counts. _absorb_usage already refuses inf; a
    # 400-digit int passes int() but explodes the float math inside
    # cost_of - cap both at a trillion tokens (a real turn is <10^7).
    ptok = min(ptok, 10 ** 12)
    ctok = min(ctok, 10 ** 12)
    try:
        dur = round(float(dur_s), 2) \
            if isinstance(dur_s, (int, float)) and 0 <= dur_s <= 10 ** 7 \
            else None
    except (OverflowError, ValueError):
        dur = None
    entry = {
        "ts": int(time.time()),
        "provider": str(provider or "?")[:40],
        "model": str(model or "?")[:120],
        "ptok": ptok, "ctok": ctok,
        "actual": bool(actual),
        "ok": bool(ok),
        "dur": dur,
        "cost": round(cost_of(ws, provider, model, ptok, ctok), 6),
    }
    with _LEDGER_LOCK:
        if natom is not None:
            try:
                with natom.file_lock(costs_path(ws).parent / "costs.lock",
                                     timeout=8.0):
                    _record_locked(ws, entry)
                return
            except Exception:
                pass                      # degraded path below still works
        _record_locked(ws, entry)


def _record_locked(ws, entry):
    """The real record body - CALLER holds the locks."""
    data = _load(ws)
    data["log"].append(entry)
    if len(data["log"]) > MAX_LOG_ENTRIES:
        # archive the oldest half into per-(provider,model,day) rollups
        overflow, data["log"] = data["log"][:MAX_LOG_ENTRIES // 2], data["log"][MAX_LOG_ENTRIES // 2:]
        bucket = {}
        for e in overflow:
            # v6.2.1 fix: a hand-edited log row with ts=null/absent crashed
            # /cost and record() here (TypeError from fromtimestamp) -
            # degrade to epoch instead
            # v6.5 fix: the OTHER keys were still assumed - one mangled
            # row (missing provider, string ptok) raised KeyError/TypeError
            # and silently killed EVERY subsequent cost record for the
            # session. Degrade per-row instead.
            try:
                day = datetime.fromtimestamp(_ts(e)).strftime("%Y-%m-%d")
                prov = str(e.get("provider") or "?")[:40]
                mdl = str(e.get("model") or "?")[:120]
                pt = _num(e.get("ptok"))
                ct = _num(e.get("ctok"))
                co = _num(e.get("cost"))
                key = (prov, mdl, day)
                b = bucket.setdefault(key, {"provider": prov, "model": mdl,
                                            "day": day, "turns": 0, "ptok": 0,
                                            "ctok": 0, "cost": 0.0, "dur": 0.0})
                b["turns"] += 1
                b["ptok"] += pt
                b["ctok"] += ct
                b["cost"] += co
                b["dur"] += _num(e.get("dur"))
            except Exception:
                continue                      # one bad row must not stop the rest
        for b in bucket.values():
            b["cost"] = round(b["cost"], 6)
        data["archived"] = (data["archived"] + list(bucket.values()))[-200:]
    _save(ws, data)


def reset(ws):
    """Wipe the ledger (returns error string or ''). v7.9: the unlink
    happens under the same cross-process lock record() uses - a
    concurrent record() could otherwise resurrect pre-reset rows in the
    load->unlink->save window (the reset was non-deterministic).

    v7.9 audit fix: file_lock() degrades by yielding False instead of
    raising, so the old `with` body ran UNLOCKED whenever the advisory
    lock could not be taken - an in-flight record()'s save resurrected
    pre-reset rows. The in-process _LEDGER_LOCK is now always held, and
    a degraded cross-process lock refuses to unlink (honest 'busy'
    error, retry works) instead of silently resurrecting spent rows."""
    with _LEDGER_LOCK:
        try:
            if natom is not None:
                try:
                    with natom.file_lock(
                            costs_path(ws).parent / "costs.lock",
                            timeout=8.0) as got:
                        if got:
                            p = costs_path(ws)
                            if p.is_file():
                                p.unlink()
                            return ""
                        # degraded: no cross-process safety - do NOT
                        # unlink; a concurrent recorder would resurrect.
                        return ("cost ledger is busy (another Nova "
                                "process?) - try again in a moment")
                except OSError:
                    pass        # lock file trouble -> degraded unlink below
            p = costs_path(ws)
            if p.is_file():
                p.unlink()
            return ""
        except OSError as e:
            return str(e)


# --------------------------------------------------------------- reports
def _ts(e):
    """Row timestamp -> safe int (a hand-edited costs.json row may carry
    null/string ts - that must never crash a report). v7.9: OverflowError
    for float infinity / 10**400 ints joined the party."""
    try:
        return int(e.get("ts") or 0)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return 0


def _num(v):
    """v6.5: any row value -> int/float (a string 'oops' in costs.json
    used to crash report() with TypeError on +=)."""
    try:
        f = float(v)
        return int(f) if f == int(f) and abs(f) < 2 ** 53 else f
    except (TypeError, ValueError, OverflowError):
        return 0


def _row_stats(rows, today=None):
    turns = 0
    ptok = ctok = 0
    cost = dur = 0.0
    est = 0
    per_model = {}
    for e in rows:
        if not isinstance(e, dict):
            continue                      # v6.5: a junk row must not kill the report
        archived = "turns" in e            # rollup bucket from the archive
        # v7.9: a string 'turns' in an archived rollup used to raise
        # TypeError on += - every field degrades through _num now.
        n = _num(e.get("turns", 1)) if archived else 1
        if today is not None:
            # v7.9: a mangled-but-numeric ts (Infinity / 10**20 from a
            # hand-edited file) raised OverflowError/ValueError here and
            # killed the WHOLE report - /cost crashed raw, the web usage
            # panel silently showed all zeros, and the daily budgets
            # stopped enforcing. One hostile row is skipped instead.
            try:
                day = e.get("day") if archived else \
                    datetime.fromtimestamp(_ts(e)).strftime("%Y-%m-%d")
            except (ValueError, OverflowError, OSError):
                continue
            if day != today:
                continue
        pt = _num(e.get("ptok"))
        ct = _num(e.get("ctok"))
        co = _num(e.get("cost"))
        turns += n
        ptok += pt
        ctok += ct
        cost += co
        dur += _num(e.get("dur"))
        if not archived and not e.get("actual"):
            est += 1
        key = (e.get("provider", "?") or "?", e.get("model", "?") or "?")
        m = per_model.setdefault(key, {"turns": 0, "ptok": 0, "ctok": 0, "cost": 0.0})
        m["turns"] += n
        m["ptok"] += pt
        m["ctok"] += ct
        m["cost"] += co
    return {"turns": turns, "ptok": ptok, "ctok": ctok, "cost": round(cost, 6),
            "estimated_rows": est,
            "tok_per_sec": (round((ptok + ctok) / dur, 1) if dur > 0 and (ptok + ctok) > 0 else None),
            "per_model": {f"{p} :: {m}": {"turns": v["turns"], "ptok": v["ptok"],
                                          "ctok": v["ctok"], "cost": round(v["cost"], 6)}
                          for (p, m), v in per_model.items()}}


def report(ws):
    """Aggregated ledger: today + all-time (log + archived rollups)."""
    data = _load(ws)
    today = datetime.now().strftime("%Y-%m-%d")
    all_rows = list(data["log"]) + list(data["archived"])
    return {"today": _row_stats(all_rows, today=today), "total": _row_stats(all_rows)}


def _per_provider(stats_dict):
    """{provider: {requests, ptok, ctok, cost, credits}} from a _row_stats
    result (its per_model keys are 'provider :: model'). Pure, fail-soft."""
    out = {}
    for key, m in (stats_dict.get("per_model") or {}).items():
        prov = str(key).split(" :: ", 1)[0].strip() or "?"
        b = out.setdefault(prov, {"requests": 0, "ptok": 0, "ctok": 0,
                                  "cost": 0.0})
        try:
            b["requests"] += int(m.get("turns", 0) or 0)
            b["ptok"] += int(m.get("ptok", 0) or 0)
            b["ctok"] += int(m.get("ctok", 0) or 0)
            b["cost"] = round(b["cost"] + float(m.get("cost", 0) or 0), 6)
        except (TypeError, ValueError):
            continue
    for b in out.values():
        b["credits"] = round(credits_of(b["cost"]), 3)
    return out


def usage_summary(ws):
    """WHAT THE CLOUDS ACTUALLY CONSUMED - the payload the /cost command
    and the web usage panel render. Fail-soft: any ledger problem degrades
    to an empty summary, never an exception.

    Shape:
      today / total: requests, prompt_tokens, completion_tokens,
                     total_tokens, cost_usd, credits, estimated_rows,
                     per_provider
      last_request:  the newest ledger row (context that request used):
                     provider, model, context_tokens (= its prompt tokens),
                     completion_tokens, ts, actual, ok, ctx_window,
                     ctx_output_cap, ctx_pct
      cache_savings: the economy counters (requests/tokens the caches saved)
    """
    empty = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "total_tokens": 0, "cost_usd": 0.0, "credits": 0.0,
             "estimated_rows": 0, "per_provider": {}}
    try:
        rep = report(ws)
    except Exception:
        rep = {"today": dict(empty), "total": dict(empty)}

    def _block(stats):
        out = dict(empty)
        try:
            out["requests"] = int(stats.get("turns", 0) or 0)
            out["prompt_tokens"] = int(stats.get("ptok", 0) or 0)
            out["completion_tokens"] = int(stats.get("ctok", 0) or 0)
            out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
            out["cost_usd"] = round(float(stats.get("cost", 0) or 0), 6)
            out["credits"] = round(credits_of(out["cost_usd"]), 3)
            out["estimated_rows"] = int(stats.get("estimated_rows", 0) or 0)
            out["per_provider"] = _per_provider(stats)
        except Exception:
            pass
        return out

    today_b, total_b = _block(rep.get("today") or {}), _block(rep.get("total") or {})

    last = None
    try:
        data = _load(ws)
        if data["log"]:
            e = data["log"][-1]
            if isinstance(e, dict):
                ptok = max(0, int(_num(e.get("ptok"))))
                ctok = max(0, int(_num(e.get("ctok"))))
                model = str(e.get("model") or "?")[:120]
                win, out_cap = ctx_limit(model)
                pct = None
                if win and ptok > 0:
                    pct = round(min(100.0, 100.0 * ptok / win), 1)
                last = {
                    "provider": str(e.get("provider") or "?")[:40],
                    "model": model,
                    "context_tokens": ptok,
                    "completion_tokens": ctok,
                    "ts": _ts(e),
                    "actual": bool(e.get("actual")),
                    "ok": bool(e.get("ok", True)),
                    "ctx_window": win,
                    "ctx_output_cap": out_cap,
                    "ctx_pct": pct,
                }
    except Exception:
        last = None

    savings = {"requests_saved": 0, "tokens_saved": 0, "cache_hits": 0}
    try:
        import nova_economy as _econ
        st = _econ.stats(ws)
        cnt = (st or {}).get("counters") or {}
        for k in savings:
            savings[k] = int(cnt.get(k, 0) or 0)
    except Exception:
        pass

    return {"today": today_b, "total": total_b,
            "last_request": last, "cache_savings": savings}


def estimate_turn(ws, prompt_chars, provider, model, expected_out_chars=None):
    """Price + duration estimate for a request BEFORE sending it.
    Duration uses the measured tokens/second of this machine+model when
    the ledger has data (local slow hardware reality), otherwise None."""
    ptok = est_tokens("x" * int(prompt_chars))
    out_tok = est_tokens("x" * int(expected_out_chars)) if expected_out_chars else None
    pin, pout, known = price_of(ws, provider, model)
    cost = (ptok / 1e6) * pin + ((out_tok or 0) / 1e6) * pout
    rep = report(ws)
    speed = None
    for stats in (rep["today"], rep["total"]):
        if stats["tok_per_sec"]:
            speed = stats["tok_per_sec"]
            break
    sec = None
    if speed and out_tok:
        sec = round(out_tok / speed, 1)
    return {"prompt_tokens": ptok, "out_tokens": out_tok,
            "cost_usd": round(cost, 6), "price_known": known,
            "tok_per_sec": speed, "est_seconds": sec}
