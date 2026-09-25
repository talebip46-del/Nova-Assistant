#!/usr/bin/env python3
# =====================================================================
#  Nova Code - codebase STYLE map (v5.0)
#
#  The old file map told the model "main.py (812 lines)" - and nothing
#  else, so the model had to burn [READ:] rounds (minutes on weak
#  hardware) just to discover what a file contains. The style map gives
#  it the SHAPE of the codebase instead: top-level classes/functions per
#  file, in a tight, budgeted block:
#
#    app/nova.py (3187 lines): class Session; def chat_turn(...);
#                              def offer_apply(...); ...
#    web/main.js (210 lines): function renderMd(...); class Table
#
#  What it extracts (regex-based, indentation-aware, zero deps):
#    python   def / async def / class (top level only)
#    js/ts    function / class / exported consts with arrow fns
#    css      top-level selectors + @media
#    html     <title>, external scripts/styles
#    json     top-level keys
#    sh       function name() { / function name
#
#  Budgets keep the system prompt safe on a 4096-token window:
#  per-file signature cap, total char cap, file cap - and every path
#  respects .novaignore.
# =====================================================================
import os
import re
from pathlib import Path

MAX_MAP_CHARS = 2600        # total budget for the injected map section
MAX_SIGS_PER_FILE = 8       # signatures shown per file
MAX_FILES = 60              # file entries shown
SIG_MAX_CHARS = 110         # one signature line is clamped to this
CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".htm",
             ".json", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".php",
             ".rb", ".sh"}

_RE_PY = re.compile(r"^(?:async[ \t]+)?def[ \t]+(\w+)|^class[ \t]+(\w+)")
_RE_JS = re.compile(
    r"^(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?function\*?[ \t]+(\w+)"
    r"|^(?:export[ \t]+)?class[ \t]+(\w+)"
    r"|^(?:export[ \t]+)?(?:const|let|var)[ \t]+(\w+)[ \t]*=[ \t]*(?:async[ \t]*)?\(")
_RE_HTML_TITLE = re.compile(r"<title>([^<]{0,400})</title>", re.IGNORECASE)
_RE_HTML_EXT = re.compile(r"<(?:script[ \t][^>]*\bsrc=|link[ \t][^>]*\bhref=)[\"']([^\"']+)",
                          re.IGNORECASE)
_RE_SH = re.compile(r"^(?:function[ \t]+(\w+)|(\w+)[ \t]*\(\)[ \t]*\{)")


def _clamp(sig):
    sig = re.sub(r"\s+", " ", sig).strip()
    return sig[:SIG_MAX_CHARS] + ("..." if len(sig) > SIG_MAX_CHARS else "")


def py_signatures(text):
    """v6.8: AST-first - real ast walk gives exact signatures (with
    defaults + annotations), decorated defs and class methods, which the
    old line regex missed (indented defs, multi-line signatures). Falls
    back to the regex when the file does not parse (it may not be Python
    at all - never a crash)."""
    try:
        import nova_astmap as _astmap
        syms = _astmap.py_symbols(text)
        if syms:
            # v6.8.1: TWO-PASS priority - a module that declares ten
            # constants first used to fill the whole 8-signature cap and
            # the actual functions/classes (the reason the map exists)
            # were pushed out. Code first, variables fill the rest.
            code_syms = [s for s in syms if s["kind"] != "variable"]
            var_syms = [s for s in syms if s["kind"] == "variable"]
            out = []
            for s in code_syms + var_syms:
                # map budget discipline: top-level symbols only (methods
                # would flood the cap) - /symbols shows them all
                if s["kind"] == "method":
                    continue
                prefix = {"function": "", "class": "", "variable": ""}.get(
                    s["kind"], "def ")
                out.append(_clamp(prefix + s["sig"]))
                if len(out) >= MAX_SIGS_PER_FILE:
                    break
            return out
    except Exception:
        pass
    out = []
    for ln in text.splitlines():
        if ln and not ln[0].isspace():
            m = _RE_PY.match(ln)
            if m:
                out.append(_clamp(ln.rstrip(":").strip()))
                if len(out) >= MAX_SIGS_PER_FILE * 2:
                    break
    return out[:MAX_SIGS_PER_FILE]


def js_signatures(text):
    out = []
    for ln in text.splitlines():
        if ln and not ln[0].isspace():
            m = _RE_JS.match(ln)
            if m:
                name = next((g for g in m.groups() if g), "")
                kind = "class" if "class" in ln.split() else "function"
                out.append(_clamp(f"{kind} {name}(...)"))
                if len(out) >= MAX_SIGS_PER_FILE * 2:
                    break
    return out[:MAX_SIGS_PER_FILE]


