#!/usr/bin/env python3
# =====================================================================
#  Nova Code - DIFFICULTY-BASED MODEL ROUTING (v7.5.0)
#
#  simple task -> fast small brain, hard task -> the strong brain.
#
#  Rules that keep it honest:
#  - LOCAL brains only, and ONLY when the user has NOT pinned an
#    explicit /brain coding route (a stored route is the user's will;
#    the router must never override it).
#  - CLOUD brains: never silently downgraded. Routing there happens
#    ONLY when the user stored an explicit fast/strong map
#    (.nova/route.json via /route) - otherwise 1 model, 1 answer.
#  - Deterministic heuristics, zero model calls, fail-soft everywhere.
# =====================================================================
import json
import os
import re
from pathlib import Path

ROUTE_FILE = "route.json"

# hard-task markers: STRONG structural markers alone signal hard work;
# weak markers add up
_STRONG = (
    # en
    "refactor", "architecture", "authentication", "auth system",
    "encryption", "compiler", "state machine", "websocket",
    # fa
    "بازسازی", "بازنویسی کامل", "معماری", "الگوریتم", "رمزنگاری",
    "احراز هویت", "پیچیده", "پروژه کامل",
)
_WEAK = (
    "concurrent", "thread", "async", "migration", "parser",
    "database schema", "api integration", "multithread", "optimize",
    # fa
    "بهینه‌ساز", "بهینه سازی", "چندنخی", "همزمان", "چند فایل",
)
_EASY = (
    # en
    "typo", "rename", "change the color", "change color", "fix the text",
    "capitaliz", "spelling", "comment", "print ", "log line", "title",
    "add a line", "one line",
    # fa
    "غلط املایی", "تایپو", "تغییر رنگ", "تغییر متن", "تغییر عنوان",
    "اسم تابع", "تغییر بده در", "یک خط", "یك خط", "فقط متن", "کامنت",
)

_WORD = re.compile(r"[a-z0-9_‌\u0600-\u06FF]+")


def classify_difficulty(text):
    """'easy' | 'medium' | 'hard' from the user's request (deterministic).
    One STRONG structural marker signals hard work; weak markers and
    big-output signals add up; easy markers lower; the default for real
    work stays 'medium'."""
    t = str(text or "")
    low = t.lower()
    strong = sum(1 for m in _STRONG if m in low)
    weak = sum(1 for m in _WEAK if m in low)
    easy = sum(1 for m in _EASY if m in low)
    # multi-file / big-output signals
    big = 0
    if len(t) > 900:
        big += 1
    words = len(_WORD.findall(low))
    if words > 120:
        big += 1
    # v8.11: the comma alternative used to sit inside \b..\b - a word
    # boundary cannot follow a literal comma when a space comes next,
    # so "file, file" never matched ("و/and" still matched). The comma
    # is now its own alternative.
    if re.search(r"\b(?:files?|فایل)\b.*(?:\b(?:and|و)\b|[,،،]).*\b(?:files?|فایل)\b", low):
        big += 1
    score = strong * 3 + weak + big - easy
    if score >= 3:
        return "hard"
    if score <= -1:
        return "easy"
    return "medium"


def _parse_param(name):
    """'qwen2.5-coder:7b-instruct' -> 7.0 (billion params) or None."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", str(name).lower())
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*m\b", str(name).lower())
    if m:
        try:
            return float(m.group(1)) / 1000.0
        except ValueError:
            return None
    return None


def pick_local_model(difficulty, installed, current):
    """Choose an installed local model for this difficulty.
    easy  -> the SMALLEST installed model at least ~2x smaller
    hard  -> the LARGEST installed model bigger than current
    Returns the model name, or '' (keep current) when nothing fits."""
    try:
        names = [n for n in (installed or []) if n and n != current]
        if not names:
            return ""
        cur = _parse_param(current)
        sized = [(n, _parse_param(n) or 0.0) for n in names]
        if difficulty == "easy":
            # cur <= 0 (unknown size): any smaller-NAMED model is a guess;
            # keep the safe list behavior (smallest installed)
            smaller = [s for s in sized if cur is None or cur <= 0.0
                       or s[1] <= cur / 2.0]
            if not smaller:
                return ""
            return min(smaller, key=lambda s: s[1])[0]
        if difficulty == "hard":
            # v8.11: an unknown current size (tags like 'llama3.1:latest'
            # carry no '7b' marker) used to parse as 0.0 - EVERY sized
            # model then counted as 'bigger', so a HARD task could be
            # downgraded to a 0.5b toy model. Never downgrade blind: a
            # hard task keeps the current brain unless something is
            # PROVABLY larger.
            if cur is None or cur <= 0.0:
                return ""
            bigger = [s for s in sized if s[1] > cur]
            if not bigger:
                return ""
            return max(bigger, key=lambda s: s[1])[0]
    except Exception:
        return ""
    return ""


def route_file(ws):
    """Path of the user's explicit cloud route map."""
    return Path(ws) / ".nova" / ROUTE_FILE


def load_route_map(ws):
    """The user's explicit {'fast': name, 'strong': name} map or {}.
    Fail-soft: a broken file is treated as absent."""
    try:
        p = route_file(ws)
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_route_map(ws, fast, strong):
    """Store / clear the explicit route map (both empty -> delete)."""
    try:
        p = route_file(ws)
        if not (str(fast or "").strip() or str(strong or "").strip()):
            if p.is_file():
                p.unlink()
            return ""
        p.parent.mkdir(parents=True, exist_ok=True)
        # v7.14.1: atomic write (same rationale as style/economy stores)
        payload = json.dumps({
            "fast": str(fast or "").strip(), "strong": str(strong or "").strip(),
        }, ensure_ascii=False, indent=1)
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


def pick_cloud_model(ws, difficulty, current):
    """Cloud routing ONLY via the user's explicit map (never a silent
    downgrade): easy->fast, hard->strong, medium keeps the active model.
    Returns ('', reason) when the active model should stay."""
    m = load_route_map(ws)
    if not m:
        return "", "no explicit route map"
    want = m.get("fast") if difficulty == "easy" \
        else m.get("strong") if difficulty == "hard" else ""
    want = str(want or "").strip()
    if not want or want == current:
        return "", "map has no entry for this difficulty"
    return want, ""


def decide(ws, text, backend, installed, current, has_coding_route=False):
    """One call the agent makes per coding turn.
    Returns (model_or_empty, difficulty, note). '' = keep the current
    model. Honors NOVA_NO_ROUTER=1. Cloud needs the explicit map; local
    needs no stored /brain coding route."""
    difficulty = classify_difficulty(text)
    if os.environ.get("NOVA_NO_ROUTER", "") == "1":
        return "", difficulty, ""
    try:
        if backend == "local":
            if has_coding_route:
                return "", difficulty, "user pinned a coding route"
            m = pick_local_model(difficulty, installed, current)
            if m:
                return m, difficulty, f"local {difficulty} -> {m}"
            return "", difficulty, ""
        m, why = pick_cloud_model(ws, difficulty, current)
        if m:
            return m, difficulty, f"cloud {difficulty} -> {m} (explicit map)"
        return "", difficulty, ""
    except Exception:
        return "", difficulty, ""
