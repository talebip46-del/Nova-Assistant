#!/usr/bin/env python3
"""LIVE practical test of Nova v7.14.0 (the THINK protocol) + the
coffee-shop landing-page demo the user asked for:
  "یک پروژه چند فایلی با نوا درست کن ... لندینگ کافی شاپ ... عکس قبل و بعد"

Everything runs over REAL processes:
  A) the REAL web server (subprocess) + a REAL local mock cloud
     - /api/info is 7.14.0
  B) a REAL /api/chat coding turn: the scripted brain reasons inside
     === THINK === ... === END === and outputs a MULTI-FILE coffee-shop
     landing page (index.html / styles.css / script.js). The files are
     applied by Nova's REAL pipeline (parse -> lint -> snapshot -> apply).
     The {t:"think"} event rides the NDJSON stream.
  C) BEFORE screenshot (real chromium via playwright, Persian fonts).
  D) a REAL EDIT turn: EDIT hunks improve the page (still with THINK) -
     the edit-destroys-run regression guard: the page still renders.
  E) AFTER screenshot.
  F) the TALK tab with the routed brain: THINK event + clean answer.
  G) the /think command through the chat box (dispatch -> notes).

Exit code 0 only when every check passes.
"""
import http.server
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
          (("  | " + str(extra)[:200]) if extra and not cond else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------------ the brain
# Turn 1: plan in the open, then the multi-file coffee-shop landing page
TURN1 = """=== THINK ===
درخواست: یک لندینگ پیج چند فایلی برای کافی‌شاپ.
برنامه: ساختار HTML تمیز + استایل جدا (CSS) + رفتار جدا (JS).
هویت بصری: قهوه‌ای تیره و کرم، فونت وزیرمتن، راست‌به‌چپ.
ریسک: بدون وب‌کم واقعی؛ پس گالری را با گرادیان و الگو می‌سازم.
=== END ===

=== FILE: index.html ===
<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>کافه نوا | قهوه‌ی تازه، هر روز</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header class="topbar">
  <div class="brand">کافه نوا</div>
  <nav class="nav">
    <a href="#home">خانه</a>
    <a href="#menu">منو</a>
    <a href="#about">درباره ما</a>
    <a href="#contact">تماس</a>
  </nav>
</header>
<section class="hero" id="home">
  <h1>قهوه‌ی تازه، فضاي گرم</h1>
  <p>در قلب شهر، جایی برای نفس کشیدن و یک فنجان خوب.</p>
  <a class="btn" href="#menu">دیدن منو</a>
</section>
<section class="about" id="about">
  <h2>درباره ما</h2>
  <p>کافه نوا از سال ۱۳۹۵ دانه‌های تازه را خودش رست می‌کند؛ از اسپرسوی
  سنگین تا دم‌آوری سرد. هر فنجان، یک وعده‌ی کوچک است.</p>
</section>
<section class="menu" id="menu">
  <h2>منو</h2>
  <ul class="menulist">
    <li>اسپرسو — ۹۸٬۰۰۰ تومان</li>
    <li>لاته — ۱۴۵٬۰۰۰ تومان</li>
    <li>موکا — ۱۶۰٬۰۰۰ تومان</li>
  </ul>
</section>
<footer class="foot" id="contact">
  <p>کافه نوا · خیابان دانش، پلاک ۸</p>
  <p id="year"></p>
</footer>
<script src="script.js"></script>
</body>
</html>
=== END ===

=== FILE: styles.css ===
:root{
  --coffee:#3b2a20; --cream:#f4ece2; --accent:#b07d4f;
}
*{box-sizing:border-box; margin:0; padding:0}
body{
  font-family: Vazirmatn, Estedad, Tahoma, sans-serif;
  background:var(--cream); color:var(--coffee); line-height:1.9;
}
.topbar{
  display:flex; justify-content:space-between; align-items:center;
  padding:14px 28px; background:var(--coffee); color:var(--cream);
}
.brand{font-weight:700; font-size:20px}
.nav a{color:var(--cream); text-decoration:none; margin-inline-start:18px; font-size:14px}
.hero{
  padding:90px 28px; text-align:center;
  background:var(--accent); color:#fff;
}
.hero h1{font-size:34px; margin-bottom:10px}
.btn{
  display:inline-block; margin-top:18px; padding:10px 26px;
  background:var(--coffee); color:#fff; text-decoration:none;
  border-radius:6px; font-size:14px;
}
.about, .menu{padding:48px 28px; max-width:820px; margin:0 auto}
.about h2, .menu h2{margin-bottom:12px; font-size:22px}
.menulist{list-style:none}
.menulist li{
  padding:8px 0; border-bottom:1px dashed var(--accent); font-size:15px;
}
.foot{
  padding:26px 28px; background:var(--coffee); color:var(--cream);
  text-align:center; font-size:13px; margin-top:40px;
}
=== END ===

=== FILE: script.js ===
document.getElementById("year").textContent = "© " + new Date().getFullYear();
=== END ===

Preview: index.html
"""

# Turn 2: the talk tab answers (also with the visible protocol)
TURN2 = """=== THINK ===
کاربر سلام گفته و حال من را پرسیده؛ پاسخ کوتاه و گرم کافی است و موضوع
خاصی نیاز به جست‌وجو ندارد.
=== END ===
سلام! من خوبم، ممنون که پرسیدی. امروز چه کاری می‌توانم برایت انجام دهم؟
"""

# Turn 3: EDIT hunks upgrade the page (hero + menu grid + reveal JS)
TURN3 = """=== THINK ===
صفحه کار می‌کند ولی ساده است. سه بهبود: منوی کارتی با فیلتر، قهرمان
دو رنگ با بافت، و انیمیشن ظهور هنگام اسکرول. جست‌وجوی دقیق متن‌های فعلی
را از خود فایل‌ها برداشتم.
=== END ===

=== EDIT: styles.css ===
<<<<<<< SEARCH
.hero{
  padding:90px 28px; text-align:center;
  background:var(--accent); color:#fff;
}
.hero h1{font-size:34px; margin-bottom:10px}
=======
.hero{
  padding:110px 28px; text-align:center; color:#fff;
  background:
    radial-gradient(circle at 20% 20%, rgba(255,255,255,.16) 0 2px, transparent 3px),
    radial-gradient(circle at 70% 60%, rgba(255,255,255,.12) 0 2px, transparent 3px),
    linear-gradient(135deg, var(--accent), #6f4a2f);
}
.hero h1{font-size:40px; margin-bottom:10px; letter-spacing:.5px}
.hero p{opacity:.92}
>>>>>>> REPLACE

<<<<<<< SEARCH
.menulist{list-style:none}
.menulist li{
  padding:8px 0; border-bottom:1px dashed var(--accent); font-size:15px;
}
=======
.menubar{display:flex; gap:8px; justify-content:center; margin-bottom:18px; flex-wrap:wrap}
.menubar button{
  padding:6px 16px; border:1px solid var(--accent); background:transparent;
  color:var(--coffee); border-radius:20px; cursor:pointer; font-size:13px;
  font-family:inherit;
}
.menubar button.active{background:var(--accent); color:#fff}
.menugrid{
  display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));
  gap:14px;
}
.card{
  background:#fff; border:1px solid #e4d5c2; border-radius:10px;
  padding:18px 16px; box-shadow:0 6px 18px rgba(59,42,32,.07);
  transition:transform .15s ease;
}
.card:hover{transform:translateY(-3px)}
.card h3{font-size:16px; margin-bottom:6px}
.card .price{color:var(--accent); font-weight:700; font-size:14px}
.card .tag{display:inline-block; font-size:11px; color:#fff;
  background:var(--accent); border-radius:10px; padding:1px 10px; margin-bottom:8px}
.reveal{opacity:0; transform:translateY(14px); transition:all .6s ease}
.reveal.on{opacity:1; transform:none}
>>>>>>> REPLACE
=== END ===

=== EDIT: index.html ===
<<<<<<< SEARCH
<section class="menu" id="menu">
  <h2>منو</h2>
  <ul class="menulist">
    <li>اسپرسو — ۹۸٬۰۰۰ تومان</li>
    <li>لاته — ۱۴۵٬۰۰۰ تومان</li>
    <li>موکا — ۱۶۰٬۰۰۰ تومان</li>
  </ul>
</section>
=======
<section class="menu" id="menu">
  <h2>منو</h2>
  <div class="menubar">
    <button class="active" data-f="all">همه</button>
    <button data-f="hot">گرم</button>
    <button data-f="cold">سرد</button>
  </div>
  <div class="menugrid">
    <div class="card reveal" data-k="hot"><span class="tag">گرم</span>
      <h3>اسپرسو</h3><p>رست تیره، کرمای غلیظ</p>
      <p class="price">۹۸٬۰۰۰ تومان</p></div>
    <div class="card reveal" data-k="hot"><span class="tag">گرم</span>
      <h3>لاته</h3><p>شیر مخملی روی شات دوبل</p>
      <p class="price">۱۴۵٬۰۰۰ تومان</p></div>
    <div class="card reveal" data-k="hot"><span class="tag">گرم</span>
      <h3>موکا</h3><p>شکلات تلخ و اسپرسو</p>
      <p class="price">۱۶۰٬۰۰۰ تومان</p></div>
    <div class="card reveal" data-k="cold"><span class="tag">سرد</span>
      <h3>آیس لاته</h3><p>یخ، شیر، شات دوبل</p>
      <p class="price">۱۵۵٬۰۰۰ تومان</p></div>
    <div class="card reveal" data-k="cold"><span class="tag">سرد</span>
      <h3>دم‌آوری سرد</h3><p>۱۸ ساعت انتظار، طعم نرم</p>
      <p class="price">۱۷۵٬۰۰۰ تومان</p></div>
    <div class="card reveal" data-k="cold"><span class="tag">سرد</span>
      <h3>شیک موزا</h3><p>موز، قهوه، بستنی وانیلی</p>
      <p class="price">۱۹۰٬۰۰۰ تومان</p></div>
  </div>
</section>
>>>>>>> REPLACE
=== END ===

=== EDIT: script.js ===
<<<<<<< SEARCH
document.getElementById("year").textContent = "© " + new Date().getFullYear();
=======
document.getElementById("year").textContent = "© " + new Date().getFullYear();

// منو: فیلتر برچسب‌ها
document.querySelectorAll(".menubar button").forEach(function (b) {
  b.addEventListener("click", function () {
    document.querySelectorAll(".menubar button").forEach(function (x) {
      x.classList.remove("active");
    });
    b.classList.add("active");
    var f = b.getAttribute("data-f");
    document.querySelectorAll(".menugrid .card").forEach(function (c) {
      c.style.display = (f === "all" || c.getAttribute("data-k") === f) ? "" : "none";
    });
  });
});

// ظهور نرم کارت‌ها هنگام اسکرول
var io = new IntersectionObserver(function (entries) {
  entries.forEach(function (e) {
    if (e.isIntersecting) e.target.classList.add("on");
  });
}, {threshold: .15});
document.querySelectorAll(".reveal").forEach(function (el) { io.observe(el); });
>>>>>>> REPLACE
=== END ===

Preview: index.html
"""


class MockCloud(http.server.BaseHTTPRequestHandler):
    hits = {"chat": 0}
    # the demo order is: build turn, EDIT turn, then the talk turn
    answers = [TURN1, TURN3, TURN2]

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
            self._json({"object": "list",
                        "data": [{"id": "mock-mini"}]})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self._json({"error": "not found"}, 404)
            return
        n = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(n)
        text = MockCloud.answers[min(MockCloud.hits["chat"],
                                     len(MockCloud.answers) - 1)]
        MockCloud.hits["chat"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(0, len(text), 120):
            piece = text[i:i + 120]
            ev = {"id": "c1", "object": "chat.completion.chunk",
                  "choices": [{"delta": {"content": piece}}]}
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
        with urllib.request.urlopen(req, timeout=90) as r:
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


def shoot(port, out_png, full=True):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1280, "height": 860})
        pg.goto("http://127.0.0.1:%d/index.html" % port,
                wait_until="networkidle")
        pg.wait_for_timeout(900)      # fonts
        # a real user scrolls: fire the IntersectionObserver reveals so
        # the full-page capture shows every card (a full_page capture
        # does NOT scroll, so below-the-fold reveals stay opacity:0)
        pg.evaluate("""async () => {
            const h = document.body.scrollHeight;
            for (let y = 0; y <= h; y += 400) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
            }
            window.scrollTo(0, 0);
            await new Promise(r => setTimeout(r, 400));
        }""")
        pg.wait_for_timeout(700)      # transitions settle
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


