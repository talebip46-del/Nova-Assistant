#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - the CONTEXT ENGINE (v8.3 "context engine")
#
#  One place that owns EVERYTHING about "how much fits in the brain":
#
#    1. PER-BACKEND WINDOWS   local models (Ollama / llama.cpp / LM
#                             Studio / vLLM) and cloud providers get
#                             SEPARATE, user-settable context windows.
#                             They must never mix: a local 7B on a weak
#                             box and a frontier cloud model live in
#                             completely different window sizes.
#                             Nova's number is sent as `num_ctx` on
#                             every Ollama call and as the `-c` flag
#                             when spawning llama-server - so it
#                             OVERRIDES whatever default the runtime
#                             picked for the model. The user's choice
#                             is the law, not the runtime's default.
#    2. SMART COMPRESSION     when the conversation grows past the
#                             window, the OLD half is folded into a
#                             compact DIGEST that keeps what actually
#                             matters for continuing the work:
#                             goals, file paths, commands, decisions,
#                             protocol targets (=== FILE: ===) - and
#                             drops the chatter. The NEWEST messages
#                             are kept verbatim (they carry the live
#                             context). Deterministic and offline: no
#                             extra model call, no credits, safe on
#                             weak hardware. The model-summarized
#                             /compact stays available as the manual
#                             "deep compact".
#
#  Settings live per-workspace in .nova/context.json (like style.json,
#  route.json). `custom` marks a file the USER actually saved - only
#  then do the numbers override the env/global defaults, so a fresh
#  workspace keeps the exact pre-8.3 behavior (NOVA_NUM_CTX /
#  NOVA_CLOUD_CTX stay honored).
#
#  Pure standard library, fail-soft everywhere: a broken or hostile
#  file falls back to clean defaults instead of breaking the session.
# =====================================================================
import json
import re
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:                       # pragma: no cover - fail-soft
    natom = None

SETTINGS_FILE = "context.json"

# ---- validation bounds -------------------------------------------------
# LOCAL: Ollama accepts huge num_ctx values but each token of KV cache
# costs RAM on the user's machine; 512 is the smallest useful window
# (system prompt + one exchange), 262144 covers every local model that
# can realistically run on consumer hardware.
LOCAL_MIN, LOCAL_MAX = 512, 262_144
# CLOUD: frontier windows grow fast (128k ... 1M+); 2048 is the floor
# for the tiny/cheap tiers, 4M covers anything shipping today.
CLOUD_MIN, CLOUD_MAX = 2_048, 4_000_000
# auto-compression trigger: fraction of the window that may fill up
# before the old block is folded into a digest.
THRESHOLD_MIN, THRESHOLD_MAX = 0.5, 0.95
# how many of the NEWEST messages stay verbatim (never digested).
KEEP_MIN, KEEP_MAX = 2, 16

DEFAULTS = {
    "local_ctx": 4096,        # env NOVA_NUM_CTX is applied on load
    "cloud_ctx": 16384,       # env NOVA_CLOUD_CTX is applied on load
    "auto_compact": True,     # smart digest ON by default (cheap: no model call)
    "compact_threshold": 0.85,
    "keep_recent": 4,
}

MAX_SETTINGS_BYTES = 8_000

# ---- digest extraction patterns ----------------------------------------
# File paths (model-facing protocol targets, plain mentions, code refs).
_PATH_RE = re.compile(
    r"(?:[\w./\\-]*[/\\])?[\w.-]+\.(?:py|js|ts|tsx|jsx|html|css|json|md|txt|"
    r"sh|bat|ps1|yaml|yml|toml|ini|cfg|sql|php|rb|go|rs|java|c|cpp|h|cs|vue|"
    r"svelte|svg|env|log)")

# Commands: backticks, $ prefix, Run: hints.
_BACKTICK_RE = re.compile(r"`([^`\n]{2,120})`")
_RUN_RE = re.compile(r"^\s*(?:Run|Preview)\s*:\s*(.+)$", re.MULTILINE)

# Protocol targets the agent may have emitted (=== FILE: x ===).
_PROTO_RE = re.compile(r"===\s*(?:FILE|EDIT)\s*:\s*([^\n=]+?)\s*===", re.MULTILINE)

