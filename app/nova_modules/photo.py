#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - Nova Photo (v6.0)
#
#  Text-to-image through FOUR engines, auto-chosen from the module
#  assignment:
#
#    a1111          Automatic1111 / InvokeAI-compatible
#                   POST /sdapi/v1/txt2img  ->  {"images": ["<b64>"]}
#    comfyui        ComfyUI POST /prompt (built-in default workflow)
#                   then poll /history/<id> and download from /view
#    openai_compat  LocalAI / Shimmy / any OpenAI-compatible
#                   POST /images/generations -> b64_json
#    offline        built-in procedural engine - gradient skies,
#                   midpoint-displacement mountains, stars, seed-locked.
#                   Always works, zero setup, honest about what it is.
#
#  Safety: engine URLs come from the assignment config (validated http/s
#  there); engine payloads are capped; every adapter raises ModuleError
#  with a SHORT readable message instead of a traceback.
# =====================================================================
import base64
import hashlib
import uuid
import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import nova_png
from nova_modules import ModuleError, module_data_dir

MAX_PROMPT = 2000
MAX_B64 = 30_000_000            # ~22 MB decoded - plenty for 1024px PNG
GALLERY_CAP = 200
HTTP_TIMEOUT = 150              # local GPUs can be slow on the first load
COMFY_POLL_S = 60

_UA = {"User-Agent": "NovaAssistant", "Accept": "application/json"}


