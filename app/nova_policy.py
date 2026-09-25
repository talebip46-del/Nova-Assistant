#!/usr/bin/env python3
# =====================================================================
#  Nova Code - workspace policy layer (v5.0)
#
#  TWO independent guards, one module, both per-workspace:
#
#  1) .novaignore (workspace root) - gitignore-style exclusion of paths
#     from the agent's VIEW: the project file map, [READ:], /read, /load,
#     /review and error-file collection all skip ignored paths. Writes are
#     still possible (the file simply never enters the model's context),
#     which is exactly what "keep build output / datasets / big assets out
#     of my context window" needs.
#
#     Supported syntax (a forgiving gitignore subset):
#       # comment            blank lines are ignored
#       name                 file or dir named `name` at ANY depth
#       *.log                fnmatch pattern on the BASE name, any depth
#       dir/                 trailing slash: matches DIRECTORIES only
#       /path                leading slash: anchored to the workspace root
#       a/b/c                a slash inside: anchored to the workspace root
#       !pattern             negation - the LAST matching rule wins
#
#  2) .nova/policy.json - per-command permission policy for shell runs:
#       {"default": "ask", "allow": ["python *"], "deny": ["rm -rf *"]}
#     `check(cmd)` returns "allow" | "deny" | "ask". DENY always wins over
#     allow. Patterns are case-insensitive fnmatch patterns against the
#     full command line (a rule without wildcards matches an exact command
#     or any command that STARTS with it - "git status" also matches
#     "git status --short").
#
#  Pure standard library. Every read/write is fail-soft: a broken file can
#  disable a restriction (never crash the agent) but is reported loudly.
# =====================================================================
import fnmatch
import json
import os
import re
import time
from pathlib import Path

NOVA_DIR = ".nova"

try:
    import nova_atomic as natom
except Exception:
    natom = None
IGNORE_FILE = ".novaignore"
POLICY_FILE = "policy.json"

MAX_PATTERN_LEN = 200
MAX_RULES = 100
MAX_POLICY_BYTES = 64_000


# --------------------------------------------------------------- .novaignore
def _norm_rel(rel):
    """Normalize a workspace-relative path to a clean posix form."""
    r = str(rel).strip().replace("\\", "/")
    r = re.sub(r"/{2,}", "/", r).strip("/")
    return r


class _Rule:
    __slots__ = ("negated", "anchored", "dir_only", "pattern", "raw")

    def __init__(self, raw):
        self.raw = raw
        pat = raw
        self.negated = pat.startswith("!")
        if self.negated:
            pat = pat[1:]
        self.dir_only = pat.endswith("/")
        pat = pat.rstrip("/")
        self.anchored = pat.startswith("/")
        if self.anchored:
            pat = pat.lstrip("/")
        self.anchored = self.anchored or "/" in pat
        self.pattern = _norm_rel(pat)

    def _pat_hits(self, path, is_dir):
        """Does the pattern match THIS exact path (a dir when is_dir)?"""
        if self.dir_only and not is_dir:
            return False
        if self.anchored:
            return fnmatch.fnmatchcase(path, self.pattern)
        # unanchored: basename or ANY path component matches
        return any(fnmatch.fnmatchcase(p, self.pattern) for p in path.split("/"))

    def hit(self, rel, is_dir):
        """True when this rule matches the normalized rel path.
        gitignore semantics: a rule matching an ANCESTOR directory ignores
        everything below it, so ancestors are checked first."""
        pat = self.pattern
        if not pat:
            return False
        parts = rel.split("/")
        for i in range(1, len(parts)):          # proper ancestor dirs
            if self._pat_hits("/".join(parts[:i]), True):
                return True
        return self._pat_hits(rel, is_dir)


