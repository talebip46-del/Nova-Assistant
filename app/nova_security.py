#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - nova_security (v6.3)
#
#  The security layer that sits BETWEEN "the model / the web / the user
#  said it" and "a shell executes it".
#
#  What it provides (all pure standard library, no dependencies):
#
#  1. SECURE MODE          is_secure() / set_secure()
#                          NOVA_SECURE=1 env, or /secure on (persisted to
#                          <ws>/.nova/security.json). Web face: forces the
#                          access token even on loopback, blocks risky
#                          commands from web-originated turns, stricter
#                          rate limits.
#
#  2. COMMAND SCREENING    screen(cmd) -> {"verdict": allow|confirm|deny,
#                          "reasons": [...]}. Deny = destructive/system
#                          level (rm -rf /, format, mkfs, fork bomb,
#                          shutdown, ...). Confirm = destructive but
#                          routinely needed (rm -rf in a project, git
#                          reset --hard, taskkill, ...). Chained commands
#                          are SPLIT on && || ; | and every segment is
#                          checked (hiding `rm -rf /` behind `echo ok &&`
#                          does not help an attacker). Quoted spans are
#                          masked first, so `git commit -m "rm -rf /"`
#                          stays a normal commit.
#
#  3. POLICY DECISION      decide(verdict, origin, auto) -> block|ask|allow
#                          deny            -> always BLOCK
#                          confirm REPL    -> ask the human (y/n)
#                          confirm REPL/auto -> allow + warn (user opted
#                                              into /auto explicitly)
#                          confirm WEB     -> allow, but BLOCKED while
#                                             secure mode is on
#
#  4. AUDIT TRAIL          audit(ws, kind, cmd, origin, verdict, reason)
#                          append-only JSONL at <ws>/.nova/audit.jsonl
#                          (size-capped). Every run/bg command and every
#                          web denial is recorded - "who ran what".
#
#  5. RATE LIMITING        RateLimiter (token bucket per key) and
#                          AttemptThrottle (failed-token lockout with
#                          exponential-ish escalation) for the web face.
#                          Both prune stale entries, so RAM stays flat.
# =====================================================================
import json
import os
import re
import threading
import time
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:
    natom = None

VERSION = "6.3"

# --------------------------------------------------------------- secure mode
_SECURE_ENV = os.environ.get("NOVA_SECURE", "").strip().lower() \
    in ("1", "true", "yes", "on")
_secure_default = _SECURE_ENV
_lock = threading.Lock()


def _sec_file(ws):
    try:
        return Path(ws) / ".nova" / "security.json"
    except Exception:
        return None


def is_secure(ws=None):
    """Secure mode flag. Per-workspace file wins when present, else the
    NOVA_SECURE env default for this process."""
    if ws is not None:
        p = _sec_file(ws)
        if p is not None:
            try:
                return bool(json.loads(p.read_text(encoding="utf-8"))
                            .get("secure"))
            except Exception:
                pass
    return _secure_default


def set_secure(on, ws=None):
    """Turn secure mode on/off. With `ws` the choice is persisted for the
    workspace; without it only this process is affected. Returns the new
    state."""
    global _secure_default
    on = bool(on)
    with _lock:
        if ws is None:
            _secure_default = on
    if ws is not None:
        p = _sec_file(ws)
        if p is not None:
            try:
                # v6.7: unique scratch name (cross-process collision)
                if natom is not None:
                    err = natom.write_text_atomic(
                        p, json.dumps({"secure": on}))
                    if err == "":
                        return on
                p.parent.mkdir(parents=True, exist_ok=True)
                # v6.8.1: even the fallback gets a UNIQUE scratch name
                tmp = p.with_suffix(f".json.{os.getpid()}{threading.get_ident() % 10000}.tmp")
                tmp.write_text(json.dumps({"secure": on}), encoding="utf-8")
                os.replace(tmp, p)
            except Exception:
                pass
    return on


# --------------------------------------------------------------- screening
# (compiled regex, level, reason). Levels: "deny" > "confirm".
# Design rule: match DESTRUCTIVE INTENT precisely, keep false positives
# low for the everyday dev vocabulary (git, npm, pip, python, ls...).
_PATTERNS = []


def _p(pattern, level, reason):
    _PATTERNS.append((re.compile(pattern, re.IGNORECASE), level, reason))


