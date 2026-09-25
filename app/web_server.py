#!/usr/bin/env python3
# =====================================================================
#  Nova Code - web face (v4.0): the SAME agent in the browser.
#  One program, one option:  python3 nova.py --web
#
#  This is NOT the old "simple chat page" (that one talked to Ollama
#  directly and had no agent). This server RUNS THE REAL AGENT:
#    - the same Session, tools, file protocol and auto-apply (backups!)
#    - the same provider layer: ANY local Ollama model OR any cloud brain
#    - notes from the agent console stream into the page live
#    - files it writes appear as chips; its Run: commands appear with a
#      Run button (explicit click - the browser never executes silently)
#
#  Wire format (NDJSON, one JSON object per line):
#    {"t":"note","text":...}  agent console line (tool calls, file changes)
#    {"t":"tok","text":...}   one token of the model's answer
#    {"t":"done", ...}        end of turn (+ files changed / proposed cmd)
#    {"t":"err","text":...}   error
#
#  Endpoints:
#    GET  /            the web app
#    GET  /favicon.ico / /favicon.svg   the app icon (same pixel mark as the header)
#    GET  /api/info    version / provider / model / workspace / status
#    POST /api/chat    {"message": "..."} -> streamed agent turn
#    POST /api/run     {"command": "..."} -> streamed command execution
#
#  Pure Python standard library. Bound to 127.0.0.1 by default - the
#  agent never leaves this machine. Serialized turns: one brain, one
#  user, so requests queue politely instead of corrupting the session.
#
#  v6.0: this is the Nova Assistant DASHBOARD face now - beyond the
#  coding agent it exposes the module layer (voice / photo / pixel /
#  flow / knowledge / platforms / per-module brain assignment).
# =====================================================================
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
import urllib.parse
import zlib
from http import cookies as http_cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import nova

# v6.3: security + logging layer (rate limiting, auth throttle, audit,
# secure mode). Optional like everything else - missing files degrade.
try:
    import nova_security as nsec
except Exception:
    nsec = None
try:
    import nova_log
except Exception:
    nova_log = None

# v6.0 module layer - each piece degrades independently, exactly like
# the v5 feature modules above nova.py.
try:
    import nova_platforms as nplatforms
except Exception:
    nplatforms = None
try:
    from nova_modules import MODULES as NMODULES
    from nova_modules import assign as nassign
    from nova_modules import flow as nflow
    from nova_modules import knowledge as nknowledge
    from nova_modules import photo as nphoto
    from nova_modules import pixelart as npixel
    from nova_modules import voice as nvoice
    from nova_modules import module_data_dir as nmod_dir
    from nova_modules import module_status as nmod_status
except Exception:
    NMODULES = []
    nassign = nflow = nknowledge = nphoto = None
    npixel = nvoice = nmod_dir = nmod_status = None

def _resolve_web_dir(app_dir):
    """Where the web face lives.

    Packaged-exe note: when frozen (PyInstaller), __file__ lives inside
    the (onedir) bundle or the _MEIPASS extraction dir. The bundled path
    is tried first - that is where the spec's "--add-data web;web" lands
    the page. If it is missing (e.g. someone ships the exe without the
    data), fall back to a "web" folder next to the real executable, so
    the UI can be updated by swapping that folder without a rebuild."""
    d = Path(app_dir) / "web"
    if (d / "index.html").is_file():
        return d
    if getattr(sys, "frozen", False):
        e = Path(sys.executable).resolve().parent / "web"
        if (e / "index.html").is_file():
            return e
    return d


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = _resolve_web_dir(APP_DIR)

TURN_LOCK = threading.Lock()      # one agent turn at a time (shared Session)
MAX_BODY = 1_000_000              # 1 MB is plenty for a chat message
MAX_STT_BODY = 17_000_000         # base64 audio upload cap (~12 MB raw)
MAX_CMD = 500                     # /api/run command length cap
ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# ---- v6.4: the simple-conversation turn (گفت و گو tab) --------------------
TALK_TEMPERATURE = 0.7            # chattier than the coding modes
TALK_HISTORY_CAP = 40             # messages (20 turns) kept in RAM
TALK_SYSTEM = (
    "You are Nova, the friendly conversation side of Nova Assistant. This is the "
    "SIMPLE CHAT tab - a normal conversation, NOT a coding session:\n"
    "- Chat naturally: answer questions, explain ideas, brainstorm, translate, "
    "summarize, help with everyday writing.\n"
    "- You CANNOT read or write files or run commands in this tab. Web search "
    "MAY ride with a turn as a [WEB RESULTS - ...] system block: when one is "
    "present, ground your answer in those results, cite them inline like "
    "[1], [2], and say honestly when they do not answer the question. Without "
    "such a block, answer from your own knowledge and say when something "
    "time-sensitive may be outdated.\n"
    "- If the user asks you to build or change a real project or file, briefly say "
    "that coding lives in the separate Coding (کدنویسی) tab of this app, and offer "
    "to discuss or plan the idea here instead.\n"
    "- NEVER output === FILE: === or === EDIT: === blocks, 'Run:' lines, "
    "[SEARCH:]/[READ:] tokens, or any other agent protocol - plain prose only.\n"
    "- Compact, warm, human answers. Match the user's language: if they write "
    "Persian (Farsi), answer in simple Farsi; code snippets and technical terms "
    "stay English."
)
TALK_EMPTY_MSG = ("پاسخی از مدل دریافت نشد - اتصال مغز را بررسی کنید "
                  "(Ollama روشن است؟ / یا پروایدر ابری در دسترس است؟)")

# v7.12: Persian labels for the three talk web-search modes + the plain
# markdown the /search command drops into the chat bubble.
_TALK_WEB_FA = {"off": "خاموش", "auto": "خودکار", "always": "همیشه"}


def _talk_results_text(query, slim):
    """Markdown answer for a talk-side /search: numbered links (renderMd
    turns them into anchors), capped so the RAM history stays lean."""
    lines = ["نتایج وب برای «%s»:" % query]
    for i, r in enumerate(slim, 1):
        title = r.get("title") or r.get("domain") or r.get("url") or ""
        lines.append("%d. [%s](%s)" % (i, title, r.get("url", "")))
        if r.get("snippet"):
            lines.append("   %s" % r["snippet"])
    lines.append("_برای پرسیدن سوال درباره این نتایج، همین‌جا ادامه بده._")
    return "\n".join(lines)[:4000]

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
COOKIE_NAME = "nova_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30   # 30 days

STATE = None                      # set by serve(): _State instance
_EMIT_LOCK = threading.Lock()     # one chunked frame per write (v6.8.1)
AUTH_TOKEN = None                 # set by serve(): None = no auth (local bind)

# Same pixel "spark" mark as the page header (web/index.html), so the
# browser tab/bookmark icon matches the in-app brand instead of a blank
# or default globe icon.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8" '
    'shape-rendering="crispEdges">'
    '<rect width="8" height="8" fill="#0d1020"/>'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="8" y2="8" '
    'gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#ffc857"/>'
    '<stop offset="1" stop-color="#9b6bff"/>'
    '</linearGradient></defs>'
    '<rect x="3" y="0" width="2" height="1" fill="url(#g)"/>'
    '<rect x="3" y="1" width="2" height="1" fill="url(#g)"/>'
    '<rect x="1" y="2" width="6" height="1" fill="url(#g)"/>'
    '<rect x="0" y="3" width="8" height="1" fill="url(#g)"/>'
    '<rect x="0" y="4" width="8" height="1" fill="url(#g)"/>'
    '<rect x="1" y="5" width="6" height="1" fill="url(#g)"/>'
    '<rect x="3" y="6" width="2" height="1" fill="url(#g)"/>'
    '<rect x="3" y="7" width="2" height="1" fill="url(#g)"/>'
    '</svg>'
).encode("utf-8")


def _new_token():
    return secrets.token_urlsafe(24)


def _header_host_port(raw):
    """'localhost:8765' / '[::1]:8765' -> (hostname_lower, port_or_None)."""
    try:
        u = urllib.parse.urlparse("//" + (raw or ""))
        return (u.hostname or "").lower(), u.port
    except ValueError:
        return "", None


def _flag_safe(fn):
    """v7.2: evaluate one /api/info feature flag. A version-skewed or
    half-initialized nova_* module on disk must never kill the whole info
    endpoint - the panel polls it every 15 s and would show 'server
    unreachable' forever."""
    try:
        return bool(fn())
    except Exception:
        return False


def _state_safe(fn, *args):
    """v8.10.1 fix: evaluate one /api/info STATE exporter (web_ctx_state /
    web_guardian_state / web_probe_state / web_vision_state - they return
    DICTS the panel fields are read from). _flag_safe used to coerce the
    dict to a bare boolean, so the payload shipped 'ctx': true and every
    panel rendered its checkboxes from undefined fields - one Save then
    silently DISABLED the guardian/probe/vision/compaction in .nova/*.json.
    A failing exporter ships None (the panel shows the honest dash)."""
    try:
        return fn(*args)
    except Exception:
        return None


def _host_allowed(handler):
    """DNS-rebinding guard for the tokenless (loopback) mode: the Host
    header must name this machine. With a token active (LAN binds) any
    advertised hostname is fine - the token already protects those."""
    if AUTH_TOKEN is not None:
        return True
    host, _port = _header_host_port(handler.headers.get("Host"))
    return host in LOOPBACK_HOSTS


def _same_origin(handler):
    """CSRF guard for state-changing requests. A browser ALWAYS sends an
    Origin on cross-site fetch/XHR/form POSTs - so any Origin that does
    not match this server's Host is a drive-by attack and is rejected.
    Missing Origin (curl, tests, same-origin GET nav) is allowed.
    RFC 6454 origin = scheme + host + port - v7.4 audit fix: the SCHEME
    is now compared too, so an https:// origin can no longer ride a
    matching port against this plain-HTTP server."""
    origin = (handler.headers.get("Origin") or "").strip()
    if not origin:
        return True
    try:
        o = urllib.parse.urlparse(origin)
    except Exception:
        return False
    # v7.4 audit fix: RFC 6454 origin = scheme + host + port. This is a
    # plain-HTTP server - any other scheme (https:// riding a matching
    # port, chrome-extension://, ...) is a DIFFERENT origin by
    # definition. Checked FIRST: the port fast-path below used to
    # return before the scheme was ever looked at.
    if (o.scheme or "http").lower() != "http":
        return False
    # v6.9: 'null' is the opaque origin of a sandboxed iframe / data: page -
    # its sendBeacon() is never CORS-preflighted, so accepting it let ANY
    # web page silently drive this agent (write files, flip settings).
    # Nothing legitimate sends Origin: null to this server.
    if origin == "null":
        return False
    if not o.hostname:
        return False
    hh, hp = _header_host_port(handler.headers.get("Host"))
    if (o.hostname or "").lower() != hh:
        return False
    # v6.2.1 fix: normalize the default ports before comparing - before,
    # `Origin: http://127.0.0.1` (implicit :80) was accepted against
    # `Host: 127.0.0.1:8765` because BOTH ports looked "unspecified enough".
    # v8.10.1 fix: urlparse validates the port LAZILY - accessing .port on
    # a malformed origin ('http://127.0.0.1:abc') raises ValueError, which
    # used to escape this guard and kill the handler thread mid-dispatch
    # (dropped connection instead of a clean 403, guard chain bypassed).
    # _header_host_port wraps the same access for exactly this reason.
    try:
        op = o.port
    except ValueError:
        return False
    if op is not None and hp is not None:
        return op == hp
    # one side omitted the port: assume the scheme's default. This is a
    # plain-HTTP local server, so a missing Host port can only mean :80
    # (no X-Forwarded-Proto games - that header is client-controlled).
    return (op or 80) == (hp or 80)