def css_signatures(text):
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("@media") or s.startswith("@supports") or s.startswith("@keyframes"):
            out.append(_clamp(s))
        elif ln and not ln[0].isspace() and "{" in ln and not s.startswith(("/", "#", "*")):
            out.append(_clamp(s.split("{", 1)[0].strip() + " {"))
        if len(out) >= MAX_SIGS_PER_FILE:
            break
    return out[:MAX_SIGS_PER_FILE]


def html_signatures(text):
    out = []
    m = _RE_HTML_TITLE.search(text)
    if m and m.group(1).strip():
        out.append(_clamp("title: " + m.group(1).strip()))
    for m in _RE_HTML_EXT.finditer(text):
        out.append(_clamp("loads: " + m.group(1)))
        if len(out) >= MAX_SIGS_PER_FILE:
            break
    return out


def json_signatures(text):
    import json as _json
    try:
        obj = _json.loads(text)
        if isinstance(obj, dict):
            return [_clamp(f"key: {k}") for k in list(obj.keys())[:MAX_SIGS_PER_FILE]]
        if isinstance(obj, list):
            return [f"array of {len(obj)} items"]
    except Exception:
        return []
    return []


def sh_signatures(text):
    out = []
    for ln in text.splitlines():
        m = _SH_match(ln)
        if m:
            out.append(_clamp(m))
            if len(out) >= MAX_SIGS_PER_FILE:
                break
    return out


def _SH_match(ln):
    m = _RE_SH.match(ln)
    if m:
        return "function " + (m.group(1) or m.group(2)) + "()"
    return None


def file_signatures(rel, text):
    """Dispatch by extension - unknown types produce no signatures."""
    ext = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    try:
        if ext == ".py":
            return py_signatures(text)
        if ext in (".js", ".ts", ".jsx", ".tsx", ".mjs"):
            return js_signatures(text)
        if ext == ".css":
            return css_signatures(text)
        if ext in (".html", ".htm"):
            return html_signatures(text)
        if ext == ".json":
            return json_signatures(text)
        if ext in (".sh", ".bash"):
            return sh_signatures(text)
    except Exception:
        return []
    return []


def build_style_map(ws, ignore=None, max_chars=MAX_MAP_CHARS):
    """The injected project map. Falls back to a plain file list (the old
    format) for files without recognizable structure. Every path goes
    through `ignore.matches()` when a .novaignore is active."""
    ws = Path(ws)
    entries, extra = [], 0
    used = 0
    # v6.5 fix: `list(os.walk(ws))` drained the ENTIRE tree up front, so the
    # dirs[:] pruning below ran after node_modules/.git had already been
    # walked AND their files collected into the map (perf + correctness:
    # dependency files pushed real project files out of the 60-file budget).
    # os.walk is lazy - iterate it directly so pruning actually prunes.
    walk = os.walk(ws)
    collected = []
    for r, dirs, names in walk:
        dirs[:] = sorted(d for d in dirs
                         if d not in (".git", "node_modules", "__pycache__",
                                      ".nova", ".nova_backups", "venv", ".venv",
                                      ".idea", ".vscode")
                         and not d.startswith("."))
        if ignore is not None:
            relroot = os.path.relpath(r, ws).replace(os.sep, "/")
            keep = []
            for d in dirs:
                rel_d = f"{relroot}/{d}" if relroot != "." else d
                if not ignore.matches(rel_d, is_dir=True):
                    keep.append(d)
            dirs[:] = keep
        for n in sorted(names):
            if n.startswith("."):
                continue
            p = Path(r) / n
            rel = p.relative_to(ws).as_posix()
            if ignore is not None and ignore.matches(rel):
                continue
            collected.append((p, rel))
    for p, rel in collected:
        if len(entries) >= MAX_FILES or used >= max_chars:
            extra = len(collected) - len(entries) - extra
            break
        try:
            size = p.stat().st_size
        except OSError:
            continue
        sigs = []
        ext = p.suffix.lower()
        if ext in CODE_EXTS and size < 300_000:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                lines = text.count("\n") + 1
                sigs = file_signatures(rel, text)
            except OSError:
                lines, sigs = -1, []
        else:
            lines = -1
        head = f"- {rel}" + (f" ({lines} lines)" if lines >= 0 else f" ({_human(size)})")
        entry = head
        if sigs:
            entry += ": " + "; ".join(sigs)
        entry = entry[:400]
        if used + len(entry) > max_chars and entries:
            extra = len(collected) - len(entries)
            break
        entries.append(entry)
        used += len(entry) + 1
    if not entries:
        return "(the workspace is empty)"
    text = "\n".join(entries)
    if extra > 0:
        text += f"\n- ... and {extra} more files"
    return text


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
