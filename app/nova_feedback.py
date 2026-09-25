#!/usr/bin/env python3
# =====================================================================
#  Nova Code - automatic feedback loop (v5.0)
#
#  Every apply is followed by a SILENT quality gate, no manual /check:
#
#    1. SYNTAX/CHECK pass on exactly the files that just changed
#       (.py -> py_compile, .js -> node --check, .json -> json.loads;
#       optional external linters: ruff / eslint / npx eslint when they
#       happen to be installed - never required)
#    2. TEST pass (optional, /autotest): one detected test command runs
#       - NOVA_TEST_CMD env wins
#       - pytest (when pytest is importable/available and tests exist)
#       - npm test (package.json has a "test" script, CI=1 so jest does
#         not sit in watch mode)
#       - unittest discover (python projects with test_*.py)
#       - make test (Makefile with a test: target + make on PATH)
#
#  The result is a compact REPORT for the user and - in auto/verify
#  flows - a machine-readable problem list the loop feeds straight back
#  to the model, so a broken edit gets fixed without a human round-trip.
#
#  Pure standard library. External tools are probed with a short timeout
#  and every failure is fail-soft: a missing linter can never break an
#  apply.
# =====================================================================
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

MAX_PROBLEM_CHARS = 600     # per-problem message cap
PROBE_TIMEOUT = 5           # seconds for "is this tool installed?" calls
RUN_TIMEOUT = 240           # default test-command timeout
OUTPUT_CAP = 20_000         # captured test output cap

PY_ERR_RE = re.compile(r"\(([^)]+\.py), (\w+)\)")


# --------------------------------------------------------------- tool probes
def which(tool):
    return shutil.which(tool)


def _run(cmd, cwd, timeout=RUN_TIMEOUT, env_extra=None):
    """Small capped runner -> (exit_code, output). Never raises."""
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), shell=isinstance(cmd, str),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=env)
        out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        return (proc.returncode, out[:OUTPUT_CAP])
    except subprocess.TimeoutExpired:
        return (-1, "(timed out after %ss)" % timeout)
    except OSError as e:
        return (-1, "(cannot run: %s)" % e)


# --------------------------------------------------------------- syntax checks
def _check_py(path):
    """py_compile one file -> error string or ''. The bytecode goes to a
    throwaway file in the system temp dir (Python 3.12 refuses /dev/null
    as cfile, and we must not litter the workspace with __pycache__)."""
    cfile = None
    try:
        cfile = os.path.join(tempfile.gettempdir(),
                             f"nova_pyc_{os.getpid()}_{threading.get_ident()}")
        py_compile.compile(str(path), doraise=True, cfile=cfile)
        return ""
    except py_compile.PyCompileError as e:
        msg = str(e).strip().splitlines()
        return msg[-1][:MAX_PROBLEM_CHARS] if msg else "syntax error"
    except (OSError, ValueError) as e:
        return str(e)[:MAX_PROBLEM_CHARS]
    finally:
        if cfile:
            try:
                os.unlink(cfile)
            except OSError:
                pass


def _check_js(path, node):
    if not node:
        return ""        # honest: no node -> no js check possible
    code, out = _run([node, "--check", str(path)], cwd=path.parent, timeout=30)
    if code == 0:
        return ""
    return (out.strip().splitlines() or ["syntax error"])[-1][:MAX_PROBLEM_CHARS]


def _check_json(path):
    try:
        json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return ""
    except ValueError as e:
        return str(e)[:MAX_PROBLEM_CHARS]
    except OSError as e:
        return str(e)[:MAX_PROBLEM_CHARS]


def check_files(ws, names, node=None):
    """Static check of specific files -> [(rel, problem)]. Files of types
    we cannot check honestly are simply not reported."""
    ws = Path(ws)
    if node is None:
        node = which("node") or which("node.exe")
    problems = []
    for name in names or []:
        rel = str(name).replace("\\", "/")
        low = rel.lower()
        p = ws / rel
        try:
            if not p.is_file():
                continue
            if low.endswith(".py"):
                err = _check_py(p)
            elif low.endswith(".js") or low.endswith(".mjs"):
                err = _check_js(p, node)
            elif low.endswith(".json"):
                err = _check_json(p)
            else:
                err = ""     # html/css/... : no honest cheap check
        except Exception as e:      # a broken checker must never break apply
            err = "checker error: " + str(e)[:100]
        if err:
            problems.append((rel, err))
    return problems


