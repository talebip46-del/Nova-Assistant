#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - platform discovery (v6.0)
#
#  Beyond Ollama: the "comprehensive platform" family - LocalAI, Shimmy,
#  llama.cpp server, LM Studio, vLLM, Mullama, LiteLLM ... - all expose
#  the SAME OpenAI-compatible GET /v1/models endpoint. One probe per
#  server turns every one of them into a Nova model source:
#
#      LocalAI   http://127.0.0.1:8080/v1     (LLM + image + audio!)
#      Shimmy    http://127.0.0.1:11435/v1    (5 MB, starts in <100ms)
#      LM Studio http://127.0.0.1:1234/v1
#      vLLM      http://127.0.0.1:8000/v1
#      llama.cpp http://127.0.0.1:8080/v1     (same port as LocalAI -
#                                              only one can run at a time)
#
#  Where platforms come from (merged, deduped):
#    1. NOVA_PLATFORMS env:  "name@http://host:port/v1, name2@http://..."
#    2. <ws>/.nova/platforms.json  (saved from the web UI / CLI)
#    3. the PRESETS above - only PROBED on an explicit scan, never every
#       poll (a dead preset would cost a connect timeout on every /api/info)
#
#  Security note, stated honestly: a platform entry is a URL Nova will
#  talk to - configured by the local user, the same trust level as the
#  'custom' provider. http/https only; anything else is rejected. This
#  is a local-first tool: pointing it at private LAN hosts is a FEATURE.
# =====================================================================
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:
    natom = None

MAX_PLATFORMS = 20
MAX_NAME_LEN = 40
PROBE_TIMEOUT = 2.5          # seconds per probe on an explicit scan
HTTP_TIMEOUT = 6             # seconds for the models fetch

PRESETS = [
    {"name": "localai", "base": "http://127.0.0.1:8080/v1",
     "hint": "LocalAI - LLM + image + audio engines"},
    {"name": "shimmy", "base": "http://127.0.0.1:11435/v1",
     "hint": "Shimmy - 5 MB server, auto-discovers Ollama/HF caches"},
    {"name": "lmstudio", "base": "http://127.0.0.1:1234/v1",
     "hint": "LM Studio local server"},
    {"name": "vllm", "base": "http://127.0.0.1:8000/v1",
     "hint": "vLLM OpenAI-compatible server"},
    {"name": "llamacpp", "base": "http://127.0.0.1:8081/v1",
     "hint": "llama.cpp server (llama-server)"},
    {"name": "ollama-openai", "base": "http://127.0.0.1:11434/v1",
     "hint": "Ollama's own OpenAI-compatible endpoint"},
    {"name": "koboldcpp", "base": "http://127.0.0.1:5001/v1",
     "hint": "KoboldCpp OpenAI-compatible endpoint"},
    {"name": "tgwebui", "base": "http://127.0.0.1:5000/v1",
     "hint": "text-generation-webui (oobabooga) --api"},
    {"name": "jan", "base": "http://127.0.0.1:1337/v1",
     "hint": "Jan local server"},
    {"name": "gpt4all", "base": "http://127.0.0.1:4891/v1",
     "hint": "GPT4All local API server"},
]

_URL_RE = re.compile(r"^https?://[A-Za-z0-9._~:/\-\[\]@!$&'()*+,;=%]+$")
_NAME_RE = re.compile(r"^[\w.\- ]{1," + str(MAX_NAME_LEN) + "}$")


class PlatformError(Exception):
    """Clean, user-readable platform problem."""


def clean_name(raw):
    if not isinstance(raw, str):
        return ""
    name = raw.strip()
    if not name or len(name) > MAX_NAME_LEN or not _NAME_RE.match(name):
        return ""
    return name


def clean_base(raw):
    """Validate a platform base URL. Returns '' for anything unsafe.
    Scheme must be http(s) - file://, ftp://, gopher:// etc. never pass."""
    if not isinstance(raw, str):
        return ""
    base = raw.strip().rstrip("/")
    if not base or len(base) > 300 or not _URL_RE.match(base):
        return ""
    low = base.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return ""
    if " " in base or "\n" in base or "\r" in base:
        return ""
    return base


def normalize_platform(entry):
    """One user-supplied entry -> clean {name, base} or None."""
    if not isinstance(entry, dict):
        return None
    name = clean_name(entry.get("name"))
    base = clean_base(entry.get("base"))
    if not name or not base:
        return None
    return {"name": name, "base": base}


# --------------------------------------------------------------- config
def config_path(ws):
    return Path(ws) / ".nova" / "platforms.json"


def load_config(ws):
    """Saved platforms: [{'name','base'}]. Never raises."""
    try:
        data = json.loads(config_path(ws).read_text(encoding="utf-8"))
    except Exception:
        return []
    plats = data.get("platforms") if isinstance(data, dict) else None
    if not isinstance(plats, list):
        return []
    out, seen = [], set()
    for p in plats[:MAX_PLATFORMS * 2]:
        norm = normalize_platform(p)
        if not norm or norm["base"] in seen:
            continue
        seen.add(norm["base"])
        out.append(norm)
        if len(out) >= MAX_PLATFORMS:
            break
    return out


