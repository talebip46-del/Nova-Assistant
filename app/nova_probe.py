#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - the BUG HUNTER (v8.6 "bug net + vision")
#
#  The user's complaint after v8.4: "the output is beautiful and the
#  syntax is correct now - but WHAT IF it still has bugs? A section of
#  the work missing, or a button (or anything else) that simply does
#  nothing." Syntax gates cannot see those: the code parses, the page
#  renders, and the button is still DEAD. This module is the fix - a
#  fleet of BEHAVIOR probes that hunt the bug classes syntax cannot:
#
#    1. THE WIRING PROBE (wiring_check)      deterministic, offline,
#       zero-model. The #1 cause of "a button does nothing" in
#       generated bundles: JS looks up an id that exists nowhere,
#       inline onclick names a function nobody defined, a <script
#       src> / <link href> points at a file that was never written,
#       a JS classList toggles a class no stylesheet knows. The probe
#       builds the element graph across the WHOLE batch (html + js +
#       css, template literals and .id assignments included) plus the
#       existing workspace, and reports every DEAD reference with a
#       line number. Python relative imports and node require("./x")
#       paths get the same treatment. Runs PRE-apply as a gate (a
#       batch with dead wiring is refused before one byte is written)
#       and POST-apply over the full workspace.
#    2. THE SMOKE PROBE (smoke_check)        runtime reality: the
#       freshly written entry scripts are EXECUTED (tight timeout,
#       stdin closed, capped output, the run-sandbox honored when the
#       user configured one) and the crash is parsed into a finding -
#       Tracebacks, ReferenceError, TypeError... A script that starts
#       a server is recognized by its output and reported as healthy;
#       an interactive script (input()) is reported as info, not a
#       bug. NOVA_PROBE_RUN=0 (or /probe smoke off) never executes.
#    3. THE BROWSER PROBE (browser_check)    when Playwright +
#       Chromium exist on the machine: the applied page loads in a
#       headless browser, console errors / page errors / failed
#       resource loads are captured, then up to 8 visible buttons are
#       CLICKED - a crash on click is a dead feature, caught. Fully
#       offline (file:// URL). No Playwright = honest skip; the wiring
#       probe stays the offline floor.
#    4. THE COMPLETENESS PROBE (review_completeness)  "a part of the
#       work fell off": the supervisor asks the LOCAL brain whether
#       the delivered files implement EVERYTHING the user asked for
#       (its wiring skeleton - ids, buttons, handlers, functions -
#       rides along, so the model judges facts, not vibes). Advisory
#       only, never on a cloud key.
#    5. THE DEEP SWEEP (static_check, v8.6)  the user's law: "bugs are
#       not limited to buttons - ANYTHING can be a bug: a simple
#       function, EXTRA code, or MISSING code." The deterministic
#       families it hunts (offline, zero-model):
#         - python: call/load of a name that is defined NOWHERE in the
#           file (a missing function/variable -> NameError the moment
#           the line runs), argument-count/kwarg mismatches against
#           same-file signatures (guaranteed TypeError), duplicate
#           defs/classes/methods (the first body is dead), unreachable
#           code after return/raise/break/continue, mutable default
#           arguments, bare `except: pass` that swallows failures,
#           stub bodies (pass / ... / NotImplementedError only).
#         - js: duplicate function declarations in one file (the first
#           silently loses), empty/TODO-only function bodies, silent
#           empty catch blocks.
#         - html: the same id defined twice in one page (the second
#           element can never be selected), an explicit type="button"
#           that no script listens to and no inline handler names (a
#           button wired to NOTHING), an inline handler whose defining
#           script the page never loads (dead in THIS page even though
#           some other file defines it).
#         - cross-file: functions defined but never referenced anywhere
#           in the pool (extra code), TODO/FIXME promises.
#       Gate errors stay reserved for the UNAMBIGUOUS families
#       (undefined names, signature math, duplicate defs); everything
#       heuristic stays advisory.
#
#  Everything is fail-soft end to end: a missing probe, a broken
#  browser, a crashed run can never break an apply - and correctness
#  NEVER depends on the internet (all probes are offline by design).
#
#  Settings live per-workspace in .nova/probe.json (guardian.json
#  pattern): on / wiring / smoke / browser / review / reject_wiring /
#  deep / reject_deep.
#
#  Pure standard library (Playwright optional), fail-soft everywhere.
# =====================================================================
import ast
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:                       # pragma: no cover - fail-soft
    natom = None

# v8.7: python 3.10+ match-statement binders (MatchAs / MatchStar) -
# absent on 3.8/3.9, where the tuple is simply empty and the branch in
# _py_facts never fires (the hasattr-based second branch covers rest).
_MATCH_BIND_NODES = tuple(
    getattr(ast, _n) for _n in ("MatchAs", "MatchStar")
    if hasattr(ast, _n))

# ------------------------------------------------------------------ caps
MAX_WIRING_WS_FILES = 120        # workspace files scanned for the pool
MAX_WIRING_FILE_CHARS = 300_000  # per-file cap before "structure only"
MAX_WIRING_FINDINGS = 40         # total wiring findings per report
MINIFY_AVG_LINE = 400            # avg line length above this = minified
MINIFY_MIN_CHARS = 2_000         # ...only when the file is also this big
SMOKE_MAX_ENTRIES = 2            # entry scripts executed per batch
SMOKE_OUTPUT_CAP = 8_000         # captured output per run
BROWSER_BUDGET_S = 25.0          # hard wall-clock for the whole probe
BROWSER_MAX_ERRORS = 12
BROWSER_MAX_CLICKS = 8
REVIEW_MAX_FILES = 4             # skeletons sent to the completeness check
REVIEW_SKELETON_CHARS = 1_200    # per-file skeleton cap
REVIEW_REQUEST_CHARS = 4_000     # user-request cap in the prompt
MAX_GAPS = 6                     # model-reported gaps kept

SETTINGS_FILE = "probe.json"
DEFAULTS = {
    "on": True,            # the whole bug hunter
    "wiring": True,        # cross-file wiring sweep (deterministic)
    "smoke": True,         # runtime smoke runs of the entry scripts
    "browser": True,       # headless browser probe (Playwright present)
    "review": True,        # completeness review (local brain, advisory)
    "reject_wiring": True, # dead wiring refuses the batch pre-apply
    "deep": True,          # v8.6 deep static sweep (functions/extra/missing)
    "reject_deep": True,   # unambiguous deep findings refuse the batch too
}
MAX_SETTINGS_BYTES = 4_000


def _env_float(name, default):
    try:
        raw = str(os.environ.get(name, "")).strip()
        val = float(raw) if raw else default
        # v8.12: nan/inf silently disabled the timeouts they fed
        # (subprocess.run(timeout=nan) raised inside every run); an env
        # knob that feeds a DEADLINE must be a finite number.
        if not math.isfinite(val):
            return default
        return val
    except ValueError:
        return default


# =====================================================================
# 0. SETTINGS - per-workspace .nova/probe.json (guardian.json pattern)
# =====================================================================
def settings_path(ws):
    return Path(ws) / ".nova" / SETTINGS_FILE


def _valid_fields(obj):
    """ONLY the valid keys of `obj` survive - a hand-edited file can
    never poison the stored settings."""
    out = {}
    if not isinstance(obj, dict):
        return out
    for key in ("on", "wiring", "smoke", "browser", "review",
                "reject_wiring", "deep", "reject_deep"):
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
        saved = json.loads(p.read_text(encoding="utf-8",
                                       errors="replace"))
        # v8.12: the same anti-freeze law the v8.11 round applied to
        # guardian/vision/ctxengine - a hand-edited file with ZERO valid
        # keys must not claim custom=True (the panel then shows a
        # customization that does not exist).
        valid = _valid_fields(saved)
        d.update(valid)
        d["custom"] = bool(valid)
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
    """Setting truth with the DEFAULT as fallback (missing module /
    broken file must never silently disable a probe)."""
    if not isinstance(cfg, dict):
        return DEFAULTS.get(key, True)
    return bool(cfg.get(key, DEFAULTS.get(key, True)))


def master_on(cfg=None):
    """Env kill-switch first (air-gapped CI, tests) - then the setting.
    Fail-soft to ON (its default)."""
    if os.environ.get("NOVA_PROBE", "") == "0":
        return False
    return enabled(cfg if cfg is not None else {}, "on")


# =====================================================================
# 1. THE WIRING PROBE - every reference must land on something real
# =====================================================================
# The element graph, built ONCE per report over the combined pool
# (batch bodies ON TOP of the existing workspace files):
#   ids        - where ids are DEFINED (html attrs, template literals,
#                .id = "x" assignments)
#   classes    - where class names are DEFINED (html class=, css rules)
#   handlers   - what inline onclick="..." calls
#   js_fns     - what the js files define (functions / consts / classes)
#   el_refs    - which ids the js looks up (getElementById/querySelector)
#   cls_refs   - which classes the js toggles (querySelector/classList)
#   local_refs - which local files the markup references (src/href)
# A reference with NO definition anywhere = a DEAD button / section.
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".nova",
                ".nova_backups", ".venv", "venv", ".idea", ".vscode",
                "dist", "build", ".pytest_cache"}
_WIRING_EXTS = (".html", ".htm", ".js", ".mjs", ".css")

# ---- definition collectors -----------------------------------------
_HTML_ID_RE = re.compile(
    r"""(?<![\w-])id\s*=\s*["']([A-Za-z][\w:.-]*)["']""")
_HTML_ID_BARE_RE = re.compile(
    r"""(?<![\w-])id=([A-Za-z][\w:.-]*)(?=[\s>])""")   # unquoted attr
_JS_ID_DEF_RE = _HTML_ID_RE            # template literals carry html too
_JS_ID_ASSIGN_RE = re.compile(
    r"""\.id\s*=\s*["']([A-Za-z][\w:.-]*)["']""")
# v8.11: setAttribute("id"/"class", ...) is a real definition too - the
# old collector saw only `.id = "x"`, so healthy JS that builds elements
# with setAttribute was rejected as a dead reference
_JS_SETATTR_ID_RE = re.compile(
    r"""setAttribute\s*\(\s*["']id["']\s*,\s*["']([A-Za-z][\w:.-]*)["']""",
    re.IGNORECASE)
_JS_SETATTR_CLASS_RE = re.compile(
    r"""setAttribute\s*\(\s*["']class["']\s*,\s*["']([^"']+)["']""",
    re.IGNORECASE)
# remote scripts: handlers they define are unknowable offline - a page
# that loads any <script src="https://..."> must not be hard-rejected
# for a handler that may live in the CDN bundle (mirror of the
# _page_handler_gaps remote-src bail)
_REMOTE_SCRIPT_RE = re.compile(
    r"""<script\b[^>]*?src\s*=\s*["'](https?:|//|data:|blob:)[^"']*?["']""",
    re.IGNORECASE)
_HTML_CLASS_RE = re.compile(
    r"""(?<![\w-])class\s*=\s*["']([^"']+)["']""")
_CSS_CLASS_RE = re.compile(
    r"""(?:^|[,{}\s])\.([A-Za-z][\w-]*)""", re.MULTILINE)

