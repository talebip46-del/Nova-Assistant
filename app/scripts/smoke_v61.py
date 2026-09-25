#!/usr/bin/env python3
"""v6.1 live smoke: categorized model folders end-to-end on a REAL web
server + the CLI face. No Ollama needed (file models only)."""
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

ROOT = Path(tempfile.mkdtemp(prefix="smoke61_root_"))
WS = Path(tempfile.mkdtemp(prefix="smoke61_ws_"))
PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + ("  -> " + str(extra)[:200] if extra else ""))


def gguf_bytes(name="m"):
    kvs = [("general.name", name), ("general.architecture", "llama"),
           ("general.file_type", 15)]
    buf = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) \
        + struct.pack("<Q", len(kvs))
    for key, val in kvs:
        kb = key.encode()
        buf += struct.pack("<Q", len(kb)) + kb
        if isinstance(val, str):
            vb = val.encode()
            buf += struct.pack("<I", 8) + struct.pack("<Q", len(vb)) + vb
        else:
            buf += struct.pack("<I", 4) + struct.pack("<I", val)
    return buf + b"\x00" * 64


# ---- the categorized layout on disk
(ROOT / "code").mkdir()
(ROOT / "voice").mkdir()
(ROOT / "photo").mkdir()
(ROOT / "gen.gguf").write_bytes(gguf_bytes("gen"))
(ROOT / "code" / "coder.gguf").write_bytes(gguf_bytes("coder"))
(ROOT / "voice" / "fa-voice.onnx").write_bytes(b"0" * 4096)
(ROOT / "photo" / "sd15.safetensors").write_bytes(b"0" * 4096)
os.environ["NOVA_MODELS_DIR"] = str(ROOT)
# v7.4 audit fix: the v6.8.2 kill-switch defaults to disabling
# voice/photo/pixel/flow - the smoke test verifies those modules,
# so it must clear the switch or 3 checks always 403-fail.
os.environ["NOVA_DISABLED_MODULES"] = ""

import web_server          # noqa: E402
import nova                # noqa: E402

# 1. the app creates its local/ category folders on demand?
made = nova.lmodels.prepare_local_dirs()
check("prepare_local_dirs makes 4 dirs", len(made) == 4, made)

web_server.nova = nova
web_server.STATE = web_server._State(WS)
web_server.AUTH_TOKEN = None
httpd = web_server._make_server({"host": "127.0.0.1", "port": 0,
                                 "workspace": str(WS)})
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode())


def post(path, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


# 2. /api/models_all: categories + folders + by_category
data = get("/api/models_all")
cats = {k: [r["name"] for r in v]
        for k, v in (data.get("by_category") or {}).items()}
check("by_category.general has gen", "gen" in cats.get("general", []), cats)
check("by_category.code has coder", "coder" in cats.get("code", []), cats)
check("by_category.voice has fa-voice",
      "fa-voice" in cats.get("voice", []), cats)
check("by_category.photo has sd15", "sd15" in cats.get("photo", []), cats)
check("folders include NOVA_MODELS_DIR",
      any(f["label"] == "NOVA_MODELS_DIR" for f in data.get("folders", [])))
check("categories legend present", "code" in (data.get("categories") or {}))
check("files exclude onnx", all(f["name"] != "fa-voice" for f in data["files"]))

# 3. assignment rules over HTTP
code, body = post("/api/assign", {"module": "assistant", "backend": "file",
                                  "model": "file:coder"})
check("code model assigned to assistant", code == 200 and
      body.get("cfg", {}).get("model") == "file:coder", (code, body))
code, body = post("/api/assign", {"module": "assistant", "backend": "file",
                                  "model": "file:sd15"})
check("photo model rejected for assistant", code == 400 and
      "runnable" in body.get("error", ""), (code, body))
(ROOT / "photo" / "art.gguf").write_bytes(gguf_bytes("art"))
code, body = post("/api/assign", {"module": "assistant", "backend": "file",
                                  "model": "file:art"})
check("photo GGUF rejected by category", code == 400 and
      "photo" in body.get("error", ""), (code, body))
code, body = post("/api/assign", {"module": "voice", "backend": "piper",
                                  "model": "fa-voice"})
check("piper voice resolved from local/voice", code == 200 and
      body.get("cfg", {}).get("model") == "file:fa-voice", (code, body))
code, body = post("/api/assign", {"module": "voice", "backend": "coqui"})
check("coqui default url filled", code == 200 and
      body.get("cfg", {}).get("url") == "http://127.0.0.1:5002", (code, body))

# 4. offline engines still work through the web face
post("/api/assign/clear", {"module": "voice"})   # back to offline engine
code, body = post("/api/voice/tts", {"text": "سلام"})
check("tts offline works", code == 200 and body.get("engine") == "offline",
      (code, body))
code, body = post("/api/photo/generate", {"prompt": "کوهستان"})
check("photo offline works", code == 200 and body.get("engine") == "offline",
      (code, body))
code, body = post("/api/pixel/generate", {"prompt": "قلعه"})
check("pixel works", code == 200, (code, body))

# 5. /api/info version
# v6.5: pin the smoke to the app's own VERSION instead of a hard-coded
# string that went stale at every release (the smoke failed on healthy
# builds since v6.2.1).
sys.path.insert(0, str(APP))
import nova as _nova_app
info = get("/api/info")
check("version " + _nova_app.VERSION, info.get("version") == _nova_app.VERSION,
      info.get("version"))

httpd.shutdown()
httpd.server_close()

# 6. CLI face: models table with categories
r = subprocess.run([sys.executable, str(APP / "nova_assistant.py"), "models"],
                   capture_output=True, text=True, timeout=120,
                   cwd=str(WS))
check("CLI models runs", r.returncode == 0, r.stderr[-200:])
check("CLI shows coder with [code]", "[code]" in r.stdout, r.stdout[:400])
check("CLI shows voice models section",
      "Voice models (.onnx for Piper): 1" in r.stdout, r.stdout[:400])

# 7. /model slash command table + --list-models (terminal face, headless)
r = subprocess.run([sys.executable, str(APP / "nova.py"), "--list-models"],
                   capture_output=True, text=True, timeout=120,
                   cwd=str(WS))
check("--list-models exit 0 with file models", r.returncode == 0,
      r.stdout[-200:])
check("--list-models shows [code] tag", "[code]" in r.stdout, r.stdout[:400])
check("--list-models categories hint",
      "<folder>/voice" in r.stdout and "categories:" in r.stdout,
      r.stdout[-300:])

print("\nSMOKE: %d ok, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
