#!/usr/bin/env python3
# =====================================================================
#  Nova Code - colored diff & hunk-by-hunk review (v5.0)
#
#  Before Nova writes anything, the user can SEE exactly what will
#  change - in the terminal as ANSI-colored unified diff lines, in the
#  web face as structured data - and approve or reject EACH hunk of an
#  === EDIT: === block independently.
#
#  Reviewing is per-hunk stateful: accepting hunk 1 changes the
#  intermediate text, so hunk 2's context is recomputed against the
#  already-accepted result. A hunk whose SEARCH no longer matches the
#  intermediate exactly once is auto-rejected with a reason instead of
#  corrupting the file.
#
#  Pure standard library (difflib + regex). No nova.py import: the
#  interactive I/O functions are INJECTED (ask/print/color), so tests
#  can drive the whole flow without a terminal.
# =====================================================================
import difflib
import re

MAX_DIFF_LINES = 120       # terminal diff preview cap (RAM/screen safety)
CONTEXT_LINES = 2          # context lines around a hunk preview


# --------------------------------------------------------------- plain diffs
def unified_diff(rel, old, new, max_lines=MAX_DIFF_LINES):
    """difflib unified diff as a plain list of lines (no colors)."""
    old_l = str(old or "").splitlines()
    new_l = str(new or "").splitlines()
    lines = list(difflib.unified_diff(old_l, new_l,
                                      fromfile="a/" + rel, tofile="b/" + rel,
                                      lineterm=""))
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["... (diff truncated, %d more lines)"
                                     % (len(lines) - max_lines)]
    return lines


def paint(lines, color_fn=None):
    """ANSI color for diff lines: additions green, removals red, hunk
    headers cyan, file headers bold. `color_fn(code, text)` is injected
    so the caller controls whether colors are even on."""
    if color_fn is None:
        return "\n".join(lines)
    out = []
    for ln in lines:
        if ln.startswith("+++") or ln.startswith("---"):
            out.append(color_fn("\033[1m", ln))
        elif ln.startswith("@@"):
            out.append(color_fn("\033[96m", ln))
        elif ln.startswith("+"):
            out.append(color_fn("\033[92m", ln))
        elif ln.startswith("-"):
            out.append(color_fn("\033[91m", ln))
        else:
            out.append(ln)
    return "\n".join(out)


def new_file_preview(rel, body, max_lines=24):
    """What 'new file' looks like in the review: head lines + a count."""
    lines = str(body or "").splitlines()
    head = lines[:max_lines]
    more = len(lines) - len(head)
    out = [f"NEW FILE {rel} (+{len(lines)} lines)"]
    out += ["  " + ln for ln in head]
    if more > 0:
        out.append(f"  ... (+{more} more lines)")
    return out


def flex_match(hay, needle):
    """v6.8.3 - whitespace-tolerant SEARCH matching (the #1 reason small
    models' === EDIT: === blocks get refused: their SEARCH differs from
    the file by trailing spaces or indentation drift).
    Falls back to a LINE-LEVEL match that ignores leading AND trailing
    whitespace on every line (strip). Returns (start, end) char span of
    the UNIQUE match, or None. Exact matching stays the caller's fast
    path; an ambiguous (multi-hit) or absent match is None - never a
    guess. The span always points at the REAL file lines, so the
    replacement lands on the file's own indentation."""
    if not needle:
        return None
    n_lines = needle.split("\n")
    had_nl = False
    if len(n_lines) > 1 and n_lines[-1] == "":
        n_lines.pop()          # a trailing newline just means 'up to EOL'
        had_nl = True
    if not n_lines or not hay:
        return None
    n_r = [ln.strip() for ln in n_lines]
    h_lines = hay.split("\n")
    if len(n_lines) > len(h_lines):
        return None
    h_r = [ln.strip() for ln in h_lines]
    # char offset where each hay line starts
    offs = [0]
    for ln in h_lines:
        offs.append(offs[-1] + len(ln) + 1)   # +1 for the \n
    hits = []
    for i in range(len(h_lines) - len(n_lines) + 1):
        if h_r[i:i + len(n_lines)] == n_r:
            hits.append(i)
            if len(hits) > 1:
                return None       # ambiguous - refuse, like exact mode
    if not hits:
        return None
    i = hits[0]
    start = offs[i]
    if i + len(n_lines) >= len(h_lines):
        end = len(hay)            # the match runs to EOF
    else:
        end = offs[i + len(n_lines)] - (0 if had_nl else 1)
    return (start, end)


