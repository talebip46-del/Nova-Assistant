#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - nova_flightlog (v8.0 "clear")
#
#  The AGENT'S BLACK BOX: a structured, always-on record of the
#  decisions made behind the scenes - which brain was picked and why,
#  which commands were screened to which verdict, what the apply
#  pipeline did, what the agent loop decided, what recovery chose.
#
#  nova_log (v6.3) records ERRORS (the fail-soft swallowing sites).
#  This module records DECISIONS - "the plane crashed, why did the
#  pilot turn?" Both read like a flight recorder: newest last, JSONL,
#  size-capped, rotated by keeping the newest lines.
#
#      import nova_flightlog as flog
#      flog.log("brain.pick", "routed to local qwen3",
#               backend="local", model="qwen3:4b", reason="coding route")
#
#  Every function swallows its own errors - the black box must never
#  be the thing that crashes the agent. Pure standard library.
#
#  - RAM ring (bounded) for instant /blackbox reads before any disk IO
#  - file sink <ws>/.nova/logs/flightlog.ndjson (rotate at 1 MB, keep
#    the newest 1500 entries)
#  - NOVA_FLIGHTLOG=0 turns the FILE sink off (RAM ring stays on)
#  - /blackbox [n] (terminal) and GET /api/blackbox (web) read it
# =====================================================================
import json
import os
import threading
import time
from collections import deque
from pathlib import Path

VERSION = "8.0"

try:
    import nova_atomic as natom
except Exception:
    natom = None

RAM_LIMIT = 240                 # entries kept in RAM
FILE_LIMIT = 1024 * 1024        # rotate the file at 1 MB
FILE_KEEP = 1500                # newest lines kept after rotation
MAX_FIELD = 400                 # any single string field is capped

_lock = threading.Lock()
_ring = deque(maxlen=RAM_LIMIT)
_path = None                    # Path or None
_ws = None


def configure(ws):
    """Point the file sink at <ws>/.nova/logs/flightlog.ndjson. Safe to
    call repeatedly (workspace switches re-point it); best effort."""
    global _path, _ws
    try:
        # v8.0: pathlib.Path HAS a `.root` attribute ("/") - detect a
        # plain path BY TYPE first (the trap nova_think._ws_root
        # documents), or the sink silently points at /.nova/...
        base = ws
        if not isinstance(base, (str, Path)):
            base = getattr(ws, "root", ws)
        if base is None:
            return
        p = Path(str(base)) / ".nova" / "logs" / "flightlog.ndjson"
        with _lock:
            _ws = str(base)
            _path = p
    except Exception:
        pass


def _cap(v):
    if v is None:
        return ""
    s = str(v)
    if len(s) > MAX_FIELD:
        return s[:MAX_FIELD - 3] + "..."
    return s


def log(where, msg="", level="info", **fields):
    """Record one decision. NEVER raises. `where` is a short dotted
    origin (brain.pick, run.verdict, apply.batch, loop.phase, ...),
    `msg` a human one-liner; **fields carry the structured context."""
    try:
        entry = {"ts": round(time.time(), 3), "where": _cap(where),
                 "level": level if level in ("info", "warn", "error")
                 else "info", "msg": _cap(msg)}
        for k, v in list(fields.items())[:8]:
            try:
                if isinstance(v, (int, float, bool)) or v is None:
                    entry[str(k)[:40]] = v
                else:
                    entry[str(k)[:40]] = _cap(v)
            except Exception:
                continue
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with _lock:
            _ring.append(entry)
            path = _path
        if path is None or os.environ.get("NOVA_FLIGHTLOG", "") == "0":
            return
        _append_file(path, line)
    except Exception:
        pass


def warn(where, msg="", **fields):
    log(where, msg, level="warn", **fields)


def error(where, msg="", **fields):
    log(where, msg, level="error", **fields)


def _append_file(path, line):
    """Append one JSONL line, rotating when the file grows past
    FILE_LIMIT. Rotation rewrites through a unique scratch file and
    keeps the newest FILE_KEEP lines."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        try:
            if path.stat().st_size > FILE_LIMIT:
                _rotate(path)
        except OSError:
            pass
    except Exception:
        pass


def _rotate(path):
    """Best-effort rotation: keep the newest FILE_KEEP lines."""
    try:
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines()
        keep = lines[-FILE_KEEP:]
        if natom is not None:
            natom.write_text_atomic(path, "\n".join(keep) + "\n")
        else:
            tmp = path.with_name("%s.%d.rot" % (path.name, os.getpid()))
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            os.replace(tmp, path)
    except Exception:
        pass


def recent(n=40, where_prefix=None, level=None):
    """The newest entries from the RAM ring (instant, no disk IO).
    Returns a list oldest-first, capped to n."""
    try:
        with _lock:
            items = list(_ring)
        if where_prefix:
            items = [e for e in items
                     if str(e.get("where", "")).startswith(where_prefix)]
        if level:
            items = [e for e in items if e.get("level") == level]
        return items[-max(1, min(int(n or 40), RAM_LIMIT)):]
    except Exception:
        return []


def read_file(n=200, where_prefix=None, level=None):
    """Read the file sink directly (survives a restart). Newest LAST,
    capped to n. Fail-soft: unreadable -> []."""
    try:
        with _lock:
            path = _path
        if path is None or not Path(path).is_file():
            return []
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        out = []
        for ln in lines[-max(1, min(int(n or 200), 2000)):]:
            try:
                e = json.loads(ln)
            except Exception:
                continue
            # v8.0: a torn/partial line can still parse as a bare JSON
            # scalar - it is not an entry and must not break the read
            if not isinstance(e, dict):
                continue
            if where_prefix and not str(e.get("where", "")).startswith(
                    where_prefix):
                continue
            if level and e.get("level") != level:
                continue
            out.append(e)
        return out
    except Exception:
        return []


def state():
    """Small status dict for /doctor and the web panel."""
    try:
        with _lock:
            path = _path
            size = len(_ring)
        on_file = os.environ.get("NOVA_FLIGHTLOG", "") != "0"
        fsize = 0
        try:
            if path is not None and Path(path).is_file():
                fsize = Path(path).stat().st_size
        except OSError:
            pass
        return {"version": VERSION, "enabled": True, "file": on_file,
                "ram_entries": size, "file_bytes": fsize,
                "path": str(path) if path is not None else ""}
    except Exception:
        return {"version": VERSION, "enabled": False}
