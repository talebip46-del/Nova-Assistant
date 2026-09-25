#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - per-module brain assignment (v6.0)
#
#  The user's core ask: "برای هر بخش یک مدل لوکال جدا و یا حتی مدل
#  ابری جدا" - a SEPARATE local or cloud brain per section.
#
#  Storage: <ws>/.nova/modules.json
#      {"modules": {"voice": {"backend": "openai_compat",
#                             "url": "http://127.0.0.1:8080/v1",
#                             "model": "tts-1", "voice": "en-kokoro",
#                             "key": ""}}}
#
#  Rules that keep this safe:
#    - unknown module ids / backend names are rejected (never stored)
#    - a module's default config wins when nothing is saved
#    - junk in the file degrades to defaults - a corrupt config must
#      never break a module (or the whole app) at startup
# =====================================================================
import json
import re
import threading
from pathlib import Path

from nova_modules import MODULES, ModuleError, spec

try:
    import nova_atomic as natom
except Exception:
    natom = None

_LOCK = threading.Lock()

_URL_RE = re.compile(r"^https?://[A-Za-z0-9._~:/\-\[\]@!$&'()*+,;=%]+$")
# every backend name any module accepts (validated against the module spec)
_ALL_BACKENDS = {"offline", "ollama", "file", "platform", "cloud",
                 "openai_compat", "a1111", "comfyui", "xtts", "coqui",
                 "bark", "piper"}
# string fields we persist, with sane caps
_FIELDS = {
    "model": 200, "url": 300, "voice": 120, "key": 400, "speaker": 200,
    "path": 600,          # piper model file / engine binary path
}


def _path(ws):
    return Path(ws) / ".nova" / "modules.json"


def _clean_str(raw, cap):
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s or len(s) > cap or "\n" in s or "\r" in s or "\x00" in s:
        return ""
    return s


def _clean_url(raw):
    s = _clean_str(raw, 300)
    if not s or not _URL_RE.match(s):
        return ""
    return s.rstrip("/")


def load_all(ws):
    """The whole saved assignment map (validated). Never raises."""
    try:
        data = json.loads(_path(ws).read_text(encoding="utf-8"))
    except Exception:
        return {}
    mods = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(mods, dict):
        return {}
    out = {}
    for mid, cfg in mods.items():
        sp = spec(mid)
        if sp is None or not isinstance(cfg, dict):
            continue
        clean = {}
        backend = _clean_str(cfg.get("backend"), 40).lower()
        if backend in _ALL_BACKENDS and backend in sp["backends"]:
            clean["backend"] = backend
        for field, cap in _FIELDS.items():
            if field in cfg and cfg[field] not in (None, ""):
                val = _clean_url(cfg[field]) if field == "url" \
                    else _clean_str(cfg[field], cap)
                if val:
                    clean[field] = val
        if clean.get("backend"):
            out[mid] = clean
    return out


def _validate_file_brain(ws, module_id, model):
    """A 'file' backend needs a REAL model file, and the file's CATEGORY
    folder must match the module (local/photo models stay in Nova Photo,
    local/voice models in Nova Voice... general models work everywhere).
    Returns the normalized 'file:<name>' id. Raises ModuleError."""
    import nova_localmodels as lmodels
    want = str(model or "").strip()
    if want.startswith(lmodels.LOCAL_PREFIX):
        want = want[len(lmodels.LOCAL_PREFIX):]
    want = want.strip().strip("\"'").lower()
    if not want:
        raise ModuleError("pick a model file (file:<name> from /model)")
    entry = None
    try:
        for e in lmodels.scan_dirs(lmodels.model_dirs(ws)):
            fname = Path(e.get("file", "")).name.lower()
            if e.get("name", "").lower() == want or \
                    fname in (want, want + ".gguf", want + ".onnx",
                              want + ".safetensors"):
                entry = e
                break
    except Exception:
        entry = None
    if entry is None:
        raise ModuleError("no model file '%s' in the model folders "
                          "(local/, local/code, local/voice, local/photo...)" % want)
    if not entry.get("runnable"):
        raise ModuleError("'%s' is not a runnable LLM brain (%s)"
                          % (entry.get("name"),
                             entry.get("note") or entry.get("format")))
    allowed = lmodels.MODULE_CATS.get(str(module_id).strip(),
                                      (lmodels.GENERAL,))
    cat = entry.get("category", lmodels.GENERAL)
    if cat not in allowed:
        raise ModuleError(
            "'%s' sits in a %s folder - the %s module needs a model from "
            "%s (or a GENERAL model straight in local/)"
            % (entry.get("name"), cat, module_id,
               " / ".join(c for c in allowed if c != lmodels.GENERAL)
               or "local/"))
    return entry["id"]


