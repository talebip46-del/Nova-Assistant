#!/usr/bin/env python3
# =====================================================================
#  Nova Code - quality toolkit: pre-apply lint, coverage, docs (v6.8)
#
#    preapply_check(name, content)   the INTERNAL LINTER before apply:
#                                    Python -> ast.parse (+ py_compile
#                                    when importable), JSON -> json,
#                                    JS -> node --check on a temp file
#                                    (when node exists). A file that
#                                    cannot parse is REJECTED before it
#                                    can break the project.
#    run_coverage(ws)                pytest/coverage OR coverage on the
#                                    detected test cmd - never imports
#                                    them into Nova (subprocess only).
#    generate_docs(ws, rels)         docstring-driven DOCS.md from the
#                                    AST symbol map (zero model calls).
# =====================================================================
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import nova_astmap as astmap
except Exception:
    astmap = None

RUN_TIMEOUT = 120

# v6.9: quoted strings / comments are stripped before the CSS brace count
# and the HTML tag count - a literal '}' inside content:"}" used to
# false-reject a healthy stylesheet (and the WHOLE atomic batch with it).
_NOISE_RE = re.compile(
    r'"""[\s\S]*?"""'          # py/js triple
    r"|'''[\s\S]*?'''"
    r'|"(?:[^"\\\n]|\\.)*"'   # "..."
    r"|'(?:[^'\\\n]|\\.)*'"     # '...'
    r'|`(?:[^`\\]|\\.)*`'       # js template literal
    r'|/\*[\s\S]*?\*/'          # css/js block comment
    r'|<!--[\s\S]*?-->'          # html comment
)
_NOISE_RE_NO_JS = re.compile(
    r'"""[\s\S]*?"""'          # py/js triple
    r"|'''[\s\S]*?'''"
    r'|"(?:[^"\\\n]|\\.)*"'   # "..."
    r"|'(?:[^'\\\n]|\\.)*'"     # '...'
    r'|/\*[\s\S]*?\*/'          # css/js block comment
    r'|<!--[\s\S]*?-->'          # html comment
)   # v8.11: same, WITHOUT the template-literal pairing (backticks are
    # plain text in html prose - see the two-count HTML branch)


def _strip_noise(text, js_templates=True):
    rx = _NOISE_RE if js_templates else _NOISE_RE_NO_JS
    return rx.sub(lambda m: "" if m.group(0)[:2] in ("/*", "<!")
                         else '"""' if m.group(0)[:3] == '"""' else
                         "''" if m.group(0)[:3] == "'''" else "", text)


# --------------------------------------------------------------- pre-apply
def preapply_check(name, content):
    """Validate NEW file content BEFORE it is written.
    Returns (ok, problem|None). Unknown types pass (repomap handles
    them); a parse failure blocks the apply with a precise message."""
    text = str(content or "")
    rel = (name or "").lower()
    if not text.strip():
        return (True, None)
    try:
        if rel.endswith(".py"):
            try:
                ast.parse(text)
            except SyntaxError as e:
                return (False, f"Python syntax error: line {e.lineno}: {e.msg}")
        elif rel.endswith(".json") or rel == ".nova":
            try:
                json.loads(text)
            except ValueError as e:
                return (False, f"invalid JSON: {e}")
        elif rel.endswith((".js", ".mjs", ".cjs")):
            node = _which_node()
            if node:
                code, out = _node_check(node, text)
                if code != 0:
                    first = (out or "").strip().splitlines()
                    return (False, "JS syntax error: " +
                            (first[0] if first else "node --check failed")[:200])
        elif rel.endswith(".html"):
            # the cheapest useful signal: balanced <script>/<style> tags
            # v8.11: TWO counts - one with the full noise strip (js
            # template-literal pairing) and one without it. A page whose
            # PROSE contains lone backticks paired up across the
            # document, swallowed a counted tag and false-rejected the
            # whole batch ('press `</p></body></html>' in a docs page).
            # When only the backtick-paired count fails, the evidence is
            # ambiguous -> fail-open (the guardian/probe gates still
            # review the file; a genuinely truncated page fails BOTH).
            low = _strip_noise(text).lower()
            for tag in ("script", "style", "html", "body"):
                op = len(re.findall(r"<" + tag + r"[\s>]", low))
                cl = len(re.findall(r"</" + tag + r"\s*>", low))
                if op and op != cl:
                    low_nb = _strip_noise(text, js_templates=False).lower()
                    op2 = len(re.findall(r"<" + tag + r"[\s>]", low_nb))
                    cl2 = len(re.findall(r"</" + tag + r"\s*>", low_nb))
                    if op2 == cl2:
                        continue      # only the backtick pairing saw it
                    return (False, f"HTML: <{tag}> opened {op}x but closed {cl}x")
        elif rel.endswith(".css"):
            # v6.8.3: CSS had ZERO lint coverage - a truncated or
            # brace-broken stylesheet shipped silently and the page
            # rendered unstyled ('the generated code is broken').
            # Cheapest real signal: balanced braces + a closing one.
            # v6.9: quoted strings/comments stripped first (content:"}").
            # v7.1.0: a valid @import/@charset-only sheet (or an all-comments
            # file) has no braces on purpose - it used to be rejected as
            # "no rules found", blocking the WHOLE atomic batch.
            # v8.10.1 fix: the all-comments half was never implemented -
            # after the noise strip an empty sheet (comments only) still
            # hit 'no rules found'. (A file that was empty from the start
            # never reaches this branch - the top gate passes it.)
            css = _strip_noise(text)
            if not css.strip():
                return (True, None)
            ob, cb = css.count("{"), css.count("}")
            if ob != cb:
                return (False, f"CSS: {{ opened {ob}x but }} closed {cb}x "
                               "(a rule is truncated or a brace is missing)")
            if ob == 0:
                # v7.1.0: an @import/@charset-only sheet has no braces on
                # purpose. v8.11 fix: the old blanket 'return ok' for ANY
                # sheet containing @import also skipped the brace-balance
                # check - a TRUNCATED stylesheet with a font @import (the
                # most common generated shape) shipped silently and the
                # page rendered unstyled. The exemption now only covers
                # sheets that genuinely have no rules.
                if re.search(r"@import\b|@charset\b", css):
                    return (True, None)
                return (False, "CSS: no rules found (is this the right content?)")
    except Exception as e:          # the linter itself must never crash apply
        return (True, None)
    return (True, None)


