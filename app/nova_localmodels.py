#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - LOCAL MODEL FILES discovery & runtime (v6.1)
#
#  Two ways to give Nova a local brain (both selectable inside the app):
#    1. models pulled into Ollama        -> nova_models.py (/api/tags)
#    2. model FILES you downloaded and
#       dropped into a models folder     -> THIS module
#
#  Supported file format: GGUF (the llama.cpp / Ollama weight format).
#  *.safetensors files are LISTED too, but honestly marked "not
#  runnable - convert to GGUF first" instead of failing at chat time.
#  *.onnx files are LISTED as voice models (Piper) - Nova Voice uses
#  them directly, they are never treated as LLM brains.
#
#  Where Nova looks for model files (first hit wins, all are scanned):
#    - NOVA_MODELS_DIR env var (os.pathsep-separated list of folders)
#    - ~/.nova/models                      (the user-wide folder)
#    - <app dir>/local                     (the app's own local/ folder)
#    - <workspace>/.nova/models            (this project only)
#
#  CATEGORY FOLDERS (v6.1) - each root above may hold category
#  sub-folders; a model's category decides WHICH modules may use it:
#
#      <root>/code/    -> coding LLMs            (Nova Code, Flow)
#      <root>/voice/   -> voice models (.onnx,   (Nova Voice)
#                       coqui/bark checkpoints)
#      <root>/photo/   -> image models           (Nova Photo)
#                       (.safetensors checkpoints
#                        for A1111/ComfyUI)
#      <root>/         -> GENERAL models - usable by EVERY module
#      (any other sub-folder is general too - never hides models)
#
#  Nova Flow sees ALL folders (it is the integration hub). Ollama
#  models need no folder at all - they are read from the Ollama
#  library itself and every module can use them.
#
#  How a .gguf file is RUN (resolved lazily, one-time, with caching):
#    a. already imported into Ollama (cache)      -> chat via Ollama
#    b. Ollama reachable                          -> `ollama create`
#       imports the file once (GGUF blobs are copied, then reused)
#    c. llama.cpp 'llama-server' on PATH          -> spawned on a free
#       localhost port, chatted with over its OpenAI-compatible API
#    d. none of the above                         -> a clean error
#
#  Pure standard library. The GGUF header parser reads ONLY the first
#  few MB (metadata block) - never the tensors - with hard caps on
#  every count/length so a truncated or hostile file cannot make Nova
#  allocate gigabytes or hang. Every function is testable offline.
# =====================================================================
import hashlib
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

LOCAL_PREFIX = "file:"          # session/profile id prefix: "file:<name>"

# ------------------------------------------------------------- categories
# A model's category comes from the sub-folder of a models root it sits
# in (code/voice/photo - anything else is "general"). general models
# are usable by EVERY module; a category folder narrows the audience.
# Aliases keep it forgiving: local/image, local/tts, local/coder ...
CATEGORY_ALIASES = {
    "code": ("code", "coding", "coder", "llm", "llms"),
    "voice": ("voice", "voices", "tts", "stt", "speech", "audio"),
    "photo": ("photo", "photos", "image", "images", "img", "draw",
              "sd", "diffusion", "art"),
}
ALIAS_TO_CATEGORY = {}
for _cat, _names in CATEGORY_ALIASES.items():
    for _n in _names:
        ALIAS_TO_CATEGORY[_n] = _cat
CATEGORY_DIRS = ("code", "voice", "photo")   # folders prepare_local_dirs() makes
GENERAL = "general"

# which categories each module may pick from ("flow" sees everything
# because it is the hub; ollama models are not affected by this at all)
MODULE_CATS = {
    "code": ("code", GENERAL),
    "assistant": (GENERAL, "code"),      # Flow's LLM brain: general or coding
    "voice": ("voice", GENERAL),
    "photo": ("photo", GENERAL),
    "pixel": (GENERAL,),                 # offline engine; prompt-writing only
    "knowledge": (GENERAL,),
    "flow": ("code", "voice", "photo", GENERAL),   # sees ALL folders
}


