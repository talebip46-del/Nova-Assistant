#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - the VISION LAYER (v8.6 "bug net + vision")
#
#  The user's law: some local models SEE (llava, qwen-vl, gemma3,
#  moondream, ...) and some are text-only - Nova must KNOW, 100%
#  automatically, whether the local brain it is using can look at a
#  photo. And when a photo is SELECTED or DOWNLOADED from the
#  internet, the local AI itself must APPROVE it.
#
#  Detection ladder (offline-first, every step cached per model):
#    1. Ollama /api/show  - "capabilities" contains "vision" (newer
#       Ollama), or details.families contains a CLIP projector, or
#       model_info carries a *.projector* key. A successful show is
#       THE TRUTH: a text-only model is reported as text-only.
#    2. GGUF header scan  - the key names of a local .gguf file are
#       scanned for clip/vision/projector/mmproj markers (the llama.cpp
#       multimodal world), plus an mmproj sidecar next to the model.
#    3. Name regex        - the honest last resort when nothing else
#       can answer (Ollama asleep, unknown host): llava / vision /
#       qwen*v / gemma3 / pixtral / minicpm-v / internvl / ...
#
#  The APPROVAL policy lives in .nova/vision.json:
#    approve (true)  - the local AI must give the final verdict on
#                      every internet photo (search fill, /img, /imgdl)
#    strict (false)  - when the active local model CANNOT see, refuse
#                      AI photo selection entirely (placeholders only)
#                      instead of falling back to heuristics.
#
#  Fail-soft everywhere: Ollama down, a weird gguf, a broken settings
#  file - the layer degrades to the next rung and never breaks a turn.
#  Correctness NEVER depends on the internet (Ollama is localhost; the
#  gguf scan is a file read). NOVA_VISION_SHOW=0 skips the /api/show
#  call (name regex only - the test/air-gapped escape hatch).
#
#  Pure standard library (Pillow optional), fail-soft everywhere.
# =====================================================================
import json
import os
import re
import struct
import time
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:                       # pragma: no cover - fail-soft
    natom = None

# ----------------------------------------------------------- constants
VISION_FILE = "vision.json"
DEFAULTS = {
    "approve": True,       # the local AI must approve internet photos
    "strict": False,       # no local vision -> no AI photo selection
}
MAX_SETTINGS_BYTES = 4_000
VISION_TTL = 600.0              # detection cache per model (seconds)
SHOW_TIMEOUT = 4.0              # /api/show is localhost - be quick
SHOW_READ_CAP = 2_000_000
GGUF_READ_CAP = 8_000_000
GGUF_MAX_KVS = 4_096

# the honest last-resort name heuristic (the same families nova.py has
# used since v8.1 - now only a FALLBACK, never the primary signal)
# v8.7: "vision" matches on a word boundary - the bare substring used
# to ride along inside unrelated names ("supervision", "visiondata").
NAME_RE = re.compile(
    # v8.10.1 fix: qwen[0-9.]*v[lL] allowed no SEPARATOR, so the canonical
    # HF/Ollama spellings 'qwen2-vl' / 'qwen2.5-vl' never matched (the
    # sibling minicpm.?v / glm-4.?v patterns allow one) - the fallback rung
    # declared a vision model text-only and strict mode refused photos.
    r"llava|bakllava|moondream|minicpm.?v|gemma3|pixtral|glm-4.?v|"
    r"\bvision\b|internvl|qwen[\w.]*-?v[lL]|(^|[-._])vl([-._]|$)",
    re.IGNORECASE)

# gguf header key markers that imply a vision/multimodal projector
_GGUF_MARKERS = ("clip", "vision", "projector", "mmproj", "mllm")

# detection cache: (kind, name, path) -> (ts, result)
_CACHE = {}

SHOW_CAPABILITIES_OK = ("vision",)


def name_looks_vision(name):
    """The name-regex rung (also reused as a quick public check)."""
    try:
        return bool(NAME_RE.search(str(name or "")))
    except Exception:
        return False


# ------------------------------------------------------------- settings
def settings_path(ws):
    return Path(ws) / ".nova" / VISION_FILE


def _valid_fields(obj):
    """ONLY the valid keys survive - a hand-edited file can never
    poison the stored settings."""
    out = {}
    if not isinstance(obj, dict):
        return out
    for key in ("approve", "strict"):
        if isinstance(obj.get(key), bool):
            out[key] = obj[key]
    return out


def load_settings(ws):
    d = dict(DEFAULTS)
    d["custom"] = False
    try:
        p = settings_path(ws)
        if not p.is_file() or p.stat().st_size > MAX_SETTINGS_BYTES:
            return d
        saved = _valid_fields(
            json.loads(p.read_text(encoding="utf-8",
                                    errors="replace")))
        d.update(saved)
        # v8.10.1 fix: custom means the user actually SAVED valid fields -
        # a foreign / hand-edited file with zero valid keys used to claim
        # custom (the ctxengine/guardian v8.7 law, mirrored here).
        d["custom"] = bool(saved)
    except Exception:
        pass
    return d


