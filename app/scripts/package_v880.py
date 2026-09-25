#!/usr/bin/env python3
"""Package Nova v8.8.0 "pre-run gate" - verify then zip (same layout
as the v8.7.0 release: FIXES/*.md at the zip root, app/... under app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.8.0 (+ nova_think), no stray pins
  2. py_compile every shipped python module
  3. release sanity: the v8.8 pre-run gate laws (executor-led scoping,
     redirect stripping, import closure, run_command refusal with zero
     shell side effects, error_signature normalization, the fix-loop
     brake) + the v8.7/v8.6/v8.5/v8.4/v8.3 laws
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the v8.8 tests)
  6. vs v8.7.0: no file lost (nothing intentionally dropped), woff2 intact
  7. FRESHNESS: repack + byte-identity, run TWICE
"""
import hashlib
import importlib
import os
import py_compile
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # nova-assistant/
APP = ROOT / "app"
VERSION = "8.8.0"
# output dir: <repo>/download by default, override with NOVA_OUT_DIR
_OUT_DIR = Path(os.environ.get(
    "NOVA_OUT_DIR", str(Path(__file__).resolve().parents[2] / "download")))
OUT = _OUT_DIR / ("nova_assistant_v" + VERSION + "_fixed.zip")
# the previous release may live in the repo download dir or the outer one
PREV_CANDIDATES = [
    _OUT_DIR / "nova_assistant_v8.7.0_fixed.zip",
    Path(__file__).resolve().parents[2] / ".." / "download"
    / "nova_assistant_v8.7.0_fixed.zip",
]
PREV = next((c for c in PREV_CANDIDATES if c.is_file()), PREV_CANDIDATES[0])
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".nova",
                "download"}   # release output dir lives inside the repo now
# files present in v8.7.0 that are INTENTIONALLY gone in this release
DROPPED_ON_PURPOSE = set()

PASS, FAIL = [], []


def probe(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name +
          ((" | " + str(extra)[:140]) if extra and not cond else ""))


# ----------------------------------------------------------------- collect
files = []
for p in ROOT.rglob("*"):
    rel = p.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS or ".nova" in rel.parts:
        continue
    if rel.name == ".DS_Store" or rel.name.endswith((".pyc", ".tmp", ".log",
                                                     ".good")):
        continue
    if p.is_file():
        files.append((p, rel))
files.sort(key=lambda t: str(t[1]))
print("collected %d files" % len(files))

# -------------------------------------------------------- probe 1: version
print("[probe] version pins")
os.environ["NOVA_NO_IMG_AI"] = "1"
sys.path.insert(0, str(APP))
import nova                    # noqa: E402
import nova_think as think     # noqa: E402
os.environ.pop("NOVA_NO_IMG_AI", None)
probe("nova.VERSION == 8.8.0", nova.VERSION == "8.8.0", nova.VERSION)
probe("nova_think.VERSION == 8.8.0", think.VERSION == "8.8.0", think.VERSION)
probe("codename is pre-run gate",
      nova.CODENAME == "pre-run gate", nova.CODENAME)
stray = subprocess.run(
    ["grep", "-rln", '"8\\.7\\.0"', str(APP / "tests")],
    capture_output=True, text=True).stdout.strip().splitlines()
probe("no stray 8.7.0 VERSION pins in tests", not stray, stray)

# ------------------------------------------------ probe 2: py_compile all
print("[probe] py_compile every shipped module")
import tempfile as _tf
compile_ok = True
with _tf.TemporaryDirectory() as _ctd:
    _cfile = str(Path(_ctd) / "c.pyc")
    for p, rel in files:
        if rel.suffix == ".py":
            try:
                py_compile.compile(str(p), doraise=True, cfile=_cfile)
            except Exception as e:
                compile_ok = False
                print("     compile fail:", rel, e)
probe("all shipped .py compile", compile_ok)

# ------------------------------------------------ probe 3: release sanity
print("[probe] v8.8 pre-run gate laws (this release's own pins)")
importlib.reload(nova)         # fresh import
import nova_guardian as gd     # noqa: E402
import nova_probe as pb        # noqa: E402
import nova_vision as vis      # noqa: E402