def category_for(rel_parts):
    """Path parts UNDER a models root -> category name.
    ['code', 'qwen.gguf'] -> 'code';  ['my-stuff'] -> 'general'.
    Pure and forgiving (unknown/junk -> general, never hides models)."""
    try:
        first = str(rel_parts[0]).strip().lower()
    except (IndexError, TypeError):
        return GENERAL
    return ALIAS_TO_CATEGORY.get(first, GENERAL)


def allowed_for_module(entries, module_id):
    """Filter scan entries down to what ONE module may use.
    Flow sees everything; unknown module ids get general-only."""
    cats = MODULE_CATS.get(str(module_id or "").strip(), (GENERAL,))
    return [e for e in (entries or []) if e.get("category", GENERAL) in cats]


def categories_of(entries):
    """entries -> {category: [entry, ...]} in stable CATEGORY_DIRS +
    general order. Missing categories still get an (empty) key."""
    out = {c: [] for c in (GENERAL,) + CATEGORY_DIRS}
    for e in (entries or []):
        cat = e.get("category", GENERAL)
        out.setdefault(cat, []).append(e)
    return out


def app_local_dir():
    """The app's own models folder: <folder of this file>/local.
    This is the 'local/' the docs talk about - drop general models
    right into it, categorized ones into local/code, local/voice,
    local/photo.

    Packaged-exe note: when frozen (PyInstaller/similar), __file__
    resolves inside the temporary extraction folder (sys._MEIPASS),
    which is deleted after the process exits - anything anchored
    there would vanish every run instead of sitting next to the .exe
    where the user can actually find it and drop model files in. So
    when frozen we anchor on the real executable's own folder instead."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / "local"


def prepare_local_dirs():
    """Create <app>/local/{code,voice,photo} (+ a tiny README in each)
    so the category layout is visible right after install. Best-effort:
    a read-only app dir must never break startup. Returns the list of
    directories that exist after the attempt."""
    base = app_local_dir()
    made = []
    try:
        base.mkdir(parents=True, exist_ok=True)
        root_readme = base / "README.txt"
        if not root_readme.exists():
            root_readme.write_text(
                "LOCAL MODELS - the categorized layout (v6.1)\n"
                "============================================\n"
                "Drop model FILES here:\n"
                "  local/*.gguf            -> GENERAL models (every module)\n"
                "  local/code/*.gguf       -> Nova Code / Flow only\n"
                "  local/voice/*.onnx      -> Nova Voice (Piper voices)\n"
                "  local/photo/*.safetensors -> Nova Photo (A1111/ComfyUI)\n"
                "Ollama models need NO folder - they are read from Ollama.\n"
                "Nova Flow sees ALL folders.\n",
                encoding="utf-8")
        made.append(base)
    except OSError:
        return []
    hints = {
        "code": "Coding LLM models (.gguf) - used by Nova Code and Flow.\n",
        "voice": "Voice models - Piper .onnx voices (+ their .onnx.json).\n",
        "photo": "Image models (.safetensors checkpoints) for A1111/ComfyUI.\n",
    }
    for cat in CATEGORY_DIRS:
        d = base / cat
        try:
            d.mkdir(exist_ok=True)
            readme = d / "README.txt"
            if not readme.exists():
                readme.write_text(hints[cat] +
                                  "General models (usable by every module) go "
                                  "one level up, directly into local/.\n",
                                  encoding="utf-8")
            made.append(d)
        except OSError:
            continue
    return made

class LocalModelError(Exception):
    """A clean, user-readable local-model problem (bad file, no runtime,
    server did not start...). Never a raw traceback."""

# --------------------------------------------------------------- GGUF parse
GGUF_MAGIC = b"GGUF"
# v6.2.1 fix: this struct was WRONG ("<IQ Q" = 20 bytes; the real header is
# magic(4s) + version(u32) + tensor count(u64) + kv count(u64) = 24 bytes)
# and unused anyway (the parser hardcodes the correct offsets). A wrong
# constant sitting in a module is a landmine for the next contributor.
GGUF_HEADER = struct.Struct("<4sIQQ")

# value-type -> struct size (0..12). Arrays/strings handled separately.
_GGUF_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1,
               10: 8, 11: 8, 12: 8}
_GGUF_FMT = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
             6: "<f", 10: "<Q", 11: "<q", 12: "<d"}

MAX_KV_COUNT = 4096          # sane cap - real files have a few dozen
MAX_STRING = 1 << 20         # 1 MiB is far beyond any metadata string
MAX_ARRAY = 1 << 16          # numeric arrays worth skipping, not parsing
READ_CAP = 8 * 1024 * 1024   # never read more of the file than this

# general.file_type enum -> quant label (llama.cpp LLAMA_FTYPE_*; a short
# map is enough - unknown codes degrade to '').
FILE_TYPE_QUANT = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0",
    9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L",
    14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
    19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS",
    24: "IQ1_S", 25: "IQ4_NL", 26: "IQ4_XS", 27: "IQ3_S", 28: "IQ2_S",
    29: "IQ4_XS", 30: "IQ3_M", 31: "IQ2_M", 32: "IQ1_M", 36: "TQ1_0",
    37: "TQ2_0",
}

# metadata keys Nova shows in the /model table
_WANTED_KEYS = ("general.name", "general.architecture", "general.size_label",
                "general.file_type", "general.quantization_version")


def _kv_value(buf, off, vtype):
    """Read one GGUF metadata value at `off`.
    Returns (value_or_None, new_off, stop_flag). `stop_flag` means 'the
    buffer ended / a field was too big - stop parsing the rest'."""
    n = len(buf)
    if vtype == 8:                                   # string
        if off + 8 > n:
            return None, off, True
        (slen,) = struct.unpack_from("<Q", buf, off)
        off += 8
        if slen > MAX_STRING or off + slen > n:
            return None, off, True
        return buf[off:off + slen].decode("utf-8", "replace"), off + slen, False
    if vtype == 9:                                   # array
        if off + 12 > n:
            return None, off, True
        etype, count = struct.unpack_from("<IQ", buf, off)
        off += 12
        if etype == 8:                               # array of strings:
            if count > MAX_ARRAY:                    # parse with caps
                return None, off, True
            vals = []
            for _ in range(count):
                s, off, stop = _kv_value(buf, off, 8)
                if stop:
                    return None, off, True
                vals.append(s)
            return vals, off, False
        if etype == 9:                               # array of arrays: nope
            return None, off, True
        esz = _GGUF_SIZES.get(etype)
        if esz is None or count > (MAX_ARRAY * 64):
            return None, off, True
        off += esz * count
        if off > n:
            return None, n, True
        return None, off, False                      # skipped, keep going
    size = _GGUF_SIZES.get(vtype)
    if size is None or off + size > n:
        return None, off, True
    if vtype == 7:                                   # bool
        return bool(buf[off]), off + size, False
    (val,) = struct.unpack_from(_GGUF_FMT[vtype], buf, off)
    return val, off + size, False


