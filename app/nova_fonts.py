#!/usr/bin/env python3
# =====================================================================
#  Nova Code - FONT ENGINE (v7.3)
#  "A local font library for many languages (Persian first, English
#   second) - and an agent that PICKS the right pairing per project."
#
#  Everything here is DETERMINISTIC and OFFLINE: the woff2 binaries live
#  in app/fonts/ (fetched once by scripts/fetch_fonts_v730.py, all under
#  the SIL OFL 1.1), so a generated website uses real, beautiful fonts
#  with zero CDN requests, zero model calls and zero API keys.
#
#  Layers:
#    1. library()       - the font registry read from fonts/index.json
#                         (name, script fa/en, category, weights, files)
#    2. pick_fonts()    - context-aware pairing: page/request language
#                         (fa/en) + a mood detector (modern-tech,
#                         elegant-editorial, friendly-playful, bold-display,
#                         creative-artistic, minimal-clean) ranked per
#                         mood, seeded by the user's own words - every
#                         project gets a fitting, slightly different
#                         pairing while the same request stays stable.
#                         The MODEL can override everything per page via
#                         <meta name="nova-fonts" content="...">.
#    3. fonts_css()     - @font-face block (unicode-range subsets) +
#                         :root tokens (--font-display/-body/-mono) +
#                         ZERO-specificity :where() defaults, so the
#                         model's own CSS always wins (freedom, not lock).
#    4. install_pass()  - the deterministic post-apply pass: copies the
#                         needed woff2 files into <ws>/fonts/, writes
#                         nova-fonts.css when no @font-face exists yet,
#                         links it into the pages and adds dir="rtl" to
#                         Persian pages that forgot it.
#
#  Kill switch: NOVA_NO_FONTS=1 -> the engine stays out completely.
#  Missing fonts dir / index -> available() False, install_pass no-ops.
#  Fail-soft everywhere, exactly like every other nova_* module.
# =====================================================================
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

__all__ = ["enabled", "available", "library", "pick_fonts", "fonts_css",
           "install_pass", "parse_font_meta", "detect_mood", "Choice",
           "MOOD_PAIRS", "MOOD_KEYWORDS"]

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
MAX_PAGES_PER_PASS = 6        # cap the work per applied batch
MAX_FONT_FILES = 14           # cap the copied binaries per batch
CSS_NAME = "nova-fonts.css"

# woff2 files above this are suspicious (not a font we shipped)
MAX_FONT_FILE_BYTES = 2_500_000

# --------------------------------------------------------------- kill switch
def enabled():
    return os.environ.get("NOVA_NO_FONTS") != "1"


# --------------------------------------------------------------- library
_INDEX = None


def _index():
    """The registry from fonts/index.json, cached. Fail-soft: a missing
    or corrupt index means 'no library' - the engine just stays out.
    A FAILED read is NOT cached: a repaired/fetched index is picked up
    by the very next call (a corrupt file must not poison the process)."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    try:
        data = json.loads(
            (FONTS_DIR / "index.json").read_text(encoding="utf-8"))
        fonts = data.get("fonts")
        if not isinstance(fonts, dict):
            raise ValueError("no fonts table")
        _INDEX = fonts
    except Exception:
        return {}
    return _INDEX


def library():
    """Only fonts whose files actually exist on disk (a stripped copy of
    Nova must still work - it just offers fewer pairings)."""
    out = {}
    for slug, f in _index().items():
        try:
            ok = all((FONTS_DIR / rel).is_file()
                     for w in f.get("weights", {}).values()
                     for rel in w.values())
        except Exception:
            ok = False
        if ok:
            out[slug] = f
    return out


def available():
    return enabled() and bool(library())


def find(name):
    """Case-insensitive lookup by display name OR slug -> (slug, entry)."""
    if not name:
        return None
    want = str(name).strip().lower()
    if not want:
        return None
    lib = library()
    for slug, f in lib.items():
        if slug.lower() == want or str(f.get("name", "")).lower() == want:
            return slug, f
    return None


# --------------------------------------------------------------- context
_FA_CHAR = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_CHAR = re.compile(r"[A-Za-z\u00C0-\u024F]")


def detect_script(text):
    """'fa' when the text clearly carries Arabic-script letters, else
    'en'. A handful of Persian words in a latin sentence still counts as
    fa - the product's primary audience types Persian."""
    t = str(text or "")
    if not t:
        return "fa"          # the app's home audience; fail Persian
    fa = len(_FA_CHAR.findall(t))
    if fa >= 2:
        return "fa"
    return "en" if _LATIN_CHAR.search(t) else "fa"