src_nova = (APP / "nova.py").read_text(encoding="utf-8")
src_ws = (APP / "web" / "index.html").read_text(encoding="utf-8")
src_wsv = (APP / "web_server.py").read_text(encoding="utf-8")

# --- extraction: only EXECUTED files gate (source-level behavior) ---
probe("interpreter-led command gates its entry",
      nova._prerun_named_files("python main.py") == ["main.py"],
      nova._prerun_named_files("python main.py"))
probe("non-executor command never gates",
      nova._prerun_named_files("git diff main.py") == []
      and nova._prerun_named_files("cat app.js") == [])
probe("compound command gates only the executor segment",
      nova._prerun_named_files("echo x && python main.py") == ["main.py"],
      nova._prerun_named_files("echo x && python main.py"))
probe("redirection target is stripped",
      nova._prerun_named_files("python build.py > out.py") == ["build.py"],
      nova._prerun_named_files("python build.py > out.py"))
probe("data/markup extensions stay out of scope",
      nova._prerun_named_files("node gen.js template.html") == ["gen.js"])

# --- the import closure + the gate itself (behavior, real temp ws) ---
with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    (ws / "main.py").write_text("import utils\nimport os\n", encoding="utf-8")
    (ws / "utils.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    files_c = nova._prerun_candidate_files(
        type("S", (), {"ws": ws})(), "python main.py")
    probe("closure follows the imported module (and never the stdlib)",
          "utils.py" in files_c and "main.py" in files_c
          and len(files_c) == 2, files_c)
    probs = nova._prerun_gate(type("S", (), {"ws": ws})(), "python main.py")
    probe("gate refuses the broken imported module",
          [r for r, _p in probs] == ["utils.py"], probs)
    (ws / "utils.py").write_text("def f():\n    pass\n", encoding="utf-8")
    probe("gate passes the repaired workspace",
          nova._prerun_gate(type("S", (), {"ws": ws})(),
                            "python main.py") == [])