_HANDLER_ATTRS = ("onclick", "onchange", "onsubmit", "oninput", "onload",
                  "onkeydown", "onkeyup", "ondblclick", "onmouseover",
                  "onmouseout", "onerror")
_HANDLER_ATTR_RE = re.compile(
    r"""\b(?:%s)\s*=\s*["']([^"']+)["']""" % "|".join(_HANDLER_ATTRS))
# first/last identifier before "(" inside a handler body
_HANDLER_FN_RE = re.compile(
    r"""([A-Za-z_$][\w$.]*)\s*\(\s*[^)]*\)\s*[;]*\s*$""")

_JS_FN_DEF_RES = (
    re.compile(r"""(?<![\w$.])(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"""),
    re.compile(r"""(?<![\w$.])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="""
               r"""\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"""),
    re.compile(r"""(?<![\w$.])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="""
               r"""\s*(?:async\s+)?function\b"""),
    re.compile(r"""(?<![\w$.])window\s*\.\s*([A-Za-z_$][\w$]*)\s*="""),
    re.compile(r"""(?<![\w$.])module\s*\.\s*exports\s*\.\s*"""
               r"""([A-Za-z_$][\w$]*)\s*="""),
    re.compile(r"""(?<![\w$.])class\s+([A-Za-z_$][\w$]*)"""),
)

# ---- reference collectors ------------------------------------------
# v8.10.1 fix: group(1) captures the CALL NAME - the raw-id fallback is
# only correct for getElementById (a raw id, no selector syntax);
# querySelector("form") / querySelectorAll("button") are TAG selectors
# and used to register the tag name as a phantom id reference ->
# "dead reference: #button" rejected perfectly healthy batches.
_JS_EL_REF_RE = re.compile(
    r"""(getElementById|querySelectorAll|querySelector)\(\s*"""
    r"""(['"])([^'"]+)\2""")
_JS_CLASSLIST_RE = re.compile(
    r"""(?:classList|className)\s*\.\s*(?:add|remove|toggle|contains)\s*"""
    r"""\(\s*(['"])([^'"]+)\1""")
