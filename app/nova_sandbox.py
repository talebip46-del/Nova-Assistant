#!/usr/bin/env python3
# =====================================================================
#  Nova Code - local command sandbox (v6.8)
#
#  Risky commands may run inside a lightweight LOCAL container on the
#  same machine - when one is installed. Detection order:
#    docker | podman  -> best isolation: no network, mem/cpu caps,
#                        workspace bind-mounted read-write
#    firejail         -> --net=none + private home = the workspace
#    bwrap            -> read-only /, private /tmp + /dev, unshared net,
#                        workspace bound read-write
#  Nothing installed -> (None, reason); the caller keeps the classic
#  screening + timeout path and SAYS SO (no false sense of security).
#
#  Config: .nova/sandbox.json {"engine","image","mem","cpus"} written by
#  /sandbox on|off|docker|podman|firejail|bwrap|image <name>.
# =====================================================================
import json
import re
import shutil
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:
    natom = None

CONFIG = "sandbox.json"
DEFAULTS = {"on": False, "engine": "", "image": "python:3.11-slim",
            "mem": "2g", "cpus": "2"}


def config_path(ws):
    return Path(ws) / ".nova" / CONFIG


def _valid_image(v):
    """v8.0: the image lands in the ARGV of docker/podman run - any token
    starting with '-' is parsed as a FLAG by the engine itself, so
    '/sandbox image --network=host' silently disabled the network
    isolation and 'image --privileged' / 'image -v /:/host' escalated.
    Only real image references pass (name[:tag][@digest], optional
    registry host:port)."""
    return bool(re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._/:@\-]*(?:[:@][A-Za-z0-9][A-Za-z0-9._\-]*)?",
        v)) and not v.startswith("-")


def _valid_mem(v):
    return bool(re.fullmatch(r"\d+(?:\.\d+)?[bkmgt]?$", v.lower()))


def _valid_cpus(v):
    return bool(re.fullmatch(r"\d+(?:\.\d+)?$", v))


def load_config(ws):
    """Defaults merged with the saved config; hostile values ignored
    (v8.0: image/mem/cpus are charset-validated too - see _valid_image)."""
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(config_path(ws).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if isinstance(raw.get("on"), bool):
                cfg["on"] = raw["on"]
            for k in ("engine", "image", "mem", "cpus"):
                v = raw.get(k)
                if isinstance(v, str) and v.strip() and len(v) < 200:
                    cfg[k] = v.strip()
            if not _valid_image(cfg["image"]):
                cfg["image"] = DEFAULTS["image"]
            if not _valid_mem(cfg["mem"]):
                cfg["mem"] = DEFAULTS["mem"]
            if not _valid_cpus(cfg["cpus"]):
                cfg["cpus"] = DEFAULTS["cpus"]
    except (OSError, ValueError):
        pass
    return cfg


def save_config(ws, updates):
    p = config_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = load_config(ws)
    cur.update({k: v for k, v in (updates or {}).items()
                if k in DEFAULTS and isinstance(v, (str, bool))})
    # v7.1.0: atomic write via nova_atomic - the fixed "sandbox.json.tmp~"
    # scratch name was the exact cross-process torn-write bug class every
    # sibling module fixed in v6.7 (REPL + web both save this config).
    if natom is not None:
        err = natom.write_text_atomic(
            p, json.dumps(cur, indent=1, ensure_ascii=False))
        return err or ""
    import os
    tmp = str(p) + ".tmp~%d" % (os.getpid(),)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cur, fh, indent=1)
    try:
        os.replace(tmp, p)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return str(e)
    return ""


# --------------------------------------------------------------- engines
def detect_engines():
    """{engine: path} for every usable container runtime on this box."""
    out = {}
    for name in ("docker", "podman", "firejail", "bwrap"):
        p = shutil.which(name)
        if p:
            out[name] = p
    return out


def pick_engine(cfg, engines):
    """Configured engine if present, else the detection order."""
    want = (cfg.get("engine") or "").strip().lower()
    if want in engines:
        return want
    for e in ("docker", "podman", "firejail", "bwrap"):
        if e in engines:
            return e
    return None