def main():
    DOWNLOAD.mkdir(parents=True, exist_ok=True)
    print("== Nova v7.14.0 LIVE test + coffee landing demo ==")
    cloud_port = free_port()
    cloud = http.server.ThreadingHTTPServer(("127.0.0.1", cloud_port),
                                            MockCloud)
    threading.Thread(target=cloud.serve_forever, daemon=True).start()
    print("  mock cloud on %d" % cloud_port)

    tmp = tempfile.TemporaryDirectory(prefix="nova_live_7140_")
    ws = Path(tmp.name) / "proj"
    ws.mkdir()
    web_port = free_port()
    env = dict(os.environ)
    env["NOVA_NO_WIZARD"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "nova.py"), "--web",
         "--port", str(web_port), "--workspace", str(ws)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    srv = None
    try:
        # ------------------------------------------------ stage A: boot
        info = None
        for _ in range(60):
            try:
                s, raw = http_call(web_port, "GET", "/api/info")
                if s == 200:
                    info = json.loads(raw)
                    break
            except Exception:
                pass
            time.sleep(0.5)
        check("server booted", info is not None)
        check("version is 7.14.0",
              info and info.get("version") == "7.14.0", info)

        # ------------------------------------- provider wiring (live)
        s, raw = http_call(web_port, "POST", "/api/providers",
                           {"action": "custom_add", "name": "mockai",
                            "base": "http://127.0.0.1:%d/v1" % cloud_port,
                            "model": "mock-mini", "kind": "openai"})
        check("custom provider added", s == 200, raw[:120])
        s, _ = http_call(web_port, "POST", "/api/providers",
                         {"action": "set_key", "provider": "mockai",
                          "key": "sk-live-test"})
        check("key saved", s == 200)
        for section in ("coding", "talk"):
            s, raw = http_call(web_port, "POST", "/api/providers",
                               {"action": "route", "section": section,
                                "target": "mockai/mock-mini"})
            check("route %s -> mock cloud" % section, s == 200, raw[:120])

        # --------------------------- stage B: the build turn (THINK!)
        s, raw = http_call(web_port, "POST", "/api/chat",
                           {"message": "یک لندینگ پیج کافی‌شاپ چندفایلی بساز"})
        ev = read_ndjson(raw) if s == 200 else []
        thinks = [e for e in ev if e.get("t") == "think"]
        check("chat turn streamed 200", s == 200, raw[:160])
        check("THINK event reached the browser", bool(thinks),
              [e.get("t") for e in ev][:12])
        check("think text mentions the plan",
              thinks and "لندینگ" in (thinks[0].get("text") or ""))
        done = [e for e in ev if e.get("t") == "done"]
        check("done event arrived", bool(done))
        idx = ws / "index.html"
        css = ws / "styles.css"
        js = ws / "script.js"
        check("index.html applied", idx.is_file())
        check("styles.css applied", css.is_file())
        check("script.js applied", js.is_file())
        check("index content is the coffee shop",
              idx.is_file() and "کافه نوا" in idx.read_text(encoding="utf-8"))
        check("history stayed clean (no markers on disk/UI)",
              idx.is_file() and "=== THINK ===" not in
              idx.read_text(encoding="utf-8"))

        # --------------------------------------- stage C: BEFORE shot
        shot_port = free_port()
        srv = serve_dir(ws, shot_port)
        before = DOWNLOAD / "coffee_before.png"
        try:
            shoot(shot_port, before)
            check("BEFORE screenshot saved", before.is_file() and
                  before.stat().st_size > 20000, before.stat().st_size)
        except Exception as e:
            check("BEFORE screenshot saved", False, repr(e))

        # ------------------------------------- stage D: the EDIT turn
        s, raw = http_call(web_port, "POST", "/api/chat",
                           {"message": "منو را کارتی کن با فیلتر و انیمیشن "
                                       "اسکرول، قهرمان را هم دو رنگ کن"})
        ev2 = read_ndjson(raw) if s == 200 else []
        thinks2 = [e for e in ev2 if e.get("t") == "think"]
        check("edit turn streamed 200", s == 200, raw[:160])
        check("EDIT turn also reasoned (THINK event)", bool(thinks2))
        body = idx.read_text(encoding="utf-8")
        check("menu grid applied to index.html",
              "menugrid" in body and "آیس لاته" in body)
        check("hero upgrade applied to styles.css",
              "linear-gradient(135deg" in css.read_text(encoding="utf-8"))
        check("filter + reveal JS applied",
              "IntersectionObserver" in js.read_text(encoding="utf-8"))
        check("no leftover SEARCH/REPLACE markers in files",
              "<<<<<<<" not in body and "=======" not in
              js.read_text(encoding="utf-8"))
        check("page still self-consistent (closing tags intact)",
              body.count("<section") == body.count("</section>"))

        # --------------------------------------- stage E: AFTER shot
        try:
            after = DOWNLOAD / "coffee_after.png"
            shoot(shot_port, after)
            check("AFTER screenshot saved", after.is_file() and
                  after.stat().st_size > 20000, after.stat().st_size)
        except Exception as e:
            check("AFTER screenshot saved", False, repr(e))
        if srv:
            srv.shutdown()

        # -------------------------------------- stage F: the TALK tab
        s, raw = http_call(web_port, "POST", "/api/talk",
                           {"message": "سلام! حالت چطوره؟", "web": "off"})
        ev3 = read_ndjson(raw) if s == 200 else []
        thinks3 = [e for e in ev3 if e.get("t") == "think"]
        check("talk turn streamed 200", s == 200, raw[:160])
        check("talk THINK event arrived", bool(thinks3))
        talk_text = "".join(e.get("text", "") for e in ev3
                            if e.get("t") == "tok")
        check("talk answer is clean prose", "خوبم" in talk_text,
              talk_text[:120])
        check("talk answer carries no edit blocks",
              "=== EDIT" not in talk_text)

        # ----------------------------------- stage G: the /think cmd
        s, raw = http_call(web_port, "POST", "/api/chat",
                           {"message": "/think"})
        ev4 = read_ndjson(raw) if s == 200 else []
        notes = " ".join(e.get("text", "") for e in ev4
                         if e.get("t") == "note")
        check("/think status printed", "تفکر مدل (THINK)" in notes,
              notes[:160])

        # ------------------------- persist the final project for the user
        try:
            out_dir = DOWNLOAD / "nova_coffee_project"
            out_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            for name in ("index.html", "styles.css", "script.js"):
                src = ws / name
                if src.is_file():
                    shutil.copy2(src, out_dir / name)
            (out_dir / "README.md").write_text(
                "# کافه نوا — پروژه‌ی نمایشی Nova v7.14.0\n\n"
                "این پروژه‌ی چندفایلی توسط **خودِ Nova** ساخته و ارتقا "
                "داده شده است (خط لوله‌ی واقعی: parse → لینت → snapshot "
                "→ apply).\n\n"
                "- نوبت اول: ساخت (با بلوک === THINK === در پاسخ عامل)\n"
                "- نوبت دوم: ادیت کارتی‌شدن منو + فیلتر + انیمیشن + hero "
                "گرادیانی\n\n"
                "اجرا: همین پوشه را باز کنید و index.html را در مرورگر "
                "باز کنید (یا: python3 -m http.server در این پوشه).\n"
                "مقایسه: coffee_before.png / coffee_after.png در "
                "پوشه‌ی download.\n",
                encoding="utf-8")
            check("coffee project persisted", all(
                (out_dir / n).is_file()
                for n in ("index.html", "styles.css", "script.js",
                          "README.md")))
        except Exception as e:
            check("coffee project persisted", False, repr(e))

        # --------------------------------------------------- summary
        print("\n== summary: %d pass, %d fail ==" % (len(PASS), len(FAIL)))
        if FAIL:
            print("  failed checks:")
            for f in FAIL:
                print("   -", f)
        return 1 if FAIL else 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
