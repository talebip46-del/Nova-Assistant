#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - nova_plugins (v8.0 "clear")
#
#  The PLUGIN SYSTEM: user-defined side tools that live OUTSIDE the
#  core. Nova's command table used to be the only way to extend the
#  agent; every new helper meant touching nova.py. A plugin is a JSON
#  file in <ws>/.nova/plugins/ that declares HTTP tools the model can
#  call from chat (via /plugin or the TOOLS index).
#
#      .nova/plugins/weather.json
#      {
#        "name": "weather",
#        "description": "Open-Meteo current weather",
#        "tools": [
#          {"name": "get",
#           "description": "current weather for a city",
#           "method": "GET",
#           "url": "https://geocoding-api.open-meteo.com/v1/search?name={city}",
#           "params": [{"name": "city", "required": true,
#                       "in": "query", "desc": "city name"}],
#           "key": {"env": "WEATHER_API_KEY", "in": "query", "param": "key"}
#          }
#        ]
#      }
#
#  Safety model (the core stays clean):
#    - one JSON file per plugin, 64 KB cap, max 24 plugins, max 12
#      tools per plugin; a hostile/broken file is QUARANTINED (moved to
#      plugins/corrupt/) and the rest keep loading - one bad plugin
#      must never take the agent down
#    - names are strict: ^[a-z][a-z0-9_]{1,31}$ for plugins AND tools;
#      collisions with Nova's own commands or other plugins are refused
#    - every URL is SSRF-guarded through nova_search.safe_url (fail
#      CLOSED - no safe_url, no plugin HTTP), scheme http/https only
#    - path params are percent-encoded, query params urlencoded, keys
#      come from the environment (or .nova/plugins/.env secrets file)
#      and are REDACTED from every error and preview
#    - responses are capped (2 MB), the raw body never reaches the
#      model - only a capped preview + extracted fields
#    - NOVA_PLUGINS=0 is the kill switch; the module never raises
# =====================================================================
import json
import os
import re
import time
from pathlib import Path

VERSION = "8.0"

try:
    import nova_atomic as natom
except Exception:
    natom = None

try:
    import nova_flightlog as flightlog
except Exception:
    flightlog = None

try:
    import nova_search as _ns
except Exception:
    _ns = None

PLUGIN_DIR_NAME = "plugins"
MAX_PLUGIN_BYTES = 64 * 1024
MAX_PLUGINS = 24
MAX_TOOLS = 12
MAX_PARAMS = 16
MAX_BODY = 2 * 1024 * 1024
MAX_PREVIEW = 4000
MAX_URL = 2000
DEFAULT_TIMEOUT = 15

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")   # 1-char tools ok

_PLUGINS_LOCK = None  # created lazily (threading import below)
import threading
_PLUGINS_LOCK = threading.RLock()
_CACHE = {}            # ws -> {"plugins": [...], "errors": [...], "ts": float}
_CACHE_TTL = 2.0


def kill_switch():
    return os.environ.get("NOVA_PLUGINS", "") == "0"


def plugins_dir(ws):
    base = getattr(ws, "root", None)
    if base is None or isinstance(ws, (str, Path)):
        base = ws
    return Path(str(base)) / ".nova" / PLUGIN_DIR_NAME


def _env_file(ws):
    return plugins_dir(ws) / ".env"


def _load_env(ws):
    """Tiny KEY=VALUE reader for the plugin secrets file (0600)."""
    out = {}
    try:
        p = _env_file(ws)
        if not p.is_file():
            return out
        for ln in p.read_text(encoding="utf-8",
                              errors="replace").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if NAME_RE.match(k) or re.match(r"^[A-Z][A-Z0-9_]*$", k):
                out[k] = v[:400]
        return out
    except Exception:
        return out


def set_secret(ws, name, value):
    """Store one plugin secret in .env (best effort, 0600).
    v8.0: read-modify-write runs under the cross-process file lock -
    the REPL and the web server share the file and used to lose
    updates (last writer replaced the WHOLE env)."""
    try:
        d = plugins_dir(ws)
        d.mkdir(parents=True, exist_ok=True)
        p = _env_file(ws)
        def _write():
            env = _load_env(ws)
            if value:
                env[name] = str(value)[:400]
            else:
                env.pop(name, None)
            body = "\n".join("%s=%s" % (k, v)
                              for k, v in sorted(env.items()))
            if natom is not None:
                return natom.write_text_atomic(p, body + "\n")
            p.write_text(body + "\n", encoding="utf-8")
            return ""
        if natom is not None:
            with natom.file_lock(p.with_suffix(".lock"), timeout=8.0):
                return _write()
        return _write()
    except Exception as e:
        return str(e)


