#!/usr/bin/env python3
"""Package Nova v8.11.0 "false alarm purge" - verify then zip (same
layout as the v8.10.1 release: FIXES/*.md at the zip root, app/... under
app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.11.0 (+ nova_think), codename,
     no stray 8.10.1 VERSION pins in tests
  2. py_compile every shipped python module
  3. release sanity: the v8.11.0 laws (the gates never refuse healthy
     batches: poison/CDN/setAttribute/namespace/staticmethod/SVG/<p>/
     $-hash/@import/backtick/ESM/design-context/prerun-argv; the
     router never downgrades blind; the stitch joins mid-token cuts;
     the digest survives re-folds; the /ctxset freeze; the loop brakes
     with the recent-norms memory; the /autofix command; the web done
     contract) + the v8.10/v8.9/v8.8/v8.7 laws still holding
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the v8.11 tests)
  6. vs v8.10.1: no file lost
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

ROOT = Path(__file__).resolve().parent.parent.parent   # project/
APP = ROOT / "app"
VERSION = "8.11.0"
_OUT_DIR = Path(os.environ.get(
    "NOVA_OUT_DIR", str(Path(__file__).resolve().parents[2] / "download")))
OUT = _OUT_DIR / ("nova_assistant_v" + VERSION + "_fixed.zip")
PREV_CANDIDATES = [
    _OUT_DIR / "nova_assistant_v8.10.1_fixed.zip",
    Path(__file__).resolve().parents[2] / ".." / "download"
    / "nova_assistant_v8.10.1_fixed.zip",
]
PREV = next((c for c in PREV_CANDIDATES if c.is_file()), PREV_CANDIDATES[0])
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".nova",
                "download"}
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
sys.path.insert(0, str(APP))
import nova  # noqa: E402
import nova_think as think  # noqa: E402

probe("nova.VERSION == 8.11.0", nova.VERSION == "8.11.0", nova.VERSION)
probe("nova_think.VERSION == 8.11.0", think.VERSION == "8.11.0",
      think.VERSION)
probe("codename is false alarm purge",
      nova.CODENAME == "false alarm purge", nova.CODENAME)
stray = []
for p in (APP / "tests").glob("test_*.py"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    if 'VERSION, "8.10.1"' in raw:
        stray.append(p.name)
probe("no stray 8.10.1 VERSION pins in tests", not stray, stray)

# ------------------------------------------------ probe 2: py_compile all
compile_ok = True
for p, rel in files:
    if rel.suffix == ".py" and str(rel).startswith("app"):
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:
            compile_ok = False
            probe("compile %s" % rel, False, e)
probe("all shipped .py compile", compile_ok)

# ------------------------------------------------ probe 3: release sanity
print("[probe 3] release sanity (v8.11.0 laws)")
os.environ.setdefault("NOVA_GUARDIAN", "")
os.environ.setdefault("NOVA_PROBE", "")

import nova_probe  # noqa: E402
import nova_guardian as gd  # noqa: E402
import nova_quality as nq  # noqa: E402
import nova_design  # noqa: E402
import nova_router  # noqa: E402
import nova_ctxengine as ce  # noqa: E402

# --- the poison law: pre-existing ws bugs never refuse a batch ---
d = tempfile.mkdtemp()
try:
    (Path(d) / "old.js").write_text(
        'document.getElementById("gone").textContent = "x";\n',
        encoding="utf-8")
    r = nova_probe.pre_apply_gate([("app.py", "print('hi')\n")], ws=d)
    probe("A1: pre-existing ws bug never refuses a healthy batch",
          not r["reject"] and not r["errors"])
    r = nova_probe.pre_apply_gate([("page.html", '<button onclick="go()">'
                                    "x</button>")])
    probe("A1: the batch's OWN dead wiring is still an error",
          r["reject"])

    # --- browser globals + CDN per-page demotion ---
    html = ('<!doctype html><html><body><button onclick="print()">p</button>'
            '<script>console.log("hi")</script></body></html>')
    probe("A2: onclick=print() passes",
          not nova_probe.pre_apply_gate([("page.html", html)])["reject"])
    cdn = ('<html><body><script src="https://cdn.example.com/x.js">'
           '</script><button onclick="auth2.signOut()">o</button></body>'
           "</html>")
    probe("A3: a CDN page's handler gap is advisory, not a reject",
          not nova_probe.pre_apply_gate([("page.html", cdn)])["reject"])
    local_dead = ('<html><body><button onclick="ghost()">x</button></body>'
                  "</html>")
    probe("A3: a local page's dead handler still rejects",
          nova_probe.pre_apply_gate([("page.html", local_dead)])["reject"])

    # --- setAttribute definitions ---
    js = ('el.setAttribute("id","box");\ndocument.getElementById("box");\n')
    probe("A4: setAttribute id is a definition",
          not nova_probe.pre_apply_gate([("app.js", js)])["reject"])

    # --- namespace packages ---
    d2 = tempfile.mkdtemp()
    (Path(d2) / "pkg").mkdir()
    (Path(d2) / "pkg" / "helpers.py").write_text("def hi():\n    return 1\n",
                                                 encoding="utf-8")
    r = nova_probe.pre_apply_gate(
        [("main.py", "from .pkg import helpers\nprint(helpers.hi())\n")],
        ws=d2)
    probe("A5: namespace package imports pass", not r["reject"])

    # --- staticmethod signature math ---
    py = ("class C:\n    @staticmethod\n    def util(a, b):\n"
          "        return a + b\n    def run(self):\n"
          "        return self.util(1, 2)\n")
    probe("A6: self.static_method() is not a TypeError",
          not nova_probe.pre_apply_gate([("m.py", py)])["reject"])
finally:
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(d2, ignore_errors=True)

# --- guardian: SVG / <p> / shell hash word boundary / json budget ---
probe("B1: explicit SVG closers are valid",
      not gd.validate("icon.svg",
                      '<svg><path d="M0 0"></path></svg>'
                      ).get("errors"))
probe("B1b: an unclosed <svg> is still flagged",
      bool(gd.validate("icon.svg", "<svg>").get("errors")))
probe("B2: sibling <p> autocloses",
      not gd.validate("page.html",
                      "<html><body><p>a\n<p>b\n</body></html>"
                      ).get("errors"))
probe("B2b: a stray </p> after sibling close no longer errors",
      not gd.validate("page.html", "<p>a<p>b</p></p>").get("errors"))
probe("B2c: a lone unclosed <p> stays strict",
      bool(gd.scan_tags("<p>unclosed")[0]))
probe("B3: $# is not a comment",
      not gd.validate("run.zsh",
                      "#!/bin/zsh\nif [ $# -eq 2 ]; then\n  echo ok\nfi\n"
                      ).get("errors"))
probe("B3b: 16#ff is not a comment",
      not gd.validate("calc.sh", "echo $(( 16#ff + 1 ))\n").get("errors"))
probe("B3c: glued python comments are legal (family-scoped law)",
      not gd.validate("m.py", "x = 1#(don't)\nprint(x)\n").get("errors"))
probe("B3d: a real unclosed [ in zsh still errors",
      bool(gd.validate("run.zsh",
                       "#!/bin/zsh\nif [ $# -eq 2 ; then\n  echo ok\nfi\n"
                       ).get("errors")))
import time as _t
_t0 = _t.time()
gd.parse_agent_json("{" * 19000)
probe("B4: guardian JSON scan is budgeted", _t.time() - _t0 < 2.0)

# --- quality: @import / backtick / ESM ---
ok, _p = nq.preapply_check("style.css",
                           "@import url('x.css');\n.card{color:red;\n")
probe("C1: a truncated @import sheet is caught", not ok)
ok, _p = nq.preapply_check("style.css", "@import url('x.css');\n")
probe("C1b: an import-only sheet still passes", ok)
ok, _p = nq.preapply_check(
    "doc.html", "<!doctype html><html><body><p>press `</p></body></html>"
    "<p>or ` here</p>")
probe("C2: lone-backtick prose does not reject the page", ok)
ok, _p = nq.preapply_check("doc.html",
                           "<!doctype html><html><body><p>hi</body>")
probe("C2b: a really truncated page is still caught", not ok)
ok, _p = nq.preapply_check(
    "mod.js", 'import { x } from "./y.js";\nexport const a = 1;\n')
probe("C3: an ESM .js module passes", ok)
ok, _p = nq.preapply_check("bad.js", "function { broken")
probe("C3b: broken js is still caught", not ok)

# --- design: usage-context implied layers ---
probe("D1: prose mention implies nothing",
      nova_design._implied_layers(
          "<p>add the class nv-glass-2 to any card.</p>") ==
      {"shadow": None, "glass": None, "motion": set(),
       "grain": None, "neon": None, "aurora": None})
probe("D1b: a real class attribute still implies",
      nova_design._implied_layers('<div class="nv-glass-3">')["glass"] == 0)
probe("D1c: data-class is not a class attribute",
      nova_design._implied_layers('<div data-class="nv-glass-3">') ==
      {"shadow": None, "glass": None, "motion": set(),
       "grain": None, "neon": None, "aurora": None})
probe("D2: nova-layers.css.old is not the layers link",
      not nova_design._LAYERS_LINK_HREF_RE.search(
          '<link href="nova-layers.css.old">'))

# --- router: never downgrade blind ---
probe("E1: hard task keeps a sizeless current model",
      nova_router.pick_local_model(
          "hard", ["llama3.1:latest", "qwen2.5:0.5b"],
          "llama3.1:latest") == "")
probe("E1b: hard still upgrades when provably bigger",
      nova_router.pick_local_model(
          "hard", ["qwen2.5:3b", "phi4:latest"], "qwen2.5:0.5b")
      == "qwen2.5:3b")

# --- prerun: argv files are data, pytest keeps all ---
probe("F1: python gen.py gates only the entry",
      nova._prerun_named_files("python gen.py skeleton.py") == ["gen.py"])
f2 = nova._prerun_named_files("pytest test_a.py test_b.py")
probe("F1b: pytest still gates every named test",
      "test_a.py" in f2 and "test_b.py" in f2)

# --- signature laws ---
a = nova.error_signature({"code": 1,
                          "output": "TypeError: expect 2 args, got 3"})
b = nova.error_signature({"code": 1,
                          "output": "TypeError: expect 3 args, got 2"})
probe("G1: two real errors keep distinct signatures", a != b)
a = nova.error_signature({"code": 1,
                          "output": 'File "m.py", line 7\nNameError: x'})
b = nova.error_signature({"code": 1,
                          "output": 'File "m.py", line 9\nNameError: x'})
probe("G1b: line drift still merges", a == b)
probe("G2: a WinError traceback line is runnable evidence",
      not nova.is_unrunnable_failure(
          1, "PermissionError: [WinError 5] Access is denied: 'x'"))
probe("G2b: shell not-found is still unrunnable",
      nova.is_unrunnable_failure(1, "sh: 1: deploy: not found"))
probe("G3: vite build is not a server",
      not nova._looks_like_server("npx vite build"))
probe("G3b: bare vite still is",
      nova._looks_like_server("npx vite"))

# --- ctxengine: the freeze law + re-digest ---
d3 = tempfile.mkdtemp()
try:
    err = ce.save_settings(d3, {"local_ctx": 10 ** 9})
    probe("H1: an all-invalid /ctxset writes nothing and admits it",
          bool(err) and not (Path(d3) / ".nova" / "context.json").exists())
    msg = {"role": "user",
           "content": ce._DIGEST_MARK + "\n#1 user: build a flask app\n"
                      "#1 decision: use bcrypt\n"}
    out = ce._extract_user(msg)
    probe("H2: a digest message re-digests goals and decisions",
          any("flask app" in ln for ln in out)
          and any("bcrypt" in ln for ln in out))
finally:
    import shutil
    shutil.rmtree(d3, ignore_errors=True)

# --- the loop brakes: the /autofix command exists ---
src_nova = (APP / "nova.py").read_text(encoding="utf-8")
probe("I1: /autofix is registered in the tool table",
      '"cmd": "/autofix"' in src_nova and "def cmd_autofix" in src_nova)
probe("I2: /clear re-arms the brake",
      "reset_fix_rounds(sess)   # v8.11" in src_nova)
probe("I3: the refusal guard anchors on the fresh flag",
      src_nova.count("sess.batch_refused = True") >= 3)
probe("I4: the stitch joins mid-token cuts",
      "raw_answer = (raw_answer or \"\") + answer" in src_nova)
probe("I5: the num_ctx keyword reaches sess-less callers",
      '"num_ctx": (num_ctx or _eff_ctx(sess))' in src_nova
      and src_nova.count("num_ctx=_eff_ctx(sess)") >= 4)

# --- v8.10/v8.9/v8.8 laws still hold (untouched surfaces) ---
ok, _p = nq.preapply_check("style.css", "/* just a comment */\n")
probe("v8.10.1 law: comments-only CSS still passes", ok)
probe("v8.8 law: PRERUN_EXIT sentinel kept",
      nova.PRERUN_EXIT == -2)

# --------------------------------------------- portability + hygiene law
bad_paths = [str(rel) for _p, rel in files
             if rel.name in ("Thumbs.db", "Desktop.ini")
             or rel.name.startswith("._")]
probe("no OS-junk files shipped", not bad_paths, bad_paths[:5])

# --------------------------------------------------------- probe 4: suite
print("[probe 4] full test suite (inside packaging)")
r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q",
                    "-p", "no:cacheprovider"],
                   cwd=str(APP), capture_output=True, text=True)
tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else "?"
probe("full suite green", r.returncode == 0 and " passed" in tail, tail)

# ----------------------------------------------------------------- write
# layout = the established release shape: FIXES/*.md + README + MAP at
# the zip ROOT, the app tree under app/ (same as v8.10.1 and before)
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


d1 = _digest(OUT)
probe("zip written", OUT.is_file(), OUT)

# ------------------------------------------------- probe 5: must-have paths
names = set(zipfile.ZipFile(OUT).namelist())
must = ["app/nova.py", "app/nova_think.py", "app/web_server.py",
        "app/web/index.html", "app/nova_guardian.py", "app/nova_probe.py",
        "app/nova_quality.py", "app/nova_design.py", "app/nova_router.py",
        "app/nova_ctxengine.py",
        "app/tests/test_v8110_stability.py",
        "app/tests/test_v8101_stability.py",
        "app/scripts/package_v8110.py",
        "FIXES-8.11.0.fa.md", "PROJECT-MAP.fa.md", "README.md",
        "app/fonts/index.json"]
missing = [m for m in must if m not in names]
probe("must-have paths present", not missing, missing)
probe("no caches in zip", not any("__pycache__" in n for n in names))

# ------------------------------------------------------ probe 6: vs v8.10.1
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist()
            if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names
                  and f != "FIXES-8.10.1.fa.md")
    probe("no file lost vs v8.10.1 (the old FIXES doc may rotate)",
          not lost, lost[:8])
    probe("fonts intact",
          sum(1 for n in names if n.endswith(".woff2")) >= 160)
else:
    print("  (skip) previous zip not found: %s" % PREV)

# ------------------------------------------- probe 7: FRESHNESS (twice)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p, rel in files:
        z.write(p, str(rel))
d2 = _digest(OUT)
probe("FRESHNESS: repack is byte-identical (run 1)", d2 == d1)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p, rel in files:
        z.write(p, str(rel))
d3 = _digest(OUT)
probe("FRESHNESS: repack is byte-identical (run 2)", d3 == d1)

# ----------------------------------------------------------------- verdict
print()
print("PROBES: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  FAIL:", f)
    sys.exit(1)
print("PACKAGE OK -> %s" % OUT)