# ---- POSIX: filesystem annihilation / system damage
# v6.5: root-target alternation also accepts trailing ')' '`' quotes etc.
# so that live command substitution ("$(rm -rf /)", now kept visible by
# _masked) and subshell forms are denied too, not only end-of-string.
_p(r"\brm\s+(-[a-eg-uwz]*[rf][a-eg-uwz]*\s+)+(/{1,2}['\"]?[)\]'\"`,;&$\s]*$|/\*|~/?['\"]?[)\]'\"`,;&$\s]*|\$home\b|/etc\b|/usr\b|/var\b|/boot\b|/lib\b|/bin\b|/sbin\b|/opt\b|/dev\b|/proc\b|/sys\b)",
   "deny", "recursive force delete of a system root")
_p(r"\brm\s+[^|;&]*\s/(?:\s|$)",
   "confirm", "delete from the filesystem root")
_p(r"\brm\s+-[a-eg-uwz]*r[a-eg-uwz]*f|\brm\s+-[a-eg-uwz]*f[a-eg-uwz]*r",
   "confirm", "recursive force delete (rm -rf)")
# v6.5: split short flags ("rm -r -f dir") used to slip past the clustered
# rm -rf confirm rule - two or more r/f flag tokens are the same intent.
_p(r"\brm\s+(-[a-eg-uwz]*[rf][a-eg-uwz]*\s+){2,}",
   "confirm", "recursive force delete (rm -r -f)")
# v6.5: --no-preserve-root exists ONLY to allow deleting / - never needed
# for legitimate project work, always a red flag on its own.
_p(r"\brm\s+[^|;&]*--no-preserve-root\b",
   "deny", "rm with --no-preserve-root")
_p(r"\bmkfs(\.\w+)?\b", "deny", "filesystem format (mkfs)")
_p(r"\bdd\b[^|;]*\bof=/dev/(sd|hd|nvme|vd|mmcblk|disk)", "deny",
   "raw disk write (dd of=/dev/...)")
_p(r">\s*/dev/(sd|hd|nvme|vd|mmcblk)", "deny", "redirect into a raw disk device")
_p(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "deny", "fork bomb")
_p(r"\b(shred|wipefs)\b", "deny", "disk wiping tool")
_p(r"\bchmod\s+-R\s+777\s+/(?:\s|$)", "deny", "chmod -R 777 on filesystem root")
_p(r"\bchmod\s+-R\s+777\b", "confirm", "chmod -R 777")
_p(r"\bchown\s+-R\b[^|;]*\s+/\s*$", "deny", "recursive chown of filesystem root")
# ---- POSIX: session / machine control
_p(r"^\s*(sudo\s+)?(shutdown|reboot|halt|poweroff|init\s+0|init\s+6)\b",
   "deny", "machine power/reboot command")
_p(r"\bsudo\b", "confirm", "superuser execution (sudo)")
# ---- remote-code-execution plumbing
_p(r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b", "confirm",
   "pipe from the network straight into a shell")
_p(r"\b(curl|wget)\b[^|;&]*\|\s*bash\b", "confirm", "pipe from the network into bash")
# v6.8.1 fix: the old (enc|e|ec)\s could never match the canonical long
# form -EncodedCommand ('enc' is followed by 'oded...', not whitespace),
# so `powershell -EncodedCommand <b64>` screened as ALLOW while -enc hit
# DENY. Match every accepted spelling as a word: -e -ec -enc -EncodedCommand.
_p(r"\bpowershell\b[^|;&]*\s-(?:e(?:c|nc(?:odedcommand)?)?)\b", "deny",
   "encoded PowerShell payload (powershell -enc/-EncodedCommand)")
_p(r"\b(invoke-expression|iex)\b", "confirm", "Invoke-Expression / iex")
# ---- Windows: disk & system
_p(r"\bformat\s+[a-z]:", "deny", "drive format (format C:)")
_p(r"\bdiskpart\b", "deny", "diskpart")
_p(r"\bcipher\s+/w\b", "deny", "cipher /w free-space wipe")
_p(r"\bvssadmin\b[^|;&]*delete", "deny", "shadow copy deletion (anti-recovery)")
_p(r"\bwmic\s+shadowcopy\b[^|;&]*delete", "deny", "shadow copy deletion (anti-recovery)")
_p(r"\bbcdedit\b", "deny", "boot configuration edit (bcdedit)")
_p(r"\b(wevtutil\s+cl|clear-eventlog)\b", "deny", "event log wipe")
_p(r"^\s*shutdown\b", "deny", "shutdown command")
# ---- Windows: recursive force deletes (drive-root variants are deny)
# v6.5: cmd/PowerShell switches are order-INdependent and PowerShell
# accepts abbreviations - the old fixed-order patterns missed common
# spellings like 'Remove-Item -Force -Recurse C:\' or 'del /s /q /f'.
# Lookaheads below match the switch SET in any order, with aliases.
_p(r"\b(rd|rmdir)\b(?=[^|;&]*\s/s\b)(?=[^|;&]*\s/q\b)[^|;&]*\s[a-z]:\\\s*$",
   "deny", "recursive delete of a drive root")
