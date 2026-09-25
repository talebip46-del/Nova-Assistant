#!/usr/bin/env python3
# =====================================================================
#  Nova Code - DESIGN ENGINE (v7.3)
#  "A weak model must still ship a beautiful, modern website - and it
#   must never look like every other site the engine builds."
#
#  The engine is 100% DETERMINISTIC: zero extra model calls, zero extra
#  tokens for the polish itself. Six layers:
#
#    1. DESIGN_CONTRACT  - a compact, byte-stable system-prompt section
#                          injected ONLY when the user's request smells
#                          like a web/UI task (nova.Session reads it).
#                          v7.2: art-direction freedom + the IMG: photo
#                          protocol (nova_images fetches real photos).
#    2. NOVA_UI_CSS      - a complete modern design-system stylesheet
#                          (light, vibrant, gradient accents, glass
#                          cards, responsive, zero CDN / offline-safe).
#                          It is the BEAUTY FLOOR: written into the
#                          project whenever the model produced HTML
#                          with no (working) stylesheet.
#    3. PALETTES +       - v7.2: the floor sheet is stamped with ONE of
#       floor_css()        8 curated accent palettes, chosen by a hash
#                          of the user's request - every project gets
#                          its own personality, still zero model calls.
#    4. design_polish()  - post-apply fixer: charset/viewport/title
#                          inserted into full HTML pages, missing local
#                          stylesheet links FILLED with the floor,
#                          bare pages linked to nova-ui.css + the tiny
#                          motion enhancer nova-ui.js (v7.2).
#    5. FONTS (v7.3)     - nova_fonts.install_pass runs right after this
#                          module: a local Persian/English font pairing
#                          per project (the model can override per page
#                          via <meta name="nova-fonts" ...>) + the
#                          dir="rtl" fix. See nova_fonts.py.
#    6. LAYERS (v8.9 +   - OPTIONAL polish layers the MODEL opts into
#       v8.10)             per project with ONE meta tag (or simply by
#                          using the nv- utility classes): a 5-level
#                          shadow scale (subtle -> dramatic), a 4-level
#                          frosted-glass scale (sharp -> misty, free of
#                          any color/font), ready micro-motions
#                          (float, fade-down, ...), a 4-level film-
#                          grain/texture scale, a 3-level neon-edge
#                          scale (recolorable) and a 3-level ambient
#                          aurora wash. Options, never rules: the
#                          sheet exists ONLY when asked for and the
#                          model keeps full creative freedom.
#
#  Kill switch: NOVA_NO_DESIGN=1 disables everything (raw output).
#  A broken/missing module degrades to None in nova.py - the agent
#  simply works without the floor, exactly like every nova_* module.
# =====================================================================
import hashlib
import os
import posixpath
import re
import tempfile
from pathlib import Path

__all__ = ["is_web_task", "design_polish", "polish_html", "DESIGN_CONTRACT",
           "NOVA_UI_CSS", "NOVA_UI_JS", "floor_css", "PALETTES", "enabled",
           "LAYERS_FILE", "parse_layers", "layers_meta", "layers_css"]

MAX_EXTRA_CSS = 4          # never write more than this many floor sheets
MAX_POLISH_BYTES = 3_000_000   # skip pages above 3 MB (pathological output)


def enabled():
    return os.environ.get("NOVA_NO_DESIGN") != "1"


# --------------------------------------------------------------- intent
# v7.0: detect "the user wants a website / UI" so the design contract is
# injected ONLY for those turns (token economy + KV-cache stability for
# everything else). Persian first: the product's primary audience.
_FA_WEB_RE = re.compile(
    "سایت|وب‌?سایت|وب‌?اپ|وب‌?صفحه|وبرا?هم|صفحه‌?ی? +(اصلی|فرود|ورود)|"
    "لندینگ|داشبورد|نمونه‌?کار|رزومه‌?ی? +(برخط|آنلاین|وب)|فروشگاه +(برخط|آنلاین|وب)|"
    "رابط +(کاربری|کاربر)|فرانت‌?اند|قالب +(وب|سایت)|صفحه +(وب|اصلی|ورود)|پنل +(مدیریت|کاربری)|"
    "طراحی +(صفحه|سایت|وب)"
)
_EN_WEB_RE = re.compile(
    r"\b(website|web\s?site|web\s?app|webapp|web\s?page|webpage|home\s?page|"
    r"landing(?:\s?page)?|dashboard|portfolio|blog|gallery|"
    r"front[\s-]?end|frontend|user\s?interface|\bui\b|\bux\b|"
    r"\bhtml\b|\bcss\b|tailwind|bootstrap|responsive|"
    r"e[\s-]?commerce|online\s+shop|web\s?store|admin\s?panel|"
    r"one[\s-]?page(?:\s+site)?|single[\s-]?page(?:\s+site)?|"
    r"hero\s+section|navigation\s+bar|navbar)\b", re.I)


def is_web_task(user_text):
    """True when the request looks like a website/UI build. Fail-soft:
    any error means 'not a web task' (the floor just stays out of the
    prompt; the deterministic polish still runs on real HTML files)."""
    try:
        t = str(user_text or "")
        if not t:
            return False
        return bool(_FA_WEB_RE.search(t) or _EN_WEB_RE.search(t))
    except Exception:
        return False


# --------------------------------------------------------------- prompt
# Byte-stable on purpose: the same bytes every web turn keeps the local
# KV/prompt cache warm. ~400 tokens, web turns only.
# v7.2: the model keeps FULL creative freedom (one bold art direction,
# chosen by the model per task) and learns the IMG: photo protocol so
# its pages show real, downloaded photos (nova_images does the work).
# v7.3: STRUCTURE FREEDOM (never repeat one template - the model is the
# art director, column layouts included) + the local font library
# (engine picks; the model can override per page with one meta tag).
# v8.9: the OPTIONAL layers menu - options, never rules (the model may
# skip the tag entirely; restraint is also design).
DESIGN_CONTRACT = """## Design contract (this is a web/UI task - mandatory)
- Link every page to its stylesheet (css/style.css); keep styling OUT of inline style attributes.
- Structure: semantic <header> with <nav>, <main> with real sections, <footer>. Real content in the user's language - never lorem ipsum.
- Structure freedom: choose the layout the CONTENT deserves - single-column story, bento grid (.bento), sidebar + content (.split), magazine columns, card grid, dashboard - and NEVER repeat one template across projects. You are the art director, not a form-filler.
- Art direction: pick ONE bold idea for THIS site (a palette mood, a big hero statement, generous whitespace, expressive headings) and carry it through every section with real, specific content. Be ambitious - it should feel designed, not generated. Strong text contrast everywhere - never gray-on-gray.
- Modern look: tokens in :root (colors, one vibrant accent GRADIENT, 14px radius, soft layered shadows, spacing scale).
- Fonts: Nova ships a local, offline font library (Persian: Vazirmatn, Estedad, Lalezar, Markazi Text, Shabnam, Gulzar... - English: Inter, Space Grotesk, Playfair Display, JetBrains Mono...). Let Nova pick the fitting pairing, or choose it yourself: <meta name="nova-fonts" content="heading=FontName; body=FontName; mono=FontName"> in <head> (FontName = a real name from the library), then use those families in your CSS. Set dir="rtl" on <html> for Persian pages.
- Components: cards with soft shadows + hover lift (transform, 0.2s ease), gradient primary buttons, styled inputs with a visible focus ring, styled tables and code blocks, image cards with rounded corners.
- Images: for EVERY <img> write src="IMG:short english description" and a meaningful alt in the user's language, plus width and height attributes (e.g. width="1200" height="800") - Nova downloads a real, watermark-free photo and center-crops it to exactly that ratio, so every image sits in a consistent frame. Never invent image URLs. NEVER embed base64/data: URIs as photo placeholders - src is ALWAYS "IMG:..." and Nova fetches the real photo. If you build cards in JavaScript, every item still keeps img:"IMG:..." in its data and the renderer creates an <img> element from it - a page or product grid that shows no photos is a BROKEN result.
- Motion: subtle fade-in on load, smooth hover states; respect prefers-reduced-motion.
- Optional layers (options, never rules - skip freely): want deeper shadows, frosted glass, micro-motion, film grain, neon edges or an aurora wash? Declare once in <head>: <meta name="nova-layers" content="shadow=1..5; glass=1..4; grain=1..4; neon=1..3; aurora=1..3; motion=float,fade-down,fade-up,slide-in,pop,glow|all"> - Nova writes nova-layers.css. Then place the utilities exactly where THEY fit: .nv-shadow-1..5 + .nv-hover-lift; frosted panels .nv-glass-1..4; motion .nv-anim-<name> + .nv-stagger on a parent; film texture .nv-grain-1..4; glowing edges .nv-neon-1..3 + .nv-neon-text (recolor: --nv-neon:R,G,B); ambient wash .nv-aurora-1..3 (recolor: --nv-aurora:R,G,B, --nv-aurora2:R,G,B). Choose levels by the site's mood; a calm design may omit the tag entirely.
- Responsive: centered max-width container, flex/grid that wraps, and a @media (max-width: 640px) block that stacks the layout."""