def _parse_kvs(buf, kv_count):
    """Metadata block -> (dict of the keys Nova cares about, complete).
    v6.8.1: returns whether parsing ended CLEANLY - the old silent
    `break` on a short buffer made the caller's grow-the-cap retry loop
    dead code (it always believed the first 256 KB were enough), so a
    GGUF with >256 KB of metadata before general.name yielded empty
    name/arch/quant. Bounded as before."""
    off, out = 24, {}
    complete = True
    for _ in range(min(int(kv_count), MAX_KV_COUNT)):
        if off + 8 > len(buf):
            complete = False
            break
        (klen,) = struct.unpack_from("<Q", buf, off)
        off += 8
        if klen > 4096 or off + klen > len(buf):
            complete = False
            break
        key = buf[off:off + klen].decode("utf-8", "replace")
        off += klen
        if off + 4 > len(buf):
            complete = False
            break
        (vtype,) = struct.unpack_from("<I", buf, off)
        off += 4
        val, off, stop = _kv_value(buf, off, vtype)
        if stop:
            complete = False
            break
        if val is not None and (key in _WANTED_KEYS
                                or key.endswith(".context_length")):
            out[key] = val
    return out, complete


def parse_gguf_header(path, read_cap=READ_CAP):
    """Read ONLY the metadata block of a .gguf file.
    Returns a dict: {version, name, arch, quant, ctx, file_type,
    size_label, error} - 'error' is '' on success, a short code
    otherwise. NEVER raises for a bad file (only for a truly insane
    path) - the /model table must stay alive for the other entries."""
    out = {"version": 0, "name": "", "arch": "", "quant": "", "ctx": 0,
           "file_type": -1, "size_label": "", "error": ""}
    try:
        p = Path(path)
        size = p.stat().st_size
    except OSError as e:
        out["error"] = f"unreadable ({e})"
        return out
    # v6.7: read INCREMENTALLY - the metadata block usually ends within
    # the first KBs, but the old code read the full 8MB cap for EVERY
    # file (a 200-file /model scan cost up to ~1.6GB of I/O on the weak
    # hardware Nova targets). Start small, grow only on truncation.
    for cap in (262_144, 1_048_576, read_cap):
        try:
            with open(p, "rb") as fh:
                buf = fh.read(min(size, cap))
        except OSError as e:
            out["error"] = f"unreadable ({e})"
            return out
        if len(buf) < 12 or buf[:4] != GGUF_MAGIC:
            out["error"] = "not_gguf"
            return out
        (version,) = struct.unpack_from("<I", buf, 4)
        out["version"] = version
        if version not in (2, 3):
            out["error"] = "gguf_v1_or_unknown"     # v1 had u32 counts - skip
            return out
        try:
            (_tensors, kv_count) = struct.unpack_from("<QQ", buf, 8)
            kvs, kvs_complete = _parse_kvs(buf, kv_count)
            if not kvs_complete and cap < read_cap and cap < size:
                continue                # v6.8.1: grow the cap and retry
            break                       # complete (or everything read)
        except (struct.error, ValueError):
            if cap >= read_cap or cap >= size:
                out["error"] = "truncated_header"
                return out
            continue                    # metadata bigger than this cap
    else:
        out["error"] = "truncated_header"
        return out
    out["name"] = str(kvs.get("general.name", "") or "")[:80]
    out["arch"] = str(kvs.get("general.architecture", "") or "")[:40]
    out["size_label"] = str(kvs.get("general.size_label", "") or "")[:24]
    ft = kvs.get("general.file_type", -1)
    out["file_type"] = int(ft) if isinstance(ft, int) else -1
    out["quant"] = FILE_TYPE_QUANT.get(out["file_type"], "")
    for k, v in kvs.items():
        if k.endswith(".context_length") and isinstance(v, int) and v > 0:
            out["ctx"] = v
            break
    return out


