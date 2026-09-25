#!/usr/bin/env python3
"""Package Nova v8.6.0 "bug net + vision" - verify then zip (same layout
as the v8.5.0 release: FIXES/*.md at the zip root, app/... under app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.6.0 (+ nova_think), no stray pins
  2. py_compile every shipped python module
  3. release sanity: the v8.6 vision laws (the detection ladder, the
     selection gate, /img + /imgdl approval, /vision command, web
     surface) + the v8.6 deep sweep laws + the v8.5 bug hunter laws +
     the v8.4 guardian + v8.3 context engine + v8.2.1 hygiene laws
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the vision module
     + its tests)
  6. vs v8.5.0: no file lost (nothing intentionally dropped), woff2 intact
  7. FRESHNESS: repack + byte-identity (same content -> identical
     listing digest), run TWICE
"""
import hashlib
import importlib
import os
import py_compile
import subprocess
import sys
import unittest.mock
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # nova-assistant/
APP = ROOT / "app"
VERSION = "8.6.0"
# output dir: <repo>/download by default, override with NOVA_OUT_DIR
_OUT_DIR = Path(os.environ.get(
    "NOVA_OUT_DIR", str(Path(__file__).resolve().parents[2] / "download")))
OUT = _OUT_DIR / ("nova_assistant_v" + VERSION + "_fixed.zip")
# the previous release may live in the repo download dir or the outer one
PREV_CANDIDATES = [
    _OUT_DIR / "nova_assistant_v8.5.0_fixed.zip",
    Path(__file__).resolve().parents[2] / ".." / "download"
    / "nova_assistant_v8.5.0_fixed.zip",
]
PREV = next((c for c in PREV_CANDIDATES if c.is_file()), PREV_CANDIDATES[0])
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".nova",
                "download"}   # release output dir lives inside the repo now
# files present in v8.5.0 that are INTENTIONALLY gone in this release
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
probe("nova.VERSION == 8.6.0", nova.VERSION == "8.6.0", nova.VERSION)
probe("nova_think.VERSION == 8.6.0", think.VERSION == "8.6.0", think.VERSION)
probe("codename is bug net + vision",
      nova.CODENAME == "bug net + vision", nova.CODENAME)
stray = subprocess.run(
    ["grep", "-rln", '"8\\.5\\.0"', str(APP / "tests")],
    capture_output=True, text=True).stdout.strip().splitlines()
probe("no stray 8.5.0 VERSION pins in tests", not stray, stray)

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
print("[probe] v8.6 vision laws")
importlib.reload(nova)         # fresh import
import nova_vision as vis      # noqa: E402
import nova_probe as pb        # noqa: E402

src_nova = (APP / "nova.py").read_text(encoding="utf-8")
src_ws = (APP / "web" / "index.html").read_text(encoding="utf-8")
src_wsv = (APP / "web_server.py").read_text(encoding="utf-8")

probe("vision module present", (APP / "nova_vision.py").is_file())
probe("the selection gate is installed on nova_images",
      "imgsys.AI_GATE_HOOK = _vision_selection_gate" in src_nova
      and nova.imgsys.AI_GATE_HOOK is nova._vision_selection_gate)
probe("/img pick rides the local-vision verdict",
      "verify=lambda raw: _img_ai_verify(query, raw)" in src_nova)
probe("/imgdl rides the human-integrity gate",
      "verify=_img_verify_human" in src_nova)
probe("AI rejection is never a silent save",
      "ai_rejected" in src_nova and "REJECTED" in src_nova)
probe("/vision registered", '"cmd": "/vision"' in src_nova)
probe("the dead name-regex shortcut is gone",
      "_IMG_VISION_RE" not in src_nova)
probe("detection ladder is honest about its rungs",
      '"ollama-show"' in (APP / "nova_vision.py").read_text(
          encoding="utf-8")
      and '"via": "name"' in (APP / "nova_vision.py").read_text(
          encoding="utf-8"))
probe("/api/info carries the vision block",
      '"vision": _flag_safe' in src_wsv)
probe("/api/settings vision fields",
      all(k in src_wsv for k in ("vision_approve", "vision_strict",
                                 "vision_reset")))
probe("web vision panel ids present",
      all(k in src_ws for k in ("visionState", "visionApprove",
                                "visionStrict", "visionSave",
                                "visionReset", "renderVisionPanel")))

# behavior spot-checks (offline, real ladder - the name rung only)
vis.clear_cache()
cap = nova._vision_capability({"kind": "ollama", "model": "llava:7b"},
                              "llava:7b")