_p(r"\b(rd|rmdir)\b(?=[^|;&]*\s/s\b)(?=[^|;&]*\s/q\b)",
   "confirm", "rd /s /q (recursive delete)")
_p(r"\bdel\b(?=[^|;&]*\s/s\b)(?=[^|;&]*\s/q\b)[^|;&]*\s[a-z]:\\",
   "deny", "del /s /q of a drive root")
_p(r"\bdel\b(?=[^|;&]*\s/s\b)(?=[^|;&]*\s/q\b)",
   "confirm", "del /s /q (recursive delete)")
# v6.7: PowerShell resolves del/rd/rmdir/rm to Remove-Item too, so the
# dash-flag variants of those aliases are just as destructive (they used
# to bypass the drive-root DENY: 'rmdir -Recurse -Force C:\' -> allow).
# Dash-flag lookaheads keep POSIX 'rm -r dir' (no force) unflagged.
_p(r"\b(remove-item|ri|del|rd|rmdir|rm)\b(?=[^|;&]*\s-(recurse|r)\b)(?=[^|;&]*\s-(force|fo)\b)[^|;&]*\s[a-z]:\\\s*$",
   "deny", "Remove-Item -Recurse -Force on a drive root")
_p(r"\b(remove-item|ri|del|rd|rmdir|rm)\b(?=[^|;&]*\s-(recurse|r)\b)(?=[^|;&]*\s-(force|fo)\b)",
   "confirm", "Remove-Item -Recurse -Force")
# ---- persistence / tampering spots
_p(r">>?\s*(~|/\w*)*/\.ssh/authorized_keys\b", "confirm",
   "write into ~/.ssh/authorized_keys")
_p(r">>?\s*(~|/\w*)*/\.(bashrc|zshrc|profile|bash_profile)\b", "confirm",
   "write into a shell startup file")
_p(r"\breg\s+delete\b", "confirm", "registry delete (reg delete)")
_p(r"\bschtasks\s+/create\b", "confirm", "scheduled task creation (persistence)")
_p(r"\bcrontab\b", "confirm", "crontab modification")
# ---- data loss in git / db
_p(r"\bgit\s+push\b[^|;&]*(-f|--force)\b", "confirm", "git push --force")
_p(r"\bgit\s+reset\s+--hard\b", "confirm", "git reset --hard")
_p(r"\bgit\s+clean\s+(-[a-z]*[fd][a-z]*|--force)\b", "confirm", "git clean -f")
_p(r"\bgit\s+checkout\s+--\s+\.?\s*$|\bgit\s+restore\s+\.?\s*$", "confirm",
   "discard all working-tree changes")
_p(r"\bdrop\s+(database|schema)\b", "confirm", "DROP DATABASE")
_p(r"\bdrop\s+table\b", "confirm", "DROP TABLE")
# ---- process killing (common in dev, still destructive)
_p(r"\bkill\s+-9\b|\bkill\s+-s\s*(kill|sigkill)\b", "confirm", "kill -9")
_p(r"\b(pkill|killall)\b", "confirm", "pkill/killall")
_p(r"\btaskkill\b", "confirm", "taskkill")
_p(r"\bkill\s+-9\s+-1\b|\bkillall\s+-9\b", "deny", "kill every process of the user")

_MAX_LEVEL = {"allow": 0, "confirm": 1, "deny": 2}


