#!/usr/bin/env python3
"""LIVE practical test of Nova v7.13.0 (Nova Intel) - the user's rule:
after every phase, test the code AND the real environment.

Two live stages over REAL processes:

  A) the REAL web server (subprocess) + a REAL local mock cloud:
     - /api/info is 7.13.0
     - the intel endpoints work over HTTP (tasks with deps, Persian
       semantic memory, ctx, impact, gentests, regression, status)
     - a REAL /api/chat coding turn (scripted cloud, real apply
       pipeline) fires the _intel_gate hooks: agent status mirrored,
       semantic memory records the batch, critic scored, impact high
     - the served dashboard HTML carries the intel tab

  B) the REAL instrumented agent loop in-process (Session + auto_build
     with a scripted brain): the phase machine records
     observe->decide->execute->test->verify->done with honest evidence
     (run_ok=True from a real exit-0 command) into .nova/agent_runs.
"""
import http.server
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  | " + str(extra)[:160]) if extra and not cond else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------------------ mock
FILE_ANSWER = """=== FILE: mymath.py ===
def add(a, b):
    \"\"\"add two numbers\"\"\"
    return a + b
=== END ===

=== FILE: app.py ===
from mymath import add

print("sum:", add(2, 3))
=== END ===

Run: python3 app.py
"""