def _which_node():
    """The node executable PATH (not a bool! - v6.9 bugfix: the old probe
    returned True/False, so _node_check ran subprocess.run([True, ...])
    and EVERY valid .js file failed the pre-apply lint with 'expected str,
    bytes or os.PathLike' - the whole multi-file batch was rejected)."""
    path = shutil.which("node")
    if not path:
        return None
    try:
        if subprocess.run([path, "--version"], capture_output=True,
                          timeout=5).returncode == 0:
            return path
    except Exception:
        return None
    return None


_ESM_HINT_RE = re.compile(
    r"(?m)^\s*(?:import\s|import\s*\(|export\s+(?:default|const|let|var|"
    r"function|class|\{|\*|async))")


def _node_check(node, text):
    mpath = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(text)
            path = fh.name
        try:
            p = subprocess.run([node, "--check", path], capture_output=True,
                               text=True, timeout=30)
            code, out = p.returncode, (p.stderr or "") + (p.stdout or "")
            # v8.11: on Node 14-18 (common on modest machines) `node
            # --check file.js` cannot parse ESM import/export in a .js
            # file ("Cannot use import statement outside a module") -
            # healthy modules were rejected and the whole atomic batch
            # with them. Retry the SAME body as .mjs before refusing.
            if code != 0 and _ESM_HINT_RE.search(text):
                try:
                    mpath = path + ".mjs"
                    with open(mpath, "w", encoding="utf-8") as mh:
                        mh.write(text)
                    p2 = subprocess.run([node, "--check", mpath],
                                        capture_output=True, text=True,
                                        timeout=30)
                    if p2.returncode == 0:
                        return (0, "")
                except Exception:
                    pass
            return (code, out)
        finally:
            for tmp in (path, mpath):
                if not tmp:
                    continue
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except Exception as e:
        return (1, str(e))


# --------------------------------------------------------------- coverage
def _py_basename(cmd0):
    try:
        base = os.path.basename(str(cmd0)).lower()
    except Exception:
        return False
    return base.startswith("python") or str(cmd0) == sys.executable


