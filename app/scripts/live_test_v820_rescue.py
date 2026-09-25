#!/usr/bin/env python3
"""v8.2 LIVE rescue test - replays the user's exact bug report:

"a 4B thinking model from Ollama kept coding, then suddenly got cut off
mid-code, and Nova said the AI was blocked because ==end== was missing."

A REAL local HTTP server speaks the Ollama /api/chat wire protocol:
  call 1  -> a qwen3-style answer: closed <think>, then === FILE: blocks
             that get CUT mid-file, final chunk done_reason="length"
  call 2  -> the continuation, exactly where it stopped (the resume
             message arrives with the raw tail)

The REAL nova.Session + chat_turn + stream_chat + parse_files +
offer_apply pipeline must: detect the cut, auto-continue ONCE, merge the
raw, salvage/parse the files and write COMPLETE files to disk - with the
think box separated. Plus the talk-side shape (open <think> + cut).
Run:  python scripts/live_test_v820_rescue.py
"""
import io
import json
import socket
import sys
import tempfile
import threading
import time
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nova  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (" - " + detail if detail and not ok else ""))


class _OllamaScript(BaseHTTPRequestHandler):
    """Serves SCRIPTED /api/chat responses in the real Ollama NDJSON wire."""
    script = []          # list of list-of-dicts (one list per call)
    calls = []
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        with _OllamaScript.lock:
            i = len(_OllamaScript.calls)
            _OllamaScript.calls.append(body)
            lines = _OllamaScript.script[i] if i < len(_OllamaScript.script) \
                else [{"message": {"content": ""}, "done": True}]
        payload = b"\n".join(json.dumps(l).encode() for l in lines) + b"\n"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@contextlib.contextmanager
def _fake_ollama(script):
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _OllamaScript)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _OllamaScript.script = script
    _OllamaScript.calls = []
    nova.OLLAMA_URL = "http://127.0.0.1:%d" % port
    time.sleep(0.15)
    try:
        yield port
    finally:
        srv.shutdown()
        srv.server_close()


def _chunks(*pieces, reason="length"):
    """One Ollama NDJSON response: stream the pieces, then a final chunk.
    reason='length' = the context/output cap CUT the answer (the bug)."""
    out = [{"message": {"content": p}, "done": False} for p in pieces]
    out.append({"message": {"content": ""}, "done": True, "done_reason": reason,
                "prompt_eval_count": 111, "eval_count": 222})
    return out


