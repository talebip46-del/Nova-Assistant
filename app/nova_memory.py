#!/usr/bin/env python3
# =====================================================================
#  Nova Code - cross-run conversation memory (v5.0)
#
#  The chat used to die with the terminal: close nova.py, and the model
#  forgot the whole session. This module persists the conversation to
#  .nova/memory.json (per workspace) so the NEXT `python3 nova.py` run
#  CONTINUES where the last one stopped - same history the model sees,
#  same transcript for /export, same current plan.
#
#  Bounds keep the file healthy on a 4 GB machine:
#    - last MAX_HISTORY messages (model context window is small anyway)
#    - last MAX_TRANSCRIPT transcript entries (/export archive)
#    - every entry capped at MAX_ENTRY_CHARS chars
#    - whole file capped at MAX_FILE_BYTES (oldest data dropped first)
#
#  Fail-soft everywhere: a corrupt/truncated/hand-mangled file is thrown
#  away with a fresh start, never a crash.
# =====================================================================
import json
import os
import threading
import time
from pathlib import Path

from nova_policy import NOVA_DIR

try:
    import nova_atomic as natom
except Exception:
    natom = None

try:
    import nova_secretbox as secretbox
except Exception:
    secretbox = None

MEMORY_FILE = "memory.json"
MEMORY_ENC_FILE = "memory.json.enc"
VERSION = 1
MAX_HISTORY = 40          # kept messages (pairs of user/assistant)
MAX_TRANSCRIPT = 200      # kept transcript entries
MAX_ENTRY_CHARS = 8000    # per-message content cap
MAX_FILE_BYTES = 256_000  # whole-file cap - oldest rows are dropped first

# v6.8 at-rest encryption: when a passphrase is set (NOVA_PASSPHRASE env
# or /lock), the memory file is written SEALED (memory.json.enc, PBKDF2 +
# HMAC-CTR + encrypt-then-MAC) and the plaintext memory.json is removed.
# load prefers the sealed file and transparently decrypts with the
# session key. The cipher module is optional - without it the classic
# plaintext path stays exactly as before.
_passphrase = None


def set_cipher(passphrase):
    """Enable at-rest encryption for THIS process. Pass None to disable
    (next save writes plaintext again). Returns True when armed."""
    global _passphrase
    if not passphrase or secretbox is None:
        _passphrase = None
        return False
    _passphrase = str(passphrase)
    return True


def encryption_on():
    return bool(_passphrase) and secretbox is not None


def _key_for(ws):
    """A STABLE key for this workspace: the session passphrase with a
    FIXED salt derived from the workspace path, so the same passphrase
    always decrypts the same workspace's file without a per-file salt
    hunt. (The salt is not secret; it only shapes the KDF.)"""
    import hashlib
    salt = hashlib.sha256(("nova-mem-v1:" + str(Path(ws).resolve()))
                          .encode("utf-8")).digest()[:16]
    return secretbox.cached_key(_passphrase, salt)


def memory_path(ws):
    return Path(ws) / NOVA_DIR / MEMORY_FILE


def _clean_history(hist):
    out = []
    for m in (hist or [])[-MAX_HISTORY:]:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant", "system") or not isinstance(content, str):
            continue
        out.append({"role": role, "content": content[:MAX_ENTRY_CHARS]})
    return out


def _clean_transcript(tr):
    out = []
    for e in (tr or [])[-MAX_TRANSCRIPT:]:
        if not (isinstance(e, (list, tuple)) and len(e) == 2):
            continue
        role, text = e
        if role not in ("user", "nova") or not isinstance(text, str):
            continue
        out.append([role, text[:MAX_ENTRY_CHARS]])
    return out


def _fit_bytes(data):
    """Drop the OLDEST rows until the serialized file is inside the cap.
    v6.2.1 fix: also shrink over-long extras, and stop once history and
    transcript are BOTH empty (the old loop stopped on its own condition
    anyway, but the extra-shrink pass below now guarantees a file that
    _fit_bytes alone could never fit still ends up under the cap)."""
    while data["history"] or data["transcript"]:
        blob = json.dumps(data, ensure_ascii=False)
        if len(blob.encode("utf-8")) <= MAX_FILE_BYTES:
            break
        if len(data["transcript"]) > len(data["history"]):
            data["transcript"] = data["transcript"][1:]
        else:
            data["history"] = data["history"][1:]
    # last resort: trim any extra field that is still too large
    for k, v in list(data.items()):
        if k in ("v", "ts", "history", "transcript"):
            continue
        blob = json.dumps(data, ensure_ascii=False)
        if len(blob.encode("utf-8")) <= MAX_FILE_BYTES:
            break
        data[k] = str(v)[:400]
    return data