class MockCloud(http.server.BaseHTTPRequestHandler):
    hits = {"models": 0, "chat": 0}

    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            MockCloud.hits["models"] += 1
            self._json({"object": "list", "data": [{"id": "mock-mini"}]})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self._json({"error": "not found"}, 404)
            return
        n = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(n)
        MockCloud.hits["chat"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        text = FILE_ANSWER if MockCloud.hits["chat"] <= 1 else \
            "پاسخ کوتاه آزمایشی از مغز ابری ماک."
        for piece in (text[i:i + 60] for i in range(0, len(text), 60)):
            ev = {"id": "c1", "object": "chat.completion.chunk",
                  "choices": [{"delta": {"content": piece}}]}
            self.wfile.write(("data: " + json.dumps(ev) + "\n\n")
                             .encode("utf-8"))
        fin = {"id": "c1", "object": "chat.completion.chunk",
               "choices": [{"delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(("data: " + json.dumps(fin) + "\n\n")
                         .encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")


def http_call(port, method, path, body=None, raw=False):
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            return r.status, (payload if raw else
                              json.loads(payload.decode("utf-8")))
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload.decode("utf-8"))
        except Exception:
            return e.code, payload.decode("utf-8", "replace")


def main():
    print("== Nova v7.13.0 LIVE practical test ==")
    cloud_port = free_port()
    cloud = http.server.ThreadingHTTPServer(("127.0.0.1", cloud_port),
                                            MockCloud)
    threading.Thread(target=cloud.serve_forever, daemon=True).start()
    print("  mock cloud on %d" % cloud_port)

    tmp = tempfile.TemporaryDirectory(prefix="nova_live_7130_")
    ws = Path(tmp.name) / "proj"
    ws.mkdir()
    web_port = free_port()
    env = dict(os.environ)
    env["NOVA_NO_WIZARD"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "nova.py"), "--web",
         "--port", str(web_port), "--workspace", str(ws)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # ------------------------------------------------------ boot
        info = None
        for _ in range(60):
            try:
                s, info = http_call(web_port, "GET", "/api/info")
                if s == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        check("server booted", info is not None)
        check("version is 7.13.0", info and info.get("version") == "7.13.0",
              info)

        # --------------------------------- provider wiring (live API)
        s, _ = http_call(web_port, "POST", "/api/providers",
                         {"action": "custom_add", "name": "mockai",
                          "base": "http://127.0.0.1:%d/v1" % cloud_port,
                          "model": "mock-mini", "kind": "openai"})
        check("custom provider added", s == 200)
        s, _ = http_call(web_port, "POST", "/api/providers",
                         {"action": "set_key", "provider": "mockai",
                          "key": "sk-live-test"})
        check("key saved", s == 200)
        s, d = http_call(web_port, "POST", "/api/providers",
                         {"action": "route", "section": "coding",
                          "target": "mockai/mock-mini"})
        check("coding routed to the mock cloud", s == 200, d)

        # --------------------------------------------- intel endpoints
        s, d = http_call(web_port, "GET", "/api/intel")
        check("GET /api/intel 200", s == 200 and d.get("available"))
        check("intel state carries version 7.13.0",
              d.get("version") == "7.13.0", d.get("version"))

        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "task_add", "title": "build the core",
                          "deps": []})
        check("task_add over HTTP", s == 200 and d.get("id") == "t1", d)
        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "task_add", "title": "test the core",
                          "deps": ["t1"]})
        check("dependent task added", s == 200 and d.get("id") == "t2", d)
        _s, d = http_call(web_port, "GET", "/api/intel")
        check("graph: t1 ready, t2 blocked",
              d["tasks"]["ready"] == ["t1"] and
              d["tasks"]["blocked"] == ["t2"], d["tasks"])

        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "mem_remember",
                          "text": "تصمیم گرفتیم پورت پیش‌فرض سرویس 8765 باشد",
                          "kind": "decision", "tags": ["port"]})
        check("Persian memory remember", s == 200 and d.get("id"), d)
        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "ctx", "query": "پورت پیش‌فرض سرویس"})
        check("context engine recalls by meaning",
              s == 200 and "8765" in d.get("text", ""), d)
        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "ctx", "query": "quantum xylophone"})
        check("irrelevant query earns no memory/kb block",
              s == 200 and "MEMORY" not in d.get("text", "") and
              "KB" not in d.get("text", ""), d.get("text", "")[:120])

        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "regress_baseline"})
        check("regression baseline recorded", s == 200, d)

        # --------------------------- a REAL coding turn (auto-apply)
        nd = []
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/chat" % web_port,
            data=json.dumps({"message": "یک اسکریپت جمع بساز"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            for line in r.read().decode("utf-8").splitlines():
                if line.strip():
                    try:
                        nd.append(json.loads(line))
                    except ValueError:
                        pass
        check("coding turn streamed", len(nd) > 0)
        check("mock cloud served the brain",
              MockCloud.hits["chat"] >= 1, MockCloud.hits)
        check("mymath.py applied to the workspace",
              (ws / "mymath.py").is_file())
        check("app.py applied to the workspace", (ws / "app.py").is_file())

        # the apply pipeline triggered the intel hooks (feedback gate)
        _s, d = http_call(web_port, "GET", "/api/intel")
        st = d.get("status") or {}
        check("agent status mirrored the apply (phase=verify)",
              st.get("phase") == "verify", st)
        ev_text = " ".join(e.get("msg", "") for e in st.get("events", []))
        check("status events mention the applied batch",
              "applied:" in ev_text, ev_text)
        mem_texts = " ".join(r["text"] for r in
                             (d.get("memory") or {}).get("recent", []))
        check("semantic memory recorded the batch",
              "applied batch" in mem_texts, mem_texts)
        check("critic evidence present in tested line",
              bool(st.get("tested")), st.get("tested"))

        # --------------------------------------- impact + gentests live
        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "impact", "paths": ["mymath.py"]})
        check("impact: app.py imports mymath (high risk)",
              s == 200 and d["report"]["risk"] == "high" and
              "app.py" in d["report"]["affected"], d.get("report"))
        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "gentests", "path": "mymath.py"})
        check("gentests generated a skeleton",
              s == 200 and (ws / "tests" / "test_gen_mymath.py").is_file(),
              d)
        s, d = http_call(web_port, "POST", "/api/intel",
                         {"action": "regress_check"})
        check("regress check answered honestly",
              s == 200 and d["result"]["verdict"] in
              ("no-tests", "stable", "new-fail"), d)

        # ------------------------------------------------ run the project
        # /api/run streams NDJSON like /api/chat - collect the verdict
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/run" % web_port,
            data=json.dumps({"command": "python3 app.py"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            lines = [ln for ln in r.read().decode("utf-8").splitlines()
                     if ln.strip()]
        run_events = []
        for ln in lines:
            try:
                run_events.append(json.loads(ln))
            except ValueError:
                pass
        exit_codes = [e.get("run_exit") for e in run_events
                      if isinstance(e, dict) and "run_exit" in e]
        outputs = " ".join(str(e.get("text") or "")
                           for e in run_events if isinstance(e, dict))
        check("project run exit 0 (sum: 5)",
              bool(exit_codes) and exit_codes[-1] == 0 and
              "sum: 5" in outputs, run_events[-3:])

        # --------------------------------------------- the dashboard face
        s, html = http_call(web_port, "GET", "/", raw=True)
        html = html.decode("utf-8")
        check("dashboard HTML has the intel tab",
              s == 200 and 'data-view="intel"' in html)

        # status_clear round-trip
        s, _ = http_call(web_port, "POST", "/api/intel",
                         {"action": "status_clear"})
        _s, d = http_call(web_port, "GET", "/api/intel")
        check("status_clear empties the live status",
              d.get("status") == {}, d.get("status"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        cloud.shutdown()

    # ------------------------------------------------- STAGE B
    print("  -- stage B: the instrumented /loop (in-process) --")
    try:
        import nova as nv
        import nova_intel as it2
        ws2 = Path(tempfile.mkdtemp(prefix="nova_live_loop_"))
        sess = nv.Session(ws2)
        sess.auto_yolo = True

        def fake_stream(model, messages, temperature, sess=None,
                        section=None, quiet=False):
            return FILE_ANSWER, True

        orig = nv.stream_chat
        nv.stream_chat = fake_stream
        try:
            nv.auto_build(sess, "یک ماژول جمع با اسکریپت اجرا بساز")
        finally:
            nv.stream_chat = orig
        runs = sorted((ws2 / ".nova" / "agent_runs").glob("*.json"))
        check("agent run persisted", bool(runs))
        run = json.loads(runs[-1].read_text(encoding="utf-8")) if runs \
            else {}
        phases = [p["phase"] for p in run.get("phases", [])]
        for want in ("observe", "decide", "execute", "test", "done"):
            check("loop phase recorded: %s" % want, want in phases,
                  phases)
        check("honest finish: done WITH evidence run_ok=True",
              run.get("result") == "done" and
              (run.get("evidence") or {}).get("run_ok") is True,
              run.get("evidence"))
        check("files really applied by the loop",
              (ws2 / "app.py").is_file())
        st2 = it2.AgentStatus(ws2).read()
        check("agent status final phase: done",
              st2.get("phase") == "done", st2)
    except Exception as e:
        check("stage B completed without crashing", False, repr(e))

    print("\n== RESULT: %d passed, %d failed ==" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  FAILED: " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