def _quarantine(p):
    """Move a broken plugin file to plugins/corrupt/ (never delete)."""
    try:
        q = p.parent / "corrupt"
        q.mkdir(parents=True, exist_ok=True)
        os.replace(str(p), str(q / (p.name + "." +
                                    str(int(time.time())) + ".corrupt")))
    except Exception:
        pass


# ------------------------------------------------------------- validation
def _valid_tool(t):
    if not isinstance(t, dict):
        return "tool is not an object"
    if not TOOL_NAME_RE.match(str(t.get("name") or "")):
        return "tool name must match ^[a-z][a-z0-9_]{0,31}$"
    if not str(t.get("description") or "").strip():
        return "tool needs a description"
    if not str(t.get("url") or "").strip():
        return "tool needs a url"
    if len(str(t.get("url") or "")) > MAX_URL:
        return "url too long"
    method = str(t.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        return "method must be GET or POST"
    params = t.get("params") or []
    if not isinstance(params, list) or len(params) > MAX_PARAMS:
        return "params must be a list of at most %d" % MAX_PARAMS
    for p in params:
        if not isinstance(p, dict) or not TOOL_NAME_RE.match(
                str(p.get("name") or "")):
            return "bad param entry (needs a valid name)"
        if str(p.get("in") or "query") not in ("query", "path", "body"):
            return "param 'in' must be query|path|body"
    key = t.get("key")
    if key is not None:
        if not isinstance(key, dict):
            return "key must be an object {env, in, param}"
        if not str(key.get("env") or ""):
            return "key needs an env var name"
        if str(key.get("in") or "query") not in ("query", "path", "header"):
            return "key 'in' must be query|path|header"
    return ""


def _validate_plugin(data, fname):
    """Returns (clean_plugin_dict, error). strict - a plugin either
    loads whole or not at all (no half-trusted tools)."""
    if not isinstance(data, dict):
        return None, "not a JSON object"
    name = str(data.get("name") or "")
    if not NAME_RE.match(name):
        return None, "plugin name must match ^[a-z][a-z0-9_]{1,31}$"
    desc = str(data.get("description") or "").strip()[:200]
    tools_in = data.get("tools")
    if not isinstance(tools_in, list) or not tools_in:
        return None, "tools must be a non-empty list"
    if len(tools_in) > MAX_TOOLS:
        return None, "at most %d tools per plugin" % MAX_TOOLS
    tools = []
    seen = set()
    for t in tools_in:
        err = _valid_tool(t)
        if err:
            return None, "%s: %s" % (name, err)
        tn = t["name"]
        if tn in seen:
            return None, "duplicate tool name: " + tn
        seen.add(tn)
        tools.append({
            "name": tn,
            "description": str(t.get("description") or "").strip()[:200],
            "method": str(t.get("method") or "GET").upper(),
            "url": str(t.get("url") or "").strip(),
            "params": [{"name": p["name"],
                        "in": str(p.get("in") or "query"),
                        "required": bool(p.get("required")),
                        "desc": str(p.get("desc") or "")[:120]}
                       for p in (t.get("params") or [])],
            "key": {"env": str((t.get("key") or {}).get("env") or ""),
                    "in": str((t.get("key") or {}).get("in") or "query"),
                    "param": str((t.get("key") or {}).get("param") or "key")}
                   if t.get("key") else None,
            "headers": {str(k)[:60]: str(v)[:300]
                        for k, v in ((t.get("headers") or {}).items())
                        if isinstance(k, str) and isinstance(v, str)},
        })
    return {"name": name, "description": desc,
            "version": str(data.get("version") or "1.0")[:20],
            "file": fname, "tools": tools}, ""


# ------------------------------------------------------------- discovery
def load_plugins(ws, force=False):
    """Scan the plugins dir -> {"plugins": [...], "errors": [...]}.
    Cached for 2 s per workspace (the agent calls this every turn via
    the tools index). Fail-soft: unreadable dir = no plugins."""
    key = str(getattr(ws, "root", ws))
    with _PLUGINS_LOCK:
        c = _CACHE.get(key)
        if not force and c and (time.time() - c["ts"]) < _CACHE_TTL:
            return c
    d = plugins_dir(ws)
    plugins, errors = [], []
    try:
        if kill_switch():
            files = []
        else:
            files = sorted(d.glob("*.json"))
    except Exception:
        files = []
    if len(files) > MAX_PLUGINS:
        errors.append("too many plugin files - only the first %d load"
                      % MAX_PLUGINS)
        files = files[:MAX_PLUGINS]
    taken_names = set()
    for p in files:
        try:
            if p.stat().st_size > MAX_PLUGIN_BYTES:
                errors.append("%s: too large (cap %d KB) - quarantined"
                              % (p.name, MAX_PLUGIN_BYTES // 1024))
                _quarantine(p)
                continue
            raw = p.read_bytes()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as e:
                errors.append("%s: broken JSON (%s) - quarantined"
                              % (p.name, str(e)[:80]))
                _quarantine(p)
                continue
            plug, err = _validate_plugin(data, p.name)
            if err:
                errors.append("%s: %s - quarantined" % (p.name, err))
                _quarantine(p)
                continue
            if plug["name"] in taken_names:
                errors.append("%s: duplicate plugin name '%s' - skipped"
                              % (p.name, plug["name"]))
                continue
            taken_names.add(plug["name"])
            plugins.append(plug)
        except Exception as e:
            errors.append("%s: %s" % (p.name, str(e)[:100]))
    out = {"plugins": plugins, "errors": errors, "ts": time.time(),
           "dir": str(d), "disabled": kill_switch()}
    with _PLUGINS_LOCK:
        _CACHE[key] = out
    return out


def all_tools(ws, force=False):
    """Flat [(plugin, tool)] list used for the TOOLS index / model help."""
    st = load_plugins(ws, force=force)
    out = []
    for plug in st.get("plugins", []):
        for t in plug.get("tools", []):
            out.append((plug, t))
    return out


def find_tool(ws, qualified):
    """'weather.get' -> (plugin, tool) or (None, None)."""
    pname, _, tname = str(qualified or "").partition(".")
    if not tname:
        return (None, None)
    for plug, t in all_tools(ws):
        if plug["name"] == pname and t["name"] == tname:
            return (plug, t)
    return (None, None)


# ------------------------------------------------------------- execution
def _redact(text, secret):
    if not secret:
        return str(text or "")[:600]
    s = str(text or "")
    return s.replace(secret, "***")[:600]


def _percent(s):
    try:
        import urllib.parse
        return urllib.parse.quote(str(s), safe="")
    except Exception:
        return str(s)


def _build_request(ws, plug, tool, params):
    """Pure request builder -> (request_dict, error). Mirrors the iran
    services engine: {p} substitution, {p?} optional drop, key env.
    v8.0: user-input problems (missing required params) are reported
    BEFORE the key check - the caller sees THEIR mistake, not ours."""
    params = dict(params or {})
    url = tool["url"]
    # 1) params
    path_vals, query_vals, body_vals = {}, {}, {}
    for p in tool.get("params", []):
        name, where = p["name"], p["in"]
        v = params.get(name)
        if v is None or str(v) == "":
            if p.get("required"):
                return None, "missing required parameter: " + name
            continue
        v = str(v)[:400]
        if where == "path":
            path_vals[name] = _percent(v)
        elif where == "query":
            query_vals[name] = v
        else:
            body_vals[name] = v
    # 2) the key: absent -> refuse with a helpful message
    key_def = tool.get("key")
    secret = ""
    if key_def:
        env = _load_env(ws)
        secret = env.get(key_def["env"]) or os.environ.get(
            key_def["env"], "")
        if not secret:
            return None, ("the API key %s is not set - add it to "
                          ".nova/plugins/.env as %s=... or export it"
                          % (key_def["env"], key_def["env"]))
    # 3) URL: substitute path params (percent-encoded), then query.
    #    v8.0: the OPTIONAL {k?} form is substituted too when the param
    #    was provided (it used to be dropped even with a value).
    for k, v in path_vals.items():
        url = url.replace("{" + k + "}", v)
        url = url.replace("{" + k + "?}", v)
    if key_def and key_def["in"] == "path":
        url = url.replace("{%s}" % key_def["param"], _percent(secret))
        url = url.replace("{%s?}" % key_def["param"], _percent(secret))
    # any leftover {x} token: UNDECLARED names are a broken template -
    # refuse loudly; DECLARED-but-unprovided names (written without the
    # '?') used to ship literally - drop them like the ? form.
    import re as _re
    declared = {p["name"] for p in tool.get("params", [])}
    for m in _re.finditer(r"\{(\w+?)\??\}", url):
        tok = m.group(1)
        if tok == (key_def["param"] if key_def else None):
            continue
        if tok not in declared:
            return None, "url references an undeclared parameter: " + tok
    url = _re.sub(r"\{\w+?\??\}", "", url)
    if query_vals or (key_def and key_def["in"] == "query"):
        import urllib.parse
        q = dict(query_vals)
        if key_def and key_def["in"] == "query":
            q[key_def["param"]] = secret
        sep = "&" if "?" in url else "?"
        url = url + sep + urllib.parse.urlencode(q)
    if len(url) > MAX_URL:
        return None, "built url too long"
    # 4) SSRF guard - FAIL CLOSED (no policy module = no plugin HTTP)
    if _ns is None:
        return None, "the SSRF policy module is unavailable - plugin " \
                     "HTTP is refused"
    safe = _ns.safe_url(url)
    if safe is None:
        return None, "url refused by the private-network policy"
    url = safe
    # 5) headers + body
    headers = {"User-Agent": "NovaAssistant-Plugin"}
    for k, v in (tool.get("headers") or {}).items():
        v = str(v).replace("{key}", secret if key_def else "")
        if "\r" in v or "\n" in v:
            return None, "header value contains a newline"
        headers[k] = v
    if key_def and key_def["in"] == "header":
        headers[tool["key"].get("param") or "Authorization"] = secret
    data = None
    if tool["method"] == "POST" and body_vals:
        data = json.dumps(body_vals, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return {"url": url, "method": tool["method"], "headers": headers,
            "data": data, "secret": secret}, ""


def run_tool(ws, qualified, params, timeout=DEFAULT_TIMEOUT):
    """Execute one plugin tool. Returns a dict (never raises).
    The SECRET never appears in any output field."""
    try:
        to = max(2, min(int(timeout or DEFAULT_TIMEOUT), 60))
    except (TypeError, ValueError):
        to = DEFAULT_TIMEOUT
    plug, tool = find_tool(ws, qualified)
    if plug is None:
        st = load_plugins(ws)
        avail = ", ".join(sorted(
            p["name"] + "." + t["name"]
            for p in st.get("plugins", []) for t in p.get("tools", [])))
        return {"ok": False, "error": "no plugin tool '%s' - available: %s"
                % (qualified, avail or "(none)")}
    if kill_switch():
        return {"ok": False, "error": "the plugin system is disabled "
                                      "(NOVA_PLUGINS=0)"}
    try:
        req, err = _build_request(ws, plug, tool, params)
    except Exception as e:
        req, err = None, str(e)[:200]
    if req is None:
        # v8.0: redact with the key the build had resolved (the error
        # may quote a header/url that carried it)
        env_key = ""
        try:
            key_def = tool.get("key") if tool else None
            if key_def:
                env_key = _load_env(ws).get(key_def["env"]) or ""
        except Exception:
            env_key = ""
        _flog("plugin.run", "build refused", tool=qualified, reason=err,
              level="warn")
        return {"ok": False, "error": _redact(err, env_key)}
    secret = req.pop("secret", "")
    import urllib.request
    import urllib.error
    t0 = time.time()
    try:
        r = urllib.request.Request(req["url"], data=req["data"],
                                   headers=req["headers"],
                                   method=req["method"])
        with urllib.request.urlopen(r, timeout=to) as resp:
            status = resp.status
            raw = resp.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raw = raw[:MAX_BODY]
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(65536).decode("utf-8", "replace")
        except Exception:
            body = ""
        finally:
            try:
                e.close()
            except Exception:
                pass
        ms = int((time.time() - t0) * 1000)
        msg = "HTTP %d: %s" % (e.code, _redact(body[:200], secret))
        _flog("plugin.run", "http error", tool=qualified, status=e.code,
              ms=ms, level="warn")
        return {"ok": False, "error": msg, "status": e.code, "ms": ms}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        _flog("plugin.run", "request failed", tool=qualified, ms=ms,
              reason=str(e)[:120], level="warn")
        return {"ok": False, "error": _redact(str(e), secret), "ms": ms}
    ms = int((time.time() - t0) * 1000)
    text = raw.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except Exception:
        data = None
    _flog("plugin.run", "tool ok", tool=qualified, status=status, ms=ms)
    try:
        data_len = len(json.dumps(data, ensure_ascii=False)) if \
            data is not None else 0
    except Exception:
        data_len = MAX_PREVIEW + 1      # unserializable -> preview only
    out = {"ok": 200 <= status < 300, "status": status, "ms": ms,
           "plugin": plug["name"], "tool": tool["name"],
           "data": data if (data is not None and
                            data_len <= MAX_PREVIEW) else None,
           "preview": text[:800] if data is None else ""}
    if secret:
        out["preview"] = _redact(out.get("preview", ""), secret)
    return out


def _flog(where, msg, **fields):
    if flightlog is not None:
        try:
            flightlog.log(where, msg, **fields)
        except Exception:
            pass


# ---------------------------------------------------------------- web API
def web_state(ws):
    """Payload for GET /api/plugins (never raises, no secrets)."""
    try:
        st = load_plugins(ws)
        return {
            "version": VERSION,
            "disabled": st.get("disabled", False),
            "dir": st.get("dir", ""),
            "plugins": [{"name": p["name"],
                         "description": p["description"],
                         "version": p.get("version", "1.0"),
                         "file": p.get("file", ""),
                         "tools": [{"name": t["name"],
                                    "description": t["description"],
                                    "method": t["method"],
                                    "params": t["params"],
                                    "has_key": bool(t.get("key"))}
                                   for t in p.get("tools", [])]}
                        for p in st.get("plugins", [])],
            "errors": st.get("errors", []),
        }
    except Exception as e:
        return {"version": VERSION, "disabled": kill_switch(),
                "plugins": [], "errors": [str(e)[:200]]}


def web_action(ws, action, payload):
    """POST /api/plugins {action, ...} -> (ok, payload, http_status).
    Actions: run (qualified + params), reload, set_secret (name+value)."""
    try:
        if kill_switch() and action != "reload":
            return (False, {"error": "the plugin system is disabled"}, 403)
        action = str(action or "").strip().lower()
        if action == "run":
            q = str((payload or {}).get("qualified") or "").strip()
            params = (payload or {}).get("params") or {}
            if not isinstance(params, dict):
                return (False, {"error": "params must be an object"}, 400)
            out = run_tool(ws, q, params)
            return (out.get("ok") is True, out,
                    200 if out.get("ok") else 502)
        if action == "reload":
            st = load_plugins(ws, force=True)
            return (True, {"reloaded": len(st.get("plugins", [])),
                           "errors": st.get("errors", [])}, 200)
        if action == "set_secret":
            name = str((payload or {}).get("name") or "").strip()
            value = str((payload or {}).get("value") or "")
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$", name):
                return (False, {"error": "bad secret name"}, 400)
            err = set_secret(ws, name, value)
            if err:
                return (False, {"error": err}, 500)
            _flog("plugin.secret", "secret saved", name=name)
            return (True, {"saved": name,
                           "masked": ("***" + value[-2:]) if len(value) > 3
                           else "***"}, 200)
        return (False, {"error": "unknown action"}, 400)
    except Exception as e:
        return (False, {"error": str(e)[:200]}, 500)


# ------------------------------------------------------------------ CLI
def cli_summary(ws):
    """One-shot summary for /plugin list."""
    st = load_plugins(ws)
    lines = []
    if st.get("disabled"):
        lines.append("plugin system DISABLED (NOVA_PLUGINS=0)")
    if not st.get("plugins"):
        lines.append("no plugins loaded - drop JSON files into " +
                     st.get("dir", ".nova/plugins/"))
    for p in st.get("plugins", []):
        lines.append("%s v%s - %s" % (p["name"], p.get("version", "1.0"),
                                      p["description"] or "-"))
        for t in p.get("tools", []):
            req = ", ".join(x["name"] for x in t["params"]
                            if x.get("required"))
            lines.append("    %s.%s(%s) %s - %s"
                         % (p["name"], t["name"], req, t["method"],
                            t["description"][:100]))
    for e in st.get("errors", []):
        lines.append("[!] " + e)
    return "\n".join(lines)