_LOCAL_REF_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"'#?]+?)["']""", re.IGNORECASE)
_A_HREF_RE = re.compile(
    r"""<a\b[^>]*?href\s*=\s*["']([^"'#?]+?)["']""", re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(
    r"""<script\b[^>]*?src\s*=\s*["']([^"'#?]+?)["']""", re.IGNORECASE)
_LINK_HREF_RE = re.compile(
    r"""<link\b[^>]*?href\s*=\s*["']([^"'#?]+?)["']""", re.IGNORECASE)
_IMG_SRC_RE = re.compile(
    r"""<img\b[^>]*?src\s*=\s*["']([^"'#?]+?)["']""", re.IGNORECASE)
_PY_REL_IMPORT_RE = re.compile(
    r"""(?m)^\s*from\s+\.{1,3}\s*import\s+([\w ,]+)""")
_PY_ABS_IMPORT_RE = re.compile(
    r"""(?m)^\s*(?:from\s+([\w.]+)\s+import\s|import\s+([\w.]+))""")
_NODE_REL_REQUIRE_RE = re.compile(
    r"""require\(\s*["'](\.{1,2}/[^"']+)["']\s*\)""")
# the browser/standard globals a plain script may call without defining
_JS_GLOBALS = frozenset((
    # dom + browser
    "document", "window", "navigator", "location", "history", "alert",
    "confirm", "prompt", "fetch", "localStorage", "sessionStorage",
    "console", "setTimeout", "setInterval", "clearTimeout",
    "clearInterval", "requestAnimationFrame", "cancelAnimationFrame",
    "getComputedStyle", "matchMedia", "scrollTo", "scrollBy", "open",
    "close", "addEventListener", "removeEventListener", "dispatchEvent",
    "CustomEvent", "Event", "EventTarget", "MutationObserver",
    "IntersectionObserver", "ResizeObserver", "URL", "URLSearchParams",
    "Blob", "File", "FileReader", "FormData", "Headers", "Request",
    "Response", "WebSocket", "Worker", "SharedWorker",
    "MessageChannel", "postMessage", "Image", "Audio", "Video",
    "HTMLElement", "Node", "NodeList", "Element", "SVGElement",
    "DOMParser", "XMLHttpRequest", "AbortController", "AbortSignal",
    "DOMException", "CSS", "crypto", "performance", "screen",
    "event",
    # js builtins
    "Math", "JSON", "Object", "Array", "String", "Number", "Boolean",
    "Date", "RegExp", "Map", "Set", "WeakMap", "WeakSet", "Promise",
    "Symbol", "BigInt", "Error", "TypeError", "RangeError",
    "SyntaxError", "ReferenceError", "EvalError", "URIError",
    "AggregateError", "Intl", "ArrayBuffer", "DataView", "Int8Array",
    "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array",
    "Int32Array", "Uint32Array", "Float32Array", "Float64Array",
    "BigInt64Array", "BigUint64Array", "globalThis", "global",
    "require", "module", "exports", "process", "Buffer", "__dirname",
    "__filename", "queueMicrotask", "structuredClone", "atob", "btoa",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURIComponent",
    "decodeURIComponent", "encodeURI", "decodeURI", "eval", "isNaN",
    "Proxy", "Reflect", "Function", "Generator", "Infinity", "NaN",
    "undefined", "arguments", "this", "super", "import", "escape",
    "unescape", "alert", "queueMicrotask",
    # v8.11: window methods an inline handler may legally call without a
    # local definition - onclick="print()"/"focus()"/"stop()" used to be
    # flagged as dead handlers, refusing HEALTHY pages (and the 'fix'
    # round then shadowed window.print with a no-op, actually breaking
    # the page)
    "print", "focus", "blur", "stop", "scroll", "find",
    "getSelection", "moveBy", "moveTo", "resizeBy", "resizeTo",
    "name", "status", "self", "top", "parent", "frames",
))

# ids/classes that are FRAMEWORK-ish or plain noise when missing
_STYLE_CLASS_HINT_RE = re.compile(r"^(is|has|active|open|show|hidden|"
                                  r"selected|disabled|error|success|"
                                  r"dark|light)[-_]?[\w-]*$", re.I)


def _line_of(body, pos):
    return body.count("\n", 0, pos) + 1


def _is_minified(body):
    if len(body) < MINIFY_MIN_CHARS:
        return False
    lines = body.splitlines() or [body]
    return (len(body) / max(1, len(lines))) > MINIFY_AVG_LINE


def _looks_binary(body):
    sample = body[:8000]
    if not sample:
        return False
    if "\x00" in sample:
        return True
    printable = sum(1 for ch in sample if ch.isprintable()
                    or ch in "\n\r\t")
    return printable / len(sample) < 0.85


def _collect_defs(rel, body, graph):
    """Feed ONE file's definitions into the element graph."""
    low = rel.lower()
    htmlish = low.endswith((".html", ".htm"))
    cssish = low.endswith(".css")
    jsish = low.endswith((".js", ".mjs"))
    if htmlish or (jsish and "<" in body):
        for m in _HTML_ID_RE.finditer(body):
            graph["ids"].setdefault(m.group(1), []).append(rel)
        if htmlish:
            for m in _HTML_ID_BARE_RE.finditer(body):
                graph["ids"].setdefault(m.group(1), []).append(rel)
    if jsish:
        for m in _JS_ID_ASSIGN_RE.finditer(body):
            graph["ids"].setdefault(m.group(1), []).append(rel)
        # v8.11: setAttribute definitions (ids + classes)
        for m in _JS_SETATTR_ID_RE.finditer(body):
            graph["ids"].setdefault(m.group(1), []).append(rel)
        for m in _JS_SETATTR_CLASS_RE.finditer(body):
            for cls in m.group(1).split():
                graph["classes"].setdefault(cls, []).append(rel)
    if htmlish:
        for m in _HTML_CLASS_RE.finditer(body):
            for cls in m.group(1).split():
                graph["classes"].setdefault(cls, []).append(rel)
    if cssish:
        for m in _CSS_CLASS_RE.finditer(body):
            graph["classes"].setdefault(m.group(1), []).append(rel)
    if jsish:
        for rx in _JS_FN_DEF_RES:
            for m in rx.finditer(body):
                graph["js_fns"].setdefault(m.group(1), []).append(rel)
    if htmlish:
        # v8.7: handlers defined in INLINE <script> blocks are real
        # definitions - the graph used to feed only .js/.mjs files, so
        # a single-file page (<button onclick="go()"> + function go)
        # was rejected as "dead handler" even though it runs fine.
        # _page_handler_gaps already harvested inline scripts; the two
        # probes must not contradict each other.
        inline = "".join(_html_script_bodies(body))
        for rx in _JS_FN_DEF_RES:
            for m in rx.finditer(inline):
                graph["js_fns"].setdefault(m.group(1), []).append(rel)


def _selector_tokens(sel):
    """All #id / .class tokens of one css selector string."""
    ids, classes = [], []
    for tok in re.split(r"""[\s,>+~()]+""", sel or ""):
        if tok.startswith("#") and len(tok) > 1:
            ids.append(tok[1:].split(".")[0].split("[")[0])
        elif tok.startswith(".") and len(tok) > 1:
            classes.append(tok[1:].split(".")[0].split("[")[0])
            if ":" in classes[-1]:
                classes[-1] = classes[-1].split(":")[0]
    return [t for t in ids if t], [t for t in classes
                                   if t and not t[0].isdigit()]


def _collect_refs(rel, body, graph):
    """Feed ONE file's REFERENCES into the element graph."""
    low = rel.lower()
    jsish = low.endswith((".js", ".mjs"))
    if jsish:
        for m in _JS_EL_REF_RE.finditer(body):
            call = m.group(1)
            sel = m.group(3)
            ids, classes = _selector_tokens(sel)
            # getElementById passes a RAW id (no '#'); querySelector a
            # selector - the token split catches "#list .item" composite
            # selectors (v8.10.1: the raw-id fallback below is guarded to
            # the getElementById call only)
            if sel.startswith("#") or "#" in sel or \
                    (call == "getElementById" and not sel.startswith(".")):
                for i in ids:
                    graph["el_refs"].setdefault(
                        i, []).append((rel, _line_of(body, m.start())))
            if call == "getElementById" and not sel.startswith("#"):
                # raw id form: also count the whole literal as the id
                if re.match(r"^[A-Za-z][\w:.-]*$", sel):
                    graph["el_refs"].setdefault(
                        sel, []).append((rel, _line_of(body, m.start())))
            for c in classes:
                graph["cls_refs"].setdefault(
                    c, []).append((rel, _line_of(body, m.start())))
        for m in _JS_CLASSLIST_RE.finditer(body):
            graph["cls_refs"].setdefault(
                m.group(2), []).append((rel, _line_of(body, m.start())))
    for m in _HANDLER_ATTR_RE.finditer(body):
        hm = _HANDLER_FN_RE.search(m.group(1).strip())
        if hm:
            path = hm.group(1).split(".")
            # dotted calls rooted in a browser global (window.print,
            # event.stopPropagation, alert(...)) are never "dead"
            if path[0] not in _JS_GLOBALS:
                graph["handlers"].setdefault(
                    path[-1], []).append((rel, _line_of(body, m.start()),
                                          hm.group(1)))
    for m in _SCRIPT_SRC_RE.finditer(body):
        graph["local_refs"].append(
            (rel, _line_of(body, m.start()), m.group(1), "script", True))
    for m in _LINK_HREF_RE.finditer(body):
        graph["local_refs"].append(
            (rel, _line_of(body, m.start()), m.group(1), "link", True))
    for m in _IMG_SRC_RE.finditer(body):
        graph["local_refs"].append(
            (rel, _line_of(body, m.start()), m.group(1), "img", False))
    for m in _A_HREF_RE.finditer(body):
        v = m.group(1)
        if re.search(r"\.(html?|php)$", v, re.I):
            graph["local_refs"].append(
                (rel, _line_of(body, m.start()), v, "a", False))


def _ws_pool(ws, exts=_WIRING_EXTS, max_files=MAX_WIRING_WS_FILES):
    """(rel, body) for the EXISTING workspace files the wiring probe may
    need (references may target files the batch never touches).
    v8.12: os.walk with in-place pruning - sorted(rglob("*")) materialized
    and walked the ENTIRE tree (including .git/node_modules) before the
    first file was even tested; the cap bounded validation, not the walk.
    Ignored directories are now pruned DURING the walk and the capped
    result is sorted afterwards (deterministic across calls; when the
    cap bites, WHICH files are kept may differ from v8.11's
    sort-the-world order - the walk is the point, not the order)."""
    root = Path(ws)
    out = []
    if not root.is_dir():
        return out
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
            for fname in sorted(filenames):
                if len(out) >= max_files:
                    break
                p = Path(dirpath) / fname
                if p.suffix.lower() not in exts:
                    continue
                rel = p.relative_to(root).as_posix()
                try:
                    body = p.read_text(encoding="utf-8",
                                       errors="replace")[:MAX_WIRING_FILE_CHARS]
                except OSError:
                    continue
                if not _looks_binary(body) and not _is_minified(body):
                    out.append((rel, body))
            if len(out) >= max_files:
                break
        out.sort(key=lambda t: t[0])
    except Exception:
        pass
    return out


def _resolve_local(ws, ref, batch_names):
    """Is a local src/href target present? Checks the batch FIRST (it
    overwrites the disk), then the workspace when one is known. With
    ws=None only the batch counts (a pure in-memory check).
    Returns '' | a reason."""
    # v8.7: strip ONE leading './' - lstrip('./') used to eat CHARACTERS
    # from both ends of the set, so '../assets/x.js' became
    # 'assets/x.js' (a parent-relative reference resolved the wrong
    # direction and could warn on a file that does exist).
    ref = str(ref).strip()
    while ref.startswith("./"):
        ref = ref[2:]
    if not ref or ref.startswith(("/", "\\")):
        return ""
    if ws is not None and (Path(ws) / ref).is_file():
        return ""
    for name in batch_names:
        if name.replace("\\", "/").lower() == ref.lower():
            return ""
        if name.replace("\\", "/").lower().endswith("/" + ref.lower()):
            return ""
    return "referenced file is missing from the workspace"


def _py_local_import_missing(ws, rel, body, batch_names):
    """Python import checks. RELATIVE imports are unambiguous (a missing
    target is always a bug); absolute local imports only fire when a
    same-named sibling file exists (else it may be a pip package).
    ws may be None (batch-only resolution). Returns [(line, msg)]."""
    out = []
    try:
        import ast
        tree = ast.parse(body)
    except Exception:
        return out
    rel_posix = rel.replace("\\", "/")
    base_dir = rel_posix.rsplit("/", 1)[0] if "/" in rel_posix else ""
    batch_low = {n2.replace("\\", "/").lower() for n2 in batch_names}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            mod = (node.module or "").replace(".", "/")
            up = node.level - 1
            anchor = base_dir.split("/") if base_dir else []
            while up > 0 and anchor:
                anchor.pop()
                up -= 1
            cand_dir = "/".join(anchor)
            hit = False
            # v8.10.1 fix: the bare form `from . import utils` has NO
            # module - the old candidate list probed literally ".py" and
            # "__init__.py" and never tested the imported NAMES, so a
            # utils.py sitting right in the anchor directory was reported
            # as "module file not found" (blocking reject of a healthy
            # batch). Names now resolve against the anchor dir.
            import_names = [n.name for n in node.names]
            if mod:
                cands = [(cand_dir + "/" + mod) if cand_dir else mod,
                         (cand_dir + "/" + mod + "/__init__")
                         if cand_dir else mod + "/__init__"]
            elif cand_dir:
                cands = [cand_dir]     # the anchor package dir itself
            else:
                cands = []
            for cand in cands:
                cand = cand.lstrip("/")
                names = {cand + ".py", cand + ".pyw"}
                if ws is not None and any(
                        (ws / n).is_file() for n in names):
                    hit = True
                    break
                # v8.11: a namespace package (pkg/ WITHOUT __init__.py,
                # valid since Python 3.3) satisfies `from .pkg import x`
                # just as well - the file-only probe used to reject it
                if ws is not None and (ws / cand).is_dir():
                    hit = True
                    break
                if batch_low & {n.lower() for n in names}:
                    hit = True
                    break
            if not hit and not mod and cand_dir:
                # bare `from . import X`: X.py (or the anchor's
                # __init__) in the anchor dir satisfies the import
                cand = cand_dir.lstrip("/")
                if ws is not None and (
                        (ws / cand).is_dir()
                        or (ws / (cand + ".py")).is_file()
                        or (ws / cand / "__init__.py").is_file()):
                    hit = True
                elif batch_low & {(cand_dir + "/" + nm + ".py").lower()
                                  for nm in import_names} \
                        or batch_low & {nm.lower()
                                        for nm in import_names}:
                    hit = True
            if not hit and not mod and not cand_dir:
                # `from . import X` at the workspace root: X.py in the
                # batch / workspace satisfies it
                if batch_low & {nm.lower() + ".py"
                                for nm in import_names}:
                    hit = True
                elif ws is not None and any(
                        (ws / (nm + ".py")).is_file()
                        for nm in import_names):
                    hit = True
            if not hit:
                out.append((getattr(node, "lineno", 0) or 0,
                            "relative import 'from %s%s import ...' - "
                            "module file not found in the workspace"
                            % ("." * node.level, node.module or "")))
    return out


def _node_local_require_missing(ws, rel, body, batch_names):
    """node require("./x") / import "./x" - a missing relative target is
    always a bug. ws may be None (batch-only resolution).
    Returns [(line, msg)]."""
    import posixpath
    out = []
    rel_posix = rel.replace("\\", "/")
    base_dir = rel_posix.rsplit("/", 1)[0] if "/" in rel_posix else ""
    for m in _NODE_REL_REQUIRE_RE.finditer(body):
        target = m.group(1)
        cand = (base_dir + "/" + target) if base_dir else target
        cand = posixpath.normpath(cand.replace("\\", "/"))
        names = [cand + ".js", cand + ".mjs", cand + ".cjs", cand +
                 "/index.js", cand + ".json", cand]
        hit = (ws is not None and
               any((ws / n).is_file() for n in names))
        if not hit:
            for n2 in batch_names:
                low2 = n2.replace("\\", "/").lower()
                if low2 in [n.lower() for n in names] or \
                        low2 == cand.lower():
                    hit = True
                    break
        if not hit:
            out.append((_line_of(body, m.start()),
                        "require('%s') - module file not found in the "
                        "workspace" % target))
    return out


def wiring_check(bodies, ws=None, cfg=None):
    """THE WIRING PROBE. bodies: [(name, content)] - the batch (pre-
    apply) or the touched files (post-apply); ws widens the graph with
    the existing workspace files. Returns
    {"errors": [(file, line, msg)], "warns": [...], "via": {...}}.
    NEVER raises for content problems."""
    ws = Path(ws) if ws else None
    batch = {}
    for name, body in (bodies or []):
        if not name:
            continue
        rel = str(name).replace("\\", "/")
        body = str(body or "")
        if _looks_binary(body) or _is_minified(body):
            continue
        if len(body) > MAX_WIRING_FILE_CHARS:
            body = body[:MAX_WIRING_FILE_CHARS]
        batch[rel] = body
    pool = dict(batch)
    if ws is not None:
        for rel, body in _ws_pool(ws):
            pool.setdefault(rel, body)          # batch wins on conflict
    graph = {"ids": {}, "classes": {}, "js_fns": {}, "handlers": {},
             "el_refs": {}, "cls_refs": {}, "local_refs": []}
    batch_names = list(batch.keys())
    batch_name_set = set(batch_names)
    for rel, body in pool.items():
        low = rel.lower()
        if low.endswith(_WIRING_EXTS):
            _collect_defs(rel, body, graph)
            _collect_refs(rel, body, graph)
    errors, warns = [], []

    def add(kind, rel, line, msg):
        # v8.11 THE POISON FIX: a finding that lives in a PRE-EXISTING
        # workspace file the batch does not touch must never hard-reject
        # the batch - one old bug used to refuse EVERY future batch of
        # any kind, forever (the repair prompt even pointed at a file
        # the model had not written and could not see). Pre-existing
        # findings are demoted to warns; the batch stays judgeable on
        # its own content.
        if kind == "error" and ws is not None \
                and rel not in batch_name_set:
            kind = "warn"
        (errors if kind == "error" else warns).append((rel, line, msg))

    # ---- 1) dead element references (THE dead-button class) ---------
    for ident, sites in graph["el_refs"].items():
        if ident in graph["ids"]:
            continue
        for rel, line in sites[:6]:
            add("error", rel, line,
                "dead reference: #%s is looked up but never exists in "
                "any html/js of this project (a button/section wired to "
                "nothing)" % ident)
    # ---- 2) dead inline handlers ------------------------------------
    for fn, sites in graph["handlers"].items():
        if fn in graph["js_fns"] or fn in _JS_GLOBALS:
            continue
        if fn in graph["ids"] and len(fn) <= 2:
            continue                  # tiny ambiguous tokens stay quiet
        for rel, line, raw in sites[:6]:
            # v8.11: a remote <script src> ON THE PAGE that calls the
            # handler may define it there (offline we cannot know) -
            # advisory for that page instead of a hard reject. The
            # demotion is per-page: one CDN script in some pre-existing
            # file used to soften the gate for the WHOLE batch.
            remote_here = bool(_REMOTE_SCRIPT_RE.search(pool.get(rel, "")))
            add("warn" if remote_here else "error", rel, line,
                "dead handler: %s(...) is called from markup but never "
                "defined in any script" % raw)
    # ---- 3) dead classes (advisory - the button LOOKS dead) ---------
    for cls, sites in graph["cls_refs"].items():
        if cls in graph["classes"] or _STYLE_CLASS_HINT_RE.match(cls):
            continue
        for rel, line in sites[:3]:
            add("warn", rel, line,
                "class '%s' is toggled in js but no stylesheet or "
                "markup defines it (no visual effect?)" % cls)
    # ---- 4) local file references ------------------------------------
    # NOTE: a missing local <link rel=stylesheet> is BY DESIGN healed
    # right after the apply (the v7.0 design floor fills the referenced
    # stylesheet by name), and a missing <script src> on a static page
    # is a common "behavior comes later" pattern - both stay ADVISORY
    # (the post-apply sweep + the browser probe still report them, and
    # the fix round sees them). The hard rejections stay reserved for
    # the unambiguous dead wiring: ids / handlers / relative imports.
    for rel, line, ref, kind, must in graph["local_refs"]:
        low_ref = ref.lower()
        if re.match(r"^(https?:|data:|blob:|mailto:|javascript:|//)",
                    low_ref):
            continue
        # ws=None = batch-only resolution (a pure in-memory check)
        why = _resolve_local(ws, ref, batch_names)
        if not why:
            continue
        if kind == "script":
            add("warn", rel, line,
                "<script src=%s> - %s (the script silently loads "
                "nothing - every button it wires would be dead)"
                % (ref, why))
        elif kind == "link":
            add("warn", rel, line,
                "<link href=%s> - %s (the stylesheet silently loads "
                "nothing)" % (ref, why))
        elif kind == "img":
            add("warn", rel, line,
                "<img src=%s> - %s (broken image)" % (ref, why))
        else:
            add("warn", rel, line,
                "link to %s - %s (404 in the preview)" % (ref, why))
    # ---- 5) python / node module wiring ------------------------------
    for rel, body in batch.items():
        low = rel.lower()
        if low.endswith(".py"):
            for line, msg in _py_local_import_missing(ws, rel, body,
                                                      batch_names):
                add("error", rel, line, msg)
        elif low.endswith((".js", ".mjs")):
            for line, msg in _node_local_require_missing(ws, rel, body,
                                                         batch_names):
                add("error", rel, line, msg)
    cap = MAX_WIRING_FINDINGS
    return {"errors": errors[:cap], "warns": warns[:cap],
            "counts": {"ids": len(graph["ids"]),
                       "refs": sum(len(v) for v in
                                   graph["el_refs"].values()),
                       "handlers": sum(len(v) for v in
                                       graph["handlers"].values()),
                       "files": len(pool)}}


def wiring_repair_prompt(report):
    """The hunter's message back to the generator model: exact dead
    wiring, exact protocol, nothing written to disk yet."""
    errs = report.get("errors") or []
    if not errs:
        return ""
    lines = ["BUG HUNTER: the batch was refused - the wiring check "
             "found %d dead reference(s) - NOTHING was written to disk. "
             "Fix EXACTLY these problems (wire every id/handler/file "
             "that is referenced) and re-output the COMPLETE corrected "
             "file(s) with the === FILE: path === ... === END === "
             "protocol:" % len(errs)]
    for rel, line, msg in errs[:12]:
        lines.append("- %s: line %s: %s" % (rel, line or "?", msg))
    lines.append("")
    lines.append("Rules: output every fixed file in THIS one answer; "
                 "keep everything else identical; end with the Run:/"
                 "Preview: line.")
    return "\n".join(lines)


# =====================================================================
# 2. THE SMOKE PROBE - execute the entries, parse the crash
# =====================================================================
_SERVER_HINT_RE = re.compile(
    r"(app\.run\s*\(|uvicorn|http\.server|HTTPServer|socket\.socket|"
    r"\.listen\s*\(|createServer|FastAPI\s*\(|Flask\s*\(|express\s*\(|"
    r"webbrowser\.open|serve\s*\(|aiohttp|bottle)", re.IGNORECASE)
_INTERACTIVE_HINT_RE = re.compile(
    r"\binput\s*\(|readline\s*\(|input\[|prompt\s*\(", re.IGNORECASE)
_JS_ENTRY_BLOCK_RE = re.compile(r"\b(document\.|window\.|DOMContent|"
                                r"getElementById|querySelector)", )


def _read_entry(ws, name, cap=200_000):
    try:
        return (Path(ws) / name).read_text(
            encoding="utf-8", errors="replace")[:cap]
    except Exception:
        return ""


def _pick_entries(ws, applied):
    """Entry candidates from the applied batch: py with a __main__ block
    (never tests/conftest), plain js WITHOUT dom references (a browser
    script would crash under node for the wrong reason)."""
    py, js = [], []
    for name in (applied or [])[:12]:
        rel = str(name).replace("\\", "/")
        low = rel.lower()
        base = low.rsplit("/", 1)[-1]
        if low.endswith(".py"):
            if base.startswith(("test_", "conftest")) or \
                    "/tests/" in "/" + low or base == "setup.py":
                continue
            body = _read_entry(ws, rel)
            if "__main__" in body:
                py.append((rel, bool(_SERVER_HINT_RE.search(body)),
                           bool(_INTERACTIVE_HINT_RE.search(body))))
        elif low.endswith(".js"):
            body = _read_entry(ws, rel)
            if body and not _JS_ENTRY_BLOCK_RE.search(body):
                js.append((rel, bool(_SERVER_HINT_RE.search(body)),
                           False))
    out = py[:SMOKE_MAX_ENTRIES]
    if len(out) < SMOKE_MAX_ENTRIES:
        out += js[:SMOKE_MAX_ENTRIES - len(out)]
    return out


def _py_interpreter():
    """A REAL python for subprocess runs - never the frozen Nova exe
    itself (the v6.5 lesson: sys.executable under PyInstaller relaunches
    Nova, which then hangs on the pipe)."""
    if getattr(sys, "frozen", False):
        for name in ("python3", "python"):
            p = shutil.which(name)
            if p:
                return p
        return None
    return sys.executable


def _extract_runtime_error(out):
    """The LAST exception line of a traceback (the actual error)."""
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    for ln in reversed(lines[-10:]):
        ln = ln.strip()
        if re.match(r"^[A-Za-z_.]*(Error|Exception)\b", ln) and \
                not ln.startswith(("During handling", "The above")):
            return ln[:300]
        # traceback frames + the node.js version footer are not the error
        if ln.startswith(("at ", "node:", "Node.js v")):
            continue
    return (lines[-1][:300] if lines else "non-zero exit without output")


def smoke_one(ws, rel, server_like=False, interactive=False,
              timeout=None):
    """Run ONE entry script. Returns a finding dict:
    {"file", "level": pass|info|warn|error, "msg"} - NEVER raises."""
    low = rel.lower()
    if low.endswith(".py"):
        exe = _py_interpreter()
        if not exe:
            return {"file": rel, "level": "info",
                    "msg": "no python interpreter found - smoke run "
                           "skipped"}
        argv = [exe, rel]
    elif low.endswith(".js"):
        exe = shutil.which("node") or shutil.which("node.exe")
        if not exe:
            return {"file": rel, "level": "info",
                    "msg": "node not installed - smoke run skipped"}
        argv = [exe, rel]
    else:
        return {"file": rel, "level": "info",
                "msg": "no smoke runner for this file type"}
    # v8.11: float, not int - NOVA_PROBE_TIMEOUT=0.5 used to truncate to
    # 0 (an instant kill that made every smoke run look like a crash)
    secs = float(timeout or _env_float("NOVA_PROBE_TIMEOUT", 8.0))
    # v8.12: a caller-passed nan/inf must not disable the deadline
    if not math.isfinite(secs) or secs <= 0:
        secs = 8.0
    cwd = str(ws)
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # the run-sandbox the user configured (docker/podman/firejail/bwrap)
    # wraps the run when ON - zero network, capped memory, the works
    try:
        import nova_sandbox as sb
        sbcfg = sb.load_config(ws)
        if sbcfg.get("on"):
            eng, wrapped = sb.wrap(ws, argv, cfg=sbcfg, cwd=cwd)
            if eng:
                argv = wrapped
    except Exception:
        pass                       # sandbox is optional, never a gate
    try:
        p = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=secs,
                           encoding="utf-8", errors="replace", env=env)
        code, out = p.returncode, ((p.stdout or "") +
                                   (p.stderr or ""))[:SMOKE_OUTPUT_CAP]
        timed_out = False
    except subprocess.TimeoutExpired as e:
        code, timed_out = None, True
        out = ((e.stdout or b"") if isinstance(e.stdout, bytes)
               else (e.stdout or ""))
        out = str(out)[:SMOKE_OUTPUT_CAP]
    except OSError as e:
        return {"file": rel, "level": "warn",
                "msg": "cannot start the smoke run: %s" % str(e)[:120]}
    if timed_out:
        if server_like:
            return {"file": rel, "level": "pass",
                    "msg": "server started and kept running (no crash "
                           "within %ss)" % secs}
        return {"file": rel, "level": "warn",
                "msg": "did not finish within %ss - endless loop or a "
                       "slow start?" % secs}
    if code == 0:
        return {"file": rel, "level": "pass", "msg": ""}
    if "EOFError" in out:
        return {"file": rel, "level": "info",
                "msg": "interactive script (waits for input) - not a "
                       "crash"}
    # v8.7: a deliberate non-zero exit (sys.exit("usage: cli <file>"),
    # a missing-args guard, `exit 1`) is NOT a runtime crash - the old
    # classifier reported every non-zero exit as "runtime crash", so
    # the fix-loop kept "repairing" healthy CLI guards. Only an
    # exception-shaped line is a crash; everything else degrades to a
    # warn (and a detected input() entry point degrades to info - the
    # `interactive` flag used to be collected and never read).
    # The WHOLE captured output is scanned (8 KB cap): node v20+ prints
    # several internal frames + a version footer AFTER the headline, so
    # a 10-line tail window used to miss the ReferenceError line.
    crash = next((ln.strip() for ln in reversed(out.splitlines())
                  if re.match(r"^[A-Za-z_.]*(Error|Exception)\b",
                              ln.strip())
                  and not ln.strip().startswith(("During handling",
                                                 "The above"))),
                 None)
    if crash:
        return {"file": rel, "level": "error",
                "msg": "runtime crash: " + crash[:300]}
    if interactive:
        return {"file": rel, "level": "info",
                "msg": "interactive script (waits for input) - not a "
                       "crash"}
    detail = (out.strip().splitlines() or [""])[-1][:200]
    return {"file": rel, "level": "warn",
            "msg": "exited with code %s%s" % (code, (": " + detail)
                                              if detail else "")}


