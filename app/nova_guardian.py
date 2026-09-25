#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - the CODE GUARDIAN (v8.4 "code guardian")
#
#  The user's complaint: Nova's outputs look GREAT but arrive with broken
#  syntax and bugs. This module is the fix - ONE supervisor agent backed
#  by a fleet of language sub-sub-agents that supervise EVERY piece of
#  code Nova produces, in EVERY language:
#
#    1. THE LANGUAGE FLEET (sub-sub-agents)   ~30 language profiles.
#       Each profile carries a DETERMINISTIC validator that ALWAYS runs
#       and never needs anything external:
#         - real parsers where Python has them for free (ast / json /
#           yaml / tomllib)
#         - optional installed tools (node --check, bash -n, php -l,
#           ruby -c, gofmt -e, luac -p, gcc -fsyntax-only) - used ONLY
#           when present, each in a subprocess with a tight timeout,
#           output filtered to true syntax errors
#         - a string-aware delimiter scanner (comments / strings /
#           heredocs understood per language family) that flags
#           unbalanced (), [], {} WITH line numbers - the offline floor
#           for every language on earth
#         - a high-signal common-bug pattern DB per language (py2
#           print, assignment-in-condition, bash 'else if', 'gets('...)
#    2. THE SUPERVISOR (review_batch)         validates the whole
#       planned batch BEFORE it touches the disk (pre-apply gate in
#       nova.offer_apply - a file that cannot parse aborts the batch,
#       nothing is written), then (post-apply, in _feedback_gate) runs
#       the MODEL layer: per-file sub-sub-agent reviews in PARALLEL
#       (nova_subagent.run_parallel) on the LOCAL brain, their findings
#       feeding the next fix round through sess.last_feedback.
#    3. THE DEDICATED WEBSEARCH (web_lookup)  the fleet's OWN search
#       channel (separate "guardian:" cache namespace - /search cache
#       is never mixed in). Used ONLY to ENRICH the sub-sub-agents'
#       prompts with fresh references. NEVER a dependency: with no
#       internet every agent falls back to the built-in OFFLINE
#       KNOWLEDGE BASE and works exactly as well for correctness.
#       Correctness is deterministic-first; the internet is a bonus.
#
#  Settings live per-workspace in .nova/guardian.json (like
#  context.json): on / model / web / reject_syntax + custom flag.
#  Missing module, missing tools, no internet, broken settings file =
#  everything degrades gracefully to exactly the pre-8.4 behavior.
#
#  Pure standard library, fail-soft everywhere.
# =====================================================================
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:                       # pragma: no cover - fail-soft
    natom = None

try:
    import nova_search as _ns           # the fleet's dedicated websearch
except Exception:                       # rides on the shared fetch stack
    _ns = None

# ------------------------------------------------------------------ caps
MAX_GUARD_FILE_CHARS = 400_000   # files bigger than this: structure only
MAX_BATCH_FILES = 24             # validate at most N files per batch
MAX_TOOL_RUNS = 8                # subprocess validators per batch (budget)
TOOL_TIMEOUT = 12                # seconds per external validator
MAX_AGENT_FILES = 2              # model-layer reviews per apply batch
MAX_AGENT_CODE_CHARS = 6_000     # code snippet sent to a sub-sub-agent
MAX_WEB_LOOKUPS = 2              # dedicated-search calls per review
MAX_FINDINGS = 64                # total findings per batch (sanity)

SETTINGS_FILE = "guardian.json"
DEFAULTS = {
    "on": True,             # the whole guardian
    "model": True,          # sub-sub-agent MODEL reviews (local brain only)
    "web": True,            # the dedicated websearch enrichment
    "reject_syntax": True,  # deterministic errors block the batch
}
MAX_SETTINGS_BYTES = 4_000


def _env_float(name, default):
    try:
        raw = str(os.environ.get(name, "")).strip()
        val = float(raw) if raw else default
        # v8.12: aligned with nova_probe._env_float - a non-finite env
        # knob (nan/inf) falls back to the default instead of poisoning
        # whatever deadline it feeds next.
        if not math.isfinite(val):
            return default
        return val
    except ValueError:
        return default


# =====================================================================
# 1. THE STRING-AWARE DELIMITER SCANNER - the offline floor
# =====================================================================
# Language "families" define what may hide a bracket: comments, string
# quoting rules, heredocs. The scanner walks the text ONCE, tracks the
# state, and counts ( [ { with line numbers. It must NEVER invent an
# error while inside a string/comment - only confident mismatches in
# real code state are reported.

_FAMILIES = {
    # c-family: // line, /* */ block, "..." '...' chars, `...` (go/rs/js)
    "c":      {"line": ("//",), "block": (("/*", "*/"),),
               "strings": ('"', "'", "`"), "triple": ()},
    # v8.7: rust - a leading ' is a LIFETIME ('a), never a char literal.
    # Counting it as a string opener swallowed whole impl blocks and
    # REJECTED every lifetime-using .rs file (phantom unmatched '}').
    "rust":   {"line": ("//",), "block": (("/*", "*/"),),
               "strings": ('"', "`"), "triple": ()},
    # python: # line, triple quotes FIRST (they beat plain quotes), then
    "py":     {"line": ("#",), "block": (), "strings": ('"', "'"),
               "triple": ('"""', "'''")},
    # shell: # line, plain quotes (heredoc BODIES are pre-stripped)
    "shell":  {"line": ("#",), "block": (), "strings": ('"', "'"),
               "triple": ()},
    # sql: -- line, /* */ block, '...' strings
    "sql":    {"line": ("--",), "block": (("/*", "*/"),),
               "strings": ("'",), "triple": ()},
    # plain: nothing hides a bracket (data formats, config files)
    "plain":  {"line": (), "block": (), "strings": (), "triple": ()},
}

_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {v: k for k, v in _OPEN.items()}

# v8.7: the opener used to demand the tag at END of line, so the two
# most common bash idioms - `cat <<EOF > out.txt` and `<<'EOF'` - were
# NOT heredocs to the scanner and their bodies got bracket-scanned
# (false "'{' opened here is never closed" -> healthy batch rejected).
# The tag may now be quoted and may be followed by a redirect / pipe /
# digit-fd token; a bare `a << b` shift stays code (next char is an
# operand, not a redirect). Swallowing MORE as a heredoc is always the
# safe direction for the gate - it can only hide brackets, never
# invent errors.
_HEREDOC_OPEN_RE = re.compile(
    r"<<-?[ \t]*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?[ \t]*(?=$|[>|;&]|\d)")