# --------------------------------------------------------------- model dirs
SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".nova", ".venv",
                  "venv", ".nova_backups", ".trash"}
SHARD_RE = re.compile(r"-(\d{1,5})-of-(\d{1,5})(?:\.gguf)?$", re.IGNORECASE)
MAX_ENTRIES = 200
MAX_WALK_DEPTH = 4
MIN_MODEL_BYTES = 1024      # smaller 'models' are junk/test files


def model_dirs(ws=None):
    """Where model FILES live: [(label, Path, exists)]. Deduplicated by
    resolved path. NOVA_MODELS_DIR may hold several os.pathsep-separated
    folders - a typo in one entry never removes the defaults.
    v6.1: the app's own local/ folder is always included."""
    out, seen = [], set()

    def add(label, raw):
        try:
            p = Path(str(raw)).expanduser()
        except Exception:
            return
        if not str(p).strip():
            return
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            return
        seen.add(key)
        out.append((label, p, p.is_dir()))

    env = os.environ.get("NOVA_MODELS_DIR", "")
    for part in env.split(os.pathsep):
        if part.strip():
            add("NOVA_MODELS_DIR", part.strip())
    add("local", app_local_dir())
    add("default", Path.home() / ".nova" / "models")
    if ws is not None:
        add("project", Path(ws) / ".nova" / "models")
    return out


