#!/usr/bin/env python3
"""Nova 8.0.1 LIVE practical test - the coffe8_after report.

The v8.0.0 screenshots showed generated sites with NO real internet
photos: the single-file build carried PIL-generated base64 junk and the
multi-file build had ZERO <img> elements (JS-only card grid). v8.0.1
closes all three deterministic holes; this harness proves the fix with
a REAL nova server, a REAL image pipeline (live Bing/Openverse downloads)
and REAL browser screenshots:

  PHASE 1 (ws A) - single-file coffee shop where the model obeys the
     IMG: protocol (the fixed contract): <img src="IMG:...">
     -> fill pass downloads REAL photos -> page references
     assets/images/*, no IMG: left, screenshot shows the photos.
  PHASE 2 (ws B) - multi-file build in the EXACT coffe8_after shape:
     index.html with zero <img>, JS card grid whose data carries
     img:"IMG:..." literals -> hero injection + js literal fill ->
     real photos in both, screenshot with rendered photos.
  PHASE 3 (ws C) - the regression attack: tiny base64 junk (the v8.0.0
     single-file bug) -> refill with REAL photos, data: gone.

Every check counts; exit 1 on any failure. Persist the built projects
+ screenshots into download/ for the user.
"""
import base64
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DOWNLOAD = Path("/home/z/my-project/download")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name if cond else "%s  <<  %s"
                                     % (name, extra))
    print("  [%s] %s%s" % ("ok" if cond else "FAIL", name,
                           "" if cond else "   <<  %s" % str(extra)[:200]))


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------- the mock answers
SINGLE_TURN = """=== THINK ===
کاربر یک کافی‌شاپ تک‌فایلی با عکس محصولات می‌خواهد. طبق قرارداد طراحی
برای هر <img> از پروتکل IMG: استفاده می‌کنم تا نوا عکس واقعی دانلود
کند؛ هر عکس alt فارسی و width/height دارد.
=== END ===
سه محصول با عکس واقعی آماده شد.

=== FILE: index.html ===
<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>کافه نوا — نسخه تک‌فایلی</title>
<style>
:root{--bg:#1b120c;--card:#2a1c12;--cream:#f0e4d2;--gold:#d6a45f}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--cream);font-family:Tahoma,sans-serif}
header{padding:22px 6vw;display:flex;justify-content:space-between;border-bottom:1px solid #3a2a1c}
.hero{padding:40px 6vw;text-align:center}
.hero img{width:100%;max-width:900px;border-radius:14px;margin-top:18px}
.hero h1{font-size:2rem;color:var(--gold);margin-top:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:22px;padding:40px 6vw}
.card{background:var(--card);border:1px solid #3a2a1c;border-radius:14px;overflow:hidden}
.card img{width:100%;display:block}
.card h3{padding:14px 16px 4px;color:var(--gold)}
.card p{padding:0 16px 16px;color:#cdb59a}
.price{color:var(--gold);font-weight:bold}
footer{padding:26px;text-align:center;color:#8a7258;border-top:1px solid #3a2a1c}
</style>
</head>
<body>
<header><div class="brand">کافه نوا</div><div>منوی تک‌فایلی</div></header>
<section class="hero">
  <img src="IMG:coffee shop interior warm" alt="داخل کافه" width="1200" height="800">
  <h1>قهوه‌ی تازه، هر روز</h1>
</section>
<main class="grid">
  <article class="card">
    <img src="IMG:espresso cup dark coffee" alt="اسپرسو" width="800" height="600">
    <h3>اسپرسو دبل</h3><p>عصاره‌ی غلیظ <span class="price">۹۵ هزار</span></p>
  </article>
  <article class="card">
    <img src="IMG:latte art milk coffee" alt="لاته" width="800" height="600">
    <h3>لاته وانیلی</h3><p>ملایم و خامه‌ای <span class="price">۱۲۰ هزار</span></p>
  </article>
  <article class="card">
    <img src="IMG:chocolate cake slice" alt="کیک" width="800" height="600">
    <h3>کیک شکلاتی</h3><p>شکلات تلخ <span class="price">۱۱۰ هزار</span></p>
  </article>
</main>
<footer>کافه نوا © 1404 — ساخته‌شده توسط Nova</footer>
</body>
</html>
=== END ===
"""

