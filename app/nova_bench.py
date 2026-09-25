#!/usr/bin/env python3
# =====================================================================
#  Nova Code - local model benchmark (v6.8)
#
#  "بدونم کدوم مدل برای کدوم بخش بهتره": /bench runs a fixed 3-prompt
#  probe on every (or selected) installed local model and measures
#    wall seconds, tokens, tokens/s, and PROTOCOL COMPLIANCE
#    (does the tiny coding prompt come back as a valid === FILE: ===
#    block? that is the single strongest predictor that a model is
#    usable as the coding brain).
#  Results persist in .nova/bench.json; best_for(section) ranks models:
#    coding = protocol score x2.0 + speed, talk/utility = speed first.
#  Every case is tiny (num_predict capped) so a full sweep of 5 models
#  costs minutes, not hours, on weak hardware.
# =====================================================================
import json
import os
import re
import threading
import time
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:
    natom = None

BENCH_FILE = ".nova/bench.json"
MAX_MODELS = 12
MAX_HISTORY = 3          # keep the last N runs per model
HISTORY_CAP = 60 * 1024  # 60 KB on-disk cap

# num_predict caps per case - the probe never lets a small model ramble
CASES = [
    {"id": "chat", "prompt": "Answer in one short sentence: what is a variable?",
     "predict": 64, "weight": 1.0},
    {"id": "code", "prompt": "Write a python function add(a, b) that returns "
                             "a+b. Answer with code only.",
     "predict": 128, "weight": 1.0},
    {"id": "protocol",
     "prompt": "Create a file named hello.py containing one line: "
               'print("hi")\n'
               "Use exactly this format:\n=== FILE: hello.py ===\n<content>\n"
               "=== END ===\n",
     "predict": 160, "weight": 2.0},
]

_FILE_OK = re.compile(r"===\s*FILE:\s*hello\.py\s*===")


class BenchError(Exception):
    pass


def _chat_once(base, model, prompt, predict, timeout=600):
    """One NON-streaming Ollama chat call. Returns (text, wall_s, tok)."""
    import json as _json
    import urllib.request
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": predict},
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/api/chat",
        data=_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = _json.loads(resp.read().decode("utf-8", "replace"))
    wall = time.time() - t0
    text = (data.get("message") or {}).get("content", "") if isinstance(data, dict) else ""
    tok = int(data.get("eval_count") or 0) if isinstance(data, dict) else 0
    return (text, wall, tok)


def _score_case(case, text, wall, tok):
    """(protocol_ok, tokens_per_s)."""
    if case["id"] == "protocol":
        ok = bool(_FILE_OK.search(text or ""))
        return ok, _tps(tok, wall)
    return None, _tps(tok, wall)


def _tps(tok, wall):
    if wall <= 0:
        return 0.0
    return round(tok / wall, 1)


def bench_model(model, base="http://127.0.0.1:11434", fetch=None):
    """Run all cases on one model -> row dict. `fetch(model, prompt,
    predict)` is injectable for tests; defaults to the real Ollama call."""
    fetch = fetch or (lambda m, p, pred: _chat_once(base, m, p, pred))
    row = {"model": model, "ts": int(time.time()), "cases": {}, "tps": 0.0,
           "protocol": 0, "wall": 0.0}
    for case in CASES:
        try:
            text, wall, tok = fetch(model, case["prompt"], case["predict"])
        except Exception as e:
            row["cases"][case["id"]] = {"error": str(e)[:160]}
            row["wall"] = round(row["wall"] + 0, 1)
            continue
        ok, tps = _score_case(case, text, wall, tok)
        row["cases"][case["id"]] = {"wall": round(wall, 2), "tok": tok,
                                    "tps": tps, "ok": ok}
        row["wall"] = round(row["wall"] + wall, 2)
        if tps > row["tps"]:
            row["tps"] = tps
        if ok:
            row["protocol"] += 1
    return row


def path_for(ws):
    return Path(ws) / BENCH_FILE


def load(ws):
    try:
        data = json.loads(path_for(ws).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(ws, data):
    p = path_for(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False)
    if len(blob) > HISTORY_CAP:      # drop oldest runs until it fits
        # v8.0: models must be a DICT of lists - load() only checks the
        # top level, so a corrupt "models": ["m1"] crashed the shrink
        # loop with TypeError and record() propagated it.
        if not isinstance(data.get("models"), dict):
            data["models"] = {}
        for name in list(data.get("models", {})):
            runs = data["models"][name]
            if isinstance(runs, list) and len(runs) > 1:
                data["models"][name] = runs[-(MAX_HISTORY - 1):]
                blob = json.dumps(data, ensure_ascii=False)
                if len(blob) <= HISTORY_CAP:
                    break
    # v7.14.1: unique per-process scratch name (a shared ".tmp~" collided
    # across processes on one workspace)
    tmp = "%s.tmp%d" % (p, (os.getpid() * 7919
                      + threading.get_ident() % 100000
                      + int(time.time() * 1000)) % 1000000)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(blob)
        os.replace(tmp, p)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return str(e)
    return ""


def record(ws, row):
    """Append one run per model, capped."""
    data = load(ws)
    models = data.setdefault("models", {})
    name = row.get("model") or "?"
    runs = models.setdefault(name, [])
    runs.append(row)
    models[name] = runs[-MAX_HISTORY:]
    return save(ws, data)


def score_row(row, section="coding"):
    """Higher = better. coding: protocol compliance DOMINATES (1000 pts
    vs a 200 tok/s speed cap - a fast model that cannot follow the file
    protocol is useless as the coding brain). talk: speed dominates; a
    model that errored on every case is last."""
    cases = row.get("cases", {})
    n_err = sum(1 for c in cases.values() if isinstance(c, dict) and c.get("error"))
    if n_err == len(cases) and cases:
        return -1.0
    tps = row.get("tps") or 0.0
    proto = 1.0 if row.get("protocol") else 0.0
    if section == "coding":
        return proto * 1000.0 + min(tps, 200.0)
    return min(tps, 200.0) + proto * 20.0


def best_for(ws, section="coding"):
    """('model', row) of the best measured model, or (None, None)."""
    data = load(ws)
    best, best_row = None, None
    for name, runs in (data.get("models") or {}).items():
        if not runs:
            continue
        row = runs[-1]
        if best is None or score_row(row, section) > score_row(best_row, section):
            best, best_row = name, row
    return (best, best_row)


def table(rows):
    """Terminal-friendly ranking rows."""
    out = []
    rows = sorted(rows, key=lambda r: -score_row(r))
    for r in rows:
        out.append(f"  {r.get('model', '?'):34s} "
                   f"{(r.get('tps') or 0):7.1f} tok/s  "
                   f"protocol {'OK ' if r.get('protocol') else '---'} "
                   f"wall {r.get('wall') or 0:>6.1f}s")
    return "\n".join(out)
