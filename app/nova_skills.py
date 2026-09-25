#!/usr/bin/env python3
# =====================================================================
#  Nova Code - self-built skills (v5.0)
#
#  Repeated solutions should not be re-derived (and re-paid in tokens)
#  every time. A SKILL is a small named instruction snippet bound to a
#  trigger; the most-used ones are injected into the system prompt:
#
#      /skill save docker "when a container must stay alive, add
#                        restart: unless-stopped to every service"
#      /skill list | /skill show <name> | /skill del <name>
#
#  AUTO-CAPTURE (no model call, zero cost): every successful task -
#  files applied AND the run command exited 0 - bumps a signature
#  counter keyed on the normalized request. The third success of the
#  same kind of request turns into an auto-skill capturing what worked,
#  so the next similar request starts from experience instead of zero.
#
#  Storage: .nova/skills.json (skills) + .nova/skills_pending.json
#  (pre-skill counters). Both tiny, bounded, fail-soft, atomic.
# =====================================================================
import hashlib
import json
import os
import threading
import re
import time
from pathlib import Path

from nova_policy import NOVA_DIR

try:
    import nova_atomic as natom
except Exception:
    natom = None

SKILLS_FILE = "skills.json"
PENDING_FILE = "skills_pending.json"
MAX_SKILLS = 40
MAX_PENDING = 30
MAX_BODY_CHARS = 700
MAX_NAME_CHARS = 40
AUTO_THRESHOLD = 3          # successes before an auto-skill is born
MAX_INJECT_CHARS = 900      # system-prompt injection budget


def _path(ws, name):
    return Path(ws) / NOVA_DIR / name


def _load(ws, name):
    try:
        p = _path(ws, name)
        if not p.is_file():
            return {}
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _save(ws, name, obj):
    try:
        p = _path(ws, name)
        # v6.7: unique scratch name (cross-process tmp collision)
        if natom is not None:
            return natom.write_text_atomic(
                p, json.dumps(obj, ensure_ascii=False, indent=1))
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}{threading.get_ident() % 10000}.tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)


# --------------------------------------------------------------- manual skills
def normalize(text):
    """Request signature base: lowercase, collapse whitespace, strip
    punctuation-ish noise, bounded."""
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    t = re.sub(r"[^\w\s+/.-]", "", t)
    return t[:90]


def add(ws, name, instructions, trigger="", auto=False):
    name = re.sub(r"\s+", "-", str(name).strip())[:MAX_NAME_CHARS]
    if not name or not str(instructions or "").strip():
        return "skill needs a name and instructions"
    data = _load(ws, SKILLS_FILE)
    skills = data.get("skills", []) if isinstance(data.get("skills"), list) else []
    skills = [s for s in skills if isinstance(s, dict) and s.get("name")]
    if any(s["name"] == name for s in skills):
        skills = [s for s in skills if s["name"] != name]   # overwrite
    skills.append({
        "name": name,
        "trigger": str(trigger or "")[:120],
        "instructions": str(instructions).strip()[:MAX_BODY_CHARS],
        "uses": 0, "created": int(time.time()), "auto": bool(auto),
    })
    skills = skills[-MAX_SKILLS:]
    return _save(ws, SKILLS_FILE, {"skills": skills})


def remove(ws, name):
    data = _load(ws, SKILLS_FILE)
    # v8.0: isinstance filter - a corrupt store with non-dict members
    # ("skills": ["docker"]) crashed /skill del with AttributeError
    # (add()/list_skills already filtered; remove/bump were missed)
    skills = [s for s in (data.get("skills") or [])
              if isinstance(s, dict) and s.get("name") != str(name).strip()]
    return _save(ws, SKILLS_FILE, {"skills": skills})


def list_skills(ws):
    data = _load(ws, SKILLS_FILE)
    skills = [s for s in (data.get("skills") or []) if isinstance(s, dict)]
    return sorted(skills, key=lambda s: (-s.get("uses", 0), s.get("name", "")))


def get(ws, name):
    for s in list_skills(ws):
        if s.get("name") == str(name).strip():
            return s
    return None


def bump(ws, name):
    data = _load(ws, SKILLS_FILE)
    for s in data.get("skills") or []:
        if not isinstance(s, dict):
            continue                    # v8.0: corrupt member, skip
        if s.get("name") == name:
            try:
                s["uses"] = int(s.get("uses", 0)) + 1
            except (TypeError, ValueError):
                s["uses"] = 1
            return _save(ws, SKILLS_FILE, data)
    return ""