def hunk_preview(cur, search, replace, context=CONTEXT_LINES):
    """Colored-ready preview of ONE hunk against the CURRENT intermediate
    text: ['-old', '+new'] lines with a little context. Returns
    (lines, found_once). Never raises on pathological input.
    v6.8.3: when the exact match fails, the rstrip-tolerant flex_match()
    is tried so a preview still renders for whitespace-drifted hunks."""
    span = None
    try:
        n = cur.count(search)
    except Exception:
        return (["(hunk preview failed)"], False)
    if n == 1:
        pos = cur.find(search)
    else:
        # n == 0 -> try the tolerant match; n > 1 stays ambiguous
        span = flex_match(cur, search) if n == 0 else None
        if span is None:
            return ([f"(SEARCH matches {n} times in the current intermediate "
                     "state - cannot preview safely)"], False)
        pos = span[0]
    before = cur[:pos].splitlines()
    after_tail = cur[pos + len(search):].splitlines() if span is None \
        else cur[span[1]:].splitlines()
    old_l = cur[pos:span[1]].splitlines() if span is not None \
        else search.splitlines()
    new_l = replace.splitlines()
    ctx_b = before[-context:]
    ctx_a = after_tail[:context]
    lines = []
    for ln in ctx_b:
        lines.append("  " + ln)
    for ln in old_l:
        lines.append("- " + ln)
    for ln in new_l:
        lines.append("+ " + ln)
    for ln in ctx_a:
        lines.append("  " + ln)
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + ["... (truncated)"]
    return (lines, True)


# --------------------------------------------------------------- hunk engine
def apply_hunks(original, hunks):
    """Per-hunk tolerant application (used ONLY by the review path where
    the user explicitly picked hunks). Returns (text, applied, problems):
      applied  = [(search, replace)] that matched exactly once, in order
      problems = [(index1based, reason)] for the rest
    The normal apply path keeps prepare_edits()'s stricter all-or-nothing
    per-file rule; this function is the reviewed/relaxed variant.
    v6.8.3: a SEARCH that fails EXACTLY gets one rstrip-tolerant retry
    (flex_match) - trailing-space / indentation drift no longer kills
    the hunk; an ambiguous match is still refused."""
    cur = original
    applied, problems = [], []
    for i, (search, replace) in enumerate(hunks, 1):
        try:
            n = cur.count(search)
        except Exception:
            n = 0
        if n == 1:
            cur = cur.replace(search, replace, 1)
            applied.append((search, replace))
            continue
        if n > 1:
            problems.append((i, f"SEARCH matches {n} times - ambiguous"))
            continue
        span = flex_match(cur, search)
        if span is None:
            problems.append((i, "SEARCH not found in the current file state"))
            continue
        cur = cur[:span[0]] + replace + cur[span[1]:]
        applied.append((search, replace))
    return (cur, applied, problems)


