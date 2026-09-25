#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - nova_log (v6.3)
#
#  Professional error reporting for the "fail-soft" swallowing pattern.
#
#  Nova deliberately keeps running when something breaks (a broken
#  knowledge file must not kill the agent). The price was 190+ silent
#  `except Exception: pass` sites - bugs disappeared without a trace.
#
#  This module keeps the stability AND restores the trace:
#
#      import nova_log
#      try:
#          ...
#      except Exception as e:
#          nova_log.soft("bg.on_done", e)      # one line, never raises
#
#  Every swallowed error lands in an in-RAM ring buffer (bounded) and,
#  once a workspace is known, in <ws>/.nova/logs/nova.log (JSONL, size
#  capped, rotated by keeping the newest lines).
#
#  - NOVA_DEBUG=1 also mirrors warnings to stderr, live.
#  - `/log` (terminal) shows the recent entries; the audit trail of
#    executed commands lives in nova_security.audit().
#
#  Pure standard library. Every function swallows its own errors - the
#  logger must never be the thing that crashes the agent.
# =====================================================================
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

VERSION = "6.3"

try:
    import nova_atomic as natom
except Exception:
    natom = None

RAM_LIMIT = 300               # entries kept in RAM
FILE_LIMIT = 512 * 1024       # rotate the file at 512 KB
FILE_KEEP = 1000              # newest lines kept after rotation

_lock = threading.Lock()
_ring = deque(maxlen=RAM_LIMIT)          # bounded -> no RAM leak
_counts = {}                             # where -> count (bounded by ring keys)
_log_path = None                         # Path or None
_configured_ws = None
DEBUG = os.environ.get("NOVA_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def configure(ws):
    """Point the file sink at <ws>/.nova/logs/nova.log. Safe to call
    repeatedly (workspace switches re-point it); best effort."""
    global _log_path, _configured_ws
    try:
        if ws is None:
            return
        ws = str(ws)
        if _configured_ws == ws and _log_path is not None:
            return
        d = Path(ws) / ".nova" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        _log_path = d / "nova.log"
        _configured_ws = ws
    except Exception:
        _log_path = None


def _emit_stderr(rec):
    try:
        line = "[nova:%s] %s" % (rec["level"], rec["where"])
        if rec.get("msg"):
            line += ": " + str(rec["msg"])
        if rec.get("exc"):
            line += " :: " + rec["exc"].splitlines()[-1] if rec["exc"] else ""
        sys.stderr.write(line + "\n")
    except Exception:
        pass


def _rotate_if_needed():
    """Keep the file bounded: over FILE_LIMIT -> rewrite with the newest
    lines, dropping quarters until it is genuinely under the cap (v6.5:
    keeping a fixed 1000 lines could exceed FILE_LIMIT - every note() then
    re-read and re-wrote the whole file forever). Called with the lock
    held."""
    try:
        if _log_path is None:
            return
        if not _log_path.exists() or _log_path.stat().st_size <= FILE_LIMIT:
            return
        lines = _log_path.read_text(encoding="utf-8", errors="replace") \
            .splitlines()[-FILE_KEEP:]
        while lines and sum(len(x) + 1 for x in lines) > FILE_LIMIT \
                and len(lines) > 10:
            lines = lines[len(lines) // 4:]
        # v6.7: unique scratch name (cross-process rotation collision)
        tmp = natom.tmp_name(_log_path, tag="logtmp") if natom is not None \
            else _log_path.with_suffix(".log.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, _log_path)
    except Exception:
        pass


def note(where, msg="", exc=None, level="warn"):
    """Record one structured entry. Never raises, never prints unless
    NOVA_DEBUG is on. `where` names the call site ('bg.on_done')."""
    try:
        exc_text = None
        if exc is not None:
            # v6.5: cap it like every other field - one exception with a
            # huge str() used to land whole in the RAM ring and the log file
            exc_text = ("%s: %s" % (type(exc).__name__, exc))[:1500]
        rec = {"ts": round(time.time(), 3), "level": str(level),
               "where": str(where)[:120], "msg": str(msg or "")[:500],
               "exc": exc_text}
        with _lock:
            _ring.append(rec)
            _counts[rec["where"]] = _counts.get(rec["where"], 0) + 1
            if _log_path is not None:
                try:
                    with open(_log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    _rotate_if_needed()
                except Exception:
                    pass
        if DEBUG and level in ("warn", "error"):
            _emit_stderr(rec)
    except Exception:
        pass


def soft(where, exc, msg=""):
    """One-liner for the classic `except Exception: pass` replacement."""
    note(where, msg=msg, exc=exc, level="warn")


def info(where, msg=""):
    note(where, msg=msg, level="info")


def debug(where, msg=""):
    """Only recorded when NOVA_DEBUG is on - keeps the log quiet."""
    if DEBUG:
        note(where, msg=msg, level="debug")


def tail(n=30):
    """The newest `n` entries, oldest first (dicts)."""
    with _lock:
        return list(_ring)[-max(1, int(n or 30)):]


def summary():
    """{where: count} for the entries still in the ring buffer."""
    with _lock:
        return dict(_counts)


def reset():
    """Test helper: clear RAM state (the file sink is untouched)."""
    global _log_path, _configured_ws
    with _lock:
        _ring.clear()
        _counts.clear()
        _log_path = None
        _configured_ws = None


def format_entries(entries):
    """Human-readable multi-line rendering for the /log command."""
    out = []
    for r in entries:
        when = time.strftime("%m-%d %H:%M:%S", time.localtime(r.get("ts", 0)))
        line = "%s  %-5s %-22s %s" % (when, r.get("level", "?"),
                                      r.get("where", "?"), r.get("msg", ""))
        if r.get("exc"):
            line += "  :: " + r["exc"]
        out.append(line)
    return out