def _strip_heredocs(text):
    """Blank out heredoc BODIES, line numbers preserved (one \n per
    dropped line): bash allows ANY character inside a <<EOF body, so
    counting its brackets would invent errors. The <<WORD line stays.
    Returns (stripped_text, unterminated_line|None)."""
    lines = text.splitlines(True)
    out, skip = [], None
    open_line = None
    for ln_no, ln in enumerate(lines, 1):
        if skip is not None:
            if re.match(r"^[ \t]*%s[ \t]*\r?$" % re.escape(skip), ln):
                skip = None
            out.append("\n" if ln.endswith("\n") else "")
            continue
        m = _HEREDOC_OPEN_RE.search(ln.rstrip("\r\n"))
        out.append(ln)
        if m:
            skip = m.group(1)
            open_line = ln_no
    return "".join(out), (open_line if skip is not None else None)


def _walk(text, fam):
    """ONE clean pass. Returns (errors, warns) as [(line, msg)].
    Only CONFIDENT problems in real code state are errors - a bracket
    inside a string or comment can never invent one."""
    line_comments, block_comments = fam["line"], fam["block"]
    strings, triples = fam["strings"], fam["triple"]
    errors, warns = [], []
    stack = []                       # [(char, line)]
    i, n, line = 0, len(text), 1
    state = "code"                   # code | line | block | string
    quote, triple = "", ""
    # v8.10.1 fix: bash parameter expansion - in `${#var}` the '#' is a
    # LENGTH operator, not a comment. The walk used to flip to line state
    # and swallow the closing '}' -> phantom "'{' opened here is never
    # closed" whenever the reference tool could not mask it (.zsh, no
    # bash, tools off, tool budget exhausted). A '${' frame on the stack
    # suppresses line comments until it closes.
    param_depth = 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            if state == "line":
                state = "code"
            i += 1
            continue
        if state == "line":
            i += 1
            continue
        if state == "block":
            if triple and text.startswith(triple, i):
                i += len(triple)
                state = "code"
                continue
            i += 1
            continue
        if state == "string":
            if ch == "\\":
                # v8.10.1 fix: a backslash-newline continuation used to
                # consume both chars without counting the line - every
                # line number after it drifted (misdirected repair).
                if i + 1 < n and text[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if triple and text.startswith(triple, i):
                i += len(triple)
                state = "code"
                continue
            if not triple and ch == quote:
                state = "code"
            i += 1
            continue
        # ------------------------- code state --------------------------
        hit = False
        for mark in line_comments:
            if text.startswith(mark, i):
                # v8.11: the word-boundary rule is SHELL-ONLY. The
                # scanner is shared, and the py family (python, perl, R)
                # allows GLUED comments ('x = 1#c' is legal) - the old
                # unscoped check phantom-rejected healthy python.
                if mark == "#" and fam is _FAMILIES.get("shell"):
                    if param_depth:
                        break          # '${#var}' - a length operator, not a comment
                    # v8.11: '#' starts a comment only at a word
                    # boundary - '$# -eq 2' (arg count), '$(( 16#ff ))'
                    # (base literal) and 'foo#bar' (a plain word) used to
                    # swallow the rest of the line as a comment and
                    # phantom-reject healthy scripts
                    if i > 0 and text[i - 1] not in " \t\n;&|(":
                        break
                state, hit = "line", True
                break
        if not hit:
            for op, cl in block_comments:
                if text.startswith(op, i):
                    state, quote, triple, hit = "block", "", cl, True
                    break
        if not hit:
            for t in triples:
                if text.startswith(t, i):
                    state, quote, triple, hit = "string", t[0], t, True
                    break
        if not hit and ch in strings:
            state, quote, triple, hit = "string", ch, "", True
        if hit:
            i += len(triple) if triple else 1
            continue
        # v8.10.1 fix: '${' opens a parameter-expansion frame (see above)
        if ch == "$" and i + 1 < n and text[i + 1] == "{":
            stack.append(("$", line))
            param_depth += 1
            i += 2
            continue
        if ch in _OPEN:
            stack.append((ch, line))
        elif ch in _CLOSE:
            if not stack:
                errors.append((line, "unmatched '%s' (nothing is open to "
                               "close)" % ch))
            else:
                op, op_line = stack.pop()
                if op == "$":          # a '${' parameter-expansion frame
                    param_depth -= 1
                    if ch != "}":
                        errors.append((line, "'%s' closes but '${' (line %d) "
                                      "is still open" % (ch, op_line)))
                elif _OPEN[op] != ch:
                    errors.append((line, "'%s' closes but '%s' (line %d) "
                                  "is still open" % (ch, op, op_line)))
        i += 1
    for op, op_line in stack:
        if op == "$":               # unclosed '${' reads clearer than '$'
            errors.append((op_line, "'${' opened here is never closed"))
        else:
            errors.append((op_line, "'%s' opened here is never closed" % op))
    if state == "block":
        warns.append((line, "block comment looks unterminated"))
    if state == "string":
        warns.append((line, "string looks unterminated (truncated file?)"))
    return errors, warns


def scan_delims(text, family="c"):
    """Public scanner: family-aware bracket balance with line numbers.
    Returns (errors, warns) as [(line, msg)]."""
    fam = _FAMILIES.get(family) or _FAMILIES["c"]
    if family == "shell":
        text, hung = _strip_heredocs(text)
        errors, warns = _walk(text, fam)
        if hung is not None:
            warns.append((hung, "heredoc looks unterminated "
                          "(no closing line)"))
        return errors, warns
    return _walk(text, fam)


# =====================================================================
# 2. MARKUP (HTML / XML / SVG / VUE / SVELTE) tag balance
# =====================================================================
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr",
              # svg self-contained regulars often seen unclosed
              "path", "circle", "rect", "line", "polyline", "polygon",
              "ellipse", "use", "stop"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9:-]*)((?:\"[^\"]*\"|'[^']*'"
                     r'|[^>"\'])*)(/?)>')
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_SCRIPT_RE = re.compile(r"<(script|style|textarea|title)\b[^>]*>.*?</\1\s*>",
                        re.IGNORECASE | re.DOTALL)


# v8.7: HTML5 OPTIONAL end tags - <ul><li>one<li>two</ul> is valid
# HTML, but the strict stack read the second <li> as nested and the
# healthy page got rejected. They auto-close like a browser does.
_HTML_OPTIONAL_END = ("li", "tr", "td", "th", "option", "dt", "dd",
                      "thead", "tbody", "tfoot",
                      # v8.11: <p> auto-closes on a sibling <p> and when a
                      # parent (</body>) closes - exactly like a browser.
                      # A <p> still open at END OF FILE stays an error
                      # (that strictness is pinned and kept).
                      "p")
# v8.11: the SVG "empty" regulars from _VOID_TAGS. In XML/SVG their
# explicit closer is legal (<path d="..."></path> is valid markup and
# common in generated icons) - the strict stack read it as a mismatch,
# rejected the icon AND the whole batch, and mis-popped <svg> so
# </svg> then errored too (two phantom errors per icon).
_SVG_EMPTY_TAGS = frozenset(("path", "circle", "rect", "line",
                             "polyline", "polygon", "ellipse",
                             "use", "stop"))


def scan_tags(text, protect=("script", "style")):
    """Stack-based tag matcher for markup languages. Returns
    (errors, warns) with line numbers. <script>/<style> bodies are
    protected (JS/CSS brackets are NOT tags)."""
    errors, warns = [], []
    # cut comments and protected raw-text elements first
    cut = _COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for m in _SCRIPT_RE.finditer(cut):
        body = m.group(0)
        inner = body[body.find(">") + 1: body.rfind("</")]
        # v8.10.1 fix: [\S\s] blanked NEWLINES too - an N-line inline
        # script collapsed to one line and every tag after it reported a
        # line N too small (the repair prompt then pointed at the wrong
        # lines). Blank only non-newline chars, like the comment cut does.
        clean = re.sub(r"[^\n]", " ", inner) if any(
            p in m.group(1).lower() for p in protect) else inner
        cut = cut[:m.start()] + body[:body.find(">") + 1] + clean + \
            body[body.rfind("</"):] + cut[m.end():]
    stack = []
    for m in _TAG_RE.finditer(cut):
        closing, name, self_close = m.group(1), m.group(2).lower(), m.group(4)
        line = cut.count("\n", 0, m.start()) + 1
        if name in ("!doctype", "?xml", "?php"):
            continue
        if self_close:
            continue
        if closing:
            # v8.11: an explicit closer of an SVG empty element is legal
            # XML - skip it exactly like the self-closed form
            if name in _SVG_EMPTY_TAGS:
                continue
            # v8.11: a stray explicit closer of an optional-end tag
            # ('<p>a<p>b</p></p>' - the sibling rule already closed the
            # first <p>) is rebuilt implicitly by the browser; only a
            # mismatched NON-optional closer stays an error
            if name in _HTML_OPTIONAL_END \
                    and not any(n == name for n, _l in stack):
                continue
            if not stack:
                errors.append((line, "closing </%s> with no matching open"
                               " tag" % name))
            else:
                # v8.7: a browser closes the open optional-end tags
                # implicitly when the parent closes - so does the stack.
                while len(stack) > 1 and stack[-1][0] != name \
                        and stack[-1][0] in _HTML_OPTIONAL_END:
                    stack.pop()
                op, op_line = stack.pop()
                if op != name:
                    errors.append((line, "</%s> closes but <%s> (line %d)"
                                   " is still open" % (name, op, op_line)))
        elif name not in _VOID_TAGS:
            if name in _HTML_OPTIONAL_END and stack \
                    and stack[-1][0] == name:
                stack.pop()          # same-name sibling auto-closes
            stack.append((name, line))
    for op, op_line in stack:
        errors.append((op_line, "<%s> opened here is never closed" % op))
    if text.lower().count("<!doctype") > 1:
        warns.append((1, "more than one doctype"))
    return errors, warns
# =====================================================================
# 3. COMMON-BUG PATTERNS - high-signal offline heuristics
# =====================================================================
# Every entry: (compiled regex, severity, message). They run on the RAW
# text (strings included on purpose - e.g. py2 print is wrong everywhere).
# High signal only: a noisy heuristic would block healthy batches.
def _c(*pairs):
    return [(re.compile(p, re.MULTILINE), sev, msg)
            for p, sev, msg in pairs]

_PATTERNS = {
    "python": _c(
        (r"^\s*print\s+[\"']", "error",
         "Python 2 print statement - wrap it: print(...)"),
        (r"^\s*except\s+\w+\s*,\s*\w+", "error",
         "Python 2 except syntax - use: except Type as name"),
        (r"def\s+\w+\([^)]*=\s*(\[\]|\{\})", "warn",
         "mutable default argument (shared between calls)"),
        (r"^\s*except\s*:", "warn", "bare except swallows everything"),
        (r"==\s*None\b", "warn", "use 'is None' instead of '== None'"),
    ),
    "javascript": _c(
        (r"\bwith\s*\(", "error", "'with' is forbidden in strict mode"),
        (r"[^=!<>]==[^=]", "warn", "loose equality '==' (prefer '===')"),
        (r"\bvar\s+\w+", "warn", "'var' has function scope (prefer let/const)"),
    ),
    "c": _c(
        (r"\bgets\s*\(", "error", "gets() is unsafe and removed from C11"),
        (r"\bif\s*\([^()]*?[A-Za-z0-9_)\]][ \t]*=[^=]", "warn",
         "assignment '=' inside an if-condition (meant '=='?)"),
    ),
    "go": _c(
        (r"fmt\.PrintIn\b", "error", "typo: fmt.Println (ln, not In)"),
        (r"\bpanic\s*\(\s*\"", "warn", "panic with a string literal in "
         "library code (prefer errors)"),
    ),
    "shell": _c(
        (r"^\s*else\s+if\b", "error", "bash uses 'elif', not 'else if'"),
        # v8.10.1 fix: \[+\S backtracked through '[[ ' and matched the
        # second bracket - the STANDARD bash idiom `if [[ -f x ]]` was a
        # blocking error even when `bash -n` ran clean. A single '['
        # followed by a non-space, non-'[' char is the actual defect.
        (r"\bif\s+\[(?![\[\s])", "error", "missing space after '[' (use '[ ... ')"),
        (r"\becho\s+\$\((?!\()", "warn", "echo $(...) - fine, but prefer "
         "printf for portability"),
    ),
    "ruby": _c(
        (r"\belse\s+if\b", "warn", "ruby uses 'elsif', not 'else if'"),
    ),
    "php": _c(
        (r"<\?(?!php|=)", "warn", "short open tag '<?' is unreliable - "
         "use '<?php'"),
    ),
    "rust": _c(
        (r"\bif\s+\w+\s*=\s*[^=]", "warn",
         "assignment inside an if-condition (meant '=='?)"),
    ),
    "java": _c(
        (r"\bString\s+\w+\s*==\s*[\"']", "warn",
         "String compared with '==' (use .equals())"),
    ),
    "sql": _c(
        (r",\s*(FROM|WHERE|GROUP|ORDER)\b", "warn",
         "trailing comma before a clause"),
    ),
}

# =====================================================================
# 4. EXTERNAL TOOL VALIDATORS - used ONLY when installed
# =====================================================================
# (tool, argv-template, exts, trust) - trust=full means ANY stderr is a
# syntax error (parse-only tools); filtered keeps only true syntax lines.
_TOOL_SPECS = {
    "node":  (["node", "--check", "@FILE@"],
              (".js", ".mjs", ".cjs"), "full"),
    "bash":  (["bash", "-n", "@FILE@"], (".sh", ".bash"), "full"),
    "php":   (["php", "-l", "@FILE@"], (".php",), "full"),
    "ruby":  (["ruby", "-c", "@FILE@"], (".rb",), "full"),
    "gofmt": (["gofmt", "-e", "-l", "@FILE@"], (".go",), "full"),
    "luac":  (["luac", "-p", "@FILE@"], (".lua",), "full"),
    "gcc":   (["gcc", "-fsyntax-only", "@FILE@"], (".c", ".h"), "filtered"),
    # v8.10.1 fix: the lookup key used to be "gxx" - shutil.which("gxx")
    # finds nothing on mainstream machines, so the C++ validator never ran
    # (the argv template clearly intends g++). The key stays "gxx" (tests /
    # cache keys); _which resolves the real binary names in order.
    "gxx":   (["g++", "-fsyntax-only", "@FILE@"],
              (".cpp", ".cc", ".cxx", ".hpp", ".hh"), "filtered"),
}
# gcc/gxx type-check too -> only true SYNTAX lines may reject a batch.
_SYNTAX_LINE_RE = re.compile(
    r"error:\s*(.*?(?:expected|syntax error|stray|unterminated|"
    r"missing terminating|extraneous|invalid preprocessing|"
    r"ISO C\+\+ forbids))",
    re.IGNORECASE)
# v8.7: "was not declared in this scope" left the list - it is a
# SEMANTIC error (a missing #include), not a syntax error. A generated
# .cpp one include short used to be hard-REJECTED pre-apply instead of
# getting one cheap repair round.

_tool_cache = {}
_tool_runs = [0]          # per-batch budget (reset by validate_batch)


def tools_available():
    """Which external validators exist on THIS machine (for /status)."""
    out = []
    for name, spec in sorted(_TOOL_SPECS.items()):
        if _which(name):
            out.append(name)
    return out


def _which(tool):
    if os.environ.get("NOVA_GUARDIAN_TOOLS", "") == "0":
        return None
    if tool not in _tool_cache:
        # v8.10.1 fix: "gxx" is a registry KEY, not a binary name - try the
        # real-world names too (conda/Nix ship gxx; distros ship g++ / c++).
        lookup = {"gxx": ("gxx", "g++", "c++")}.get(tool, (tool,))
        try:
            _tool_cache[tool] = next(
                (shutil.which(t) or "" for t in lookup if shutil.which(t)),
                "")
        except Exception:
            _tool_cache[tool] = ""
    return _tool_cache[tool] or None


def reset_tool_budget():
    _tool_runs[0] = 0


def _tool_check(tool, name, body):
    """Run one external parse-only validator. Returns [] when clean,
    [(0, first_error)] on syntax errors, None = tool/skipped."""
    spec = _TOOL_SPECS[tool]
    argv, exts, trust = spec[0], spec[1], spec[2]
    low = (name or "").lower()
    if not low.endswith(exts) or _tool_runs[0] >= MAX_TOOL_RUNS:
        return None
    path = _which(tool)
    if not path:
        return None
    _tool_runs[0] += 1
    suffix = os.path.splitext(low)[1] or ".txt"
    try:
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                         encoding="utf-8") as fh:
            fh.write(body[:MAX_GUARD_FILE_CHARS])
            tmp = fh.name
        try:
            # argv[0] is the tool NAME; the resolved absolute path goes
            # in its place, @FILE@ is the temp copy of the content
            cmd = [path] + [a.replace("@FILE@", tmp) for a in argv[1:]]
            # v8.10.1 fix: text=True without encoding decodes with the
            # LOCALE codec (cp1252 on Windows) and strict errors - a tool
            # echoing a Persian source line raised UnicodeDecodeError,
            # which the except swallowed and the tool verdict was lost.
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=TOOL_TIMEOUT)
            out = (p.stderr or "") + (p.stdout or "")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        return None                       # tool broken -> stay silent
    if p.returncode == 0:
        return []
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return [(0, tool + " failed without output (exit %d)" % p.returncode)]
    if trust == "full":
        # the parse-only tools never lie: first stderr line IS the error
        first = next((ln for ln in lines if "warning" not in ln.lower()),
                     lines[0])
        return [(0, "%s: %s" % (tool, first[:220]))]
    m = _SYNTAX_LINE_RE.search(out)
    return [(0, "%s: %s" % (tool, m.group(0)[:220]))] if m else []


