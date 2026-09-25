#!/usr/bin/env python3
"""PRACTICAL v8.10 verification: build a real demo site, run the real
design_polish pipeline, render it in a REAL browser (Playwright) and
prove the three new layers actually paint - plus zero console errors.

Checks:
  1. grain mood 3   -> html::after overlay opacity 0.13
  2. aurora mood 2  -> body background-image = radial gradients
                     -> body animation nv-aurora-drift (26s)
  3. neon level 2   -> card box-shadow contains the glow ring
  4. motion         -> .nv-anim-float really animates (nv-float)
  5. calm page      -> NO layers link, NO sheet (options, never rules)
  6. console        -> zero errors / page errors on both pages
Screenshots land in /home/z/my-project/download/.
"""
import sys
import tempfile
from pathlib import Path

APP = Path("/home/z/my-project/project/app")
sys.path.insert(0, str(APP))

import nova_design  # noqa: E402

OUT = Path("/home/z/my-project/download")
OUT.mkdir(parents=True, exist_ok=True)

INDEX = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>کافه آفتاب - layers demo</title>
<meta name="nova-layers" content="shadow=4; glass=2; grain=3; neon=2; aurora=2; motion=float,fade-down,pop">
<link rel="stylesheet" href="css/style.css">
</head>
<body>
<header><nav><strong>کافه آفتاب</strong>
<a href="#">خانه</a><a href="#">منو</a><a href="#">درباره ما</a></nav></header>
<main>
<section class="hero">
  <h1>یک فنجان آرامش</h1>
  <p>دموی واقعی لایه‌های طراحی نوا — بافت گرین، حاشیه نئونی و شفق محیطی،
  همه فقط چون صفحه آن‌ها را خواسته است.</p>
</section>
<section class="grid">
  <article class="card nv-neon-2"><h3>قهوه ترک</h3>
    <p>حاشیه نئونی سطح ۲ — درخشش ملایم لبه‌ها.</p></article>
  <article class="card nv-neon-1"><h3>اسپرسو</h3>
    <p>نئون سطح ۱ — لبه‌ی شفاف و جمع‌وجور.</p></article>
  <article class="card nv-neon-text"><h3>موكا</h3>
    <p>متن نئونی با رنگ قابل تغییر.</p></article>
</section>
<section class="nv-glass-2 panel">
  <h3>پنل شیشه‌ای</h3><p>شیشه مات سطح ۲ (v8.9) روی گرین سراسری.</p>
