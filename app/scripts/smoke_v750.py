#!/usr/bin/env python3
"""v7.5.0 live smoke: boot the REAL web server on an ephemeral port and
probe every new endpoint end-to-end (in-process, no shell tricks)."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
os.environ.setdefault("NOVA_DISABLED_MODULES", "")

import web_server   # noqa: E402
import nova         # noqa: E402

ws = Path(tempfile.mkdtemp(prefix="nova_v75_smoke_"))
web_server.nova = nova
args = {"host": "127.0.0.1", "port": 0, "workspace": str(ws)}
web_server.STATE = web_server._State(ws)
web_server.AUTH_TOKEN = None
httpd = web_server._make_server(args)
port = httpd.server_address[1]
BASE = f"http://127.0.0.1:{port}"
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)


def get(p):
    try:
        with urllib.request.urlopen(BASE + p, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def post(p, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + p, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


# the workspace gets a couple of files so style/rag have something to read
(ws / "app.py").write_text("def run():\n    x = 'v'\n    return x\n", encoding="utf-8")
(ws / "index.html").write_text("<!doctype html><html><body>hi</body></html>",
                               encoding="utf-8")

c, info = get("/api/info")
# tracks nova.VERSION so the smoke never goes stale on a release bump
check("info 200 + version", c == 200 and info.get("version") == nova.VERSION, info.get("version"))
check("info backend flag", info.get("backend") in ("local", "cloud"), info.get("backend"))
check("info explore/rag/style/git flags", all(info.get(k) is not None
                                              for k in ("explore", "rag", "style", "git_history")))

c, tl = get("/api/timeline")
check("timeline 200 (empty)", c == 200 and tl.get("units") == [])

c, r = post("/api/style", {"op": "rebuild"})
check("style rebuild", c == 200 and r.get("ok") and
      r.get("profile", {}).get("indent") == "spaces", r.get("profile"))
c, r = post("/api/style", {"op": "clear"})
check("style clear", c == 200 and r.get("cleared"))

c, r = post("/api/route", {"fast": "gpt-4o-mini", "strong": "gpt-4o"})
check("route save", c == 200 and r.get("map", {}).get("fast") == "gpt-4o-mini")
import nova_router
check("route map persisted", nova_router.load_route_map(ws).get("strong") == "gpt-4o")
c, r = post("/api/route", {"off": True})
check("route off", c == 200 and r.get("map") == {})

c, r = post("/api/rag", {"q": ""})
check("rag empty query -> 400", c == 400)
c, r = post("/api/rag", {"q": "run"})
check("rag no index -> clean empty", c == 200 and r.get("hits") == [])

c, r = post("/api/timeline/restore", {"id": "bogus/../id"})
check("restore rejects traversal id", c == 400)
c, r = post("/api/timeline/restore", {"id": "nope-404"})
check("restore unknown id -> 404", c == 404)
c, r = post("/api/timeline/restore", {"op": "undo"})
check("undo on empty history -> clean ok", c == 200 and r.get("ok") is True)

# a REAL unit + restore-to-point through the live API
f = ws / "smoke.txt"
f.write_text("v1", encoding="utf-8")
uid, err = nova.snaps.push_auto_unit(ws, [(f, None)], note="smoke")
check("snapshot pushed", err == "")
f2 = ws / "smoke2.txt"
f2.write_text("v2", encoding="utf-8")
uid2, err2 = nova.snaps.push_auto_unit(ws, [(f2, None)], note="smoke2")
c, tl = get("/api/timeline")
unit = next((u for u in tl["units"] if u["id"] == uid), None)
check("timeline payload has string files + kind",
      unit is not None and unit["files"] == ["smoke.txt"] and "kind" in unit,
      unit)
c, r = post("/api/timeline/restore", {"id": uid})
check("restore to unit", c == 200 and r.get("ok") and not f2.exists() and f.exists())

# the help guide must carry the new commands exactly once
c, r = get("/api/help")
ids = [i["cmd"] for g in r.get("groups", []) for i in g.get("items", [])]
check("help: new cmds present", all(x in ids for x in
                                    ("/explore", "/rag", "/style", "/route", "/gitlog")),
      [x for x in ("/explore", "/rag", "/style", "/route", "/gitlog") if x not in ids])
check("help: no duplicates", len(ids) == len(set(ids)))

httpd.shutdown()
httpd.server_close()
print("-" * 46)
print("SMOKE RESULT:", "ALL GREEN" if not FAILS else f"{len(FAILS)} FAIL: {FAILS}")
sys.exit(1 if FAILS else 0)