# --------------------------------------------------------------- the floor
# Complete, dependency-free design system. PLAIN semantic HTML must look
# great with ZERO classes (weak models forget classes); helper classes
# (.card/.btn/.container/.grid/...) are there for models that read the
# file header comment. Light theme default: hardcoded colors from a weak
# model (e.g. color:#333) stay readable on it.
# v7.2: every accent color goes through --brand-rgb / var() so the per-
# project palette stamp (floor_css) recolors the WHOLE sheet coherently;
# new: figure/figcaption, .hero, .chip, details, scrollbar, print styles,
# color-scheme, scroll-reveal helpers (.nv-reveal/.nv-in) for nova-ui.js.
NOVA_UI_CSS = """/* nova-ui.css - the Nova design floor (auto-added by Nova Assistant).
   This baseline makes a plain page look modern; override anything in your
   own CSS. Helpers: .container .card .btn .btn.ghost .grid .badge .chip
   .hero .grid-2 .grid-3 .bento .split */

:root{
  --bg:#f6f7fb; --bg2:#ffffff; --ink:#1c2130; --ink2:#4c5566; --line:#e3e7f0;
  --brand:#5b5bd6; --brand2:#8b5cf6; --accent:#0ea5e9; --brand-rgb:91,91,214;
  --code-ink:#4338ca;
  --grad:linear-gradient(135deg,#5b5bd6 0%,#8b5cf6 55%,#0ea5e9 100%);
  --grad-btn:linear-gradient(135deg,#5b5bd6 0%,#7f50ea 55%,#0073b7 100%);
  --radius:14px; --radius-sm:9px;
  --shadow:0 1px 2px rgba(28,33,48,.06),0 8px 24px rgba(28,33,48,.08);
  --shadow-lg:0 4px 10px rgba(28,33,48,.08),0 18px 44px rgba(var(--brand-rgb),.18);
  --font:'Vazirmatn','Segoe UI',system-ui,-apple-system,'Helvetica Neue',Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Consolas,'Liberation Mono',monospace;
  color-scheme:light;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0;font-family:var(--font);color:var(--ink);line-height:1.65;
  background:
    radial-gradient(900px 480px at 85% -10%,rgba(var(--brand-rgb),.13),transparent 60%),
    radial-gradient(700px 420px at -10% 20%,rgba(14,165,233,.09),transparent 55%),
    var(--bg);
  min-height:100vh;-webkit-font-smoothing:antialiased;
}
::selection{background:rgba(var(--brand-rgb),.25)}
:focus-visible{outline:3px solid rgba(var(--brand-rgb),.55);outline-offset:2px;border-radius:6px}
h1,h2,h3,h4,h5,h6{line-height:1.25;margin:0 0 .5em;font-weight:800;letter-spacing:-.01em;color:var(--ink)}
h1{font-size:2.4rem}h2{font-size:1.75rem}h3{font-size:1.34rem}
h4,h5,h6{font-size:1.08rem}
p{margin:0 0 1em;color:var(--ink2)}
strong,b{color:var(--ink)}
a{color:var(--brand);text-decoration:none;border-bottom:1px solid rgba(var(--brand-rgb),.35);transition:color .2s,border-color .2s}
a:hover{color:var(--brand2);border-color:rgba(var(--brand-rgb),.6)}
small{color:var(--ink2)}
hr{border:0;border-top:1px solid var(--line);margin:2rem 0}
img,video{max-width:100%;height:auto;border-radius:var(--radius-sm)}
img{transition:transform .25s ease,box-shadow .25s ease}
figure{margin:1.4em 0}
figure img{box-shadow:var(--shadow)}
figcaption{margin-top:.55em;font-size:.88rem;color:var(--ink2);text-align:center}
ul,ol{padding-inline-start:1.4em;color:var(--ink2)}
li{margin:.3em 0}
li::marker{color:var(--brand)}
blockquote{margin:1.2em 0;padding:.9em 1.2em;border-inline-start:4px solid var(--brand);
  background:var(--bg2);border-radius:var(--radius-sm);color:var(--ink2);box-shadow:var(--shadow)}
code{font-family:var(--mono);font-size:.92em;background:rgba(var(--brand-rgb),.10);
  padding:.15em .45em;border-radius:6px;color:var(--code-ink)}
pre{background:#151a2c;color:#dbe3f4;padding:1.1em 1.3em;border-radius:var(--radius);
  overflow-x:auto;box-shadow:var(--shadow);line-height:1.55}
pre code{background:none;color:inherit;padding:0}
kbd{font-family:var(--mono);font-size:.85em;border:1px solid var(--line);border-bottom-width:2px;
  border-radius:6px;padding:.1em .5em;background:#fff}
details{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius-sm);
  padding:.7em 1em;margin:.8em 0;box-shadow:var(--shadow)}
summary{cursor:pointer;font-weight:700;color:var(--ink)}
input[type=checkbox],input[type=radio]{accent-color:var(--brand)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:rgba(var(--brand-rgb),.35);border-radius:8px}
::-webkit-scrollbar-thumb:hover{background:rgba(var(--brand-rgb),.55)}
::-webkit-scrollbar-track{background:transparent}

/* ---- page skeleton ---- */
body>header,body>main,body>section,body>article,body>footer,body>nav,
body>.container{max-width:1080px;margin-inline:auto;padding-inline:22px}
body>header{padding-block:18px 14px}
body>main,body>section{padding-block:26px}

/* header / nav: sticky glass bar */
header{position:sticky;top:0;z-index:20;
  background:rgba(255,255,255,.78);backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
nav{display:flex;flex-wrap:wrap;align-items:center;gap:1.1rem}
nav a{border:0;color:var(--ink2);font-weight:600;padding:.3em .1em}
nav a:hover{color:var(--brand)}
nav a[aria-current],nav a.active{color:var(--brand)}

/* hero: the big confident opener */
.hero{padding-block:3.2rem 2.2rem;text-align:center}
.hero h1{font-size:clamp(2.1rem,5vw,3.3rem);
  background:var(--grad);-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;color:transparent}
.hero p{max-width:640px;margin-inline:auto;font-size:1.13rem}

/* sections & cards */
section+section,article+article{margin-top:1.6rem}
.card,article,.panel,.box{background:var(--bg2);border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow);padding:1.35rem 1.5rem;
  transition:transform .2s ease,box-shadow .2s ease}
.card:hover,article:hover{transform:translateY(-3px);box-shadow:var(--shadow-lg)}
main>section:first-of-type{padding-block:2.4rem 1.6rem}
main>section:first-of-type h1:not(.hero h1){
  background:var(--grad);-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;color:transparent}

/* buttons & forms */
button,.btn,input[type=submit],input[type=button]{
  display:inline-block;border:0;cursor:pointer;font:inherit;font-weight:700;
  color:#fff;background:var(--grad-btn);padding:.62em 1.35em;border-radius:999px;
  text-shadow:0 1px 2px rgba(0,0,0,.22);
  box-shadow:0 6px 18px rgba(var(--brand-rgb),.35);transition:transform .18s ease,box-shadow .18s ease,filter .18s ease}
button:hover,.btn:hover,input[type=submit]:hover,input[type=button]:hover{
  transform:translateY(-1px);filter:brightness(1.06);box-shadow:0 10px 26px rgba(var(--brand-rgb),.42)}
button:active,.btn:active{transform:translateY(0)}
.btn.ghost,button.ghost{background:transparent;color:var(--brand);
  border:1.5px solid rgba(var(--brand-rgb),.5);box-shadow:none}
input,select,textarea{
  font:inherit;color:var(--ink);background:#fff;border:1.5px solid var(--line);
  border-radius:var(--radius-sm);padding:.55em .85em;transition:border-color .2s,box-shadow .2s}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--brand);
  box-shadow:0 0 0 4px rgba(var(--brand-rgb),.15)}
label{font-weight:600;color:var(--ink);display:block;margin:.8em 0 .3em}
textarea{min-height:110px;resize:vertical}
fieldset{border:1px solid var(--line);border-radius:var(--radius-sm);margin:1em 0}
legend{font-weight:700;padding-inline:.4em}

/* tables */
table{width:100%;border-collapse:collapse;background:var(--bg2);border-radius:var(--radius);
  overflow:hidden;box-shadow:var(--shadow);font-size:.97em}
th{background:rgba(var(--brand-rgb),.08);color:var(--ink);text-align:start;font-weight:700}
th,td{padding:.7em 1em;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:rgba(var(--brand-rgb),.05)}

/* footer */
footer{margin-top:3rem;padding-block:1.6rem;border-top:1px solid var(--line);
  color:var(--ink2);font-size:.92rem;text-align:center}

/* helpers (for models that use them) */
.container{max-width:1080px;margin-inline:auto;padding-inline:22px}
.grid{display:grid;gap:1.2rem;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.grid-2{display:grid;gap:1.2rem;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.grid-3{display:grid;gap:1.2rem;grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
/* v7.4: weak models keep inventing '.cards' for a row of cards - give
   the name a real grid rule instead of letting it stack single-file */
.cards{display:grid;gap:1.2rem;grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
/* column layouts: asymmetric bento + sidebar/content split
   (grid is logical - both mirror correctly in RTL pages) */
.bento{display:grid;gap:1.2rem;grid-template-columns:repeat(4,1fr)}
.bento>.span-2{grid-column:span 2}
.bento>.tall{grid-row:span 2}
.split{display:grid;gap:1.6rem;grid-template-columns:minmax(230px,320px) 1fr;align-items:start}
.badge{display:inline-block;font-size:.78rem;font-weight:700;color:var(--code-ink);
  background:rgba(var(--brand-rgb),.12);border-radius:999px;padding:.25em .8em}
.chip{display:inline-block;font-size:.8rem;font-weight:600;color:var(--ink2);
  border:1px solid var(--line);background:var(--bg2);border-radius:999px;
  padding:.22em .75em;margin:.15em .2em}

/* motion (CSS-only entrance + nova-ui.js scroll reveal) */
@media (prefers-reduced-motion:no-preference){
  body>header,body>main,body>section,body>footer{animation:nv-fade .5s ease both}
  body>section:nth-of-type(2){animation-delay:.08s}
  body>section:nth-of-type(3){animation-delay:.16s}
  @keyframes nv-fade{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  .nv-reveal{opacity:0;transform:translateY(16px);
    transition:opacity .6s ease,transform .6s ease}
  .nv-reveal.nv-in{opacity:1;transform:none}
}

/* mobile */
@media (max-width:900px){
  .split{grid-template-columns:1fr}
  .bento{grid-template-columns:repeat(2,1fr)}
  .cards{grid-template-columns:repeat(2,1fr)}
}
@media (max-width:640px){
  h1{font-size:1.75rem}h2{font-size:1.4rem}
  .hero{padding-block:2.2rem 1.4rem}
  body>header,body>main,body>section,body>article,body>footer,body>.container{
    padding-inline:16px}
  nav{gap:.7rem}
  .card,article{padding:1.05rem 1.1rem}
  table{font-size:.88em}
  th,td{padding:.55em .7em}
  .bento{grid-template-columns:1fr}
  .bento>.span-2,.bento>.tall{grid-column:auto;grid-row:auto}
  .cards{grid-template-columns:1fr}
}

/* print: a generated page that prints cleanly is a feature */
@media print{
  header,nav,footer,.nv-reveal{animation:none}
  body{background:#fff}
  .card,article,table,details{box-shadow:none}
  .nv-reveal{opacity:1 !important;transform:none !important}
}
"""