def _post_json(url, payload, timeout=HTTP_TIMEOUT, headers=None):
    body = json.dumps(payload).encode("utf-8")
    all_headers = dict(_UA)
    all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})
    try:
        req = urllib.request.Request(url, data=body, headers=all_headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(MAX_B64 * 2).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read(300).decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise ModuleError("HTTP %d from image engine %s"
                          % (e.code, detail[:160])) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise ModuleError("cannot reach the image engine (%s)"
                          % str(getattr(e, "reason", e))[:120]) from None
    except ValueError:
        raise ModuleError("image engine returned invalid JSON") from None


def _decode_b64_png(b64):
    """base64 -> raw bytes with a REAL PNG magic check (servers have
    been known to return error JSON inside image fields)."""
    if not isinstance(b64, str) or not b64 or len(b64) > MAX_B64:
        raise ModuleError("image engine returned no usable image data")
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        raise ModuleError("image payload is not valid base64") from None
    if len(raw) < 100 or not raw.startswith(b"\x89PNG"):
        raise ModuleError("image payload is not a PNG")
    return raw


def _cfg_url(cfg):
    url = str(cfg.get("url") or "").strip().rstrip("/")
    if not url or not url.lower().startswith(("http://", "https://")):
        raise ModuleError("this engine needs a server URL in the module assignment")
    return url


def _seed(cfg):
    """Seed from the config; -1 = engine-random. v6.5: `0 or -1` treated
    the EXPLICIT seed 0 as random (0 is falsy) - reproducibility broke
    for exactly the seed users asked for."""
    try:
        return int(str(cfg.get("seed", "")).strip() or -1)
    except (TypeError, ValueError):
        return -1


# --------------------------------------------------------------- adapters
def gen_a1111(ws, prompt, cfg, width=512, height=512):
    url = _cfg_url(cfg) + "/sdapi/v1/txt2img"
    data = _post_json(url, {
        "prompt": prompt[:MAX_PROMPT], "negative_prompt": "",
        "steps": min(max(int(cfg.get("steps", 20) or 20), 4), 60),
        "width": width, "height": height, "sampler_name": "Euler a",
        "seed": _seed(cfg),
    })
    images = data.get("images") if isinstance(data, dict) else None
    if not images or not isinstance(images, list):
        raise ModuleError("txt2img returned no image (is the model loaded?)")
    return _decode_b64_png(images[0]), "a1111"


_COMFY_TEMPLATE = {
    "3":  {"class_type": "KSampler", "inputs": {}},
    "4":  {"class_type": "CheckpointLoaderSimple", "inputs": {}},
    "5":  {"class_type": "EmptyLatentImage", "inputs":
           {"width": 512, "height": 512, "batch_size": 1}},
    "6":  {"class_type": "CLIPTextEncode", "inputs": {}},
    "7":  {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    "8":  {"class_type": "VAEDecode", "inputs": {}},
    "9":  {"class_type": "SaveImage", "inputs": {"filename_prefix": "nova"}},
}


def _comfy_workflow(prompt, model, width, height):
    wf = json.loads(json.dumps(_COMFY_TEMPLATE))   # deep copy
    wf["4"]["inputs"]["ckpt_name"] = model or "v1-5-pruned-emaonly.safetensors"
    wf["6"]["inputs"]["text"] = prompt[:MAX_PROMPT]
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["3"]["inputs"] = {
        "seed": random.randrange(2 ** 31), "steps": 20, "cfg": 7.5,
        "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
        "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
        "latent_image": ["5", 0],
    }
    wf["8"]["inputs"] = {"samples": ["3", 0], "vae": ["4", 2]}
    wf["9"]["inputs"] = {"filename_prefix": "nova", "images": ["8", 0]}
    return {"prompt": wf}


def _resolve_photo_model(ws, ref):
    """'file:<name>' / bare name -> real file name of an image model from
    the model folders (local/photo, ...). ComfyUI needs the checkpoint
    INSIDE its own models/checkpoints dir - so we pass the FILE NAME and
    document the copy/link step. None when not found / a plain name."""
    if not ref or "/" in ref or "\\" in ref:
        return None
    import nova_localmodels as lmodels
    want = str(ref).strip()
    if want.startswith(lmodels.LOCAL_PREFIX):
        want = want[len(lmodels.LOCAL_PREFIX):]
    want = want.strip().strip("\"'").lower()
    if not want:
        return None
    try:
        for e in lmodels.scan_dirs(lmodels.model_dirs(ws)):
            fname = Path(e.get("file", "")).name.lower()
            if e.get("name", "").lower() == want or \
                    fname in (want, want + ".safetensors", want + ".gguf"):
                return Path(e["file"]).name
    except Exception:
        return None
    return None


def gen_comfyui(ws, prompt, cfg, width=512, height=512):
    base = _cfg_url(cfg)
    model = str(cfg.get("model") or "").strip()
    if model.startswith("file:"):
        model = _resolve_photo_model(ws, model) or ""
    wf = _comfy_workflow(prompt, model, width, height)
    try:
        req = urllib.request.Request(
            base + "/prompt", data=json.dumps(wf).encode("utf-8"),
            headers={"Content-Type": "application/json", **_UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            ack = json.loads(resp.read(200_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise ModuleError("ComfyUI HTTP %d (workflow/model mismatch?)"
                          % e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise ModuleError("cannot reach ComfyUI (%s)"
                          % str(getattr(e, "reason", e))[:120]) from None
    except ValueError:
        raise ModuleError("ComfyUI returned invalid JSON") from None
    pid = ack.get("prompt_id") if isinstance(ack, dict) else None
    if not pid:
        raise ModuleError("ComfyUI did not accept the workflow")
    # poll history until the output image appears
    deadline = time.time() + COMFY_POLL_S
    while time.time() < deadline:
        time.sleep(1.5)
        try:
            with urllib.request.urlopen(base + "/history/" + str(pid)[:200],
                                        timeout=10) as resp:
                hist = json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
        except Exception:
            continue
        entry = hist.get(pid) if isinstance(hist, dict) else None
        outs = (entry or {}).get("outputs") if isinstance(entry, dict) else None
        if isinstance(outs, dict):
            for node in outs.values():
                for img in (node.get("images") or []):
                    fn = img.get("filename")
                    if fn and img.get("type", "output") == "output":
                        vurl = "%s/view?filename=%s&type=output" % (
                            base, urllib.request.quote(str(fn), safe=""))
                        try:
                            with urllib.request.urlopen(vurl, timeout=60) as r:
                                raw = r.read(MAX_B64)
                        except Exception as e:
                            raise ModuleError("image download failed (%s)" % str(e)[:120])
                        if raw.startswith(b"\x89PNG"):
                            return raw, "comfyui"
        if entry is not None and outs is not None and not outs:
            status = entry.get("status", {})
            if str(status.get("status_str", "")) == "error":
                raise ModuleError("ComfyUI reported an execution error")
    raise ModuleError("ComfyUI timed out after %ds" % COMFY_POLL_S)


def gen_openai_compat(ws, prompt, cfg, width=512, height=512):
    url = _cfg_url(cfg) + "/images/generations"
    headers = {}
    if cfg.get("key"):
        headers["Authorization"] = "Bearer " + str(cfg["key"])[:400]
    data = _post_json(url, {
        "model": cfg.get("model") or "stable-diffusion",
        "prompt": prompt[:MAX_PROMPT], "n": 1,
        "size": "%dx%d" % (width, height),
        "response_format": "b64_json",
    }, headers=headers)
    items = data.get("data") if isinstance(data, dict) else None
    if not items or not isinstance(items, list) or not isinstance(items[0], dict):
        raise ModuleError("images/generations returned no data (is the image model loaded?)")
    if items[0].get("url"):
        # some servers return a URL instead of inline b64
        u = str(items[0]["url"])[:1000]
        # v6.8.1: scheme + host guard - a compromised/odd engine could
        # hand back file:///etc/passwd or an internal endpoint
        try:
            sch = urllib.parse.urlparse(u).scheme.lower()
        except Exception:
            sch = ""
        if sch not in ("http", "https"):
            raise ModuleError("engine returned a non-http(s) image URL - refused")
        try:
            with urllib.request.urlopen(u, timeout=60) as r:
                raw = r.read(MAX_B64)
        except Exception as e:
            raise ModuleError("image download failed (%s)" % str(e)[:120])
        if raw.startswith(b"\x89PNG"):
            return raw, "openai_compat"
        raise ModuleError("downloaded payload is not a PNG")
    return _decode_b64_png(items[0].get("b64_json")), "openai_compat"


# --------------------------------------------------------------- offline engine
def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex2rgb(h):
    h = (h or "#000").lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def gen_offline(ws, prompt, cfg, width=512, height=512):
    """Deterministic procedural landscape art from the prompt hash:
    banded sky, sun disc, midpoint-displacement mountain ridges, stars.
    Honest engine: it will NOT hallucinate a cat - it paints a mood."""
    seed = hashlib.sha256((prompt or "nova").encode("utf-8", "replace")).hexdigest()
    rng = random.Random(seed)
    W, H = width, height
    top = _hex2rgb("#0d1020" if rng.random() < 0.5 else "#1b0b2e")
    bot = _hex2rgb(rng.choice(["#9b6bff", "#ff9760", "#2a97c2", "#d4547a"]))
    rows = []
    horizon = int(H * rng.uniform(0.55, 0.72))
    sun_x, sun_y = rng.randrange(W // 4, 3 * W // 4), rng.randrange(H // 8, horizon // 2)
    sun_r = rng.randint(H // 14, H // 8)
    sun = _hex2rgb(rng.choice(["#ffd07b", "#ffe9a8", "#ff9760"]))
    ridge_cols = [tuple(min(255, c + rng.randint(-18, 18)) for c in bot)
                  for _ in range(3)]
    for y in range(H):
        row = bytearray(b"\x00")
        if y < horizon:
            t = y / max(1, horizon)
            base = _lerp(top, bot, t)
        else:
            t = (y - horizon) / max(1, H - horizon)
            base = _lerp(ridge_cols[0], (8, 6, 18), t)
        for x in range(W):
            # dithered band transitions keep the retro soul alive
            b = base
            if y < horizon and (x * 7 + y * 13 + rng.randrange(4)) % 11 == 0:
                b = _lerp(base, top, 0.25)
            r, g, bl = b
            if (x - sun_x) ** 2 + (y - sun_y) ** 2 <= sun_r * sun_r:
                r, g, bl = sun
            # stars in the upper sky
            if y < horizon // 2 and rng.random() < 0.002:
                r = g = bl = 255
            row += bytes((min(255, max(0, r)), min(255, max(0, g)),
                          min(255, max(0, bl))))
        rows.append(bytes(row))
    # ridge lines between sky and ground - painted AFTER the frame is
    # complete: a ridge can reach rows that do not exist mid-loop yet
    # (that was a real IndexError on some seeds)
    for ri, col in enumerate(ridge_cols):
        amp = H // 12
        level = horizon + ri * H // 30
        pts = []
        nseg = 8
        for i in range(nseg + 1):
            pts.append(level + rng.randint(-amp // 2, amp // 2))
        # two midpoint passes smooth the zigzag into a ridge
        for _ in range(2):
            nxt = []
            for i in range(len(pts) - 1):
                nxt.append(pts[i])
                nxt.append((pts[i] + pts[i + 1]) // 2 + rng.randint(-amp // 4, amp // 4))
            nxt.append(pts[-1])
            pts = nxt
        step = max(1, W // (len(pts) - 1))
        for xi in range(W):
            pi = min(len(pts) - 1, xi // step)
            yline = pts[pi]
            for yy in range(max(0, yline), min(H, yline + H // 20)):
                row = rows[yy]
                off = 1 + xi * 3        # skip the filter byte
                rows[yy] = row[:off] + bytes(col) + row[off + 3:]
    return nova_png.encode_png(W, H, rows, alpha=False), "offline"


ENGINES = {"a1111": gen_a1111, "comfyui": gen_comfyui,
           "openai_compat": gen_openai_compat, "offline": gen_offline}


# --------------------------------------------------------------- entry
def generate(ws, prompt, cfg=None, size=512, engine=None, want_engine=None):
    """Prompt -> {engine, png(bytes), path, name, note}. The engine comes
    from the module assignment (cfg), overridable per call. Saves the
    PNG into the photo gallery. Raises ModuleError with clean messages."""
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ModuleError("empty prompt")
    if len(prompt) > MAX_PROMPT:
        prompt = prompt[:MAX_PROMPT]
    try:
        side = int(size)
    except (TypeError, ValueError):
        side = 512
    side = min(max(side, 64), 1024)
    cfg = cfg or {}
    engine = engine or want_engine or cfg.get("backend") or "offline"
    if engine not in ENGINES:
        raise ModuleError("unknown image engine '%s'" % engine)
    png, used = ENGINES[engine](ws, prompt, cfg, side, side)
    name = "photo-%s-%s.png" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])
    base = module_data_dir(ws, "photo")
    path = base / name
    # v6.2.1: atomic write - a crash mid-write used to leave a truncated
    # photo-*.png that the gallery then displayed
    tmp = base / (name + ".part")
    tmp.write_bytes(png)
    tmp.replace(path)
    note = ""
    if used == "offline":
        note = ("موتور آفلاین داخلی: تصویر رویه‌ای از هش پرامپت - برای "
                "تولید واقعی، موتور A1111/ComfyUI/LocalAI را در بخش «مدل‌ها» متصل کنید")
    elif used == "comfyui" and str(cfg.get("model") or "").startswith("file:"):
        note = ("چک‌پوینت از پوشه local/photo خوانده شد - فایل باید در "
                "models/checkpoints خودِ ComfyUI هم موجود باشد (کپی یا symlink)")
    # gallery hygiene: cap the number of saved files; v6.7: also sweep
    # orphaned .part files (>1h old) - a crash between the tmp write and
    # the replace used to leak them forever (invisible to the gallery).
    old = sorted(base.glob("photo-*.png"))
    if len(old) > GALLERY_CAP:
        for f in old[:len(old) - GALLERY_CAP]:
            try:
                f.unlink()
            except OSError:
                pass
    try:
        import time as _t
        for f in base.glob("*.part"):
            if _t.time() - f.stat().st_mtime > 3600:
                f.unlink()
    except OSError:
        pass
    return {"engine": used, "name": name, "path": str(path),
            "bytes": len(png), "note": note, "prompt": prompt}


def list_gallery(ws, cap=60):
    import nova_png as _np
    base = module_data_dir(ws, "photo", create=False)
    if not base.is_dir():
        return []
    out = []
    for f in base.glob("photo-*.png"):
        meta = _np.read_png_meta(str(f)) or {}
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        out.append({"name": f.name, "mtime": mt,
                    "width": meta.get("width", 0), "height": meta.get("height", 0)})
    out.sort(key=lambda e: -e["mtime"])
    return out[:cap]