def review_hunks(original, hunks, ask_fn, print_fn, color_fn=None):
    """Interactive per-hunk review for ONE file's === EDIT: === block.
    ask_fn(prompt) -> str ('' also accepted = yes, web-safe default);
    print_fn(str) renders; color_fn optional (see paint).
    Returns (accepted_hunks, rejected_notes, final_text)."""
    cur = original
    accepted = []
    notes = []
    total = len(hunks)
    for i, (search, replace) in enumerate(hunks, 1):
        if total > 1:
            print_fn(f"--- hunk {i}/{total} ---")
        lines, ok = hunk_preview(cur, search, replace)
        print_fn(paint(lines, color_fn))
        if not ok:
            notes.append(f"hunk {i}: preview impossible - rejected")
            continue
        ans = (ask_fn(f"Apply hunk {i}/{total}? [Y/n/a(ll)/q(uit)]: ") or "").strip().lower()
        if ans in ("q", "quit", "stop"):
            print_fn("(review stopped - remaining hunks rejected)")
            break
        if ans in ("a", "all"):
            # apply this and ALL remaining valid hunks without more prompts
            rest = [(search, replace)] + list(hunks)[i:]
            text, applied, problems = apply_hunks(cur, rest)
            accepted.extend(applied)
            for j, reason in problems:
                notes.append(f"hunk {i + j - 1}: {reason}")
            cur = text
            break
        if ans in ("n", "no"):
            notes.append(f"hunk {i}: rejected by user")
            continue
        # default = yes
        text, applied, problems = apply_hunks(cur, [(search, replace)])
        if applied:
            cur = text
            accepted.append((search, replace))
        else:
            notes.append(f"hunk {i}: {problems[0][1] if problems else 'failed'}")
    return (accepted, notes, cur)


# --------------------------------------------------------------- commit-label
def summarize_changes(files_new, files_edited, limit=3):
    """Short human string for snapshot notes / commit messages."""
    parts = []
    if files_new:
        parts.append("new: " + ", ".join(files_new[:limit])
                     + ("..." if len(files_new) > limit else ""))
    if files_edited:
        parts.append("edited: " + ", ".join(files_edited[:limit])
                     + ("..." if len(files_edited) > limit else ""))
    return "; ".join(parts) if parts else "no file changes"


# --------------------------------------------------------------- v6.8: unified patch
# Models often answer in classic `diff -u` / `git diff` form. The
# SEARCH/REPLACE hunk protocol stays the default (it is far more robust
# with tiny models), but a REAL unified patch can now be applied too:
# parse_patch() -> per-file hunks, apply_patch() -> tolerant context
# matching (exact first, then fuzzy on trimmed lines), never partial
# writes: the caller decides what to do with the problems list.
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _strip_ab(p):
    """'a/rel' / 'b/rel' -> 'rel' (workspace-relative); '/dev/null' and
    quoted names handled too."""
    p = (p or "").strip().strip('"').strip("'")
    if p.startswith(("a/", "b/")):
        p = p[2:]
    return p.replace("\\", "/").strip()


def parse_patch(text):
    """Parse a unified diff into {path: [(old_start, old_lines,
    new_start, new_lines)]}. v6.8.1: hunks consume EXACTLY the line
    counts from their @@ header before the next header/file is accepted -
    a deleted line like '-- sql comment' can then never be mistaken for
    a new file header. Returns (files, problems)."""
    files = {}
    problems = []
    cur_path = None
    cur = None
    h = None          # current hunk dict
    old_left = 0      # lines still expected for the hunk's OLD side
    new_left = 0      # ... and NEW side
    for raw in str(text or "").splitlines():
        if h is not None and (old_left or new_left):
            # inside a hunk body: header syntax is CONTENT here
            if raw.startswith("+"):
                h["new"].append(raw[1:])
                new_left -= 1
            elif raw.startswith("-"):
                h["old"].append(raw[1:])
                old_left -= 1
            elif raw.startswith("\\"):
                pass  # "\ No newline at end of file"
            elif raw.startswith(" "):
                h["old"].append(raw[1:])
                h["new"].append(raw[1:])
                old_left -= 1
                new_left -= 1
            elif raw == "":
                h["old"].append("")
                h["new"].append("")
                old_left -= 1
                new_left -= 1
            else:
                # malformed line inside a counted hunk - record, bail out
                problems.append("unexpected line inside hunk: " + raw[:60])
                h = None
            continue
        if raw.startswith("--- "):
            cur_path = _strip_ab(raw[4:])
            cur = None
            h = None
            continue
        if raw.startswith("+++ "):
            newp = _strip_ab(raw[4:])
            if cur_path in (None, "/dev/null", ""):
                cur_path = newp
            cur = files.setdefault(cur_path, [])
            h = None
            continue
        if raw.startswith("@@"):
            m = _HUNK.match(raw)
            if not m or cur is None:
                problems.append("bad hunk header: " + raw[:60])
                cur = None
                h = None
                continue
            h = {"old_start": int(m.group(1)),
                 "old": [], "new_start": int(m.group(3)),
                 "new": []}
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_left = int(m.group(4)) if m.group(4) is not None else 1
            cur.append(h)
            continue
        # everything before the first header is prelude - harmless
    files = {p: [(x["old_start"], x["old"], x["new_start"], x["new"])
                 for x in hunks if x["old"] or x["new"]]
             for p, hunks in files.items()}
    files = {p: h2 for p, h2 in files.items() if h2}
    return (files, problems)