def smoke_check(ws, applied):
    """The smoke probe over the applied batch. Returns
    {"runs": [finding...], "ran": n} - never raises."""
    runs = []
    if os.environ.get("NOVA_PROBE_RUN", "") == "0":
        return {"runs": [], "ran": 0, "skipped": "NOVA_PROBE_RUN=0"}
    try:
        entries = _pick_entries(ws, applied)
    except Exception:
        entries = []
    for rel, server_like, interactive in entries:
        try:
            runs.append(smoke_one(ws, rel, server_like, interactive))
        except Exception as e:
            runs.append({"file": rel, "level": "warn",
                         "msg": "smoke probe error: %s" % str(e)[:120]})
    return {"runs": runs, "ran": len(runs)}


# =====================================================================
# 3. THE BROWSER PROBE - console truth (Playwright when present)
# =====================================================================
# A page can be perfectly balanced html and still scream in the console:
# "Uncaught ReferenceError: openModal is not defined", a 404 stylesheet,
# a crash the moment a button is clicked. When Playwright + Chromium are
# installed, the hunter LOADS the applied page in a headless browser
# (file:// - fully offline), captures console errors / page errors /
# failed resource loads, then CLICKS up to 8 visible buttons - a crash
# on click is a dead feature, caught. No Playwright = an honest skip;
# the wiring probe stays the offline floor either way.
_PLAYWRIGHT_STATE = {"checked": False, "ok": False}