def _clean_id_name(filename):
    """'qwen2.5-7b-q4_k_m-00001-of-00003.gguf' -> 'qwen2.5-7b-q4_k_m'
    (display + id name; multi-part groups keep ONE identity).
    Every model format loses its extension: 'v1-5.safetensors' ->
    'v1-5', 'fa_IR.onnx' -> 'fa_IR' - ids stay uniform for /model,
    the web UI and the assign layer."""
    base = filename
    low = base.lower()
    for ext in (".gguf", ".onnx", ".safetensors"):
        if low.endswith(ext):
            base = base[:-len(ext)]
            break
    base = SHARD_RE.sub("", base)
    base = base.strip().strip(".")
    base = re.sub(r"[\x00-\x1f]", "", base)
    return base[:120] or "model"


def _entry_for(path, size=None, parts=1, part_total=1, format="gguf",
               category=None):
    """One scan result. Meta parsing is defensive: a broken header marks
    the file not runnable instead of breaking the whole table."""
    p = Path(path)
    name = _clean_id_name(p.name)
    entry = {"id": LOCAL_PREFIX + name, "file": str(p), "name": name,
             "size": int(size) if size and size > 0 else 0,
             "parts": parts, "part_total": part_total, "format": format,
             "model_name": "", "arch": "", "quant": "", "ctx": 0,
             "params": "", "runnable": format == "gguf", "note": "",
             "mtime": 0.0, "category": category or GENERAL}
    try:
        entry["mtime"] = p.stat().st_mtime
    except OSError:
        pass
    if format == "onnx":
        # a Piper voice: never an LLM brain, never "not runnable" noise -
        # it runs through Nova Voice (piper backend)
        entry["runnable"] = False
        entry["note"] = "voice model (.onnx) - use it in Nova Voice (piper)"
        entry["category"] = entry["category"] if entry["category"] != GENERAL \
            else "voice"
        return entry
    if format == "gguf":
        meta = parse_gguf_header(p)
        if meta["error"] == "not_gguf":
            entry["runnable"] = False
            entry["note"] = "not a valid GGUF (bad magic)"
        elif meta["error"] == "gguf_v1_or_unknown":
            # GGUF v1 (2023 draft) and future versions: today's runtimes
            # (Ollama, llama.cpp) refuse them - do not promise a run.
            entry["runnable"] = False
            entry["note"] = "old/unknown GGUF version - not runnable here"
        elif meta["error"] == "truncated_header":
            entry["runnable"] = False
            entry["note"] = "truncated download (header incomplete)"
        elif meta["error"].startswith("unreadable"):
            entry["runnable"] = False
            entry["note"] = meta["error"]
        entry["model_name"] = meta["name"]
        entry["arch"] = meta["arch"]
        entry["quant"] = meta["quant"]
        entry["ctx"] = meta["ctx"]
        entry["params"] = meta["size_label"]
        if entry["runnable"] and entry["size"] \
                and entry["size"] < MIN_MODEL_BYTES:
            entry["runnable"] = False
            entry["note"] = "too small to be a real model file"
    else:
        entry["note"] = "not runnable - convert to GGUF first"
        if entry["category"] == "photo":
            entry["note"] = ("image model - point ComfyUI/A1111 at this file "
                             "(see README v6.1)")
    return entry