def _masked(cmd, keep_dq=False):
    """Copy of the command with DOUBLE-quoted spans blanked - EXCEPT live
    command substitution inside them: the shell EXECUTES $(...) and
    `...` between double quotes (v6.5 fix - "echo \"hi $(rm -rf /)\""
    used to screen as a harmless echo). Single quotes stay VISIBLE on
    purpose: `sh -c 'rm -rf /'` is live executable content, not a
    message. Over-showing is always the safe direction here: it can only
    cause a false alarm, never a missed one.

    keep_dq=True: double-quoted CONTENT stays visible too (quote chars
    still blanked). Used for the `sh -c "..."` / `cmd /c "..."` /
    `powershell -Command "..."` forms where the quoted span is LIVE CODE,
    not a message (v6.7 fix - `sh -c "rm -rf /"` used to screen as an
    allow because the whole payload was masked away)."""
    out = []
    in_dq = False
    sub = 0                      # $( depth while inside double quotes
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if in_dq:
            if keep_dq:
                if ch == '"':
                    in_dq = False
                    out.append(" ")
                elif ch == "\\" and i + 1 < n \
                        and cmd[i + 1] in ('"', "\\", "$", "`"):
                    out.append(cmd[i:i + 2])   # escaped pair: live code
                    i += 1
                else:
                    out.append(ch)
            elif sub > 0:
                out.append(ch)           # live substitution: stays visible
                if ch == "(":
                    sub += 1
                elif ch == ")":
                    sub -= 1
            elif ch == "`":
                # backtick substitution: copy through the closing backtick
                out.append(ch)
                i += 1
                while i < n and cmd[i] != "`":
                    out.append(cmd[i])
                    i += 1
                if i < n:
                    out.append("`")
            elif ch == "$" and i + 1 < n and cmd[i + 1] == "(":
                out.append("$(")
                sub = 1
                i += 1
            elif ch == "\\" and i + 1 < n \
                    and cmd[i + 1] in ('"', "\\", "$", "`"):
                # v6.7: POSIX escape inside dquotes consumes BOTH chars as
                # a pair. Only \" was handled before, so the second
                # backslash of '\\' swallowed the real closing quote, the
                # span never closed and the whole command tail vanished
                # from screening (echo "a\\\" && rm -rf /" -> allow).
                out.append("  ")
                i += 1
            elif ch == '"':
                in_dq = False
                out.append(" ")
            else:
                out.append(" ")
        elif ch == '"':
            in_dq = True
            out.append(" ")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


# v6.7: interpreter forms whose double-quoted argument is EXECUTED code.
# For these, analyze() additionally screens an unmasked copy of the line.
_INTERPRETER_RX = re.compile(
    r"\b(?:sh|bash|zsh|dash|ksh|mksh)\s+-[a-z]*c\b"
    r"|\bcmd(?:\.exe)?\s+/c\b"
    r"|\b(?:powershell|pwsh)\b[^|;&]*\s-(?:command|c|encodedcommand)\b",
    re.IGNORECASE)


# v8.0: destructive command whose TARGET is hidden in quotes. The masked
# screening blanks dq content, so 'rm -rf "/etc"' looked harmless; this
# pattern matches the RAW line. It requires the quoted span to start with
# a sensitive target AND a destructive verb before the opening quote -
# messages like 'git commit -m "rm -rf /"' do not match (the quote there
# FOLLOWS the words, nothing sensitive follows the quote itself).
_QUOTED_TARGET_RX = re.compile(
    r"\b(?:rm|rmdir|shred|dd|mkfs(?:\.\w+)?|chmod|chown)\b"
    r"[^;&|\n\"]{0,80}[\"']"
    r"(?:/(?:etc|root|boot|bin|sbin|usr|var|lib|opt|srv)\b"
    r"|~/|~/|\$HOME|~|/)",
    re.IGNORECASE)


def _normalize_long_flags(text):
    """v6.5: GNU long options rewritten to the short destructive flags the
    patterns know, so 'rm --recursive --force /' screens exactly like
    'rm -rf /'. Only the two flags that matter for the rules are mapped."""
    text = re.sub(r"--recursive\b", "-r ", text, flags=re.IGNORECASE)
    text = re.sub(r"--force\b", "-f ", text, flags=re.IGNORECASE)
    return text


def segments(cmd):
    """Split a command line on shell chaining operators so each part can
    be screened on its own. Naive but deliberately conservative."""
    return [s for s in re.split(r"&&|\|\||;|\||\n|&", cmd) if s.strip()]


