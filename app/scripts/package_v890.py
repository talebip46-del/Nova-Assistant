#!/usr/bin/env python3
"""Package Nova v8.9.0 "design layers" - verify then zip (same layout
as the v8.8.0 release: FIXES/*.md at the zip root, app/... under app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.9.0 (+ nova_think), no stray pins
  2. py_compile every shipped python module
  3. release sanity: the v8.9 design-layers laws (opt-in grammar,
     deterministic sheet, cascade-safe link injection, idempotency,
     union-merge growth, user file sanctity, offline/no-model-calls)
     + the v8.8/v8.7/v8.6/v8.5/v8.4/v8.3 laws
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the v8.9 tests)
  6. vs v8.8.0: no file lost (nothing intentionally dropped), woff2 intact
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
VERSION = "8.9.0"
# output dir: <repo>/download by default, override with NOVA_OUT_DIR
_OUT_DIR = Path(os.environ.get(
    "NOVA_OUT_DIR", str(Path(__file__).resolve().parents[2] / "download")))
OUT = _OUT_DIR / ("nova_assistant_v" + VERSION + "_fixed.zip")
# the previous release may live in the repo download dir or the outer one
PREV_CANDIDATES = [
    _OUT_DIR / "nova_assistant_v8.8.0_fixed.zip",
    Path(__file__).resolve().parents[2] / ".." / "download"
    / "nova_assistant_v8.8.0_fixed.zip",
]
PREV = next((c for c in PREV_CANDIDATES if c.is_file()), PREV_CANDIDATES[0])
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".nova",
                "download"}   # release output dir lives inside the repo now
# files present in v8.8.0 that are INTENTIONALLY gone in this release
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
probe("nova.VERSION == 8.9.0", nova.VERSION == "8.9.0", nova.VERSION)
probe("nova_think.VERSION == 8.9.0", think.VERSION == "8.9.0", think.VERSION)
probe("codename is design layers",
      nova.CODENAME == "design layers", nova.CODENAME)
stray = subprocess.run(
    ["grep", "-rln", '"8\\.8\\.0"', str(APP / "tests")],
    capture_output=True, text=True).stdout.strip().splitlines()
probe("no stray 8.8.0 VERSION pins in tests", not stray, stray)

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
print("[probe] v8.9 design-layers laws (this release's own pins)")
importlib.reload(nova)         # fresh import
import nova_design as dsg      # noqa: E402
import nova_guardian as gd     # noqa: E402
import nova_probe as pb        # noqa: E402
import nova_vision as vis      # noqa: E402
import nova_quality            # noqa: E402

src_nova = (APP / "nova.py").read_text(encoding="utf-8")

# --- the opt-in grammar (forgiving = options, never rules) ---
probe("parser: words + words for both scales",
      dsg.parse_layers("shadow=dramatic; glass=2, motion=float,fade-down")
      == {"shadow": 5, "glass": 2, "motion": {"float", "fade-down"}})
probe("parser: persian digits work",
      dsg.parse_layers("shadow=۴ glass=۳")["shadow"] == 4)
probe("parser: out-of-range clamps, 0 means off",
      dsg.parse_layers("shadow=9 glass=0")
      == {"shadow": 5, "glass": None, "motion": set()})
probe("parser: bare keys = utilities, bare preset = motion shorthand",
      dsg.parse_layers("shadow glass")["shadow"] == 0
      and dsg.parse_layers("float")["motion"] == {"float"})
probe("parser: off / garbage mean nothing",
      dsg.parse_layers("off") == {"shadow": None, "glass": None,
                                  "motion": set()}
      and dsg.parse_layers("fancy=stuff")["shadow"] is None)
probe("meta reader: attr order free, absent/valueless/off = None",
      dsg.layers_meta('<meta content="glass=sharp" name="nova-layers">')
      == {"shadow": None, "glass": 1, "motion": set()}
      and dsg.layers_meta('<meta name="nova-layers" content="off">') is None
      and dsg.layers_meta("<p>x</p>") is None)
probe("classes imply their layer (no meta needed)",
      dsg._implied_layers('<i class="nv-glass-3 nv-anim-float">')
      == {"shadow": None, "glass": 0, "motion": {"float"}}
      and dsg._implied_layers('<i class="nv-reveal nv-in">')["glass"] is None)
probe("merge: declared mood beats implied, stronger wins, motion unions",
      dsg._merge_specs({"shadow": 2, "glass": None, "motion": {"float"}},
                       {"shadow": 4, "glass": 3, "motion": set()})
      == {"shadow": 4, "glass": 3, "motion": {"float"}})

# --- the sheet: deterministic, lint-clean, only what was asked ---
sheet = dsg.layers_css({"shadow": 4, "glass": 2, "motion": {"float", "pop"}})
probe("sheet lint-clean + headered + only requested layers",
      nova_quality.preapply_check("nova-layers.css", sheet) == (True, None)
      and sheet.startswith("/* nova-layers.css")
      and ".nv-anim-float{" in sheet and ".nv-anim-glow{" not in sheet)
probe("sheet round-trips through the marker parser byte-identically",
      dsg.layers_css(dsg._spec_from_sheet(sheet)) == sheet)
probe("mood remap retunes the floor tokens site-wide",
      ":root{--shadow:var(--nv-shadow-4);--shadow-lg:var(--nv-shadow-5)}"
      in dsg.layers_css({"shadow": 4, "glass": None, "motion": set()}))
_g = dsg.layers_css({"shadow": None, "glass": 2, "motion": set()})
probe("glass: tint token + @supports fallback, color/font stay out",
      "--nv-glass-tint:255,255,255" in _g
      and "@supports not ((backdrop-filter:blur(1px))" in _g
      and "--brand" not in _g and "--font" not in _g)
_m = dsg.layers_css({"shadow": None, "glass": None,
                     "motion": {"float", "fade-down", "fade-up", "slide-in",
                                "pop", "glow"}})
probe("motion: every preset behind a reduced-motion guard + stagger",
      _m.count("@media (prefers-reduced-motion: no-preference)") == 7
      and ".nv-stagger>*:nth-child(1){" in _m)

# --- the integration: real design_polish on a real temp workspace ---
STYLED = ('<!doctype html><html><head><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width, '
          'initial-scale=1"><title>t</title>'
          '<link rel="stylesheet" href="css/style.css"></head>'
          '<body><h1>x</h1></body></html>')
with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    (ws / "index.html").write_text(
        STYLED.replace("</head>",
                       '<meta name="nova-layers" '
                       'content="shadow=dramatic; motion=float"></head>'),
        encoding="utf-8")
    (ws / "css").mkdir()
    (ws / "css" / "style.css").write_text("body{color:teal}",
                                          encoding="utf-8")
    extras, notes = dsg.design_polish(ws, ["index.html", "css/style.css"])
    names = [e[0] for e in extras]
    probe("opted-in page gets exactly one deterministic sheet",
          names.count("nova-layers.css") == 1
          and "shadow mood 5" in dict(extras)["nova-layers.css"]
          and ".nv-anim-float{" in dict(extras)["nova-layers.css"],
          names)
    html = (ws / "index.html").read_text(encoding="utf-8")
    probe("link lands before </head> and AFTER the page's own sheet",
          0 < html.index("css/style.css") < html.index("nova-layers.css")
          < html.index("</head>"))
    # a page that never opted in stays untouched
    ws2 = Path(td) / "clean"
    ws2.mkdir()
    (ws2 / "index.html").write_text(STYLED, encoding="utf-8")
    (ws2 / "css").mkdir()
    (ws2 / "css" / "style.css").write_text("body{color:red}",
                                           encoding="utf-8")
    e2, n2 = dsg.design_polish(ws2, ["index.html", "css/style.css"])
    probe("no opt-in = zero bytes, zero noise",
          e2 == [] and n2 == [] and not (ws2 / "nova-layers.css").exists())
with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    (ws / "index.html").write_text(
        STYLED.replace("</head>",
                       '<meta name="nova-layers" content="shadow=soft">'
                       "</head>"), encoding="utf-8")
    (ws / "css").mkdir()
    (ws / "css" / "style.css").write_text("body{color:red}",
                                          encoding="utf-8")
    e1, _ = dsg.design_polish(ws, ["index.html", "css/style.css"])
    for rel, c in e1:
        (ws / rel).write_text(c, encoding="utf-8")
    (ws / "index.html").write_text(
        STYLED.replace("</head>",
                       '<meta name="nova-layers" content="motion=pop">'
                       "</head>"), encoding="utf-8")
    e2_, n2_ = dsg.design_polish(ws, ["index.html", "css/style.css"])
    grew = dict(e2_).get("nova-layers.css", "")
    probe("union-merge: the sheet grows, never shrinks (turn 2)",
          "shadow mood 2" in grew and ".nv-anim-pop{" in grew, grew[:80])
    for rel, c in e2_:          # the hook writes the extras (real flow)
        (ws / rel).write_text(c, encoding="utf-8")
    e3, n3 = dsg.design_polish(ws, ["index.html", "css/style.css"])
    probe("second identical pass is fully silent (idempotent)",
          e3 == [] and n3 == [], n3)
with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    (ws / "nova-layers.css").write_text("/* mine */ .f{color:red}",
                                        encoding="utf-8")
    (ws / "index.html").write_text(
        STYLED.replace("</head>",
                       '<meta name="nova-layers" content="glass=2">'
                       "</head>"), encoding="utf-8")
    (ws / "css").mkdir()
    (ws / "css" / "style.css").write_text("body{color:red}",
                                          encoding="utf-8")
    eu, _ = dsg.design_polish(ws, ["index.html", "css/style.css"])
    probe("a user-made nova-layers.css is NEVER overwritten",
          "nova-layers.css" not in [e[0] for e in eu]
          and (ws / "nova-layers.css").read_text(
              encoding="utf-8").startswith("/* mine */"))
probe("the contract teaches the menu AND keeps it optional",
      "nova-layers" in dsg.DESIGN_CONTRACT
      and "options, never rules" in dsg.DESIGN_CONTRACT
      and "skip freely" in dsg.DESIGN_CONTRACT
      and "may omit the tag" in dsg.DESIGN_CONTRACT)
probe("the floor is byte-identical without a seed (v7.2 law intact)",
      dsg.floor_css(None) == dsg.NOVA_UI_CSS)

# --- v8.8 laws still hold (behavioral spot checks) ---
with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    (ws / "main.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    s = nova.Session(ws)
    s.model = "fake:7b"
    s._local_brain = lambda: True
    code = nova.run_command(s, "python main.py; echo RAN > ran.txt",
                            auto=True)
    probe("v8.8: broken entry returns PRERUN_EXIT, shell never runs",
          code == nova.PRERUN_EXIT and not (ws / "ran.txt").exists(), code)
a = {"code": 1, "output": 'File "m.py", line 3\nSyntaxError: invalid syntax'}
b = {"code": 1, "output": 'File "m.py", line 7\nSyntaxError: invalid syntax'}
probe("v8.8: error_signature absorbs shifted line numbers",
      nova.error_signature(a) == nova.error_signature(b))
probe("v8.8: gate sits after policy, before spawn",
      src_nova.index("verdict = npol.check_command(sess.policy, cmd)")
      < src_nova.index("prerun = _prerun_gate(sess, cmd)")
      < src_nova.index("proc = subprocess.Popen("))

# --- v8.7/v8.6/v8.5/v8.4/v8.3 laws still hold ---
rep = gd.validate("m.rs", "struct S<'a> {\n    name: &'a str,\n}\n")
probe("v8.7: rust lifetimes pass the structure floor", not rep["errors"],
      rep["errors"])
e, _w = gd.scan_tags("<ul><li>one<li>two</ul>")
probe("v8.7: HTML5 optional-end tags auto-close", not e, e)
with tempfile.TemporaryDirectory() as td:
    (Path(td) / "boom.py").write_text("raise ValueError('nope')\n",
                                      encoding="utf-8")
    r = pb.smoke_one(Path(td), "boom.py")
probe("v8.7: a real crash still errors", r["level"] == "error", r)
probe("v8.6: vision gate asks the ACTIVE brain",
      '_VISION_ACTIVE.get("model")' in src_nova)
probe("v8.5: pre-apply wiring gate wired into offer_apply",
      "probe.pre_apply_gate(" in src_nova and "probe_reject" in src_nova)
probe("v8.4: guardian pre-apply gate still wired",
      "guardian.review_batch(" in src_nova and "guardian_reject" in src_nova)
probe("v8.3: Ollama payload carries the SESSION window",
      '"num_ctx": (sess._effective_num_ctx()' in src_nova)

# --------------------------------------------- probe 3c: v8.2.1 portability law
print("[probe] v8.2.1 portability + hygiene (still holds)")
machine = "nova_project" + "/nova-assistant"
bad_tests = [p.name for p in sorted((APP / "tests").glob("test_*.py"))
             if machine in p.read_text(encoding="utf-8", errors="ignore")]
probe("no machine-specific paths in tests", not bad_tests, bad_tests)
probe("no stray duplicate FIXES doc in app/",
      not (APP / "FIXES-6.8.0.fa.md").exists())
probe("root FIXES-8.9.0 doc present", (ROOT / "FIXES-8.9.0.fa.md").is_file())
probe("README advertises 8.9.0",
      "8.9.0" in (ROOT / "README.md").read_text(encoding="utf-8"))

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
must = ["app/nova.py", "app/nova_design.py", "app/nova_guardian.py",
        "app/nova_probe.py", "app/nova_ctxengine.py", "app/nova_vision.py",
        "app/nova_think.py", "app/nova_providers.py",
        "app/web_server.py", "app/web/index.html",
        "app/tests/test_v890_design_layers.py",
        "app/tests/test_v880_prerun.py",
        "app/tests/test_v870_stability.py",
        "app/tests/test_v860_vision.py",
        "app/tests/test_v850_bug_hunter.py",
        "app/tests/test_v840_code_guardian.py",
        "app/tests/test_v830_context_engine.py",
        "app/scripts/package_v890.py",
        "FIXES-8.9.0.fa.md", "PROJECT-MAP.fa.md", "README.md",
        "app/fonts/index.json"]
probe("must-have paths present",
      all(m in names for m in must),
      [m for m in must if m not in names])
probe("no caches in zip", not any("__pycache__" in n for n in names))
probe("no stray FIXES duplicate in zip",
      "app/FIXES-6.8.0.fa.md" not in names)

# ------------------------------------------------------ probe 6: vs v8.8.0
print("[probe] vs v8.8.0 release")
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist() if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names
                  and f not in DROPPED_ON_PURPOSE)
    probe("no file lost vs v8.8.0", not lost, lost[:8])
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