# =====================================================================
# 5. THE LANGUAGE FLEET (sub-sub-agents) - every language, one registry
# =====================================================================
# profile: label / exts / family (scanner) / tool (optional external) /
# check (custom in-process fn) / brief (the sub-agent persona) /
# kb (offline knowledge). 'generic' catches everything unmapped.
def _py_check(name, body):
    import ast
    try:
        ast.parse(body)
        return []
    except SyntaxError as e:
        line = e.lineno or 0
        msg = e.msg or "syntax error"
        text = (e.text or "").strip()[:80]
        return [(line, "SyntaxError: %s%s" % (msg, (" -> " + text)
                                              if text else ""))]


def _json_check(name, body):
    if not body.strip():
        return []                 # an empty buffer passes (preapply parity)
    try:
        json.loads(body)
        return []
    except ValueError as e:
        return [(0, "invalid JSON: %s" % str(e)[:160])]


def _yaml_check(name, body):
    try:
        import yaml                      # optional dependency
        yaml.safe_load(body)
        return []
    except Exception:
        pass
    # offline floor: YAML forbids tabs in indentation - the one cheap
    # confident check without the library
    for i, ln in enumerate(body.splitlines(), 1):
        stripped = ln.lstrip(" ")
        if stripped.startswith("\t"):
            return [(i, "tab character in indentation (YAML forbids tabs)")]
    return []