# Decision-ish lines (en + fa keywords), kept short.
_DECISION_RE = re.compile(
    r"^\s*(?:[-*]|\d+\.)?\s*(?:we (?:decided|chose|use[d]?|switched|fixed|renamed|added|removed)|"
    r"decision\s*:|note\s*:|important\s*:|قرار شد|تصمیم|توجه|مهم)\s*:?\s*(.{4,160})$",
    re.IGNORECASE | re.MULTILINE)

# Token prefixes the model uses to fetch things - worth keeping the query.
_SEARCH_RE = re.compile(r"\[(?:SEARCH|READ|IMG):\s*([^\]\n]{3,120}?)\s*\]")

_DIGEST_MARK = "[compact digest - older messages were folded by the v8.3 context engine]"
_MAX_LINE = 180           # chars per digest line
_MAX_PAIR_LINES = 3       # digest lines per message pair
_DIGEST_HEADROOM = 0.90   # digest must not exceed this share of its budget


def settings_path(ws):
    return Path(ws) / ".nova" / SETTINGS_FILE


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _env_int(name, default):
    """Env override at load time - a typo'd value must never crash."""
    import os
    raw = str(os.environ.get(name, "")).strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _valid_fields(obj):
    """ONLY the valid keys found in `obj` - invalid/unknown keys are
    dropped silently so a bad update can never clobber a good stored
    value (never trust a hand-edited file)."""
    out = {}
    if not isinstance(obj, dict):
        return out
    lc = obj.get("local_ctx")
    if isinstance(lc, int) and not isinstance(lc, bool) \
            and LOCAL_MIN <= lc <= LOCAL_MAX:
        out["local_ctx"] = lc
    cc = obj.get("cloud_ctx")
    if isinstance(cc, int) and not isinstance(cc, bool) \
            and CLOUD_MIN <= cc <= CLOUD_MAX:
        out["cloud_ctx"] = cc
    ac = obj.get("auto_compact")
    if isinstance(ac, bool):
        out["auto_compact"] = ac
    th = obj.get("compact_threshold")
    if isinstance(th, (int, float)) and not isinstance(th, bool) \
            and THRESHOLD_MIN <= float(th) <= THRESHOLD_MAX:
        out["compact_threshold"] = round(float(th), 2)
    kr = obj.get("keep_recent")
    if isinstance(kr, int) and not isinstance(kr, bool) \
            and KEEP_MIN <= kr <= KEEP_MAX:
        out["keep_recent"] = kr
    return out


def _clean(obj):
    """Defaults overlaid with the valid fields of `obj`."""
    out = dict(DEFAULTS)
    out.update(_valid_fields(obj))
    return out


def load_settings(ws):
    """Effective settings for this workspace. Defaults track the env
    (NOVA_NUM_CTX / NOVA_CLOUD_CTX) so a fresh workspace behaves exactly
    like pre-8.3. `custom: True` = the user saved a file - the stored
    numbers then override everything (Nova's law beats Ollama's default)."""
    d = dict(DEFAULTS)
    # v8.7: env overrides ride the SAME bounds as saved settings - a
    # hand-typed NOVA_NUM_CTX=0 or -500 used to flow into the Ollama
    # payload / llama-server -c flag unchecked.
    d["local_ctx"] = _clamp(_env_int("NOVA_NUM_CTX", d["local_ctx"]),
                            LOCAL_MIN, LOCAL_MAX)
    d["cloud_ctx"] = _clamp(_env_int("NOVA_CLOUD_CTX", d["cloud_ctx"]),
                            CLOUD_MIN, CLOUD_MAX)
    d["custom"] = False
    try:
        p = settings_path(ws)
        if not p.is_file() or p.stat().st_size > MAX_SETTINGS_BYTES:
            return d
        saved = _valid_fields(
            json.loads(p.read_text(encoding="utf-8", errors="replace")))
        d.update(saved)
        # v8.7: custom means the user actually SAVED valid fields - a
        # foreign / hand-edited file with zero valid keys used to claim
        # custom and silently freeze the env-derived windows.
        d["custom"] = bool(saved)
    except Exception:
        pass
    return d