with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    (ws / "pkg").mkdir()
    (ws / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (ws / "pkg" / "core.py").write_text("def c():\n    return 1\n",
                                        encoding="utf-8")
    (ws / "run.py").write_text("from pkg.core import c\n", encoding="utf-8")
    files_p = nova._prerun_candidate_files(
        type("S", (), {"ws": ws})(), "python run.py")
    probe("package __init__.py is followed on dotted imports",
          "pkg/__init__.py" in files_p and "pkg/core.py" in files_p, files_p)

# --- run_command integration: the shell NEVER sees a broken entry ---
class _MiniSess:
    pass
with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    (ws / "main.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    s = nova.Session(ws)
    s.model = "fake:7b"
    s._local_brain = lambda: True
    code = nova.run_command(s, "python main.py; echo RAN > ran.txt",
                            auto=True)
    probe("broken entry returns PRERUN_EXIT", code == nova.PRERUN_EXIT, code)
    probe("the shell never saw the command",
          not (ws / "ran.txt").exists())
    probe("evidence lands in last_failed with the prerun code",
          bool(s.last_failed) and s.last_failed.get("code") == "prerun",
          s.last_failed)
    probe("the report survives the unrunnable filter (autofix fires)",
          not nova.is_unrunnable_failure(code, s.last_failed["output"]))
    (ws / "main.py").write_text("print('hi')\n", encoding="utf-8")
    s.fix_rounds = 2
    code2 = nova.run_command(s, "python main.py", auto=True)
    probe("green run executes normally", code2 == 0, code2)
    probe("green run re-arms the fix brake", s.fix_rounds == 0, s.fix_rounds)

# --- the loop brakes ---
a = {"code": 1, "output": 'File "m.py", line 3\nSyntaxError: invalid syntax'}
b = {"code": 1, "output": 'File "m.py", line 7\nSyntaxError: invalid syntax'}
probe("error_signature absorbs shifted line numbers",
      nova.error_signature(a) == nova.error_signature(b))
probe("different errors keep different signatures",
      nova.error_signature(a) != nova.error_signature(
          {"code": 1, "output": "NameError: x"}))
sess_fb = type("S", (), {"fix_rounds": 0})()
[nova.bump_fix_round(sess_fb) for _ in range(nova.MAX_FIX_ROUNDS)]
probe("fix budget drains to zero",
      nova.fix_budget_left(sess_fb) == 0)
nova.reset_fix_rounds(sess_fb)
probe("reset re-arms the budget",
      nova.fix_budget_left(sess_fb) == nova.MAX_FIX_ROUNDS)
probe("web handler consults the brake before the skip chain",
      "if nova.fix_budget_left(sess) <= 0:" in src_wsv
      and src_wsv.index("if nova.fix_budget_left(sess) <= 0:")
      < src_wsv.index("elif nova.is_unrunnable_failure("))
probe("/autofix on re-arms the brake in the web face",
      "nova.reset_fix_rounds(sess)" in src_wsv)
probe("prerun_reject renders in the web UI",
      'ev.t === "prerun_reject"' in src_ws
      and "خطای سینتکس پیش از اجرا" in src_ws)
probe("gate sits after policy, before spawn",
      src_nova.index("verdict = npol.check_command(sess.policy, cmd)")
      < src_nova.index("prerun = _prerun_gate(sess, cmd)")
      < src_nova.index("proc = subprocess.Popen("))
probe("both autonomous loops consult the normalized signature",
      src_nova.count("error_signature(f) == last_norm") == 2)
probe("NOVA_FIX_ROUNDS env is clamped",
      1 <= nova.MAX_FIX_ROUNDS <= 8, nova.MAX_FIX_ROUNDS)

# --- v8.7 laws still hold (behavioral spot checks) ---
rep = gd.validate("m.rs", "struct S<'a> {\n    name: &'a str,\n}\n")
probe("v8.7: rust lifetimes pass the structure floor", not rep["errors"],
      rep["errors"])
rep = gd.validate("s.sh", "cat <<EOF > out.txt\nhello { world [\nEOF\necho\n")
probe("v8.7: heredoc with redirect is not bracket-scanned",
      not rep["errors"], rep["errors"])
e, _w = gd.scan_tags("<ul><li>one<li>two</ul>")
probe("v8.7: HTML5 optional-end tags auto-close", not e, e)
with tempfile.TemporaryDirectory() as td:
    (Path(td) / "boom.py").write_text("raise ValueError('nope')\n",
                                      encoding="utf-8")
    r = pb.smoke_one(Path(td), "boom.py")
probe("v8.7: a real crash still errors", r["level"] == "error", r)
probe("v8.7: vision gate asks the ACTIVE brain",
      '_VISION_ACTIVE.get("model")' in src_nova)
probe("v8.7: guardian_reject/probe_reject render in the web UI",
      'ev.t === "guardian_reject"' in src_ws
      and 'ev.t === "probe_reject"' in src_ws)

# --------------------------------------------- probe 3b: older release laws
print("[probe] v8.6/v8.5/v8.4/v8.3 laws (still hold)")
probe("the selection gate is installed on nova_images",
      nova.imgsys.AI_GATE_HOOK is nova._vision_selection_gate)
probe("/vision registered", '"cmd": "/vision"' in src_nova)
probe("deep defaults on + reject_deep on",
      pb.DEFAULTS.get("deep") is True
      and pb.DEFAULTS.get("reject_deep") is True)
probe("pre-apply wiring gate wired into offer_apply",
      "probe.pre_apply_gate(" in src_nova
      and "probe_reject" in src_nova)
rep5 = pb.pre_apply_gate([
    ("tool.py", "import requests\nprint('x')\n")])
probe("pip imports never false-reject", not rep5["reject"])
probe("guardian fleet >= 28 languages", gd.lang_count() >= 28,
      gd.lang_count())
probe("guardian pre-apply gate still wired",
      "guardian.review_batch(" in src_nova
      and "guardian_reject" in src_nova)
probe("v8.3: Ollama payload carries the SESSION window",
      '"num_ctx": (sess._effective_num_ctx()' in src_nova)
probe("v8.3: /ctxset still registered", '"cmd": "/ctxset"' in src_nova)

# ------------------------------------------- probe 3c: v8.2.1 portability law
print("[probe] v8.2.1 portability + hygiene (still holds)")
machine = "nova_project" + "/nova-assistant"
bad_tests = [p.name for p in sorted((APP / "tests").glob("test_*.py"))
             if machine in p.read_text(encoding="utf-8", errors="ignore")]
probe("no machine-specific paths in tests", not bad_tests, bad_tests)
bad_scripts = [p.name for p in sorted((APP / "scripts").glob("*.py"))
               if machine in p.read_text(encoding="utf-8", errors="ignore")]
probe("no machine-specific paths in scripts", not bad_scripts, bad_scripts)
probe("no stray duplicate FIXES doc in app/",
      not (APP / "FIXES-6.8.0.fa.md").exists())
probe("root FIXES-8.8.0 doc present", (ROOT / "FIXES-8.8.0.fa.md").is_file())
probe("README advertises 8.8.0",
      "8.8.0" in (ROOT / "README.md").read_text(encoding="utf-8"))

# --------------------------------------------------------- probe 4: suite
print("[probe] FULL test suite (inside packaging)")
r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q",
                    "-p", "no:cacheprovider"],
                   cwd=str(APP), capture_output=True, text=True,
                   timeout=1500)
tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "?"
probe("full suite green", r.returncode == 0, tail)
print("     " + tail)
failed_lines = [ln for ln in r.stdout.splitlines()
                if ln.startswith("FAILED")]
if failed_lines:
    print("     flaky/failing pins:")
    for ln in failed_lines[:10]:
        print("       " + ln)
    _log = OUT.parent / ("test_failures_" + VERSION + ".log")
    _log.parent.mkdir(parents=True, exist_ok=True)
    _log.write_text(r.stdout, encoding="utf-8")
    print("     full output -> " + str(_log))

# ----------------------------------------------------------------- write
OUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p, rel in files:
        z.write(p, str(rel))
print("packaged %d files -> %s (%.1f KB)"
      % (len(files), OUT, OUT.stat().st_size / 1024))


def _digest(path):
    z = zipfile.ZipFile(path)
    h = hashlib.sha256()
    for n in sorted(z.namelist()):
        h.update(n.encode())
        h.update(z.read(n))
    return h.hexdigest()


# ------------------------------------------------- probe 5: must-have paths
print("[probe] zip contents")
z = zipfile.ZipFile(OUT)
names = set(z.namelist())
must = ["app/nova.py", "app/nova_guardian.py", "app/nova_probe.py",
        "app/nova_ctxengine.py", "app/nova_vision.py",
        "app/nova_think.py", "app/nova_providers.py",
        "app/web_server.py", "app/web/index.html",
        "app/tests/test_v880_prerun.py",
        "app/tests/test_v870_stability.py",
        "app/tests/test_v860_vision.py",
        "app/tests/test_v850_bug_hunter.py",
        "app/tests/test_v840_code_guardian.py",
        "app/tests/test_v830_context_engine.py",
        "app/scripts/package_v880.py",
        "FIXES-8.8.0.fa.md", "PROJECT-MAP.fa.md", "README.md",
        "app/fonts/index.json"]
probe("must-have paths present",
      all(m in names for m in must),
      [m for m in must if m not in names])
probe("no caches in zip", not any("__pycache__" in n for n in names))
probe("no stray FIXES duplicate in zip",
      "app/FIXES-6.8.0.fa.md" not in names)

# ------------------------------------------------------ probe 6: vs v8.7.0
print("[probe] vs v8.7.0 release")
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist() if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names
                  and f not in DROPPED_ON_PURPOSE)
    probe("no file lost vs v8.7.0", not lost, lost[:8])
    probe("fonts intact",
          sum(1 for n in names if n.endswith(".woff2")) >= 160)
else:
    probe("prev release zip present", False, PREV)

# ------------------------------------------- probe 7: FRESHNESS (twice)
print("[probe] freshness: repack byte-identity x2")
d1 = _digest(OUT)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p, rel in files:
        z.write(p, str(rel))
d2 = _digest(OUT)
probe("repack 1 identical", d1 == d2)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p, rel in files:
        z.write(p, str(rel))
d3 = _digest(OUT)
probe("repack 2 identical", d2 == d3)

# ----------------------------------------------------------------- verdict
print("")
print("=" * 62)
print("PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED probes:")
    for n in FAIL:
        print("  - " + n)
    sys.exit(1)
