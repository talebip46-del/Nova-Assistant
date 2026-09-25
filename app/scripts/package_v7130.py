#!/usr/bin/env python3
"""Package Nova v7.13.0 - verify then zip.

Release probes (ALL must pass before the zip is written):
  1. version pin: nova.VERSION == 7.13.0 and no stray 7.12.0 pins
  2. full test suite green (re-run INSIDE packaging)
  3. py_compile every shipped python module
  4. node --check the inline web JS
  5. no emoji chars >= 0x2300 in web/index.html (the v6.9 pin)
  6. live-test artifact present (scripts/live_test_v7130.py compiles)
"""
import json
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # nova-assistant/
APP = ROOT / "app"
VERSION = "7.13.0"
OUT = Path("/home/z/my-project/download") / \
    ("nova_assistant_v" + VERSION + "_fixed.zip")

PASS, FAIL = [], []


def probe(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name +
          ((" | " + str(extra)[:140]) if extra and not cond else ""))


def main():
    print("== packaging Nova " + VERSION + " ==")

    # 1. version pins
    nova_src = (APP / "nova.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION = "(.+?)"', nova_src, re.M)
    probe("nova.py VERSION is " + VERSION, m and m.group(1) == VERSION,
          m and m.group(1))
    strays = [p.name for p in (APP / "tests").glob("test_*.py")
              if "7.12.0" in p.read_text(encoding="utf-8")]
    probe("no stray 7.12.0 pins in tests", not strays, strays)

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
    probe("py_compile all %d modules" %
          (len(list(APP.glob("*.py")))), not bad, bad[:3])

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
    bad_emoji = [hex(ord(c)) for c in html
                 if 0x2300 <= ord(c) < 0xE000 and
                 c not in "—–«»…·×"]
    probe("no emoji >= 0x2300 in index.html", not bad_emoji,
          bad_emoji[:6])

    # 6. live-test artifact
    probe("live test script present",
          (APP / "scripts" / "live_test_v7130.py").is_file())

    if FAIL:
        print("!! packaging aborted: %d probe(s) failed" % len(FAIL))
        return 1

    # ---- build the zip ------------------------------------------------
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    files = []
    for base in (ROOT,):
        for p in base.rglob("*"):
            rel = p.relative_to(ROOT)
            parts = set(rel.parts)
            if parts & {"__pycache__", ".git", ".pytest_cache",
                        ".nova", ".nova_backups", "node_modules",
                        "build", "dist"}:
                continue
            if rel.name == ".DS_Store" or rel.name.endswith(".pyc"):
                continue
            if p.is_file():
                files.append((p, rel))
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in sorted(files, key=lambda t: str(t[1])):
            z.write(p, str(rel))
    n = len(files)
    print("packed %d files -> %s (%.1f KB)" %
          (n, OUT, OUT.stat().st_size / 1024))
    with zipfile.ZipFile(OUT) as z:
        names = set(z.namelist())
    for must in ("app/nova.py", "app/nova_intel.py", "app/web_server.py",
                 "app/web/index.html", "app/tests/test_v7130_intel.py",
                 "app/scripts/live_test_v7130.py", "README.md",
                 "FIXES-7.13.0.fa.md"):
        probe("zip contains " + must, must in names)
    print("== %d/%d probes passed ==" % (len(PASS), len(PASS) + len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