# --------------------------------------------------------------- tests
def detect_test_cmd(ws):
    """(cmd, source) for the best available test command, (None, '') when
    the workspace has no recognizable test setup."""
    ws = Path(ws)
    env_cmd = os.environ.get("NOVA_TEST_CMD", "").strip()
    if env_cmd:
        return (env_cmd, "NOVA_TEST_CMD env")

    has_tests_dir = (ws / "tests").is_dir() or (ws / "test").is_dir()
    py_tests = list(ws.glob("test_*.py")) + list(ws.glob("*_test.py"))
    if has_tests_dir or py_tests:
        # v6.5: a FROZEN exe (PyInstaller) must not auto-run tests:
        #  - a bundled 'pytest' console script does not exist on the user's
        #    machine (guaranteed failure), and
        #  - the unittest fallback used sys.executable, which IS the
        #    packaged NovaAssistant.exe - it relaunched Nova, which hung
        #    reading a pipe until the 240s RUN_TIMEOUT (every apply with a
        #    tests/ dir stalled 4 minutes and reported a bogus failure).
        if getattr(sys, "frozen", False):
            if os.environ.get("NOVA_TEST_CMD", "").strip():
                pass                      # env override still honored below
            else:
                return (None, "")
        # pytest if importable (the venv on this very machine has it)
        try:
            import pytest  # noqa: F401
            return ("pytest -q", "pytest detected")
        except Exception:
            pass
        if which("pytest"):
            return ("pytest -q", "pytest detected")
        return (f'"{sys.executable}" -m unittest discover -q',
                "unittest detected")

    pkg = ws / "package.json"
    if pkg.is_file():
        try:
            scripts = (json.loads(pkg.read_text(encoding="utf-8",
                                               errors="replace"))
                       .get("scripts") or {})
            if isinstance(scripts, dict) and scripts.get("test"):
                if which("npm") or which("npm.cmd"):
                    return ("npm test --silent", "package.json test script")
        except Exception:
            pass

    makefile = ws / "Makefile"
    if makefile.is_file() and which("make"):
        try:
            if re.search(r"(?m)^test\s*:", makefile.read_text(encoding="utf-8",
                                                              errors="replace")):
                return ("make test", "Makefile test target")
        except OSError:
            pass
    return (None, "")


def run_tests(ws, cmd=None, timeout=RUN_TIMEOUT):
    """Run the test command inside the workspace.
    Returns dict(ok, cmd, source, exit, report, passed, failed)."""
    cmd, source = (cmd, "explicit") if cmd else detect_test_cmd(ws)
    if not cmd:
        # v8.0 honesty fix: "nothing ran" used to be ok=True and flowed
        # into agent-loop evidence as a PASSING suite. It is None (n/a)
        # now; every caller already treats non-True as non-evidence.
        return {"ok": None, "cmd": None, "source": "", "exit": None,
                "report": "no test setup detected", "passed": None,
                "failed": None, "ran": False}
    code, out = _run(cmd, ws, timeout=timeout)
    tail = "\n".join((out or "").strip().splitlines()[-12:])
    passed, failed = _parse_summary(out)
    ok = (code == 0)
    report = f"{cmd} -> exit {code}"
    if passed is not None:
        report += f" ({passed} passed" + (f", {failed} failed)" if failed else ")")
    return {"ok": ok, "cmd": cmd, "source": source, "exit": code,
            "report": report, "tail": tail, "passed": passed, "failed": failed}


def _parse_summary(out):
    """Extract passed/failed counts from pytest/unittest/npm output."""
    passed = failed = None
    m = re.search(r"(\d+) passed", out or "")
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", out or "")
    if m:
        failed = int(m.group(1))
    m = re.search(r"Ran (\d+) tests?\s+(?:\n)?.*?(OK|FAILED)", out or "", re.DOTALL)
    if m and passed is None:
        total = int(m.group(1))
        if m.group(2) == "OK":
            passed, failed = total, 0
        else:
            failed = failed if failed is not None else total
    return (passed, failed)


# --------------------------------------------------------------- linters (optional)
def optional_lint(ws, names):
    """Run an installed-but-optional linter over changed files.
    Returns [(rel, problem)] - empty when no linter exists."""
    problems = []
    py = [n for n in names or [] if str(n).lower().endswith(".py")]
    js = [n for n in names or [] if str(n).lower().endswith((".js", ".mjs"))]
    ruff = which("ruff")
    if ruff and py:
        code, out = _run([ruff, "check", "--no-cache", "--select=E9,F",
                          "--quiet"] + [str(Path(ws) / n) for n in py],
                         cwd=ws, timeout=30)
        # v6.7: same guard the eslint branch got in v6.5 - a ruff build
        # that rejects our CLI options (or a wrapper printing a usage
        # error) used to turn every output line into a phantom lint
        # problem, sending the auto-fix loop to 'repair' healthy files.
        bad_invocation = any(marker in (out or "") for marker in
                             ("Invalid option", "invalid option",
                              "unexpected argument", "error: unrecognized",
                              "Usage:"))
        if code not in (0,) and not bad_invocation:
            for line in (out or "").splitlines():
                line = line.strip()
                if line:
                    problems.append(("lint(py)", line[:MAX_PROBLEM_CHARS]))
    if js and (which("eslint") or (Path(ws) / "node_modules" / ".bin" / "eslint").exists()):
        eslint = which("eslint") or str(Path(ws) / "node_modules" / ".bin" / "eslint")
        # v6.5: ESLint 9 (flat config) removed --no-eslintrc/--env - the
        # run exited non-zero with 'Invalid option' and every output line
        # became a phantom lint problem, sending the auto-fix loop to
        # 'repair' perfectly healthy JS. Probe the major version first.
        code, out = _run([eslint, "--version"], cwd=ws, timeout=10)
        try:
            eslint_major = int(re.search(r"v?(\d+)", out or "").group(1))
        except Exception:
            eslint_major = 0
        if eslint_major >= 9:
            cmd = [eslint] + [str(Path(ws) / n) for n in js]
        else:
            cmd = [eslint, "--no-eslintrc", "--env", "es2022",
                   "--parser-options=ecmaVersion:2022"] + \
                [str(Path(ws) / n) for n in js]
        code, out = _run(cmd, cwd=ws, timeout=30)
        if code not in (0,) and "Invalid option" not in (out or "") \
                and "invalid option" not in (out or ""):
            for line in (out or "").splitlines()[:8]:
                if line.strip():
                    problems.append(("lint(js)", line.strip()[:MAX_PROBLEM_CHARS]))
    return problems