def save_settings(ws, updates):
    """Merge validated updates into .nova/context.json (atomic write).
    Returns '' or an error string. Saving marks the workspace CUSTOM -
    from then on Nova's windows override the runtime defaults."""
    try:
        valid = _valid_fields(updates if isinstance(updates, dict) else {})
        # v8.11: a save with nothing valid must not write anything - the
        # old code wrote a full DEFAULTS file, whose valid-looking keys
        # then claimed custom=True on the next load and silently froze
        # the env-derived windows for the workspace.
        if not valid:
            return ("no valid context settings in the update "
                    "(nothing was written)")
        cur = load_settings(ws)
        cur.update(valid)
        cur = _clean(cur)
        p = settings_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        if natom is not None:
            return natom.write_text_atomic(
                p, json.dumps(cur, indent=2, ensure_ascii=False) + "\n")
        # v8.11: pid/tid-unique temp name - a shared '.tmp' could tear
        # when the REPL and the web face save concurrently
        import os
        import threading
        tmp = p.with_suffix(".%d-%s.tmp" % (os.getpid(),
                                            threading.current_thread().name))
        tmp.write_text(json.dumps(cur, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)


def reset_settings(ws):
    """Delete the custom settings file (back to env/global defaults)."""
    try:
        p = settings_path(ws)
        if p.is_file():
            p.unlink()
        return ""
    except OSError as e:
        return str(e)


def est_tokens(text, cpt=2.7):
    """Conservative chars-per-token estimate (mixed en/code/fa) - the
    same pessimism as nova.CTX_CHARS_PER_TOKEN, +/-1 to avoid zero.
    v8.7: cpt is floored - a direct caller passing 0/negative used to
    raise ZeroDivisionError."""
    return int(len(str(text or "")) / max(0.1, float(cpt) if cpt else 2.7)) + 1


# =====================================================================
#  Smart compression - the digest
# =====================================================================
def _shrink(line):
    line = " ".join(str(line).split())
    return line if len(line) <= _MAX_LINE else line[:_MAX_LINE - 1] + "…"


def _extract_user(msg):
    """What the user asked for + the concrete objects they mentioned.
    v8.11: a previous DIGEST message is re-digested line by line - the
    old extractor read only the FIRST line (the digest mark itself), so
    every re-fold lost the goals and decisions the previous fold had
    saved (digest-of-digest lobotomy on long sessions)."""
    text = str(msg.get("content", ""))
    if text.startswith(_DIGEST_MARK):
        out = []
        for ln in text[len(_DIGEST_MARK):].splitlines():
            ln = " ".join(ln.split())
            if not ln:
                continue
            # strip the old pair tag ('#3 user: ...' -> 'user: ...') so
            # the next fold renumbers cleanly; keep every info line
            ln = re.sub(r"^#\d+\s+", "", ln)
            if ln.startswith(("user:", "decision:", "cmd:", "lookup:",
                              "run:", "wrote:", "files seen:")):
                out.append(ln)
        return out[:_MAX_PAIR_LINES * 4]
    out = []
    goal = _shrink(text.strip().splitlines()[0]) if text.strip() else ""
    if goal:
        out.append("user: " + goal)
    paths = sorted(set(_PATH_RE.findall(text)))
    if paths:
        out.append("files: " + ", ".join(paths[:8]))
    cmds = [c.strip() for c in _BACKTICK_RE.findall(text)
            if (" " in c or c.strip().endswith(("run", "install", "dev", "build", "test")))]
    if cmds:
        out.append("cmd: " + _shrink("; ".join(dict.fromkeys(cmds[:4]))))
    for q in _SEARCH_RE.findall(text)[:3]:
        out.append("lookup: " + _shrink(q))
    return out[:_MAX_PAIR_LINES]


def _extract_assistant(msg):
    """What the agent DID: protocol targets, run hints, decisions."""
    text = str(msg.get("content", ""))
    out = []
    targets = sorted(set(t.strip() for t in _PROTO_RE.findall(text)))
    if targets:
        out.append("wrote: " + ", ".join(targets[:8]))
    for m in _RUN_RE.finditer(text):
        out.append("run: " + _shrink(m.group(1)))
        break
    for m in _DECISION_RE.finditer(text):
        out.append("decision: " + _shrink(m.group(1)))
        break
    return out[:_MAX_PAIR_LINES]


def _pair_digest(history, start, end):
    """Fold history[start:end] into digest lines (dedup across pairs)."""
    files, lines = set(), []
    idx = 0
    for i in range(start, min(end, len(history))):
        m = history[i]
        if not isinstance(m, dict):
            continue
        idx += 1
        role = m.get("role", "?")
        for ln in (_extract_user(m) if role == "user" else _extract_assistant(m)):
            tag = "#" + str(max(1, (i - start) // 2 + 1))
            if ln.startswith("files:"):
                for f in ln[6:].split(","):
                    files.add(f.strip())
                continue
            lines.append(tag + " " + ln)
    # dedupe line prefixes (same goal repeated), keep order
    seen, dedup = set(), []
    for ln in lines:
        key = ln.split(" ", 1)[-1][:60]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(ln)
    if files:
        dedup.append("files seen: " + ", ".join(sorted(files)[:12]))
    return dedup


def compress_history(history, budget_tokens, keep_recent=4, cpt=2.7):
    """Fold the OLD part of `history` until it fits `budget_tokens`.

    Returns (new_history, stats). The newest `keep_recent` messages are
    always kept VERBATIM. Three escalating modes:
      digest - smart fold (goals/files/commands/decisions kept)
      tight  - one goal line per pair (digest got too big)
      drop   - keep only the newest block (even the digest is too big)
    `stats["changed"]` is False when nothing needed to happen."""
    stats = {"changed": False, "mode": "", "old": 0, "kept": len(history),
             "tokens_before": 0, "tokens_after": 0}
    msgs = [m for m in (history or []) if isinstance(m, dict)]
    if len(msgs) <= keep_recent:
        return history, stats

    before = sum(est_tokens(m.get("content", ""), cpt) for m in msgs)
    stats["tokens_before"] = before
    if before <= budget_tokens:
        return history, stats

    keep = max(KEEP_MIN, min(int(keep_recent or KEEP_MIN), len(msgs) - 1))
    recent = msgs[-keep:]
    old_cnt = len(msgs) - keep
    recent_tok = sum(est_tokens(m.get("content", ""), cpt) for m in recent)
    digest_budget = max(64, int(budget_tokens * _DIGEST_HEADROOM) - recent_tok)

    def build(lines):
        body = "\n".join(lines)
        return [{"role": "user",
                 "content": _DIGEST_MARK + "\n" + body}]

    stats["old"] = old_cnt

    # mode 1: the full digest - goals + files + commands + decisions.
    # digest_budget keeps headroom below the budget so the NEXT user
    # message still fits after the fold.
    lines = _pair_digest(msgs, 0, old_cnt)
    d_tok = est_tokens("\n".join(lines), cpt) if lines else -1
    if lines and d_tok <= digest_budget:
        newh = build(lines) + recent
        stats.update(changed=True, mode="digest", kept=len(newh),
                     tokens_after=recent_tok +
                     est_tokens(_DIGEST_MARK + "\n" + "\n".join(lines), cpt))
        return newh, stats

    # mode 2: tight - one goal line per pair (the digest was too roomy).
    # v8.11: the old even-index walk assumed msgs[2k] is always the user
    # message of a pair - after a fold the history STARTS with a digest
    # (role=user) and assistant/file lines got mislabeled 'user:' while
    # the real request vanished. Walk the actual roles instead: every
    # user message opens a pair; digest messages hand over their saved
    # goal lines.
    tight = []
    pair = 0
    for i in range(0, old_cnt):
        m = msgs[i]
        c = str(m.get("content", ""))
        if c.startswith(_DIGEST_MARK):
            for ln in c[len(_DIGEST_MARK):].splitlines():
                ln = ln.strip()
                if ln.startswith("#") and "user:" in ln[:16]:
                    tight.append("#%d user: %s"
                                 % (pair + 1,
                                    _shrink(ln.split("user:", 1)[1])))
                    pair += 1
            continue
        if m.get("role", "?") != "user":
            continue
        t = c.strip().splitlines()
        if t:
            tight.append("#%d user: %s" % (pair + 1, _shrink(t[0])))
            pair += 1
    t_tok = est_tokens("\n".join(tight), cpt) if tight else -1
    if tight and t_tok <= digest_budget:
        newh = build(tight) + recent
        stats.update(changed=True, mode="tight", kept=len(newh),
                     tokens_after=recent_tok +
                     est_tokens(_DIGEST_MARK + "\n" + "\n".join(tight), cpt))
        return newh, stats

    # mode 3: drop - the window is tiny; the newest block still survives
    drop_note = ("(the window was too small for a digest - %d old "
                 "messages were dropped)" % old_cnt)
    newh = build([drop_note]) + recent
    stats.update(changed=True, mode="drop", kept=len(newh),
                 tokens_after=recent_tok +
                 est_tokens(_DIGEST_MARK + "\n" + drop_note, cpt))
    return newh, stats
