#!/usr/bin/env python3
# =====================================================================
#  Nova Code - git helpers: auto-commit, commit messages, PR drafts (v5.0)
#
#  When the workspace happens to be a git repository (never forced):
#    - every apply batch is auto-committed with a generated message
#      (prefix `nova:`), so history mirrors every agent step;
#    - .nova/ + .nova_backups/ are excluded via .git/info/exclude
#      (does not touch the user's .gitignore);
#    - /pr collects the session's nova: commits + diff stat and asks the
#      model for a PR title + description.
#
#  The commit message DEFAULT is a deterministic heuristic (zero extra
#  model calls - minutes matter on weak hardware). The model only gets
#  involved for /pr and /commitmsg.
#
#  Every git call is bounded, -- safety-separated, fail-soft: a missing
#  git, a dirty index, a detached HEAD - nothing here may break a chat.
# =====================================================================
import shlex
import shutil
import subprocess
from pathlib import Path

GIT_TIMEOUT = 30
NOVA_PREFIX = "nova:"
EXCLUDE_LINES = (".nova/", ".nova_backups/", ".novaignore.bak")

# v7.5.0 COMMIT-PER-EDIT: when the workspace is NOT a git repo (the user
# never made one and never asked for one), Nova keeps its OWN history
# repo at .nova/history.git (separate git-dir, work-tree = the workspace).
# Every apply batch is committed there too - so /gitlog, per-edit history
# and time travel work EVERYWHERE, without polluting the user's project
# with a .git directory. NOVA_NO_GIT=1 turns the whole thing off.


def git_available():
    return bool(shutil.which("git"))


def is_repo(ws):
    """True when ws is inside a git work tree (top-level OR nested)."""
    if not git_available():
        return False
    code, out = _git(ws, "rev-parse --is-inside-work-tree")
    return code == 0 and out.strip() == "true"


# ---------------------------------------------------------------- v7.5.0
# the Nova-managed history repo (commit-per-edit for NON-repo workspaces)
def nova_repo_dir(ws):
    from pathlib import Path as _P
    return _P(ws) / ".nova" / "history.git"


def nova_repo_ready(ws):
    """True when the Nova history repo exists and has at least one commit."""
    d = nova_repo_dir(ws)
    try:
        return (d / "HEAD").is_file()
    except OSError:
        return False


def _nova_git(ws, args, timeout=GIT_TIMEOUT):
    """One git command against the Nova history repo (separate git-dir,
    work-tree = ws). Never raises."""
    try:
        if isinstance(args, str):
            args = shlex.split(args)
        proc = subprocess.run(
            ["git", "--git-dir=" + str(nova_repo_dir(ws)),
             "--work-tree=" + str(ws)] + [str(a) for a in args],
            cwd=str(ws), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout)
        return (proc.returncode, proc.stdout or "")
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return (-1, "")


def ensure_nova_repo(ws):
    """Idempotently create the Nova history repo + its own identity.
    Returns '' or an error note (non-fatal)."""
    if not git_available():
        return "git not installed"
    try:
        d = nova_repo_dir(ws)
        if not (d / "HEAD").is_file():
            d.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                ["git", "init", "--quiet", "--bare", str(d)],
                capture_output=True, text=True, timeout=GIT_TIMEOUT)
            if proc.returncode != 0:
                return (proc.stderr or "git init failed").strip()[:120]
            # a bare repo has no work-tree config - point it at ws and
            # give it its own identity so commits never fail on config
            _nova_git(ws, ["config", "core.bare", "false"])
            _nova_git(ws, ["config", "core.worktree", str(ws)])
        _nova_git(ws, ["config", "user.name", "Nova Code"])
        _nova_git(ws, ["config", "user.email", "nova@local"])
        _nova_git(ws, ["config", "commit.gpgsign", "false"])
        # bookkeeping must never be tracked by the history repo itself
        # (a bare init already SHIPS an info/exclude - the missing lines
        # are appended, the existing ones are never duplicated)
        info = d / "info"
        info.mkdir(parents=True, exist_ok=True)
        excl = info / "exclude"
        try:
            have = excl.read_text(encoding="utf-8", errors="replace") \
                if excl.is_file() else ""
            missing = [ln for ln in (".nova/", ".nova_backups/")
                       if ln not in have.splitlines()]
            if missing:
                with open(excl, "a", encoding="utf-8") as fh:
                    fh.write("\n# added by Nova Code\n"
                             + "\n".join(missing) + "\n")
        except OSError:
            pass
        return ""
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)[:120]


