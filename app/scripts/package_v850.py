#!/usr/bin/env python3
"""Package Nova v8.5.0 "bug hunter" - verify then zip (same layout as
the v8.4.0 release: FIXES/*.md at the zip root, app/... under app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.5.0 (+ nova_think), no stray pins
  2. py_compile every shipped python module
  3. release sanity: the v8.5 bug hunter laws (pre-apply wiring gate,
     one-shot repair context, advisory-only local-brain completeness,
     smoke kill-switches, the browser probe's honest skips, /probe
     command, /api/settings probe fields, web panel) + the v8.4
     guardian laws + the v8.3 context engine law + the v8.2.1
     portability/hygiene law
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the probe module
     + its tests)
  6. vs v8.4.0: no file lost (nothing intentionally dropped), woff2 intact
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
VERSION = "8.5.0"
# output dir: <repo>/download by default, override with NOVA_OUT_DIR
_OUT_DIR = Path(os.environ.get(
    "NOVA_OUT_DIR", str(Path(__file__).resolve().parents[2] / "download")))
OUT = _OUT_DIR / ("nova_assistant_v" + VERSION + "_fixed.zip")
# the previous release may live in the repo download dir or the outer one
PREV_CANDIDATES = [
    _OUT_DIR / "nova_assistant_v8.4.0_fixed.zip",
    Path(__file__).resolve().parents[2] / ".." / "download"
    / "nova_assistant_v8.4.0_fixed.zip",
]
PREV = next((c for c in PREV_CANDIDATES if c.is_file()), PREV_CANDIDATES[0])
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".nova",
                "download"}   # release output dir lives inside the repo now
# files present in v8.4.0 that are INTENTIONALLY gone in this release
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
probe("nova.VERSION == 8.5.0", nova.VERSION == "8.5.0", nova.VERSION)
probe("nova_think.VERSION == 8.5.0", think.VERSION == "8.5.0", think.VERSION)
probe("codename is bug hunter", nova.CODENAME == "bug hunter",
      nova.CODENAME)
stray = subprocess.run(
    ["grep", "-rln", '"8\\.4\\.0"', str(APP / "tests")],
    capture_output=True, text=True).stdout.strip().splitlines()
probe("no stray 8.4.0 VERSION pins in tests", not stray, stray)

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
print("[probe] v8.5 bug hunter laws")
importlib.reload(nova)         # fresh import
import nova_probe as pb        # noqa: E402

src_nova = (APP / "nova.py").read_text(encoding="utf-8")
probe("probe module present", (APP / "nova_probe.py").is_file())
probe("pre-apply wiring gate wired into offer_apply",
      "probe.pre_apply_gate(" in src_nova
      and "probe_reject" in src_nova)
probe("repair context rides the NEXT user message (one shot)",
      "sess.probe_repair = None" in src_nova
      and "_prep_ctx = getattr(sess, \"probe_repair\", None)" in src_nova)
probe("post-apply behavior sweep feeds last_feedback",
      'last_feedback["probe"] = flat' in src_nova)
probe("feedback note carries hunter findings",
      "BUG HUNTER (" in src_nova)
probe("/probe registered", '"cmd": "/probe"' in src_nova)
probe("completeness never spends a cloud key",
      "_coding_brain_is_local" in src_nova
      and "_probe_chat_fn" in src_nova)
probe("/api/settings probe fields",
      all(k in (APP / "web_server.py").read_text(encoding="utf-8")
          for k in ("probe_on", "probe_wiring", "probe_smoke",
                    "probe_browser", "probe_review", "probe_reject",
                    "probe_reset")))
src_ws = (APP / "web" / "index.html").read_text(encoding="utf-8")
probe("web panel ids present",
      all(k in src_ws for k in ("probeState", "probeOn", "probeWiring",
                                "probeSmoke", "probeBrowser",
                                "probeReview", "probeReject",
                                "probeSave", "probeReset",
                                "renderProbePanel")))

# behavior spot-checks (offline, real bug hunter)
os.environ["NOVA_PROBE_RUN"] = "0"
os.environ["NOVA_PROBE_BROWSER"] = "0"
rep = pb.pre_apply_gate([
    ("index.html", '<button onclick="go()">x</button>'),
    ("app.js", 'document.getElementById("nope");')])
probe("wiring gate refuses a dead batch", rep["reject"])
probe("repair prompt speaks the FILE protocol",
      "=== FILE:" in rep["repair"]
      and "NOTHING was written" in rep["repair"])
rep2 = pb.pre_apply_gate([
    ("tool.py", "import requests\nprint('x')\n")])
probe("pip imports never false-reject", not rep2["reject"])
rep3 = pb.pre_apply_gate([
    ("index.html", '<link rel="stylesheet" href="css/style.css">'
                   '<h1>t</h1>')])
probe("missing stylesheet = advisory (the design floor heals it)",
      not rep3["reject"] and rep3["warns"])
rep4 = pb.run_post_apply(
    __import__("tempfile").mkdtemp(), ["x.txt"], request="", chat_fn=None)
probe("post-apply sweep: non-code batch stays pass",
      rep4["verdict"] == "pass")
probe("smoke kill-switch honored", pb.smoke_check("/tmp", [])["ran"] == 0)
os.environ.pop("NOVA_PROBE_RUN", None)
os.environ.pop("NOVA_PROBE_BROWSER", None)

# v8.4 guardian laws still hold
import nova_guardian as gd     # noqa: E402
probe("guardian fleet >= 28 languages", gd.lang_count() >= 28,
      gd.lang_count())
probe("guardian pre-apply gate still wired",
      "guardian.review_batch(" in src_nova
      and "guardian_reject" in src_nova)
probe("v8.3: Ollama payload carries the SESSION window",
      '"num_ctx": (sess._effective_num_ctx()' in src_nova)
probe("v8.3: /ctxset still registered", '"cmd": "/ctxset"' in src_nova)

# ------------------------------------------- probe 3b: v8.2.1 portability law
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
probe("root FIXES-8.5.0 doc present", (ROOT / "FIXES-8.5.0.fa.md").is_file())
probe("README advertises 8.5.0",
      "8.5.0" in (ROOT / "README.md").read_text(encoding="utf-8"))

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
        "app/nova_ctxengine.py", "app/nova_think.py",
        "app/nova_providers.py", "app/web_server.py",
        "app/web/index.html", "app/tests/test_v850_bug_hunter.py",
        "app/tests/test_v840_code_guardian.py",
        "app/tests/test_v830_context_engine.py",
        "app/scripts/package_v850.py",
        "FIXES-8.5.0.fa.md", "PROJECT-MAP.fa.md", "README.md",
        "app/fonts/index.json"]
probe("must-have paths present",
      all(m in names for m in must),
      [m for m in must if m not in names])
probe("no caches in zip", not any("__pycache__" in n for n in names))
probe("no stray FIXES duplicate in zip",
      "app/FIXES-6.8.0.fa.md" not in names)

# ------------------------------------------------------ probe 6: vs v8.4.0
print("[probe] vs v8.4.0 release")
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist() if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names
                  and f not in DROPPED_ON_PURPOSE)
    probe("no file lost vs v8.4.0", not lost, lost[:8])
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
print("READY: " + str(OUT))
sys.exit(0)