# moods: keyword -> score. Persian first, English aliases. Kept small on
# purpose - the detector must stay explainable, not another neural net.
MOOD_KEYWORDS = {
    "modern-tech": (
        "تکنولوژی", "فناوری", "استارتاپ", "هوش مصنوعی", "دیجیتال", "نرم‌افزار",
        "اپلیکیشن", "سرویس", "داده", "داشبورد", "ابر",
        "tech", "startup", "saas", "ai", "software", "digital", "cloud",
        "data", "developer", "code", "crypto", "fintech", "modern"),
    "elegant-editorial": (
        "مجله", "خبر", "مقاله", "رستوران", "کافه", "لوکس", "لاکچری", "عکاسی",
        "هتل", "عروس", "شعر", "ادبی", "کلاسیک",
        "magazine", "news", "journal", "blog", "restaurant", "luxury",
        "photography", "hotel", "wedding", "elegant", "editorial",
        "classic", "serif"),
    "friendly-playful": (
        "کودک", "بچه", "بازی", "سرگرمی", "آموزش", "مدرسه", "شاد", "رنگارنگ",
        "کارتون", "فان",
        "kids", "child", "toy", "game", "fun", "playful", "school",
        "education", "colorful", "cute", "cartoon"),
    "bold-display": (
        "فروش", "تخفیف", "کمپین", "رویداد", "کنسرت", "ورزشی", "باشگاه",
        "تبلیغ", "برند",
        "sale", "discount", "campaign", "event", "concert", "sport",
        "gym", "fitness", "bold", "poster", "launch", "brand"),
    "creative-artistic": (
        "هنر", "خلاق", "آژانس", "طراحی", "موسیقی", "گالری", "نمایشگاه",
        "دست‌ساز",
        # v7.4 audit fix: the bare verb 'ساخت' (build/make) used to sit
        # here - 'ساخت سایت فروشگاه' scored creative 1 vs minimal 1 and
        # the tie handed an online shop a calligraphy pairing. It is the
        # most common verb in every build request, never a mood signal.
        "art", "creative", "studio", "music", "gallery", "design",
        "portfolio", "handmade", "craft", "festival"),
    "minimal-clean": (
        "ساده", "مینیمال", "حرفه‌ای", "کسب‌وکار", "شرکتی", "رزومه", "فروشگاه",
        "minimal", "clean", "simple", "business", "corporate", "resume",
        "cv", "shop", "store", "agency", "product", "landing"),
}


def detect_mood(text):
    """The dominant mood of a request (default: minimal-clean).
    Matching is deliberately conservative - a FALSE positive forces a
    wrong personality onto a whole project, a missed keyword only falls
    back to the clean default:
      - single words: EXACT token equality (Persian 'فروش' must not match
        inside 'فروشگاه', latin 'art' must not match inside 'article')
      - multi-word phrases ('هوش مصنوعی'): substring
      - latin words: \\b-delimited ('ai' never matches 'email')
    Ties keep the FIRST mood in MOOD_KEYWORDS order - stable/explainable."""
    raw = str(text or "")
    if not raw:
        return "minimal-clean"
    low = raw.lower()
    # tokens keep in-word ZWNJ ('کسب‌وکار' stays one token)
    tokens = {t.strip(".,!?؛،:;()[]«»\"'-–—").lower()
              for t in raw.split()} - {""}
    best, best_score = "minimal-clean", 0
    for mood, words in MOOD_KEYWORDS.items():
        score = 0
        for w in words:
            if " " in w:                      # phrase: substring (both fa/en)
                score += 1 if w in low else 0
            elif re.search(r"[a-z]", w, re.I):  # latin word: \b-delimited
                score += 1 if re.search(
                    r"\b" + re.escape(w) + r"\b", low) else 0
            else:                              # persian word: exact token
                score += 1 if w in tokens else 0
        if score > best_score:
            best, best_score = mood, score
    return best


