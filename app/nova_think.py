"""nova_think.py - v7.14: THE THINK PROTOCOL (visible reasoning).

Some models reason natively (DeepSeek-R1 / QwQ / Qwen3 / o1-family emit a
<think> block). Most small local models (and several cloud ones) do NOT -
they answer straight from the gut, which is exactly where hallucinations
are born. This module makes reasoning VISIBLE and UNIVERSAL:

  1. FORCED reasoning - models without native reasoning get a short system
     instruction: start every reply with

         === THINK ===
         (what am I being asked, what is the plan, what could go wrong)
         === END ===

     followed by the real answer. Thinking in the open measurably helps
     small models (the same trick behind several "reasoning distill"
     papers) - and the user can SEE what the brain is doing.

  2. NATIVE capture - when a reasoner emits <think>...</think>, it is
     converted into the same visible block, so every brain looks the same
     to the user and to the UI.

  3. CLEAN SEPARATION - extract() pulls the reasoning OUT of the answer
     text, so thinking can never become a file block, fire a tool token,
     or bloat the conversation history (the clean answer is what gets
     remembered - the context diet stays intact).

Fail-soft everywhere: a missing file, a corrupt mode file or a malformed
block degrades to "no reasoning shown", never to a crash. NOVA_THINK=0
kills the whole layer (the forced prompt AND the mode file) while native
<think> capture stays on - protocol hygiene must never depend on a toggle.

v8.2 OPEN-BLOCK SALVAGE: weak models CONSTANTLY forget the === END ===
closer (or the stream is cut before it arrives). The old rule "an unclosed
block is never an answer" threw away the ENTIRE reply - including every
=== FILE: === block the model had already written. That nuked real work:
the user watched the model code for minutes and then got "empty answer".
Now an open block is scanned for REAL WORK (a FILE/EDIT header, a code
fence, a tool token): the prose stays the think box, the work after the
first work marker becomes the answer and is parsed/applied normally.
Only a block with NO work marker at all (pure truncated reasoning) stays
open=True - the caller's auto-continue then asks the model to finish.
"""

import json
import os
import re
import threading
import time

try:
    from pathlib import Path
except Exception:  # pragma: no cover - pathlib ships with every Python
    Path = None

VERSION = "8.12.0"

# ---- the protocol markers -------------------------------------------------
THINK_START = "=== THINK ==="
THINK_END = "=== END ==="

# Lenient marker matching: weak local models mangle spacing (`===THINK===`,
# `===  Think ===`) - the INTENT must still count. The END marker must sit
# on its own line (never the tail of a longer word like "=== ENVELOPE ===").
_THINK_OPEN_RE = re.compile(r"^\s*={2,}\s*THINK\s*={2,}\s*$", re.I | re.M)
_THINK_CLOSE_RE = re.compile(r"^\s*={2,}\s*END\s*={2,}\s*$", re.I | re.M)

# Native reasoner tags (<think> is DeepSeek-R1/Qwen3; <thinking> and
# <reasoning> appear on several fine-tunes and relays).
_NATIVE_RE = re.compile(
    r"<(think|thinking|reasoning|thought)>(.*?)</\1>", re.I | re.S)
_NATIVE_OPEN_RE = re.compile(
    r"<(think|thinking|reasoning|thought)>(?!.*</\1>)", re.I | re.S)
_NATIVE_OPEN_RX = re.compile(
    r"<(think|thinking|reasoning|thought)>", re.I | re.S)

# Models that reason natively - matched against the MODEL NAME only (the
# cheapest reliable signal; providers never agree on a capability flag).
# Deliberately conservative: qwen2.5-coder and llama3 do NOT belong here.
REASONING_MODEL_RE = re.compile(
    r"(deepseek[-_ ]?r|qwq|qwen\s*3|qwen3|reason|think"
    r"|\bo1\b|\bo1[-_ ]?(mini|preview|pro)|\bo3\b|\bo4[-_ ]?mini"
    r"|phi[-_ ]?4[-_ ]?reason|magistral|nemotron[-_ ]?think"
    r"|glm[-_ ]?4\.5|glm[-_ ]?4\.6|exaone[-_ ]?deep"
    r"|skywork|openthinker|deephermes)",
    re.I)

MODES = ("auto", "on", "off")
DEFAULT_MODE = "auto"
CONFIG_NAME = "think.json"


def enabled():
    """NOVA_THINK=0 disables the FORCED prompt (native <think> capture
    stays on regardless - it is protocol hygiene, not a feature flag)."""
    return os.environ.get("NOVA_THINK", "") != "0"


def capable(model_name):
    """True when the model reasons natively (its family emits a think
    block by itself). Unknown families -> False -> they get the forced
    prompt, which is the safe default."""
    name = str(model_name or "")
    return bool(REASONING_MODEL_RE.search(name))


