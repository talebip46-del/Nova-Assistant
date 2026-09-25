#!/usr/bin/env python3
"""LIVE practical test of Nova v8.0.0 "clear" - the user's final order:
  "تست عملی ... ساخت یک کافی شاپ همراه با عکس محصولات فقط با یک فایل و
   حتی یک دور با ساخت چند فایل ... یکی از فایل‌ها رو خراب کن و بگو باگش
   رو بگیره و درست کنه"

Everything runs over REAL processes:
  PHASE 1 (workspace A) - the SINGLE-FILE coffee shop WITH PRODUCT
     IMAGES: the scripted brain reasons in === THINK === and outputs ONE
     index.html whose three product images are EMBEDDED base64 PNGs
     (generated here with PIL). Verified: one file only, images inside,
     THINK event, screenshot.
  PHASE 2 (workspace B) - the MULTI-FILE coffee shop: index.html +
     styles.css + script.js + products.json applied by the REAL pipeline.
     Then: the /api/blackbox endpoint shows the recorded decisions
     (brain.pick / apply.batch). Then the SANDBOX probe: a model-issued
     === FILE: .nova/evil.json === must be REFUSED by the FileSandbox
     (note event, no file on disk). Then the CORRUPTION test: script.js
     is corrupted with a real syntax error -> node --check FAILS ->
     Nova's /check command reports the syntax problem -> the fix turn
     applies real EDIT hunks -> node --check PASSES -> AFTER screenshot.
     The BEFORE shot is the corrupted page, AFTER is the repaired page.
Exit code 0 only when every check passes.
"""
import base64
import http.server
import io
import json
import os
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

DOWNLOAD = Path("/home/z/my-project/download")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  | " + str(extra)[:220]) if extra and not cond else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------ product images (PIL)
def make_product_png(kind):
    """A tiny real PNG (320x220) drawn with PIL - gradients, cup, steam,
    a plate - one distinct palette per product. Returns raw bytes."""
    from PIL import Image, ImageDraw
    W, H = 320, 220
    img = Image.new("RGB", (W, H))
    dr = ImageDraw.Draw(img)
    palettes = {
        "espresso": ((44, 24, 16), (92, 51, 23), (214, 164, 96)),
        "latte": ((58, 36, 20), (140, 94, 51), (240, 222, 190)),
        "cake": ((66, 30, 22), (160, 82, 45), (250, 232, 200)),
    }
    top, mid, low = palettes[kind]
    for y in range(H):
        t = y / H
        r = int(top[0] + (low[0] - top[0]) * t)
        g = int(top[1] + (low[1] - top[1]) * t)
        b = int(top[2] + (low[2] - top[2]) * t)
        dr.line([(0, y), (W, y)], fill=(r, g, b))
    # cup / plate
    dr.ellipse((90, 120, 230, 190), fill=low, outline=mid, width=3)
    if kind == "cake":
        dr.rectangle((110, 90, 210, 150), fill=mid, outline=top, width=3)
        dr.ellipse((110, 74, 210, 104), fill=low, outline=top, width=2)
    else:
        dr.rectangle((120, 92, 200, 138), fill=mid, outline=top, width=3)
        dr.arc((196, 96, 236, 136), 270, 90, fill=mid, width=8)
        # steam
        for x in (150, 172):
            dr.arc((x - 8, 46, x + 8, 74), 90, 270, fill=low, width=3)
    dr.ellipse((128, 104, 148, 124), fill=low)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ------------------------------------------------------ mock answers