def _toml_check(name, body):
    if not body.strip():
        return []
    try:
        import tomllib                   # py3.11+
        tomllib.loads(body)
        return []
    except Exception as e:
        try:
            msg = str(e).splitlines()[0][:160]
            line = 0
            m = re.search(r"line (\d+)", msg)
            if m:
                line = int(m.group(1))
            return [(line, "invalid TOML: %s" % msg)]
        except Exception:
            return [(0, "invalid TOML")]


def _html_check(name, body):
    errs, _warns = scan_tags(body)
    return errs


def _css_check(name, body):
    # string/comment aware brace balance via the c-family scanner
    # (CSS braces come in pairs like any code)
    errs, _w = scan_delims(body, "c")
    out = []
    for line, msg in errs:
        if "{" in msg or "}" in msg:
            out.append((line, "CSS " + msg))
    if out:
        return out
    # a stylesheet with zero rules is almost always the wrong content
    if not body.strip():
        return []
    ob = body.count("{")
    if ob == 0 and not re.search(r"@import|@charset", body):
        return [(1, "CSS: no rules found (is this the right content?)")]
    return []


def _looks_binary(body):
    """A sniff good enough for the gate: NUL bytes or mostly
    non-printable text -> not source code, skip it (a false reject on
    a font/asset file would block a whole healthy batch)."""
    sample = body[:8000]
    if not sample:
        return False
    if "\x00" in sample:
        return True
    printable = sum(1 for ch in sample if ch.isprintable()
                    or ch in "\n\r\t")
    return printable / len(sample) < 0.85


