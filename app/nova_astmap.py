#!/usr/bin/env python3
# =====================================================================
#  Nova Code - syntax-aware (AST) symbol map (v6.8)
#
#  The repomap shows raw text lines; this module UNDERSTANDS structure:
#    Python   real ast walk -> classes / functions / methods with their
#             exact signatures, decorators, line ranges and docstrings
#    JS/TS    light regex pass (function/class/const-arrow) - honest
#             best-effort, never a parse error source
#    other    [] (caller falls back to the raw repomap)
#
#  Used by:
#    /symbols <file>     show the skeleton of one file
#    symbol_change()     OLD vs NEW signature diff -> drives smarter
#                        commit messages ("edited function X") and the
#                        dependency-graph churn hints
#    repomap upgrade     .py entries now list signatures, not line 1
# =====================================================================
import ast
import re

MAX_SYMBOLS = 400
MAX_DOC = 60


def _sig_of(node):
    """Compact signature string of a FunctionDef / AsyncFunctionDef."""
    try:
        a = node.args
        parts = []
        pos = list(getattr(a, "posonlyargs", [])) + list(a.args)
        defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
        for arg, d in zip(pos, defaults):
            s = arg.arg
            if getattr(arg, "annotation", None) is not None:
                s += ": " + _unparse(arg.annotation)
            if d is not None:
                s += "=" + _unparse(d)
            parts.append(s)
        if a.vararg:
            parts.append("*" + a.vararg.arg)
        elif a.kwonlyargs:
            parts.append("*")
        for arg, d in zip(a.kwonlyargs, a.kw_defaults):
            s = arg.arg
            if d is not None:
                s += "=" + _unparse(d)
            parts.append(s)
        if a.kwarg:
            parts.append("**" + a.kwarg.arg)
        ret = ""
        if getattr(node, "returns", None) is not None:
            ret = " -> " + _unparse(node.returns)
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({', '.join(parts)}){ret}"
    except Exception:
        return f"def {node.name}(...)"


def _unparse(node):
    """ast.unparse with a hard length cap (2.x safety: never raise)."""
    try:
        s = ast.unparse(node)
        return s if len(s) <= 48 else s[:45] + "..."
    except Exception:
        return "?"


def _class_sig(node):
    bases = []
    try:
        for b in node.bases:
            bases.append(_unparse(b))
    except Exception:
        pass
    return f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"


def py_symbols(text):
    """All top-level + class-level symbols of a Python source text.
    Returns [{kind, name, sig, line, end, doc}] sorted by line."""
    out = []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, TypeError):
        return out

    def _doc(n):
        try:
            d = ast.get_docstring(n) or ""
            d = " ".join(d.split())
            return d[:MAX_DOC] if d else ""
        except Exception:
            return ""

    def _push(node, kind, sig):
        out.append({"kind": kind, "name": node.name, "sig": sig,
                    "line": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno),
                    "doc": _doc(node)})

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _push(node, "function", _sig_of(node))
        elif isinstance(node, ast.ClassDef):
            _push(node, "class", _class_sig(node))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append({"kind": "method", "name": sub.name,
                                "sig": _sig_of(sub), "line": sub.lineno,
                                "end": getattr(sub, "end_lineno", sub.lineno),
                                "doc": _doc(sub)})
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.append({"kind": "variable", "name": t.id,
                                "sig": f"{t.id} = {_unparse(node.value)}",
                                "line": node.lineno, "end": node.lineno,
                                "doc": ""})
                elif isinstance(t, ast.Tuple):
                    for e in t.elts:
                        if isinstance(e, ast.Name):
                            out.append({"kind": "variable", "name": e.id,
                                        "sig": f"{e.id} = (...)",
                                        "line": node.lineno, "end": node.lineno,
                                        "doc": ""})
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.append({"kind": "variable", "name": node.target.id,
                        "sig": f"{node.target.id}: {_unparse(node.annotation)}",
                        "line": node.lineno, "end": node.lineno, "doc": ""})
        if len(out) >= MAX_SYMBOLS:
            break
    out.sort(key=lambda s: s["line"])
    return out[:MAX_SYMBOLS]


# --------------------------------------------------------------- JS/TS
_JS_FN = re.compile(
    r"(?:^|\n)[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]{0,300})\)")
_JS_CLASS = re.compile(
    r"(?:^|\n)[ \t]*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+[\w$.]+)?")
_JS_ARROW = re.compile(
    r"(?:^|\n)[ \t]*(?:export\s+)?(?:const|let|var)\s+"
    r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]{0,200})\)\s*=>")


def js_symbols(text):
    out = []
    for m in _JS_CLASS.finditer(text):
        out.append({"kind": "class", "name": m.group(1),
                    "sig": f"class {m.group(1)}",
                    "line": text[:m.start()].count("\n") + 1,
                    "end": None, "doc": ""})
    for m in _JS_FN.finditer(text):
        out.append({"kind": "function", "name": m.group(1),
                    "sig": f"function {m.group(1)}({m.group(2)[:120]})",
                    "line": text[:m.start()].count("\n") + 1,
                    "end": None, "doc": ""})
    for m in _JS_ARROW.finditer(text):
        out.append({"kind": "function", "name": m.group(1),
                    "sig": f"const {m.group(1)} = ({m.group(2)[:80]}) => ...",
                    "line": text[:m.start()].count("\n") + 1,
                    "end": None, "doc": ""})
    out.sort(key=lambda s: s["line"])
    return out[:MAX_SYMBOLS]


def symbols_for(rel, text):
    """Dispatch by extension; returns [] for unknown types."""
    rel = (rel or "").lower()
    if rel.endswith(".py"):
        return py_symbols(text)
    if rel.endswith((".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx")):
        return js_symbols(text)
    return []


def skeleton(symbols, max_lines=60):
    """One compact text block: '  12: def f(x) -> int' style."""
    lines = []
    for s in symbols[:max_lines]:
        lines.append(f"{s['line']:5d}: {s['sig']}")
    if len(symbols) > max_lines:
        lines.append(f"  ... (+{len(symbols) - max_lines} more symbols)")
    return "\n".join(lines)


# --------------------------------------------------------------- change diff
def _sig_map(symbols):
    return {s["name"]: s["sig"] for s in symbols}


def symbol_change(old_text, new_text, ext=".py"):
    """(added, removed, changed) symbol-name lists between two versions."""
    old = _sig_map(symbols_for("x" + ext, old_text))
    new = _sig_map(symbols_for("x" + ext, new_text))
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(n for n in set(old) & set(new) if old[n] != new[n])
    return (added, removed, changed)


def change_summary(old_text, new_text, ext=".py"):
    """Human one-liner for commit messages, e.g.
    'edited: run_command, stream_chat; added: parse_patch'."""
    try:
        added, removed, changed = symbol_change(old_text, new_text, ext)
    except Exception:
        return ""
    parts = []
    if changed:
        parts.append("edited " + ", ".join(changed[:4]) +
                     ("..." if len(changed) > 4 else ""))
    if added:
        parts.append("added " + ", ".join(added[:4]) +
                     ("..." if len(added) > 4 else ""))
    if removed:
        parts.append("removed " + ", ".join(removed[:4]) +
                     ("..." if len(removed) > 4 else ""))
    return "; ".join(parts)