# --------------------------------------------------------------- pairings
# Per mood, per script: ranked (heading font, body font) pairs. Every name
# MUST exist in the library (find() filters silently if a font is gone).
MOOD_PAIRS = {
    "modern-tech": {
        "fa": [("Lalezar", "Vazirmatn"), ("Noto Kufi Arabic", "Estedad"),
               ("El Messiri", "Shabnam"), ("Rubik", "Vazirmatn")],
        "en": [("Space Grotesk", "Inter"), ("Unbounded", "Manrope"),
               ("Oswald", "DM Sans"), ("Sora", "Inter")],
    },
    "elegant-editorial": {
        "fa": [("Markazi Text", "Vazirmatn"), ("Amiri", "Estedad"),
               ("Aref Ruqaa", "Vazirmatn"), ("Noto Naskh Arabic", "Sahel")],
        "en": [("Playfair Display", "Lora"), ("Cormorant Garamond", "EB Garamond"),
               ("Fraunces", "Work Sans"), ("Libre Baskerville", "Inter")],
    },
    "friendly-playful": {
        "fa": [("Baloo Bhaijaan 2", "Vazirmatn"), ("Katibeh", "Estedad"),
               ("Tanha", "Shabnam")],
        "en": [("Quicksand", "Nunito"), ("Caveat", "Poppins"),
               ("Baloo Bhaijaan 2", "Vazirmatn")],
    },
    "bold-display": {
        "fa": [("Lalezar", "Vazirmatn"), ("Reem Kufi", "Estedad"),
               ("Mirza", "Samim")],
        "en": [("Bebas Neue", "Inter"), ("Anton", "Montserrat"),
               ("Archivo Black", "Work Sans"), ("Oswald", "Raleway")],
    },
    "creative-artistic": {
        "fa": [("Gulzar", "Vazirmatn"), ("Noto Nastaliq Urdu", "Estedad"),
               ("Aref Ruqaa", "Shabnam"), ("Nahid", "Vazirmatn")],
        "en": [("Syne", "DM Sans"), ("Unbounded", "Outfit"),
               ("Great Vibes", "Lora"), ("Syne", "Urbanist")],
    },
    "minimal-clean": {
        "fa": [("Estedad", "Vazirmatn"), ("IBM Plex Sans Arabic", "Estedad"),
               ("Vazirmatn", "Shabnam"), ("Readex Pro", "Vazirmatn")],
        "en": [("Sora", "Inter"), ("Outfit", "DM Sans"),
               ("Manrope", "Inter"), ("Urbanist", "Work Sans")],
    },
}

# code font: Latin-only by design (code is latin) - seeded variety
_MONOS = ["JetBrains Mono", "Fira Code", "IBM Plex Mono", "Space Mono",
          "Source Code Pro"]

# Persian pages ALWAYS also get Vazirmatn installed: the design floor's
# default --font stack names it, so the floor stays coherent even when a
# project's own pairing has a different body font.
FA_FALLBACK_BODY = "Vazirmatn"


class Choice:
    """One resolved font pairing. Plain and printable - it travels into
    notes and tests."""

    __slots__ = ("display", "body", "mono", "mood", "script", "source")

    def __init__(self, display, body, mono, mood, script, source="auto"):
        self.display = display
        self.body = body
        self.mono = mono
        self.mood = mood
        self.script = script
        self.source = source

    def __repr__(self):
        return (f"Choice({self.display!r} + {self.body!r} + {self.mono!r}, "
                f"{self.script}/{self.mood}/{self.source})")

    def note(self):
        return (f"fonts: '{self.display}' for headings, '{self.body}' for "
                f"body, '{self.mono}' for code ({self.script}/{self.mood}, "
                f"{self.source})")


def _seed_pick(seq, seed, salt=""):
    """Deterministic pick from a non-empty sequence, stable per seed."""
    if not seq:
        return None
    h = hashlib.md5((str(seed or "") + salt).encode("utf-8", "replace")).digest()
    return seq[h[0] % len(seq)]


def pick_fonts(text, seed=None):
    """The context-aware pairing (or None when the library is empty).
    Ranked mood candidates + a hash of the user's own words -> fitting,
    varied, and STABLE for the same request."""
    if not enabled() or not library():
        return None
    script = detect_script(text)
    mood = detect_mood(text)
    pairs = [(d, b) for d, b in MOOD_PAIRS.get(mood, {}).get(script, [])
             if find(d) and find(b)]
    if not pairs:
        # graceful fallback: any available body font of the right script
        # (display = body - one solid family beats a broken pairing)
        pairs = [(f["name"], f["name"]) for slug, f in library().items()
                 if f.get("script") == script and f.get("category") == "body"]
    if not pairs:
        return None
    display, body = _seed_pick(pairs, seed or text, salt="pair")
    mono = _seed_pick([m for m in _MONOS if find(m)], seed or text,
                      salt="mono") or "monospace"
    return Choice(display, body, mono, mood, script, "auto")