def scan_dirs(dirs, max_entries=MAX_ENTRIES):
    """Scan model folders -> list of entry dicts (sorted by name).
    `dirs` is what model_dirs() returns. Multi-part GGUFs
    (xxx-00001-of-00003.gguf) collapse into ONE entry whose size is the
    sum of all shards. Symlinked directories are never followed; the
    walk is depth- and count-capped. Each entry carries a `category`
    derived from its first folder under the root (code/voice/photo,
    else general)."""
    singles, shard_groups, safetensors, onnx = [], {}, [], []
    for _label, base, exists in (dirs or []):
        if not exists or not base.is_dir():
            continue
        base_start = len(base.parts)
        try:
            walk = os.walk(base, followlinks=False)
            for root, dnames, fnames in walk:
                depth = len(Path(root).parts) - base_start
                if depth >= MAX_WALK_DEPTH:
                    dnames[:] = []
                dnames[:] = sorted(d for d in dnames
                                   if d not in SKIP_DIR_NAMES
                                   and not d.startswith(".")
                                   and not (Path(root) / d).is_symlink())
                rel = Path(root).parts[base_start:] if \
                    len(Path(root).parts) > base_start else ()
                cat = category_for(rel)
                for fn in sorted(fnames):
                    low = fn.lower()
                    if low.endswith(".gguf"):
                        fp = Path(root) / fn
                        m = SHARD_RE.search(fn)
                        if m:
                            shard_groups.setdefault(
                                (str(fp.parent).lower(),
                                 _clean_id_name(fn).lower()),
                                []).append(fp)
                            # v6.5: shards used to bypass max_entries
                            # entirely - a folder of 10^4 shard files built
                            # an 8MB-header parse per group before the cap
                            if len(shard_groups) + len(singles) \
                                    + len(safetensors) + len(onnx) \
                                    >= max_entries:
                                dnames[:] = []
                                break
                        else:
                            singles.append((fp, cat))
                            if len(singles) + len(safetensors) + len(onnx) \
                                    >= max_entries:
                                dnames[:] = []
                                break
                    elif low.endswith(".onnx"):
                        onnx.append((Path(root) / fn, cat))
                        if len(singles) + len(safetensors) + len(onnx) \
                                >= max_entries:
                            dnames[:] = []
                            break
                    elif low.endswith(".safetensors"):
                        safetensors.append((Path(root) / fn, cat))
                        if len(singles) + len(safetensors) + len(onnx) \
                                >= max_entries:
                            dnames[:] = []
                            break
        except OSError:
            continue                      # unreadable folder - skip it
    entries = []
    for fp, cat in singles:
        entries.append(_entry_for(fp, category=cat))
    for _key, paths in sorted(shard_groups.items()):
        total = 0
        for sp in paths:
            try:
                total += sp.stat().st_size
            except OSError:
                pass
        first = min(paths, key=lambda p: p.name)
        m = SHARD_RE.search(first.name)
        ptot = int(m.group(2)) if m else len(paths)
        # shards keep the category of the folder they actually live in
        cat = GENERAL
        for _l, b, exists in (dirs or []):
            if not exists or not b.is_dir():
                continue
            try:
                rel_to = first.parent.relative_to(b).parts
            except ValueError:
                continue
            cat = category_for(rel_to)
            break
        entries.append(_entry_for(first, size=total or None,
                                  parts=len(paths), part_total=ptot,
                                  category=cat))
    for fp, cat in safetensors:
        try:
            sz = fp.stat().st_size
        except OSError:
            sz = 0
        entries.append(_entry_for(fp, size=sz, format="safetensors",
                                  category=cat))
    for fp, cat in onnx:
        try:
            sz = fp.stat().st_size
        except OSError:
            sz = 0
        entries.append(_entry_for(fp, size=sz, format="onnx", category=cat))
    entries.sort(key=lambda e: e["name"].lower())
    return entries[:max_entries]