# the EXACT coffe8_after shape: index.html has ZERO <img>, the product
# photos live in the JS data as IMG: literals (fixed contract) - Nova
# must inject the hero AND replace the JS literals with real photos.
MULTI_INDEX = """=== FILE: index.html ===
<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>کافه نوا — نسخه چندفایلی</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header><div class="brand">کافه نوا</div>
<nav><a href="#menu">منو</a></nav></header>
<section class="hero"><h1>قهوه‌ی تازه، فضای گرم</h1>
<p>در قلب شهر، جایی برای نفس کشیدن و یک فنجان خوب.</p></section>
<section id="menu">
<h2>منو</h2>
<div class="filters">
<button class="filter active" data-f="all">همه</button>
<button class="filter" data-f="drink">نوشیدنی</button>
<button class="filter" data-f="food">خوراکی</button>
</div>
<main class="grid" id="grid"></main>
</section>
<footer>کافه نوا © 1404</footer>
<script src="script.js"></script>
</body>
</html>
=== END ===

=== FILE: styles.css ===
:root{--bg:#1b120c;--card:#2a1c12;--cream:#f0e4d2;--gold:#d6a45f}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--cream);font-family:Tahoma,sans-serif}
header{padding:22px 6vw;display:flex;justify-content:space-between;border-bottom:1px solid #3a2a1c}
.hero{padding:56px 6vw;text-align:center}
.hero h1{font-size:2rem;color:var(--gold)}
.hero img{width:100%;max-width:900px;border-radius:14px;margin-top:18px}
#menu{padding:34px 6vw}
.filters{display:flex;gap:10px;margin:16px 0}
.filter{background:#241709;color:var(--cream);border:1px solid #3a2a1c;padding:8px 16px;border-radius:999px;cursor:pointer}
.filter.active{background:var(--gold);color:#1b120c}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:20px}
.card{background:var(--card);border:1px solid #3a2a1c;border-radius:14px;overflow:hidden}
.card img{width:100%;display:block}
.card h3{color:var(--gold);padding:14px 16px 4px}
.card p{color:#cdb59a;padding:0 16px 16px}
.price{color:var(--gold);font-weight:bold}
footer{padding:26px;text-align:center;color:#8a7258;border-top:1px solid #3a2a1c}
=== END ===

=== FILE: script.js ===
// کافه نوا - منوی زنده با فیلتر
const ITEMS = [
  {name: "اسپرسو دبل", desc: "عصاره غلیظ", price: "۹۵ هزار", cat: "drink",
   img: "IMG:espresso cup dark coffee", alt: "اسپرسو"},
  {name: "لاته وانیلی", desc: "ملایم و خامه‌ای", price: "۱۲۰ هزار", cat: "drink",
   img: "IMG:latte art milk coffee", alt: "لاته"},
  {name: "کیک شکلاتی", desc: "شکلات تلخ ۷۰٪", price: "۱۱۰ هزار", cat: "food",
   img: "IMG:chocolate cake slice", alt: "کیک"},
  {name: "کروسان کره", desc: "تازه از فر", price: "۸۵ هزار", cat: "food",
   img: "IMG:butter croissant bakery", alt: "کروسان"}
];
function render(filter) {
  const grid = document.getElementById("grid");
  if (!grid) return;
  grid.innerHTML = "";
  ITEMS.filter(it => filter === "all" || it.cat === filter).forEach(it => {
    const card = document.createElement("article");
    card.className = "card";
    const im = document.createElement("img");
    im.src = it.img; im.alt = it.alt || it.name;
    im.width = 800; im.height = 600;
    const h = document.createElement("h3");
    h.textContent = it.name;
    const p = document.createElement("p");
    p.textContent = it.desc;
    const pr = document.createElement("span");
    pr.className = "price";
    pr.textContent = it.price;
    card.appendChild(im); card.appendChild(h);
    card.appendChild(p); card.appendChild(pr);
    grid.appendChild(card);
  });
}
document.addEventListener("DOMContentLoaded", () => {
  render("all");
  document.querySelectorAll(".filter").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      render(btn.dataset.f);
    });
  });
});
=== END ===

=== FILE: products.json ===
{"shop": "کافه نوا", "items": 4, "currency": "IRT", "updated": "1404"}
=== END ===
"""