def _apply_one_hunk(old_l, old_start, old_lines):
    """Locate hunk in old_l (1-based old_start, then trimmed-context
    fuzzy search). Returns (splice_at, splice_len) or raises ValueError.
    v6.8.1: a PURE-ADDITION hunk (old_lines == [], e.g. @@ -3,0 +4,1 @@
    from diff -U0 or a new-file diff) has no context to match - it splices
    at the header position instead of failing."""
    n = len(old_l)
    if not old_lines:
        # @@ -N,0 +M,K @@ = INSERT AFTER old line N (git semantics),
        # so the splice index is N (0-based: after the Nth line);
        # clamped into [0, n] - new files start at N=0.
        return (max(0, min(int(old_start), n)), 0)
    start = max(0, old_start - 1)
    if old_l[start:start + len(old_lines)] == old_lines:
        return (start, len(old_lines))
    # fuzzy: compare with trailing-space stripped, then with stripped lines
    def _fuzzy_match(strip):
        for off in range(0, n + 1):
            for p in ({start - off, start + off} if off else {start}):
                if 0 <= p <= n - len(old_lines):
                    seg = old_l[p:p + len(old_lines)]
                    if [strip(x) for x in seg] == [strip(x) for x in old_lines]:
                        return (p, len(old_lines))
        return None
    hit = _fuzzy_match(lambda x: x.rstrip())
    if hit is None:
        hit = _fuzzy_match(lambda x: x.strip())
    if hit is None:
        raise ValueError("hunk context not found in the current file")
    return hit


def apply_patch(original, hunks):
    """Apply parsed hunks of ONE file (from parse_patch) to `original`
    text. Returns (new_text, applied_n, problems). All hunk positions
    refer to the ORIGINAL file, so they are applied bottom-up (later
    hunks first) - line numbers stay valid. v6.8.1: OVERLAPPING splices
    are rejected instead of silently destroying lines."""
    old_l = str(original).splitlines()
    had_trailing_nl = str(original).endswith("\n")
    problems = []
    applied = 0
    splices = []
    for idx, (old_start, old_lines, _ns, new_lines) in enumerate(hunks, 1):
        try:
            pos, ln = _apply_one_hunk(old_l, old_start, old_lines)
        except ValueError as e:
            problems.append((idx, str(e)))
            continue
        splices.append((pos, ln, list(new_lines), idx))
    # apply bottom-up; reject a splice that lands inside an already-
    # accepted splice's replaced range (fuzzy matches can collide)
    accepted = []
    for pos, ln, new_lines, idx in sorted(splices, key=lambda s: -s[0]):
        start_b, end_b = pos, pos + ln           # replaced range [a, b)
        collides = False
        for a2, b2 in accepted:
            if start_b < b2 and a2 < end_b:
                collides = True
                break
        if collides:
            # v6.9 fix: report the ORIGINAL hunk number - the old 'applied + 1'
            # counted accepted splices and named the wrong hunk
            problems.append((idx, "hunk overlaps another applied "
                             "hunk - rejected for safety"))
            continue
        old_l[pos:pos + ln] = new_lines
        accepted.append((pos, pos + len(new_lines)))
        applied += 1
    text = "\n".join(old_l) + ("\n" if had_trailing_nl and old_l else "")
    return (text, applied, problems)