def _validate_piper_voice(ws, model):
    """A piper 'model' is either a real filesystem PATH (kept as-is) or a
    voice NAME that must resolve to a .onnx in the model folders
    (local/voice...). Returns the normalized reference. Raises
    ModuleError for a bare name that matches nothing or an LLM file.
    v6.5: a 'file:'-prefixed reference is ALWAYS resolved through the
    model folders - 'file:/models/fa.onnx' used to pass validation
    verbatim and then fail at EVERY synthesis ('no voice model ... in
    the model folders'), because the synthesizer refuses refs with '/'.
    Contract mismatch is now caught at save time."""
    ref = str(model or "").strip()
    if not ref:
        return ref
    if not ref.startswith("file:") and \
            ("/" in ref or "\\" in ref or Path(ref).suffix in (".onnx", ".gguf")):
        # a path-like or extension-carrying reference - piper gets it verbatim
        return ref
    import nova_localmodels as lmodels
    want = ref[len(lmodels.LOCAL_PREFIX):].strip().strip("\"'").lower() \
        if ref.startswith(lmodels.LOCAL_PREFIX) else ref.lower()
    entry = None
    try:
        for e in lmodels.scan_dirs(lmodels.model_dirs(ws)):
            fname = Path(e.get("file", "")).name.lower()
            if e.get("name", "").lower() == want or \
                    fname in (want, want + ".onnx", want + ".gguf"):
                entry = e
                break
    except Exception:
        entry = None
    if entry is None:
        raise ModuleError("no voice model '%s' in the model folders - "
                          "drop the .onnx into local/voice" % want)
    if entry.get("format") != "onnx":
        raise ModuleError("'%s' is an LLM brain (%s) - piper needs a voice "
                          "model (.onnx) from local/voice"
                          % (entry.get("name"), entry.get("format")))
    return entry["id"]