def wrap(ws, argv, cfg=None, engines=None, cwd=None):
    """Build the sandboxed argv. Returns (engine, full_argv) or
    (None, reason). argv is a LIST - never a shell string (this module
    never becomes an injection vector itself)."""
    if not isinstance(argv, (list, tuple)) or not argv:
        return (None, "sandbox needs an argv list")
    cfg = cfg or {}
    engines = engines if engines is not None else detect_engines()
    engine = pick_engine(cfg, engines)
    if engine is None:
        return (None, "no container runtime found (install docker, podman, "
                      "firejail or bubblewrap)")
    ws = Path(ws)
    mem = str(cfg.get("mem") or "2g")
    cpus = str(cfg.get("cpus") or "2")
    image = str(cfg.get("image") or DEFAULTS["image"])
    # v8.0: validate HERE too - wrap() accepts a caller-supplied cfg dict
    # that never went through load_config, so a hostile value could
    # otherwise reach the engine argv as a flag.
    if not _valid_image(image):
        image = DEFAULTS["image"]
    if not _valid_mem(mem):
        mem = DEFAULTS["mem"]
    if not _valid_cpus(cpus):
        cpus = DEFAULTS["cpus"]
    if engine in ("docker", "podman"):
        base = [engines[engine], "run", "--rm",
                "--network", "none",
                "--memory", mem, "--cpus", cpus,
                "--security-opt", "no-new-privileges",
                "-v", f"{ws}:/work", "-w", "/work",
                image]
        return (engine, base + [str(a) for a in argv])
    if engine == "firejail":
        base = [engines[engine], "--net=none", "--noroot", "--quiet",
                f"--private={ws}", "--"]
        return (engine, base + [str(a) for a in argv])
    # bubblewrap: read-only root, fresh /tmp + /dev, no network, cwd bound rw
    base = [engines[engine],
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--proc", "/proc",
            "--bind", str(ws), str(ws),
            "--chdir", str(cwd or ws),
            "--unshare-net",
            "--die-with-parent", "--new-session"]
    return (engine, base + [str(a) for a in argv])


def status_line(ws, cfg=None, engines=None):
    cfg = cfg or load_config(ws)
    engines = engines if engines is not None else detect_engines()
    eng = pick_engine(cfg, engines) if engines else None
    state = "ON" if cfg.get("on") else "OFF"
    if eng:
        return f"sandbox {state} via {eng} (image: {cfg.get('image') or '-'})"
    return f"sandbox {state}, but NO container runtime is installed - " \
           "commands still run unsandboxed (screening + timeout only)"


# =====================================================================
#  v8.0 "clear": FILE SANDBOX - the agent's file-access isolation
#
#  The command sandbox above isolates RUNS. This half isolates the
#  agent's own FILE operations (apply pipeline, read actions): they are
#  confined to the workspace, can never reach sensitive SYSTEM paths
#  (via symlinks, absolute paths or traversal - safe_join already did
#  the first two), and can never write into Nova's own .nova state
#  (a model-issued === FILE: .nova/profile.json === used to be a valid
#  write and silently re-configured the agent on the next turn).
#
#  - check_write() / check_read(): resolve + verify, never raise
#  - DEFAULT ON; NOVA_SANDBOX_FILES=0 turns it off (the run-sandbox
#    above is unaffected by that switch)
#  - file_guard status shows in /sandbox status and the web doctor
# =====================================================================
import os as _os

FILE_GUARD_ENV = "NOVA_SANDBOX_FILES"

# sensitive SYSTEM locations the agent never needs (checked on the
# RESOLVED path; prefix match on the POSIX side, drive-relative on
# Windows: the workspace containment already blocks everything outside)
SENSITIVE_UNIX = ("/etc", "/root", "/boot", "/proc", "/sys", "/dev",
                  "/bin", "/sbin", "/usr", "/lib", "/lib64", "/opt",
                  "/srv", "/run", "/var/log", "/var/run")