def run_coverage(ws, cmd=None, timeout=RUN_TIMEOUT):
    """Run the project's tests under coverage.py when it exists.
    Returns {"ok", "mode", "report", "percent"} - mode explains what
    actually ran; percent is None when coverage.py is missing.
    `cmd` accepts: None (auto-detect), a full command string, a list,
    or nova_feedback.detect_test_cmd's (cmd, source) tuple."""
    ws = Path(ws)
    has_cov = _importable("coverage")
    if cmd is None:
        try:
            import nova_feedback as feedback
            detected = feedback.detect_test_cmd(ws)
            if isinstance(detected, tuple):
                cmd = detected[0]
            elif isinstance(detected, dict):
                cmd = detected.get("cmd")
            else:
                cmd = detected
        except Exception:
            cmd = None
    if not cmd:
        return {"ok": False, "mode": "none", "report":
                "no test command detected - add pytest or a test suite first",
                "percent": None}
    if isinstance(cmd, str):
        try:
            import shlex
            # v6.8.1: posix=False on Windows - backslash paths survive
            cmd_list = shlex.split(cmd, posix=(os.name != "nt"))
        except ValueError:
            cmd_list = cmd.split()
    else:
        cmd_list = [str(c) for c in cmd]
    if not cmd_list:
        return {"ok": False, "mode": "none", "report": "empty command",
                "percent": None}
    if has_cov:
        first = cmd_list[0]
        if _py_basename(first):
            # python -m pytest / python -m unittest / python script.py -
            # coverage re-runs the MODULE/script with its own interpreter
            full = ["coverage", "run", "--source=."] + cmd_list[1:]
        elif os.path.basename(first).startswith("pytest"):
            full = ["coverage", "run", "--source=.", "-m"] + cmd_list
        else:
            full = ["coverage", "run"] + cmd_list
        mode = "coverage"
    else:
        full = cmd_list
        mode = "tests-only"
    try:
        p = subprocess.run(full, cwd=str(ws), capture_output=True,
                           text=True, timeout=timeout)
        out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return {"ok": False, "mode": mode, "report": "timed out", "percent": None}
    except OSError as e:
        return {"ok": False, "mode": mode, "report": str(e)[:200], "percent": None}
    percent = None
    tail = ""
    if has_cov and p.returncode == 0:
        try:
            r = subprocess.run(["coverage", "report", "--skip-covered"],
                               cwd=str(ws), capture_output=True, text=True,
                               timeout=60)
            tail = (r.stdout or "").strip()
            m = re.search(r"TOTAL.*?(\d+)%", tail)
            if m:
                percent = int(m.group(1))
        except Exception:
            pass
    short = _last_meaningful(out.splitlines(), 25)
    return {"ok": p.returncode == 0, "mode": mode,
            "report": "\n".join(short) if short else "(no output)",
            "extra": tail[-4000:], "percent": percent}


def _last_meaningful(lines, n):
    out = [ln for ln in lines if ln.strip()]
    return out[-n:] if len(out) > n else out


def _importable(name):
    """Is a module importable here? (coverage only - we never import the
    project under test into Nova)."""
    try:
        __import__(name)
        return True
    except Exception:
        return False


# --------------------------------------------------------------- docs
DOCS_HEADER = ("# Project documentation\n\n"
               "Generated by Nova from docstrings & signatures "
               "(python {python}). Re-run /docs after big changes.\n")


def generate_docs(ws, rels=None, out_name="DOCS.md", max_files=200):
    """Write DOCS.md from the AST skeletons of the workspace's Python
    files (docstrings included). Returns (path, error)."""
    if astmap is None:
        return (None, "nova_astmap.py missing")
    ws = Path(ws)
    if rels is None:
        rels = []
        for p in sorted(ws.rglob("*.py")):
            rel = p.relative_to(ws).as_posix()
            parts = set(rel.split("/"))
            if parts & {".git", ".nova", "__pycache__", ".venv", "venv",
                        ".nova_backups", "node_modules"}:
                continue
            rels.append(rel)
    rels = [r for r in rels if str(r).lower().endswith(".py")][:max_files]
    if not rels:
        return (None, "no python files found to document")
    blocks = [DOCS_HEADER.format(python=sys.version.split()[0])]
    total_syms = 0
    for rel in rels:
        try:
            text = (ws / rel).read_text(encoding="utf-8", errors="replace")[:400_000]
        except OSError:
            continue
        syms = astmap.py_symbols(text)
        if not syms:
            continue
        total_syms += len(syms)
        module_doc = ""
        try:
            module_doc = (ast.get_docstring(ast.parse(text)) or "").strip()
        except Exception:
            pass
        blocks.append(f"\n## {rel}\n")
        if module_doc:
            blocks.append(module_doc[:600] + "\n")
        for s in syms:
            kind = {"function": "#### ", "method": "##### ",
                    "class": "### ", "variable": "- "}.get(s["kind"], "- ")
            blocks.append(f"{kind}`{s['sig']}`  (line {s['line']})")
            if s.get("doc"):
                blocks.append(f"  {s['doc']}")
        if total_syms > 1500:
            blocks.append("\n(truncated: project too large for one DOCS.md)")
            break
    outp = ws / out_name
    try:
        outp.write_text("\n".join(blocks), encoding="utf-8", newline="\n")
    except OSError as e:
        return (None, str(e))
    return (outp.name, "")