def analyze(cmd):
    """Screen one command string. Returns
    {"verdict": "allow"|"confirm"|"deny", "reasons": [str, ...]}."""
    res = {"verdict": "allow", "reasons": []}
    try:
        cmd = str(cmd or "")
        if not cmd.strip():
            return res
        masked = _masked(cmd)
        # v6.5: screen both the raw masked form and a long-flag-normalized
        # copy (--recursive/--force -> -r/-f), plus every chained segment
        # of each - hiding behind '&&' or GNU spelling must not help.
        norm = _normalize_long_flags(masked)
        texts = [masked, norm] + segments(masked) + segments(norm)
        # v8.0: a QUOTED destructive target used to vanish from screening
        # ('rm -rf "/etc"' screened as plain 'rm -rf' -> confirm -> allow
        # on the insecure web default). The quoted-target pattern below
        # denies exactly that shape (verb ... "target") on the RAW text;
        # quoted ARGUMENTS that merely CONTAIN scary words - the v6.7
        # doctrine that 'git commit -m "rm -rf /"' stays allowed - are
        # untouched, and interpreter payloads are screened unmasked
        # (v6.7: their double-quoted content is live code).
        if _QUOTED_TARGET_RX.search(cmd):
            res["verdict"] = "deny"
            res["reasons"].append("a quoted sensitive target of a "
                                  "destructive command")
            return res
        if _INTERPRETER_RX.search(cmd):
            live = _masked(cmd, keep_dq=True)
            lnorm = _normalize_long_flags(live)
            texts += [live, lnorm] + segments(live) + segments(lnorm)
        for text in texts:
            for rx, level, reason in _PATTERNS:
                if rx.search(text):
                    if _MAX_LEVEL[level] > _MAX_LEVEL[res["verdict"]]:
                        res["verdict"] = level
                    if reason not in res["reasons"]:
                        res["reasons"].append(reason)
                    if res["verdict"] == "deny":
                        return res
    except Exception as e:                      # the guard must not crash the caller
        try:
            import nova_log
            nova_log.soft("security.analyze", e)
        except Exception:
            pass
        res["verdict"] = "confirm"
        res["reasons"] = ["command could not be screened"]
    return res


def screen(cmd):
    """Public alias kept separate from analyze() for readability."""
    return analyze(cmd)


def decide(verdict, origin="repl", auto=False, secure=None):
    """Turn a screening verdict into an action for THIS call context:
    "block" | "ask" | "allow". `secure` overrides is_secure() (callers
    that already know the workspace pass the per-workspace flag)."""
    if verdict == "deny":
        return "block"
    if verdict == "confirm":
        if origin == "web":
            sec = is_secure() if secure is None else bool(secure)
            return "block" if sec else "allow"
        if auto:
            return "allow"          # explicit /auto opt-in, audited + warned
        return "ask"
    return "allow"


# --------------------------------------------------------------- audit trail
_AUDIT_LOCK = threading.Lock()
AUDIT_FILE_LIMIT = 512 * 1024
AUDIT_KEEP = 2000


def _audit_path(ws):
    try:
        return Path(ws) / ".nova" / "audit.jsonl"
    except Exception:
        return None