def playwright_available():
    """Is the headless browser probe possible on THIS machine? (cached -
    but the kill-switch never poisons the cache: flipping NOVA_PROBE_
    BROWSER back on re-checks honestly)"""
    if os.environ.get("NOVA_PROBE_BROWSER", "") == "0":
        return False
    if _PLAYWRIGHT_STATE["checked"]:
        return _PLAYWRIGHT_STATE["ok"]
    ok = False
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        ok = True
    except Exception:
        ok = False
    _PLAYWRIGHT_STATE["checked"] = True
    _PLAYWRIGHT_STATE["ok"] = ok
    return ok


def browser_check(ws, applied, budget=None):
    """The headless-browser probe. Returns
    {"ran": bool, "skipped": str, "page": str,
     "errors": [(file, line, msg)], "warns": [...], "clicks": n}.
    Hard wall-clock budget, NEVER raises, zero network (file://)."""
    out = {"ran": False, "skipped": "", "page": "", "errors": [],
           "warns": [], "clicks": 0}
    if os.environ.get("NOVA_PROBE_BROWSER", "") == "0":
        out["skipped"] = "NOVA_PROBE_BROWSER=0"
        return out
    page_name = next((n for n in (applied or [])
                      if str(n).lower().endswith((".html", ".htm"))), None)
    if not page_name:
        out["skipped"] = "no html file in the batch"
        return out
    if not playwright_available():
        out["skipped"] = ("playwright/chromium not installed (the wiring "
                          "probe still ran - offline floor)")
        return out
    out["page"] = str(page_name)
    budget = float(budget or _env_float("NOVA_PROBE_BROWSER_TIMEOUT",
                                        BROWSER_BUDGET_S))
    # v8.12: a nan/inf budget must not poison the deadline arithmetic
    # (int(inf * 1000) raised inside the browser probe)
    if not math.isfinite(budget) or budget <= 0:
        budget = BROWSER_BUDGET_S
    deadline = time.time() + budget
    url = "file:///" + str(Path(ws) / str(page_name)).replace("\\", "/") \
        .lstrip("/")
    console, pageerrs, reqfail = [], [], []

    def on_console(m):
        try:
            if str(getattr(m, "type", "")) == "error":
                console.append(str(getattr(m, "text", ""))[:240])
        except Exception:
            pass

    def on_pageerror(e):
        pageerrs.append(str(e)[:240])

    def on_reqfail(r):
        try:
            fail = getattr(r, "failure", None)
            u = str(getattr(r, "url", ""))[-120:]
            if fail or u.startswith("file:"):
                if "/favicon" not in u:
                    reqfail.append(u)
        except Exception:
            pass

    pw = None
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("requestfailed", on_reqfail)
        page.goto(url, timeout=min(8_000, int(budget * 1000)),
                  wait_until="domcontentloaded")
        page.wait_for_timeout(700)
        out["ran"] = True
        # ---- the dead-button hunt: click what is visible ------------
        try:
            loc = page.locator("button, [onclick], input[type=button], "
                               "input[type=submit]")
            n = min(loc.count(), BROWSER_MAX_CLICKS)
            before = len(pageerrs) + len(console)
            for i in range(n):
                if time.time() > deadline:
                    break
                try:
                    el = loc.nth(i)
                    if el.is_visible(timeout=200):
                        el.click(timeout=800)
                        page.wait_for_timeout(120)
                except Exception:
                    continue          # hidden / detached / navigated
            out["clicks"] = n
            _ = before
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
    except Exception as e:
        if not out["ran"]:
            out["skipped"] = ("browser probe failed: %s"
                              % str(e)[:120])
    finally:
        try:
            if pw is not None:
                pw.stop()
        except Exception:
            pass
    seen = set()
    for msg in (pageerrs + console)[:BROWSER_MAX_ERRORS * 2]:
        key = msg[:120]
        if key in seen:
            continue
        seen.add(key)
        out["errors"].append((str(page_name), 0,
                              "browser: " + (msg or "console error")))
        if len(out["errors"]) >= BROWSER_MAX_ERRORS:
            break
    for u in reqfail[:4]:
        out["warns"].append((str(page_name), 0,
                             "browser: failed to load: %s" % u))
    return out


# =====================================================================
# 4. THE COMPLETENESS PROBE - "a part of the work fell off"
# =====================================================================
# The wiring probe proves every reference lands somewhere; it cannot
# prove the work implements EVERYTHING the user asked for. The
# completeness supervisor sends the request + a WIRING SKELETON of each
# delivered file (ids, buttons, handlers, functions - facts, not vibes)
# to the LOCAL brain and asks: what did the user ask for that is
# missing or has no behavior? Advisory only, local brain only, and the
# deterministic skeleton is built so a no-internet, no-cloud answer is
# still grounded in the real file contents.
def parse_agent_json(text):
    """Tolerant JSON-object extraction from a model answer (the same
    bracket-budget philosophy as nova_guardian.parse_agent_json)."""
    if not text:
        return None
    text = text[:20000]
    # v8.11: a bounded attempt budget - a derailed model answer that is
    # one giant run of '{' used to scan 8000 chars PER BRACE (~10 s of a
    # frozen apply path). nova_subagent got the same cap (MAX_SPLIT_ATTEMPTS).
    attempts = 0
    for m in re.finditer(r"\{", text):
        attempts += 1
        if attempts > 200:
            break
        depth, start = 0, m.start()
        in_str = False
        esc = False
        for j in range(start, min(len(text), start + 8000)):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:j + 1])
                    except (ValueError, TypeError):
                        break
    return None


def _py_skeleton(body):
    """Top-level defs/classes of a python file (ast, fail-soft)."""
    try:
        import ast
        tree = ast.parse(body)
        names = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.append(node.name)
        return names[:40]
    except Exception:
        return []


def _js_skeleton(body):
    names = []
    for rx in _JS_FN_DEF_RES:
        for m in rx.finditer(body):
            if m.group(1) not in names:
                names.append(m.group(1))
    return names[:40]


def _html_skeleton(body):
    ids, btns, handlers, headings = [], 0, [], []
    for m in _HTML_ID_RE.finditer(body):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    btns = len(re.findall(r"<button\b", body, re.I)) + \
        len(re.findall(r"<input\b[^>]*type=[\"'](?:button|submit)", body,
                       re.I))
    for m in _HANDLER_ATTR_RE.finditer(body):
        hm = _HANDLER_FN_RE.search(m.group(1).strip())
        if hm and hm.group(1) not in handlers:
            handlers.append(hm.group(1))
    for m in re.finditer(r"<h[1-3][^>]*>([^<]{2,60})</h[1-3]>", body, re.I):
        headings.append(m.group(1).strip()[:40])
    return {"ids": ids[:24], "buttons": btns, "handlers": handlers[:12],
            "headings": headings[:8]}


def skeleton_of(ws, name, body=""):
    """The wiring skeleton ONE file shows the completeness supervisor."""
    rel = str(name).replace("\\", "/")
    low = rel.lower()
    if not body:
        body = _read_entry(ws, rel, cap=120_000)
    if low.endswith((".html", ".htm")):
        sk = _html_skeleton(body)
        return ("html: %d button(s), ids [%s], handlers [%s], sections %s"
                % (sk["buttons"], ", ".join(sk["ids"][:12]) or "-",
                   ", ".join(sk["handlers"][:8]) or "-",
                   " | ".join(sk["headings"][:4]) or "-"))
    if low.endswith((".js", ".mjs")):
        return "js functions: %s" % (", ".join(_js_skeleton(body)) or "-")
    if low.endswith(".py"):
        return "python defs: %s" % (", ".join(_py_skeleton(body)) or "-")
    return "text: %d lines" % max(1, body.count("\n"))


def review_completeness(request, ws, applied, chat_fn):
    """The supervisor's ONE local-model question: is anything the user
    asked for missing or unwired? Returns
    {"model_used": bool, "complete": bool|None,
     "gaps": [(file, what)]} - NEVER raises."""
    out = {"model_used": False, "complete": None, "gaps": []}
    if chat_fn is None or not str(request or "").strip() or not applied:
        return out
    files = [str(n) for n in (applied or [])[:REVIEW_MAX_FILES]]
    parts = []
    for rel in files:
        try:
            parts.append("- %s -> %s" % (rel, skeleton_of(ws, rel)))
        except Exception:
            parts.append("- %s -> (unreadable)" % rel)
    prompt = (
        "You are the completeness supervisor of Nova's bug hunter "
        "fleet. The model just DELIVERED files for this user request. "
        "Check whether the delivery covers EVERY feature the user "
        "asked for: a button the user wanted that is absent, a section "
        "of the work that fell off, a command/field/mode that was "
        "promised but has no code.\n\n"
        "USER REQUEST:\n%s\n\n"
        "DELIVERED FILES (wiring skeletons - real ids/buttons/functions "
        "extracted from the files):\n%s\n\n"
        "Answer ONLY compact JSON, no markdown:\n"
        '{"complete": true|false, "gaps": [{"what": "<short>", '
        '"where": "<file or ->"}]}\n'
        "Max %d gaps. Only REAL missing work the user explicitly asked "
        "for - never style opinions, never extra ideas. If everything "
        'asked for exists: {"complete": true, "gaps": []}'
        % (str(request)[:REVIEW_REQUEST_CHARS], "\n".join(parts),
           MAX_GAPS))
    try:
        ans = chat_fn(prompt)
    except Exception:
        return out
    data = parse_agent_json(ans or "")
    if not isinstance(data, dict):
        return out
    out["model_used"] = True
    out["complete"] = bool(data.get("complete"))
    gaps = data.get("gaps")
    if isinstance(gaps, list):
        for g in gaps[:MAX_GAPS]:
            if not isinstance(g, dict):
                continue
            what = str(g.get("what") or "").strip()[:220]
            if not what:
                continue
            where = str(g.get("where") or "-").strip()[:120] or "-"
            out["gaps"].append((where, what))
    return out


# =====================================================================
# 6. THE DEEP SWEEP (v8.6) - "ANYTHING can be a bug"
# =====================================================================
# The wiring probe proves every REFERENCE lands somewhere. The deep
# sweep proves the CODE ITSELF is whole: the missing function, the
# extra never-used definition, the impossible call signature, the stub
# body, the duplicated id, the button nobody listens to. Deterministic,
# offline, zero-model; gate errors stay reserved for the unambiguous
# families and every heuristic family stays advisory (warn).
MAX_DEEP_FINDINGS = 30           # errors cap per report
MAX_UNUSED_REPORTED = 4          # extra-code findings per report
MAX_TODO_REPORTED = 3            # TODO/FIXME findings per report
MAX_STUB_REPORTED = 5            # stub-body findings per report
MAX_DEAD_BUTTONS = 3             # listener-less type=button findings

_DEEP_EXTS = _WIRING_EXTS + (".py",)