# --------------------------------------------------------------- palettes
# v7.2: 8 curated accent palettes. floor_css(seed) stamps ONE of them
# (chosen by a stable hash of the user's request) onto the sheet, so
# every project gets its own personality while the whole floor stays
# coherent (all accents flow from --brand-rgb). Zero model calls.
PALETTES = [
    # (name, brand, brand2, accent, brand-rgb, code-ink)
    ("indigo-violet", "#5b5bd6", "#8b5cf6", "#0ea5e9", "91,91,214",  "#4338ca"),
    ("ocean",         "#0369a1", "#0ea5e9", "#14b8a6", "3,105,161",  "#0c4a6e"),
    ("sunset",        "#c2410c", "#f43f5e", "#b45309", "194,65,12",  "#7c2d12"),
    ("forest",        "#047857", "#10b981", "#84cc16", "4,120,87",   "#065f46"),
    ("royal",         "#7c3aed", "#c026d3", "#6366f1", "124,58,237", "#5b21b6"),
    ("rose",          "#be123c", "#f43f5e", "#ea580c", "190,18,60",  "#881337"),
    ("teal-gold",     "#0f766e", "#14b8a6", "#a16207", "15,118,110", "#134e4a"),
    ("midnight-blue", "#1d4ed8", "#3b82f6", "#06b6d4", "29,78,216",  "#1e40af"),
]


def _lum_channel(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _wcag_lum(hexcolor):
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return (0.2126 * _lum_channel(r) + 0.7152 * _lum_channel(g)
            + 0.0722 * _lum_channel(b))


def _wcag_contrast(a, b):
    la, lb = _wcag_lum(a), _wcag_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _btn_safe(hexcolor, target=4.65):
    """v7.4 audit fix: white 16px-bold text rides the WHOLE button
    gradient, and the bright tail stops (forest #84cc16 = 1.98:1) failed
    WCAG AA badly. Buttons therefore get their own gradient built from
    WCAG-safe darker shades of the SAME hues (>=4.65:1 with white, and
    still >=4.5:1 after the hover brightness(1.06)); the decorative
    --grad keeps the vibrant original colors for text-clip/borders."""
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    while True:
        cur = f"#{r:02x}{g:02x}{b:02x}"
        bright = "#{:02x}{:02x}{:02x}".format(
            min(255, int(r * 1.06)), min(255, int(g * 1.06)),
            min(255, int(b * 1.06)))
        if _wcag_contrast(cur, "#ffffff") >= target \
                and _wcag_contrast(bright, "#ffffff") >= 4.5:
            return cur
        if r == g == b == 0:
            return cur
        r, g, b = max(0, r - 2), max(0, g - 2), max(0, b - 2)


def _btn_grad(b, b2, ac):
    return "linear-gradient(135deg," + _btn_safe(b) + " 0%," \
         + _btn_safe(b2) + " 55%," + _btn_safe(ac) + " 100%)"


def _palette_block(idx):
    name, b, b2, ac, rgb, code = PALETTES[idx % len(PALETTES)]
    return (
        "\n/* nova palette stamp: " + name + " */\n"
        ":root{\n"
        "  --brand:" + b + "; --brand2:" + b2 + "; --accent:" + ac + ";\n"
        "  --brand-rgb:" + rgb + "; --code-ink:" + code + ";\n"
        "  --grad:linear-gradient(135deg," + b + " 0%," + b2 + " 55%,"
        + ac + " 100%);\n"
        "  --grad-btn:" + _btn_grad(b, b2, ac) + ";\n"
        "}\n")


def floor_css(seed=None):
    """The floor sheet, stamped with the palette chosen by `seed` (the
    user's own words). seed=None -> the plain default sheet (byte-identical
    to NOVA_UI_CSS, exactly what older direct callers/tests expect)."""
    if not seed:
        return NOVA_UI_CSS
    h = hashlib.md5(str(seed).encode("utf-8", "replace")).digest()
    return NOVA_UI_CSS + _palette_block(h[0])


# --------------------------------------------------------------- motion js
# v7.2: a tiny, safe enhancer linked next to the floor when a bare page
# gets styled. Scroll-reveal for sections/cards; honors reduced motion;
# no innerHTML, no globals beyond one IIFE, works when missing.
NOVA_UI_JS = """/* nova-ui.js - Nova motion floor (auto-added; safe to delete). */
(function () {
  "use strict";
  if (window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (!("IntersectionObserver" in window)) return;
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add("nv-in"); io.unobserve(e.target); }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
  function arm(el) {
    if (el.classList.contains("nv-reveal") || el.classList.contains("nv-in")) return;
    el.classList.add("nv-reveal");
    if (el.getBoundingClientRect().top < window.innerHeight * 0.92) {
      el.classList.add("nv-in");          // already visible: show instantly
    } else {
      io.observe(el);
    }
  }
  function scan() {
    var sel = "main > section, main > article, article, .card";
    document.querySelectorAll(sel).forEach(arm);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scan);
  } else {
    scan();
  }
})();
"""


# --------------------------------------------------------------- layers
# v8.9: OPTIONAL design layers. The MODEL opts in per project - options,
# never rules, and creativity stays entirely its own:
#
#   <meta name="nova-layers" content="shadow=1..5; glass=1..4;
#          motion=float,fade-down,fade-up,slide-in,pop,glow|all">
#
# ...or it simply uses the nv- utility classes (both count as a request,
# the meta additionally sets the site-wide mood). When any applied page
# opts in, design_polish writes ONE deterministic nova-layers.css -
# merged with a previous Nova-made sheet (a union never shrinks), never
# overwriting a file the user made themselves - and links it AFTER the
# page's own sheets so the layer tokens win the cascade. 100%
# deterministic, offline, zero model calls, exactly like the rest of
# the engine.
LAYERS_FILE = "nova-layers.css"

# the motion menu: ready, subtle, respectful - every block is wrapped
# in prefers-reduced-motion, entrances run ONCE, loops are slow/soft
_MOTION_PRESETS = ("float", "fade-down", "fade-up", "slide-in", "pop",
                   "glow")

# v8.10.1: the DESIGN_CONTRACT documents the grammar as ranges
# ('shadow=1..5; glass=1..4; ...') - a weak model copying it VERBATIM used
# to get nothing (the range failed every branch and the layer stayed
# undeclared). A range expresses the layer WITHOUT a specific level, i.e.
# exactly the docstring's level-0 meaning: 'requested as bare utilities
# (no site-wide mood)' - deterministic, and it never hijacks the design.
_RANGE_VAL_RE = re.compile(r"^\d{1,3}(?:\.\.|-)\d{1,3}$")

_SHADOW_WORDS = {"subtle": 1, "soft": 2, "medium": 3, "deep": 4,
                 "dramatic": 5}
_GLASS_WORDS = {"sharp": 1, "crisp": 1, "clear": 1, "soft": 2, "silky": 3,
                "mist": 4, "haze": 4}
# v8.10: the texture / glow menu - film grain, neon edges, aurora wash
_GRAIN_WORDS = {"whisper": 1, "subtle": 1, "film": 2, "medium": 3,
                "heavy": 4}
_NEON_WORDS = {"crisp": 1, "glow": 2, "dramatic": 3}
_AURORA_WORDS = {"whisper": 1, "dream": 2, "vivid": 3}

_LAYERS_META_RE = re.compile(
    r"<meta\b[^>]*\bname\s*=\s*[\"']nova-layers[\"'][^>]*>", re.I)
_META_CONTENT_RE = re.compile(r"\bcontent\s*=\s*[\"']([^\"']*)[\"']", re.I)
_LAYERS_LINK_HREF_RE = re.compile(
    r"<link\b[^>]*\bhref\s*=\s*[\"']((?:[^\"']*/)?" + re.escape(LAYERS_FILE)
    + r"(?:\?[^\"']*)?)[\"']", re.I)
_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.I)
_SHEET_MOOD_RE = re.compile(r"/\* nova layer: shadow mood (\d)")
_SHEET_ALIAS_RE = re.compile(r"/\* nova layer: glass alias (\d)")
_SHEET_ANIM_RE = re.compile(r"\.nv-anim-([a-z0-9-]+)\{")
# v8.10: reverse-parse markers of the texture/glow layers
_SHEET_GRAIN_MOOD_RE = re.compile(r"/\* nova layer: grain mood (\d)")
_SHEET_NEON_ALIAS_RE = re.compile(r"/\* nova layer: neon alias (\d)")
_SHEET_AURORA_MOOD_RE = re.compile(r"/\* nova layer: aurora mood (\d)")