def nova_auto_commit(ws, message, paths):
    """Commit the applied paths into the NOVA history repo.
    Returns (committed, detail). Only the named paths are staged - never
    'git add -A' - so bookkeeping and stray files cannot leak in."""
    if not git_available() or not paths:
        return (False, "")
    err = ensure_nova_repo(ws)
    if err:
        return (False, err)
    specs = [str(p) for p in paths][:200]
    code, out = _nova_git(ws, ["add", "--", *specs])
    if code != 0:
        return (False, "git add failed")
    code, out = _nova_git(ws, ["commit", "-m", str(message), "--no-verify"])
    if code == 0:
        return (True, "committed")
    low = (out or "").lower()
    if "nothing to commit" in low or "nothing added" in low:
        return (False, "nothing to commit")
    return (False, "git commit failed")


def nova_log(ws, limit=30):
    """The history repo's commits (newest first) as [(hash, subject)]."""
    code, out = _nova_git(ws, ["log", "--oneline", "-n", str(int(limit))])
    rows = []
    if code == 0:
        for ln in out.splitlines():
            parts = ln.split(" ", 1)
            if len(parts) == 2:
                rows.append((parts[0], parts[1]))
    return rows


def history_mode(ws):
    """'repo' (user's own git) | 'nova' (managed history) | 'none'."""
    if not git_available():
        return "none"
    if is_repo(ws):
        return "repo"
    return "nova"


def commit_any(ws, message, paths):
    """Commit-per-edit entry point: the USER's repo when one exists,
    otherwise the Nova-managed history repo. Returns (ok, mode, detail)."""
    if not git_available() or not paths:
        return (False, "none", "git unavailable or nothing to commit")
    if is_repo(ws):
        ok, detail = auto_commit(ws, message, paths)
        return (ok, "repo", detail)
    ok, detail = nova_auto_commit(ws, message, paths)
    return (ok, "nova", detail)


def _git(ws, args, timeout=GIT_TIMEOUT):
    """Run one git command in ws -> (exit_code, stdout). Never raises.
    v6.2.1 fix: executed WITHOUT a shell now. The old `f"git {args}" +
    shell=True` form turned agent-written filenames into cmd.exe
    metacharacters on Windows - a file named `x&calc.exe` (POSIX-quoted,
    which cmd.exe ignores) executed calc.exe. `args` is an argv LIST; a
    string is still accepted and parsed with shlex (no shell ever)."""
    try:
        if isinstance(args, str):
            args = shlex.split(args)
        proc = subprocess.run(
            ["git"] + [str(a) for a in args], cwd=str(ws),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout)
        return (proc.returncode, proc.stdout or "")
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return (-1, "")


def ensure_excludes(ws):
    """Idempotently add Nova's bookkeeping dirs to .git/info/exclude.
    Returns '' or an error note (non-fatal)."""
    try:
        info = Path(ws) / ".git" / "info"
        # nested repos: ask git where its dir actually is
        code, out = _git(ws, "rev-parse --git-dir")
        gitdir = out.strip() if code == 0 and out.strip() else ".git"
        info = Path(ws) / gitdir / "info"
        info.mkdir(parents=True, exist_ok=True)
        excl = info / "exclude"
        have = excl.read_text(encoding="utf-8", errors="replace") if excl.is_file() else ""
        missing = [ln for ln in EXCLUDE_LINES if ln not in have.splitlines()]
        if missing:
            with open(excl, "a", encoding="utf-8") as fh:
                fh.write("\n# added by Nova Code (agent bookkeeping)\n"
                         + "\n".join(missing) + "\n")
        return ""
    except OSError as e:
        return str(e)