# --------------------------------------------------------------- auto capture
def _pending_load(ws):
    obj = _load(ws, PENDING_FILE)
    return obj.get("pending", {}) if isinstance(obj.get("pending"), dict) else {}


def record_success(ws, user_text, run_cmd=""):
    """A task just succeeded (applied files + exit 0). Bump/forge the
    matching signature. Returns 'auto:<name>' | 'bumped' | 'counted' | ''.
    A manual skill whose trigger matches the request is simply bumped.
    v6.8.1: the pending-counter read-modify-write is guarded by the same
    cross-process lock the other stores use (REPL + web can both record
    a success; racing writers used to reset counters)."""
    if natom is not None:
        try:
            with natom.file_lock(_path(ws, PENDING_FILE).parent
                                 / "skills.lock", timeout=5.0):
                return _record_success_impl(ws, user_text, run_cmd)
        except Exception:
            pass
    return _record_success_impl(ws, user_text, run_cmd)


def _record_success_impl(ws, user_text, run_cmd=""):
    sig = normalize(user_text)
    if not sig:
        return ""
    # manual skill with a matching trigger keyword gets credit
    for s in list_skills(ws):
        trig = normalize(s.get("trigger") or s.get("name"))
        if trig and trig[:40] in sig:
            bump(ws, s["name"])
            return "bumped"
    pend = _pending_load(ws)
    entry = pend.get(sig) or {"count": 0, "sample": str(user_text)[:120],
                              "run_cmd": "", "last": 0}
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last"] = int(time.time())
    if run_cmd and not entry.get("run_cmd"):
        entry["run_cmd"] = str(run_cmd)[:200]
    pend = {k: v for k, v in pend.items() if k != sig}
    pend[sig] = entry
    # v8.0: the pending sort is junk-proof (a non-dict value or a value
    # without a numeric count crashed every successful apply)
    def _count(kv):
        v = kv[1]
        if not isinstance(v, dict):
            return 0
        try:
            return -int(v.get("count", 0))
        except (TypeError, ValueError):
            return 0
    pend = dict(sorted(pend.items(), key=_count)[:MAX_PENDING])
    made = ""
    if entry["count"] >= AUTO_THRESHOLD:
        sample = (entry.get("sample") or sig)[:80]
        what = (f"For requests like '{sample}', this approach already worked: "
                f"{entry.get('run_cmd') or 'apply the files, then run the verify command'}. "
                "Reuse the same file layout and commands as a starting point.")
        # v6.5: the old precedence ("auto-" + slug) or "auto-skill" let the
        # fallback die - '+' binds tighter than 'or', so the left side was
        # always truthy. Slug first, fallback on the slug.
        # v6.7: the v6.5 fix only repaired the precedence - every Persian
        # (or multi-word-colliding) signature STILL produced the same
        # "auto-auto-skill" name and overwrote its predecessors. A short
        # content hash makes each distinct signature its own skill.
        slug = re.sub(r"[^a-z0-9]+", "-", sig[:28].lower()).strip("-") \
            or "auto"
        name = "auto-" + slug + "-" + hashlib.sha1(
            sig.encode("utf-8")).hexdigest()[:8]
        add(ws, name, what, trigger=sample, auto=True)
        made = f"auto:{name}"
        pend.pop(sig, None)
    err = _save(ws, PENDING_FILE, {"pending": pend})
    return made or ("" if err else "counted")


# --------------------------------------------------------------- injection
def inject_text(ws):
    """System-prompt section for learned skills (top by uses, bounded).
    '' when there is nothing worth injecting."""
    skills = [s for s in list_skills(ws) if s.get("uses", 0) > 0 or not s.get("auto")]
    skills = skills[:6]
    if not skills:
        return ""
    lines = []
    used = 0
    for s in skills:
        ln = f"- {s['name']}: {s.get('instructions', '')}"
        if used + len(ln) > MAX_INJECT_CHARS:
            break
        lines.append(ln)
        used += len(ln) + 1
    if not lines:
        return ""
    return ("\n\n## Learned skills (proven approaches in this project)\n"
            "Apply these when they match the request - they worked before:\n"
            + "\n".join(lines))