# ------------------------------------------------------- model override
_META_RE = re.compile(
    r"<meta[^>]*name\s*=\s*[\"']nova-fonts[\"'][^>]*>", re.I)
_META_CONTENT_RE = re.compile(r"content\s*=\s*[\"']([^\"']*)[\"']", re.I)


def parse_font_meta(html):
    """The model's per-page font request:
      <meta name="nova-fonts" content="heading=Lalezar; body=Vazirmatn;
             mono=JetBrains Mono">
    or the short form: content="Lalezar, Vazirmatn" (heading, body).
    Returns {} when absent/invalid. Unknown names are ignored here -
    resolve_choice falls back to the engine's pick per slot."""
    m = _META_RE.search(html or "")
    if not m:
        return {}
    cm = _META_CONTENT_RE.search(m.group(0))
    if not cm:
        return {}
    raw = cm.group(1)
    out = {}
    if "=" in raw:
        for part in raw.split(";"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            k = k.strip().lower()
            if k in ("heading", "head", "display", "title", "h"):
                out["display"] = v.strip()
            elif k in ("body", "text", "b"):
                out["body"] = v.strip()
            elif k in ("mono", "code", "m"):
                out["mono"] = v.strip()
    else:
        names = [p.strip() for p in raw.split(",") if p.strip()]
        if names:
            out["display"] = names[0]
        if len(names) > 1:
            out["body"] = names[1]
    return out


def resolve_choice(meta, auto):
    """Model's meta names win per slot; anything missing/unknown falls
    back to the engine's automatic choice. source='model' when the model
    drove at least one slot."""
    if not meta:
        return auto
    if auto is None:
        auto = Choice("Inter", "Inter", "monospace", "minimal-clean",
                      detect_script(" ".join(str(v) for v in meta.values())),
                      "auto")
    d = find(meta.get("display")) if meta.get("display") else None
    b = find(meta.get("body")) if meta.get("body") else None
    m = find(meta.get("mono")) if meta.get("mono") else None
    if not (d or b or m):
        return auto
    return Choice(d[1]["name"] if d else auto.display,
                  b[1]["name"] if b else auto.body,
                  m[1]["name"] if m else auto.mono,
                  auto.mood, auto.script, "model")


# --------------------------------------------------------------- css
# standard Google-Fonts unicode-ranges (arabic / latin / latin-ext)
_UNICODE_RANGES = {
    "arabic": ("U+0600-06FF, U+0750-077F, U+0870-088E, U+08A0-08FF, "
               "U+FB50-FDFF, U+FE70-FEFF"),
    "latin": ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, "
              "U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, "
              "U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, "
              "U+FFFD"),
    "latin-ext": ("U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, "
                  "U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, "
                  "U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, "
                  "U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF"),
}

_FALLBACK_STACK = {
    "fa": ("'Vazirmatn','Segoe UI',Tahoma,system-ui,sans-serif"),
    "en": ("'Inter','Segoe UI',system-ui,-apple-system,sans-serif"),
}


def _css_escape_family(name):
    return str(name).replace("\\", "").replace("'", "").replace('"', "")


def _font_face_block(family, entry, prefix):
    """All @font-face rules for one family. `prefix` points from the css
    file to the fonts/ dir ('' for a root-level css, '../' for css/)."""
    out = []
    for w in sorted(entry.get("weights", {}), key=lambda x: int(x or 0)):
        for subset, rel in sorted(entry["weights"][w].items()):
            url = (prefix + "fonts/" + rel).replace("\\", "/")
            ur = _UNICODE_RANGES.get(subset)
            out.append(
                "@font-face{font-family:'%s';font-style:normal;"
                "font-weight:%s;font-display:swap;src:url('%s') "
                "format('woff2');%s}" % (
                    _css_escape_family(family), w, url,
                    ("unicode-range:%s;" % ur) if ur else ""))
    return "\n".join(out)