def _json_content_type(handler):
    """True when Content-Type is application/json (charset suffix ok).
    Cross-site HTML forms can only send text/plain / multipart /
    urlencoded - requiring JSON closes that CSRF route for good."""
    ctype = (handler.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    return ctype == "application/json"


def _cookie_value(handler, name):
    raw = handler.headers.get("Cookie")
    if not raw:
        return None
    jar = http_cookies.SimpleCookie()
    try:
        jar.load(raw)
    except Exception:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


def _token_matches(token):
    # compare BYTES: secrets.compare_digest raises TypeError on non-ASCII
    # str input, which would turn a hostile cookie into a handler crash
    if not token or not AUTH_TOKEN:
        return False
    try:
        return secrets.compare_digest(token.encode("utf-8"), AUTH_TOKEN.encode("utf-8"))
    except (UnicodeError, AttributeError):
        return False


def _page_authed(handler, query):
    """GET / - accepts either the ?token= query (first visit, from the
    link printed at startup) or the cookie set by a previous visit."""
    if AUTH_TOKEN is None:
        return True
    qtoken = urllib.parse.parse_qs(query).get("token", [None])[0]
    return _token_matches(qtoken) or _token_matches(_cookie_value(handler, COOKIE_NAME))


def _api_authed(handler):
    """API calls are same-origin fetches, so the cookie alone is enough -
    no token is ever read from a URL/query here."""
    if AUTH_TOKEN is None:
        return _same_origin(handler) and _host_allowed(handler)
    return _token_matches(_cookie_value(handler, COOKIE_NAME))


class _State:
    """Everything the web face shares: one agent session, one workspace."""

    def __init__(self, workspace):
        nova.NONINTERACTIVE = True
        nova.USE_COLOR = False    # notes stream to the page, not a terminal
        self.sess = nova.Session(workspace)
        self.provider_error = ""
        # v6.4: the SIMPLE CHAT tab (گفت و گو) - same brain, no coding
        # protocol, own short RAM-only history so a conversation never
        # pollutes the coding agent's context (and vice versa).
        self.talk_history = []
        if nova.providers is not None:
            try:
                cfg = nova.providers.current()
                if cfg.get("kind") != "ollama":
                    self.sess.model = cfg.get("model", self.sess.model)
            except Exception as e:
                self.provider_error = str(e)


# --------------------------------------------------------------- PWA assets
# The installable-app surface: manifest + service worker + icons, ALL
# generated locally (the icons are drawn pixel-by-pixel with a tiny
# pure-Python PNG writer - no files, no dependencies, no CDN).
def _spark_png(size):
    """The pixel-spark mark as a PNG byte string (8x8 grid, scaled, with
    a 12.5% maskable-safe padding and the gold->violet gradient)."""
    mark = ("00100100", "00100100", "01111110", "11111111",
            "11111111", "01111110", "00100100", "00100100")
    pad = size // 8
    cell = (size - 2 * pad) / 8.0
    rows = []
    for y in range(size):
        row = bytearray()
        my = (y - pad) / cell
        in_band = 0 <= my < 8
        for x in range(size):
            r, g, b = 0x0d, 0x10, 0x20           # panel background
            if in_band:
                mx = (x - pad) / cell
                if 0 <= mx < 8 and mark[int(my)][int(mx)] == "1":
                    t = (x + y) / (2.0 * size)
                    r = int(0xff + (0x9b - 0xff) * t)
                    g = int(0xc8 + (0x6b - 0xc8) * t)
                    b = int(0x57 + (0xff - 0x57) * t)
            row += bytes((r, g, b))
        rows.append(b"\x00" + bytes(row))       # filter 0 per scanline
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))


ICONS = {"192": _spark_png(192), "512": _spark_png(512), "180": _spark_png(180)}

MANIFEST = json.dumps({
    "name": "Nova Assistant - local AI assistant",
    "short_name": "Nova Assistant",
    "description": "Nova Assistant (with the Nova Code coding module), in the browser and on your phone.",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#05060d",
    "theme_color": "#05060d",
    "lang": "fa",
    "dir": "rtl",
    "icons": [
        {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png",
         "purpose": "any maskable"},
        {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "any maskable"},
    ],
}, ensure_ascii=False, indent=1).encode("utf-8")

SW_JS = b'''"use strict";
/* Nova Assistant service worker: installable PWA + offline app shell.
   Never touches /api/* - the agent itself is always live. */
const CACHE = "nova-assistant-shell-v2";
const ASSETS = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];
self.addEventListener("install", (ev) => {
  ev.waitUntil(caches.open(CACHE).then((c) =>
    Promise.allSettled(ASSETS.map((u) => c.add(u)))
  ).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (ev) => {
  ev.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (ev) => {
  const url = new URL(ev.request.url);
  if (ev.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;      // always live
  if (url.pathname.startsWith("/icons/")) {
    ev.respondWith(caches.match(ev.request).then((hit) => hit || fetch(ev.request)));
    return;
  }
  if (ev.request.mode === "navigate" || url.pathname === "/") {
    // network-first for the app itself (updates arrive), cache as fallback
    ev.respondWith(fetch(ev.request).then((res) => {
      // v6.9: only cache OK responses - a 401 token page used to become
      // the offline "/" shell until the next successful online load
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put("/", copy)).catch(() => {});
      }
      return res;
    }).catch(() => caches.match("/").then((hit) => hit || fetch(ev.request))));
    return;
  }
  ev.respondWith(caches.match(ev.request).then((hit) => hit || fetch(ev.request)));
});
self.addEventListener("notificationclick", (ev) => {
  ev.notification.close();
  ev.waitUntil(self.clients.matchAll({type: "window"}).then((list) => {
    for (const cli of list) if ("focus" in cli) return cli.focus();
    return self.clients.openWindow("/");
  }));
});
'''


def _pwa_asset(path):
    """(content_bytes, content_type, cache_seconds) or None."""
    if path == "/manifest.webmanifest":
        return (MANIFEST, "application/manifest+json; charset=utf-8", 3600)
    if path == "/sw.js":
        return (SW_JS, "application/javascript; charset=utf-8", 0)
    if path == "/icons/icon-192.png":
        return (ICONS["192"], "image/png", 86400)
    if path in ("/icons/icon-512.png", "/apple-touch-icon.png"):
        return (ICONS["512"] if path.endswith("512.png") else ICONS["180"],
                "image/png", 86400)
    return None


class _ClientGone(Exception):
    pass


# =====================================================================
#  v6.0 MODULE API - the multi-section dashboard behind /api/*
#  Every endpoint goes through the SAME auth chain as the agent API
#  (same-origin -> JSON content-type -> Host check -> token) BEFORE it
#  reaches module code. File serving is containment-checked twice.
# =====================================================================
_FILE_TYPES = {".png": "image/png", ".wav": "audio/wav", ".mp3": "audio/mpeg",
               ".ogg": "audio/ogg", ".flac": "audio/flac",
               ".json": "application/json"}
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,120}$")
_GALLERY_KINDS = ("pixel", "photo", "voice")


def _mod_ok(handler):
    """503 with a clean message when the module layer failed to import."""
    if not (nassign and nmod_dir):
        handler._send_json({"error": "module layer unavailable"}, 501)
        return False
    if STATE is None:
        handler._send_json({"error": "server is still starting"}, 503)
        return False
    return True


def _module_gallery_dir(kind, ws):
    """Data dir for a gallery kind - None when unknown."""
    if kind not in _GALLERY_KINDS:
        return None
    try:
        return nmod_dir(ws, kind, create=False)
    except Exception:
        return None


def _serve_module_file(handler, ws, kind, name):
    """GET /api/file - module outputs only, basename-validated, served
    from INSIDE the module dir (a match against an actual dir entry,
    so traversal/symlink tricks cannot escape)."""
    if not _FILE_NAME_RE.match(name or ""):
        handler._send_json({"error": "bad file name"}, 400)
        return
    d = _module_gallery_dir(kind, ws)
    if d is None:
        handler._send_json({"error": "unknown module"}, 404)
        return
    target = d / name
    ctype = _FILE_TYPES.get(target.suffix.lower())
    if ctype is None or not target.is_file():
        handler._send_json({"error": "not found"}, 404)
        return
    try:
        resolved = target.resolve()
        resolved.relative_to(d.resolve())
    except (ValueError, OSError):
        handler._send_json({"error": "not found"}, 404)
        return
    try:
        body = target.read_bytes()
    except OSError:
        handler._send_json({"error": "not found"}, 404)
        return
    handler.send_response(200)
    # v7.1.0: user-generated module media served 200 without nosniff -
    # every other 200 path sets the security headers (v6.7 rule)
    handler._security_headers()
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "private, max-age=3600")
    handler.end_headers()
    handler.wfile.write(body)


def _gallery_json(ws, kind, cap=60):
    if kind == "pixel":
        items = npixel.list_gallery(ws, cap)
    elif kind == "photo":
        items = nphoto.list_gallery(ws, cap)
    else:
        items = nvoice.list_history(ws, cap)
    for it in items:
        it["url"] = "/api/file?k=%s&name=%s&v=%d" % (
            kind, urllib.parse.quote(it.get("name", ""), safe=""),
            int(it.get("mtime", 0)))
    return items


# ---------------- v6.8.2: module kill-switch ------------------------
# The four media/automation modules (voice / photo / pixel / flow) are
# DISABLED by default on the web surface: product focus right now is the
# two chat surfaces (code chat + normal talk). The web tab buttons ship
# disabled AND every API endpoint of a disabled module answers a clean
# 403 here, so the modules are truly unreachable - not just hidden.
# Re-enable without code edits: NOVA_DISABLED_MODULES="" (empty value)
# or any custom comma list, e.g. NOVA_DISABLED_MODULES="pixel,flow".
_DISABLEABLE_MODULES = ("voice", "photo", "pixel", "flow")
_DISABLED_MODULES_DEFAULT = "voice,photo,pixel,flow"
_MODULE_FA_NAMES = {"voice": "صدا", "photo": "تصویر",
                    "pixel": "پیکسل‌آرت", "flow": "جریان کار"}


def _disabled_modules():
    """Parsed NOVA_DISABLED_MODULES (default: all four off)."""
    raw = os.environ.get("NOVA_DISABLED_MODULES", _DISABLED_MODULES_DEFAULT)
    return {m.strip().lower() for m in raw.split(",") if m.strip()}


def _disabled_module_hit(path, query):
    """The disabled module this request belongs to, or None."""
    dis = _disabled_modules()
    if not dis:
        return None
    for m in _DISABLEABLE_MODULES:
        if m in dis and (path == "/api/" + m
                         or path.startswith("/api/" + m + "/")):
            return m
    # /api/flows, /api/flow, /api/flow_status, /api/flow/<op> - all flow
    if "flow" in dis and path.startswith("/api/flow"):
        return "flow"
    # gallery/file are kind-parameterised (k=voice|photo|pixel|...)
    if path in ("/api/gallery", "/api/file"):
        q = urllib.parse.parse_qs(query or "")
        kind = (q.get("k", [""])[0] or "").strip().lower()
        if kind in dis and kind in _DISABLEABLE_MODULES:
            return kind
    return None


def _send_disabled(handler, module):
    handler._send_json(
        {"error": "بخش «%s» فعلاً غیرفعال است — تمرکز فعلی نوا روی گفت و گو "
                  "و کدنویسی است." % _MODULE_FA_NAMES[module],
         "module": module, "disabled": True}, 403)