def save_settings(ws, updates):
    """Merge validated updates (atomic write). Returns '' or an error."""
    try:
        cur = load_settings(ws)
        cur.update(_valid_fields(updates if isinstance(updates, dict)
                                 else {}))
        cur.pop("custom", None)
        p = settings_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(cur, indent=2, ensure_ascii=False) + "\n"
        if natom is not None:
            return natom.write_text_atomic(p, blob)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(blob, encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)


def reset_settings(ws):
    try:
        p = settings_path(ws)
        if p.is_file():
            p.unlink()
        return ""
    except OSError as e:
        return str(e)


def enabled(cfg, key):
    if not isinstance(cfg, dict):
        return DEFAULTS.get(key, False)
    return bool(cfg.get(key, DEFAULTS.get(key, False)))


# ------------------------------------------------------------ ollama show
def _show_default(base, model):
    """POST <base>/api/show - the REAL capability source. Returns the
    parsed dict or None on ANY problem (fail-soft, fast - it is a
    localhost call)."""
    base = str(base or "http://localhost:11434").rstrip("/")
    try:
        import urllib.request
        req = urllib.request.Request(
            base + "/api/show",
            data=json.dumps({"model": str(model or "")}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=SHOW_TIMEOUT) as resp:
            data = json.loads(resp.read(SHOW_READ_CAP)
                              .decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _parse_show(data):
    """(vision, via, detail) from an /api/show payload. A SUCCESSFUL
    show is authoritative: no vision marker anywhere = text-only."""
    if not isinstance(data, dict):
        return None
    caps = data.get("capabilities") or []
    if isinstance(caps, list):
        for cv in caps:
            if str(cv).strip().lower() in SHOW_CAPABILITIES_OK:
                return (True, "ollama-show",
                        "capabilities reports 'vision'")
    details = data.get("details") or {}
    fams = details.get("families") if isinstance(details, dict) else None
    if isinstance(fams, list):
        for f in fams:
            lf = str(f).lower()
            if "clip" in lf or "vision" in lf:
                return (True, "ollama-families",
                        "families carries the CLIP projector (%s)" % f)
    info = data.get("model_info")
    if isinstance(info, dict):
        for k in info:
            if ".projector" in str(k).lower():
                return (True, "ollama-projector",
                        "model_info key %s" % k)
    if caps or fams or info:
        return (False, "ollama-show",
                "model reports no vision capability")
    return None                     # shape unknown - keep looking


# ---------------------------------------------------------------- gguf
def _gguf_vision_keys(path):
    """Scan the KEY NAMES of a .gguf header for vision/multimodal
    markers. Returns True/False/None (None = unreadable). Pure file
    read, bounded, offline."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, "rb") as fh:
            head = fh.read(GGUF_READ_CAP)
        if len(head) < 24 or head[:4] != b"GGUF":
            return None
        version, = struct.unpack_from("<I", head, 4)
        if version < 2:
            return None
        _tensor_count, = struct.unpack_from("<Q", head, 8)
        kv_count, = struct.unpack_from("<Q", head, 16)
        pos = 24
        n = min(int(kv_count), GGUF_MAX_KVS)

        def _need(m):
            nonlocal pos
            if pos + m > len(head):
                raise EOFError
            pos += m

        def _u32():
            v, = struct.unpack_from("<I", head, pos)
            _need(4)
            return v

        def _u64():
            v, = struct.unpack_from("<Q", head, pos)
            _need(8)
            return v

        def _skip_value(vtype):
            # scalar sizes (GGUF metadata value types 0..12)
            if vtype <= 7:
                _need(1 if vtype in (0, 1, 7) else
                      (2 if vtype in (2, 3) else 4))
            elif vtype == 8:                       # string
                ln = _u64()
                _need(ln)
            elif vtype == 9:                       # array
                et = _u32()
                cnt = _u64()
                if cnt > GGUF_MAX_KVS * 1024:
                    raise EOFError                 # corrupt - bail
                for _i in range(int(cnt)):
                    _skip_value(et)
            elif vtype in (10, 11):
                _need(8)
            elif vtype == 12:
                _need(8)
            else:
                raise EOFError                     # unknown type - bail

        for _i in range(n):
            klen = _u64()
            if klen > 4096:
                raise EOFError
            _need(klen)
            key = head[pos - klen:pos].decode("utf-8", "replace").lower()
            if any(m in key for m in _GGUF_MARKERS):
                return True
            _skip_value(_u32())
        return False
    except (EOFError, OSError, struct.error, Exception):
        return None


def _mmproj_near(path):
    """An mmproj*.gguf sidecar next to the model file = the projector
    weights ship separately (llava-style splits)."""
    try:
        p = Path(path)
        if not p.is_file():
            return False
        for sib in p.parent.glob("*.gguf"):
            if "mmproj" in sib.name.lower():
                return True
        return False
    except Exception:
        return False


# ------------------------------------------------------------- detection
def _detect_impl(kind, name, base, path, show_fn):
    low_name = str(name or "").lower().replace("file:", "")
    path = Path(path) if path else None

    # ---- rung 2a: gguf file on disk (file: brains) ------------------
    if path is not None and path.is_file():
        gg = _gguf_vision_keys(path)
        if gg is True:
            return {"vision": True, "via": "gguf-keys",
                    "detail": "vision keys in the gguf header"}
        if _mmproj_near(path):
            return {"vision": True, "via": "mmproj",
                    "detail": "mmproj sidecar found next to the model"}
        if gg is False:
            return {"vision": False, "via": "gguf",
                    "detail": "no vision keys in the gguf header"}
        # unreadable header -> keep looking

    # ---- rung 1: the REAL answer from ollama ------------------------
    if kind == "ollama" and name:
        # an INJECTED show_fn is a controlled probe (tests, callers with
        # their own transport) - only the DEFAULT /api/show call obeys
        # the NOVA_VISION_SHOW=0 air-gapped escape hatch.
        if show_fn is not None or os.environ.get("NOVA_VISION_SHOW",
                                                 "") != "0":
            fn = show_fn or _show_default
            data = fn(base or "http://localhost:11434", name)
            parsed = _parse_show(data)
            if parsed is not None:
                return {"vision": parsed[0], "via": parsed[1],
                        "detail": parsed[2]}
        # show skipped/unreachable -> name fallback (honest about it)
        if NAME_RE.search(low_name):
            return {"vision": True, "via": "name",
                    "detail": "model name hints at vision (ollama "
                              "details unreachable)"}
        return {"vision": False, "via": "name",
                "detail": "name gives no vision hint and ollama "
                          "details are unreachable"}

    # ---- rung 2b: llama.cpp runtime (no --mmproj support in nova) ---
    if kind == "llamacpp":
        if path is not None and _mmproj_near(path):
            return {"vision": True, "via": "mmproj",
                    "detail": "mmproj sidecar present (still needs "
                              "--mmproj on the server)"}
        return {"vision": False, "via": "llamacpp",
                "detail": "llama-server runs without --mmproj - "
                          "text-only in practice"}

    # ---- rung 3: the honest last resort -----------------------------
    if NAME_RE.search(low_name):
        return {"vision": True, "via": "name",
                "detail": "model name hints at vision"}
    return {"vision": False, "via": "name",
            "detail": "model name gives no vision hint"}


def detect(kind="", name="", base=None, path=None, show_fn=None,
           force=False):
    """THE 100% AUTOMATIC DETECTION. kind: ollama | llamacpp | file | ?
    name: the model name (file: prefix tolerated); path: the gguf file
    for file: brains. Returns {"vision": bool, "via": str,
    "detail": str} - cached per model, NEVER raises."""
    try:
        # v8.7: the cache key must include the SERVER BASE - the same
        # model name on a different host (or NOVA_OLLAMA_URL) can have a
        # different answer, and the 600 s TTL used to hand back the
        # wrong host's verdict to the strict gate.
        key = (str(kind or ""), str(name or ""), str(path or ""),
               str(base or ""))
        now = time.time()
        hit = _CACHE.get(key)
        if hit is not None and not force and now - hit[0] < VISION_TTL:
            return dict(hit[1])
        res = _detect_impl(kind, name, base, path, show_fn)
        res["model"] = str(name or "")
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = (now, dict(res))
        return res
    except Exception:
        return {"vision": False, "via": "error",
                "detail": "detection failed (fail-soft)", "model": name}


def clear_cache():
    """A model switch / ollama pull may change reality - the callers
    can force a fresh look."""
    _CACHE.clear()


def state_payload(vision_result, settings, model="", backend=""):
    """The /api/info payload block (fail-soft, plain data)."""
    vr = vision_result if isinstance(vision_result, dict) else {}
    st = settings if isinstance(settings, dict) else {}
    return {
        "model": str(model or vr.get("model") or ""),
        "backend": str(backend or ""),
        "vision": bool(vr.get("vision")),
        "via": str(vr.get("via") or ""),
        "detail": str(vr.get("detail") or ""),
        "approve": bool(st.get("approve", DEFAULTS["approve"])),
        "strict": bool(st.get("strict", DEFAULTS["strict"])),
        "custom": bool(st.get("custom")),
        "show_env_off": os.environ.get("NOVA_VISION_SHOW", "") == "0",
    }