def _seal_write(p, blob, ws):
    """Write blob either sealed (encryption armed) or plaintext."""
    if not encryption_on():
        if natom is not None:
            return natom.write_text_atomic(
                p, blob.decode("utf-8") if isinstance(blob, bytes) else blob)
        p.parent.mkdir(parents=True, exist_ok=True)
        # v8.10.1 fix: unique scratch name (cross-process tmp collision) -
        # the fixed 'memory.tmp' was the one site the v6.7 law missed: the
        # REPL and the web server both persist memory in the same
        # workspace, and a writer B truncating between A's write and A's
        # os.replace published torn JSON (whole memory reset, silently).
        tmp = p.with_name("%s.%d.%d.tmp" % (p.name, os.getpid(),
                                            threading.get_ident() % 100000))
        try:
            tmp.write_text(blob.decode("utf-8") if isinstance(blob, bytes)
                           else blob, encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return ""
    try:
        enc = p.with_name(MEMORY_ENC_FILE)
        enc.parent.mkdir(parents=True, exist_ok=True)   # .nova may not exist yet
        secretbox.seal_file(enc, blob, _key_for(ws))
        try:
            if p.is_file():
                p.unlink()      # no plaintext twin left on disk
        except OSError:
            pass
        return ""
    except OSError as e:
        return str(e)


def save_memory(ws, history, transcript, extra=None):
    """Persist the conversation. Any OSError is silent by design (saving
    must never break a session) - returns error string or ''."""
    data = {
        "v": VERSION,
        "ts": int(time.time()),
        "history": _clean_history(history),
        "transcript": _clean_transcript(transcript),
    }
    for k, v in (extra or {}).items():
        # v6.2.1 fix: an oversized extra value (any huge str/dict was
        # accepted verbatim) made the file exceed MAX_FILE_BYTES even after
        # _fit_bytes dropped every row - load_memory then silently refused
        # the file (>4x cap) and the memory was lost. Cap extras here.
        if isinstance(v, (str, int, float, bool, list, dict)) and k not in data:
            blob = json.dumps(v, ensure_ascii=False, default=str)
            data[k] = v if len(blob) <= 4000 else blob[:4000]
    try:
        _fit_bytes(data)
        p = memory_path(ws)
        blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return _seal_write(p, blob, ws)
    except OSError as e:
        return str(e)


def load_memory(ws):
    """Previous conversation as (history, transcript, meta) - ([], [], {})
    when there is nothing (usable) to restore. A sealed file that cannot
    be decrypted (no passphrase armed / wrong one) returns ([], [], {})
    with meta["locked"]=True - fail-soft like every other corrupt state,
    but distinguishable for the UI."""
    try:
        p = memory_path(ws)
        enc = p.with_name(MEMORY_ENC_FILE)
        if secretbox is not None and enc.is_file() and secretbox.is_sealed(enc):
            size = enc.stat().st_size
            if size > MAX_FILE_BYTES * 4:
                return [], [], {}
            if not encryption_on():
                return [], [], {"locked": True}   # passphrase not armed
            try:
                raw = secretbox.open_file(enc, _key_for(ws))
            except ValueError:
                return [], [], {"locked": True}   # wrong passphrase / corrupt
            obj = json.loads(raw.decode("utf-8"))
        else:
            if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES * 4:
                return [], [], {}
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(obj, dict):
            return [], [], {}
        meta = {k: obj[k] for k in ("ts", "model", "mode") if k in obj}
        return (_clean_history(obj.get("history")),
                _clean_transcript(obj.get("transcript")), meta)
    except Exception:
        return [], [], {}


def clear_memory(ws):
    """Delete the stored conversation. Returns error string or ''."""
    try:
        p = memory_path(ws)
        if p.is_file():
            p.unlink()
        enc = p.with_name(MEMORY_ENC_FILE)
        if enc.is_file():
            enc.unlink()
        return ""
    except OSError as e:
        return str(e)


def has_memory(ws):
    try:
        p = memory_path(ws)
        return p.is_file() or p.with_name(MEMORY_ENC_FILE).is_file()
    except Exception:
        return False