def save_module(ws, module_id, cfg):
    """Validate + persist ONE module's assignment. Returns the saved
    config. Raises ModuleError on a bad module id / backend / payload."""
    sp = spec(module_id)
    if sp is None or not sp.get("assignable"):
        raise ModuleError("module '%s' does not accept an assignment" % module_id)
    if not isinstance(cfg, dict):
        raise ModuleError("assignment must be a JSON object")
    backend = _clean_str(cfg.get("backend"), 40).lower()
    if backend not in sp["backends"]:
        raise ModuleError("backend '%s' is not valid for %s (allowed: %s)"
                          % (backend or "?", module_id, ", ".join(sp["backends"])))
    clean = {"backend": backend}
    for field, cap in _FIELDS.items():
        if field in cfg and cfg[field] not in (None, ""):
            val = _clean_url(cfg[field]) if field == "url" \
                else _clean_str(cfg[field], cap)
            if val:
                clean[field] = val
    # backend-specific sanity BEFORE the file is touched
    if backend in ("platform", "openai_compat") and not clean.get("url"):
        raise ModuleError("this backend needs a server URL (e.g. http://127.0.0.1:8080/v1)")
    if backend == "a1111" and not clean.get("url"):
        clean["url"] = "http://127.0.0.1:7860"
    if backend == "comfyui" and not clean.get("url"):
        clean["url"] = "http://127.0.0.1:8188"
    if backend == "xtts" and not clean.get("url"):
        clean["url"] = "http://127.0.0.1:8020"
    if backend in ("coqui", "bark") and not clean.get("url"):
        clean["url"] = ("http://127.0.0.1:5002" if backend == "coqui"
                        else "http://127.0.0.1:8010")
    if backend == "ollama" and not clean.get("model"):
        raise ModuleError("pick a model for the ollama backend")
    if backend == "cloud" and not clean.get("model"):
        raise ModuleError("pick a model for the cloud backend")
    if backend == "file":
        clean["model"] = _validate_file_brain(ws, sp["id"],
                                              clean.get("model", ""))
    if backend == "piper" and not clean.get("model"):
        # v6.5: 'path' alone used to save green but tts_piper unconditionally
        # raises 'piper needs a voice model path' - same contract at both
        # ends now (path = the piper BINARY, model = the voice).
        raise ModuleError("piper needs a voice model (file:<name> from "
                          "local/voice, or a model path) - the 'path' field "
                          "is only the piper binary")
    if backend == "piper" and clean.get("model"):
        clean["model"] = _validate_piper_voice(ws, clean["model"])
    # v6.7: the thread lock cannot span processes (REPL + web both save
    # assignments) - the read-modify-write gets an advisory file lock too.
    with _LOCK:
        fl = natom.file_lock(_path(ws).parent / "assign.lock", timeout=5.0) \
            if natom is not None else _null()
        with fl:
            mods = load_all(ws)
            mods[sp["id"]] = clean
            data = {"modules": mods}
            p = _path(ws)
            p.parent.mkdir(parents=True, exist_ok=True)
            # v8.7: unique-scratch atomic write (the fixed '.json.part'
            # name collided across processes exactly like the v6.7
            # secrets-file bug - a torn modules.json silently reset
            # EVERY module assignment to its default).
            if natom is not None:
                err = natom.write_text_atomic(
                    p, json.dumps(data, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                if err:
                    raise OSError(err)
            else:                       # natom missing - best effort
                tmp = p.with_suffix(".json.part")
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                               encoding="utf-8")
                tmp.replace(p)
    return clean


def clear_module(ws, module_id):
    """Back to the built-in default. Returns True when something was removed.
    v6.2.1 fix: wrote modules.json directly (no tmp+replace) - a crash
    mid-write wiped ALL assignments; inconsistent with save_module."""
    with _LOCK:
        fl = natom.file_lock(_path(ws).parent / "assign.lock", timeout=5.0) \
            if natom is not None else _null()
        with fl:
            mods = load_all(ws)
            if module_id in mods:
                del mods[module_id]
                p = _path(ws)
                p.parent.mkdir(parents=True, exist_ok=True)
                # v8.7: same unique-scratch atomic write as save_module.
                blob = json.dumps({"modules": mods}, ensure_ascii=False,
                                  indent=1)
                if natom is not None:
                    err = natom.write_text_atomic(p, blob, encoding="utf-8")
                    if err:
                        raise OSError(err)
                else:                   # natom missing - best effort
                    tmp = p.with_suffix(".json.part")
                    tmp.write_text(blob, encoding="utf-8")
                    tmp.replace(p)
                return True
    return False


class _null:
    """Context-manager no-op (the file lock is best-effort)."""
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def resolve(ws, module_id):
    """Saved assignment merged over the module default -> clean dict with
    AT LEAST a 'backend' key. Never raises; unknown ids give {}."""
    sp = spec(module_id)
    if sp is None:
        return {}
    base = dict(sp.get("default") or {})
    saved = load_all(ws).get(sp["id"], {})
    base.update({k: v for k, v in saved.items() if v})
    return base


def assignments_view(ws):
    """For /api/modules: every assignable module + its resolved config."""
    out = []
    for m in MODULES:
        entry = {"id": m["id"], "title": m["title"], "fa": m["fa"],
                 "icon": m["icon"], "desc": m["desc"],
                 "backends": m["backends"], "assignable": m["assignable"]}
        if m["assignable"]:
            entry["cfg"] = resolve(ws, m["id"])
        out.append(entry)
    return out