def save_config(ws, platforms):
    """Persist the platform list (web UI / CLI). Returns the clean list.
    Raises PlatformError when nothing valid remains."""
    if not isinstance(platforms, list):
        raise PlatformError("platforms must be a list")
    out, seen = [], set()
    for p in platforms[:MAX_PLATFORMS * 2]:
        norm = normalize_platform(p)
        if not norm or norm["base"] in seen:
            continue
        seen.add(norm["base"])
        out.append(norm)
        if len(out) >= MAX_PLATFORMS:
            break
    if not out and any(isinstance(p, dict) and (p.get("name") or p.get("base"))
                       for p in platforms):
        # the caller TRIED to configure something and nothing survived -
        # silently saving an empty registry would hide the mistake
        raise PlatformError("no valid platform entries "
                            "(need name + http/https base URL)")
    path = config_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    # v6.5: atomic write (project convention: tmp + os.replace, like
    # nova_policy.save_policy) - a crash mid-save used to truncate
    # platforms.json and silently erase every saved platform.
    # v6.7: unique scratch name (cross-process tmp collision).
    if natom is not None:
        natom.write_text_atomic(
            path, json.dumps({"platforms": out}, ensure_ascii=False, indent=1))
        return out
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"platforms": out}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)
    return out


def env_platforms():
    """NOVA_PLATFORMS='name@url, name@url' -> [{'name','base'}]. Junk
    entries are skipped silently - an env var is a convenience, not a
    place to crash a startup."""
    raw = os.environ.get("NOVA_PLATFORMS", "")
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part or "@" not in part:
            continue
        name, _, base = part.partition("@")
        norm = normalize_platform({"name": name, "base": base})
        if norm:
            out.append(norm)
    return out[:MAX_PLATFORMS]


def all_platforms(ws=None):
    """env + saved config, env first, deduped by base URL."""
    merged, seen = [], set()
    for p in env_platforms() + (load_config(ws) if ws else []):
        if p["base"] in seen:
            continue
        seen.add(p["base"])
        merged.append(p)
    return merged


# --------------------------------------------------------------- probe
def parse_models_payload(payload):
    """GET /v1/models body -> ordered clean model-id list.
    OpenAI shape: {"data":[{"id":...}]}. Some servers (Shimmy, LM
    Studio variants) return a bare list or different keys - all are
    handled. Junk is skipped, never raised."""
    ids, seen = [], set()
    entries = None
    if isinstance(payload, dict):
        d = payload.get("data")
        entries = d if isinstance(d, list) else None
        if entries is None:
            # some minimal servers: {"models": ["a","b"]} or {"models":[{...}]}
            m = payload.get("models")
            if isinstance(m, list):
                entries = m
    elif isinstance(payload, list):
        entries = payload
    if not entries:
        return []
    for e in entries[:500]:
        if isinstance(e, dict):
            raw = e.get("id") or e.get("name") or e.get("model")
        elif isinstance(e, str):
            raw = e
        else:
            continue
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not name or len(name) > 160 or "\n" in name or name in seen:
            continue
        seen.add(name)
        ids.append(name)
    return ids


def probe(base, api_key="", timeout=HTTP_TIMEOUT):
    """GET {base}/models -> {'ok':True,'models':[...]} or
    {'ok':False,'note':...}. Never raises."""
    base = clean_base(base)
    if not base:
        return {"ok": False, "note": "invalid URL (http/https only)"}
    url = base + "/models"
    headers = {"Accept": "application/json", "User-Agent": "NovaAssistant"}
    if api_key:
        headers["Authorization"] = "Bearer " + str(api_key)[:400]
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2_000_000)
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            return {"ok": False, "note": "response is not JSON"}
        return {"ok": True, "models": parse_models_payload(payload)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "note": "HTTP %d" % e.code}
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        return {"ok": False, "note": "unreachable (" + str(getattr(e, "reason", e))[:120] + ")"}


def scan(ws=None, include_presets=True, timeout=PROBE_TIMEOUT, prober=None):
    """Probe every configured platform (+presets when asked) IN PARALLEL
    (one thread per platform - dead servers cost their timeout, not
    their timeout * count). Returns [{'name','base','ok','models','note'}]
    with presets marked preset=True when hit."""
    plats = all_platforms(ws)
    if include_presets:
        seen = {p["base"] for p in plats}
        for preset in PRESETS:
            if preset["base"] not in seen:
                plats = plats + [{"name": preset["name"], "base": preset["base"],
                                  "preset": True}]
    fn = prober or (lambda p: probe(p["base"], timeout=timeout))
    import threading
    results = [None] * len(plats)

    def worker(i, p):
        try:
            r = fn(p)
        except Exception as e:                       # hostile prober etc.
            r = {"ok": False, "note": type(e).__name__}
        results[i] = {
            "name": p["name"], "base": p["base"],
            "preset": bool(p.get("preset")),
            "ok": bool(r.get("ok")),
            "models": r.get("models", []) if r.get("ok") else [],
            "note": r.get("note", "") if not r.get("ok") else "",
        }

    threads = []
    # v6.7 fix: the slice at MAX_PLATFORMS + len(PRESETS) (= 30) silently
    # dropped configured platforms beyond it (all_platforms() can return
    # 20 env + 20 saved = 40) - they were never probed and never reported.
    # The global deadline below already bounds the total cost.
    for i, p in enumerate(plats):
        t = threading.Thread(target=worker, args=(i, p), daemon=True)
        threads.append(t)
        t.start()
    # v6.2.1 fix: the old per-thread join(timeout + 5) summed up: N stalled
    # probes (urlopen's timeout does NOT cap DNS resolution) blocked the
    # scan for N x (timeout+5) worst case. One GLOBAL deadline instead -
    # the scan returns once, on time, with whatever answered by then.
    deadline = time.monotonic() + timeout + 5
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return [r for r in results if r is not None]


def models_by_platform(scan_results):
    """scan() output -> {'platformname|base': [model ids]} - only live
    platforms. The '|' keeps a model ref unambiguous for the assign layer."""
    out = {}
    for r in scan_results or []:
        if r.get("ok") and r.get("models"):
            out[str(r.get("name", "?")) + "|" + str(r.get("base", ""))] = \
                r["models"]
    return out