def _empty_spec():
    """A fresh no-layers spec (a fresh set each call - never share one).
    Every layer key is ALWAYS present (None = not requested) so specs
    compare, merge and round-trip predictably."""
    return {"shadow": None, "glass": None, "motion": set(),
            "grain": None, "neon": None, "aurora": None}


def parse_layers(spec):
    """Parse the nova-layers meta CONTENT into a clean spec:
    {'shadow': None|int(0..5), 'glass': None|int(0..4), 'motion': set,
     'grain': None|int(0..4), 'neon': None|int(0..3),
     'aurora': None|int(0..3)}
    None = the layer was not requested; 0 = requested as bare utilities
    (no site-wide mood); 1..N = requested WITH that mood level.
    Forgiving by design (options, never rules): 'key=value' or
    'key:value' or bare keys, any spacing, commas or semicolons, digits
    (Persian digits included) or mood words; unknown keys/values are
    ignored; 'off'/'none' (whole spec or per key) means 'not wanted';
    bare 'motion', 'motion=all' or a bare preset name ('float') work;
    bare 'all' = every layer at sensible defaults. Never raises."""
    out = _empty_spec()
    try:
        s = str(spec or "").strip().lower()
    except Exception:
        return out
    if not s or s in ("off", "none", "false", "no", "0"):
        return out
    for tok in re.split(r"[;,\s]+", s):
        if not tok:
            continue
        m = re.match(r"^([a-z][a-z0-9_-]*)(?:[=:](.*))?$", tok)
        if not m:
            continue
        key = m.group(1)
        val = (m.group(2) or "").strip()
        bare = not val
        if key == "shadow":
            if bare:
                if out["shadow"] is None:
                    out["shadow"] = 0
            elif val in ("off", "none", "no", "false", "0"):
                out["shadow"] = None
            elif val in _SHADOW_WORDS:
                out["shadow"] = _SHADOW_WORDS[val]
            elif val.isdecimal():
                out["shadow"] = min(5, max(1, int(val)))
            elif _RANGE_VAL_RE.match(val):
                if out["shadow"] is None:
                    out["shadow"] = 0
        elif key == "glass":
            if bare:
                if out["glass"] is None:
                    out["glass"] = 0
            elif val in ("off", "none", "no", "false", "0"):
                out["glass"] = None
            elif val in _GLASS_WORDS:
                out["glass"] = _GLASS_WORDS[val]
            elif val.isdecimal():
                out["glass"] = min(4, max(1, int(val)))
            elif _RANGE_VAL_RE.match(val):
                if out["glass"] is None:
                    out["glass"] = 0
        elif key == "motion":
            if bare or val in ("all", "on", "yes"):
                out["motion"] = set(_MOTION_PRESETS)
            elif val in ("off", "none", "no", "false", "0"):
                out["motion"] = set()
            else:
                for name in re.split(r"[+/&|]+", val):
                    if name == "all":
                        out["motion"] = set(_MOTION_PRESETS)
                    elif name in _MOTION_PRESETS:
                        out["motion"].add(name)
        elif key == "grain":
            if bare:
                if out["grain"] is None:
                    out["grain"] = 0
            elif val in ("off", "none", "no", "false", "0"):
                out["grain"] = None
            elif val in _GRAIN_WORDS:
                out["grain"] = _GRAIN_WORDS[val]
            elif val.isdecimal():
                out["grain"] = min(4, max(1, int(val)))
            elif _RANGE_VAL_RE.match(val):
                if out["grain"] is None:
                    out["grain"] = 0
        elif key == "neon":
            if bare:
                if out["neon"] is None:
                    out["neon"] = 0
            elif val in ("off", "none", "no", "false", "0"):
                out["neon"] = None
            elif val in _NEON_WORDS:
                out["neon"] = _NEON_WORDS[val]
            elif val.isdecimal():
                out["neon"] = min(3, max(1, int(val)))
            elif _RANGE_VAL_RE.match(val):
                if out["neon"] is None:
                    out["neon"] = 0
        elif key == "aurora":
            if bare:
                if out["aurora"] is None:
                    out["aurora"] = 0
            elif val in ("off", "none", "no", "false", "0"):
                out["aurora"] = None
            elif val in _AURORA_WORDS:
                out["aurora"] = _AURORA_WORDS[val]
            elif val.isdecimal():
                out["aurora"] = min(3, max(1, int(val)))
            elif _RANGE_VAL_RE.match(val):
                if out["aurora"] is None:
                    out["aurora"] = 0
        elif key == "neon-text" and bare:
            # v8.10: the bare utility name opts into the neon layer too
            if out["neon"] is None:
                out["neon"] = 0
        elif key == "all" and bare:
            if out["shadow"] is None:
                out["shadow"] = 3
            if out["glass"] is None:
                out["glass"] = 2
            if out["grain"] is None:
                out["grain"] = 2
            if out["neon"] is None:
                out["neon"] = 1
            if out["aurora"] is None:
                out["aurora"] = 1
            out["motion"] = set(_MOTION_PRESETS)
        elif key in _MOTION_PRESETS and bare:
            out["motion"].add(key)
    return out


def layers_meta(html):
    """The parsed nova-layers spec of one document, or None when the
    page does not opt in (no meta, a valueless meta, or a meta that
    resolves to nothing - e.g. content="off"). Fail-soft: any surprise
    means None."""
    try:
        m = _LAYERS_META_RE.search(str(html or ""))
        if not m:
            return None
        cm = _META_CONTENT_RE.search(m.group(0))
        spec = parse_layers(cm.group(1) if cm else "")
        if all(spec[k] is None for k in ("shadow", "glass", "grain",
                                         "neon", "aurora")) \
                and not spec["motion"]:
            return None
        return spec
    except Exception:
        return None


_NV_CLASS_RE = re.compile(
    r"\bnv-(glass-[1-4]|shadow-[1-5]|anim-[a-z0-9-]+|hover-lift"
    r"|grain-[1-4]|neon-[1-3]|neon-text|aurora-[1-3])\b")
# v8.11: the REAL usage contexts of a utility class - class attributes,
# js classList calls, and the page's own <style> selectors. The old
# scan matched nv-* tokens ANYWHERE in the raw document, so a docs page
# whose prose merely mentioned "add the class nv-glass-2" self-activated
# the layers engine (sheet written + link injected) with no design
# intended.
_NV_CLASS_ATTR_RE = re.compile(
    r"""(?<![\w-])class(?:Name)?\s*=\s*["']([^"']+)['"]""", re.I)
_NV_CLASSLIST_RE = re.compile(
    r"""classList\.\w+\(\s*["']([^"')]+)['"]""", re.I)
_STYLE_BLOCK_RE = re.compile(
    r"<style\b[^>]*>([\s\S]*?)</style\s*>", re.I)


def _implied_layers(html):
    """Layers IMPLIED by actual nv- utility usage: the model may skip
    the meta and just place the classes - both are first-class options
    (a bare meta level never overrides a declared mood; see merge).
    v8.11: only real usage contexts count - class attributes, js
    classList calls, and the page's own <style> selectors. Plain PROSE
    mentioning a class name no longer activates anything."""
    spec = _empty_spec()
    try:
        text = str(html or "")
        ctx = [m.group(1) for m in _NV_CLASS_ATTR_RE.finditer(text)]
        ctx += [m.group(1) for m in _NV_CLASSLIST_RE.finditer(text)]
        ctx += [m.group(1) for m in _STYLE_BLOCK_RE.finditer(text)]
        for hay in ctx:
            for m in _NV_CLASS_RE.finditer(hay):
                tok = m.group(1)
                if tok.startswith("glass-"):
                    spec["glass"] = 0
                elif tok.startswith("shadow-") or tok == "hover-lift":
                    spec["shadow"] = 0
                elif tok.startswith("anim-") and tok[5:] in _MOTION_PRESETS:
                    spec["motion"].add(tok[5:])
                elif tok.startswith("grain-"):
                    spec["grain"] = 0
                elif tok.startswith("neon-"):
                    spec["neon"] = 0
                elif tok.startswith("aurora-"):
                    spec["aurora"] = 0
    except Exception:
        pass
    return spec


def _merge_level(x, y):
    vals = [v for v in (x, y) if v is not None]
    return max(vals) if vals else None