def fonts_css(choice, prefix="", extra_families=(), only_families=None):
    """The full stylesheet: a stamp comment (the project's pairing, read
    back by install_pass so a project keeps its personality across turns)
    + @font-face for every needed family + tokens + zero-specificity
    defaults. The :where() rules (specificity 0) can NEVER override the
    model's own font-family declarations - Nova suggests, the model
    decides. only_families (when given) is the exact declaration list -
    install_pass uses it so the sheet never references a binary that the
    copy cap could not fit (a declared-but-absent file is a 404)."""
    if choice is None:
        return ""
    lib = library()

    def entry_of(name):
        got = find(name)
        return (got[0], got[1]) if got else None

    if only_families is not None:
        families = []
        for name in only_families:
            e = entry_of(name)
            if e and all(e[0] != s for s, _e in families):
                families.append(e)
    else:
        families = []
        for name in [choice.display, choice.body, choice.mono,
                     *(extra_families or ())]:
            e = entry_of(name)
            if e and all(e[0] != s for s, _e in families):
                families.append(e)
        # the Persian fallback body font keeps the floor coherent
        if choice.script == "fa" and choice.body != FA_FALLBACK_BODY:
            fb = entry_of(FA_FALLBACK_BODY)
            if fb and all(fb[0] != s for s, _e in families):
                families.append(fb)

    blocks = ["/* nova-fonts.css - Nova local font library (auto-added, "
              "offline, SIL OFL). Override anything in your own CSS. */",
              "/* nova-fonts stamp: display=%s; body=%s; mono=%s; "
              "mood=%s; script=%s */" % (choice.display, choice.body,
                                         choice.mono, choice.mood,
                                         choice.script)]
    for _slug, e in families:
        blocks.append(_font_face_block(e["name"], e, prefix))

    stack = _FALLBACK_STACK.get(choice.script, _FALLBACK_STACK["en"])
    d = _css_escape_family(choice.display)
    b = _css_escape_family(choice.body)
    m = _css_escape_family(choice.mono)
    blocks.append(
        ":root{--font-display:'%s',%s;--font-body:'%s',%s;"
        "--font-mono:'%s',ui-monospace,SFMono-Regular,Consolas,monospace;"
        "--font:var(--font-body)}" % (d, stack, b, stack, m))
    # zero-specificity defaults: the model's own CSS always wins
    blocks.append(
        ":where(body){font-family:var(--font-body)}\n"
        ":where(h1,h2,h3,h4,h5,h6,legend,summary,th)"
        "{font-family:var(--font-display)}\n"
        ":where(code,kbd,pre,samp){font-family:var(--font-mono)}")
    return "\n".join(blocks) + "\n"


# --------------------------------------------------------------- install
_LOCAL_URL_RE = re.compile(r"^(https?:)?//|^data:", re.I)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_REL_STYLE_RE = re.compile(r"rel\s*=\s*[\"']?stylesheet", re.I)
_HREF_RE = re.compile(r"href\s*=\s*[\"']([^\"']+)[\"']", re.I)
_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.I)
_HTML_TAG_RE = re.compile(r"<html\b[^>]*>", re.I)
_DIR_ATTR_RE = re.compile(r"\bdir\s*=", re.I)
_REMOTE_FONT_RE = re.compile(
    r"fonts\.googleapis\.com|fonts\.gstatic\.com|@font-face|typekit\.net",
    re.I)
_TAG_TEXT_RE = re.compile(r"<[^>]+>")
# v7.3 audit fix: style/script BODIES are not visible text - a Persian
# page whose latin chars live inside its own <style>/<script> must still
# be detected as Persian (strip the blocks BEFORE stripping the tags)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
# a full page (doctype or <html>) - fragments are left alone, exactly
# like the design floor's _is_full_page rule
_FULLPAGE_RE = re.compile(r"<!doctype\s*html|<html[\s>]", re.I)


def _atomic_write(path: Path, data):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               suffix=".tmp")
    try:
        if isinstance(data, bytes):
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        else:
            # newline="": the text keeps its OWN line endings (a CRLF page
            # is never line-normalized just because a link was injected)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _stylesheet_hrefs(content):
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
        out.append(re.split(r"[?#]", href, 1)[0] or href)
    return out