# PHASE 3 attack: the v8.0.0 single-file bug - tiny procedural junk
_JUNK_PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 120).decode()
JUNK_TURN = """=== FILE: index.html ===
<!doctype html>
<html lang="fa" dir="rtl">
<head><meta charset="utf-8"><title>کافه نوا — جاسازی</title>
<style>body{background:#1b120c;color:#f0e4d2;font-family:Tahoma}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;padding:40px 6vw}
.card{background:#2a1c12;border-radius:14px;overflow:hidden}
.card img{width:100%}</style></head>
<body><h1 style="padding:20px 6vw">کافه نوا</h1>
<main class="grid">
<article class="card"><img src="data:image/png;base64,__JUNK__" alt="espresso cup" width="800" height="600"><h3>اسپرسو</h3></article>
<article class="card"><img src="data:image/png;base64,__JUNK__" alt="chocolate cake slice" width="800" height="600"><h3>کیک</h3></article>
</main></body></html>
=== END ===
""".replace("__JUNK__", _JUNK_PNG)


class MockCloud(http.server.BaseHTTPRequestHandler):
    hits = {"chat": 0}
    chat_answers = []

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
            self._json({"object": "list", "data": [
                {"id": "mock-mini", "object": "model"}]})
            return
        self._json({"ok": True})

    def do_POST(self):
        n = MockCloud.hits["chat"]
        MockCloud.hits["chat"] = n + 1
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}
        stream = bool(body.get("stream"))
        answer = (MockCloud.chat_answers[n]
                  if n < len(MockCloud.chat_answers) else "باشه.")
        if not stream:
            self._json({"id": "mock-%d" % n, "object": "chat.completion",
                        "model": "mock-mini", "choices": [{
                            "index": 0, "finish_reason": "stop",
                            "message": {"role": "assistant",
                                        "content": answer}}]})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        parts = [answer[i:i + 24] for i in range(0, len(answer), 24)]
        for part in parts:
            chunk = json.dumps({"id": "mock-%d" % n,
                                "object": "chat.completion.chunk",
                                "model": "mock-mini",
                                "choices": [{"index": 0,
                                             "finish_reason": None,
                                             "delta": {
                                                 "content": part}}]})
            self.wfile.write(b"data: " + chunk.encode("utf-8") + b"\n\n")
            self.wfile.flush()
            time.sleep(0.01)
        end = json.dumps({"id": "mock-%d" % n,
                          "object": "chat.completion.chunk",
                          "model": "mock-mini",
                          "choices": [{"index": 0, "finish_reason": "stop",
                                       "delta": {}}]})
        self.wfile.write(b"data: " + end.encode("utf-8") + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")


def http_call(port, method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def read_ndjson(raw):
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "data: [DONE]":
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return events


def shoot(path_or_url, out_png, full=True):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.goto(path_or_url, wait_until="networkidle")
        pg.wait_for_timeout(900)
        pg.evaluate("""async () => {
            const h = document.body.scrollHeight;
            for (let y = 0; y <= h; y += 400) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
            }
            window.scrollTo(0, 0);
            await new Promise(r => setTimeout(r, 400));
        }""")
        pg.wait_for_timeout(700)
        pg.screenshot(path=str(out_png), full_page=full)
        b.close()


def serve_dir(ws, port):
    import functools
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(ws))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def boot_server(ws, tag):
    web_port = free_port()
    env = dict(os.environ)
    env["NOVA_NO_WIZARD"] = "1"
    env.pop("NOVA_NO_IMAGES", None)      # the pipeline under test
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "nova.py"), "--web",
         "--port", str(web_port), "--workspace", str(ws)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            s, raw = http_call(web_port, "GET", "/api/info")
            if s == 200:
                return proc, web_port, json.loads(raw)
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("server %s did not boot" % tag)


def wire_brain(web_port, cloud_port):
    s, raw = http_call(web_port, "POST", "/api/providers",
                       {"action": "custom_add", "name": "mockai",
                        "base": "http://127.0.0.1:%d/v1" % cloud_port,
                        "model": "mock-mini", "kind": "openai"})
    check("[%d] custom provider added" % web_port, s == 200, raw[:120])
    http_call(web_port, "POST", "/api/providers",
              {"action": "set_key", "provider": "mockai",
               "key": "sk-live-801"})
    for section in ("coding", "talk"):
        s, raw = http_call(web_port, "POST", "/api/providers",
                           {"action": "route", "section": section,
                            "target": "mockai/mock-mini"})
        check("[%d] route %s -> mock brain" % (web_port, section),
              s == 200, raw[:120])