def _merge_specs(a, b):
    """Union of two specs: a DECLARED mood (1..N) beats an implied one
    (0), the stronger mood wins, motion sets unite. Fresh dict."""
    out = _empty_spec()
    for k in ("shadow", "glass", "grain", "neon", "aurora"):
        out[k] = _merge_level(a.get(k), b.get(k))
    out["motion"] = set(a.get("motion") or set()) \
        | set(b.get("motion") or set())
    return out


# ----------------------------------------------------- layers css parts
def _shadow_section_css():
    return (
        "/* nova layer: shadow - 5-level scale (subtle 1 -> dramatic 5) */\n"
        ":root{\n"
        "  --nv-shadow-1:0 1px 2px rgba(15,23,42,.06);\n"
        "  --nv-shadow-2:0 2px 6px rgba(15,23,42,.07),"
        "0 8px 20px rgba(15,23,42,.07);\n"
        "  --nv-shadow-3:0 4px 12px rgba(15,23,42,.08),"
        "0 16px 34px rgba(15,23,42,.10);\n"
        "  --nv-shadow-4:0 8px 20px rgba(15,23,42,.12),"
        "0 26px 52px rgba(15,23,42,.16);\n"
        "  --nv-shadow-5:0 12px 28px rgba(15,23,42,.18),"
        "0 38px 76px rgba(15,23,42,.24);\n"
        "}\n"
        ".nv-shadow-1{box-shadow:var(--nv-shadow-1)}\n"
        ".nv-shadow-2{box-shadow:var(--nv-shadow-2)}\n"
        ".nv-shadow-3{box-shadow:var(--nv-shadow-3)}\n"
        ".nv-shadow-4{box-shadow:var(--nv-shadow-4)}\n"
        ".nv-shadow-5{box-shadow:var(--nv-shadow-5)}\n"
        ".nv-hover-lift{transition:transform .25s ease,"
        "box-shadow .25s ease}\n"
        ".nv-hover-lift:hover{transform:translateY(-4px);"
        "box-shadow:var(--nv-shadow-4)}\n")


_SHADOW_MOODS = {
    1: ("var(--nv-shadow-1)", "var(--nv-shadow-2)"),
    2: ("var(--nv-shadow-2)", "var(--nv-shadow-3)"),
    3: ("var(--nv-shadow-3)", "var(--nv-shadow-4)"),
    4: ("var(--nv-shadow-4)", "var(--nv-shadow-5)"),
    5: ("var(--nv-shadow-5)", "var(--nv-shadow-5)"),
}


def _shadow_mood_css(level):
    """Site-wide mood: retune the FLOOR's own shadow tokens, so cards,
    tables, pre blocks - everything the floor elevates - follow the
    requested level (later sheet wins the cascade by design)."""
    sh, shlg = _SHADOW_MOODS[level]
    return ("/* nova layer: shadow mood %d - site-wide retune of the "
            "floor tokens */\n:root{--shadow:%s;--shadow-lg:%s}\n"
            % (level, sh, shlg))


_GLASS_LEVELS = (          # level -> (blur px, saturate %, white alpha)
    (4, 120, .60),         # sharp
    (8, 140, .55),
    (14, 150, .45),
    (22, 160, .35),        # misty
)


def _glass_rule(level):
    blur, sat, alpha = _GLASS_LEVELS[level - 1]
    return ("background:rgba(var(--nv-glass-tint),%.2f);"
            "-webkit-backdrop-filter:blur(%dpx) saturate(%d%%);"
            "backdrop-filter:blur(%dpx) saturate(%d%%)"
            % (alpha, blur, sat, blur, sat))


def _glass_section_css():
    return (
        "/* nova layer: glass - frosted scale (sharp 1 -> misty 4); "
        "free of color and font: a dark site retints with "
        "--nv-glass-tint */\n"
        ":root{--nv-glass-tint:255,255,255}\n"
        + "".join(".nv-glass-%d{%s}\n" % (lvl, _glass_rule(lvl))
                  for lvl in (1, 2, 3, 4))
        + ".nv-glass-1,.nv-glass-2,.nv-glass-3,.nv-glass-4{"
          "border:1px solid rgba(var(--nv-glass-tint),.6);"
          "box-shadow:var(--nv-shadow-2,0 2px 6px rgba(15,23,42,.08))}\n"
        + "@supports not ((backdrop-filter:blur(1px)) or "
          "(-webkit-backdrop-filter:blur(1px))){"
          ".nv-glass-1,.nv-glass-2,.nv-glass-3,.nv-glass-4{"
          "background:rgba(var(--nv-glass-tint),.95)}}\n")


def _glass_alias_css(level):
    return ("/* nova layer: glass alias %d - the declared site default */\n"
            ".nv-glass{%s}\n" % (level, _glass_rule(level)))


# --- v8.10: film grain / texture -------------------------------------
# A monochrome SVG turbulence noise, tiled and blended soft-light over
# the element (utilities) or the whole viewport (declared mood). The
# noise is inline (offline, zero requests), pointer-events:none (it can
# never intercept a click) and it hides itself on print and on the rare
# engine without mix-blend-mode (a gray veil is NOT an option).
_GRAIN_URL = ('url("data:image/svg+xml,%3Csvg xmlns='
              "'http://www.w3.org/2000/svg' width='180' height='180'%3E"
              "%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' "
              "baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E"
              "%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E"
              "%3Crect width='100%25' height='100%25' "
              "filter='url(%23n)'/%3E%3C/svg%3E\")")
_GRAIN_LEVELS = (.04, .08, .13, .19)      # mood opacity per level


def _grain_section_css():
    after = ",\n".join(".nv-grain-%d::after" % i for i in (1, 2, 3, 4))
    hide = (".nv-grain-1::after,.nv-grain-2::after,.nv-grain-3::after,"
            ".nv-grain-4::after{display:none}}")
    return (
        "/* nova layer: grain - film texture scale (subtle 1 -> heavy 4); "
        "monochrome noise, soft-light blend, never intercepts clicks */\n"
        + "".join(".nv-grain-%d{position:relative}\n" % i
                  for i in (1, 2, 3, 4))
        + after + "{content:\"\";position:absolute;inset:0;"
          "border-radius:inherit;pointer-events:none;"
          "background-image:" + _GRAIN_URL + ";"
          "background-size:180px 180px;mix-blend-mode:soft-light}\n"
        + "".join(".nv-grain-%d::after{opacity:%s}\n"
                  % (i, "%.2f" % _GRAIN_LEVELS[i - 1])
                  for i in (1, 2, 3, 4))
        + "@supports not (mix-blend-mode:soft-light){" + hide + "\n"
          "@media print{" + hide + "\n")


def _grain_mood_css(level):
    """Site-wide film texture: ONE fixed html::after overlay (html is
    used on purpose - pages practically never style it, body::after is
    a common model hangout). html::after sits in @media screen, so
    printing never gets the veil."""
    return ("/* nova layer: grain mood " + str(level)
            + " - site-wide film texture */\n"
            "@media screen{html::after{content:\"\";position:fixed;"
            "inset:0;z-index:2147483647;pointer-events:none;"
            "background-image:" + _GRAIN_URL + ";"
            "background-size:180px 180px;mix-blend-mode:soft-light;"
            "opacity:" + "%.2f" % _GRAIN_LEVELS[level - 1] + "}}\n"
            "@supports not (mix-blend-mode:soft-light){"
            "html::after{display:none}}\n")


# --- v8.10: neon edges -----------------------------------------------
def _neon_rule(level):
    """border + glow declarations for one neon level (the declared
    alias reuses them); recolorable with --nv-neon:R,G,B (any CSS RGB
    triplet - the default is the floor's indigo)."""
    n = "var(--nv-neon,91,91,214)"
    if level == 1:
        return ("border:1px solid rgba(" + n + ",.8);"
                "box-shadow:0 0 6px rgba(" + n + ",.22),"
                "inset 0 0 6px rgba(" + n + ",.10)")
    if level == 2:
        return ("border:1px solid rgba(" + n + ",.9);"
                "box-shadow:0 0 10px rgba(" + n + ",.42),"
                "0 0 28px rgba(" + n + ",.16),"
                "inset 0 0 12px rgba(" + n + ",.14)")
    return ("border:2px solid rgba(" + n + ",1);"
            "box-shadow:0 0 14px rgba(" + n + ",.55),"
            "0 0 46px rgba(" + n + ",.28),"
            "inset 0 0 18px rgba(" + n + ",.20)")


def _neon_section_css():
    n = "var(--nv-neon,91,91,214)"
    return (
        "/* nova layer: neon - glowing edge scale (crisp 1 -> dramatic 3); "
        "recolor any element with --nv-neon:R,G,B */\n"
        ".nv-neon-1,.nv-neon-2,.nv-neon-3{transition:box-shadow .25s ease,"
        "border-color .25s ease}\n"
        + "".join(".nv-neon-%d{%s}\n" % (i, _neon_rule(i))
                  for i in (1, 2, 3))
        + ".nv-neon-1:hover{box-shadow:0 0 10px rgba(" + n + ",.38),"
          "inset 0 0 9px rgba(" + n + ",.14)}\n"
        + ".nv-neon-2:hover{box-shadow:0 0 14px rgba(" + n + ",.55),"
          "0 0 38px rgba(" + n + ",.24),inset 0 0 15px rgba(" + n
          + ",.18)}\n"
        + ".nv-neon-3:hover{box-shadow:0 0 18px rgba(" + n + ",.65),"
          "0 0 60px rgba(" + n + ",.36),inset 0 0 22px rgba(" + n
          + ",.26)}\n"
        + ".nv-neon-text{color:rgb(" + n + ");"
          "text-shadow:0 0 7px rgba(" + n + ",.55),"
          "0 0 22px rgba(" + n + ",.30)}\n"
        + "@media print{.nv-neon-1,.nv-neon-2,.nv-neon-3,.nv-neon-text{"
          "box-shadow:none;text-shadow:none}}\n")