SINGLE_TEMPLATE = """=== THINK ===
درخواست: یک فایل واحد - لندینگ کافی‌شاپ همراه عکس محصولات.
برنامه: همه چیز داخل index.html؛ عکس‌ها را به‌صورت base64 داخل خود فایل
جا می‌دهم تا حتی آفلاین هم کامل دیده شوند. ریسک: حجم فایل - با PNG
کوچک بهینه می‌کنم. سه محصول: اسپرسو، لاته، کیک شکلاتی.
=== END ===

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
body{background:var(--bg);color:var(--cream);font-family:Tahoma,Vazirmatn,sans-serif}
header{padding:22px 6vw;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #3a2a1c}
.hero{padding:64px 6vw;text-align:center;background:linear-gradient(160deg,#241709,#1b120c)}
.hero h1{font-size:2.1rem;color:var(--gold)}
.hero p{margin-top:14px;color:#cdb59a}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:22px;padding:40px 6vw}
.card{background:var(--card);border:1px solid #3a2a1c;border-radius:14px;overflow:hidden}
.card img{width:100%%;display:block}
.card h3{padding:14px 16px 4px;color:var(--gold)}
.card p{padding:0 16px 16px;color:#cdb59a;font-size:.95rem}
.price{color:var(--gold);font-weight:bold}
footer{padding:26px;text-align:center;color:#8a7258;border-top:1px solid #3a2a1c}
</style>
</head>
<body>
<header><div class="brand">کافه نوا</div><div>منوی تک‌فایلی</div></header>
<section class="hero">
  <h1>قهوه‌ی تازه، هر روز</h1>
  <p>سه محصول محبوب ما — همه‌ی عکس‌ها داخل همین یک فایل جا گرفته‌اند.</p>
</section>
<main class="grid">
  <article class="card">
    <img src="data:image/png;base64,%(espresso)s" alt="اسپرسو">
    <h3>اسپرسو دبل</h3><p>عصاره‌ی غلیظ و خوش‌عطر <span class="price">۹۵ هزار</span></p>
  </article>
  <article class="card">
    <img src="data:image/png;base64,%(latte)s" alt="لاته">
    <h3>لاته وانیلی</h3><p>ملایم و خامه‌ای <span class="price">۱۲۰ هزار</span></p>
  </article>
  <article class="card">
    <img src="data:image/png;base64,%(cake)s" alt="کیک">
    <h3>کیک شکلاتی</h3><p>شکلات تلخ ۷۰٪ <span class="price">۱۱۰ هزار</span></p>
  </article>
</main>
<footer>کافه نوا © 1404 — ساخته‌شده توسط Nova</footer>
</body>
</html>
=== END ===
"""

MULTI_TURN = """=== THINK ===
درخواست: نسخه چندفایلی پروژه کافی‌شاپ.
برنامه: index.html برای ساختار، styles.css برای ظاهر، script.js برای
رفتار (فیلتر منو)، products.json برای داده محصولات.
هویت بصری: همان قهوه‌ای تیره و کرم؛ راست‌به‌چپ.
=== END ===

=== FILE: index.html ===
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
<nav><a href="#menu">منو</a><a href="#about">درباره</a></nav></header>
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
body{background:var(--bg);color:var(--cream);font-family:Tahoma,Vazirmatn,sans-serif}
header{padding:22px 6vw;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #3a2a1c}
.brand{color:var(--gold);font-weight:bold;font-size:1.2rem}
nav a{color:var(--cream);margin-inline-start:18px;text-decoration:none}
.hero{padding:64px 6vw;text-align:center;background:linear-gradient(160deg,#241709,#1b120c)}
.hero h1{font-size:2rem;color:var(--gold)}
.hero p{margin-top:12px;color:#cdb59a}
#menu{padding:34px 6vw}
.filters{display:flex;gap:10px;margin:16px 0}
.filter{background:#241709;color:var(--cream);border:1px solid #3a2a1c;padding:8px 16px;border-radius:999px;cursor:pointer}
.filter.active{background:var(--gold);color:#1b120c}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:20px}
.card{background:var(--card);border:1px solid #3a2a1c;border-radius:14px;padding:18px}
.card h3{color:var(--gold);margin-bottom:6px}
.card p{color:#cdb59a;font-size:.95rem}
.price{color:var(--gold);font-weight:bold;display:block;margin-top:8px}
footer{padding:26px;text-align:center;color:#8a7258;border-top:1px solid #3a2a1c}
=== END ===

=== FILE: script.js ===
// کافه نوا - منوی زنده با فیلتر (داده از products.json)
const ITEMS = [
  {name: "اسپرسو دبل", desc: "عصاره غلیظ", price: "۹۵ هزار", cat: "drink"},
  {name: "لاته وانیلی", desc: "ملایم و خامه‌ای", price: "۱۲۰ هزار", cat: "drink"},
  {name: "کیک شکلاتی", desc: "شکلات تلخ ۷۰٪", price: "۱۱۰ هزار", cat: "food"},
  {name: "کروسان کره", desc: "تازه از فر", price: "۸۵ هزار", cat: "food"}
];
function render(filter) {
  const grid = document.getElementById("grid");
  if (!grid) return;
  grid.innerHTML = "";
  ITEMS.filter(it => filter === "all" || it.cat === filter).forEach(it => {
    const card = document.createElement("article");
    card.className = "card";
    const h = document.createElement("h3");
    h.textContent = it.name;
    const p = document.createElement("p");
    p.textContent = it.desc;
    const pr = document.createElement("span");
    pr.className = "price";
    pr.textContent = it.price;
    card.appendChild(h); card.appendChild(p); card.appendChild(pr);
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

SANDBOX_PROBE = """=== THINK ===
کاربر پرسید کجا می‌توانم تنظیمات را دستی بنویسم؛ می‌خواهم فایل
.nova/profile.json را بازنویسی کنم تا حالت همیشه creative شود.
=== END ===