def audit(ws, kind, cmd="", origin="repl", verdict="allow", reason=""):
    """Append one line to <ws>/.nova/audit.jsonl. Never raises."""
    p = _audit_path(ws)
    if p is None:
        return
    rec = {"ts": round(time.time(), 3), "kind": str(kind)[:24],
           "origin": str(origin)[:24], "verdict": str(verdict)[:16],
           "cmd": str(cmd or "")[:300]}
    if reason:
        rec["reason"] = str(reason)[:200]
    try:
        with _AUDIT_LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            try:
                if p.stat().st_size > AUDIT_FILE_LIMIT:
                    lines = p.read_text(encoding="utf-8", errors="replace") \
                        .splitlines()[-AUDIT_KEEP:]
                    # v6.5: keep dropping the OLDEST quarter until the file
                    # is truly under the size cap (2000 worst-case lines
                    # used to settle permanently above it, forcing a full
                    # read+rewrite on every single audit call).
                    while lines and \
                            (sum(len(x) + 1 for x in lines) > AUDIT_FILE_LIMIT) \
                            and len(lines) > 10:
                        lines = lines[len(lines) // 4:]
                    # v6.7: unique scratch name (both processes rotate)
                    tmp = natom.tmp_name(p, tag="audittmp") if natom is not None \
                        else p.with_suffix(".jsonl.tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines) + ("\n" if lines else ""))
                    os.replace(tmp, p)
            except Exception:
                pass
    except Exception:
        pass


def audit_tail(ws, n=30):
    """Newest `n` audit entries (oldest first); [] when none/unreadable."""
    p = _audit_path(ws)
    if p is None or not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out = []
    for ln in lines[-max(1, int(n or 30)):]:
        try:
            e = json.loads(ln)
            if isinstance(e, dict):
                out.append(e)
        except Exception:
            continue
    return out


# --------------------------------------------------------------- rate limiting
class RateLimiter:
    """Token bucket per key (client IP). Thread-safe; stale buckets are
    pruned lazily so memory stays flat under address churn."""

    def __init__(self, per_minute=90, burst=30):
        self.rate = max(1.0, float(per_minute)) / 60.0    # tokens per second
        self.burst = max(1, int(burst))
        self._buckets = {}
        self._lock = threading.Lock()
        # v6.7: monotonic clock - a backwards wall-clock step (NTP, DST,
        # manual) used to drive token counts negative and wedge every
        # bucket until the clock caught back up.
        self._last_prune = time.monotonic()

    def allow(self, key, cost=1.0):
        now = time.monotonic()
        with self._lock:
            if now - self._last_prune > 300:
                stale = [k for k, (tokens, ts) in self._buckets.items()
                         if now - ts > 600]
                for k in stale:
                    self._buckets.pop(k, None)
                self._last_prune = now
            tokens, ts = self._buckets.get(key, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - ts) * self.rate)
            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                return True
            self._buckets[key] = (tokens, now)
            return False

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


class AttemptThrottle:
    """Failed-attempt lockout (brute-force guard for the access token).
    `max_fails` inside `window_s` seconds locks the key for `lockout_s`."""

    def __init__(self, max_fails=10, window_s=60, lockout_s=120):
        self.max_fails = max(1, int(max_fails))
        self.window_s = float(window_s)
        self.lockout_s = float(lockout_s)
        self._fails = {}                 # key -> [timestamps]
        self._locked_until = {}          # key -> ts
        self._lock = threading.Lock()
        # v8.10.1 fix: lazy prune like RateLimiter - both dicts used to
        # grow without bound under address churn (a key that fails a few
        # times and never returns kept its entry forever).
        self._last_prune = time.monotonic()

    def _prune_locked(self, now):
        """CALLER HOLDS THE LOCK. Drop stale entries: fail stamps older
        than the window and lockouts whose deadline has passed."""
        if now - self._last_prune <= 300:
            return
        stale_f = [k for k, stamps in self._fails.items()
                   if not stamps or now - max(stamps) > self.window_s]
        for k in stale_f:
            self._fails.pop(k, None)
        stale_l = [k for k, until in self._locked_until.items()
                   if until <= now]
        for k in stale_l:
            self._locked_until.pop(k, None)
        self._last_prune = now

    def check(self, key):
        """(allowed, retry_after_seconds)"""
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            until = self._locked_until.get(key, 0)
            if until > now:
                return False, int(until - now) + 1
            if until:
                self._locked_until.pop(key, None)
                self._fails.pop(key, None)
            return True, 0

    def fail(self, key):
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            stamps = [t for t in self._fails.get(key, []) if now - t < self.window_s]
            stamps.append(now)
            self._fails[key] = stamps
            if len(stamps) >= self.max_fails:
                # escalation: each new lockout doubles (capped at 30 min)
                prev = self._locked_until.get(key, 0)
                base = self.lockout_s if prev <= now else min(
                    (prev - now) * 2, 1800.0)
                self._locked_until[key] = now + base
                self._fails.pop(key, None)

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._fails.clear()
                self._locked_until.clear()
            else:
                self._fails.pop(key, None)
                self._locked_until.pop(key, None)


# Default web guards (module-level so tests and /secure can tune them).
# SECURE_API_LIMITER is the stricter profile used while secure mode is on.
API_LIMITER = RateLimiter(per_minute=300, burst=100)
SECURE_API_LIMITER = RateLimiter(per_minute=150, burst=50)
AUTH_THROTTLE = AttemptThrottle(max_fails=10, window_s=60, lockout_s=120)


def lockdown(ws=None, secure=True):
    """One-call hardening: secure mode (+ optional workspace persist).
    Returns a short human-readable summary of the new posture."""
    set_secure(secure, ws=ws)
    return ("secure mode %s" % ("ON" if secure else "OFF"))