def main():
    print("== v8.2 live rescue: the exact '4B thinking model cut mid-code' scenario ==\n")

    # ---- scenario 1: the user's bug, end to end -------------------------
    # a qwen3-style brain: native <think> closed properly, two FILE
    # blocks; the stream is CUT in the middle of styles.css (length).
    part1 = ("<think>I will build a small cafe page with a menu.\n"
             "First the HTML, then the CSS.</think>\n"
             "=== FILE: index.html ===\n"
             "<!doctype html>\n<html><head><title>Cafe Nova</title></head>\n"
             "<body><h1>Cafe Nova</h1></body></html>\n=== END ===\n"
             "=== FILE: styles.css ===\nbody { font-family: sans-serif;\n")
    part2 = ("  color: #222;\n}\n=== END ===\n"
             "Preview: index.html")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        ws = Path(td)
        sess = nova.Session(ws)
        sess.model = "qwen3:4b"
        script = [_chunks(part1), _chunks(part2, reason="stop")]
        buf = io.StringIO()
        with _fake_ollama(script), contextlib.redirect_stdout(buf):
            res = nova.chat_turn(sess, "یک صفحه کافه ساده بساز", auto=True)

        check("S1 cut detected (done_reason=length) -> auto-continue",
              len(_OllamaScript.calls) == 2,
              "calls=%d" % len(_OllamaScript.calls))
        resume_msg = _OllamaScript.calls[1]["messages"][-1]["content"]
        check("S1 resume message carries the raw tail",
              "font-family" in resume_msg)
        check("S1 resume message anchors the original request",
              "کافه" in resume_msg)
        check("S1 files applied", "index.html" in res["files"]
              and "styles.css" in res["files"], str(res["files"]))
        html = (ws / "index.html").read_text(encoding="utf-8")
        css = (ws / "styles.css").read_text(encoding="utf-8")
        check("S1 file 1 complete on disk", "<h1>Cafe Nova</h1>" in html)
        check("S1 file 2 MERGED complete on disk (was cut mid-file)",
              "color: #222" in css and "}" in css, repr(css[:120]))
        check("S1 think box separated (never in files)",
              res.get("think") and "menu" in res["think"]
              and "<think>" not in html)
        check("S1 history holds the CLEAN merged answer",
              "I will build" not in (sess.history[-1]["content"] or ""))
        check("S1 run hint survived (normalized for Preview)",
              (res.get("run_cmd") or "").endswith("index.html"),
              str(res.get("run_cmd")))

    # ---- scenario 2: model forgets === END === entirely (no cut) --------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        ws = Path(td)
        sess = nova.Session(ws)
        sess.model = "gemma3:4b"     # non-reasoner, /think on style answer
        raw = ("=== THINK ===\nplan the cafe menu page\n"
               "=== FILE: index.html ===\n<h1>منوی کافه</h1>\n")
        with _fake_ollama([_chunks(raw, reason="stop")]), \
                contextlib.redirect_stdout(io.StringIO()):
            res = nova.chat_turn(sess, "منو بساز", auto=True)
        check("S2 unclosed THINK + file (no cut) -> salvaged, applied",
              "index.html" in res["files"], str(res["files"]))
        check("S2 file content intact",
              "منوی کافه" in (ws / "index.html").read_text(encoding="utf-8"))
        check("S2 think = prose", res.get("think") == "plan the cafe menu page")

    # ---- scenario 3: the OLD fatal shape - open think, nothing usable ---
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        sess = nova.Session(Path(td))
        sess.model = "qwen3:4b"
        script = [_chunks("<think>let me think about how to build the whole"),
                  _chunks(" cafe site step by step</think>\nAll ready!",
                          reason="stop")]
        with _fake_ollama(script), contextlib.redirect_stdout(io.StringIO()):
            res = nova.chat_turn(sess, "سلام", auto=True)
        check("S3 open <think> cut -> continued, final answer kept",
              res["answer"].strip() == "All ready!", repr(res["answer"][:60]))
        check("S3 think merged across the cut",
              "how to build the whole" in (res.get("think") or ""))

    # ---- scenario 4: terminal case - cut twice, honest failure ----------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        sess = nova.Session(Path(td))
        sess.model = "qwen3:4b"
        script = [_chunks("<think>cut one"),
                  _chunks("<think>cut two"),
                  _chunks("<think>cut three")]
        buf = io.StringIO()
        with _fake_ollama(script), contextlib.redirect_stdout(buf):
            res = nova.chat_turn(sess, "بساز", auto=True)
        check("S4 budget respected (3 calls max: 1 + 2 continuations)",
              len(_OllamaScript.calls) == 3, "calls=%d" % len(_OllamaScript.calls))
        check("S4 honest empty answer + complete=False",
              res["answer"] == "" and res.get("complete") is False)
        check("S4 the honest message mentions the unclosed reasoning",
              "never have closed" in buf.getvalue())

    # ---- scenario 5: hard ollama error -> NO wasted continuation --------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        sess = nova.Session(Path(td))
        sess.model = "qwen3:4b"
        script = [[{"message": {"content": "par"}, "done": False},
                   {"error": "model 'qwen3:4b' requires more system memory"}]]
        buf = io.StringIO()
        with _fake_ollama(script), contextlib.redirect_stdout(buf):
            res = nova.chat_turn(sess, "بساز", auto=True)
        check("S5 hard error -> no auto-continue (1 call)",
              len(_OllamaScript.calls) == 1, "calls=%d" % len(_OllamaScript.calls))

    # ---- scenario 6: unclosed FILE + quoted END marker inside a string --
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        ws = Path(td)
        sess = nova.Session(ws)
        sess.model = "qwen3:4b"
        raw = ("=== FILE: gen.py ===\n"
               "PROTO = '=== END ==='  # the file prints the protocol\n"
               "print(PROTO)\n"
               "=== END ===\nRun: python gen.py")
        with _fake_ollama([_chunks(raw, reason="stop")]), \
                contextlib.redirect_stdout(io.StringIO()):
            res = nova.chat_turn(sess, "بساز", auto=True)
        on_disk = (ws / "gen.py").read_text(encoding="utf-8")
        check("S6 quoted === END === inside a string no longer truncates the file",
              "PROTO = '=== END ==='" in on_disk and "print(PROTO)" in on_disk,
              repr(on_disk[:120]))

    print("\n== result: %d PASS / %d FAIL ==" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
