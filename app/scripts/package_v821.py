#!/usr/bin/env python3
"""Package Nova v8.2.1 - verify then zip (same ROOT-relative layout as
the v8.2.0 release: FIXES/*.md at the zip root, app/... under app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.2.1 (+ nova_think), no stray pins
  2. py_compile every shipped python module
  3. release sanity: the v8.2 cut-answer rescue (salvage law, resume
     message tail-last, done_reason=length contract, providers
     finish-reason capture, client splitThink salvage, FILE_RE
     line-anchored END) + the v8.2.1 portability/hygiene law
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the new audit test)
  6. vs v8.2.0: no file lost (the INTENTIONALLY dropped stray duplicate
     app/FIXES-6.8.0.fa.md is whitelisted), woff2 intact
  7. FRESHNESS: repack + byte-identity (same content -> identical
     listing digest), run TWICE
"""
import hashlib
import importlib
import os
import py_compile
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # nova-assistant/
APP = ROOT / "app"
VERSION = "8.2.1"
# output dir: <repo>/download by default, override with NOVA_OUT_DIR
_OUT_DIR = Path(os.environ.get(
    "NOVA_OUT_DIR", str(Path(__file__).resolve().parents[2] / "download")))
OUT = _OUT_DIR / ("nova_assistant_v" + VERSION + "_fixed.zip")
PREV = _OUT_DIR / "nova_assistant_v8.2.0_fixed.zip"
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".nova",
                "download"}   # release output dir lives inside the repo now
# files present in v8.2.0 that are INTENTIONALLY gone in this release
DROPPED_ON_PURPOSE = {"app/FIXES-6.8.0.fa.md"}

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
probe("nova.VERSION == 8.2.1", nova.VERSION == "8.2.1", nova.VERSION)
probe("nova_think.VERSION == 8.2.1", think.VERSION == "8.2.1", think.VERSION)
stray = subprocess.run(
    ["grep", "-rln", '"8\\.2\\.0"', str(APP / "tests")],
    capture_output=True, text=True).stdout.strip().splitlines()
probe("no stray 8.2.0 VERSION pins in tests", not stray, stray)

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
print("[probe] v8.2 cut-answer rescue layers")
importlib.reload(nova)         # fresh import
import nova_providers as nprov  # noqa: E402
from unittest import mock      # noqa: E402

# the salvage law: unclosed think + real work -> work survives
r = think.extract("=== THINK ===\nplan\n=== FILE: index.html ===\n<h1>x</h1>\n")
probe("salvage: unclosed think keeps the file",
      r.get("salvaged") and r["answer"].startswith("=== FILE: index.html ==="))
r2 = think.extract("=== THINK ===\nquoted\n=== FILE: ex.py ===\nx\n"
                   "=== END ===\nmore")
probe("salvage: quoted COMPLETE example stays reasoning",
      "ex.py" not in r2["answer"] and r2["open"])
msg = nova._resume_message("TAIL_MARKER_xxx", "req")
probe("resume message is tail-LAST (survives budget trim)",
      msg.rstrip().endswith("TAIL_MARKER_xxx"))
probe("resume message guides the closer",
      "=== END ===" in msg and "Continue EXACTLY" in msg)
probe("done_reason contract: stream_chat reads length as incomplete",
      "done_reason" in (APP / "nova.py").read_text(encoding="utf-8"))
nprov._openai_parse('{"choices":[{"delta":{},"finish_reason":"length"}]}', None)
probe("providers finish_reason captured (openai)",
      nprov.LAST_FINISH_REASON == "length")
nprov.LAST_FINISH_REASON = ""
src_ws = (APP / "web" / "index.html").read_text(encoding="utf-8")
probe("client splitThink salvage present",
      "workRe" in src_ws and "salvage" in src_ws)
src_nova = (APP / "nova.py").read_text(encoding="utf-8")
probe("FILE_RE END is line-anchored (no mid-line cut)",
      '(.*?)' in src_nova and "re.DOTALL | re.MULTILINE)" in src_nova)

# ------------------------------------------- probe 3b: v8.2.1 portability law
print("[probe] v8.2.1 portability + hygiene")
machine = "nova_project" + "/nova-assistant"
bad_tests = [p.name for p in sorted((APP / "tests").glob("test_*.py"))
             if machine in p.read_text(encoding="utf-8", errors="ignore")]
probe("no machine-specific paths in tests", not bad_tests, bad_tests)
bad_scripts = [p.name for p in sorted((APP / "scripts").glob("*.py"))
               if machine in p.read_text(encoding="utf-8", errors="ignore")]
probe("no machine-specific paths in scripts", not bad_scripts, bad_scripts)
probe("no stray duplicate FIXES doc in app/",
      not (APP / "FIXES-6.8.0.fa.md").exists())
probe("root FIXES-8.2.1 doc present", (ROOT / "FIXES-8.2.1.fa.md").is_file())
probe("README advertises 8.2.1",
      "8.2.1" in (ROOT / "README.md").read_text(encoding="utf-8"))

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
must = ["app/nova.py", "app/nova_think.py", "app/nova_providers.py",
        "app/web_server.py", "app/web/index.html",
        "app/tests/test_v820_coding_rescue.py",
        "app/tests/test_v821_audit.py",
        "app/scripts/live_test_v820_rescue.py",
        "FIXES-8.2.1.fa.md", "PROJECT-MAP.fa.md", "README.md",
        "app/fonts/index.json"]
probe("must-have paths present",
      all(m in names for m in must),
      [m for m in must if m not in names])
probe("no caches in zip", not any("__pycache__" in n for n in names))
probe("no stray FIXES duplicate in zip",
      "app/FIXES-6.8.0.fa.md" not in names)

# ------------------------------------------------------ probe 6: vs v8.2.0
print("[probe] vs v8.2.0 release")
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist() if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names
                  and f not in DROPPED_ON_PURPOSE)
    probe("no file lost vs v8.2.0 (duplicate doc whitelisted)", not lost,
          lost[:8])
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
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p, rel in files:
        z.write(p, str(rel))
d3 = _digest(OUT)
probe("repack identity run 1", d1 == d2, d1[:16] + " vs " + d2[:16])
probe("repack identity run 2", d2 == d3, d2[:16] + " vs " + d3[:16])

print("=" * 60)
print("RESULT: %d ok, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL PROBES GREEN ->", OUT)