# code lines that never carry a real TODO (strings shown to users,
# urls, license headers) stay quiet: only TODO/FIXME tokens matter
_TODO_RE = re.compile(r"\b(TODO|FIXME)\b[::]? *(.{0,80})")

_PY_STUB_PASS = ("pass", "...")
_NOT_IMPL_RE = re.compile(r"^\s*raise\s+NotImplementedError\b")
_JS_EMPTY_FN_RE = re.compile(
    r"(?<![\w$.])(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    r"\s*\([^)]*\)\s*\{\s*(?:/\*[\s\S]*?\*/|//[^\n]*)?\s*\}")
_JS_SILENT_CATCH_RE = re.compile(
    r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}")
_JS_FN_DECL_RE = _JS_FN_DEF_RES[0]     # hoisted declarations (same scope)


def _py_facts(tree):
    """The name universe of ONE python file: everything that could
    possibly be bound (imports, defs, params, assignments, for/with/
    except targets, comprehensions, walrus, globals). Returns a dict
    with the module-level functions, the per-class method tables, the
    full bound-name set and the star-import flag."""
    fns, classes, bound = {}, {}, set()
    star = False
    for node in ast_walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda)):
            if not isinstance(node, ast.Lambda):
                bound.add(node.name)
            a = node.args                      # parameters ARE bindings
            for arg in (list(getattr(a, "posonlyargs", []) or []) +
                        list(a.args or []) +
                        list(a.kwonlyargs or []) +
                        [x for x in (a.vararg, a.kwarg) if x]):
                bound.add(arg.arg)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
            meths = {}
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef,
                                    ast.AsyncFunctionDef)):
                    meths[sub.name] = sub
            classes[node.name] = meths
        elif isinstance(node, ast.Import):
            for a in node.names:
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            names = [a for a in (node.names or [])]
            if any(a.name == "*" for a in names):
                star = True
            for a in names:
                if a.name != "*":
                    bound.add(a.asname or a.name)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(
                node.ctx, (ast.Store,)):
            bound.add(node.id)
        elif isinstance(node, ast.Global) or isinstance(node,
                                                        ast.Nonlocal):
            bound.update(node.names)
        elif _MATCH_BIND_NODES and isinstance(node, _MATCH_BIND_NODES):
            # v8.7: `case {"op": op}:` / `case [first]:` / `case [*, rest]`
            # bind names OUTSIDE ast.Name(Store) - they used to be
            # reported as guaranteed NameError on perfectly valid code.
            nm = getattr(node, "name", None)
            if nm:
                bound.add(nm)
        elif getattr(ast, "MatchMapping", None) is not None \
                and isinstance(node, ast.MatchMapping):
            if getattr(node, "rest", None):
                bound.add(node.rest)
    # module-level functions for the signature math
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns[node.name] = node
    return {"fns": fns, "classes": classes, "bound": bound,
            "star": star}


def ast_walk(node):                    # thin alias, test-seamable
    import ast as _ast
    return _ast.walk(node)


def _annotation_names(tree):
    """Names that appear ONLY in annotation positions (parameter and
    return annotations, AnnAssign). With `from __future__ import
    annotations` these never evaluate at runtime - flagging them would
    be a false NameError, so the undefined check excludes them."""
    out = set()

    def _names_in(node):
        if node is None:
            return
        for n in ast_walk(node):
            if isinstance(n, ast.Name):
                out.add(n.id)

    for n in ast_walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            for arg in (list(getattr(a, "posonlyargs", []) or []) +
                        list(a.args or []) +
                        list(a.kwonlyargs or []) +
                        [x for x in (a.vararg, a.kwarg) if x]):
                _names_in(getattr(arg, "annotation", None))
            _names_in(getattr(n, "returns", None))
        elif isinstance(n, ast.AnnAssign):
            _names_in(n.annotation)
    return out


def _py_undefined(tree, facts):
    """Load-context names that are bound NOWHERE in the file and are no
    builtin -> a guaranteed NameError when the line runs. Files with a
    star import are skipped (a * import binds anything); names used in
    annotation positions are excluded (PEP 563 never evaluates them)."""
    if facts["star"]:
        return []
    try:
        import builtins
        bi = set(dir(builtins))
    except Exception:
        bi = set()
    bi.update(("__name__", "__file__", "__doc__", "__package__",
               "__spec__", "__loader__", "__builtins__", "__debug__",
               "__annotations__", "__cached__", "__all__", "self",
               "cls", "__class__", "__dict__", "__module__",
               "__qualname__"))
    bound = facts["bound"] | bi | _annotation_names(tree)
    out = []
    seen = set()
    for node in ast_walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx,
                                                     ast.Load):
            if node.id in bound or node.id in seen:
                continue
            seen.add(node.id)
            out.append((getattr(node, "lineno", 0) or 0, node.id,
                        "call to '%s' but it is defined nowhere in "
                        "this file (NameError when this line runs)"
                        % node.id))
    return out


def _fn_signature(node):
    """(pos_params, defaulted_pos_names, kwonly_names,
    kwonly_defaulted, has_vararg, has_kwarg) of one FunctionDef."""
    a = node.args
    pos = [x.arg for x in (getattr(a, "posonlyargs", []) or [])] + \
        [x.arg for x in (a.args or [])]
    defaulted = set()
    defaults = list(a.defaults or [])
    if defaults:
        for name in pos[len(pos) - len(defaults):]:
            defaulted.add(name)
    kwonly = [x.arg for x in (a.kwonlyargs or [])]
    kw_def = set()
    kd = list(a.kw_defaults or [])
    for i, x in enumerate(a.kwonlyargs or []):
        if i < len(kd) and kd[i] is not None:
            kw_def.add(x.arg)
    return (pos, defaulted, kwonly, kw_def,
            a.vararg is not None, a.kwarg is not None)


def _py_call_issues(tree, facts):
    """Same-file signature math: a call that passes too many positional
    args, an unknown keyword, or misses a required argument against a
    SAME-FILE def is a guaranteed TypeError. Star-args/star-kw calls
    are skipped (unknown), cross-file calls are unknown (skipped)."""
    out = []
    fns = facts["fns"]
    classes = facts["classes"]

    def _check(call, sig, skip_first, where, line):
        pos, defaulted, kwonly, kw_def, has_var, has_kw = sig
        if skip_first and pos:
            pos = pos[1:]          # 'self'/'cls' is bound by the call
        args = list(call.args or [])
        if any(isinstance(x, ast.Starred) for x in args):
            return
        kws = [k for k in (call.keywords or []) if k.arg is not None]
        if len(kws) != len(call.keywords or []):
            return                       # a **kwargs splash - unknowable
        kw_names = [k.arg for k in kws]
        all_params = set(pos) | set(kwonly)
        # too many positional arguments?
        if not has_var and len(args) > len(pos):
            out.append((line, "call %s passes %d positional argument(s) "
                        "but %s accepts at most %d (TypeError)"
                        % (where, len(args), where, len(pos))))
            return
        # unknown keyword argument?
        if not has_kw:
            for kn in kw_names:
                if kn not in all_params:
                    out.append((line, "call %s passes unknown keyword "
                                "'%s' (TypeError)" % (where, kn)))
                    return
        # missing required arguments?
        req = [p for p in pos if p not in defaulted]
        covered = set()
        for i, p in enumerate(pos):
            if i < len(args):
                covered.add(p)
        covered.update(kn for kn in kw_names if kn in pos)
        missing = [p for p in req if p not in covered]
        if missing and not has_var:
            out.append((line, "call %s is missing required argument "
                        "'%s' (TypeError)" % (where, missing[0])))

    def _visit(node, cls=None):
        for child in ast_iter_child(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                nxt = cls
                if isinstance(child, ast.ClassDef):
                    nxt = child.name
                elif cls and isinstance(child, (ast.FunctionDef,
                                                ast.AsyncFunctionDef)):
                    pass
                _visit(child, nxt)
                continue
            if isinstance(child, ast.Call):
                f = child.func
                line = getattr(child, "lineno", 0) or 0
                if isinstance(f, ast.Name) and f.id in fns:
                    _check(child, _fn_signature(fns[f.id]), False,
                           f.id, line)
                elif isinstance(f, ast.Attribute) and cls and \
                        isinstance(f.value, ast.Name) and \
                        f.value.id in ("self", "cls") and \
                        f.attr in classes.get(cls, {}):
                    _fn_node = classes[cls][f.attr]
                    # v8.11: a @staticmethod has no self/cls - the old
                    # unconditional first-param strip truncated the real
                    # signature and flagged healthy calls as TypeError
                    _is_static = any(
                        (isinstance(d, ast.Name) and d.id == "staticmethod")
                        or (isinstance(d, ast.Attribute)
                            and d.attr == "staticmethod")
                        for d in (getattr(_fn_node, "decorator_list", None)
                                  or []))
                    _check(child, _fn_signature(_fn_node),
                           not _is_static,
                           "%s.%s" % (f.value.id, f.attr), line)
                _visit(child, cls)
                continue
            _visit(child, cls)

    _visit(tree)
    return out


def ast_iter_child(node):
    """ast.iter_child_nodes is a MODULE function, not a node method -
    the hasattr trick always returned False and silenced the visitor."""
    return list(ast.iter_child_nodes(node))


def _py_dup_defs(tree):
    """The same def/class name twice in ONE scope: the first body is
    dead code (Python silently keeps the last)."""
    out = []

    def _scan(stmts, scope):
        seen = {}
        for n in stmts:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
                if n.name in seen:
                    out.append((getattr(n, "lineno", 0) or 0,
                                "%s is defined twice in the same scope "
                                "(%s) - the first body is dead code"
                                % (n.name, scope)))
                seen[n.name] = True

    _scan(getattr(tree, "body", []), "module")
    for n in ast_walk(tree):
        if isinstance(n, ast.ClassDef):
            _scan(n.body, "class " + n.name)
    return out


def _py_unreachable(tree):
    """Code after return/raise/break/continue inside one block."""
    out = []
    _TERMINAL = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    _SCOPED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For,
               ast.While, ast.With, ast.AsyncWith, ast.Try,
               ast.ExceptHandler, ast.Match)

    def _scan_list(stmts, where):
        hit = False
        for n in (stmts or []):
            if hit:
                out.append((getattr(n, "lineno", 0) or 0,
                            "unreachable code after %s - it can never "
                            "run" % where))
                return
            if isinstance(n, _TERMINAL):
                hit = True

    for n in ast_walk(tree):
        if isinstance(n, _SCOPED):
            _scan_list(getattr(n, "body", None), type(n).__name__)
            if getattr(n, "orelse", None):
                _scan_list(n.orelse, type(n).__name__ + "-else")
    return out[:4]


def _py_mutable_defaults(tree):
    """def f(x=[], d={}): - the classic shared-state bug."""
    out = []
    for node in ast_walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            pos = [x.arg for x in (getattr(a, "posonlyargs", []) or [])] \
                + [x.arg for x in (a.args or [])]
            defaults = list(a.defaults or [])
            if defaults:
                tail = pos[len(pos) - len(defaults):]
                for name, dv in zip(tail, defaults):
                    if isinstance(dv, (ast.List, ast.Dict, ast.Set)):
                        out.append((getattr(node, "lineno", 0) or 0,
                                    "mutable default argument '%s' in "
                                    "def %s() - shared across calls"
                                    % (name, node.name)))
    return out