def _mk(label, exts, family="c", tool=None, check=None, brief=None, kb=()):
    return {"label": label, "exts": tuple(exts), "family": family,
            "tool": tool, "check": check, "brief": brief or
            "You are the %s review sub-agent of Nova's code guardian "
            "fleet. Find REAL bugs only: syntax errors, missing imports, "
            "undefined names, wrong API usage, obvious logic errors. "
            "Ignore style." % label, "kb": tuple(kb)}


LANGS = {
    "python": _mk("Python", (".py", ".pyw", ".pyi"), family="py",
                  check=_py_check,
                  kb=["print is a function: print(x) - not print x",
                      "except handlers: except ValueError as e:",
                      "indentation IS syntax - never mix tabs and spaces",
                      "mutable defaults (def f(x=[])) are shared between calls"]),
    "javascript": _mk("JavaScript", (".js", ".mjs", ".cjs"), family="c",
                      tool="node",
                      kb=["=== for comparison, == coerces types",
                          "every ( [ { must close; check the LAST line too",
                          "const/let over var; async functions need await"]),
    "typescript": _mk("TypeScript", (".ts", ".tsx"), family="c",
                      kb=["types live in annotations - a wrong type name "
                          "breaks compilation even when syntax is fine",
                          "interfaces are erased at runtime: import paths "
                          "must exist at build time"]),
    "jsx": _mk("React JSX", (".jsx",), family="c",
               kb=["JSX: every tag closes, class= is className=",
                   "one root element per return (or a fragment <></>)"]),
    "html": _mk("HTML", (".html", ".htm"), family="c", check=_html_check,
                kb=["void tags (img/br/input/meta/link) need no closer",
                    "quotes inside attributes must match their own kind"]),
    "css": _mk("CSS", (".css",), family="c", check=_css_check,
               kb=["every rule: selector { prop: value; }",
                   "a missing ';' or '}' silently kills the next rule"]),
    "json": _mk("JSON", (".json",), family="plain", check=_json_check,
                kb=["no trailing commas, keys need double quotes",
                    "JSON has no comments"]),
    "yaml": _mk("YAML", (".yaml", ".yml"), family="plain", check=_yaml_check,
                kb=["indentation with SPACES only - tabs are illegal",
                    "a missing space after 'key:' changes the type"]),
    "toml": _mk("TOML", (".toml",), family="plain", check=_toml_check,
                kb=["sections [table], keys = values, strings double-quoted"]),
    "xml": _mk("XML", (".xml", ".svg"), family="c", check=_html_check,
               kb=["every tag closes or self-closes (<tag/>)",
                   "attribute values must be quoted"]),
    "shell": _mk("Bash / Shell", (".sh", ".bash", ".zsh"), family="shell",
                 tool="bash",
                 kb=["'elif' not 'else if'; spaces around '[' and ']'",
                     "quote variables: \"$var\" survives spaces",
                     "heredoc bodies are free-form (<<EOF ... EOF)"]),
    "c": _mk("C", (".c", ".h"), family="c", tool="gcc",
             kb=["every statement ends with ';'",
                 "headers must be included before use"]),
    "cpp": _mk("C++", (".cpp", ".cc", ".cxx", ".hpp", ".hh"), family="c",
               tool="gxx",
               kb=["std:: names need #include <...> or using",
                   "templates fail loudly at instantiation - check <>"]),
    "csharp": _mk("C#", (".cs",), family="c",
                  kb=["namespaces, classes and methods all use { }",
                      "statements end with ';'"]),
    "java": _mk("Java", (".java",), family="c",
                kb=["file name MUST equal the public class name",
                    "every statement ends with ';'; main signature: "
                    "public static void main(String[] args)"]),
    "kotlin": _mk("Kotlin", (".kt", ".kts"), family="c",
                  kb=["'fun main()' is the entry; val immutable, var mutable"]),
    "swift": _mk("Swift", (".swift",), family="c",
                 kb=["no ';' needed; optionals unwrap with if let / guard"]),
    "go": _mk("Go", (".go",), family="c", tool="gofmt",
              kb=["unused imports/variables are COMPILE ERRORS in Go",
                  "fmt.Println - ln for line, not In"]),
    "rust": _mk("Rust", (".rs",), family="rust",
                kb=["variables immutable by default - 'let mut' to mutate",
                    "every expression block returns a value; semicolons "
                    "end statements, not blocks"]),
    "php": _mk("PHP", (".php",), family="c", tool="php",
               kb=["variables start with $; blocks use { }",
                   "'<?php' opener, optional '?>' closer"]),
    "ruby": _mk("Ruby", (".rb",), family="c", tool="ruby",
                kb=["blocks end with 'end' (def/if/do/class...)",
                    "'elsif' not 'else if'"]),
    "lua": _mk("Lua", (".lua",), family="sql", tool="luac",
               kb=["blocks end with 'end'; 'then' after if/elseif conditions",
                   "'~=' is not-equal (not '!=')",
                   "comments start with '--' (block: --[[ ... ]])"]),
    "perl": _mk("Perl", (".pl", ".pm"), family="py",
                kb=["statements end with ';'; scalars use $, arrays@"]),
    "sql": _mk("SQL", (".sql",), family="sql",
               kb=["strings in single quotes; identifiers in double/`back`",
                   "every SELECT needs matching FROM/JOIN structure"]),
    "r": _mk("R", (".r", ".R"), family="py",
             kb=["assignment '<-' preferred; parentheses around if conditions"]),
    "dart": _mk("Dart", (".dart",), family="c",
                kb=["flutter widgets nest with trailing commas; every "
                    "constructor call closes its parens"]),
    "scala": _mk("Scala", (".scala",), family="c",
                 kb=["braces or indentation both legal but pick one"]),
    "vue": _mk("Vue SFC", (".vue",), family="c", check=_html_check,
               kb=["one <template>, one <script>, many <style> blocks "
                   "per file"]),
    "svelte": _mk("Svelte", (".svelte",), family="c", check=_html_check,
                  kb=["<script> at top, markup below, <style> at bottom"]),
    "markdown": _mk("Markdown", (".md", ".markdown"), family="plain",
                    check=None,
                    kb=["link brackets: [text](url) come in pairs"]),
    "generic": _mk("Code", (), family="c",
                   brief="You are a code review sub-agent of Nova's "
                         "code guardian fleet. Find REAL bugs only: "
                         "syntax errors, undefined names, wrong API "
                         "usage, obvious logic errors. Ignore style.",
                   kb=["balanced brackets are the universal floor: every "
                       "( [ { needs its closer"]),
}