def _neon_alias_css(level):
    return ("/* nova layer: neon alias " + str(level)
            + " - the declared site default */\n"
            ".nv-neon{" + _neon_rule(level) + "}\n")


# --- v8.10: aurora wash ----------------------------------------------
def _aurora_rule(level):
    """Ambient radial-gradient wash for one level (element form); the
    wash rides background-image, so the element's own background COLOR
    stays untouched and the blobs melt over it. Recolorable."""
    a = "var(--nv-aurora,91,91,214)"
    b = "var(--nv-aurora2,14,165,233)"
    if level == 1:
        return ("background-image:"
                "radial-gradient(640px 340px at 12% -6%,"
                "rgba(" + a + ",.07),transparent 62%),"
                "radial-gradient(560px 320px at 96% 8%,"
                "rgba(" + b + ",.06),transparent 58%)")
    if level == 2:
        return ("background-image:"
                "radial-gradient(720px 380px at 10% -8%,"
                "rgba(" + a + ",.13),transparent 62%),"
                "radial-gradient(620px 360px at 98% 6%,"
                "rgba(" + b + ",.11),transparent 58%)")
    return ("background-image:"
            "radial-gradient(780px 420px at 8% -10%,"
            "rgba(" + a + ",.20),transparent 62%),"
            "radial-gradient(680px 400px at 100% 4%,"
            "rgba(" + b + ",.16),transparent 58%),"
            "radial-gradient(600px 360px at 50% 112%,"
            "rgba(" + a + ",.12),transparent 60%)")


def _aurora_section_css():
    return (
        "/* nova layer: aurora - ambient gradient wash (whisper 1 -> "
        "vivid 3); recolor with --nv-aurora:R,G,B and "
        "--nv-aurora2:R,G,B */\n"
        + "".join(".nv-aurora-%d{%s}\n" % (i, _aurora_rule(i))
                  for i in (1, 2, 3)))


def _aurora_mood_css(level):
    """Site-wide ambient wash: the body's background-image is remapped
    (the declared mood wins the cascade by design, exactly like the
    shadow mood remaps the floor tokens), the base color of the page
    stays untouched, and a slow 26s drift rides the usual
    prefers-reduced-motion guard."""
    a = "var(--nv-aurora,91,91,214)"
    b = "var(--nv-aurora2,14,165,233)"
    alphas = {1: (.05, .04, .03), 2: (.10, .08, .06),
              3: (.16, .13, .10)}[level]
    return (
        "/* nova layer: aurora mood " + str(level)
        + " - site-wide ambient wash (slow drift behind the content) */\n"
        "body{background-image:"
        "radial-gradient(1100px 560px at 8% -8%,rgba(" + a + ","
        + "%.2f" % alphas[0] + "),transparent 62%),"
        "radial-gradient(900px 520px at 98% 4%,rgba(" + b + ","
        + "%.2f" % alphas[1] + "),transparent 58%),"
        "radial-gradient(820px 480px at 50% 110%,rgba(" + a + ","
        + "%.2f" % alphas[2] + "),transparent 60%);"
        "background-size:140% 140%,140% 140%,140% 140%;"
        "background-repeat:no-repeat,no-repeat,no-repeat}\n"
        "@media (prefers-reduced-motion:no-preference){"
        "body{animation:nv-aurora-drift 26s ease-in-out "
        "infinite alternate}}\n"
        "@keyframes nv-aurora-drift{from{background-position:"
        "0% 0%,100% 0%,50% 100%}to{background-position:"
        "6% 4%,92% 0%,50% 92%}}\n"
        "@media print{body{animation:none;background-image:none}}\n")


def _motion_block(name):
    keyframes, rule = {
        "float": ("@keyframes nv-float{0%,100%{transform:translateY(0)}"
                  "50%{transform:translateY(-8px)}}",
                  "animation:nv-float 6s ease-in-out infinite"),
        "fade-down": (
            "@keyframes nv-fade-down{from{opacity:0;"
            "transform:translateY(-18px)}to{opacity:1;transform:none}}",
            "animation:nv-fade-down .7s ease-out both"),
        "fade-up": (
            "@keyframes nv-fade-up{from{opacity:0;"
            "transform:translateY(18px)}to{opacity:1;transform:none}}",
            "animation:nv-fade-up .7s ease-out both"),
        "slide-in": (
            "@keyframes nv-slide-in{from{opacity:0;"
            "transform:translateX(-24px)}to{opacity:1;transform:none}}",
            "animation:nv-slide-in .6s cubic-bezier(.22,1,.36,1) both"),
        "pop": ("@keyframes nv-pop{0%{opacity:0;transform:scale(.94)}"
                "60%{transform:scale(1.015)}100%{opacity:1;"
                "transform:scale(1)}}",
                "animation:nv-pop .5s ease-out both"),
        "glow": ("@keyframes nv-glow{0%,100%{box-shadow:0 0 0 0 "
                 "rgba(var(--nv-glow,91,91,214),.35)}50%{box-shadow:"
                 "0 0 0 10px rgba(var(--nv-glow,91,91,214),0)}}",
                 "animation:nv-glow 2.6s ease-in-out infinite"),
    }[name]
    return ("/* nova layer: motion - %s */\n"
            "@media (prefers-reduced-motion: no-preference){\n"
            "%s\n.nv-anim-%s{%s}\n}\n" % (name, keyframes, name, rule))


_MOTION_STAGGER_CSS = (
    "/* nova layer: motion - stagger helper (.nv-stagger on a parent) */\n"
    "@media (prefers-reduced-motion: no-preference){\n"
    ".nv-stagger>*:nth-child(1){animation-delay:.06s}\n"
    ".nv-stagger>*:nth-child(2){animation-delay:.12s}\n"
    ".nv-stagger>*:nth-child(3){animation-delay:.18s}\n"
    ".nv-stagger>*:nth-child(4){animation-delay:.24s}\n"
    ".nv-stagger>*:nth-child(5){animation-delay:.3s}\n"
    ".nv-stagger>*:nth-child(6){animation-delay:.36s}\n"
    ".nv-stagger>*:nth-child(n+7){animation-delay:.42s}\n"
    "}\n")


_LAYERS_HEADER = ("/* nova-layers.css - OPTIONAL Nova design layers, "
                  "written because the page asked for them (the "
                  "nova-layers meta / the nv- classes). Safe to "
                  "delete. */\n")


def layers_css(spec):
    """The deterministic layer sheet for one spec - ONLY the requested
    layers are emitted, each behind its stable 'nova layer:' marker
    (which _spec_from_sheet reads back for merges). Deterministic and
    byte-stable per spec."""
    parts = [_LAYERS_HEADER]
    if spec.get("shadow") is not None:
        parts.append(_shadow_section_css())
        if spec["shadow"] >= 1:
            parts.append(_shadow_mood_css(spec["shadow"]))
    if spec.get("glass") is not None:
        parts.append(_glass_section_css())
        if spec["glass"] >= 1:
            parts.append(_glass_alias_css(spec["glass"]))
    if spec.get("grain") is not None:
        parts.append(_grain_section_css())
        if spec["grain"] >= 1:
            parts.append(_grain_mood_css(spec["grain"]))
    if spec.get("neon") is not None:
        parts.append(_neon_section_css())
        if spec["neon"] >= 1:
            parts.append(_neon_alias_css(spec["neon"]))
    if spec.get("aurora") is not None:
        parts.append(_aurora_section_css())
        if spec["aurora"] >= 1:
            parts.append(_aurora_mood_css(spec["aurora"]))
    motion = spec.get("motion") or set()
    for name in _MOTION_PRESETS:
        if name in motion:
            parts.append(_motion_block(name))
    if motion:
        parts.append(_MOTION_STAGGER_CSS)
    return "".join(parts)


def _spec_from_sheet(text):
    """Reverse-parse a Nova-made layers sheet back into a spec, so a new
    request MERGES with (never shrinks) what earlier turns added."""
    spec = _empty_spec()
    try:
        kinds = set(m.group(1) for m in
                    re.finditer(r"/\* nova layer: ([a-z]+)\b", text or ""))
        if "shadow" in kinds:
            m = _SHEET_MOOD_RE.search(text)
            spec["shadow"] = int(m.group(1)) if m else 0
        if "glass" in kinds:
            m = _SHEET_ALIAS_RE.search(text)
            spec["glass"] = int(m.group(1)) if m else 0
        if "grain" in kinds:
            m = _SHEET_GRAIN_MOOD_RE.search(text)
            spec["grain"] = int(m.group(1)) if m else 0
        if "neon" in kinds:
            m = _SHEET_NEON_ALIAS_RE.search(text)
            spec["neon"] = int(m.group(1)) if m else 0
        if "aurora" in kinds:
            m = _SHEET_AURORA_MOOD_RE.search(text)
            spec["aurora"] = int(m.group(1)) if m else 0
        if "motion" in kinds:
            found = set(_SHEET_ANIM_RE.findall(text)) & set(_MOTION_PRESETS)
            spec["motion"] = found or set(_MOTION_PRESETS)
    except Exception:
        pass
    return spec