probe("llava named brain detects as vision-capable (honest rung)",
      cap.get("vision") is True and cap.get("via") == "name", cap)
cap2 = nova._vision_capability({"kind": "ollama", "model": "coder:7b"},
                               "coder:7b")
probe("text-only name detects as not vision-capable",
      cap2.get("vision") is False, cap2)
probe("a successful show beats a vision name",
      vis._parse_show({"capabilities": ["completion"]})[0] is False)
probe("show capabilities vision -> ollama-show",
      vis._parse_show({"capabilities": ["vision"]})[0] is True)
ok_g, note_g = nova._vision_selection_gate("a rose")
probe("the gate never bricks the fill (offline default open)",
      ok_g is True, note_g)
os.environ["NOVA_VISION_SHOW"] = "0"
with __import__("unittest").mock.patch.object(
        nova, "_vision_settings_now",
        return_value={"approve": False}):
    ok_h, tail_h = nova._img_verify_human(b"jpeg")
probe("approve=off short-circuits the human gate",
      ok_h and tail_h == "approval-off", tail_h)
os.environ.pop("NOVA_VISION_SHOW", None)

print("[probe] v8.6 deep sweep laws (the bug hunter upgrade)")
probe("deep defaults on + reject_deep on",
      pb.DEFAULTS.get("deep") is True
      and pb.DEFAULTS.get("reject_deep") is True)
rep = pb.static_check([
    ("calc.py", "def add(a, b):\n    return a + b\n\n"
                "print(multiply(2, 3))\n")])
probe("deep sweep: undefined call is an error",
      any("multiply" in str(e) for e in rep["errors"]), rep["errors"])
rep2 = pb.static_check([
    ("calc.py", "def add(a, b):\n    return a + b\n"
                "def add(a, b):\n    return a - b\n")])
probe("deep sweep: duplicate def is an error",
      any("add" in str(e) for e in rep2["errors"]), rep2["errors"])
rep3 = pb.static_check([
    ("tool.py", "def used():\n    return 1\n\nprint(used())\n"
                "def never_called():\n    return 2\n")])
probe("deep sweep: an extra never-referenced function is a warn",
      any("never_called" in str(w) for w in rep3["warns"]), rep3["warns"])
rep4 = pb.pre_apply_gate([
    ("calc.py", "print(missing_helper(1))\n")])
probe("deep findings refuse the batch pre-apply",
      rep4["reject"], rep4.get("errors"))
probe("/api/settings deep fields",
      all(k in src_wsv for k in ("probe_deep", "probe_rejectdeep")))
probe("web deep checkboxes present",
      all(k in src_ws for k in ("probeDeep", "probeRejectDeep")))

print("[probe] v8.5 bug hunter laws (still hold)")
probe("pre-apply wiring gate wired into offer_apply",
      "probe.pre_apply_gate(" in src_nova
      and "probe_reject" in src_nova)
probe("/probe registered", '"cmd": "/probe"' in src_nova)
probe("completeness never spends a cloud key",
      "_coding_brain_is_local" in src_nova
      and "_probe_chat_fn" in src_nova)
rep5 = pb.pre_apply_gate([
    ("tool.py", "import requests\nprint('x')\n")])
probe("pip imports never false-reject", not rep5["reject"])

print("[probe] v8.4/v8.3/v8.2.1 laws (still hold)")
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
probe("root FIXES-8.6.0 doc present", (ROOT / "FIXES-8.6.0.fa.md").is_file())
probe("README advertises 8.6.0",
      "8.6.0" in (ROOT / "README.md").read_text(encoding="utf-8"))

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
        "app/tests/test_v860_vision.py",
        "app/tests/test_v850_bug_hunter.py",
        "app/tests/test_v840_code_guardian.py",
        "app/tests/test_v830_context_engine.py",
        "app/scripts/package_v860.py",
        "FIXES-8.6.0.fa.md", "PROJECT-MAP.fa.md", "README.md",
        "app/fonts/index.json"]
probe("must-have paths present",
      all(m in names for m in must),
      [m for m in must if m not in names])
probe("no caches in zip", not any("__pycache__" in n for n in names))
probe("no stray FIXES duplicate in zip",
      "app/FIXES-6.8.0.fa.md" not in names)

# ------------------------------------------------------ probe 6: vs v8.5.0
print("[probe] vs v8.5.0 release")
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist() if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names
                  and f not in DROPPED_ON_PURPOSE)
    probe("no file lost vs v8.5.0", not lost, lost[:8])
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