def _py_stubs(tree):
    """Functions whose whole body is pass / ... / NotImplementedError -
    a promised feature with no implementation."""
    out = []
    for node in ast_walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = [s for s in (node.body or [])
                if not (isinstance(s, ast.Expr)
                        and isinstance(getattr(s, "value", None),
                                       ast.Constant)
                        and isinstance(s.value.value, str))]
        if not body:
            continue
        if all(isinstance(s, ast.Pass) for s in body) or \
                all(isinstance(s, ast.Expr) and
                    isinstance(getattr(s, "value", None), ast.Constant)
                    and s.value.value is Ellipsis for s in body):
            out.append((getattr(node, "lineno", 0) or 0, node.name,
                        "stub body"))
        elif len(body) == 1 and isinstance(body[0], ast.Raise) and \
                _NOT_IMPL_RE.match(
                    ast_unparse(body[0]) or "raise NotImplementedError"):
            out.append((getattr(node, "lineno", 0) or 0, node.name,
                        "NotImplementedError only"))
    return out


def ast_unparse(node):
    try:
        import ast as _ast
        return _ast.unparse(node)
    except Exception:
        return ""


def _py_bare_except(tree):
    """`except: pass` swallows EVERY failure - a bug factory."""
    out = []
    for node in ast_walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            body = [s for s in (node.body or [])
                    if not (isinstance(s, ast.Expr)
                            and isinstance(getattr(s, "value", None),
                                           ast.Constant)
                            and isinstance(s.value.value, str))]
            if body and all(isinstance(s, ast.Pass) for s in body):
                out.append((getattr(node, "lineno", 0) or 0,
                            "bare 'except: pass' swallows every error "
                            "- at least catch Exception and log it"))
    return out


def _js_dup_fns(body):
    """The same hoisted `function name(...)` declared twice in one js
    file: the FIRST silently loses (a wrong-behavior + extra-code bug).
    Returns [(line, name)]."""
    seen = {}
    out = []
    for m in _JS_FN_DECL_RE.finditer(body):
        name = m.group(1)
        if name in seen:
            out.append((_line_of(body, m.start()), name))
        else:
            seen[name] = True
    return out


def _js_stubs_and_catches(body):
    out = []
    for m in _JS_EMPTY_FN_RE.finditer(body):
        out.append((_line_of(body, m.start()), m.group(1),
                    "empty implementation"))
    for m in _JS_SILENT_CATCH_RE.finditer(body):
        out.append((_line_of(body, m.start()), "-",
                    "silent empty catch{} swallows the error"))
    return out


def _html_dup_ids(body):
    """The same id twice in ONE page: #sel returns only the FIRST
    element - the second is unreachable (a dead section)."""
    counts = {}
    for m in _HTML_ID_RE.finditer(body):
        counts.setdefault(m.group(1), []).append(
            _line_of(body, m.start()))
    for m in _HTML_ID_BARE_RE.finditer(body):
        counts.setdefault(m.group(1), []).append(
            _line_of(body, m.start()))
    return [(lines[1], name) for name, lines in counts.items()
            if len(lines) > 1]


def _html_dead_buttons(body, js_text):
    """An explicit type="button" with an id, no inline onclick, and an
    id no script ever mentions (and no event delegation anywhere) is a
    button wired to NOTHING - the exact 'this button does nothing'
    class. Returns [(line, id)]."""
    if "closest(" in js_text or "delegat" in js_text.lower():
        return []
    out = []
    for m in re.finditer(r"<button\b[^>]*>\s*</button>|<button\b[^>]*>",
                         body, re.I):
        tag = m.group(0)
        if 'type="button"' not in tag.lower() and \
                "type='button'" not in tag.lower():
            continue
        if re.search(r"\bonclick\s*=", tag, re.I):
            continue
        idm = re.search(r"""\bid\s*=\s*["']([A-Za-z][\w:.-]*)["']""",
                        tag, re.I)
        if not idm:
            continue
        ident = idm.group(1)
        if ident in js_text:
            continue
        out.append((_line_of(body, m.start()), ident))
    return out


def _html_script_bodies(body):
    """Inline <script>...</script> bodies (no src=) of one html file."""
    return [m.group(1) for m in re.finditer(
        r"<script(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)</script>", body,
        re.I)]


def _page_handler_gaps(rel, body, pool, ws):
    """Inline handlers of page REL must be defined by the scripts THAT
    PAGE loads: its own inline <script> blocks, or a local <script src>
    resolvable from the page's directory. A handler defined only in a
    file the page never loads is DEAD IN THIS PAGE (ReferenceError on
    click) even though the wiring probe sees the definition elsewhere.
    Conservative: any remote/unresolvable script makes the page skip
    (a CDN script could define anything). Returns [(line, fn, srcs)]."""
    low = rel.lower()
    if not low.endswith((".html", ".htm")):
        return []
    # resolve the page's scripts
    rel_posix = rel.replace("\\", "/")
    base_dir = rel_posix.rsplit("/", 1)[0] if "/" in rel_posix else ""
    defined = set(_JS_GLOBALS)
    inline = "".join(_html_script_bodies(body))
    for rx in _JS_FN_DEF_RES:
        for m in rx.finditer(inline):
            defined.add(m.group(1))
    for m in _SCRIPT_SRC_RE.finditer(body):
        src = m.group(1).strip()
        low_src = src.lower()
        if re.match(r"^(https?:|//|data:|blob:)", low_src):
            return []            # remote script - could define anything
        cands = _script_candidates(base_dir, src)
        hit_body = None
        for cand in cands:
            if cand in pool:
                hit_body = pool[cand]
                break
            if ws is not None and (Path(ws) / cand).is_file():
                hit_body = _read_entry(ws, cand, cap=MAX_WIRING_FILE_CHARS)
                break
        if hit_body is None:
            return []            # unresolvable - the wiring probe already warns
        for rx in _JS_FN_DEF_RES:
            for mm in rx.finditer(hit_body):
                defined.add(mm.group(1))
    out = []
    for m in _HANDLER_ATTR_RE.finditer(body):
        hm = _HANDLER_FN_RE.search(m.group(1).strip())
        if not hm:
            continue
        path = hm.group(1).split(".")
        fn = path[-1]
        if path[0] in _JS_GLOBALS or fn in defined:
            continue
        if fn in out_names(out):
            continue
        out.append((_line_of(body, m.start()), fn,
                    "%s(...) is called from this page's markup but no "
                    "script this page loads defines it (dead in THIS "
                    "page)" % hm.group(1)))
    return out


def out_names(out):
    return {x[1] for x in out}


def _script_candidates(base_dir, src):
    """The pool-relative candidates one src= could resolve to."""
    # v8.10.1 fix: lstrip("./") ate CHARACTERS, not the prefix - the exact
    # bug class the v8.7 _resolve_local fix documents ('../x' lost its hop
    # AND a leading dot of a real name). Strip ONE leading './'; a parent
    # hop then resolves exactly via normpath below.
    src = str(src).strip()
    if src.startswith("./"):
        src = src[2:]
    cands = []
    if src.startswith("/"):
        cands.append(src.lstrip("/"))
    else:
        cands.append((base_dir + "/" + src) if base_dir else src)
        cands.append(src)            # root-relative fallback
    import posixpath
    return [posixpath.normpath(x.replace("\\", "/")) for x in cands]


def _unused_fns(pool_bodies, py_facts_by_file, js_fns_by_file):
    """EXTRA code: top-level functions never referenced ANYWHERE in the
    pool (def site only). Heuristic on purpose -> advisory. Skips short
    names (<4 chars, too noisy) and anything mentioned even once."""
    whole = "\n".join(b for _r, b in pool_bodies)
    out = []
    for rel, names in py_facts_by_file:
        for name, line in names:
            if len(name) < 4 or name.startswith("__"):
                continue
            if whole.count(name) <= 1:
                out.append((rel, line, name,
                            "function '%s' is defined but never used "
                            "anywhere in the project (extra code)"
                            % name))
    for rel, names in js_fns_by_file:
        for name, line in names:
            if len(name) < 4 or name.startswith("_"):
                continue
            if whole.count(name) <= 1:
                out.append((rel, line, name,
                            "function '%s' is defined but never used "
                            "anywhere in the project (extra code)"
                            % name))
    return out


def _todos(body):
    return [(_line_of(body, m.start()), m.group(1),
             "unresolved %s promise: %s" % (m.group(1),
                                            (m.group(2) or "").strip()
                                            [:60] or "-"))
            for m in _TODO_RE.finditer(body)]


