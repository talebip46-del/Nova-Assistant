#!/usr/bin/env python3
"""Package Nova v8.1.0 - verify then zip (same ROOT-relative layout as
the v8.0.1 release: FIXES/*.md at the zip root, app/... under app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.1.0 (+ nova_think), no stray pins
  2. py_compile every shipped python module
  3. release sanity: AI image hooks wired, once() collector, verdict
     parser, verify/query fail-soft gates, gemini inline_data vision
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the new test file)
  6. vs v8.0.1: no file lost, woff2 intact
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
VERSION = "8.0.1"
VERSION = "8.1.0"
OUT = Path("/home/z/my-project/download") / \
    ("nova_assistant_v" + VERSION + "_fixed.zip")
PREV = Path("/home/z/my-project/download") / "nova_assistant_v8.0.1_fixed.zip"
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".nova"}

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
probe("nova.VERSION == 8.1.0", nova.VERSION == "8.1.0", nova.VERSION)
probe("nova_think.VERSION == 8.1.0", think.VERSION == "8.1.0", think.VERSION)
stray = subprocess.run(
    ["grep", "-rln", '"8\\.0\\.1"', str(APP / "tests")],
    capture_output=True, text=True).stdout.strip().splitlines()
probe("no stray 8.0.1 VERSION pins in tests", not stray, stray)

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
print("[probe] v8.1 AI image layers")
importlib.reload(nova)         # fresh import WITH the hooks (env popped)
import nova_images as ni       # noqa: E402
import nova_providers as nprov  # noqa: E402
from unittest import mock      # noqa: E402

probe("AI hooks wired", ni.AI_QUERY_HOOK is nova._img_ai_queries
      and ni.AI_VERIFY_HOOK is nova._img_ai_verify)
with mock.patch.object(nprov, "stream_chunks",
                       lambda *a, **k: iter(["x", "y"])):
    probe("once() collector", nprov.once({"kind": "openai"}, "m", []) == "xy")
probe("verdict parser", nova._img_ai_parse_verdict('{"ok": true}') == (True, "")
      and nova._img_ai_parse_verdict(
          '{"ok": false, "reason": "a cat"}') == (False, "a cat")
      and nova._img_ai_parse_verdict("garbage")[0] is None)
# unhook -> pure pre-8.1 defaults, then re-wire for the tail check
ni.AI_QUERY_HOOK = None
ni.AI_VERIFY_HOOK = None
probe("fail-soft gates (no hooks)",
      ni._ai_verify_ok("red rose", b"px") == (True, "")
      and ni._ai_extra_rungs("red rose") == [])
ni.AI_VERIFY_HOOK = nova._img_ai_verify
probe("approve carries verdict tail",
      ni._ai_verify_ok("red rose", b"px") == (True, "ai-approved"))
ni.AI_QUERY_HOOK = nova._img_ai_queries
g = nprov._gemini_build(
    [{"role": "user", "content": "hi", "images": ["QUJD"]}], 0.1)
probe("gemini inline_data vision",
      g["contents"][0]["parts"][1]["inline_data"]["data"] == "QUJD")

# --------------------------------------------------------- probe 4: suite
print("[probe] FULL test suite (inside packaging)")
r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q",
                    "-p", "no:cacheprovider"],
                   cwd=str(APP), capture_output=True, text=True,
                   timeout=1500)
tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "?"
probe("full suite green", r.returncode == 0, tail)
print("     " + tail)

# ----------------------------------------------------------------- write
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
must = ["app/nova.py", "app/nova_images.py", "app/nova_providers.py",
        "app/web_server.py", "app/web/index.html",
        "app/tests/test_v810_img_ai.py", "app/tests/test_v801_image_fill.py",
        "FIXES-8.1.0.fa.md", "README.md", "app/fonts/index.json",
        "app/nova_think.py"]
probe("must-have paths present",
      all(m in names for m in must),
      [m for m in must if m not in names])
probe("no caches in zip", not any("__pycache__" in n for n in names))

# ------------------------------------------------------ probe 6: vs v8.0.1
print("[probe] vs v8.0.1 release")
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist() if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names)
    probe("no file lost vs v8.0.1", not lost, lost[:8])
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
sys.exit(1 if FAIL else 0)