def heuristic_message(note, user_request, files_new, files_edited):
    """Deterministic commit message: what changed + why (the request's
    first line). Bounded, single line, no model call."""
    bits = []
    if files_new:
        bits.append("new " + ", ".join(files_new[:3]) +
                    (f" +{len(files_new) - 3}" if len(files_new) > 3 else ""))
    if files_edited:
        bits.append("edit " + ", ".join(files_edited[:3]) +
                    (f" +{len(files_edited) - 3}" if len(files_edited) > 3 else ""))
    what = "; ".join(bits) if bits else "workspace change"
    why = ""
    for line in str(user_request or "").strip().splitlines():
        line = line.strip()
        if line and not line.startswith(("/", "=", "#")):
            why = line[:72]
            break
    msg = f"{NOVA_PREFIX} {what}"
    if note:
        msg += f" ({str(note)[:40]})"
    if why:
        msg += f" - {why}"
    return msg[:150]


def auto_commit(ws, message, paths):
    """git add -- <paths> && git commit -m <message>.
    Returns (committed: bool, detail: str). Empty `paths` commits nothing.
    v6.2.1: argv lists - no shell, no quoting games with agent filenames."""
    if not is_repo(ws) or not paths:
        return (False, "")
    specs = [str(p) for p in paths][:200]
    code, out = _git(ws, ["add", "--", *specs])
    if code != 0:
        return (False, "git add failed")
    code, out = _git(ws, ["commit", "-m", str(message), "--no-verify"])
    if code == 0:
        return (True, "committed")
    low = (out or "").lower()
    if "nothing to commit" in low or "nothing added" in low:
        return (False, "nothing to commit")
    return (False, "git commit failed (is git configured? git config user.name/email)")


def session_log(ws, limit=30, all_nova=False):
    """This session's nova: commits (newest first) as [(hash, subject)].
    all_nova=True reads the managed history repo instead (which holds
    ONLY nova commits, so no grep filter is needed)."""
    if all_nova:
        return nova_log(ws, limit)
    code, out = _git(ws, ["log", "--oneline", "--grep=^" + NOVA_PREFIX,
                          "-n", str(int(limit))])
    rows = []
    if code == 0:
        for ln in out.splitlines():
            parts = ln.split(" ", 1)
            if len(parts) == 2:
                rows.append((parts[0], parts[1]))
    return rows


def session_diff_stat(ws, limit=30):
    """Cumulative diff stat over the last `limit` nova commits."""
    rows = session_log(ws, limit)
    if not rows:
        return ("", 0)
    oldest = rows[-1][0]
    code, out = _git(ws, ["diff", "--stat", oldest + "^..HEAD"])
    if code != 0:
        # v6.7 fix: the middle fallback `oldest..HEAD` (which excludes the
        # oldest commit's own changes) SHADOWED the v6.5 empty-tree fix -
        # when the first nova commit was the repo's ROOT commit, this
        # middle attempt succeeded with a PARTIAL stat and /pr described
        # the changes minus the first one. Go straight to the empty tree.
        code, out = _git(ws, ["diff", "--stat", _EMPTY_TREE, "HEAD"])
        if code != 0:
            code, out = _git(ws, ["diff", "--stat", oldest + "..HEAD"])
    return (out if code == 0 else "", len(rows))


# git's well-known empty-tree hash (stable across repos)
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def build_pr_prompt(ws, base=""):
    """Everything the model needs for a PR description. Returns
    (prompt, n_commits) or ('', 0) when there is nothing to describe."""
    stat, n = session_diff_stat(ws)
    if n == 0:
        return ("", 0)
    rows = session_log(ws)
    log_text = "\n".join(f"- {h} {s}" for h, s in rows)
    base_note = f"\nTarget base branch: {base}" if base else ""
    prompt = (
        "Write a pull-request description for the changes below. Output "
        "EXACTLY this shape and nothing else:\n"
        "TITLE: <one line, imperative, max 72 chars>\n"
        "BODY:\n<short what+why paragraph, then bullet points of the main "
        "changes, then a small 'How to test' section with concrete commands>\n\n"
        f"## Commits ({n})\n{log_text}\n\n## Diff stat\n"
        f"{stat[:4000]}{base_note}")
    return (prompt, n)