class NovaIgnore:
    """Compiled .novaignore rules. matches() = last matching rule wins."""

    def __init__(self, rules=None, source=""):
        self.rules = rules or []
        self.source = source
        self.error = ""      # non-empty = file existed but could not be read

    @classmethod
    def load(cls, ws):
        path = Path(ws) / IGNORE_FILE
        ig = cls()
        try:
            if not path.is_file():
                return ig
            # v8.0: size-capped like load_policy - a runaway multi-GB
            # .novaignore used to be fully re-read (and re-parsed) on
            # every load while only the first rules are ever used.
            if path.stat().st_size > MAX_POLICY_BYTES:
                ig.error = "too large (over %d bytes) - ignored"
                ig.error = ig.error % MAX_POLICY_BYTES
                return ig
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            ig.error = str(e)
            return ig
        rules = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if len(line) > MAX_PATTERN_LEN:
                line = line[:MAX_PATTERN_LEN]
            try:
                rules.append(_Rule(line))
            except Exception:
                continue
            if len(rules) >= MAX_RULES:
                break
        ig.rules = rules
        return ig

    def matches(self, rel, is_dir=False):
        """True when `rel` (workspace-relative) is ignored. A parse problem
        inside one rule never breaks the others."""
        r = _norm_rel(rel)
        if not r or r == ".":
            return False
        hit = False
        for rule in self.rules:
            try:
                if rule.hit(r, is_dir):
                    hit = not rule.negated
            except Exception:
                continue
        return hit


# --------------------------------------------------------------- command policy
DEFAULT_POLICY = {"default": "ask", "allow": [], "deny": []}
VALID_DEFAULTS = ("ask", "allow", "deny")


def _clean_patterns(seq):
    out = []
    for p in seq if isinstance(seq, list) else []:
        if not isinstance(p, str):
            continue
        p = re.sub(r"\s+", " ", p).strip()
        if not p or len(p) > MAX_PATTERN_LEN:
            continue
        out.append(p.lower())
        if len(out) >= MAX_RULES:
            break
    return out


def _norm_policy(obj):
    """Validate/clean a loaded policy dict - anything malformed falls back
    to the safe default. Never trust a file the user may have hand-edited."""
    if not isinstance(obj, dict):
        return dict(DEFAULT_POLICY)
    default = obj.get("default", "ask")
    if default not in VALID_DEFAULTS:
        default = "ask"
    return {"default": default,
            "allow": _clean_patterns(obj.get("allow")),
            "deny": _clean_patterns(obj.get("deny"))}


def policy_path(ws):
    return Path(ws) / NOVA_DIR / POLICY_FILE


def load_policy(ws):
    """Command policy for this workspace (fail-soft -> safe defaults)."""
    p = policy_path(ws)
    try:
        if not p.is_file():
            return dict(DEFAULT_POLICY)
        if p.stat().st_size > MAX_POLICY_BYTES:
            return dict(DEFAULT_POLICY)
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return dict(DEFAULT_POLICY)
    return _norm_policy(obj)


def save_policy(ws, pol):
    """Atomic write; creates .nova/ on demand. Returns error string or ''."""
    pol = _norm_policy(pol)
    p = policy_path(ws)
    try:
        # v6.7: unique scratch name (cross-process tmp collision)
        if natom is not None:
            return natom.write_text_atomic(
                p, json.dumps(pol, indent=2, ensure_ascii=False))
        p.parent.mkdir(parents=True, exist_ok=True)
        # v8.0: unique scratch name in the fallback too (fixed policy.tmp
        # reintroduced the torn-write bug in degraded mode)
        tmp = p.with_name("%s.%d.%d.tmp" % (
            p.stem, os.getpid(), int(time.time() * 1000) % 1000000))
        tmp.write_text(json.dumps(pol, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)


def _rule_matches(pattern, cmd):
    """fnmatch against the whole command; a plain rule also matches any
    command that starts with it (so 'pytest' covers 'pytest -q tests/')."""
    c = re.sub(r"\s+", " ", cmd or "").strip().lower()
    if fnmatch.fnmatchcase(c, pattern):
        return True
    if not any(ch in pattern for ch in "*?["):
        return c == pattern or c.startswith(pattern + " ")
    return False


def check_command(pol, cmd):
    """'deny' | 'allow' | 'ask' for one command line. Deny always wins.
    Patterns are lowercased defensively here too, so even a policy dict
    that skipped save_policy() normalization stays case-insensitive."""
    cmd = (cmd or "").strip()
    if not cmd:
        return "ask"
    for pat in pol.get("deny", []):
        if _rule_matches(str(pat).lower(), cmd):
            return "deny"
    for pat in pol.get("allow", []):
        if _rule_matches(str(pat).lower(), cmd):
            return "allow"
    d = pol.get("default", "ask")
    return d if d in VALID_DEFAULTS else "ask"