# ---- per-workspace mode (auto | on | off) ---------------------------------
def _cfg_path(ws):
    base = getattr(ws, "root", ws) if ws is not None else None
    if base is None:
        return None
    p = Path(str(base)) / ".nova" / CONFIG_NAME
    return p


def _ws_root(ws):
    """A workspace object or a plain path - both work. pathlib.Path ALSO
    has a `.root` attribute (the "/" component), so Path inputs must be
    detected by TYPE before any getattr probe, or a tmpdir workspace
    silently becomes '/.nova'."""
    if ws is None:
        return None
    if isinstance(ws, (str, Path)):
        return Path(ws)
    root = getattr(ws, "root", None)
    if root:
        return Path(str(root))
    return Path(str(ws))


def mode(ws):
    """Read the persisted mode; 'auto' when absent/corrupt."""
    try:
        p = _ws_root(ws) / ".nova" / CONFIG_NAME
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            m = str(data.get("mode", DEFAULT_MODE)).strip().lower()
            if m in MODES:
                return m
    except Exception:
        pass
    return DEFAULT_MODE


try:
    import nova_atomic as _natom
except Exception:
    _natom = None


def set_mode(ws, value):
    """Persist the mode atomically. Returns the mode actually set.
    Uses nova_atomic when present (pid+tid unique scratch name, the
    REPL+web two-writer case); the manual fallback never deletes an
    existing config - a failed replace removes only our OWN tmp file and
    the old mode simply stays (fail-soft beats silent loss)."""
    m = str(value or "").strip().lower()
    if m not in MODES:
        raise ValueError("mode must be one of " + "|".join(MODES))
    p = _ws_root(ws) / ".nova" / CONFIG_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"mode": m}, ensure_ascii=False)
    if _natom is not None:
        try:
            err = _natom.write_text_atomic(p, payload, encoding="utf-8")
            if not err:
                return m
        except Exception:
            pass
    tmp = p.with_name("%s.tmp%d" % (p.name, (os.getpid() * 7919
                    + threading.get_ident() % 100000
                    + int(time.time() * 1000)) % 1000000))
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(p)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
    return m


def should_force(ws, model_name):
    """The ONE decision point: must THIS turn carry the forced prompt?
    auto -> only for models WITHOUT native reasoning;
    on   -> every model (a native reasoner is asked to ALSO use the
            visible markers - double visibility, never double answers);
    off  -> nobody (native capture still runs at extraction time)."""
    if not enabled():
        return False
    m = mode(ws)
    if m == "off":
        return False
    if m == "on":
        return True
    return not capable(model_name)


def force_prompt(section="coding"):
    """The short system fragment that teaches the protocol. Kept tiny
    (~90 tokens): on a 4068-token local window it must stay noise-level,
    and a small model follows SHORT rules far better than long essays."""
    where = ("the coding agent" if section == "coding"
             else "the friendly chat side" if section == "talk"
             else "this assistant")
    return (
        "REASONING PROTOCOL (always on, every reply): start EACH reply with "
        "a short visible reasoning block in exactly this format:\n"
        "=== THINK ===\n"
        "(2-6 short lines: what is really being asked, your plan, risks or "
        "alternatives you weigh)\n"
        "=== END ===\n"
        "Then give the normal answer AFTER the === END === line. The block "
        "is your scratchpad - plain sentences, NO code, NO file blocks, NO "
        "tool tokens inside it. Never skip it, never put the answer inside "
        f"it. As {where}, your reasoning helps the user trust the answer."
    )


# ---- v7.14.1: FILE/EDIT protection ----------------------------------------
# === FILE:/EDIT: ... === blocks are the coding protocol's territory. A
# THINK marker (or a native tag) quoted INSIDE a file body - or an ===
# END === that closes a FILE block - must never be consumed here, or a
# real file the user asked for silently disappears (verified failure
# before the fix: a docs answer lost its file to the extractor).
_FILE_HEAD_RE = re.compile(
    r"^[ \t]*={2,}[ \t]*(?:FILE|EDIT)[ \t]*:[^\n]*$", re.I | re.M)

# v8.2: the first REAL-WORK marker inside an OPEN think block. When a
# model forgets the === END === closer (or the stream dies first) and then
# continues straight into files / edits / code / tool tokens, everything
# from the FIRST such marker onward is the answer - not reasoning. The
# FILE/EDIT header and fence alternatives are line-anchored (like the
# parser's own regexes); the tool-token alternative is not, because a
# model fires [SEARCH: q] mid-sentence while leaving its think block open.
_WORK_MARK_RE = re.compile(
    r"^[ \t]*={2,}[ \t]*(?:FILE|EDIT)[ \t]*:[^\n]*$"
    r"|^[ \t]*(?:```+|~~~+)"
    r"|\[[A-Z][A-Z_]{1,20}:[^\]\n]{0,200}\]",
    re.M)