</section>
<div class="nv-anim-float badge">شناور شدن آرام</div>
</main>
<footer>ساخته‌شده با نوا ۸.۱۰ — texture &amp; neon</footer>
</body>
</html>
"""

CALM = """<!doctype html><html lang="fa" dir="rtl"><head>
<meta charset="utf-8"><title>صفحه آرام</title>
<link rel="stylesheet" href="css/style.css"></head>
<body><main><h1>بدون هیچ لایه‌ای</h1>
<p>این صفحه هیچ لایه‌ای اعلام نکرده — هیچ بایت لایه‌ای هم نباید
نوشته شود. گزینه، نه قانون.</p></main></body></html>
"""

CSS = "body{max-width:900px;margin-inline:auto;font-family:sans-serif}\n" \
      "header nav{display:flex;gap:1.2rem;align-items:center;" \
      "padding:.9rem 0;border-bottom:1px solid #e5e7eb}\n" \
      "header strong{margin-inline-end:auto}\n" \
      "header a{color:#4c5566;text-decoration:none}\n" \
      ".hero{text-align:center;padding:3rem 0}\n" \
      ".grid{display:grid;gap:1rem;grid-template-columns:repeat(3,1fr)}\n" \
      ".card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;" \
      "padding:1.2rem}\n.panel{border-radius:14px;padding:1.2rem;" \
      "margin:1rem 0}\n.badge{display:inline-block;margin:1.2rem 0}\n" \
      "footer{padding:1.4rem 0;color:#4c5566;border-top:1px solid #e5e7eb;" \
      "text-align:center;margin-top:2rem}\n"


def main():
    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        print(("  PASS  " if cond else "  FAIL  ") + label +
              ("  " + str(extra) if extra and not cond else ""))
        ok = ok and bool(cond)

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        (ws / "css").mkdir()
        (ws / "index.html").write_text(INDEX, encoding="utf-8")
        (ws / "calm.html").write_text(CALM, encoding="utf-8")
        (ws / "css" / "style.css").write_text(CSS, encoding="utf-8")

        print("[1] design_polish (the real pipeline)")
        extras, notes = nova_design.design_polish(
            ws, ["index.html", "calm.html", "css/style.css"],
            seed="یک فروشگاه قهوه با حال و هوای گرم و نئونی")
        names = [e[0] for e in extras]
        for rel, content in extras:
            target = ws / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        check("layers sheet written", "nova-layers.css" in names, names)
        check("calm page got NOTHING layers-related",
              not (ws / "calm.html").read_text(encoding="utf-8")
              .count("name=\"nova-layers\"")
              and not (ws / "calm.html").read_text(encoding="utf-8")
              .count("href=\"nova-layers.css\""))
        sheet = (ws / "nova-layers.css").read_text(encoding="utf-8")
        check("sheet carries grain mood 3", "grain mood 3" in sheet)
        check("sheet carries neon alias 2", "neon alias 2" in sheet)
        check("sheet carries aurora mood 2", "aurora mood 2" in sheet)
        for n in notes:
            print("        note:", n)

        print("[2] real browser render")
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 860})
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))

            page.goto((ws / "index.html").as_uri())
            page.wait_for_timeout(700)
            demo = page.evaluate(
                """() => {
                  const cs = (el, pseudo) =>
                    getComputedStyle(el, pseudo || null);
                  const htmlAfter = cs(document.documentElement, '::after');
                  const body = cs(document.body);
                  const neon = document.querySelector('.nv-neon-2');
                  const floatEl = document.querySelector('.nv-anim-float');
                  return {
                    grainOpacity: htmlAfter.opacity,
                    grainPointer: htmlAfter.pointerEvents,
                    bodyBg: body.backgroundImage,
                    drift: body.animationName,
                    driftDur: body.animationDuration,
                    neonShadow: neon ? cs(neon).boxShadow : '',
                    floatAnim: floatEl ? cs(floatEl).animationName : '',
                  };
                }""")
            check("grain overlay opacity == 0.13",
                  demo["grainOpacity"] == "0.13", demo["grainOpacity"])
            check("grain overlay never intercepts clicks",
                  demo["grainPointer"] == "none", demo["grainPointer"])
            check("aurora wash on body",
                  "radial-gradient" in demo["bodyBg"], demo["bodyBg"][:80])
            check("aurora drift animating",
                  demo["drift"] == "nv-aurora-drift", demo["drift"])
            check("drift is slow (26s)",
                  demo["driftDur"] in ("26s", "26.0s"), demo["driftDur"])
            check("neon glow painted",
                  "rgba(91, 91, 214" in demo["neonShadow"]
                  or "rgb(91, 91, 214" in demo["neonShadow"],
                  demo["neonShadow"][:90])
            check("float animation running",
                  demo["floatAnim"] == "nv-float", demo["floatAnim"])
            page.screenshot(path=str(OUT / "nova_v8100_layers_demo.png"),
                            full_page=True)

            page.goto((ws / "calm.html").as_uri())
            page.wait_for_timeout(250)
            calm = page.evaluate(
                """() => ({
                  htmlAfter: getComputedStyle(
                    document.documentElement, '::after').content,
                  bodyBg: getComputedStyle(document.body).backgroundImage,
                  drift: getComputedStyle(document.body).animationName,
                })""")
            check("calm page: no grain overlay", calm["htmlAfter"] == "none",
                  calm["htmlAfter"])
            check("calm page: no aurora wash / drift",
                  calm["drift"] == "none", calm["drift"])
            page.screenshot(path=str(OUT / "nova_v8100_calm_demo.png"))

            browser.close()
        check("zero console/page errors", not errors, errors[:3])

    print("RESULT:", "ALL PRACTICAL CHECKS PASSED" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