def _module_get(handler, path, query):
    """The v6.0 GET surface. Returns True when handled."""
    hit = _disabled_module_hit(path, query)      # v6.8.2 kill-switch
    if hit:
        _send_disabled(handler, hit)
        return True
    ws = STATE.sess.ws
    if path == "/api/modules":
        rows = []
        for m in NMODULES:
            row = dict(m)
            row.pop("default", None)
            row["cfg"] = nassign.resolve(ws, m["id"]) if m["assignable"] else None
            row["status"] = nmod_status(ws, m["id"])
            rows.append(row)
        handler._send_json({"modules": rows})
        return True
    if path == "/api/models_all":
        out = {"ollama": [], "files": [], "platforms": [], "cloud": [],
               "by_category": {}, "folders": [],
               "platforms_cfg": nplatforms.all_platforms(ws) if nplatforms else []}
        prov = nova._provider_cfg()
        if prov.get("kind") == "ollama":
            try:
                tags = nova.http_get_json("/api/tags", timeout=4)
                import nova_models
                out["ollama"] = nova_models.web_list(nova_models.parse_tags(tags), cap=100)
            except Exception:
                pass
        try:
            import nova_localmodels as lmodels
            dirs = lmodels.model_dirs(ws)
            out["folders"] = [{"label": lb, "path": str(p), "exists": ex}
                              for lb, p, ex in dirs]
            out["categories"] = {"general": "همه بخش‌ها",
                                 "code": "Nova Code / Flow",
                                 "voice": "Nova Voice",
                                 "photo": "Nova Photo"}
            # scan_dirs takes the (label, path, exists) TUPLES - v6.0
            # unpacked them into bare Paths here, the TypeError was
            # swallowed and the file models silently vanished from the
            # web UI (found by the v6.1 tests)
            entries = lmodels.scan_dirs(dirs)
            for e in entries:
                row = {"id": e["id"], "name": e["name"],
                       "size": e.get("size") or 0,
                       "category": e.get("category", "general"),
                       "format": e.get("format", "gguf")}
                if e.get("runnable"):
                    out["files"].append(row)
                (out["by_category"].setdefault(
                    e.get("category", "general"), [])).append(row)
        except Exception:
            pass
        try:
            import nova_providers
            out["cloud"] = [n for n in nova_providers.names() if n != "ollama"]
        except Exception:
            pass
        handler._send_json(out)
        return True
    if path == "/api/gallery":
        q = urllib.parse.parse_qs(query)
        kind = (q.get("k", [""])[0] or "").strip()
        if kind not in _GALLERY_KINDS:
            handler._send_json({"error": "unknown gallery kind"}, 400)
            return True
        try:
            handler._send_json({"items": _gallery_json(ws, kind)})
        except Exception as e:
            handler._send_json({"error": type(e).__name__}, 500)
        return True
    if path == "/api/file":
        q = urllib.parse.parse_qs(query)
        _serve_module_file(handler, ws, (q.get("k", [""])[0] or "").strip(),
                           (q.get("name", [""])[0] or "").strip())
        return True
    if path == "/api/flows":
        # v6.2.1 fix: a broken flows dir / vanishing run file (pruned between
        # glob and stat) used to escape as an unhandled exception and kill
        # the response - the client saw an empty reply instead of an error.
        try:
            handler._send_json({"flows": nflow.list_flows(ws),
                                "runs": nflow.list_runs(ws),
                                "sample": nflow.SAMPLE})
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 500)
        return True
    if path == "/api/flow":
        q = urllib.parse.parse_qs(query)
        # v6.2.1 fix: nflow.get raises ModuleError on an invalid/empty name
        # (e.g. GET /api/flow with no ?name=) - that used to escape the
        # handler and the client got a connection close with NO response.
        try:
            f = nflow.get(ws, (q.get("name", [""])[0] or "").strip())
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 400)
            return True
        if f is None:
            handler._send_json({"error": "flow not found"}, 404)
        else:
            handler._send_json(f)
        return True
    if path == "/api/flow_status":
        q = urllib.parse.parse_qs(query)
        try:
            snap = nflow.run_status(ws, (q.get("run", [""])[0] or "").strip())
        except Exception as e:
            # v6.8.1: a torn/corrupt run file used to kill the handler
            # thread - the browser got a dropped connection instead of a
            # clean error (same fix /api/flows got in v6.2.1).
            handler._send_json({"error": f"flow status failed: {e}"}, 500)
            return True
        if snap is None:
            handler._send_json({"error": "run not found"}, 404)
        else:
            handler._send_json(snap)
        return True
    if path == "/api/knowledge":
        q = urllib.parse.parse_qs(query)
        text = (q.get("q", [""])[0] or "").strip()
        try:
            kk = int((q.get("k", ["6"])[0] or "6"))
        except ValueError:
            kk = 6
        try:
            hits = nknowledge.search(ws, text, k=kk)
            stats = nknowledge.stats(ws)
        except Exception as e:
            # v6.8.1: same guard - a corrupt knowledge store must answer
            # with a JSON error, not a closed socket.
            handler._send_json({"error": f"knowledge search failed: {e}"}, 500)
            return True
        handler._send_json({"hits": hits, "stats": stats})
        return True
    if path == "/api/intel":
        # v7.13: the live agent dashboard (state only - mutations POST).
        handler._send_json(nova.web_intel_state(STATE.sess))
        return True
    if path == "/api/blackbox":
        # v8.0: the agent's black box (read-only, newest last).
        try:
            import nova_flightlog as _flog
            # NOTE: `query` arrives as the RAW query STRING here - parse
            # it ourselves (the /api/blackbox?n=50&filter=x form)
            q = urllib.parse.parse_qs(query or "")
            n = 60
            try:
                qn = (q.get("n") or [""])[0]
                if qn.isdigit():
                    n = max(1, min(int(qn), 240))
            except Exception:
                pass
            flt = (q.get("filter") or [""])[0] or None
            entries = _flog.read_file(n=n, where_prefix=flt)
            if not entries:
                entries = _flog.recent(n=n, where_prefix=flt)
            handler._send_json({"entries": entries,
                                "state": _flog.state()})
        except Exception as e:
            handler._send_json({"entries": [],
                                "error": str(e)[:200]})
        return True
    if path == "/api/plugins":
        # v8.0: the plugin system (state only - run/reload POST).
        try:
            import nova_plugins as _plugins
            handler._send_json(_plugins.web_state(STATE.sess.ws))
        except Exception as e:
            handler._send_json({"plugins": [], "errors": [str(e)[:200]],
                                "version": "8.0"})
        return True
    return False


def _module_post(handler, path):
    """The v6.0 POST surface (body already validated as JSON by the
    common guard chain). Returns True when handled."""
    ws = STATE.sess.ws
    data = {}
    cap = MAX_STT_BODY if path == "/api/voice/stt" else MAX_BODY
    try:
        data = handler._read_body(cap)
    except ValueError as e:
        handler._send_json({"error": str(e)}, 400)
        return True
    # v6.8.2 kill-switch - AFTER the body read (HTTP/1.1 keep-alive: an
    # unread body would desync the next request on this connection).
    hit = _disabled_module_hit(path, "")
    if hit:
        _send_disabled(handler, hit)
        return True

    if path == "/api/assign":
        try:
            saved = nassign.save_module(ws, str(data.get("module", "")), data)
            handler._send_json({"ok": True, "cfg": saved})
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 400)
        return True
    if path == "/api/assign/clear":
        # v8.10.1: guarded like its siblings - a failing optional-module
        # call used to escape do_POST and kill the handler thread (dropped
        # connection instead of a clean error).
        try:
            okc = nassign.clear_module(ws, str(data.get("module", "")))
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 400)
            return True
        handler._send_json({"ok": okc})
        return True
    if path == "/api/platforms/save" or path == "/api/platforms/scan":
        # v6.5: nplatforms has its own optional import; when it failed, the
        # AttributeError used to escape do_POST and kill the handler thread
        # -> the browser got a dropped connection instead of a clean error
        # (the GET side already guarded this exact case).
        if nplatforms is None:
            handler._send_json({"error": "platform layer unavailable"}, 501)
            return True
    if path == "/api/platforms/save":
        try:
            saved = nplatforms.save_config(ws, data.get("platforms") or [])
            handler._send_json({"ok": True, "platforms": saved})
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 400)
        return True
    if path == "/api/platforms/scan":
        # v8.10.1: guarded like /api/platforms/save - scan probes the
        # network and filesystem; a raise used to kill the handler thread.
        try:
            results = nplatforms.scan(ws, include_presets=bool(
                data.get("include_presets", True)), timeout=2.5)
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 500)
            return True
        handler._send_json({"results": results})
        return True
    if path == "/api/voice/tts":
        text = str(data.get("text", ""))
        cfg = nassign.resolve(ws, "voice")
        try:
            r = nvoice.synthesize(ws, text, cfg,
                                  want_engine=str(data.get("engine", "")) or None)
            r["url"] = "/api/file?k=voice&name=%s&v=%d" % (
                urllib.parse.quote(r["name"], safe=""), int(time.time() * 1000))
            handler._send_json({"ok": True, **r})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 502)
        return True
    if path == "/api/voice/stt":
        import base64
        raw = b""
        try:
            raw = base64.b64decode(str(data.get("data_b64", "")), validate=False)
        except Exception:
            handler._send_json({"error": "invalid base64 audio"}, 400)
            return True
        cfg = nassign.resolve(ws, "voice")
        if not cfg.get("url"):
            cfg["url"] = "http://127.0.0.1:8080/v1"   # whisper.cpp/LocalAI default
        try:
            text = nvoice.transcribe(ws, raw, cfg,
                                     filename=str(data.get("name", "audio.wav")))
            handler._send_json({"ok": True, "text": text})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 502)
        return True
    if path == "/api/photo/generate":
        cfg = dict(nassign.resolve(ws, "photo"))
        if str(data.get("engine", "")):
            cfg["backend"] = str(data["engine"])
        try:
            r = nphoto.generate(ws, str(data.get("prompt", "")), cfg,
                                size=int(data.get("size", 512) or 512))
            r["url"] = "/api/file?k=photo&name=%s&v=%d" % (
                urllib.parse.quote(r["name"], safe=""), int(time.time() * 1000))
            handler._send_json({"ok": True, **r})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 502)
        return True
    if path == "/api/pixel/generate":
        try:
            r = npixel.generate(ws, str(data.get("prompt", "")),
                                size=int(data.get("size", 32) or 32),
                                palette=str(data.get("palette", "")) or None,
                                symmetry=str(data.get("symmetry", "")) or None,
                                seed=str(data.get("seed", "")) or None,
                                scale=int(data.get("scale", 8) or 8))
            r["url"] = "/api/file?k=pixel&name=%s&v=%d" % (
                urllib.parse.quote(r["name"], safe=""), int(time.time() * 1000))
            handler._send_json({"ok": True, **r})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 400)
        return True
    if path == "/api/pixel/upscale":
        try:
            path_out, _sz = npixel.render_from_grid(
                ws, str(data.get("name", "")), int(data.get("scale", 16) or 16))
            name = Path(path_out).name
            handler._send_json({"ok": True, "name": name, "path": path_out,
                                "url": "/api/file?k=pixel&name=%s&v=%d" % (
                                    urllib.parse.quote(name, safe=""),
                                    int(time.time() * 1000))})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 400)
        return True
    if path == "/api/flow/save":
        try:
            norm = nflow.save(ws, {"name": data.get("name"),
                                   "steps": data.get("steps")})
            handler._send_json({"ok": True, "flow": norm})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 400)
        return True
    if path == "/api/flow/delete":
        # v6.2.1 fix: flow.delete now validates the name (raises ModuleError
        # on traversal attempts) - return it as a clean 400, not a dropped
        # connection; previously ANY name was joined into a filesystem path.
        try:
            okd = nflow.delete(ws, str(data.get("name", "")))
            handler._send_json({"ok": okd})
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 400)
        return True
    if path == "/api/flow/run":
        name = str(data.get("name", "")).strip()
        try:
            f = nflow.get(ws, name)
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 400)
            return True
        if f is None:
            handler._send_json({"error": "flow not found"}, 404)
            return True
        inputs = data.get("inputs")
        if not isinstance(inputs, dict):
            inputs = {}
        try:
            run_id, snap = nflow.run_async(ws, f, inputs=inputs)
            handler._send_json({"ok": True, "run_id": run_id, "status": snap["status"]})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 502)
        return True
    if path == "/api/knowledge/ingest":
        try:
            r = nknowledge.ingest(ws, data.get("paths") or [])
            handler._send_json({"ok": True, **r})
        except Exception as e:
            handler._send_json({"error": str(e)[:300]}, 400)
        return True
    if path == "/api/knowledge/reset":
        # v8.10.1: guarded like the other module endpoints.
        try:
            handler._send_json({"ok": True, **nknowledge.reset(ws)})
        except Exception as e:
            handler._send_json({"error": str(e)[:200]}, 500)
        return True
    return False


def _make_server(args):
    """Build (not start) the ThreadingHTTPServer - split out so the QA
    suite can bind an ephemeral port and talk to the real handlers."""
    return ThreadingHTTPServer((args["host"], args["port"]), Handler)