def _spec_label(spec):
    def lvl(v, top):
        return (str(v) + "/" + top) if v else "utilities"
    bits = []
    if spec.get("shadow") is not None:
        bits.append("shadow " + lvl(spec["shadow"], "5"))
    if spec.get("glass") is not None:
        bits.append("glass " + lvl(spec["glass"], "4"))
    if spec.get("grain") is not None:
        bits.append("grain " + lvl(spec["grain"], "4"))
    if spec.get("neon") is not None:
        bits.append("neon " + lvl(spec["neon"], "3"))
    if spec.get("aurora") is not None:
        bits.append("aurora " + lvl(spec["aurora"], "3"))
    mot = sorted(spec.get("motion") or ())
    if mot:
        bits.append("motion " + "+".join(mot))
    return ", ".join(bits)


def _layers_linked(content):
    """True when a <link> already targets nova-layers.css (any folder,
    any cache-bust - mirrors _script_linked's rule)."""
    return bool(_LAYERS_LINK_HREF_RE.search(content or ""))


def _layers_href_target(href, parent_rel):
    """Workspace-relative target of a nova-layers.css href found on a
    page (None when the href is external or escapes the workspace)."""
    try:
        h = str(href or "").split("?", 1)[0].split("#", 1)[0].strip()
        if not h or h.startswith(("/", "http:", "https:", "//", "data:",
                                    "#")):
            return None
        norm = posixpath.normpath(
            (parent_rel + "/" + h) if parent_rel else h)
        if norm == ".." or norm.startswith("../") or norm.startswith("/"):
            return None
        if Path(norm).name.lower() != LAYERS_FILE:
            return None
        return norm.replace("\\", "/")
    except Exception:
        return None


def _inject_layers_link(text, pre):
    """Insert the layers link BEFORE </head> so it cascades after the
    floor and the page's own sheets. Without a </head> (the head was
    built by polish), it lands after the LAST stylesheet link - or at
    the head-open position as a final fallback. Returns
    (new_text, changed)."""
    tag = '<link rel="stylesheet" href="' + pre + LAYERS_FILE + '">\n'
    m = _HEAD_CLOSE_RE.search(text)
    if m:
        return text[:m.start()] + tag + text[m.start():], True
    last = None
    for lm in _LINK_RE.finditer(text):
        if _REL_STYLE_RE.search(lm.group(0)):
            last = lm
    if last is not None:
        return text[:last.end()] + "\n" + tag.rstrip("\n") \
            + text[last.end():], True
    pos, _built = _head_insert_pos(text)
    return text[:pos] + tag + text[pos:], True


# --------------------------------------------------------------- helpers
_HEAD_RE = re.compile(r"<head\b[^>]*>", re.I)
_HTML_OPEN_RE = re.compile(r"<html\b[^>]*>", re.I)
_DOCTYPE_RE = re.compile(r"<!doctype\s+html[^>]*>", re.I)
_CHARSET_RE = re.compile(r"<meta[^>]*charset", re.I)
_VIEWPORT_RE = re.compile(r"<meta[^>]*name\s*=\s*[\"']viewport[\"']", re.I)
_TITLE_RE = re.compile(r"<title[\s>]", re.I)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_REL_STYLE_RE = re.compile(r"rel\s*=\s*[\"']?stylesheet", re.I)
_HREF_RE = re.compile(r"href\s*=\s*[\"']([^\"']+)[\"']", re.I)
_STYLE_RE = re.compile(r"<style[\s>]", re.I)
_FULLPAGE_RE = re.compile(r"<!doctype\s*html|<html[\s>]", re.I)
_LOCAL_URL_RE = re.compile(r"^(https?:)?//|^data:|^#|^mailto:", re.I)


def _is_full_page(text):
    return bool(_FULLPAGE_RE.search(text or ""))


def _head_insert_pos(text):
    """Position (idx) right after the <head> open tag - or build a head
    after <html ...> / after the DOCTYPE when the model forgot them.
    v7.1.0 fix: a doctype-only page (valid HTML5, no <html>/<head> tags)
    used to get its meta/link injected BEFORE the doctype - browsers then
    render quirks mode and the whole design floor loses its box-sizing.
    Returns (pos, head_built)."""
    m = _HEAD_RE.search(text)
    if m:
        return m.end(), False
    m = _HTML_OPEN_RE.search(text)
    if m:
        return m.end(), True
    m = _DOCTYPE_RE.search(text)
    if m:
        return m.end(), True
    return 0, True


def _ensure_head_block(text):
    """Guarantee a <head>...</head> region exists; return (text, note).
    v7.1.0: a doctype-only page gets a <head> right after the doctype
    (never before it - that would flip quirks mode)."""
    if _HEAD_RE.search(text):
        return text, ""
    m = _HTML_OPEN_RE.search(text) or _DOCTYPE_RE.search(text)
    if not m:
        return text, ""      # fragment - leave it alone
    pos = m.end()
    block = "\n<head>\n<meta charset=\"utf-8\">\n"
    return text[:pos] + block + text[pos:], "head"


def polish_html(content, doc_name="index.html"):
    """Deterministic head polish for one FULL html page:
    charset -> viewport -> title. Returns (new_content, notes[]).
    Fragments (no <html>/<doctype>) pass through untouched."""
    src = content or ""
    notes = []
    if not _is_full_page(src) or len(src) > MAX_POLISH_BYTES:
        return src, notes

    text = src
    # 1) a <head> region to insert into
    text, head_note = _ensure_head_block(text)
    if head_note:
        notes.append("missing <head> added")

    pos, _ = _head_insert_pos(text)
    inject = ""

    # 2) charset
    if not _CHARSET_RE.search(text):
        inject += "<meta charset=\"utf-8\">\n"
        notes.append("charset meta added")
    # 3) viewport (the #1 reason a 'broken mobile site' is actually fine)
    if not _VIEWPORT_RE.search(text):
        inject += "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        notes.append("viewport meta added")
    # 4) title
    if not _TITLE_RE.search(text):
        safe = re.sub(r"[<>\"']", "", str(doc_name or "Page"))
        inject += f"<title>{safe}</title>\n"
        notes.append("title added")

    if inject:
        text = text[:pos] + inject + text[pos:]
    return text, notes


def stylesheet_hrefs(content):
    """Local stylesheet hrefs referenced by one html document (in order).
    Query strings / fragments are stripped (cache-busted hrefs like
    'style.css?v=2' resolve to the real file, never to a junk name)."""
    out = []
    for tag in _LINK_RE.finditer(content or ""):
        if not _REL_STYLE_RE.search(tag.group(0)):
            continue
        m = _HREF_RE.search(tag.group(0))
        if not m:
            continue
        href = m.group(1).strip()
        if not href or _LOCAL_URL_RE.match(href):
            continue
        href = re.split(r"[?#]", href, 1)[0]
        if not href:
            continue
        if href not in out:
            out.append(href)
    return out


def _has_inline_style(content):
    return bool(_STYLE_RE.search(content or ""))


def _script_linked(content, name):
    """True when a <script src="...name"> tag already references `name`.
    v7.2 audit fix: cache-busted srcs (`nova-ui.js?v=2`) count too - the
    tag used to be injected a SECOND time next to them."""
    pat = ("<script\\b[^>]*src\\s*=\\s*[\"'](?:[^\"]*/)?"
           + re.escape(name) + r"(?:[?#][^\"']*)?[\"']")
    return bool(re.search(pat, content or "", re.I))