# inside the workspace: Nova's own state + host-side secrets that must
# never be agent-writable/readable through the FILE protocol (compared
# LOWERCASED - the FS may be case-insensitive)
SENSITIVE_WS_PARTS = (".ssh", ".gnupg", ".aws", ".kube", ".docker")
NOVA_STATE_DIR = ".nova"


def file_guard_enabled():
    return _os.environ.get(FILE_GUARD_ENV, "") != "0"


def check_path(ws, path, write=False):
    """FileSandbox verdict for ONE path. Returns (True, '') or
    (False, reason). Never raises; on internal failure it fails CLOSED
    for writes and OPEN for reads (a broken sandbox must not make the
    agent unable to read its own project)."""
    try:
        if not file_guard_enabled():
            return (True, "")
        from pathlib import Path as _P
        # v8.0: pathlib.Path HAS a `.root` attribute ("/") - a plain Path
        # input must be detected BY TYPE before any getattr probe, or the
        # sandbox quietly believes the workspace is "/" (the exact trap
        # nova_think._ws_root documents).
        base = ws
        if not isinstance(base, (str, _P)):
            base = getattr(ws, "root", ws)
        ws_p = _P(str(base)).resolve()
        p = _P(str(path))
        # v8.0: backslashes are treated as separators BEFORE resolution -
        # on POSIX "..\..\win.txt" is literally a legal file NAME, but a
        # Windows-shaped traversal arriving through a copied path must
        # never be treated as an in-workspace file. (On Windows this is
        # the native separator anyway.)
        if "\\" in str(p):
            p = _P(str(p).replace("\\", "/"))
        if not p.is_absolute():
            p = ws_p / p
        rp = p.resolve()
        # 1) the resolved path must live INSIDE the workspace
        try:
            rel = rp.relative_to(ws_p)
        except ValueError:
            return (False, "outside the workspace")
        parts = rel.parts
        # 2) system-sensitive dirs are never reachable even if someone
        #    bind-mounted/bound them inside (defense in depth)
        as_posix = rp.as_posix()
        for pre in SENSITIVE_UNIX:
            if as_posix == pre or as_posix.startswith(pre + "/"):
                return (False, "sensitive system path: " + pre)
        # 3) Nova's own state dir is agent-untouchable (writes always,
        #    reads too - the agent has its own tools for state).
        #    v8.0: compares are CASE-INSENSITIVE - on macOS/Windows the
        #    filesystem is, and .NOVA/x must not bypass the .nova rule.
        if parts and parts[0].lower() == NOVA_STATE_DIR:
            if write:
                return (False, "the agent cannot write into .nova "
                               "(Nova's own state)")
            return (False, "the agent cannot read Nova's own .nova state")
        # 3b) home-relative trick paths stay literal when unexpanded
        # ("~/.ssh/id_rsa", "$HOME/...") - never treat them as project files
        if parts and parts[0] in ("~", "$HOME", "$HOME/"):
            return (False, "home-relative paths are not project files")
        # 4) host-side credential folders inside the project (case-insensitive
        # for the same reason as 3)
        for part in parts:
            if part.lower() in SENSITIVE_WS_PARTS:
                return (False, "sensitive folder: " + part)
        return (True, "")
    except Exception:
        if write:
            return (False, "sandbox check failed")
        return (True, "")


def check_batch(ws, rel_paths, write=True):
    """Check many relpaths at once; returns the FIRST rejection as
    (False, relpath, reason) or (True, None, '')."""
    from pathlib import Path as _P
    base = ws
    if not isinstance(base, (str, _P)):
        base = getattr(ws, "root", ws)
    for rel in rel_paths or []:
        ok, why = check_path(ws, _P(str(base)) / str(rel), write=write)
        if not ok:
            return (False, str(rel), why)
    return (True, None, "")


def status_line_files():
    if not file_guard_enabled():
        return "file sandbox OFF (NOVA_SANDBOX_FILES=0) - agent file " \
               "operations are only containment-checked"
    return "file sandbox ON - agent file operations are confined to the " \
           "workspace; .nova and system-sensitive paths are blocked"


def status_line_all(ws, cfg=None, engines=None):
    return status_line(ws, cfg=cfg, engines=engines) + " | " + \
        status_line_files()