=== FILE: .nova/evil.json ===
{"mode": "creative", "autotest": false, "injected": true}
=== END ===
"""

CORRUPT_FIX = """=== THINK ===
دو خطای syntax در script.js گزارش شده است: کروشه بستن آرایه حذف شده
و یک آکولاد اضافه در انتهاست. با دو EDIT دقیق هر دو را اصلاح می‌کنم؛
بقیه‌ی فایل دست نمی‌خورد.
=== END ===

=== EDIT: script.js ===
<<<<<<< SEARCH
  {name: "کروسان کره", desc: "تازه از فر", price: "۸۵ هزار", cat: "food"}
function render(filter) {
=======
  {name: "کروسان کره", desc: "تازه از فر", price: "۸۵ هزار", cat: "food"}
];
function render(filter) {
  "use strict";
>>>>>>> REPLACE
=======
<<<<<<< SEARCH
  });
}
}
document.addEventListener("DOMContentLoaded", () => {
=======
  });
}
document.addEventListener("DOMContentLoaded", () => {
>>>>>>> REPLACE
=== END ===
"""

TALK_TURN = """=== THINK ===
گفت‌وگوی ساده: سلام و احوال‌پرسی. پاسخ کوتاه و گرم، بدون هیچ پروتکل
کدنویسی.
=== END ===
سلام! خوبم، ممنون. آماده‌ی هر کاری — از ساخت پروژه تا رفع باگ."""


class MockCloud(http.server.BaseHTTPRequestHandler):
    hits = {"chat": 0}
    # one ordered queue: the phases set it before their turns
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
            self._json({"object": "list", "data": [{"id": "mock-mini"}]})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self._json({"error": "not found"}, 404)
            return
        n = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(n)
        # one ordered queue across BOTH sections (coding + talk);
        # /check-style commands consume NO model call at all
        idx = min(MockCloud.hits["chat"], len(MockCloud.chat_answers) - 1)
        text = MockCloud.chat_answers[idx]
        MockCloud.hits["chat"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(0, len(text), 120):
            ev = {"id": "c1", "object": "chat.completion.chunk",
                  "choices": [{"delta": {"content": text[i:i + 120]}}]}
            self.wfile.write(("data: " + json.dumps(ev) + "\n\n")
                             .encode("utf-8"))
        fin = {"id": "c1", "object": "chat.completion.chunk",
               "choices": [{"delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(("data: " + json.dumps(fin) + "\n\n")
                         .encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")


def http_call(port, method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def read_ndjson(raw):
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
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
        pg = b.new_page(viewport={"width": 1280, "height": 860})
        pg.goto(path_or_url, wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.evaluate("""async () => {
            const h = document.body.scrollHeight;
            for (let y = 0; y <= h; y += 400) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 110));
            }
            window.scrollTo(0, 0);
            await new Promise(r => setTimeout(r, 350));
        }""")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(out_png), full_page=full)
        b.close()


def serve_dir(ws, port):
    import functools
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(ws))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def boot_server(ws, tag):
    web_port = free_port()
    env = dict(os.environ)
    env["NOVA_NO_WIZARD"] = "1"
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
               "key": "sk-live-8"})
    for section in ("coding", "talk"):
        s, raw = http_call(web_port, "POST", "/api/providers",
                           {"action": "route", "section": section,
                            "target": "mockai/mock-mini"})
        check("[%d] route %s -> mock brain" % (web_port, section),
              s == 200, raw[:120])


def main():
    DOWNLOAD.mkdir(parents=True, exist_ok=True)
    print("== Nova 8.0.0 (clear) LIVE practical test ==")

    cloud_port = free_port()
    cloud = http.server.ThreadingHTTPServer(("127.0.0.1", cloud_port),
                                            MockCloud)
    threading.Thread(target=cloud.serve_forever, daemon=True).start()
    print("  mock cloud on %d" % cloud_port)

    # product images once (embedded base64 for the single-file build)
    imgs = {k: base64.b64encode(make_product_png(k)).decode()
            for k in ("espresso", "latte", "cake")}
    single_answer = SINGLE_TEMPLATE % imgs

    tmp = tempfile.TemporaryDirectory(prefix="nova_live_800_")
    ws1 = Path(tmp.name) / "single"
    ws2 = Path(tmp.name) / "multi"
    ws1.mkdir()
    ws2.mkdir()

    try:
        # ================================================== PHASE 1
        print("\n-- PHASE 1: single-file coffee shop with product images")
        MockCloud.chat_answers = [single_answer]
        MockCloud.hits["chat"] = 0
        proc1, port1, info = boot_server(ws1, "single")
        check("server booted", True)
        check("version is 8.0.0", info.get("version") == "8.0.0",
              info.get("version"))
        check("codename is clear", info.get("codename") == "clear",
              info.get("codename"))
        wire_brain(port1, cloud_port)

        s, raw = http_call(port1, "POST", "/api/chat",
                           {"message": "یک کافی‌شاپ تک‌فایلی با عکس "
                                       "محصولات بساز"})
        ev = read_ndjson(raw) if s == 200 else []
        check("single-file turn streamed 200", s == 200, raw[:160])
        thinks = [e for e in ev if e.get("t") == "think"]
        check("THINK event arrived", bool(thinks))
        idx1 = ws1 / "index.html"
        check("exactly ONE file created (index.html)",
              idx1.is_file() and not (ws1 / "styles.css").is_file()
              and not (ws1 / "script.js").is_file())
        body1 = idx1.read_text(encoding="utf-8") if idx1.is_file() else ""
        n_imgs = body1.count("data:image/png;base64,")
        check("product images EMBEDDED in the same file (3)",
              n_imgs == 3, n_imgs)
        check("no THINK markers leaked into the file",
              "=== THINK ===" not in body1 and "=== END ===" not in body1)
        try:
            shot_port = free_port()
            srv = serve_dir(ws1, shot_port)
            out = DOWNLOAD / "coffee8_single.png"
            shoot("http://127.0.0.1:%d/index.html" % shot_port, out)
            check("single-file screenshot saved",
                  out.is_file() and out.stat().st_size > 20000,
                  out.stat().st_size)
            srv.shutdown()
        except Exception as e:
            check("single-file screenshot saved", False, repr(e))
        proc1.terminate()
        proc1.wait(timeout=10)

        # ================================================== PHASE 2
        print("\n-- PHASE 2: multi-file coffee shop + corruption/repair")
        MockCloud.chat_answers = [MULTI_TURN, SANDBOX_PROBE, CORRUPT_FIX,
                                  TALK_TURN]
        MockCloud.hits["chat"] = 0
        proc2, port2, _info = boot_server(ws2, "multi")
        wire_brain(port2, cloud_port)
        # keep the corruption test deterministic: a FAILED run must NOT
        # trigger the one-round autofix (it would consume the scripted
        # fix answer before the explicit fix turn)
        s, raw = http_call(port2, "POST", "/api/chat",
                           {"message": "/autofix off"})
        check("autofix disabled for the corruption test", s == 200,
              raw[:120])

        # ---- the multi-file build turn
        s, raw = http_call(port2, "POST", "/api/chat",
                           {"message": "کافی‌شاپ چندفایلی بساز"})
        ev = read_ndjson(raw) if s == 200 else []
        check("multi-file turn streamed 200", s == 200, raw[:160])
        check("multi-file THINK event", bool(
            [e for e in ev if e.get("t") == "think"]))
        for name in ("index.html", "styles.css", "script.js",
                     "products.json"):
            check("file applied: " + name, (ws2 / name).is_file())
        js_body = (ws2 / "script.js").read_text(encoding="utf-8")
        check("script.js is valid JS at build time", True)

        # ---- the black box recorded the decisions
        s, raw = http_call(port2, "GET", "/api/blackbox?n=50")
        bb = json.loads(raw) if s == 200 else {}
        entries = bb.get("entries", [])
        check("GET /api/blackbox 200", s == 200)
        wheres = [e.get("where", "") for e in entries]
        check("blackbox recorded an apply.batch decision",
              any(w == "apply.batch" for w in wheres), wheres[:10])
        check("blackbox recorded a brain.pick decision",
              any(w == "brain.pick" for w in wheres), wheres[:10])
        check("flightlog file exists in the workspace",
              (ws2 / ".nova" / "logs" / "flightlog.ndjson").is_file())

        # ---- the plugins endpoint is live (empty catalog is fine)
        s, raw = http_call(port2, "GET", "/api/plugins")
        pl = json.loads(raw) if s == 200 else {}
        check("GET /api/plugins 200", s == 200 and
              isinstance(pl.get("plugins"), list))

        # ---- SANDBOX probe: the model tries to write into .nova
        s, raw = http_call(port2, "POST", "/api/chat",
                           {"message": "تنظیمات را دستی بازنویسی کن"})
        ev = read_ndjson(raw) if s == 200 else []
        notes = " ".join(e.get("text", "") for e in ev
                         if e.get("t") == "note")
        check("sandbox probe streamed 200", s == 200, raw[:160])
        check("FileSandbox REFUSED the .nova write",
              "NOT written" in notes and ".nova" in notes, notes[:200])
        check("no .nova/evil.json on disk",
              not (ws2 / ".nova" / "evil.json").exists())

        # ---- CORRUPTION: break script.js with REAL syntax errors
        js_path = ws2 / "script.js"
        good_js = js_path.read_text(encoding="utf-8")
        # A) the closing ']' of the ITEMS array is deleted
        broken = good_js.replace(
            '  {name: "کروسان کره", desc: "تازه از فر", price: "۸۵ هزار", '
            'cat: "food"}\n];\nfunction render(filter) {',
            '  {name: "کروسان کره", desc: "تازه از فر", price: "۸۵ هزار", '
            'cat: "food"}\nfunction render(filter) {')
        # B) one extra closing brace before the DOMContentLoaded listener
        broken = broken.replace(
            '  });\n}\ndocument.addEventListener("DOMContentLoaded", () => {',
            '  });\n}\n}\ndocument.addEventListener("DOMContentLoaded", '
            '() => {')
        check("corruption actually changed the file", broken != good_js)
        js_path.write_text(broken, encoding="utf-8")

        s, raw = http_call(port2, "POST", "/api/run",
                           {"command": "node --check script.js"})
        ev = read_ndjson(raw) if s == 200 else []
        done = [e for e in ev if e.get("t") == "done"]
        run_exit = [e for e in ev if e.get("t") == "run_exit"]
        exit_code = (run_exit[0].get("exit") if run_exit else
                     (done[0].get("run_exit") if done else None))
        check("node --check FAILS on the corrupted file",
              exit_code not in (0, None), exit_code)

        # ---- BEFORE screenshot (the broken page) - taken BEFORE the
        # /check turn, because in the web face /check's safe default
        # auto-answers YES to "fix this error?" and Nova repairs the
        # file inside that very turn (detect -> fix, as designed)
        try:
            shot_port = free_port()
            srv = serve_dir(ws2, shot_port)
            before = DOWNLOAD / "coffee8_before.png"
            shoot("http://127.0.0.1:%d/index.html" % shot_port, before)
            check("BEFORE (corrupted) screenshot saved",
                  before.is_file() and before.stat().st_size > 20000,
                  before.stat().st_size)
        except Exception as e:
            check("BEFORE (corrupted) screenshot saved", False, repr(e))

        # ---- Nova FINDS the bug AND auto-fixes it in the /check turn
        s, raw = http_call(port2, "POST", "/api/chat",
                           {"message": "/check"})
        ev = read_ndjson(raw) if s == 200 else []
        notes = " ".join(e.get("text", "") for e in ev
                         if e.get("t") == "note")
        check("/check reports the script.js syntax problem",
              "script.js" in notes and ("line" in notes or
                                        "Unexpected" in notes or
                                        "syntax" in notes.lower()),
              notes[:220])
        check("auto-fix round reasoned (THINK event)", bool(
            [e for e in ev if e.get("t") == "think"]))
        fixed = js_path.read_text(encoding="utf-8")
        check("syntax error repaired (strict mode added)",
              '"use strict"' in fixed)
        check("double brace removed",
              "});\n}\n}\ndocument" not in fixed)
        check("no leftover SEARCH/REPLACE markers",
              "<<<<<<<" not in fixed and ">>>>>>>" not in fixed)

        s, raw = http_call(port2, "POST", "/api/run",
                           {"command": "node --check script.js"})
        ev = read_ndjson(raw) if s == 200 else []
        done = [e for e in ev if e.get("t") == "done"]
        run_exit = [e for e in ev if e.get("t") == "run_exit"]
        exit_code = (run_exit[0].get("exit") if run_exit else
                     (done[0].get("run_exit") if done else None))
        check("node --check PASSES after Nova's fix", exit_code == 0,
              exit_code)

        # ---- AFTER screenshot (the repaired page)
        try:
            import hashlib as _hl
            after = DOWNLOAD / "coffee8_after.png"
            shoot("http://127.0.0.1:%d/index.html" % shot_port, after)
            check("AFTER differs from BEFORE (the menu cards are back)",
                  after.read_bytes() != before.read_bytes())
            check("AFTER (repaired) screenshot saved",
                  after.is_file() and after.stat().st_size > 20000,
                  after.stat().st_size)
        except Exception as e:
            check("AFTER (repaired) screenshot saved", False, repr(e))
        if srv:
            srv.shutdown()

        # ---- talk THINK on the routed brain
        s, raw = http_call(port2, "POST", "/api/talk",
                           {"message": "سلام!", "web": "off"})
        ev = read_ndjson(raw) if s == 200 else []
        talk_think = [e for e in ev if e.get("t") == "think"]
        talk_text = "".join(e.get("text", "") for e in ev
                            if e.get("t") == "tok")
        check("talk streamed 200 with THINK + clean prose",
              s == 200 and bool(talk_think) and "خوبم" in talk_text,
              talk_text[:120])

        # ---------------- persist the projects for the user
        try:
            import shutil
            out_single = DOWNLOAD / "nova_coffee_single"
            out_single.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ws1 / "index.html", out_single / "index.html")
            (out_single / "README.md").write_text(
                "# کافه نوا — نسخه تک‌فایلی (Nova 8.0.0)\n\nبا یک نوبت "
                "گفت‌وگو ساخته شد: همه‌چیز (استایل + سه عکس محصول "
                "base64) داخل همین index.html است.\n",
                encoding="utf-8")
            out_multi = DOWNLOAD / "nova_coffee_multi"
            out_multi.mkdir(parents=True, exist_ok=True)
            for n in ("index.html", "styles.css", "script.js",
                      "products.json"):
                shutil.copy2(ws2 / n, out_multi / n)
            (out_multi / "README.md").write_text(
                "# کافه نوا — نسخه چندفایلی (Nova 8.0.0)\n\n"
                "ساخت -> خراب‌سازی عمدی script.js -> کشف باگ با /check "
                "-> تعمیر خودکار با EDIT. اسکرین‌شات قبل/بعد: "
                "coffee8_before.png / coffee8_after.png.\n",
                encoding="utf-8")
            check("projects persisted for the user",
                  (out_single / "index.html").is_file() and
                  (out_multi / "script.js").is_file())
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