def _atomic_write(path: Path, data: str):
    """tmp file + os.replace: a crash mid-polish can never truncate a file."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------- entry
def design_polish(ws, applied_names, seed=None):
    """The v7.0 post-apply beauty floor, v7.2 palette-stamped.
    `ws` = workspace Path, `applied_names` = [relpath] of the files THIS
    apply just wrote, `seed` = the user's own request text (None keeps
    the plain default sheet - direct callers and old tests). May REWRITE
    applied .html files in place (polished heads) and returns
    (extra_writes, notes):
        extra_writes = [(relpath, css_or_js_text)] - stylesheets (+ the
                       motion enhancer) Nova adds so every produced page
                       is styled (the floor),
        notes        = [str] - human-readable actions for console + web.
    Fail-soft per file; the whole call never raises."""
    extras, notes = [], []
    if not enabled():
        return extras, notes
    ws = Path(ws)
    try:
        htmls = [n for n in (applied_names or [])
                 if str(n).lower().endswith((".html", ".htm"))]
        if not htmls:
            return extras, notes
        written_css = {str(n) for n in (applied_names or [])
                       if str(n).lower().endswith(".css")}
        written_js = set()    # v7.2 audit fix: nova-ui.js exactly ONCE per
                              # pass (a duplicate extra used to make /undo
                              # delete-then-RESTORE the file - an orphan)
        floor = floor_css(seed)
        batch_spec = None             # v8.9: union of the layer requests
        layer_copy_targets = set()    # v8.9: manual-link folder copies

        def _css_extras():
            # v7.2 audit fix: only stylesheets count toward MAX_EXTRA_CSS -
            # the js extra used to eat the cap and leave later pages naked
            # v8.9: the single layers sheet never eats a floor slot either
            return sum(1 for e in extras
                       if str(e[0]).lower().endswith(".css")
                       and e[0] != LAYERS_FILE)

        def _offer_js(parent_rel=""):
            if "nova-ui.js" not in written_js \
                    and not (ws / "nova-ui.js").is_file():
                extras.append(("nova-ui.js", NOVA_UI_JS))
                written_js.add("nova-ui.js")
            # v7.4 audit fix: a NESTED page linking nova-ui.js resolves it
            # INSIDE its own folder - without a copy there the motion js
            # 404'd forever (the root file could not serve it)
            if parent_rel:
                nj = parent_rel + "/nova-ui.js"
                if nj not in written_js and not (ws / nj).is_file():
                    extras.append((nj, NOVA_UI_JS))
                    written_js.add(nj)

        def _parent_rel(name):
            pr = Path(name).parent
            return "" if str(pr) == "." else pr.as_posix()

        for name in htmls[:6]:          # cap the work per batch
          try:
            p = Path(ws) / name
            # v8.0: the page itself is containment-checked like the two
            # sibling passes - an absolute or ../ name used to resolve
            # OUTSIDE the workspace (Path() discards ws on absolute paths).
            try:
                _p_res = p.resolve()
                _p_res.relative_to(Path(ws).resolve())
            except (ValueError, OSError):
                continue
            parent_rel = _parent_rel(name)
            if not p.is_file() or p.stat().st_size > MAX_POLISH_BYTES:
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")

            # --- 0) v8.9 OPTIONAL design layers: recorded from the
            # nova-layers meta, the nv- utility classes or a manual
            # nova-layers.css link. The SHEET is written once per batch
            # below; the LINK is injected at step 4 (full pages only,
            # before </head> so it cascades after the floor).
            layers_pre = ("../" * len(Path(name).parent.parts)
                          if str(Path(name).parent) != "." else "")
            declared = layers_meta(raw)
            implied = _implied_layers(raw)
            manual = _layers_linked(raw)
            if declared is not None:
                spec = _merge_specs(declared, implied)
            elif (implied["shadow"] is not None
                    or implied["glass"] is not None or implied["motion"]
                    or implied["grain"] is not None
                    or implied["neon"] is not None
                    or implied["aurora"] is not None):
                spec = implied
            elif manual:
                # v8.10: utilities-only baseline for the two floor-touching
                # layers + whatever the nv- classes imply (the merge knows
                # every layer key, now and later)
                spec = _merge_specs({"shadow": 0, "glass": 0}, implied)
            else:
                spec = None
            if spec is not None:
                batch_spec = spec if batch_spec is None \
                    else _merge_specs(batch_spec, spec)
                for lm in _LAYERS_LINK_HREF_RE.findall(raw):
                    tgt = _layers_href_target(lm, parent_rel)
                    if tgt:
                        layer_copy_targets.add(tgt)
            # v8.9: the bare-page check below must stay blind to a
            # layers link (the link is injected later, at step 4)
            styled = bool(stylesheet_hrefs(raw)) or _has_inline_style(raw)

            # --- 1) fill a REFERENCED but MISSING local stylesheet ---
            # (the classic weak-model failure: index.html links
            #  css/style.css but the model never outputs it - the page
            #  then renders naked. Nova fills the gap with the floor.)
            filled = False
            ws_root = ws.resolve()
            for href in stylesheet_hrefs(raw):
                # root-absolute hrefs ('/css/style.css') resolve
                # against the workspace root, not the html's folder
                if href.startswith("/"):
                    target = (ws_root / href.lstrip("/")).resolve()
                else:
                    target = (p.parent / href).resolve()
                try:
                    rel = str(target.relative_to(ws_root)
                              ).replace("\\", "/")
                except ValueError:
                    continue          # escapes the workspace - ignore
                if not rel or rel in written_css or target.is_file():
                    continue
                # v8.9: a manual nova-layers.css link is the layers
                # writer's job - never filled with the floor sheet
                if Path(rel).name.lower() == LAYERS_FILE:
                    continue
                if _css_extras() >= MAX_EXTRA_CSS:
                    break
                extras.append((rel, floor))
                written_css.add(rel)
                notes.append(f"missing stylesheet '{href}' was created "
                             "with the Nova design floor")
                filled = True
                # v7.2: the motion enhancer rides EVERY floor fill
                # (deferred, safe to delete, honors reduced motion).
                # v7.2 audit fix: FULL PAGES only - a fragment has no
                # head, the tag used to be prepended at position 0.
                if _is_full_page(raw):
                    if not _script_linked(raw, "nova-ui.js"):
                        text, _h = polish_html(raw, name)
                        pos, _ = _head_insert_pos(text)
                        text = (text[:pos]
                                + '<script src="nova-ui.js" defer></script>\n'
                                + text[pos:])
                        if text != raw:
                            _atomic_write(p, text)
                            # keep `raw` in sync: the case-3 head polish
                            # below re-reads it and would otherwise clobber
                            # the script tag with the pre-polish text
                            raw = text
                        # v8.0 audit fix: the injected src="nova-ui.js"
                        # resolves INSIDE the page's own folder - a nested
                        # page needs a copy there too (the legacy branch
                        # got this in v7.4; the fill branch forgot it).
                        _offer_js(parent_rel)
                    else:
                        # v7.4 audit fix: legacy self-heal - an old nested
                        # page links nova-ui.js root-relative; give that
                        # resolution path a real file
                        _offer_js(parent_rel)
                break                 # one floor sheet per page

            # --- 2) page with NO styling at all -> link the floor ---
            # v8.9: 'styled' was captured before the layers scan (the
            # layers link is injected later, at step 4, and must not
            # make a bare page look styled); the early 'continue' became
            # if/else so step 4 still runs for bare pages
            if not filled and not styled \
                    and not _has_inline_style(raw) and _is_full_page(raw):
                if _css_extras() < MAX_EXTRA_CSS:
                    # v7.4 audit fix: the href used to be verbatim
                    # 'nova-ui.css' - from a nested page that resolves to
                    # pages/nova-ui.css (404). It now carries the correct
                    # ../ depth, exactly like the fonts link does.
                    pre = ("../" * (len(Path(name).parent.parts)
                                    if str(Path(name).parent) != "." else 0))
                    head_add = ('<link rel="stylesheet" href="' + pre
                                + 'nova-ui.css">\n<script src="' + pre
                                + 'nova-ui.js" defer></script>\n')
                    text, _hnotes = polish_html(raw, name)
                    if not any("nova-ui.css" in h
                               for h in stylesheet_hrefs(text)):
                        pos, _ = _head_insert_pos(text)
                        text = text[:pos] + head_add + text[pos:]
                        notes.append("page had no styles - nova-ui.css "
                                     "(Nova design floor) linked")
                    if text != raw:
                        _atomic_write(p, text)
                    floor_rel = "nova-ui.css"
                    if floor_rel not in written_css \
                            and not (ws / floor_rel).is_file():
                        extras.append((floor_rel, floor))
                        written_css.add(floor_rel)
                    _offer_js()

            # --- 3) plain head polish (charset/viewport/title) ---
            else:
                text, hnotes = polish_html(raw, name)
                if hnotes:
                    _atomic_write(p, text)
                    notes.append(f"{name}: " + ", ".join(hnotes))

            # --- 4) v8.9 layers link: full pages that opted in get the
            # stylesheet link, injected into the DISK state so whatever
            # steps 1-3 just wrote is preserved (and the link always
            # lands after those sheets in the cascade)
            if spec is not None and _is_full_page(raw) \
                    and not _layers_linked(raw):
                disk = p.read_text(encoding="utf-8", errors="replace")
                new, changed = _inject_layers_link(disk, layers_pre)
                if changed and new != disk:
                    _atomic_write(p, new)
                    notes.append(LAYERS_FILE + " linked into " + name)
          except Exception as e:        # one bad page never stops the rest
            notes.append(f"{name}: polish skipped ({type(e).__name__})")

        # ---- v8.9: the layers sheet - ONE deterministic file per
        # project. A previous Nova-made sheet is merged (the union never
        # shrinks); a file the user wrote themselves is never touched.
        if batch_spec is not None:
            try:
                lp = ws / LAYERS_FILE
                old = lp.read_text(encoding="utf-8", errors="replace") \
                    if lp.is_file() else None
                sheet = None
                if old is not None and old.lstrip().startswith(
                        "/* nova-layers.css"):
                    merged = _merge_specs(batch_spec, _spec_from_sheet(old))
                    sheet = layers_css(merged)
                    if sheet != old:
                        extras.append((LAYERS_FILE, sheet))
                        notes.append("design layers updated -> "
                                     + LAYERS_FILE)
                elif old is None:
                    sheet = layers_css(batch_spec)
                    extras.append((LAYERS_FILE, sheet))
                    notes.append("design layers added ("
                                 + _spec_label(batch_spec) + ") -> "
                                 + LAYERS_FILE)
                if sheet is not None:
                    for tgt in sorted(layer_copy_targets):
                        if tgt == LAYERS_FILE:
                            continue
                        if not (ws / tgt).is_file():
                            extras.append((tgt, sheet))
                            notes.append(tgt + " written (nova-layers copy)")
            except Exception as e:
                notes.append("layers skipped (" + type(e).__name__ + ")")
    except Exception as e:
        notes.append(f"design floor skipped ({type(e).__name__})")
    return extras, notes
