#!/usr/bin/env python3
# =====================================================================
#  Nova Code - per-project settings profile (v5.0)
#
#  Each workspace can pin its OWN defaults in .nova/profile.json:
#      {"provider": "ollama", "model": "nova-code", "mode": "code",
#       "run_timeout": 120, "autotest": true}
#  Open the same project twice -> the same brain, the same model, the
#  same generation mode. Command switches (/provider, /model, /mode,
#  /timeout, /autotest) persist into the profile automatically.
#
#  Pure standard library, fail-soft everywhere: a broken or hostile file
#  falls back to clean defaults instead of breaking the session.
# =====================================================================
import json
import os
from pathlib import Path

from nova_policy import NOVA_DIR

try:
    import nova_atomic as natom
except Exception:
    natom = None

PROFILE_FILE = "profile.json"
MAX_PROFILE_BYTES = 8_000

FIELDS = ("provider", "model", "mode", "run_timeout", "autotest")
MODES = ("code", "balanced", "creative")
RUN_TIMEOUT_MIN, RUN_TIMEOUT_MAX = 5, 3600


def profile_path(ws):
    return Path(ws) / NOVA_DIR / PROFILE_FILE


def _clean(obj):
    """Validate one loaded/saved profile dict. Unknown fields are dropped,
    bad values fall back to '' / defaults - never trust a hand-edited file."""
    out = {}
    if not isinstance(obj, dict):
        return out
    p = obj.get("provider")
    if isinstance(p, str) and p.strip() and len(p) <= 40:
        out["provider"] = p.strip().lower()
    m = obj.get("model")
    if isinstance(m, str) and m.strip() and len(m) <= 120:
        out["model"] = m.strip()
    mode = obj.get("mode")
    if mode in MODES:
        out["mode"] = mode
    rt = obj.get("run_timeout")
    if isinstance(rt, int) and not isinstance(rt, bool) \
            and RUN_TIMEOUT_MIN <= rt <= RUN_TIMEOUT_MAX:
        out["run_timeout"] = rt
    at = obj.get("autotest")
    if isinstance(at, bool):
        out["autotest"] = at
    return out


def load_profile(ws):
    """Stored profile for this workspace, {} when absent/broken."""
    try:
        p = profile_path(ws)
        if not p.is_file() or p.stat().st_size > MAX_PROFILE_BYTES:
            return {}
        return _clean(json.loads(p.read_text(encoding="utf-8", errors="replace")))
    except Exception:
        return {}


def save_profile(ws, updates):
    """Merge `updates` into the stored profile (atomic write).
    Passing None/'' for a field clears it. Returns error string or ''."""
    try:
        cur = load_profile(ws)
        for k, v in (updates or {}).items():
            if k not in FIELDS:
                continue
            if v in (None, "", False) and k in ("provider", "model"):
                cur.pop(k, None)
                continue
            cur[k] = v
        cur = _clean(cur)
        p = profile_path(ws)
        # v6.7: unique scratch name (cross-process tmp collision)
        if natom is not None:
            return natom.write_text_atomic(
                p, json.dumps(cur, indent=2, ensure_ascii=False))
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)


def clear_profile(ws):
    """Remove the profile file entirely. Returns error string or ''."""
    try:
        p = profile_path(ws)
        if p.is_file():
            p.unlink()
        return ""
    except OSError as e:
        return str(e)