_FENCE_RE = re.compile(r"^[ \t]*(?:```+|~~~+)", re.M)


def _fence_spans(text):
    """[(start, end)] covering fenced code blocks (v8.0).
    A `=== THINK === ... === END ===` pair QUOTED inside a fence ("show
    me the THINK protocol") used to be consumed as the reply's own
    reasoning - the quoted example silently vanished from the answer.
    EXCEPTION: a fence that OPENS at the very beginning of the reply is
    a WRAPPED reply (weak models fence the whole answer) - that whole
    outer pair is skipped, its markers stay extractable, and the
    fence-wrapping repair in parse_files relies on THINK extraction
    running first there."""
    marks = list(_FENCE_RE.finditer(text))
    if not marks:
        return []
    idx = 0
    if text[:marks[0].start()].strip() == "":
        idx = 2                       # drop the wrapping pair entirely
    spans = []
    rest = marks[idx:]
    for i in range(0, len(rest) - 1, 2):
        spans.append((rest[i].start(), rest[i + 1].end()))
    if len(rest) % 2 == 1:            # unclosed fence runs to the end
        spans.append((rest[-1].start(), len(text)))
    return spans


def _protected_spans(text):
    """[(start, end)] covering every well-formed FILE/EDIT block and
    every (non-wrapping) fenced code block."""
    spans = []
    for m in _FILE_HEAD_RE.finditer(text):
        m_end = _THINK_CLOSE_RE.search(text, m.end())
        if m_end:
            spans.append((m.start(), m_end.end()))
    spans.extend(_fence_spans(text))
    return spans


def _file_only_spans(text):
    """[(start, end)] of the well-formed FILE/EDIT blocks ONLY (no fences).
    The v8.2 salvage scan uses this list: a COMPLETE quoted file example
    inside an open think block stays reasoning (the v7.14 law), while an
    UNCLOSED file header - one with no === END === after it - is real work
    the model never got to close and must be salvaged."""
    spans = []
    for m in _FILE_HEAD_RE.finditer(text):
        m_end = _THINK_CLOSE_RE.search(text, m.end())
        if m_end:
            spans.append((m.start(), m_end.end()))
    return spans


def _in_spans(pos, spans):
    return any(a <= pos < b for a, b in spans)


def _salvage_point(body, offset, fspans):
    """v8.2: (index of the first REAL-WORK marker in `body`) or None.
    A marker inside a COMPLETE FILE/EDIT span is a quoted example - the
    v7.14 law keeps it in the think box. An unclosed header / fence /
    tool token is work the stream never let the model finish."""
    for m in _WORK_MARK_RE.finditer(body):
        if _in_spans(offset + m.start(), fspans):
            continue
        return m.start()
    return None


def _marker_extract(text, opener, spans):
    """Split at a KNOWN-good THINK opener (outside protected spans).
    v8.2: an UNCLOSED block no longer nukes the answer. If the body
    carries REAL WORK after the opener (a === FILE:/EDIT: === header, a
    code fence, a tool token), the work is salvaged as the answer and
    only the prose becomes the think box - a model that forgets === END ===
    (nearly every small local model, at least once per session) keeps its
    files instead of dying as an 'empty answer'. Without any work marker
    the old honest rule stands: half a reasoning is never an answer."""
    body = text[opener.end():]
    # v8.11: everything BEFORE the opener is real answer text (a model
    # preamble like 'Sure! Here is the fix:' - or even complete FILE
    # blocks from a model that works first and thinks later). The old
    # branch dropped it entirely; the native branch always kept its
    # prefix. Fold it into every answer this function returns.
    prefix = text[:opener.start()].strip()

    def _join(tail):
        tail = (tail or "").lstrip("\n")
        return ((prefix + "\n" + tail).strip() if prefix.strip()
                else tail)

    pos = 0
    fspans = _file_only_spans(text)
    while True:
        m_cand = _THINK_CLOSE_RE.search(body, pos)
        if not m_cand:
            # unclosed: interrupted stream or a forgotten END
            w = _salvage_point(body, opener.end(), fspans)
            if w is not None:
                return {"think": body[:w].strip() or None,
                        "answer": _join(body[w:]),
                        "native": False, "open": False, "salvaged": True}
            # nothing salvageable - never mistake half a reasoning for an
            # answer; the caller's auto-continue asks the model to finish
            # (a prefix alone is not a work answer either)
            return {"think": body.strip() or None, "answer": "",
                    "native": False, "open": True}
        if not _in_spans(opener.end() + m_cand.start(), spans):
            think = body[:m_cand.start()].strip()
            answer = _join(body[m_cand.end():])
            return {"think": think or None, "answer": answer,
                    "native": False, "open": False}
        # that END closes a FILE/EDIT block - the think block's own END
        # must come later
        pos = m_cand.end()


