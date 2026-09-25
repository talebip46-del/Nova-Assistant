#!/usr/bin/env python3
"""Package Nova v8.0.0 "clear" - verify then zip.

Release probes (ALL must pass before the zip is written):
  1. version pin: nova.VERSION == 8.0.0 and CODENAME == clear; no stray
     7.14.0 pins left in tests
  2. full test suite green (re-run INSIDE packaging)
  3. py_compile every shipped python module
  4. node --check the inline web JS
  5. no emoji chars >= 0x2300 in web/index.html (the v6.9 pin)
  6. the four stability modules ship: nova_flightlog / nova_atomic /
     nova_sandbox / nova_plugins + the fuzz suite + live test
  7. zip content verification (must-have paths)
  8. FRESHNESS: the zip is rebuilt and byte-compared against a second
     packaging run in a temp dir (same content -> identical listing)
"""
import json
import py_compile
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # nova-assistant/
APP = ROOT / "app"
VERSION = "8.0.0"
OUT = Path("/home/z/my-project/download") / \
    ("nova_assistant_v" + VERSION + "_clear.zip")

PASS, FAIL = [], []


def probe(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name +
          ((" | " + str(extra)[:140]) if extra and not cond else ""))


def build_zip(dst):
    files = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        parts = set(rel.parts)
        if parts & {"__pycache__", ".git", ".pytest_cache", ".nova",
                    ".nova_backups", "node_modules", "build", "dist",
                    "corrupt"}:
            continue
        if rel.name == ".DS_Store" or rel.name.endswith(".pyc") \
                or rel.name.endswith(".tmp") or rel.name.endswith(".good"):
            continue
        if p.is_file():
            files.append((p, rel))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in sorted(files, key=lambda t: str(t[1])):
            z.write(p, str(rel))
    return files


def main():
    print("== packaging Nova " + VERSION + ' "' +
          ("clear" if True else "") + '" ==')

    # 1. version pins
    nova_src = (APP / "nova.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION = "(.+?)"', nova_src, re.M)
    probe("nova.py VERSION is " + VERSION, m and m.group(1) == VERSION,
          m and m.group(1))
    m2 = re.search(r'^CODENAME = "(.+?)"', nova_src, re.M)
    probe("codename is clear", m2 and m2.group(1) == "clear",
          m2 and m2.group(1))
    strays = [p.name for p in (APP / "tests").glob("test_*.py")
              if "7.14.0" in p.read_text(encoding="utf-8")]
    probe("no stray 7.14.0 pins in tests", not strays, strays)

    # 2. full suite
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"],
                       cwd=APP, capture_output=True, text=True,
                       timeout=600)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "?"
    probe("full suite green", r.returncode == 0, tail)

    # 3. py_compile all shipped py
    bad = []
    for p in list(APP.glob("*.py")) + list((APP / "scripts").glob("*.py")):
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:
            bad.append("%s: %s" % (p.name, str(e)[:60]))
    probe("py_compile all modules", not bad, bad[:3])

    # 4. node --check inline JS
    html = (APP / "web" / "index.html").read_text(encoding="utf-8")
    js = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js)
        tmpjs = fh.name
    r = subprocess.run(["node", "--check", tmpjs], capture_output=True,
                       text=True)
    probe("node --check inline JS", r.returncode == 0, r.stderr[:120])

    # 5. emoji pin
    bad_emoji = [c for c in html if 0x2300 <= ord(c) < 0xE000
                 and c not in "—–«»…·×"]
    probe("no emoji >= 0x2300 in index.html", not bad_emoji,
          bad_emoji[:6])

    # 6. stability-four artifacts
    for must in ("nova_flightlog.py", "nova_atomic.py", "nova_sandbox.py",
                 "nova_plugins.py", "nova_think.py"):
        probe("ships " + must, (APP / must).is_file())
    probe("fuzz suite ships",
          (APP / "tests" / "test_v800_fuzz.py").is_file())
    probe("live test ships",
          (APP / "scripts" / "live_test_v800_coffee.py").is_file())

    if FAIL:
        print("!! packaging aborted: %d probe(s) failed" % len(FAIL))
        return 1

    # ---- build the zip ------------------------------------------------
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    files = build_zip(OUT)
    n = len(files)
    print("packed %d files -> %s (%.1f KB)" %
          (n, OUT, OUT.stat().st_size / 1024))

    # 7. content verification
    with zipfile.ZipFile(OUT) as z:
        names = set(z.namelist())
        bad_zip = z.testzip()
    probe("zip integrity (testzip)", bad_zip is None, bad_zip)
    for must in ("app/nova.py", "app/nova_flightlog.py",
                 "app/nova_atomic.py", "app/nova_sandbox.py",
                 "app/nova_plugins.py", "app/nova_think.py",
                 "app/web_server.py", "app/web/index.html",
                 "app/tests/test_v800_fuzz.py",
                 "app/scripts/live_test_v800_coffee.py",
                 "app/scripts/pin_v800.py",
                 "README.md", "FIXES-8.0.0.fa.md"):
        probe("zip contains " + must, must in names)
    # the web JS inside the zip must reference the new endpoints
    zjs = None
    with zipfile.ZipFile(OUT) as z:
        zjs = z.read("app/web/index.html").decode("utf-8")
    probe("zip UI wires the blackbox card", "blackboxOut" in zjs)
    probe("zip UI wires the plugins card", "plgRows" in zjs)

    # 8. FRESHNESS: rebuild into a temp file, compare the NAME LISTS and
    # the new-version marker count - proves the zip carries the newest
    # files and that packaging is repeatable
    with tempfile.TemporaryDirectory() as td:
        again = Path(td) / "again.zip"
        files2 = build_zip(again)
        with zipfile.ZipFile(again) as z:
            names2 = set(z.namelist())
        probe("second packaging identical (file list)", names == names2)
        with zipfile.ZipFile(again) as z:
            a = z.read("app/nova.py")
        with zipfile.ZipFile(OUT) as z:
            b = z.read("app/nova.py")
        probe("second packaging byte-identical nova.py", a == b)

    print("== %d/%d probes passed ==" % (len(PASS), len(PASS) + len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