# --------------------------------------------------------------- ollama name
def sanitize_model_name(base):
    """Free file name -> a name `ollama create` accepts (letters, digits,
    . _ - only; no spaces). Pure."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(base)).strip("-.")
    s = re.sub(r"-{2,}", "-", s)
    s = s[:48].strip("-.")
    return s or "model"


def ollama_import_name(file_path):
    """Deterministic Ollama name for one file: 'local-<name>-<hash6>'.
    Same file name + size -> same name (no duplicate imports); different
    files never collide. Pure given the inputs."""
    p = Path(file_path)
    base = p.name.lower()
    if base.endswith(".gguf"):
        base = base[:-5]
    base = SHARD_RE.sub("", base)
    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    h = hashlib.sha1(f"{p.name.lower()}:{size}".encode("utf-8", "replace")) \
        .hexdigest()[:6]
    return "local-" + sanitize_model_name(base) + "-" + h


# --------------------------------------------------------------- llama.cpp
def find_llama_server():
    """Path of a llama.cpp server binary on PATH, or None."""
    for exe in ("llama-server", "llama-server.exe", "llamafile",
                "llamafile.exe"):
        w = shutil.which(exe)
        if w:
            return w
    return None


_RUNNING = {}          # resolved file path -> handle dict (max ONE live)
# v6.5: start_llama_server is reachable from the REPL, Flow AND the web
# server threads; without this lock two concurrent starts both saw an
# empty _RUNNING and both spawned a llama-server (two loaded GGUFs in
# RAM - exactly what the one-server policy exists to prevent).
_START_LOCK = threading.Lock()


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _wait_health(base, deadline_s, poll=None, timeout_each=2.0, died=None):
    """Poll llama-server /health until 200 (loaded) or deadline.
    503 means 'still loading the model' - keep waiting.
    v6.2.1 fix: `died` (optional liveness callback) breaks the loop the
    moment the process exits - before, a llama-server that died instantly
    (corrupt GGUF, missing CUDA lib, lost port race) was polled for the
    FULL deadline (default NOVA_LLAMA_WAIT=120s -> a 2-minute UI freeze
    while TURN_LOCK was held)."""
    if poll is not None:                      # injectable for tests
        return bool(poll(base, deadline_s))
    end = time.time() + max(1, int(deadline_s))
    while time.time() < end:
        if died is not None:
            try:
                if died():
                    return False
            except Exception:
                pass
        try:
            req = urllib.request.Request(base + "/health")
            with urllib.request.urlopen(req, timeout=timeout_each) as r:
                if r.status == 200:
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 503:
                pass                      # loading - keep waiting
            else:
                # v6.7: any other 4xx/5xx (404 = llamafile / old
                # llama.cpp without /health) can never turn into 200 -
                # the old code polled the full deadline (up to 120s of
                # frozen UI) for a server that will never be ready.
                return False
        except OSError:
            pass
        time.sleep(1.0)
    return False


def _reap(proc, grace=5.0):
    """terminate() -> wait(grace) -> kill() -> wait(). v6.2.1 fix: the old
    code terminated WITHOUT reaping, so a llama-server that took seconds
    to unload still held its RAM + port while the replacement started
    (new bind could fail), and reaping was left to gc/subprocess._active.
    Tolerates duck-typed handles without wait()/kill() (test fakes)."""
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace)
        except Exception:
            pass
    except (OSError, AttributeError):
        pass   # already gone, or a handle without wait() - nothing to reap


def get_running(file_path):
    """Live handle for this file (or None). Re-spawned transparently if
    the old process died."""
    key = str(Path(file_path).resolve())
    h = _RUNNING.get(key)
    if h and h["proc"].poll() is None:
        return h
    if h:
        _RUNNING.pop(key, None)
    return None


def start_llama_server(file_path, exe=None, wait_s=None, ctx=4096,
                       popen=None, log_dir=None, poll=None):
    """Spawn `llama-server -m <gguf>` on a free 127.0.0.1 port and wait
    for the model to load. Returns {proc, base, port, log}. Exactly ONE
    server stays alive: starting another file stops the previous one
    (weak-hardware policy - one loaded GGUF is enough RAM pressure).
    `popen`/`poll` are injectable seams for the offline test suite.
    v6.5: serialized by _START_LOCK - a second concurrent start waits and
    then reuses the first handle (same file) or replaces it (next file)."""
    with _START_LOCK:
        return _start_llama_server_locked(file_path, exe=exe, wait_s=wait_s,
                                          ctx=ctx, popen=popen,
                                          log_dir=log_dir, poll=poll)


def _start_llama_server_locked(file_path, exe=None, wait_s=None, ctx=4096,
                               popen=None, log_dir=None, poll=None):
    key = str(Path(file_path).resolve())
    existing = get_running(key)
    if existing:
        return existing
    exe = exe or find_llama_server()
    if not exe:
        raise LocalModelError(
            "llama-server not found - install llama.cpp, or start Ollama "
            "(it imports .gguf files automatically)")
    # one-server policy: a model switch must not stack RAM usage
    for old_key, old in list(_RUNNING.items()):
        _reap(old["proc"])
        _RUNNING.pop(old_key, None)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    log_path = None
    kwargs = {}
    if os.name == "nt":
        # A packaged windowed .exe has no console of its own, so
        # llama-server.exe would otherwise flash a brand new black
        # cmd.exe window on Windows on every model start/switch.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if log_dir is not None:
        try:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = str(log_dir / "llama-server.log")
            logf = open(log_path, "wb")
            kwargs["stdout"] = logf
            kwargs["stderr"] = subprocess.STDOUT
        except OSError:
            log_path = None
    args = [exe, "-m", str(key), "--host", "127.0.0.1", "--port", str(port),
            "-c", str(max(512, int(ctx)))]
    try:
        if popen is not None:
            proc = popen(args)
        else:
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, **kwargs)
    except OSError as e:
        raise LocalModelError(f"cannot start llama-server: {e}") from None
    finally:
        # Popen (when reached) dup()s the fd into the child; our copy must
        # be closed here or every model start/restart leaks one fd for the
        # life of the Nova process (visible after many switches in a long
        # session). Closing is safe whether Popen succeeded or raised.
        if "logf" in locals():
            try:
                logf.close()
            except OSError:
                pass
    handle = {"proc": proc, "base": base + "/v1", "port": port,
              "log": log_path, "file": key}
    _RUNNING[key] = handle
    wait = wait_s if wait_s is not None else _env_wait()
    if not _wait_health(base, wait, poll=poll,
                        died=lambda: proc.poll() is not None):
        died = proc.poll() is not None
        _reap(proc)
        _RUNNING.pop(key, None)
        raise LocalModelError(
            "llama-server did not become ready within "
            f"{int(wait)}s" + (" - it exited (see its log)" if died else
                               " - raise NOVA_LLAMA_WAIT for big models"))
    return handle


def stop_all():
    """Kill every llama-server Nova spawned (called at session exit)."""
    # v6.5: never block shutdown behind an in-progress (locked) start that
    # may be inside its up-to-120s health wait - best-effort reap instead.
    if not _START_LOCK.acquire(timeout=2.0):
        for _key, h in list(_RUNNING.items()):
            _reap(h["proc"])
        return
    try:
        for _key, h in list(_RUNNING.items()):
            _reap(h["proc"])
        _RUNNING.clear()
    finally:
        _START_LOCK.release()


def _env_wait():
    raw = os.environ.get("NOVA_LLAMA_WAIT", "").strip()
    try:
        v = int(raw)
        if v >= 5:
            return v
    except ValueError:
        pass
    return 120


def openai_cfg(handle):
    """Provider config for nova_providers.stream_chunks() - the llama.cpp
    server speaks the OpenAI wire protocol out of the box. v6.7:
    key_optional marks this config FREE for the economy budget gate
    (nova._is_free_local also recognizes it by its loopback base)."""
    return {"kind": "openai", "name": "llamacpp", "label": "llama.cpp (local GGUF)",
            "base": handle["base"], "key": "", "model": "local",
            "key_optional": True}