def serve(args):
    """Start the web face. Returns only on Ctrl+C."""
    global STATE, AUTH_TOKEN
    # v6.2.1 fix: honor NOVA_WORKSPACE like the terminal face and the
    # module commands do - the env var used to be silently ignored here
    _ws_env = (args.get("workspace") or os.environ.get("NOVA_WORKSPACE", "")
               or "nova-workspace")
    workspace = Path(_ws_env).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    STATE = _State(workspace)

    # v5.1: same model resolution as the terminal face - honour profile /
    # NOVA_MODEL, else auto-pick the best installed local model.
    prov0 = nova._provider_cfg()
    if prov0.get("kind") == "ollama":
        STATE.sess.model = nova.resolve_session_model(STATE.sess)
        # v8.7: keep the sess-less vision hooks on the ACTUAL boot brain.
        nova._VISION_ACTIVE["model"] = STATE.sess.model

    # ONE sanitized host for BOTH the bind and the auth decision - binding
    # the raw arg once let --host "" bind 0.0.0.0 while auth thought it was
    # loopback (network access with NO token). parse_args already rejects
    # an empty --host; this is the defensive second layer.
    host = (args.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    # v6.3: secure mode demands the access token EVEN on loopback - a
    # drive-by page on the user's machine can fetch http://localhost:port
    # (same-origin blocks reading it, but why rely on that alone).
    secure_on = nsec.is_secure(workspace) if nsec else False
    AUTH_TOKEN = _new_token() if (host not in LOOPBACK_HOSTS or secure_on) else None
    bind_args = dict(args)
    bind_args["host"] = host

    httpd = _make_server(bind_args)
    port = httpd.server_address[1]
    url = f"http://localhost:{port}" + (f"/?token={AUTH_TOKEN}" if AUTH_TOKEN else "")
    prov = nova._provider_cfg()
    print("")
    print("  Nova Assistant v" + nova.VERSION + " - web face (the same agent)")
    print("  Brain     : " + prov["label"] + "  (model: " + str(STATE.sess.model or "none yet") + ")")
    print("  Workspace : " + str(STATE.sess.ws))
    if STATE.provider_error:
        print("  [!] provider problem: " + STATE.provider_error)
        print("      fix the key / settings, or run:  /provider ollama  in the page")
    if AUTH_TOKEN:
        print("  [!] bound to " + host + " - reachable from other devices, so a")
        print("      one-time access token is required (kept as a cookie after that):")
        print("        http://" + host + ":" + str(port) + "/?token=" + AUTH_TOKEN)
    print("  Open      : " + url)
    print("  Stop      : Ctrl+C here")
    print("")
    nova.open_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")
    finally:
        # a selected model FILE may have spawned llama.cpp - never leak it
        if nova.lmodels is not None:
            nova.lmodels.stop_all()
        # v6.2.1: close the listening socket cleanly (was process-exit only)
        try:
            httpd.server_close()
        except Exception:
            pass


_MODULE_POST_PATHS = frozenset({
    "/api/assign", "/api/assign/clear", "/api/platforms/save",
    "/api/platforms/scan", "/api/voice/tts", "/api/voice/stt",
    "/api/photo/generate", "/api/pixel/generate", "/api/pixel/upscale",
    "/api/flow/save", "/api/flow/run", "/api/flow/delete",
    "/api/knowledge/ingest", "/api/knowledge/reset",
})


class Handler(BaseHTTPRequestHandler):
    server_version = "NovaAssistant"   # no version disclosure in the Server header
    sys_version = ""
    protocol_version = "HTTP/1.1"
    # v6.2.1 hardening: cap how long ONE connection may sit idle / stall
    # mid-request. Without this, HTTP/1.1 keep-alive clients that open
    # sockets and never finish a request pinned a handler thread + fd each,
    # accumulating threads forever (local-only exposure, but free to fix).
    timeout = 60

    def log_message(self, fmt, *args):
        pass  # the agent's own notes are the show - keep the console clean

    def _log_denied(self, why):
        """One line for DENIED requests (auth/CSRF/rebind) - failed attempts
        stay visible without flooding the console with normal traffic."""
        print("[web] denied (" + why + "): " + self.address_string() + " " + self.path)
        if nsec is not None:
            nsec.audit(STATE.sess.ws if STATE else None, "web-denied",
                       self.path[:200], origin="web", verdict="deny", reason=why)

    # ------------------------------------------------ security guards (v6.3)
    def _security_headers(self, html=False):
        """Defense-in-depth headers on every response. The page uses inline
        script/style, so 'unsafe-inline' is required there - the policy still
        blocks every REMOTE source (exfiltration / CDN injection)."""
        try:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if html:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                    "connect-src 'self'; font-src 'self'")
        except Exception as e:
            if nova_log is not None:
                nova_log.soft("web.headers", e)

    def _throttled(self):
        """True while this client IP is locked out for repeated bad tokens.
        Sends the 429 itself; caller just returns."""
        if nsec is None:
            return False
        ok, retry = nsec.AUTH_THROTTLE.check(self.client_address[0])
        if ok:
            return False
        body = json.dumps({"error":
                           "too many failed attempts - try again in %ss" % retry},
                          ensure_ascii=False).encode("utf-8")
        # v6.9: like every >=400 JSON path - the request body was never
        # read, so the connection MUST close (HTTP/1.1 keep-alive would
        # parse the unread body as the next request).
        self.close_connection = True
        self.send_response(429)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", str(retry))
        self.send_header("Connection", "close")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)
        return True

    def _rate_limited(self, path):
        """Token-bucket rate limit on the API surface (per client IP).
        Sends 429 and returns True when the bucket is empty. Secure mode
        tightens the limits. Static/page GETs are NOT limited."""
        if nsec is None or not path.startswith("/api/"):
            return False
        limiter = nsec.API_LIMITER
        if STATE is not None and nsec.is_secure(STATE.sess.ws):
            limiter = nsec.SECURE_API_LIMITER
        if limiter.allow(self.client_address[0]):
            return False
        nsec.audit(STATE.sess.ws if STATE else None, "web-ratelimit",
                   path[:200], origin="web", verdict="deny", reason="rate limit")
        body = json.dumps({"error": "rate limit exceeded - slow down"},
                          ensure_ascii=False).encode("utf-8")
        # v6.9: same unread-body desync fix as _throttled above
        self.close_connection = True
        self.send_response(429)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", "5")
        self.send_header("Connection", "close")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)
        return True

    # ------------------------------------------------------------ helpers
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        if code >= 400:
            # the request body may not have been read yet; with HTTP/1.1
            # keep-alive those unread bytes would be parsed as the NEXT
            # request on this connection (request-smuggling-style desync).
            # Closing the connection makes that impossible.
            self.close_connection = True
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, cap=None):
        limit = cap or MAX_BODY
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > limit:
            raise ValueError("bad request body size")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("request body must be JSON")
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    # ------------------------------------------------------------ helpers (auth)
    def _send_unauthorized_page(self):
        if nsec is not None:
            # v6.3: every failed token attempt feeds the brute-force lockout
            nsec.AUTH_THROTTLE.fail(self.client_address[0])
            nsec.audit(STATE.sess.ws if STATE else None, "web-auth", "",
                       origin="web", verdict="deny", reason="bad token (page)")
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<body style='font-family:sans-serif;background:#05060d;color:#e9ecf8;"
            "padding:40px'><h1>Access token required</h1>"
            "<p>This Nova Assistant server is bound to a non-local address. "
            "Open it using the link with <code>?token=...</code> printed in the "
            "terminal where you started <code>nova.py --web</code>.</p></body>"
        ).encode("utf-8")
        self.close_connection = True   # body unread - never reuse the conn
        self.send_response(401)
        # v7.1.0: the 401 page was the only HTML path without the standard
        # security headers (X-Content-Type-Options etc, v6.7 rule)
        self._security_headers(html=True)
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_unauthorized_json(self):
        if nsec is not None:
            nsec.AUTH_THROTTLE.fail(self.client_address[0])
            nsec.audit(STATE.sess.ws if STATE else None, "web-auth", "",
                       origin="web", verdict="deny", reason="bad token (api)")
        self._send_json({"error": "unauthorized - open the link with the access "
                                   "token shown in the terminal"}, 401)

    # ------------------------------------------------------------ GET
    def _drain_body(self):
        """v7.4 audit fix: a GET (or any routed method) that arrives WITH
        a Content-Length used to leave the body bytes unread on the
        keep-alive socket - the next loop iteration parsed them as a
        pipelined request (request smuggling on one connection). The
        body is now consumed (capped) before any response."""
        try:
            n = int(str(self.headers.get("Content-Length") or "0")
                    .strip() or "0")
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            return
        remaining = min(n, 1_000_000)
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass
        # v7.9: when the body exceeded the drain cap there are still
        # unread bytes on the socket - a 200 response does not close the
        # connection, so the tail parsed as the NEXT request (proven:
        # a pipelined /api/info executed after a 2MB-body GET). Close
        # instead - the guard chain never sees an unsanctioned request.
        if n > 1_000_000:
            self.close_connection = True

    def do_GET(self):
        self._drain_body()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self._throttled():                      # v6.3: brute-force lockout
            return
        if self._rate_limited(path):               # v6.3: API rate limit
            return
        if path in ("/favicon.ico", "/favicon.svg"):
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(FAVICON_SVG)))
            self.send_header("Cache-Control", "public, max-age=86400")
            # v6.7: defense-in-depth consistency - these routes skipped the
            # security headers every JSON path carries (nosniff matters).
            self._security_headers()
            self.end_headers()
            self.wfile.write(FAVICON_SVG)
            return
        # ---- PWA statics (no secrets inside; still Host-checked) --------
        asset = _pwa_asset(path)
        if asset is not None:
            if not _host_allowed(self):
                self._log_denied("host header")
                self._send_json({"error": "unknown host header"}, 403)
                return
            body, ctype, cache_s = asset
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", f"public, max-age={cache_s}")
            if path == "/sw.js":
                self.send_header("Service-Worker-Allowed", "/")
            # v6.7: same header consistency as the favicon route
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/", "/index.html"):
            if not _host_allowed(self):
                # DNS-rebinding: an attacker page resolving evil.com to
                # 127.0.0.1 would arrive with a non-loopback Host header
                self._log_denied("host header")
                self._send_json({"error": "unknown host header"}, 403)
                return
            if not _page_authed(self, parsed.query):
                self._send_unauthorized_page()
                return
            page = WEB_DIR / "index.html"
            if not page.is_file():
                self._send_json({"error": "web/index.html is missing"}, 500)
                return
            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers(html=True)
            if AUTH_TOKEN:
                self.send_header(
                    "Set-Cookie",
                    f"{COOKIE_NAME}={AUTH_TOKEN}; Path=/; HttpOnly; SameSite=Lax; "
                    f"Max-Age={COOKIE_MAX_AGE}")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/info":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            prov = nova._provider_cfg()
            ollama_ok = None
            models = []
            local_models = []
            models_dirs = []
            sess = STATE.sess          # (defined early - used by both blocks)
            if prov.get("kind") == "ollama":
                try:
                    tags = nova.http_get_json("/api/tags", timeout=4)
                    ollama_ok = True
                    if nova.nmodels is not None:
                        models = nova.nmodels.web_list(nova.nmodels.parse_tags(tags))
                except Exception:
                    ollama_ok = False
                # v5.2: the SECOND local source - .gguf files in the
                # model folders. Shown even when Ollama is down: the
                # llama.cpp fallback still makes them usable.
                if nova.lmodels is not None:
                    try:
                        for e in nova.list_local_models(sess.ws)[:60]:
                            local_models.append({
                                "id": e.get("id", ""),
                                "name": e.get("name", ""),
                                "size": nova.nmodels.fmt_size(e.get("size"))
                                        if nova.nmodels else str(e.get("size") or ""),
                                "arch": e.get("arch", ""),
                                "quant": e.get("quant", ""),
                                "runnable": bool(e.get("runnable")),
                                "note": e.get("note", "")})
                        models_dirs = [str(p) for _l, p, _e
                                       in nova.lmodels.model_dirs(sess.ws)]
                    except Exception:
                        local_models = []
            else:
                # v6.6: a cloud / local-API provider - serve the
                # AUTO-DETECTED model list from the workspace cache.
                # NO network in /api/info: discovery runs explicitly
                # (on key save / the provider panel's detect button).
                if nova.providers is not None:
                    try:
                        models = [{"name": m, "size": "", "params": ""}
                                  for m in nova.providers.cached_models(
                                      prov.get("name", ""))[:60]]
                    except Exception:
                        models = []
            # ---- v5.0 live state for the UI ------------------------------
            cost = None
            if nova.nova_cost is not None:
                try:
                    rep = nova.nova_cost.report(sess.ws)
                    cost = {"turns": rep["today"]["turns"],
                            "cost": rep["today"]["cost"],
                            "total_cost": rep["total"]["cost"]}
                except Exception:
                    cost = None
            bg_running = bg_recent = 0
            bg_finished = []
            if nova.nova_bg is not None:
                try:
                    tasks = nova.nova_bg.list_tasks(sess.ws)
                    bg_running = sum(1 for t in tasks if t.get("status") == "running")
                    bg_finished = [{"id": t["id"], "cmd": t.get("cmd", ""),
                                    "status": t.get("status")}
                                   for t in tasks if t.get("status") != "running"][:5]
                    bg_recent = len(bg_finished)
                except Exception:
                    pass
            # v7.5: who serves the coding turns (for the panel's badge).
            # Fail-soft: a broken provider config must not kill /api/info.
            try:
                backend_flag = "local" if sess._local_brain() else "cloud"
            except Exception:
                backend_flag = "local"
            self._send_json({
                "agent": nova.AGENT_NAME,
                "version": nova.VERSION,
                "codename": getattr(nova, "CODENAME", ""),
                "provider": prov.get("name", "ollama"),
                "provider_label": prov.get("label", ""),
                "provider_kind": prov.get("kind", ""),
                "provider_error": STATE.provider_error,
                "model": sess.model,
                "models": models,
                "local_models": local_models,
                "models_dirs": models_dirs,
                "workspace": str(sess.ws),
                # v6.7: workspace_name is DISPLAY only; the UI must key its
                # localStorage buckets on the FULL path ('workspace') - two
                # different projects named 'nova-workspace' used to share
                # one chat-history bucket.
                "workspace_name": sess.ws.name or str(sess.ws),
                "ollama_ok": ollama_ok,
                "explain": bool(sess.explain),
                "confirm_changes": bool(getattr(sess, "confirm_changes", False)),
                "autotest": bool(sess.autotest),
                "autofix": bool(getattr(sess, "autofix", True)),
                "todo": sess.todo,
                "todo_progress": nova.nova_todo.progress(sess.todo) if nova.nova_todo else "",
                "cost": cost,
                "bg_running": bg_running,
                "bg_recent": bg_recent,
                "bg_finished": bg_finished,
                "pending_apply": bool(getattr(sess, "pending_apply", None)),
                "git_repo": bool(nova.commitmsg and nova.commitmsg.is_repo(sess.ws)),
                "modules_ok": bool(nassign),
                "secure": bool(nsec.is_secure(sess.ws)) if nsec else False,
                # v7.0: the deterministic design engine (beauty floor) state
                # v7.2: + the internet-images engine (real photos) state.
                # A version-skewed module on disk must never kill the whole
                # info endpoint (the panel polls it every 15 s).
                "design": _flag_safe(lambda: bool(
                    nova.design and nova.design.enabled())),
                "images": _flag_safe(lambda: bool(
                    getattr(nova, "imgsys", None) and nova.imgsys.available())),
                # v7.3: the local font library (Persian + English pairings)
                "fonts": _flag_safe(lambda: bool(
                    getattr(nova, "fontsys", None) and nova.fontsys.available())),
                # v7.5: the backend-aware power features (router/speculative/
                # explore/rag/style) - the panel shows what is live
                "backend": backend_flag,
                # v8.3: the context engine (per-backend windows + smart
                # compression) state for the Models-tab panel
                "ctx": _state_safe(nova.web_ctx_state, sess),
                # v8.4: the code guardian (supervisor + language fleet)
                # state for its Models-tab panel
                "guardian": _state_safe(nova.web_guardian_state, sess),
                # v8.5: the bug hunter (behavior probes) state for its
                # Models-tab panel
                "probe": _state_safe(nova.web_probe_state, sess),
                # v8.6: the vision layer - the live "can the local brain
                # see photos?" answer + the approval policy
                "vision": _state_safe(nova.web_vision_state, sess),
                "explore": _flag_safe(lambda: bool(
                    getattr(nova, "explore", None)
                    and getattr(nova, "backend_policy", None))),
                "rag": _flag_safe(lambda: bool(getattr(nova, "rag", None))),
                "style": _flag_safe(lambda: bool(getattr(nova, "style", None))),
                "git_history": _flag_safe(lambda: bool(
                    nova.commitmsg and os.environ.get("NOVA_NO_GIT", "") != "1"
                    and nova.commitmsg.history_mode(sess.ws) != "none")),
            })
            return
        # ---- v6.6 provider panel state (same guard chain as /api/info) --
        if path == "/api/providers":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            # v7.9: the sibling endpoints (/api/doctor, /api/graph) wrap
            # their builder - an exception here must answer 500 JSON, not
            # drop the connection on the browser.
            try:
                self._send_json(nova.web_providers_state(STATE.sess))
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 500)
            return
        # ---- v7.11 Iranian services panel (same guard chain) ------------
        if path == "/api/iran":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            try:
                self._send_json(nova.web_iran_state(STATE.sess))
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 500)
            return
        # ---- v7.12 talk web-search mode (same guard chain) --------------
        if path == "/api/talk/web":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            try:
                self._send_json(nova.web_talk_state(STATE.sess))
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 500)
            return
        # ---- v6.3 security posture (same guard chain as /api/info) -----
        if path == "/api/secure":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            self._send_json({"secure": bool(nsec.is_secure(STATE.sess.ws))
                             if nsec is not None else False})
            return
        # ---- v6.8 setup wizard (same guard chain as /api/info) ----------
        if path == "/api/doctor":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            try:
                self._send_json(nova.run_doctor(STATE.sess.ws))
            except Exception as e:
                self._send_json({"error": f"doctor failed: {e}"}, 500)
            return
        # ---- v6.8 change timeline (same guard chain as /api/info) -------
        if path == "/api/timeline":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            ws = STATE.sess.ws
            units = []
            if nova.snaps is not None:
                try:
                    for u in nova.snaps.list_units(ws)[-30:][::-1]:
                        # unit files are [{'rel':..,'backup':..}] - the API
                        # exposes plain rel strings (the old payload leaked
                        # raw dicts that rendered as [object Object])
                        files = [f.get("rel") if isinstance(f, dict)
                                 else str(f) for f in u.get("files", [])]
                        units.append({"id": u.get("id", ""),
                                      "ts": u.get("ts", 0),
                                      "kind": u.get("kind", "auto"),
                                      "note": (u.get("note") or "")[:120],
                                      "files": [f for f in files if f][:20]})
                except Exception as e:
                    self._send_json({"error": f"timeline failed: {e}"}, 500)
                    return
            self._send_json({"units": units})
            return
        # ---- v6.8 dependency graph (same guard chain as /api/info) ------
        if path == "/api/graph":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            if nova.depgraph is None:
                self._send_json({"error": "nova_depgraph.py missing"}, 501)
                return
            try:
                g = nova.depgraph.build(STATE.sess.ws)
                self._send_json({
                    "nodes": [{"id": k, "kind": v.get("kind", "other")}
                              for k, v in g["nodes"].items()],
                    "edges": g["edges"],
                    "cycles": g["cycles"],
                    "missing": g["missing"][:20],
                })
            except Exception as e:
                self._send_json({"error": f"graph failed: {e}"}, 500)
            return
        # ---- v6.9 command guide (same guard chain as /api/info) ---------
        if path == "/api/help":
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            # generated from nova's TOOLS registry at request time - the
            # guide can never drift from the real command set
            self._send_json(nova.web_help_payload())
            return
        # ---- v6.0 module surface (same guard chain as /api/info) -------
        if path.startswith("/api/") and nassign is not None:
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _same_origin(self) or not _host_allowed(self):
                self._log_denied("cross-origin")
                self._send_json({"error": "cross-origin requests are not allowed"}, 403)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            if _module_get(self, path, parsed.query):
                return
        self._send_json({"error": "not found"}, 404)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if self._throttled():                      # v6.3: brute-force lockout
            return
        if self._rate_limited(path):               # v6.3: API rate limit
            return
        is_module = path in _MODULE_POST_PATHS and nassign is not None
        if path not in ("/api/chat", "/api/run", "/api/apply", "/api/settings",
                        "/api/secure", "/api/talk", "/api/providers",
                        "/api/iran", "/api/intel", "/api/plugins",
                        "/api/timeline/restore", "/api/rag", "/api/route",
                        "/api/style") \
                and not is_module:
            self._send_json({"error": "not found"}, 404)
            return
        if not _same_origin(self):
            self._log_denied("cross-origin")
            self._send_json({"error": "cross-origin requests are not allowed"}, 403)
            return
        if not _json_content_type(self):
            self._log_denied("bad content-type")
            self._send_json({"error": "Content-Type must be application/json"}, 415)
            return
        if not _host_allowed(self):
            self._log_denied("host header")
            self._send_json({"error": "unknown host header"}, 403)
            return
        if path in ("/api/apply", "/api/settings", "/api/secure",
                    "/api/providers", "/api/iran", "/api/intel",
                    "/api/plugins", "/api/timeline/restore",
                    "/api/rag", "/api/route", "/api/style"):
            self._api_action(path)
            return
        if is_module:
            if STATE is None:
                self._send_json({"error": "server is still starting"}, 503)
                return
            if not _api_authed(self):
                self._log_denied("unauthorized")
                self._send_unauthorized_json()
                return
            _module_post(self, path)
            return
        if path == "/api/talk":
            self._turn("talk")
        else:
            self._turn("chat" if path == "/api/chat" else "run")

    # ------------------------------------------------------------ actions
    def _api_action(self, path):
        """Non-streaming JSON actions (/api/apply, /api/settings)."""
        if STATE is None:
            self._send_json({"error": "server is still starting"}, 503)
            return
        if not _api_authed(self):
            self._log_denied("unauthorized")
            self._send_unauthorized_json()
            return
        try:
            data = self._read_body()
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
            return
        sess = STATE.sess
        if path == "/api/secure":
            # v6.3: flip the security posture for this workspace. No TURN_LOCK
            # needed - a bool flip cannot corrupt an agent turn.
            # v6.5: nsec is an optional import - a missing security layer
            # must degrade to a clean 501, not a dropped connection.
            if nsec is None:
                self._send_json({"error": "security layer unavailable"}, 501)
                return
            want = data.get("secure")
            if not isinstance(want, bool):
                self._send_json({"error": "body must be {\"secure\": true|false}"}, 400)
                return
            state = nsec.set_secure(want, ws=sess.ws)
            nsec.audit(sess.ws, "web-secure", str(want), origin="web",
                       verdict="allow", reason="via /api/secure")
            self._send_json({"ok": True, "secure": state,
                             "note": "token-even-on-localhost applies after a restart"})
            return
        if path == "/api/settings":
            # v6.2.1 fix: mutating the shared Session (model swap can spawn
            # llama-server / import a gguf!) while a turn streams used to
            # bypass TURN_LOCK entirely - the one place that still did.
            # Serialize with the turns, like /api/apply below.
            if not TURN_LOCK.acquire(timeout=30):
                self._send_json({"error": "the agent is busy"}, 409)
                return
            try:
                self._apply_settings(sess, data)
            finally:
                TURN_LOCK.release()
            return
        if path == "/api/providers":
            # v6.6: provider panel mutations (keys/customs/routing/economy).
            # No TURN_LOCK: nothing here touches the shared Session's
            # in-flight turn state - the config is atomic-file based and
            # the NEXT turn picks it up. Discovery runs inside set_key /
            # discover actions (up to ~10 s, explicit user action).
            ok, payload, status = nova.web_providers_action(sess, data)
            self._send_json(payload, status)
            return
        if path == "/api/iran":
            # v7.11: Iranian services panel mutations (service keys /
            # safe tests / real calls). No TURN_LOCK for the same reason;
            # the HTTP call to the service runs up to ~20 s (explicit
            # user action), metered per service inside the module.
            ok, payload, status = nova.web_iran_action(sess, data)
            self._send_json(payload, status)
            return
        if path == "/api/intel":
            # v7.13: the intelligence layer's mutations (tasks, memory,
            # rescan, ctx, impact, gentests, regression, status). No
            # TURN_LOCK - every action touches its own .nova store or
            # reads the tree; none touch the shared turn state.
            # v8.11: EXCEPT the three heavy ones - gentests hits the
            # model and regress_* runs the workspace's tests beside an
            # in-flight turn (tests reading half-written files). They
            # queue on the turn lock now; the light actions stay free.
            _act = str((data or {}).get("action", ""))
            if _act in ("gentests", "regress_baseline", "regress_check"):
                if not TURN_LOCK.acquire(timeout=5):
                    self._send_json({"error": "the agent is busy - wait for the current turn"}, 409)
                    return
                try:
                    ok, payload, status = nova.web_intel_action(sess, data)
                finally:
                    TURN_LOCK.release()
            else:
                ok, payload, status = nova.web_intel_action(sess, data)
            self._send_json(payload, status)
            return
        if path == "/api/plugins":
            # v8.0: plugin system mutations (run tool / reload / secret).
            # No TURN_LOCK - the HTTP call runs up to ~20 s (explicit
            # user/model action) and touches nothing shared.
            try:
                import nova_plugins as _plugins
                ok, payload, status = _plugins.web_action(
                    sess.ws, str(data.get("action", "")), data)
            except Exception as e:
                ok, payload, status = False, {"error": str(e)[:200]}, 500
            self._send_json(payload, status)
            return
        # ---- v7.5: visual timeline - restore the workspace to one unit ---
        if path == "/api/timeline/restore":
            uid = str(data.get("id", "")).strip()
            op = str(data.get("op", "")).strip()
            if nova.snaps is None:
                self._send_json({"error": "nova_snapshots.py missing"}, 501)
                return
            if not TURN_LOCK.acquire(timeout=30):
                self._send_json({"error": "the agent is busy"}, 409)
                return
            try:
                if op == "undo" and not uid:
                    # plain "undo the newest apply batch"
                    res = nova.snaps.undo_units(sess.ws, 1)
                    res["ok"] = not res.get("errors")
                    self._send_json(res)
                    return
                if not uid or len(uid) > 80 \
                        or not re.fullmatch(r"[A-Za-z0-9_-]+", uid):
                    self._send_json({"error": "invalid unit id"}, 400)
                    return
                units = nova.snaps.list_units(sess.ws)   # newest first
                meta = next((u for u in units if u.get("id") == uid), None)
                if meta is None:
                    self._send_json({"error": "no such unit"}, 404)
                    return
                if meta.get("kind") == "manual":
                    # restore_manual returns {'written'/'deleted'/'skipped'/'errors'}
                    rres = nova.snaps.restore_manual(sess.ws, meta,
                                                     ignore=sess.ignore)
                    res = {"ok": not rres.get("errors"), **rres}
                else:
                    # undo everything NEWER than this unit - the workspace
                    # lands exactly at the moment that unit was applied
                    n = units.index(meta)
                    if n <= 0:
                        self._send_json({"ok": True, "restored": [],
                                         "note": "already the newest unit"})
                        return
                    res = nova.snaps.undo_units(sess.ws, n)
                    res["ok"] = not res.get("errors")
                nova.emit_event({"t": "note", "text":
                                 "[timeline] workspace restored to unit " + uid})
                self._send_json(res)
            except Exception as e:
                self._send_json({"error": type(e).__name__ + ": " + str(e)[:300]}, 500)
            finally:
                TURN_LOCK.release()
            return
        # ---- v7.5: semantic RAG query (build/status ride the GET view) ---
        if path == "/api/rag":
            if nova.rag is None:
                self._send_json({"error": "nova_rag.py missing"}, 501)
                return
            q = str(data.get("q", "")).strip()[:300]
            if not q:
                self._send_json({"error": "empty query"}, 400)
                return
            try:
                hits = nova.rag.search(sess.ws, q, k=5)
                self._send_json({"ok": True, "hits": [
                    {"file": f, "line": ln, "score": s, "text": t}
                    for f, ln, s, t in hits]})
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 500)
            return
        # ---- v7.5: the explicit cloud difficulty map ---------------------
        if path == "/api/route":
            if nova.router is None:
                self._send_json({"error": "nova_router.py missing"}, 501)
                return
            fast = str(data.get("fast", "")).strip()[:120] if data.get("fast") else ""
            strong = str(data.get("strong", "")).strip()[:120] if data.get("strong") else ""
            if data.get("off"):
                fast = strong = ""
            err = nova.router.save_route_map(sess.ws, fast, strong)
            if err:
                self._send_json({"error": err}, 500)
                return
            self._send_json({"ok": True,
                             "map": nova.router.load_route_map(sess.ws)})
            return
        # ---- v7.5: the user's coding-style profile -----------------------
        if path == "/api/style":
            if nova.style is None:
                self._send_json({"error": "nova_style.py missing"}, 501)
                return
            op = str(data.get("op", "rebuild"))
            if op == "clear":
                try:
                    p = nova.style.style_path(sess.ws)
                    if p.is_file():
                        p.unlink()
                except OSError as e:
                    self._send_json({"error": str(e)}, 500)
                    return
                self._send_json({"ok": True, "cleared": True})
                return
            try:
                prof, err = nova.style.refresh(sess.ws, sess.ignore)
                self._send_json({"ok": not err, "profile": prof,
                                 "error": err or None})
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 500)
            return
        # /api/apply
        if not TURN_LOCK.acquire(timeout=30):
            self._send_json({"error": "the agent is busy"}, 409)
            return
        try:
            self._apply(sess, data)
        finally:
            TURN_LOCK.release()

    def _apply_settings(self, sess, data):
        """Body of /api/settings (runs under TURN_LOCK)."""
        changed = {}
        # v8.12: the *_reset keys are DESTRUCTIVE (they wipe the saved
        # settings file) - a non-boolean value is rejected up front.
        # Any truthy garbage (e.g. the string "no") used to fire the
        # reset and silently flip the feature back to its defaults.
        for rkey in ("ctx_reset", "guardian_reset", "probe_reset",
                     "vision_reset"):
            if rkey in data and not isinstance(data[rkey], bool):
                self._send_json({"error": rkey + " must be a boolean"}, 400)
                return
        # v8.12: session toggles follow the same honesty contract as
        # every other key - a present-but-non-boolean value is rejected
        # (it used to be silently ignored while the panel toasted
        # "saved", leaving the caller unable to tell apply from drop).
        for key in ("confirm_changes", "explain", "autotest", "autofix"):
            if key in data:
                if not isinstance(data[key], bool):
                    self._send_json(
                        {"error": key + " must be a boolean"}, 400)
                    return
                setattr(sess, key, data[key])
                changed[key] = data[key]
        # v8.12: a key that belongs to a MISSING engine layer is
        # answered honestly (the /api/rag + /api/route convention)
        # instead of falling through to ok:true with nothing written.
        if nova.ctxengine is None and any(
                k in data for k in ("ctx_local", "ctx_cloud", "ctx_auto",
                                    "ctx_threshold", "ctx_keep",
                                    "ctx_reset")):
            self._send_json(
                {"error": "the context-engine layer is unavailable"}, 501)
            return
        if getattr(nova, "guardian", None) is None and any(
                k in data for k in ("guardian_on", "guardian_model",
                                    "guardian_web", "guardian_reject",
                                    "guardian_reset")):
            self._send_json(
                {"error": "the code-guardian layer is unavailable"}, 501)
            return
        if getattr(nova, "probe", None) is None and any(
                k in data for k in ("probe_on", "probe_wiring",
                                    "probe_deep", "probe_smoke",
                                    "probe_browser", "probe_review",
                                    "probe_reject", "probe_rejectdeep",
                                    "probe_reset")):
            self._send_json(
                {"error": "the bug-hunter layer is unavailable"}, 501)
            return
        if getattr(nova, "vision", None) is None and any(
                k in data for k in ("vision_approve", "vision_strict",
                                    "vision_reset")):
            self._send_json(
                {"error": "the vision layer is unavailable"}, 501)
            return
        # ---- v8.3: the context engine (per-backend windows + compression)
        if nova.ctxengine is not None and (
                any(k in data for k in ("ctx_local", "ctx_cloud", "ctx_auto",
                                        "ctx_threshold", "ctx_keep"))
                or data.get("ctx_reset")):
            if data.get("ctx_reset"):
                err = nova.ctxengine.reset_settings(sess.ws)
                if err:
                    self._send_json({"error": err}, 500)
                    return
            else:
                ups = {}
                if "ctx_local" in data:
                    try:
                        ups["local_ctx"] = int(data["ctx_local"])
                    except (TypeError, ValueError):
                        self._send_json({"error": "ctx_local must be an integer"}, 400)
                        return
                if "ctx_cloud" in data:
                    try:
                        ups["cloud_ctx"] = int(data["ctx_cloud"])
                    except (TypeError, ValueError):
                        self._send_json({"error": "ctx_cloud must be an integer"}, 400)
                        return
                if "ctx_auto" in data:
                    if not isinstance(data["ctx_auto"], bool):
                        self._send_json({"error": "ctx_auto must be a boolean"}, 400)
                        return
                    ups["auto_compact"] = data["ctx_auto"]
                if "ctx_threshold" in data:
                    try:
                        ups["compact_threshold"] = float(data["ctx_threshold"])
                    except (TypeError, ValueError):
                        self._send_json({"error": "ctx_threshold must be a number"}, 400)
                        return
                if "ctx_keep" in data:
                    try:
                        ups["keep_recent"] = int(data["ctx_keep"])
                    except (TypeError, ValueError):
                        self._send_json({"error": "ctx_keep must be an integer"}, 400)
                        return
                err = nova.ctxengine.save_settings(sess.ws, ups)
                if err:
                    self._send_json({"error": err}, 500)
                    return
                # surface silently-dropped out-of-range values honestly
                kept = nova.ctxengine._valid_fields(ups)
                dropped = [k for k in ups if k not in kept]
                if dropped:
                    changed["ctx_dropped"] = dropped
            sess.ctx_settings = nova.ctxengine.load_settings(sess.ws)
            changed["ctx"] = nova.web_ctx_state(sess)
        # ---- v8.4: the code guardian (supervisor + language fleet) ----
        gkeys = ("guardian_on", "guardian_model", "guardian_web",
                 "guardian_reject")
        if getattr(nova, "guardian", None) is not None and (
                any(k in data for k in gkeys) or data.get("guardian_reset")):
            if data.get("guardian_reset"):
                err = nova.guardian.reset_settings(sess.ws)
                if err:
                    self._send_json({"error": err}, 500)
                    return
            else:
                ups = {}
                for key, field in (("guardian_on", "on"),
                                   ("guardian_model", "model"),
                                   ("guardian_web", "web"),
                                   ("guardian_reject", "reject_syntax")):
                    if key in data:
                        if not isinstance(data[key], bool):
                            self._send_json(
                                {"error": key + " must be a boolean"}, 400)
                            return
                        ups[field] = data[key]
                err = nova.guardian.save_settings(sess.ws, ups)
                if err:
                    self._send_json({"error": err}, 500)
                    return
            sess.guardian_settings = nova.guardian.load_settings(sess.ws)
            changed["guardian"] = nova.web_guardian_state(sess)
        # ---- v8.5: the bug hunter (the behavior probes) ---------------
        pkeys = ("probe_on", "probe_wiring", "probe_deep",
                 "probe_smoke", "probe_browser", "probe_review",
                 "probe_reject", "probe_rejectdeep")
        if getattr(nova, "probe", None) is not None and (
                any(k in data for k in pkeys) or data.get("probe_reset")):
            if data.get("probe_reset"):
                err = nova.probe.reset_settings(sess.ws)
                if err:
                    self._send_json({"error": err}, 500)
                    return
            else:
                ups = {}
                for key, field in (("probe_on", "on"),
                                   ("probe_wiring", "wiring"),
                                   ("probe_deep", "deep"),
                                   ("probe_smoke", "smoke"),
                                   ("probe_browser", "browser"),
                                   ("probe_review", "review"),
                                   ("probe_reject", "reject_wiring"),
                                   ("probe_rejectdeep", "reject_deep")):
                    if key in data:
                        if not isinstance(data[key], bool):
                            self._send_json(
                                {"error": key + " must be a boolean"}, 400)
                            return
                        ups[field] = data[key]
                err = nova.probe.save_settings(sess.ws, ups)
                if err:
                    self._send_json({"error": err}, 500)
                    return
            sess.probe_settings = nova.probe.load_settings(sess.ws)
            changed["probe"] = nova.web_probe_state(sess)
        # ---- v8.6: the vision layer (local-vision approval gate) ------
        vkeys = ("vision_approve", "vision_strict")
        if getattr(nova, "vision", None) is not None and (
                any(k in data for k in vkeys) or data.get("vision_reset")):
            if data.get("vision_reset"):
                err = nova.vision.reset_settings(sess.ws)
                if err:
                    self._send_json({"error": err}, 500)
                    return
            else:
                ups = {}
                for key, field in (("vision_approve", "approve"),
                                   ("vision_strict", "strict")):
                    if key in data:
                        if not isinstance(data[key], bool):
                            self._send_json(
                                {"error": key + " must be a boolean"}, 400)
                            return
                        ups[field] = data[key]
                err = nova.vision.save_settings(sess.ws, ups)
                if err:
                    self._send_json({"error": err}, 500)
                    return
            sess.vision_settings = nova.vision.load_settings(sess.ws)
            changed["vision"] = nova.web_vision_state(sess)
        # v5.1: model switching from the header dropdown - same rules
        # as the terminal /model command: validate against the
        # installed list (ollama), persist into the project profile.
        if "model" in data:
            want = data["model"]
            if not isinstance(want, str) or not want.strip() or len(want) > 120:
                self._send_json({"error": "invalid model name"}, 400)
                return
            want = want.strip()
            prov = nova._provider_cfg()
            # v5.2: a model FILE from the model folders (id 'file:<name>')
            if want.startswith("file:"):
                if nova.lmodels is None:
                    self._send_json({"error": "local model support is unavailable"}, 501)
                    return
                entry = nova._find_local_entry(
                    want, nova.list_local_models(sess.ws, force=True))
                if entry is None:
                    self._send_json({"error": "model file not found in the model folders"}, 404)
                    return
                mode, val = nova.ensure_local_model(sess, entry=entry)
                if mode is None:
                    self._send_json({"error": str(val)}, 502)
                    return
                sess.model = entry["id"]
                sess.save_profile_field("model", entry["id"])
                changed["model"] = entry["id"]
                self._send_json({"ok": True, "via": mode,
                                 "route": val if mode == "ollama" else val.get("base", ""),
                                 **changed})
                return
            if prov.get("kind") == "ollama":
                installed = nova.list_installed_models()
                if nova.nmodels is not None:
                    full = nova.nmodels.resolve_choice(want, installed)
                else:
                    full = want if want in installed else None
                if full is None:
                    self._send_json(
                        {"error": f"model '{want}' is not installed - pull it with: ollama pull {want}"},
                        409)
                    return
                want = full
            sess.model = want
            sess.save_profile_field("model", want)
            changed["model"] = want
        self._send_json({"ok": True, **changed})

    def _apply(self, sess, data):
        """/api/apply: write the staged changes (runs under TURN_LOCK)."""
        batch_id = str(data.get("id", ""))
        files = data.get("files") or []
        hunks = data.get("hunks") or {}
        if not isinstance(files, list) or not isinstance(hunks, dict):
            self._send_json({"error": "files must be a list, hunks an object"}, 400)
            return
        norm = {}
        for p, idxs in hunks.items():
            if not isinstance(idxs, list):
                continue
            clean = []
            for i in idxs:
                try:
                    clean.append(int(i))
                except (TypeError, ValueError):
                    continue
            norm[str(p)] = clean
        try:
            ok, result = nova.apply_approved(sess, batch_id, files, norm)
            self._send_json(result if ok else {"error": result.get("error", "failed")},
                            200 if ok else 409)
        except Exception as e:
            self._send_json({"error": type(e).__name__ + ": " + str(e)[:300]}, 500)

    # ------------------------------------------------------------ turns
    def _turn(self, kind):
        """Streamed agent turn (chat message or explicit Run click)."""
        if STATE is None:
            self._send_json({"error": "server is still starting"}, 503)
            return
        if not _api_authed(self):
            self._log_denied("unauthorized")
            self._send_unauthorized_json()
            return
        try:
            data = self._read_body()
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
            return
        if kind == "chat":
            text = str(data.get("message", "")).strip()
            if not text:
                self._send_json({"error": "empty message"}, 400)
                return
            if len(text) > 100_000:
                self._send_json({"error": "message too long (100k chars max)"}, 400)
                return
        elif kind == "talk":
            text = str(data.get("message", "")).strip()
            if not text:
                self._send_json({"error": "empty message"}, 400)
                return
            if len(text) > 20_000:
                self._send_json({"error": "message too long (20k chars max)"}, 400)
                return
        else:
            text = str(data.get("command", "")).strip()
            if not text or len(text) > MAX_CMD:
                self._send_json({"error": "command must be 1-" + str(MAX_CMD) + " chars"}, 400)
                return

        # one brain, one turn: queue politely instead of corrupting state.
        # v6.4: a simple-chat turn must not queue for 3 minutes behind a
        # long coding turn - fail fast with 409 so the user can decide.
        lock_wait = 5 if kind == "talk" else 180
        if not TURN_LOCK.acquire(timeout=lock_wait):
            self._send_json({"error": "the agent is busy - wait for the current turn"}, 409)
            return

        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Transfer-Encoding", "chunked")
            # v8.0: every other 200 path sets the security headers - the
            # streaming path used to be the one exception (nosniff is
            # exactly the header that makes content-type confusion safe).
            self._security_headers()
            self.end_headers()
            self._stream_open = True
            self._run_turn(kind, text, data)
            # chunked transfer-encoding MUST end with a zero-length final
            # chunk - without it the response body is never "closed" from
            # the client's point of view, so fetch()'s reader.read() never
            # resolves with done=true and the page stays stuck on "busy"
            # after every single turn until the whole connection times out.
            # v7.1.0: the terminator goes out under the SAME lock as every
            # frame, and the stream is marked closed UNDER it - a late
            # frame from a background worker (which used to land after the
            # terminator) can no longer desync the next keep-alive request
            # on this socket.
            with _EMIT_LOCK:
                self._stream_open = False
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        except (_ClientGone, BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass  # browser tab closed / stopped watching - keep the agent sane
        except KeyboardInterrupt:
            # v8.11: Ctrl+C in the server terminal during a Run used to
            # kill this handler thread BEFORE the chunked terminator -
            # the browser stream then never resolved (a permanent busy
            # tab). The terminator still goes out under the lock.
            try:
                with _EMIT_LOCK:
                    self._stream_open = False
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
            except Exception:
                pass
        finally:
            self._stream_open = False
            TURN_LOCK.release()

    def _emit(self, obj):
        try:
            line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
            # v6.8.1: chunked-encoding frames must never interleave - a
            # /agent turn streams from PARALLEL worker threads into this
            # one socket; without the lock a slow client could receive a
            # half-written frame from two threads at once (desync).
            with _EMIT_LOCK:
                if not getattr(self, "_stream_open", False):
                    # v7.1.0: the chunked response is closed - a late
                    # frame (background task / parallel worker that kept
                    # a reference to emit_fn) must never corrupt the NEXT
                    # response on this keep-alive connection.
                    raise _ClientGone()
                self.wfile.write(("%x\r\n" % len(line)).encode("ascii") + line + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            raise _ClientGone()

    def _run_turn(self, kind, text, data=None):
        sess = STATE.sess
        old_out, old_err = sys.stdout, sys.stderr
        old_sink = nova.TOKEN_SINK
        old_event = nova.EVENT_SINK
        emit_fn = self._emit

        def bridge(s):
            """Console -> browser bridge: every agent print becomes a live
            note event (ANSI colors stripped, blank lines dropped). The
            real console keeps its copy, so the terminal stays useful."""
            if s and s.strip():
                try:
                    emit_fn({"t": "note", "text": ANSI_RE.sub("", s)})
                except _ClientGone:
                    pass  # keep the turn alive; no one is watching

        def token_bridge(piece):
            """Same policy as note events: a closed tab must NOT abort the
            whole agent turn mid-tool-loop. The turn runs to completion
            (slow-hardware design: nothing cuts a generation short); only
            the streaming to the (gone) browser stops."""
            try:
                emit_fn({"t": "tok", "text": piece})
            except _ClientGone:
                pass

        def event_bridge(obj):
            """Structured UI events (todo panel, staged changes, background
            notices) ride the SAME stream as notes."""
            try:
                emit_fn(obj)
            except _ClientGone:
                pass

        class _TeeOut:
            def __init__(self, original):
                self.original = original

            def write(self, s):
                try:
                    self.original.write(s)
                except Exception as e:
                    if nova_log is not None:
                        nova_log.soft("web.tee.console", e)   # v6.3: logged
                bridge(s)
                return len(s)

            def flush(self):
                try:
                    self.original.flush()
                except Exception:
                    pass

            def isatty(self):
                return False

            def reconfigure(self, *a, **k):
                pass

        sys.stdout = _TeeOut(old_out)
        sys.stderr = _TeeOut(old_err)
        nova.TOKEN_SINK = token_bridge
        nova.EVENT_SINK = event_bridge

        before = dict(sess.touched)
        result = None
        try:
            if kind == "chat":
                if text.startswith("/confirm"):
                    # web-only convenience toggle for the approve-before-write UI
                    sub = text.split(maxsplit=1)[1].strip().lower() if len(text.split(maxsplit=1)) > 1 else ""
                    if sub in ("on", "off"):
                        sess.confirm_changes = (sub == "on")
                    print("[confirm] approve-before-write mode: "
                          + ("ON" if sess.confirm_changes else "OFF")
                          + " - every apply waits for your per-hunk approval")
                elif text.startswith("/autofix"):
                    # v6.8.3: one auto fix round when a Run click fails
                    sub = text.split(maxsplit=1)[1].strip().lower() if len(text.split(maxsplit=1)) > 1 else ""
                    if sub in ("on", "off"):
                        sess.autofix = (sub == "on")
                        # v8.8: turning autofix (back) on is a conscious user
                        # decision - re-arm the fix-loop brake with it
                        if sess.autofix:
                            nova.reset_fix_rounds(sess)
                    print("[autofix] auto fix on failed run: "
                          + ("ON" if sess.autofix else "OFF")
                          + " - a failed Run feeds its error back for one fix round")
                elif text.startswith("/"):
                    # v6.5: '/quit' reaches cmd_quit which raises SystemExit -
                    # a BaseException the generic handler below cannot catch,
                    # so the turn died mid-stream with zero feedback (and the
                    # server kept running, so "quit" did not even quit).
                    # v7.14.1 fix: '/quit now' (any argument) used to slip
                    # past the exact-string check and kill the stream - the
                    # FIRST WORD is what counts.
                    if text.strip().lower().split()[:1] in (["/quit"],
                                                            ["/exit"],
                                                            ["/bye"]):
                        print("[!] /quit in the web face only ends this turn - "
                              "stop the server with Ctrl+C in its terminal.")
                    else:
                        nova.dispatch(sess, text)     # slash commands in the box
                else:
                    result = nova.chat_turn(sess, text, auto=True)
            elif kind == "talk":
                result = self._run_talk(text, data)
            else:
                code = nova.run_command(sess, text, auto=True, origin="web")
                result = {"run_cmd": None, "run_exit": code}
                # v6.8.3: ONE bounded auto-fix round - a failed Run feeds its
                # own error (plus the files named in it) back to the model.
                # This is the web face of what /auto and /verify already do
                # in the terminal; without it a broken first draft just sat
                # there and the user had to hand-copy the error back.
                if getattr(sess, "autofix", True) and code not in (0, None) \
                        and getattr(sess, "last_failed", None):
                    lf_cmd = sess.last_failed.get("cmd") or ""
                    # v8.11: the skip checks now come FIRST - the brake
                    # check used to run before them, so a timeout or
                    # 'command not found' run printed "[autofix] paused -
                    # the last N fix rounds never produced a green run"
                    # when the truth was simply 'nothing to fix here'.
                    if nova.is_unrunnable_failure(
                            code, sess.last_failed.get("output") or ""):
                        # v7.7: 'command not found' / a non-command Run hint
                        # is NOT a code error - the old auto-fix round fed a
                        # non-existent bug to the model, which then rewrote
                        # HEALTHY files (the "run worked, then I edited, and
                        # everything broke" report)
                        print(nova.c(nova.C.Y,
                                     "[autofix] skipped - the OS never ran this "
                                     "command (nothing to fix). For a website the "
                                     "answer should end with 'Preview: index.html'."))
                    elif lf_cmd and nova._looks_like_server(lf_cmd):
                        # v7.7: a timed-out server is HEALTHY - it never exits.
                        # The old fix round 'repaired' working servers.
                        print(nova.c(nova.C.Y,
                                     "[autofix] skipped - that looks like a long-running "
                                     "server (preview it with /serve instead)."))
                    elif sess.last_failed.get("code") == "timeout" or code == -1:
                        # v7.7: a timeout is AMBIGUOUS evidence (a healthy
                        # server that never exits, or genuinely stuck code).
                        # Auto-feeding it to the model 'repaired' healthy
                        # servers; the user can ask for a fix with one click.
                        print(nova.c(nova.C.Y,
                                     "[autofix] skipped - the run was killed at the "
                                     "timeout, which alone proves nothing. If it is a "
                                     "server, preview with /serve; if the program is "
                                     "stuck, ask Nova to fix it."))
                    elif nova.fix_budget_left(sess) <= 0:
                        # v8.8: THE FIX-LOOP BRAKE. The user's report: the
                        # run -> fix cycle "gets stuck in a loop and never
                        # finishes". After MAX_FIX_ROUNDS fix rounds without
                        # a green run, Nova stops and SAYS so instead of
                        # silently cycling forever. A green run (run_command
                        # resets the counter) or a manual /autofix on re-arms
                        # the budget.
                        print(nova.c(nova.C.Y,
                                     "\n[autofix] paused - the last "
                                     + str(nova.MAX_FIX_ROUNDS)
                                     + " fix round(s) never produced a green "
                                       "run, so auto-fix stops here instead of "
                                       "looping (fix by hand, or /autofix on to "
                                       "re-arm)"))
                        print(nova.c(nova.C.D,
                                     "    (بریک حلقه‌ی اصلاح: چند دور پشت‌سرهم سبز نشد - "
                                     "به‌جای لوپ بی‌پایان متوقف شد. با /autofix on دوباره فعال شود)"))
                    else:
                        print(nova.c(nova.C.Y, "\n[autofix] the run failed - sending the "
                                           "error back to the model for one fix round "
                                           "(/autofix off to disable)"))
                        nova.bump_fix_round(sess)   # v8.8: count it against the brake
                        try:
                            msg = nova.build_fix_message(sess)
                            if msg:
                                fx = nova.chat_turn(sess, msg, auto=True)
                                result["autofix"] = {"files": fx.get("files") or [],
                                                     "edits": fx.get("edits") or [],
                                                     "applied": fx.get("applied") or []}
                                # v8.11: the fix's own Run hint reaches the
                                # UI - the old code dropped it, so after a
                                # fix round the Run button vanished and the
                                # user re-ran the STALE chip from before
                                for _k in ("run_cmd", "suggested_run"):
                                    _v = (fx or {}).get(_k)
                                    if _v:
                                        result["run_cmd"] = _v
                                        break
                        except Exception as e:
                            print(nova.c(nova.C.R, "[autofix] fix round failed: " + str(e)[:200]))
        except Exception as e:  # a broken turn must never kill the server
            try:
                emit_fn({"t": "err", "text": type(e).__name__ + ": " + str(e)[:400]})
            except Exception:
                pass
        finally:
            changed = [{"name": k, "kind": v} for k, v in sess.touched.items()
                       if before.get(k) != v]
            done = {
                "t": "done",
                "changed": changed,
                # v6.9: the derived (never model-written) command is ONLY a
                # button suggestion - the verify/auto loops read run_cmd
                "run_cmd": (result or {}).get("run_cmd")
                           or (result or {}).get("suggested_run"),
                "run_exit": (result or {}).get("run_exit"),
                "complete": (result or {}).get("complete"),
                "pending": bool(getattr(sess, "pending_apply", None)),
            }
            # v8.11: the UI shows what the auto-fix round did - the key
            # only rides the event when a round actually ran (the old
            # done contract stays byte-compatible otherwise)
            if (result or {}).get("autofix"):
                done["autofix"] = result["autofix"]
            sys.stdout, sys.stderr = old_out, old_err
            nova.TOKEN_SINK = old_sink
            nova.EVENT_SINK = old_event
            try:
                emit_fn(done)
            except _ClientGone:
                pass

    def _talk_search(self, query):
        """v7.12: one fail-soft web search for the talk tab.
        Returns (results, None) or (None, error-string). A missing
        nova_search module or a dead network degrades to a note - the
        answer itself NEVER dies because search did."""
        nsearch = getattr(nova, "ns", None)
        if nsearch is None:
            return None, "nova_search.py missing"
        try:
            return nsearch.web_search(query,
                                      max_results=nova.TALK_WEB_MAX_RESULTS), None
        except Exception as e:
            return None, str(e)[:200]

    def _talk_web_event(self, query, results):
        """Slim, browser-safe source list for the {t:"web"} event."""
        nsearch = getattr(nova, "ns", None)
        slim = []
        for r in (results or [])[:nova.TALK_WEB_MAX_RESULTS]:
            url = str((r or {}).get("url") or "").strip()
            if not url:
                continue
            dom = ""
            try:
                dom = nsearch.domain_of(url) if nsearch else \
                    urllib.parse.urlparse(url).hostname or ""
            except Exception:
                dom = ""
            slim.append({
                "title": str((r or {}).get("title") or dom or url)[:120],
                "url": url,
                "domain": str(dom)[:80],
                "snippet": str((r or {}).get("snippet") or "")[:200],
            })
        if slim:
            # v8.10.1: the note/token bridges swallow _ClientGone so a
            # closed tab never aborts the turn - this hop used to be the
            # one unguarded _emit left, dropping the whole talk turn
            # (memory persist included) when the tab closed mid-search.
            try:
                self._emit({"t": "web", "query": query, "results": slim})
            except _ClientGone:
                pass
        return slim

    def _run_talk(self, text, data=None):
        """v6.4: the simple-conversation turn behind the گفت و گو tab.
        Same brain as the coding agent, but NO coding protocol: its own
        system prompt (no file blocks / tool tokens / Run hints) and a
        short RAM-capped history, so chatting never pollutes the coding
        agent's context and can never touch files. Tokens stream through
        the SAME TOKEN_SINK plumbing as the coding turn.
        v6.6: section="talk" - a routed talk brain (/brain talk ...) is
        used when one is configured, with the talk output cap.
        v7.12: WEB SEARCH in the simple chat. Three modes persisted per
        workspace (.nova/talk_web.json): off | auto (default - only
        turns whose wording implies fresh facts search) | always. When a
        search runs, its results stream to the browser as a structured
        {t:"web"} event AND a compact [WEB RESULTS] block rides with the
        turn (an extra system message that NEVER enters talk_history).
        Talk-side commands: /web [off|auto|always] shows or flips the
        mode; /search <query> runs a manual search straight into the
        chat bubble without a model call."""
        sess = STATE.sess

        # ---- v7.12: per-request mode flip (UI segmented control) -------
        want_mode = (data or {}).get("web")
        if want_mode in nova.TALK_WEB_MODES:
            try:
                nova.talk_web_set(sess.ws, want_mode)
            except Exception:
                pass
            mode = nova.talk_web_get(sess.ws)
        else:
            mode = nova.talk_web_get(sess.ws)

        # ---- v7.12: talk-side commands (no model call) -----------------
        low = text.strip()
        if low.startswith("/web"):
            arg = low[4:].strip().lower()
            if arg in nova.TALK_WEB_MODES:
                try:
                    mode = nova.talk_web_set(sess.ws, arg)
                except Exception as e:
                    print("[web] mode unchanged: " + str(e)[:120])
            if arg not in nova.TALK_WEB_MODES:
                print("[web] mode: " + mode + "  (off | auto | always)")
            else:
                print("[web] جست‌وجوی وب در گفت و گو: " + _TALK_WEB_FA[mode])
            try:
                self._emit({"t": "webmode", "mode": mode})
            except _ClientGone:
                raise
            except Exception:
                pass
            return {"run_cmd": None, "run_exit": None}
        if low.startswith("/search"):
            q = low[len("/search"):].strip()
            if not q:
                print("[web] usage: /search <query>")
                return {"run_cmd": None, "run_exit": None}
            print("[web] جست‌وجوی وب برای: " + q)
            results, err = self._talk_search(q)
            if err:
                print("[web] جست‌وجو ناموفق بود: " + err)
                return {"run_cmd": None, "run_exit": None}
            slim = self._talk_web_event(q, results)
            if not slim:
                print("[web] نتیجه‌ای پیدا نشد")
                return {"run_cmd": None, "run_exit": None}
            answer = _talk_results_text(q, slim)
            try:
                if nova.TOKEN_SINK:
                    nova.TOKEN_SINK(answer)
            except _ClientGone:
                raise
            except Exception:
                pass
            STATE.talk_history.append({"role": "user", "content": text})
            STATE.talk_history.append({"role": "assistant",
                                       "content": answer})
            if len(STATE.talk_history) > TALK_HISTORY_CAP:
                del STATE.talk_history[:-TALK_HISTORY_CAP]
            return {"run_cmd": None, "run_exit": None}

        # ---- v7.12: decide whether THIS turn carries web results -------
        web_block = None
        if mode != "off" and not low.startswith("/"):
            if mode == "always" or nova.talk_needs_web(text, "auto"):
                q = nova.talk_web_query(text)
                print("[web] جست‌وجوی وب برای: " + q)
                results, err = self._talk_search(q)
                if err:
                    print("[web] جست‌وجو ناموفق - پاسخ بدون وب ادامه "
                          "می‌یابد: " + err)
                else:
                    slim = self._talk_web_event(q, results)
                    if slim:
                        web_block = nova.talk_web_block(q, results)
                    else:
                        print("[web] نتیجه‌ای پیدا نشد - پاسخ بدون وب")

        # v7.14: the THINK protocol rides in the simple chat too - a brain
        # without native reasoning gets the short forced-reasoning fragment
        # appended to the talk system prompt (auto/on/off, per workspace).
        # v7.14.1 fix: the decision consults the brain that will ACTUALLY
        # serve (a routed talk brain may be a reasoner even when the
        # coding model is not).
        sys_prompt = TALK_SYSTEM
        try:
            serve_model = sess.model
            try:
                if nova.providers is not None:
                    _rcfg, _rm = nova.providers.resolve_route("talk")
                    if _rcfg is not None and _rm:
                        serve_model = _rm
            except Exception:
                pass
            if nova.think is not None and nova.think.enabled() \
                    and nova.think.should_force(sess.ws, serve_model):
                sys_prompt += "\n\n" + nova.think.force_prompt("talk")
        except Exception:
            sys_prompt = TALK_SYSTEM
        msgs = [{"role": "system", "content": sys_prompt}]
        if web_block:
            msgs.append({"role": "system", "content": web_block})
        msgs += STATE.talk_history[-TALK_HISTORY_CAP:]
        msgs.append({"role": "user", "content": text})
        answer = ""
        _ok = False
        try:
            answer, _ok = nova.stream_chat(sess.model, msgs, TALK_TEMPERATURE,
                                           sess=sess, section="talk")
        except Exception as e:   # stream_chat is fail-soft already; belt+braces
            try:
                self._emit({"t": "err",
                            "text": type(e).__name__ + ": " + str(e)[:300]})
            except Exception:
                pass
        _raw = answer   # v8.2: the pre-extraction raw (the rescue merges into it)
        # v7.14: separate the THINK block BEFORE it enters the talk history
        # (the raw text already streamed; the web face renders the box).
        # v8.2: cut-answer rescue - an open reasoning block (or a stream
        # cut at the talk output cap) that left NOTHING usable gets ONE
        # automatic continuation round, exactly like the coding side; the
        # model never sees its friendly answer vanish into "empty".
        # v8.7: _td MUST pre-exist - when nova_think is missing (the
        # fail-soft import made nova.think None) the try block never
        # assigns it and the _talk_cut line below raised NameError,
        # killing every talk turn in the degraded install.
        _td = None
        try:
            if nova.think is not None:
                _td = nova.think.extract(answer)
                if _td is not None:
                    answer = _td["answer"]
        except Exception:
            _td = None
        _talk_cut = (not _ok) or (_td is not None and _td.get("open")
                                  and not answer.strip())
        if _talk_cut and answer.strip() == "" and _raw.strip():
            try:
                _rmsgs = msgs + [{"role": "user", "content":
                                  nova._resume_message(_raw, text)}]
                _cont, _cok = nova.stream_chat(sess.model, _rmsgs,
                                               TALK_TEMPERATURE,
                                               sess=sess, section="talk")
                if _cont.strip():
                    _raw = _raw.rstrip() + "\n\n" + _cont.rstrip()
                    _ok = _cok
                    if nova.think is not None:
                        try:
                            _td = nova.think.extract(_raw)
                            if _td is not None:
                                answer = _td["answer"]
                        except Exception:
                            pass
            except Exception:
                pass
        try:
            if nova.think is not None and _td and _td.get("think"):
                self._emit({"t": "think", "text": _td["think"],
                            "native": bool(_td.get("native"))})
        except Exception:
            pass
        if answer.strip():
            STATE.talk_history.append({"role": "user", "content": text})
            STATE.talk_history.append({"role": "assistant", "content": answer})
            if len(STATE.talk_history) > TALK_HISTORY_CAP:
                del STATE.talk_history[:-TALK_HISTORY_CAP]
        else:
            try:
                self._emit({"t": "err", "text": TALK_EMPTY_MSG})
            except Exception:
                pass
        return {"run_cmd": None, "run_exit": None}
