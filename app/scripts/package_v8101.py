#!/usr/bin/env python3
"""Package Nova v8.10.1 "stability sweep II" - verify then zip (same
layout as the v8.10.0 release: FIXES/*.md at the zip root, app/... under
app/).

Release probes (ALL must pass before/after the zip is written):
  1. version pin: nova.VERSION == 8.10.1 (+ nova_think), codename,
     no stray 8.10.0 pins in tests
  2. py_compile every shipped python module
  3. release sanity: the v8.10.1 stability laws (the /api/info state
     dicts, the malformed-Origin 403, the if[[ / ${#var} / tag-selector
     / bare-import gate fixes, the scan_tags newline law, the qwen2-vl
     name regex, the throttle prune, the pinned flow fetch, the
     comments-only CSS pass, the hostile-ts fail-soft, the design range
     grammar, NOVA_AGENTS=1, the advisory review gaps, the panel
     display law) + the v8.10/v8.9/v8.8/... laws still holding
  4. full test suite green (re-run INSIDE packaging)
  5. zip content verification (must-have paths incl. the v8.10.1 tests)
  6. vs v8.10.0: no file lost (nothing intentionally dropped), woff2
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
VERSION = "8.10.1"
_OUT_DIR = Path(os.environ.get(
    "NOVA_OUT_DIR", str(Path(__file__).resolve().parents[2] / "download")))
OUT = _OUT_DIR / ("nova_assistant_v" + VERSION + "_fixed.zip")
PREV_CANDIDATES = [
    _OUT_DIR / "nova_assistant_v8.10.0_fixed.zip",
    Path(__file__).resolve().parents[2] / ".." / "download"
    / "nova_assistant_v8.10.0_fixed.zip",
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
print("[probe] version pins")
os.environ["NOVA_NO_IMG_AI"] = "1"
sys.path.insert(0, str(APP))
import nova                    # noqa: E402
import nova_think as think     # noqa: E402
os.environ.pop("NOVA_NO_IMG_AI", None)
probe("nova.VERSION == 8.10.1", nova.VERSION == "8.10.1", nova.VERSION)
probe("nova_think.VERSION == 8.10.1", think.VERSION == "8.10.1",
      think.VERSION)
probe("codename is stability sweep II",
      nova.CODENAME == "stability sweep II", nova.CODENAME)
stray = subprocess.run(
    ["grep", "-rln", '"8\\.10\\.0"', str(APP / "tests")],
    capture_output=True, text=True).stdout.strip().splitlines()
probe("no stray 8.10.0 VERSION pins in tests", not stray, stray)

# ------------------------------------------------ probe 2: py_compile all
print("[probe] py_compile every shipped module")
compile_ok = True
with tempfile.TemporaryDirectory() as _ctd:
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
print("[probe] v8.10.1 stability laws (this release's own pins)")
import nova_design as dsg      # noqa: E402
import nova_guardian as gd     # noqa: E402
import nova_probe as pb        # noqa: E402
import nova_quality            # noqa: E402
import nova_security as nsec   # noqa: E402
import nova_vision as vis      # noqa: E402
import nova_intel as intel     # noqa: E402
import web_server as wsrv      # noqa: E402

src_ws = (APP / "web_server.py").read_text(encoding="utf-8")
src_nova = (APP / "nova.py").read_text(encoding="utf-8")

# --- C1: the state blocks ship dicts, not booleans ---
probe("C1: _state_safe helper exists and is used for all four blocks",
      all(('"ctx": _state_safe(nova.web_ctx_state, sess)' in src_ws,
           '"guardian": _state_safe(nova.web_guardian_state, sess)' in src_ws,
           '"probe": _state_safe(nova.web_probe_state, sess)' in src_ws,
           '"vision": _state_safe(nova.web_vision_state, sess)' in src_ws)))
probe("C1: _state_safe fails soft to None",
      wsrv._state_safe(lambda: 1 / 0) is None)
probe("C1: _flag_safe kept for the boolean flags",
      '"fonts": _flag_safe' in src_ws and '"rag": _flag_safe' in src_ws)

# --- C3: malformed Origin is a clean False ---
class _H:
    def __init__(self, d):
        self.headers = d
probe("C3: malformed origin port -> False (no escape)",
      wsrv._same_origin(_H({"Origin": "http://127.0.0.1:abc",
                            "Host": "127.0.0.1:8765"})) is False)
probe("C3: valid same-origin still True",
      wsrv._same_origin(_H({"Origin": "http://127.0.0.1:8765",
                            "Host": "127.0.0.1:8765"})) is True)

# --- guarded module endpoints ---
probe("C1-class: assign/clear + platforms/scan + knowledge/reset guarded",
      all(_g for _g in (
          src_ws.find('path == "/api/assign/clear"') > 0
          and "except Exception" in src_ws[
              src_ws.find('path == "/api/assign/clear"'):
              src_ws.find('path == "/api/assign/clear"') + 700],
          src_ws.find('path == "/api/platforms/scan"') > 0
          and "except Exception" in src_ws[
              src_ws.find('path == "/api/platforms/scan"'):
              src_ws.find('path == "/api/platforms/scan"') + 700],
          src_ws.find('path == "/api/knowledge/reset"') > 0
          and "except Exception" in src_ws[
              src_ws.find('path == "/api/knowledge/reset"'):
              src_ws.find('path == "/api/knowledge/reset"') + 700])))

# --- B1/B4: the shell gate only rejects real defects ---
_sh_ok = gd.validate("t.sh", "#!/usr/bin/env bash\n"
                     "if [[ -f config ]]; then\n  source config\nfi\n")
probe("B1: `if [[ ` is valid bash", not _sh_ok["errors"], _sh_ok["errors"])
_sh_bad = gd.validate("t.sh", "#!/usr/bin/env bash\nif [-f x]; then\nfi\n")
probe("B1: `if [-f` still caught",
      any("missing space" in e[1] for e in _sh_bad["errors"]))
_zsh = gd.validate("t.zsh", "#!/bin/zsh\nlen=${#var}\necho $len\n")
probe("B4: ${#var} is not a comment", not _zsh["errors"], _zsh["errors"])
_nest = gd.validate("t.zsh", "#!/bin/zsh\nn=$((${#a}+1))\n")
probe("B4: nested parameter expansion balances",
      not _nest["errors"], _nest["errors"])

# --- B2/B3: the probe gate only rejects real defects ---
_wgood = pb.wiring_check([
    ("index.html", '<html><body><form id="m"><button>g</button></form>'
     '<script src="a.js"></script></body></html>'),
    ("a.js", 'document.querySelector("form").addEventListener('
     '"submit", function(){});\n'
     'document.querySelectorAll("button").forEach(function(b){});')])
probe("B2: tag selectors are not dead ids", not _wgood["errors"],
      _wgood["errors"])
_wbad = pb.wiring_check([("a.js",
                          'document.querySelector("#ghost");')])
probe("B2: #ghost still caught",
      any("#ghost" in e[2] for e in _wbad["errors"]))
_igood = pb.wiring_check([
    ("pkg/main.py", "from . import utils\nutils.go()\n"),
    ("pkg/utils.py", "def go():\n    return 1\n")])
probe("B3: bare relative import resolves the sibling",
      not _igood["errors"], _igood["errors"])
_ibad = pb.wiring_check([
    ("pkg/main.py", "from . import missing_m\nmissing_m.go()\n"),
    ("pkg/utils.py", "x = 1\n")])
probe("B3: truly missing module still caught",
      any("not found" in e[2] for e in _ibad["errors"]))

# --- B7/B8: line numbers + utf-8 tool decode ---
_tags = gd.scan_tags('<html>\n<body>\n<script>\nvar a = 1;\n</script>\n'
                     '<div>\n<span>oops\n</body>\n</html>\n', "i.html")
probe("B7: line numbers survive a multi-line script",
      any("line 6" in e[1] for e in _tags[0]), _tags[0])
probe("B8: tool subprocess decodes utf-8/replace",
      'encoding="utf-8", errors="replace"' in
      (APP / "nova_guardian.py").read_text(encoding="utf-8"))

# --- B5/B6: silent capabilities found again ---
import shutil
if shutil.which("g++") or shutil.which("gxx"):
    probe("B5: gxx resolves the C++ validator",
          "gxx" in gd.tools_available(), gd.tools_available())
for nm in ("qwen2-vl:7b", "qwen2.5-vl:3b"):
    probe("B6: %s matches the vision name regex" % nm,
          bool(vis.NAME_RE.search(nm)))
probe("B6: qwen2-coder stays text-only",
      not vis.NAME_RE.search("qwen2-coder:7b"))

# --- D1: the throttle prunes ---
import time as _t
_th = nsec.AttemptThrottle(max_fails=3, window_s=0.05, lockout_s=0.05)
_th.fail("a")
_th._last_prune = _t.monotonic() - 400
_t.sleep(0.06)
_th.check("c")
probe("D1: stale throttle entries pruned", "a" not in _th._fails)

# --- D2/D3/D5: flow stack, css pass, hostile ts ---
_flow = (APP / "nova_modules" / "flow.py").read_text(encoding="utf-8")
_i, _j = _flow.find("def _http(self, st, w):"), _flow.find(
    "def _condition(self, w):")
probe("D2: the flow http step fetches through the pinned stack",
      "http_get_bytes" in _flow
      and "urllib.request.urlopen" not in _flow[_i:_j])
probe("D3: comments-only CSS passes preapply",
      nova_quality.preapply_check("s.css", "/* nothing */\n") == (True, None))
probe("D3: brace-broken CSS still blocked",
      nova_quality.preapply_check("s.css", ".a { color: red")[0] is False)
_mem = intel.SemanticMemory(Path(tempfile.mkdtemp()) / "mem.json")
_mem.records = [{"id": "a", "text": "hello world", "kind": "fact",
                 "tags": [], "tf": {"hello": 1}, "ts": "2024-01-01"}]
probe("D5: a hostile ts never crashes recall",
      isinstance(_mem.recall("hello", k=1), list))

# --- design range grammar + advisory review gaps + env honesty ---
_rng = dsg.parse_layers("shadow=1..5; glass=1..4; grain=1..4; neon=1..3; "
                        "aurora=1..3; motion=float|all")
probe("design: the contract's own range grammar declares level 0",
      all(_rng[k] == 0 for k in ("shadow", "glass", "grain", "neon",
                                 "aurora")) and _rng["motion"])
_sane = dsg.parse_layers("shadow=2")
probe("design: the sane form is unchanged", _sane["shadow"] == 2)
_rep = pb.findings_summary({"review": {"gaps": [("x", "y")]},
                            "wiring": {}, "static": {}, "smoke": {},
                            "browser": {}})
probe("probe: completeness-review gaps are advisory warns",
      _rep and all(lv == "warn" for *_x, lv in _rep))
_src_sub = (APP / "nova_subagent.py").read_text(encoding="utf-8")
probe("subagent: NOVA_AGENTS=1 is honored (no max(2,...) floor)",
      "max(2, env_n" not in _src_sub)

# --- the panel display law + repair leak + undo law ---
_src_html = (APP / "web" / "index.html").read_text(encoding="utf-8")
probe("C2: the todo/changes panels are shown explicitly",
      _src_html.count('panel.style.display = "block";') == 2
      and 'cp.style.display = "block"' in _src_html)
probe("S1: set_workspace resets the one-shot repair contexts",
      "self.guardian_repair = None" in src_nova
      and "self.probe_repair = None" in src_nova)
probe("A3: the snapshot undo clears the legacy batch",
      src_nova.find('if res["undone"]:') <
      src_nova.find("# legacy fallback")
      and "sess.last_batch = []" in src_nova[
          src_nova.find('if res["undone"]:'):
          src_nova.find("# legacy fallback")])
probe("A1: the merged RAW answer is the truth after auto-continue",
      "answer = _td[\"answer\"] if _td is not None else raw_answer"
      in src_nova)

# --- v8.10 laws still hold (texture & neon untouched) ---
probe("v8.10: grain/neon/aurora grammar + sheet + round-trip intact",
      dsg.parse_layers("grain=film; neon=glow, aurora=dream")["grain"] == 2
      and "pointer-events:none" in dsg.layers_css(
          {"shadow": None, "glass": None, "motion": set(), "grain": 3,
           "neon": None, "aurora": None})
      and "options, never rules" in dsg.DESIGN_CONTRACT)
probe("v8.10: the floor is byte-identical without a seed",
      dsg.floor_css(None) == dsg.NOVA_UI_CSS)

# --- v8.8/v8.7/v8.6/v8.5/v8.4/v8.3 laws still hold ---
with tempfile.TemporaryDirectory() as td:
    wsx = Path(td)
    (wsx / "main.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    s = nova.Session(wsx)
    s.model = "fake:7b"
    s._local_brain = lambda: True
    code = nova.run_command(s, "python main.py; echo RAN > ran.txt",
                            auto=True)
    probe("v8.8: broken entry returns PRERUN_EXIT, shell never runs",
          code == nova.PRERUN_EXIT and not (wsx / "ran.txt").exists(), code)
_a = {"code": 1, "output": 'File "m.py", line 3\nSyntaxError: invalid syntax'}
_b = {"code": 1, "output": 'File "m.py", line 7\nSyntaxError: invalid syntax'}
probe("v8.8: error_signature absorbs shifted line numbers",
      nova.error_signature(_a) == nova.error_signature(_b))
probe("v8.5: pre-apply wiring gate wired into offer_apply",
      "probe.pre_apply_gate(" in src_nova and "probe_reject" in src_nova)
probe("v8.4: guardian pre-apply gate still wired",
      "guardian.review_batch(" in src_nova and "guardian_reject" in src_nova)
probe("v8.3: Ollama payload carries the SESSION window",
      '"num_ctx": (sess._effective_num_ctx()' in src_nova)

# --------------------------------------------- portability + hygiene law
print("[probe] portability + hygiene (still holds)")
machine = "nova_project" + "/nova-assistant"
bad_tests = [p.name for p in sorted((APP / "tests").glob("test_*.py"))
             if machine in p.read_text(encoding="utf-8", errors="ignore")]
probe("no machine-specific paths in tests", not bad_tests, bad_tests)
probe("no stray duplicate FIXES doc in app/",
      not (APP / "FIXES-6.8.0.fa.md").exists())
probe("root FIXES-8.10.1 doc present",
      (ROOT / "FIXES-8.10.1.fa.md").is_file())
probe("README advertises 8.10.1",
      "8.10.1" in (ROOT / "README.md").read_text(encoding="utf-8"))
probe("no test images left in the release",
      not [f for f in files if f[1].suffix.lower() in (".png", ".jpg")
           and "fonts" not in str(f[1]) and "web" not in str(f[1])])

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
        "app/tests/test_v8101_stability.py",
        "app/tests/test_v8100_texture_neon.py",
        "app/tests/test_v890_design_layers.py",
        "app/tests/test_v880_prerun.py",
        "app/tests/test_v870_stability.py",
        "app/tests/test_v860_vision.py",
        "app/tests/test_v850_bug_hunter.py",
        "app/tests/test_v840_code_guardian.py",
        "app/tests/test_v830_context_engine.py",
        "app/scripts/package_v8101.py",
        "FIXES-8.10.1.fa.md", "PROJECT-MAP.fa.md", "README.md",
        "app/fonts/index.json"]
probe("must-have paths present",
      all(m in names for m in must),
      [m for m in must if m not in names])
probe("no caches in zip", not any("__pycache__" in n for n in names))
probe("no stray FIXES duplicate in zip",
      "app/FIXES-6.8.0.fa.md" not in names)

# ------------------------------------------------------ probe 6: vs v8.10.0
print("[probe] vs v8.10.0 release")
if PREV.is_file():
    prev = {n for n in zipfile.ZipFile(PREV).namelist() if not n.endswith("/")}
    lost = sorted(f for f in prev if f not in names
                  and f not in DROPPED_ON_PURPOSE)
    probe("no file lost vs v8.10.0", not lost, lost[:8])
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
print("ALL PROBES GREEN -> " + str(OUT))