def static_check(bodies, ws=None, cfg=None):
    """THE DEEP SWEEP. bodies: [(name, content)] - the batch (pre-apply)
    or the touched files (post-apply); ws widens the pool with the
    existing workspace files (batch wins). Returns
    {"errors": [(file, line, msg)], "warns": [(file, line, msg)],
     "counts": {...}} - NEVER raises for content problems."""
    ws = Path(ws) if ws else None
    batch = {}
    for name, body in (bodies or []):
        if not name:
            continue
        rel = str(name).replace("\\", "/")
        body = str(body or "")
        if _looks_binary(body) or _is_minified(body):
            continue
        if len(body) > MAX_WIRING_FILE_CHARS:
            body = body[:MAX_WIRING_FILE_CHARS]
        batch[rel] = body
    pool = dict(batch)
    if ws is not None:
        for rel, body in _ws_pool(ws, exts=_DEEP_EXTS):
            pool.setdefault(rel, body)       # batch wins on conflict
    errors, warns = [], []

    def add(kind, rel, line, msg):
        if kind == "error" and len(errors) < MAX_DEEP_FINDINGS:
            errors.append((rel, line, msg))
        elif kind == "warn":
            warns.append((rel, line, msg))

    fams = {"py_undefined": 0, "py_call": 0, "dup_def": 0, "stub": 0,
            "unreachable": 0, "mutable": 0, "bare_except": 0,
            "js_dup": 0, "dup_id": 0, "dead_button": 0,
            "page_handler": 0, "unused": 0, "todo": 0}
    py_facts_by_file, js_fns_by_file = [], []
    js_text_all = "\n".join(b for r, b in pool.items()
                            if r.lower().endswith((".js", ".mjs")))
    # v8.7: INLINE <script> bodies count as listening scripts too - a
    # single-file page wiring its own buttons used to produce a false
    # "wired to nothing" warn for every explicitly-javascript button.
    js_text_all += "\n" + "\n".join(
        "".join(_html_script_bodies(b)) for b in pool.values()
        if "<script" in (b or "").lower())
    for rel, body in batch.items():
        low = rel.lower()
        if low.endswith(".py"):
            try:
                import ast as _ast
                tree = _ast.parse(body)
            except Exception:
                continue                      # syntax gate owns this
            facts = _py_facts(tree)
            py_facts_by_file.append((rel, [
                (n.name, getattr(n, "lineno", 0) or 0)
                for n in _top_level_fns(tree)]))
            for line, name, msg in _py_undefined(tree, facts):
                add("error", rel, line, msg)
                fams["py_undefined"] += 1
            for line, msg in _py_call_issues(tree, facts):
                add("error", rel, line, msg)
                fams["py_call"] += 1
            for line, msg in _py_dup_defs(tree):
                add("error", rel, line, msg)
                fams["dup_def"] += 1
            stubs = _py_stubs(tree)
            for line, name, _kind in stubs[:MAX_STUB_REPORTED]:
                add("warn", rel, line,
                    "stub body: %s() has no real implementation "
                    "(%s) - a promised feature is missing" % (name,
                                                              _kind))
                fams["stub"] += 1
            for line, msg in _py_unreachable(tree)[:4]:
                add("warn", rel, line, msg)
                fams["unreachable"] += 1
            for line, msg in _py_mutable_defaults(tree)[:4]:
                add("warn", rel, line, msg)
                fams["mutable"] += 1
            for line, msg in _py_bare_except(tree)[:4]:
                add("warn", rel, line, msg)
                fams["bare_except"] += 1
        elif low.endswith((".js", ".mjs")):
            js_fns_by_file.append((rel, [
                (m.group(1), _line_of(body, m.start()))
                for m in _JS_FN_DECL_RE.finditer(body)]))
            for line, name in _js_dup_fns(body):
                add("error", rel, line,
                    "function %s(...) is declared twice in this file - "
                    "the first body silently loses (extra code / wrong "
                    "behavior)" % name)
                fams["js_dup"] += 1
            stubs = _js_stubs_and_catches(body)
            n_stub = 0
            for line, name, kind in stubs:
                if kind == "empty implementation":
                    if n_stub >= MAX_STUB_REPORTED:
                        continue
                    n_stub += 1
                    fams["stub"] += 1
                    add("warn", rel, line,
                        "stub body: %s() is empty - a promised feature "
                        "is missing" % name)
                else:
                    add("warn", rel, line, kind)
                    fams["bare_except"] += 1
        elif low.endswith((".html", ".htm")):
            for line, ident in _html_dup_ids(body)[:6]:
                add("warn", rel, line,
                    "id '%s' is defined twice in this page - #sel only "
                    "reaches the FIRST element (the other is dead)"
                    % ident)
                fams["dup_id"] += 1
            for line, ident in _html_dead_buttons(body,
                                                  js_text_all)[:MAX_DEAD_BUTTONS]:
                add("warn", rel, line,
                    "button '%s' is type=button but NO script listens "
                    "to it and it has no onclick (wired to nothing)"
                    % ident)
                fams["dead_button"] += 1
            for line, fn, msg in _page_handler_gaps(rel, body, pool,
                                                    ws)[:6]:
                add("warn", rel, line, msg)
                fams["page_handler"] += 1
        if low.endswith(_DEEP_EXTS):
            for line, mark, msg in _todos(body)[:MAX_TODO_REPORTED]:
                add("warn", rel, line, msg)
                fams["todo"] += 1
    if cfg is None or (isinstance(cfg, dict) and
                       cfg.get("unused", True)):
        for rel, line, name, msg in \
                _unused_fns(list(pool.items()), py_facts_by_file,
                            js_fns_by_file)[:MAX_UNUSED_REPORTED]:
            add("warn", rel, line, msg)
            fams["unused"] += 1
    return {"errors": errors, "warns": warns[:MAX_WIRING_FINDINGS],
            "counts": {"files": len(pool), "families": fams}}


def _top_level_fns(tree):
    return [n for n in getattr(tree, "body", [])
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def deep_repair_prompt(report):
    """The deep sweep's message back to the generator model."""
    errs = report.get("errors") or []
    if not errs:
        return ""
    lines = ["BUG HUNTER (deep sweep): %d code-level bug(s) found - "
             "NOTHING was written to disk. Fix EXACTLY these (define "
             "every missing name, correct every signature, remove "
             "duplicate definitions) and re-output the COMPLETE "
             "corrected file(s) with the === FILE: path === ... "
             "=== END === protocol:" % len(errs)]
    for rel, line, msg in errs[:12]:
        lines.append("- %s: line %s: %s" % (rel, line or "?", msg))
    lines.append("")
    lines.append("Rules: output every fixed file in THIS one answer; "
                 "keep everything else identical; end with the Run:/"
                 "Preview: line.")
    return "\n".join(lines)


# =====================================================================
# 5. THE ORCHESTRATORS - pre-apply gate + post-apply sweep
# =====================================================================
def pre_apply_gate(bodies, ws=None, cfg=None):
    """THE PRE-APPLY GATE (wiring + v8.6 deep sweep). Deterministic,
    offline, atomic: a batch whose wiring is dead (a button wired to
    nothing, a missing script/stylesheet, a broken relative import) or
    whose CODE is broken in an unambiguous way (a call to a name defined
    nowhere, an impossible call signature, a duplicate definition) is
    refused BEFORE one byte is written. Returns
    {"errors", "warns", "reject", "repair", "static"} - never raises."""
    cfg = cfg if isinstance(cfg, dict) else dict(DEFAULTS)
    # v8.12: the wiring toggle now really controls the wiring probe -
    # 'deep on / wiring off' previously still paid for the wiring sweep
    # while 'wiring on / deep off' worked; symmetric and honest now.
    if enabled(cfg, "wiring"):
        rep = wiring_check(bodies, ws=ws, cfg=cfg)
    else:
        rep = {"errors": [], "warns": [], "via": {}, "counts": {}}
    errors = list(rep["errors"])
    warns = list(rep["warns"])
    static = {"errors": [], "warns": [], "counts": {}}
    if enabled(cfg, "deep"):
        try:
            static = static_check(bodies, ws=ws, cfg=cfg)
        except Exception as e:            # the sweep never breaks the gate
            static = {"errors": [], "warns": [],
                      "counts": {}, "error": str(e)[:120]}
        errors.extend(static.get("errors") or [])
        warns.extend(static.get("warns") or [])
    reject = bool(rep["errors"]) and enabled(cfg, "reject_wiring") \
        and master_on(cfg)
    deep_reject = bool(static.get("errors")) and \
        enabled(cfg, "reject_deep") and master_on(cfg)
    reject = reject or deep_reject
    repair = ""
    if reject:
        parts = []
        if rep["errors"]:
            parts.append(wiring_repair_prompt(rep))
        if static.get("errors"):
            parts.append(deep_repair_prompt(static))
        repair = "\n\n".join(p for p in parts if p)
    return {"errors": errors[:MAX_WIRING_FINDINGS + MAX_DEEP_FINDINGS],
            "warns": warns[:MAX_WIRING_FINDINGS],
            "counts": rep.get("counts", {}),
            "static": static,
            "reject": reject,
            "repair": repair}


def run_post_apply(ws, applied, request="", chat_fn=None, cfg=None):
    """The post-apply sweep: wiring over the real workspace + the deep
    static sweep + smoke runs + the browser probe + the completeness
    review. Returns a report dict; NEVER raises for content problems.
    Bounded in time (the feedback gate must stay fast)."""
    cfg = cfg if isinstance(cfg, dict) else dict(DEFAULTS)
    rep = {"wiring": None, "static": None, "smoke": None, "browser": None,
           "review": None, "verdict": "pass", "findings": []}
    if not applied:
        return rep
    bodies = []
    if enabled(cfg, "wiring") or enabled(cfg, "deep"):
        for name in applied[:8]:
            rel = str(name).replace("\\", "/")
            body = _read_entry(ws, rel, cap=MAX_WIRING_FILE_CHARS)
            if body:
                bodies.append((rel, body))
    if enabled(cfg, "wiring"):
        try:
            rep["wiring"] = wiring_check(bodies, ws=Path(ws), cfg=cfg)
        except Exception as e:
            rep["wiring"] = {"errors": [], "warns": [],
                             "counts": {}, "error": str(e)[:120]}
    if enabled(cfg, "deep"):
        try:
            rep["static"] = static_check(bodies, ws=Path(ws), cfg=cfg)
        except Exception as e:
            rep["static"] = {"errors": [], "warns": [],
                             "counts": {}, "error": str(e)[:120]}
    if enabled(cfg, "smoke"):
        try:
            rep["smoke"] = smoke_check(ws, applied)
        except Exception as e:
            rep["smoke"] = {"runs": [], "ran": 0,
                            "error": str(e)[:120]}
    if enabled(cfg, "browser"):
        try:
            rep["browser"] = browser_check(ws, applied)
        except Exception as e:
            rep["browser"] = {"ran": False, "errors": [], "warns": [],
                              "clicks": 0, "skipped": str(e)[:120]}
    if enabled(cfg, "review") and chat_fn is not None:
        try:
            rep["review"] = review_completeness(request, ws, applied,
                                                chat_fn)
        except Exception as e:
            rep["review"] = {"model_used": False, "complete": None,
                             "gaps": [], "error": str(e)[:120]}
    rep["findings"] = findings_summary(rep)
    levels = {lv for _f, _l, _m, lv in rep["findings"]}
    if "error" in levels:
        rep["verdict"] = "bug"
    elif "warn" in levels:
        rep["verdict"] = "warn"
    return rep


def findings_summary(rep):
    """Flat [(file, line, msg, level)] across every probe - the shape
    last_feedback / the web event / the fix note all consume."""
    out = []
    w = rep.get("wiring") or {}
    for rel, line, msg in (w.get("errors") or [])[:MAX_WIRING_FINDINGS]:
        out.append((rel, line, msg, "error"))
    for rel, line, msg in (w.get("warns") or [])[:12]:
        out.append((rel, line, msg, "warn"))
    d = rep.get("static") or {}
    for rel, line, msg in (d.get("errors") or [])[:MAX_DEEP_FINDINGS]:
        out.append((rel, line, msg, "error"))
    for rel, line, msg in (d.get("warns") or [])[:12]:
        out.append((rel, line, msg, "warn"))
    s = rep.get("smoke") or {}
    for run in (s.get("runs") or []):
        lv = run.get("level") or "info"
        if lv in ("pass",) and not run.get("msg"):
            continue
        out.append((run.get("file") or "-", 0,
                    run.get("msg") or "smoke run " + lv, lv))
    b = rep.get("browser") or {}
    for rel, line, msg in (b.get("errors") or [])[:BROWSER_MAX_ERRORS]:
        out.append((rel, line, msg, "error"))
    for rel, line, msg in (b.get("warns") or [])[:4]:
        out.append((rel, line, msg, "warn"))
    r = rep.get("review") or {}
    for where, what in (r.get("gaps") or [])[:MAX_GAPS]:
        # v8.10.1 fix: the completeness review is the MODEL OPINION rung -
        # documented advisory-only ("the local brain advises, the
        # deterministic gates decide"). Level "error" made the sweep
        # verdict "bug" from model prose alone and gave the gaps the same
        # weight as deterministic dead references in the fix feedback.
        out.append((where if where != "-" else "(delivery)", 0,
                    "missing work: " + what, "warn"))
    return out[:MAX_WIRING_FINDINGS + 24]


def report_lines(rep, max_lines=6):
    """Compact terminal/web lines [(level, text)] for the gate report."""
    out = []
    for rel, line, msg, lv in rep.get("findings") or []:
        where = ("line %s" % line) if line else "-"
        out.append((lv, "%s: %s: %s" % (rel, where, msg)))
        if len(out) >= max_lines:
            break
    return out