def _native_extract(text, start, end, body):
    """Split at a KNOWN native <think>...</think> span. Only the tag span
    is removed - never any === END === from the answer (it may close a
    FILE block; verified corruption before this rule).
    v8.0: takes explicit (start, end, body) from the depth-aware scan
    instead of a non-greedy regex match."""
    think = (body or "").strip()
    answer = (text[:start] + " " + text[end:]).strip()
    # A reasoner may ALSO follow our forced protocol right after its
    # native block. A THINK opener at the very START of the remainder
    # begins that block - fold it into the same visible reasoning. (A
    # FILE body can never start the answer: file bodies live behind a
    # === FILE: header, which the marker branch itself protects.)
    stripped = answer.lstrip()
    m_lead = _THINK_OPEN_RE.search(stripped) if stripped else None
    if m_lead is not None and m_lead.start() == 0:
        r2 = _marker_extract(stripped, m_lead, _protected_spans(stripped))
        if r2["think"]:
            think = (think + "\n" + r2["think"]).strip()
        answer = r2["answer"]
    return {"think": think or None, "answer": answer,
            "native": True, "open": False}


def _native_scan(text):
    """v8.0: DEPTH-AWARE scan for a native reasoner block. The old
    non-greedy regex closed at the FIRST `</think>`, so a nested block
    ('<think>outer <think>inner</think> tail</think>ANSWER') leaked the
    literal tail + stray '</think>' into the answer - which then reached
    history and could be parsed into FILE bodies.
    Returns dict(start, end, tag, body, closed) or None (no opener)."""
    m = _NATIVE_OPEN_RX.search(text)
    if not m:
        return None
    tag = m.group(1)
    both = re.compile(r"<(/?\s*%s)\s*>" % re.escape(tag), re.I | re.S)
    depth = 1
    for it in both.finditer(text, m.end()):
        if it.group(1).startswith("/"):
            depth -= 1
            if depth == 0:
                return {"start": m.start(), "end": it.end(), "tag": tag,
                        "body": text[m.end():it.start()], "closed": True}
        else:
            depth += 1
    return {"start": m.start(), "end": m.end(), "tag": tag,
            "body": text[m.end():], "closed": False}


def extract(text):
    """Split a model reply into {think, answer, native, open}.

    Order of precedence:
      1. our === THINK === / === END === markers - but ONLY an opener
         that sits OUTSIDE any FILE/EDIT block and (when a native block
         is present too) BEFORE it; markers nested inside <think>...</think>
         belong to the native block,
      2. native <think>/<thinking>/<reasoning>/<thought> tags,
      3. nothing -> think=None, answer unchanged.
    An UNCLOSED block (interrupted stream, or a small model that forgot
    END) is reported with open=True and answer='' ONLY when it carries no
    real work - half a reasoning is never mistaken for an answer. When the
    open body contains a === FILE:/EDIT: === header, a code fence or a
    tool token, everything from that marker on IS the answer (v8.2
    salvage, result carries salvaged=True): models forget === END === all
    the time and their files must survive."""
    if not text or not str(text).strip():
        return {"think": None, "answer": text or "", "native": False,
                "open": False}
    text = str(text)
    spans = _protected_spans(text)
    nat = _native_scan(text)

    # ---- 1) the explicit protocol markers --------------------------------
    opener = next((m for m in _THINK_OPEN_RE.finditer(text)
                   if not _in_spans(m.start(), spans)
                   and (nat is None or m.start() < nat["start"])), None)
    if opener is not None:
        return _marker_extract(text, opener, spans)

    # ---- 2) native reasoner tags (depth-aware, v8.0) ----------------------
    if nat is not None:
        if nat["closed"]:
            return _native_extract(text, nat["start"], nat["end"],
                                   nat["body"])
        # stream died mid-think (or the model never closed it). Salvage
        # real work (files/fences/tool tokens) from the open body - the
        # same v8.2 law as the marker branch; without work, half a
        # reasoning is never an answer.
        w = _salvage_point(nat["body"], nat["end"], _file_only_spans(text))
        if w is not None:
            answer = (text[:nat["start"]] + "\n"
                      + nat["body"][w:]).strip()
            return {"think": nat["body"][:w].strip() or None,
                    "answer": answer, "native": True, "open": False,
                    "salvaged": True}
        return {"think": nat["body"].strip() or None, "answer": "",
                "native": True, "open": True}

    return {"think": None, "answer": text, "native": False, "open": False}


def clean(text):
    """The answer without any reasoning block (history / parsing diet)."""
    try:
        return extract(text)["answer"]
    except Exception:
        return text