_EXT_MAP = {}
for _lid, _prof in LANGS.items():
    for _ext in _prof["exts"]:
        _EXT_MAP[_ext] = _lid


def resolve_lang(name):
    """Language id for a file name ('generic' when unmapped)."""
    low = (name or "").lower()
    if low.endswith(".r") and not low.endswith((".for",)):
        return "r"
    return _EXT_MAP.get(low[low.rfind("."):] if "." in low else low,
                        "generic")


def lang_count():
    return len([k for k in LANGS if k != "generic"])


# =====================================================================
# 6. validate() - the deterministic heart of every sub-sub-agent
# =====================================================================
def validate(name, body):
    """Validate ONE in-memory file. Returns
    {"file", "lang", "label", "errors": [(line, msg)], "warns": [...],
     "via": [str, ...]}  - via lists which validators actually ran.
    Blocking errors ONLY for KNOWN languages; 'generic' and markdown
    problems stay advisory (never block a healthy batch on a guess)."""
    lang = resolve_lang(name)
    prof = LANGS[lang]
    body = str(body or "")
    errors, warns, via = [], [], []
    if _looks_binary(body):
        return {"file": name, "lang": lang, "label": prof["label"],
                "errors": [], "warns": [], "via": ["skipped (binary)"]}
    blocking = lang not in ("generic", "markdown")
    if len(body) > MAX_GUARD_FILE_CHARS:
        via.append("structure-only (file too big for full check)")
        errs, _w = scan_delims(body, prof["family"])
        for ln, msg in errs[:20]:
            (errors if blocking else warns).append((ln, msg))
        return {"file": name, "lang": lang, "label": prof["label"],
                "errors": errors, "warns": warns, "via": via}
    # 1) in-process parser (ast / json / yaml / toml / tags / css)
    if prof["check"] is not None:
        try:
            found = prof["check"](name, body) or []
        except Exception:
            found = []
        for line, msg in found:
            (errors if blocking else warns).append((line, msg))
        via.append("parser:" + lang)
    # 2) external parse-only tool (node/bash/php/ruby/gofmt/luac/gcc)
    tool_clean = False
    if prof["tool"] and os.environ.get("NOVA_GUARDIAN_TOOLS", "") != "0":
        res = _tool_check(prof["tool"], name, body)
        if res is not None:
            # v8.7: a real parser RAN and found the file syntactically
            # clean - the delimiter heuristic must not get a second,
            # noisier vote (a js regex literal or template trick used
            # to turn a node --check-clean file into a false REJECT).
            tool_clean = not res
            for ln, msg in res:
                (errors if blocking else warns).append((ln, msg))
            via.append("tool:" + prof["tool"])
    # 3) the structure floor - only when no real parser found anything
    if not errors and not tool_clean \
            and not (prof["check"] and lang != "css"):
        errs, _w = scan_delims(body, prof["family"])
        for ln, msg in errs:
            (errors if blocking else warns).append((ln, msg))
        via.append("structure:" + prof["family"])
    # 4) high-signal pattern heuristics (always advisory)
    pats = _PATTERNS.get(lang)
    if pats is None and lang not in ("python", "javascript", "html",
                                     "json", "css", "markdown",
                                     "generic"):
        pats = _PATTERNS.get("c")     # C-family siblings share basics
    for rx, sev, msg in (pats or ()):
        try:
            m = rx.search(body)
        except Exception:
            continue
        if m:
            line = body.count("\n", 0, m.start()) + 1
            target = errors if (sev == "error" and blocking) else warns
            target.append((line, msg))
    if lang == "markdown":
        errors = []                    # prose never blocks a batch
    return {"file": name, "lang": lang, "label": prof["label"],
            "errors": errors[:20], "warns": warns[:20], "via": via}


# =====================================================================
# 7. SETTINGS - per-workspace .nova/guardian.json (ctxengine pattern)
# =====================================================================
def settings_path(ws):
    return Path(ws) / ".nova" / SETTINGS_FILE