def real_assets(ws):
    """Downloaded photo files (not .svg placeholders) with real size."""
    d = ws / "assets" / "images"
    if not d.is_dir():
        return []
    return [p for p in sorted(d.iterdir())
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            and p.stat().st_size >= 4_000]


def run_turn(port, message):
    s, raw = http_call(port, "POST", "/api/chat", {"message": message})
    ev = read_ndjson(raw) if s == 200 else []
    return s, ev, raw


def main():
    DOWNLOAD.mkdir(parents=True, exist_ok=True)
    print("== Nova 8.0.1 LIVE test: REAL internet photos in builds ==")

    # pre-flight: the image pipeline must be able to reach the internet
    import nova_images as ni
    results, _tq = ni.smart_search("espresso cup", limit=2)
    check("pre-flight: image search backend live", bool(results),
          "offline? %d results" % len(results))

    cloud_port = free_port()
    cloud = http.server.ThreadingHTTPServer(("127.0.0.1", cloud_port),
                                            MockCloud)
    threading.Thread(target=cloud.serve_forever, daemon=True).start()

    tmp = tempfile.TemporaryDirectory(prefix="nova_live_801_")
    ws1 = Path(tmp.name) / "single"
    ws2 = Path(tmp.name) / "multi"
    ws3 = Path(tmp.name) / "junk"
    for w in (ws1, ws2, ws3):
        w.mkdir(parents=True)

    try:
        # ================================================== PHASE 1
        print("\n-- PHASE 1: single-file build obeys the IMG: protocol")
        MockCloud.chat_answers = [SINGLE_TURN]
        MockCloud.hits["chat"] = 0
        proc1, port1, info = boot_server(ws1, "single")
        check("server booted", True)
        check("version is 8.0.1", info.get("version") == "8.0.1",
              info.get("version"))
        wire_brain(port1, cloud_port)

        s, ev, raw = run_turn(port1, "یک کافی‌شاپ تک‌فایلی با عکس "
                                    "محصولات بساز")
        check("single-file turn streamed 200", s == 200, raw[:160])
        idx1 = ws1 / "index.html"
        check("index.html created", idx1.is_file())
        body1 = idx1.read_text(encoding="utf-8") if idx1.is_file() else ""
        check("no IMG: protocol left in the page",
              "IMG:" not in body1, body1.count("IMG:"))
        check("no tiny data: junk left in the page",
              "data:image" not in body1)
        assets1 = real_assets(ws1)
        check("4+ REAL photos downloaded (>=4KB each)",
              len(assets1) >= 4, [a.name for a in assets1])
        check("photos referenced by the page",
              all(a.name in body1 for a in assets1[:2]),
              [a.name for a in assets1][:4])
        import re as _re
        srcs = _re.findall(r'src="([^"]+)"', body1)
        check("hero + product photos are LOCAL files (no remote src)",
              bool(srcs) and not any(
                  s.startswith(("http:", "https:", "//")) for s in srcs),
              srcs[:5])
        try:
            shot_port = free_port()
            srv = serve_dir(ws1, shot_port)
            out = DOWNLOAD / "coffee81_single.png"
            shoot("http://127.0.0.1:%d/index.html" % shot_port, out)
            check("PHASE 1 screenshot saved (with real photos)",
                  out.is_file() and out.stat().st_size > 50000,
                  out.stat().st_size if out.exists() else 0)
            srv.shutdown()
        except Exception as e:
            check("PHASE 1 screenshot saved", False, repr(e))
        proc1.terminate()
        proc1.wait(timeout=10)

        # ================================================== PHASE 2
        print("\n-- PHASE 2: multi-file build, coffe8_after shape "
              "(zero-img index + JS grid)")
        MockCloud.chat_answers = [MULTI_INDEX]
        MockCloud.hits["chat"] = 0
        proc2, port2, _i = boot_server(ws2, "multi")
        wire_brain(port2, cloud_port)
        s, ev, raw = run_turn(port2, "کافی‌شاپ چندفایلی بساز")
        check("multi-file turn streamed 200", s == 200, raw[:160])
        for name in ("index.html", "styles.css", "script.js"):
            check("file applied: " + name, (ws2 / name).is_file())
        idx2 = ws2 / "index.html"
        js2 = ws2 / "script.js"
        body2 = idx2.read_text(encoding="utf-8")
        jstext = js2.read_text(encoding="utf-8")
        check("HERO injected into the photo-less index.html",
              "<img" in body2 and "assets/images/" in body2,
              body2.count("<img"))
        check("no IMG: literal left in script.js",
              "IMG:" not in jstext, jstext.count("IMG:"))
        check("script.js references real local photos",
              jstext.count("assets/images/") >= 4,
              jstext.count("assets/images/"))
        assets2 = real_assets(ws2)
        check("5+ REAL photos downloaded for the multi build",
              len(assets2) >= 5, [a.name for a in assets2])
        try:
            shot_port = free_port()
            srv = serve_dir(ws2, shot_port)
            out = DOWNLOAD / "coffee81_after.png"
            shoot("http://127.0.0.1:%d/index.html" % shot_port, out)
            check("PHASE 2 screenshot saved (products WITH photos)",
                  out.is_file() and out.stat().st_size > 50000,
                  out.stat().st_size if out.exists() else 0)
            srv.shutdown()
        except Exception as e:
            check("PHASE 2 screenshot saved", False, repr(e))

        # ================================================== PHASE 3
        print("\n-- PHASE 3: tiny base64 junk attack (the v8.0.0 bug)")
        MockCloud.chat_answers = [JUNK_TURN]
        MockCloud.hits["chat"] = 0
        proc3, port3, _i = boot_server(ws3, "junk")
        wire_brain(port3, cloud_port)
        s, ev, raw = run_turn(port3, "کافی‌شاپ با عکس بساز")
        check("junk turn streamed 200", s == 200, raw[:160])
        body3 = (ws3 / "index.html").read_text(encoding="utf-8")
        check("tiny data: junk REPLACED (no data:image left)",
              "data:image" not in body3)
        check("real photos took the junk slots",
              body3.count("assets/images/") >= 2,
              body3.count("assets/images/"))
        assets3 = real_assets(ws3)
        check("junk build got 2+ REAL photos",
              len(assets3) >= 2, [a.name for a in assets3])
        proc3.terminate()
        proc3.wait(timeout=10)

        # ---------------- persist everything for the user
        try:
            out1 = DOWNLOAD / "nova_coffee_single"
            out1.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ws1 / "index.html", out1 / "index.html")
            if (ws1 / "assets" / "images").is_dir():
                if (out1 / "assets").exists():
                    shutil.rmtree(out1 / "assets")
                shutil.copytree(ws1 / "assets", out1 / "assets")
            (out1 / "README.md").write_text(
                "# کافه نوا — نسخه تک‌فایلی (Nova 8.0.1)\n\n"
                "عکس‌های واقعی اینترنت در assets/images/ ذخیره شده‌اند "
                "و صفحه به آن‌ها ارجاع می‌دهد (پروتکل IMG:).\n",
                encoding="utf-8")
            out2 = DOWNLOAD / "nova_coffee_multi"
            out2.mkdir(parents=True, exist_ok=True)
            for n in ("index.html", "styles.css", "script.js"):
                shutil.copy2(ws2 / n, out2 / n)
            if (ws2 / "assets" / "images").is_dir():
                if (out2 / "assets").exists():
                    shutil.rmtree(out2 / "assets")
                shutil.copytree(ws2 / "assets", out2 / "assets")
            (out2 / "README.md").write_text(
                "# کافه نوا — نسخه چندفایلی (Nova 8.0.1)\n\n"
                "شکل دقیق باگ coffe8_after: index بدون هیچ <img> و "
                "منوی JS-محور. حالا: hero تزریق‌شده + عکس‌های واقعی در "
                "assets/images/ + رفرنس‌ها داخل script.js.\n",
                encoding="utf-8")
            check("projects persisted for the user",
                  (out1 / "index.html").is_file()
                  and (out2 / "script.js").is_file()
                  and (out2 / "assets" / "images").is_dir())
        except Exception as e:
            check("projects persisted for the user", False, repr(e))

        proc2.terminate()
        proc2.wait(timeout=10)

        print("\n== summary: %d pass, %d fail ==" % (len(PASS), len(FAIL)))
        if FAIL:
            print("  failed checks:")
            for f in FAIL:
                print("   -", f)
        return 1 if FAIL else 0
    finally:
        try:
            cloud.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
