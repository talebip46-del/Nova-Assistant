#!/usr/bin/env python3
# =====================================================================
#  Nova Code - the USER'S CODING STYLE PROFILE (v7.5.0)
#
#  Long-term project memory: Nova reads the workspace's existing code
#  ONCE, learns the user's habits (indent, quotes, naming, comment
#  language, framework hints) and injects a compact "match this style"
#  block into every coding turn - LOCAL and CLOUD alike, because this
#  is personalization, not weakness compensation: it makes output fit
#  the project instead of fighting it.
#
#  Persisted to .nova/style.json; refreshed after applies (cheap,
#  bounded); NOVA_NO_STYLE=1 disables; fail-soft everywhere.
# =====================================================================
import json
import os
import re
from pathlib import Path

STYLE_FILE = "style.json"
MAX_FILES = 120
MAX_FILE_BYTES = 120_000
SCAN_EXT = (".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html")

_indents = re.compile(r"^( +)\S")
_defs = re.compile(r"^(?:def|function|class)\s+([A-Za-z_][\w$]*)", re.M)
_dq = re.compile(r'"[^"\n]*"')
_sq = re.compile(r"'[^'\n]*'")
_comments = {"py": re.compile(r"#[^\n]*"),
             "js": re.compile(r"(?://[^\n]*|/\*.*?\*/)", re.S)}
_FA = re.compile(r"[\u0600-\u06FF]")
_FRAMEWORKS = ("flask", "django", "fastapi", "react", "vue", "express",
               "tkinter", "pandas", "numpy")


def _detect_indent(lines):
    """(style, width) - 'tabs' or 'spaces' with the modal width."""
    widths = {}
    tabs = 0
    for ln in lines[:1500]:
        if ln.startswith("\t"):
            tabs += 1
            continue
        m = _indents.match(ln)
        if m:
            w = len(m.group(1))
            if 0 < w <= 12:
                widths[w] = widths.get(w, 0) + 1
    if tabs > sum(widths.values()):
        return ("tabs", 4)
    if not widths:
        return ("spaces", 4)
    w = max(widths, key=lambda k: widths[k])
    # 2/4/8 bucketing: odd counts are usually continuation lines
    w = min((2, 4, 8), key=lambda c: (abs(c - w), c))
    return ("spaces", w)


def analyze_text(name, text, acc):
    """Fold one file's signals into the accumulator dict (mutated)."""
    try:
        lines = text.splitlines()
        if not lines:
            return
        style, width = _detect_indent(lines)
        acc.setdefault("indent_votes", []).append((style, width))
        ext = Path(name).suffix.lower().lstrip(".")
        if ext in ("py", "js", "ts", "jsx", "tsx"):
            dq, sq = len(_dq.findall(text)), len(_sq.findall(text))
            if dq or sq:
                acc.setdefault("quote_votes", []).append(
                    "double" if dq >= sq else "single")
            names = _defs.findall(text)
            for n in names:
                if "_" in n:
                    acc["naming_snake"] = acc.get("naming_snake", 0) + 1
                elif n[:1].islower() and any(c.isupper() for c in n[1:]):
                    acc["naming_camel"] = acc.get("naming_camel", 0) + 1
            cmt = _comments["py" if ext == "py" else "js"].findall(text)
            fa = sum(1 for c in cmt if _FA.search(c))
            if cmt:
                acc.setdefault("comment_total", 0)
                acc["comment_total"] += len(cmt)
                acc.setdefault("comment_fa", 0)
                acc["comment_fa"] += fa
            low = text.lower()
            for f in _FRAMEWORKS:
                if f in low:
                    acc.setdefault("frameworks", set()).add(f)
        lens = [len(l) for l in lines if l.strip()]
        if lens:
            lens.sort()
            acc.setdefault("line_len", []).append(lens[int(len(lens) * 0.9)])
    except Exception:
        pass