def _page_font_ready(content, ws: Path, page: Path):
    """True when the page already handles fonts itself (remote font CDN
    link, or @font-face in its inline <style> or a linked local sheet) -
    Nova must not fight the model's own typography."""
    hay = content or ""
    if _REMOTE_FONT_RE.search(hay):
        return True
    ws_root = ws.resolve()
    for href in _stylesheet_hrefs(hay):
        try:
            target = ((page.parent / href) if not href.startswith("/")
                      else (ws_root / href.lstrip("/"))).resolve()
            target.relative_to(ws_root)
        except (ValueError, OSError):
            continue
        try:
            if _REMOTE_FONT_RE.search(
                    target.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def _inject_link(content, href):
    """Add <link rel="stylesheet"> AFTER the last stylesheet link (so the
    font tokens land after the floor/model sheets), else before </head>.
    Idempotent: never adds a second link to the same href - the existing
    href value must match EXACTLY (path-wise); 'css/nova-fonts.css' is a
    DIFFERENT file and must not suppress the root sheet."""
    tag = f'<link rel="stylesheet" href="{href}">\n'
    for m in _LINK_RE.finditer(content or ""):
        hm = _HREF_RE.search(m.group(0))
        if not hm:
            continue
        existing = hm.group(1).strip().split("#")[0].split("?")[0]
        if existing == href:
            return content, False
    last = None
    for m in _LINK_RE.finditer(content or ""):
        if _REL_STYLE_RE.search(m.group(0)) and _HREF_RE.search(m.group(0)):
            last = m
    if last is not None:
        pos = last.end()
        return content[:pos] + "\n" + tag.strip() + content[pos:], True
    m = _HEAD_CLOSE_RE.search(content or "")
    if m:
        return content[:m.start()] + tag + content[m.start():], True
    return content + tag, True


def _ensure_rtl(content):
    """A Persian page that forgot dir="rtl" is half-broken in every
    browser - add it deterministically (never touch pages that set it).
    Detection reads the VISIBLE text only: <style>/<script> bodies are
    stripped first, so a page whose latin chars live in its own CSS/JS
    is still detected as Persian."""
    try:
        m = _HTML_TAG_RE.search(content or "")
        if not m or _DIR_ATTR_RE.search(m.group(0)):
            return content, False
        visible = _TAG_TEXT_RE.sub(
            " ", _SCRIPT_STYLE_RE.sub(" ", content))
        fa = len(_FA_CHAR.findall(visible))
        en = len(_LATIN_CHAR.findall(visible))
        if fa < 20 or fa <= en:
            return content, False
        tag = m.group(0)
        core = tag[:-1]                      # drop the closing '>'
        if core.rstrip().endswith("/"):      # self-closing '<html ... />'
            core = core.rstrip()[:-1].rstrip()
        new_tag = core.rstrip() + ' dir="rtl">'
        return content[:m.start()] + new_tag + content[m.end():], True
    except Exception:
        return content, False


def _page_depth(page_rel):
    parts = [p for p in Path(page_rel).parts[:-1]]
    return len(parts)


def _link_href(page_rel):
    depth = _page_depth(page_rel)
    return ("../" * depth) + CSS_NAME


_STAMP_RE = re.compile(
    r"/\*\s*nova-fonts stamp:\s*([^*]*)\*/")
_CSS_FAMILY_RE = re.compile(
    r"@font-face\{[^}]*?font-family\s*:\s*['\"]([^'\"]+)['\"]", re.I)


def _existing_css_families(ws):
    """Families the project's nova-fonts.css already declares - a
    follow-up turn must never DROP them (the sheet is regenerated from
    the union of old + new)."""
    try:
        text = (Path(ws) / CSS_NAME).read_text(encoding="utf-8",
                                               errors="replace")
    except OSError:
        return []
    return _CSS_FAMILY_RE.findall(text or "")


def _read_project_choice(ws):
    """A project keeps its personality: when nova-fonts.css already
    carries a stamp from an earlier batch, THAT choice wins for the
    whole project (a follow-up turn like 'add a contact section' must
    not re-skin the site). Meta overrides still add families.
    Returns a Choice or None."""
    try:
        text = (Path(ws) / CSS_NAME).read_text(encoding="utf-8",
                                               errors="replace")
    except OSError:
        return None
    m = _STAMP_RE.search(text)
    if not m:
        return None
    kv = {}
    for part in m.group(1).split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        kv[k.strip().lower()] = v.strip()
    if not all(kv.get(k) for k in ("display", "body")):
        return None
    if not (find(kv["display"]) and find(kv["body"])):
        return None                      # library changed - re-pick
    mono = kv.get("mono") if find(kv.get("mono")) else "JetBrains Mono"
    return Choice(kv["display"], kv["body"], mono,
                  kv.get("mood") or "minimal-clean",
                  kv.get("script") or detect_script(kv["body"]),
                  "project")


def install_pass(ws, applied_names, request_text=None):
    """The deterministic font pass (mirrors nova_images.fill_html_images):
    `ws` = workspace Path, `applied_names` = [relpath] just written,
    `request_text` = the user's own words (drives language + mood).
    Returns (extras, notes):
        extras = [(relpath, bytes_or_str)] - woff2 binaries (always new)
                 + nova-fonts.css (text; the hook backs up if it exists)
        notes  = [str] human-readable actions.
    Fail-soft per page; the whole call never raises."""
    extras, notes = [], []
    try:
        if not enabled() or not library():
            return extras, notes
        ws = Path(ws)
        ws_root = ws.resolve()
        pages = [n for n in (applied_names or [])
                 if str(n).lower().endswith((".html", ".htm"))][:MAX_PAGES_PER_PASS]
        if not pages:
            return extras, notes

        # a project keeps its personality: an already-stamped sheet wins
        # over re-picking per turn ('add a section' must not re-skin it)
        auto = _read_project_choice(ws)
        project_locked = auto is not None
        if auto is None:
            auto = pick_fonts(request_text, seed=request_text)
        auto = auto or pick_fonts("", seed=str(ws.name))

        batch_choice = None
        plan = []                  # (rel, raw, choice, Path, font_ready)
        for name in pages:
            try:
                # containment: install_pass is public API - pages are
                # always resolved INSIDE the workspace (the hook already
                # safe_joins the extras; this guards the page rewrites)
                p = Path(name) if not Path(name).is_absolute() \
                    else (ws_root / name)
                p = (ws / p).resolve() if not p.is_absolute() \
                    else p.resolve()
                try:
                    rel = str(p.relative_to(ws_root)).replace("\\", "/")
                except ValueError:
                    notes.append(f"{name}: fonts skipped "
                                 "(outside the workspace)")
                    continue
                if not p.is_file():
                    continue
                if p.stat().st_size > 3_000_000:
                    notes.append(f"{rel}: fonts skipped (page > 3 MB)")
                    continue
                raw = p.read_bytes()
                try:
                    raw = raw.decode("utf-8")
                except UnicodeDecodeError:
                    # a page Nova cannot decode is never rewritten -
                    # a re-encode would corrupt it with U+FFFD (the
                    # same rule nova_images has had since v7.2)
                    notes.append(f"{rel}: fonts skipped (not UTF-8)")
                    continue
                if not _FULLPAGE_RE.search(raw):
                    # fragments are left alone (the design-floor rule):
                    # no link injection at position 0, no dir=rtl
                    notes.append(f"{rel}: fonts skipped (html fragment)")
                    continue
                meta = parse_font_meta(raw)
                page_auto = auto
                if page_auto is None:
                    page_auto = pick_fonts(raw, seed=rel)
                if page_auto is None:
                    continue
                choice = resolve_choice(meta, page_auto)
                if batch_choice is None:
                    batch_choice = choice
                plan.append((rel, raw, choice, p, _page_font_ready(raw, ws, p)))
            except Exception as e:
                notes.append(f"{name}: fonts skipped ({type(e).__name__})")
        if not plan or batch_choice is None:
            return extras, notes
        # with a project stamp, meta choices only ADD families - the
        # tokens never change mid-project (no re-skin on follow-ups)
        if project_locked:
            batch_choice = auto

        # ---- 1) the family union, in PRIORITY order: the project's
        # choice slots first (they must always fit), then the fa
        # fallback, then the families the MODEL requested this turn
        # (v7.4 audit fix: they used to land last and be dropped
        # cap-first under MAX_FONT_FILES pressure), then the families
        # an earlier turn already declared (never dropped), then the
        # other pages' auto choices -------------------------------
        families = []                # ordered, deduped font names

        def _add(nm):
            if nm and nm not in families and find(nm):
                families.append(nm)

        for slot in ("display", "body", "mono"):
            _add(getattr(batch_choice, slot))
        if batch_choice.script == "fa" and \
                batch_choice.body != FA_FALLBACK_BODY:
            _add(FA_FALLBACK_BODY)
        for _name, _raw, choice, _p, _ready in plan:
            if choice.source == "model":
                for slot in ("display", "body", "mono"):
                    _add(getattr(choice, slot))
        if project_locked:
            for nm in _existing_css_families(ws):
                _add(nm)
        for _name, _raw, choice, _p, _ready in plan:
            if choice.source != "model":
                for slot in ("display", "body", "mono"):
                    _add(getattr(choice, slot))

        # ---- 2) binaries - FAMILY-COMPLETE: a family is installed only
        # when ALL its files fit under the cap, and only families that
        # fit are declared in the css (a declared-but-absent url is a
        # guaranteed 404). Immutable library files: an existing same-size
        # file is skipped, so re-applies stay idempotent. v7.4 audit
        # fix: an existing DIFFERENT-size file at a library path is the
        # user's own - it is never overwritten (that made /undo delete
        # a file Nova never created). ------------------------------
        _declared = set(_existing_css_families(ws))
        needs_css = any(not ready for *_x, ready in plan) or any(
            c.source == "model" and not all(
                getattr(c, s) in _declared
                for s in ("display", "body", "mono"))
            for _n, _r, c, _p, _rd in plan)
        needs_fonts = needs_css or any(c.source == "model"
                                       for _n, _r, c, _p, _rd in plan)
        included = []                # families that fully fit
        wanted = []                  # (dest_rel, src Path)
        if needs_fonts:
            for fname in families:
                got = find(fname)
                if not got:
                    continue
                entry = got[1]
                files = []
                overflow = False
                for w in entry.get("weights", {}).values():
                    for sub, rel in w.items():
                        if len(wanted) + len(files) >= MAX_FONT_FILES:
                            overflow = True
                            break
                        src = FONTS_DIR / rel
                        if not src.is_file():
                            continue
                        if src.stat().st_size > MAX_FONT_FILE_BYTES:
                            continue
                        files.append(("fonts/" + rel.replace("\\", "/"),
                                      src))
                if overflow:
                    continue          # family does not fit - not declared
                for dest_rel, src in files:
                    if all(dest_rel != r for r, _s in wanted):
                        wanted.append((dest_rel, src))
                included.append(fname)
            copied = 0
            owned = 0
            for dest_rel, src in wanted:
                dest = ws / dest_rel
                if dest.is_file():
                    if dest.stat().st_size == src.stat().st_size:
                        continue
                    owned += 1          # user's own file - never touched
                    continue
                extras.append((dest_rel, src.read_bytes()))
                copied += 1
            if copied:
                notes.append(f"font library: {copied} font file(s) "
                             f"installed into fonts/")
            if owned:
                notes.append(f"font library: {owned} file(s) at library "
                             "paths kept as-is (your own files)")

        # ---- 3) per page: css (once) + link + rtl -----------------------
        # @font-face urls are relative to the CSS FILE (root-level
        # nova-fonts.css -> prefix '' always), while the <link> href is
        # relative to each PAGE (../ for nested pages).
        # v7.4 audit fix: the sheet regeneration is decoupled from the
        # link injection - a meta override on an already-stamped page
        # (whose nova-fonts.css supplies the @font-face that made it
        # 'ready') used to copy the binaries but NEVER regenerate the
        # sheet, so the requested family existed nowhere.
        css_done = not needs_css
        for name, raw, choice, p, ready in plan:
            try:
                text = raw
                if not css_done:
                    css = fonts_css(batch_choice, prefix="",
                                    only_families=included)
                    if css:
                        target = ws / CSS_NAME
                        same = False
                        if target.is_file():
                            try:
                                same = (target.read_text(
                                    encoding="utf-8",
                                    errors="replace") == css)
                            except OSError:
                                same = False
                        if not same:
                            extras.append((CSS_NAME, css))
                    css_done = True
                if not ready:
                    text, added = _inject_link(text, _link_href(name))
                    if added:
                        notes.append(f"{name}: {CSS_NAME} linked "
                                     f"({choice.display} + {choice.body})")
                text, rtl = _ensure_rtl(text)
                if rtl:
                    notes.append(f'{name}: dir="rtl" added (Persian page)')
                if text != raw:
                    _atomic_write(p, text)
            except Exception as e:
                notes.append(f"{name}: fonts skipped ({type(e).__name__})")
        if wanted:
            notes.append(batch_choice.note())
    except Exception as e:
        notes.append(f"font pass skipped ({type(e).__name__})")
    return extras, notes