def _valid_fields(obj):
    """ONLY the valid keys of `obj` survive - a hand-edited file can
    never poison the stored settings."""
    out = {}
    if not isinstance(obj, dict):
        return out
    for key in ("on", "model", "web", "reject_syntax"):
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
        _valid = _valid_fields(saved)
        d.update(_valid)
        # v8.11: custom means the user actually saved valid fields - a
        # hand-edited file with zero valid keys used to claim custom
        # (the v8.7 law nova_vision already mirrors)
        d["custom"] = bool(_valid)
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
    broken file must never silently disable the guardian)."""
    if not isinstance(cfg, dict):
        return DEFAULTS.get(key, True)
    return bool(cfg.get(key, DEFAULTS.get(key, True)))


# =====================================================================
# 8. THE DEDICATED WEBSEARCH - enrichment, never a dependency
# =====================================================================
# The fleet's OWN channel: queries go out with a "guardian:" cache
# prefix (a SEPARATE namespace - /search's cache is never mixed in),
# tiny budgets, and a hard contract: this function NEVER RAISES and
# NEVER blocks correctness. No internet -> the built-in KB answers.
_WEB_DIGEST_MAX = 900


def knowledge_note(lang):
    """The OFFLINE knowledge base - the fleet's floor when the internet
    is gone. Shipped in-module, so correctness never depends on a
    connection."""
    prof = LANGS.get(lang) or LANGS["generic"]
    lines = list(prof["kb"])
    if lang != "markdown" and lang != "generic":
        lines.append("universal floor: every ( [ { needs its closer - "
                     "check the file END too")
    return "\n".join("- " + ln for ln in lines[:6])


def web_lookup(query, lang=None, max_results=3):
    """The guardian's dedicated websearch. Returns
    {"ok", "online", "source", "digest"} - ok=False always pairs with
    the offline KB digest so callers NEVER need to branch on network
    state. Best-effort end to end: every failure mode degrades to
    offline knowledge. HARD wall-clock budget (NOVA_GUARDIAN_WEB_TIMEOUT,
    default 8 s) so a dead network can never hang the apply path, and
    NOVA_GUARDIAN_WEB=0 skips the internet entirely (tests / air-gapped
    machines) - the built-in KB answers instead."""
    out = {"ok": False, "online": False, "source": "offline-kb",
           "digest": knowledge_note(lang) if lang else ""}
    if not str(query or "").strip():
        return out
    if _ns is None or os.environ.get("NOVA_GUARDIAN_WEB", "") == "0":
        return out
    q = " ".join(str(query).split())[:200]
    try:
        hit = _ns.cache_get("guardian:" + q.lower())
        if isinstance(hit, dict) and hit.get("digest"):
            return {"ok": True, "online": True, "source": "cache",
                    "digest": str(hit["digest"])[:_WEB_DIGEST_MAX]}
    except Exception:
        pass
    try:
        # v8.7: cap ABOVE too - NOVA_GUARDIAN_WEB_TIMEOUT=inf used to
        # make t.join(inf) hang the whole apply path (the "hard" budget
        # had no ceiling), so one bad env value froze the gate.
        budget = min(15.0, _env_float("NOVA_GUARDIAN_WEB_TIMEOUT", 8.0))
        box = {}

        def _fetch():
            try:
                box["res"] = _ns.web_search(
                    "%s common syntax errors current best practices" % q,
                    max_results=max_results, use_cache=False)
            except Exception as e:
                box["err"] = e

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(max(1.0, budget))
        res = box.get("res")
        if res is None:
            return out            # timed out or failed -> offline KB
        blocks = []
        for r in (res or [])[:max_results]:
            title = str(r.get("title") or "")[:90]
            snippet = " ".join(str(r.get("snippet") or "").split())[:220]
            if title or snippet:
                blocks.append("* %s - %s" % (title, snippet))
        if not blocks:
            return out
        digest = "\n".join(blocks)[:_WEB_DIGEST_MAX]
        out.update(ok=True, online=True, source="web", digest=digest)
        try:
            _ns.cache_put("guardian:" + q.lower(),
                          {"digest": digest, "lang": lang})
        except Exception:
            pass                       # cache is best-effort
        return out
    except Exception:
        return out                     # offline: the KB digest stays


# =====================================================================
# 9. THE SUPERVISOR - review a whole batch (deterministic + fleet)
# =====================================================================
def parse_agent_json(text):
    """Tolerant JSON-object extraction from a model answer (the same
    bracket-budget philosophy as nova_subagent.parse_task_list)."""
    if not text:
        return None
    text = text[:20000]
    # v8.11: bounded attempt budget - a derailed model answer that is one
    # giant run of '{' scanned 8000 chars PER BRACE (~10 s frozen apply
    # path, twice per post-apply review). Same cap as nova_subagent.
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


def _agent_review_one(item, web_enrich, extra_note):
    """One sub-sub-agent (model) review of one file. `item` is
    (name, body, lang_id). Returns a findings dict; NEVER raises."""
    name, body, lang = item
    prof = LANGS.get(lang) or LANGS["generic"]
    code = body[:MAX_AGENT_CODE_CHARS]
    prompt = ("%s Answer ONLY compact JSON, no markdown:\n"
              '{"syntax_ok": true|false, "bugs": [{"line": <int>, '
              '"severity": "error"|"warn", "msg": "<short>"}]}\n'
              "Max 8 bugs. Clean code -> {\"syntax_ok\": true, "
              '"bugs": []}\n\n' % prof["brief"])
    if extra_note:
        prompt += "KNOWN PROBLEMS from the deterministic gate (verify " \
                  "and find MORE):\n%s\n\n" % extra_note
    if web_enrich:
        prompt += ("REFERENCES (%s):\n%s\n\n"
                   % ("fresh from the web" if web_enrich.get("online")
                      else "offline knowledge base",
                      web_enrich.get("digest") or "-"))
    prompt += "CODE (%s):\n```\n%s\n```" % (name, code)

    def run(chat_fn):
        ans = chat_fn(prompt)
        data = parse_agent_json(ans or "")
        if not isinstance(data, dict):
            return []
        bugs = data.get("bugs")
        if not isinstance(bugs, list):
            return []
        out = []
        for b in bugs[:8]:
            if not isinstance(b, dict):
                continue
            msg = str(b.get("msg") or "").strip()[:220]
            if not msg:
                continue
            try:
                line = int(b.get("line") or 0)
            except (TypeError, ValueError):
                line = 0
            sev = "warn"
            if str(b.get("severity") or "").lower() == "error":
                sev = "warn"           # model errors stay advisory pre-apply
            out.append((line, "[agent] " + msg, sev))
        return out
    return run


def review_batch(files, chat_fn=None, cfg=None, web_on=True,
                 edit_bodies=None):
    """THE SUPERVISOR'S ENTRY. files/edit_bodies: [(name, content)].
    1) deterministic pass over EVERY file (always, offline, fast)
    2) verdict reject when any deterministic error (and reject_syntax)
    3) MODEL layer: up to MAX_AGENT_FILES sub-sub-agent reviews in
       PARALLEL on the local brain (only when chat_fn is provided)
    4) the dedicated websearch enriches the agent prompts (web) with
       the offline KB as the no-internet fallback
    Returns a report dict; NEVER raises for content problems."""
    cfg = cfg if isinstance(cfg, dict) else dict(DEFAULTS)
    items = [it for it in (list(files or []) + list(edit_bodies or []))
             if it and it[0]][:MAX_BATCH_FILES]
    reset_tool_budget()
    det = []
    for name, body in items:
        try:
            det.append(validate(name, body))
        except Exception as e:          # the gate must never crash apply
            det.append({"file": name, "lang": "generic",
                        "label": "Code",
                        "errors": [], "warns": [],
                        "via": ["validator error: %s" % str(e)[:80]]})
    rejects = [d for d in det if d["errors"]] \
        if enabled(cfg, "reject_syntax") else []
    soft = [d for d in det if not d["errors"] and d["warns"]]
    report = {"files": det, "rejects": rejects, "warns": soft,
              "agents": [], "online": False, "model_used": False,
              "verdict": "pass"}
    if rejects:
        report["verdict"] = "reject"
        return report
    if soft:
        report["verdict"] = "warn"
    # ---- the MODEL layer (sub-sub-agents in parallel) ------------------
    if chat_fn is None or not enabled(cfg, "model") or not items:
        return report
    pool = list(items)
    # prefer files that already drew warnings, then the biggest ones
    warned_names = {d["file"] for d in soft}
    pool.sort(key=lambda it: (it[0] not in warned_names, -len(it[1])))
    picks = pool[:MAX_AGENT_FILES]
    langs_seen = []
    for name, _body in picks:
        lid = resolve_lang(name)
        if lid not in langs_seen:
            langs_seen.append(lid)
    # dedicated websearch: at most MAX_WEB_LOOKUPS per review, ONLY to
    # enrich prompts - correctness already stood without it
    enrich = {}
    if web_on and enabled(cfg, "web"):
        for lid in langs_seen[:MAX_WEB_LOOKUPS]:
            enrich[lid] = web_lookup("%s language" % lid, lang=lid)
            if enrich[lid].get("online"):
                report["online"] = True
    tasks = [(n, b, resolve_lang(n)) for n, b in picks]
    import nova_subagent as fleet

    def worker(task):
        _name, _body, lid = task
        _runner = _agent_review_one(task, enrich.get(lid), None)
        return _runner(chat_fn)

    try:
        results = fleet.run_parallel(
            tasks, worker, max_parallel=min(len(tasks), MAX_AGENT_FILES))
    except Exception:
        return report
    report["model_used"] = True
    for task, res, err in results:
        name = task[0]
        if err:
            report["agents"].append({"file": name, "findings": [],
                                     "error": str(err)[:160]})
            continue
        findings = [(ln, msg) for ln, msg, _sev in (res or [])]
        report["agents"].append({"file": name, "findings": findings,
                                 "error": None})
        if findings:
            report["verdict"] = "warn"
    return report


def repair_prompt(report):
    """The supervisor's message back to the generator model: exact
    problems, exact protocol, nothing written to disk yet."""
    rejects = report.get("rejects") or []
    if not rejects:
        return ""
    lines = ["CODE GUARDIAN: %d file(s) failed the syntax validation - "
             "NOTHING was written to disk. Fix EXACTLY these problems "
             "and re-output the COMPLETE corrected file(s) with the "
             "=== FILE: path === ... === END === protocol (or === "
             "EDIT: === hunks for small changes):" % len(rejects)]
    for d in rejects[:MAX_BATCH_FILES]:
        lines.append("")
        lines.append("=== %s (%s) ===" % (d["file"], d["label"]))
        for line, msg in d["errors"][:10]:
            lines.append("- line %s: %s" % (line or "?", msg))
        for line, msg in d["warns"][:4]:
            lines.append("- line %s (verify): %s" % (line or "?", msg))
    lines.append("")
    lines.append("Rules: output every fixed file in THIS one answer; "
                 "keep everything else identical; end with the Run:/"
                 "Preview: line.")
    return "\n".join(lines)


def findings_summary(report):
    """Flat [(file, line, msg)] for feedback notes / web events."""
    out = []
    for d in report.get("files") or []:
        for line, msg in d.get("errors") or []:
            out.append((d["file"], line, msg))
    for d in report.get("warns") or []:
        for line, msg in d.get("warns") or []:
            out.append((d["file"], line, "warn: " + msg))
    for a in report.get("agents") or []:
        for line, msg in a.get("findings") or []:
            out.append((a["file"], line, msg))
    return out[:MAX_FINDINGS]


# =====================================================================
# 10. /guardian audit - the fleet sweeps the WHOLE workspace
# =====================================================================
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".nova",
                ".nova_backups", ".venv", "venv", ".idea", ".vscode",
                "dist", "build", ".pytest_cache"}


def audit_workspace(ws, max_files=200, exts=None):
    """Deterministic sweep over every file the fleet knows. Returns
    [{"file", "lang", "label", "errors", "warns"}] for PROBLEM files
    only ([] = the workspace is clean)."""
    root = Path(ws)
    if not root.is_dir():
        return []
    wanted = set(exts or (e for p in LANGS.values() for e in p["exts"]))
    found, out = [], []
    reset_tool_budget()
    try:
        # v8.12: os.walk with in-place pruning - sorted(rglob("*"))
        # materialized and walked the ENTIRE tree (including .git and
        # node_modules) before the cap could ever apply; the sweep now
        # prunes ignored directories DURING the walk and sorts the
        # capped result afterwards (deterministic across calls; when
        # the cap bites, WHICH files are kept may differ from v8.11's
        # sort-the-world order - the walk is the point, not the order).
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
            for fname in sorted(filenames):
                if len(found) >= max_files:
                    break
                p = Path(dirpath) / fname
                if p.suffix.lower() not in wanted:
                    continue
                try:
                    if not p.is_file():
                        continue
                except OSError:
                    continue
                found.append(p)
            if len(found) >= max_files:
                break
        found.sort()
        for p in found:
            # v8.7: per-file try - one unreadable/odd file used to abort
            # the WHOLE sweep via the outer except (silent partial scan).
            try:
                body = p.read_text(encoding="utf-8",
                                   errors="replace")
                rel = p.relative_to(root).as_posix()
                r = validate(rel, body)
            except OSError:
                continue
            except Exception:
                continue
            if r["errors"] or r["warns"]:
                out.append(r)
    except Exception:
        pass
    return out