def analyze(ws, ignore=None):
    """Scan the workspace -> style dict (bounded, deterministic)."""
    acc = {}
    n = 0
    try:
        ws = Path(ws)
        for p in sorted(ws.rglob("*")):
            if n >= MAX_FILES:
                break
            if not p.is_file():
                continue
            rel = p.relative_to(ws).as_posix()
            if any(rel == d or rel.startswith(d + "/") for d in
                   (".git", ".nova", ".nova_backups", "node_modules",
                    "__pycache__", "fonts", "venv", ".venv")):
                continue
            if p.suffix.lower() not in SCAN_EXT:
                continue
            if ignore is not None:
                try:
                    if ignore.matches(rel):
                        continue
                except Exception:
                    pass
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            analyze_text(rel, text, acc)
            n += 1
    except Exception:
        pass
    return _summarize(acc)


def _summarize(acc):
    """Votes -> the compact profile dict (stable field order)."""
    prof = {"indent": "spaces", "indent_width": 4, "quotes": "double",
            "naming": "snake_case", "comment_lang": "en",
            "max_line": 96, "frameworks": []}
    iv = acc.get("indent_votes") or []
    if iv:
        style = "tabs" if sum(1 for s, _ in iv if s == "tabs") * 2 > len(iv) \
            else "spaces"
        widths = [w for s, w in iv if s == style]
        prof["indent"] = style
        if widths:
            prof["indent_width"] = max(set(widths), key=widths.count)
    qv = acc.get("quote_votes") or []
    if qv:
        prof["quotes"] = max(set(qv), key=qv.count)
    sn, ca = acc.get("naming_snake", 0), acc.get("naming_camel", 0)
    if ca > sn * 2:
        prof["naming"] = "camelCase"
    elif sn >= ca:
        prof["naming"] = "snake_case"
    tot, fa = acc.get("comment_total", 0), acc.get("comment_fa", 0)
    if tot and fa * 3 > tot:
        prof["comment_lang"] = "fa"
    ll = acc.get("line_len") or []
    if ll:
        prof["max_line"] = max(72, min(140, sorted(ll)[len(ll) // 2] + 8))
    fw = acc.get("frameworks") or set()
    prof["frameworks"] = sorted(fw)[:4]
    return prof


def style_path(ws):
    return Path(ws) / ".nova" / STYLE_FILE


def load(ws):
    try:
        p = style_path(ws)
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else None
    except Exception:
        return None
    return None


def save(ws, prof):
    try:
        p = style_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        # v7.14.1: atomic write - a crash mid-write used to publish a
        # truncated profile which then silently disabled style learning
        payload = json.dumps(prof, ensure_ascii=False, indent=1)
        try:
            import nova_atomic
            err = nova_atomic.write_text_atomic(p, payload,
                                                encoding="utf-8")
            if err:
                p.write_text(payload, encoding="utf-8")
        except ImportError:
            p.write_text(payload, encoding="utf-8")
        return ""
    except OSError as e:
        return str(e)


def refresh(ws, ignore=None):
    """Analyze + persist. Returns (profile, error)."""
    prof = analyze(ws, ignore)
    return prof, save(ws, prof)


def inject_text(ws):
    """The prompt block ('' when off/absent) - the model must MATCH the
    user's existing style instead of imposing its own defaults."""
    try:
        if os.environ.get("NOVA_NO_STYLE", "") == "1":
            return ""
        prof = load(ws)
        if not prof:
            return ""
        bits = [f"indent: {prof.get('indent', 'spaces')}"
                f"{' ' + str(prof.get('indent_width')) if prof.get('indent') == 'spaces' else ''}",
                f"quotes: {prof.get('quotes', 'double')}",
                f"naming: {prof.get('naming', 'snake_case')}"]
        if prof.get("comment_lang") == "fa":
            bits.append("comments: Persian (code + identifiers stay English)")
        if prof.get("frameworks"):
            bits.append("stack already used here: " +
                        ", ".join(prof["frameworks"]))
        return ("## Match the user's coding style (observed in this project)\n"
                "New code must blend in:\n- " + "\n- ".join(bits))
    except Exception:
        return ""
