#!/usr/bin/env python3
# =====================================================================
#  Nova Code - INTERNET IMAGES (v7.2, quality pass v7.4, semantic v7.10)
#  "The site the agent builds must show REAL photos - found precisely,
#   downloaded safely - even when the model is small."
#
#  Four layers, all fail-soft and deadline-bounded:
#
#    1. search_images()    - multi-provider photo search (DDG images ->
#                            BING images -> Openverse -> Wikimedia
#                            Commons), merged, deduped, QUALITY-GATED and
#                            ranked. No API keys. v7.4 gates keep the junk
#                            the user actually saw OUT of the results:
#                            stock/watermarked hosts, clip-art & logo
#                            hosts, meme/gif URLs, text-y titles, extreme
#                            aspect ratios and tiny thumbnails.
#    2. download_image()   - SSRF-safe binary fetch (reuses nova_search's
#                            pinned stack: safe_url on every redirect +
#                            actual-peer-IP verification), magic-byte
#                            sniffing, 8 MB cap, idempotent filenames.
#    3. normalize_for_page - v7.4: every photo headed for a built page
#                            is made CONSISTENT with its siblings:
#                            EXIF rotation fixed (no more sideways
#                            photos), center-cropped to the ratio the
#                            model declared on the tag (3:2 default),
#                            capped at 1600px, re-encoded JPEG q85
#                            (uniform small files, metadata stripped).
#                            Without Pillow this layer is a no-op.
#    4. fill_html_images() - the DETERMINISTIC post-apply filler: every
#                            <img> in the applied pages gets a real,
#                            downloaded photo; anything the internet
#                            cannot provide falls back to a generated
#                            local art placeholder. A built site never
#                            shows a broken image - online or offline.
#
#  The model's protocol is one attribute:  <img src="IMG:rose garden">
#  Nova replaces it with the real downloaded path. Weak models that
#  ignore the protocol are still covered: placeholder-image srcs and
#  broken/missing local paths are auto-filled from the alt text, and
#  dead remote URLs are replaced by searched photos.
#
#  v8.1 AI LAYERS (wired by nova.py at import time - this module stays
#  decoupled from the provider stack, the hooks are plain callables):
#    AI_QUERY_HOOK   (query:str) -> [str] extra ENGLISH photo-search
#                    phrases the connected CLOUD brain suggests - they
#                    join the search ladder right after the primary rung.
#    AI_VERIFY_HOOK  (query:str, jpeg:bytes) -> (ok:bool, verdict:str)
#                    the AI's FINAL say on one downloaded, normalized
#                    photo. A cloud brain is the MANDATORY gate; a local
#                    vision-capable model gets the same job when no
#                    cloud brain exists (best effort).
#  Kill switches: NOVA_NO_IMAGES=1 disables everything (raw output);
#  NOVA_NO_IMG_AI=1 keeps the plain search but turns both AI layers off.
#  Missing nova_search.py = no network layer -> only local placeholders.
#  A broken module degrades to None in nova.py - exactly like every
#  other nova_* module.
# =====================================================================
import base64 as _b64
import hashlib
import io
import json
import os
import re
import tempfile
import time
import unicodedata
import urllib.parse as _urlparse
from pathlib import Path

try:                                   # the SSRF-safe network layer
    import nova_search as _ns_mod
except Exception:
    _ns_mod = None

__all__ = ["enabled", "available", "search_images", "smart_search",
           "translate_query", "download_image",
           "pick_and_save", "save_result", "save_from_url",
           "fill_html_images", "placeholder_svg", "normalize_for_page",
           "IMG_PROTOCOL_NOTE", "ASSETS_DIR"]

MAX_SEARCH_RESULTS = 8
MAX_FILE_BYTES = 8_000_000        # never keep an asset above 8 MB
# v8.0.1: a REAL photo embedded as a data: URI is virtually never below
# this size at page scale; weak models embed 1-3 KB procedural pixel
# junk instead of using the IMG: protocol and the page then ships fake
# "photos" (the coffe8_after report). Anything smaller is refilled.
MIN_EMBEDDED_PHOTO_BYTES = 15_000
T_SEARCH = 6                      # seconds per search request
T_DOWNLOAD = 12                   # seconds per image download
DEFAULT_DEADLINE = 90             # seconds for a whole fill pass
MAX_REMOTE_TRIES_PER_PAGE = 4     # remote-URL download attempts per page
MAX_FILLS_PER_PAGE = 12           # img tags touched per page
CACHE_FILE = ".nova/images.json"
CACHE_MAX = 600

ASSETS_DIR = ("assets", "images")

IMG_PROTOCOL_NOTE = (
    'Images: for EVERY <img> write src="IMG:2-4 english words" - name the '
    "subject with its color, like IMG:red rose or IMG:sliced pizza or "
    'IMG:milad tower. NEVER write a bare color (IMG:red matches anything '
    'red), never one vague word, never invent image URLs. Also give every '
    "img a meaningful alt in the user's language plus width and height "
    "attributes - Nova finds a real, watermark-free photo, verifies it "
    "matches the subject and color, and center-crops it to exactly that "
    "ratio.")


def enabled():
    return os.environ.get("NOVA_NO_IMAGES") != "1"


# ------------------------------------------------------------- v8.1 AI layers
AI_QUERY_HOOK = None      # set by nova.py; plain callable, never imported
AI_VERIFY_HOOK = None
# v8.6 SELECTION GATE: nova.py installs the local-vision approval layer
# here - called ONCE per photo request BEFORE any search/download with
# the query; False = no internet photo at all (honest note, placeholders).
AI_GATE_HOOK = None
AI_MAX_QUERY_RUNGS = 3    # extra AI rungs per query (deduped, normalized)
VERIFY_LEFT_SEC = 6.0     # skip verification under this much budget left


def ai_layers_on():
    """The AI layers respect their own kill switch (NOVA_NO_IMG_AI=1)
    on top of the master NOVA_NO_IMAGES one."""
    return os.environ.get("NOVA_NO_IMG_AI") != "1"


_AI_RUNG_CACHE = {}       # original query -> [normalized AI rungs]


def _ai_extra_rungs(query):
    """Layer 1 (FIND): the cloud brain's English phrases for one query.
    [] without a hook / under the kill switch / on any hook error -
    the local dictionary ladder still searches exactly as before.
    Cached per query: one brain round-trip per UNIQUE subject."""
    if AI_QUERY_HOOK is None or not ai_layers_on():
        return []
    hit = _AI_RUNG_CACHE.get(query)
    if hit is not None:
        return hit
    try:
        out = AI_QUERY_HOOK(query) or []
    except Exception:
        out = []
    rungs = []
    for q in list(out)[:AI_MAX_QUERY_RUNGS * 2]:
        try:
            qn = _norm_query(str(q))
        except Exception:
            continue
        if qn and len(qn) >= 3 and qn != query and qn not in rungs:
            rungs.append(qn)
        if len(rungs) >= AI_MAX_QUERY_RUNGS:
            break
    if len(_AI_RUNG_CACHE) > 300:
        _AI_RUNG_CACHE.clear()
    _AI_RUNG_CACHE[query] = rungs
    return rungs


def _ai_verify_ok(query, raw, deadline=None):
    """Layer 2 (VERIFY): the AI's final say on one normalized photo.
    ALWAYS (ok, tail): a missing hook, an exhausted budget or a broken
    brain can never brick the fill (fail-soft law) - only a clear
    REJECT verdict from the AI returns False and sends the caller to
    the next candidate."""
    if AI_VERIFY_HOOK is None or not ai_layers_on() or not raw:
        return True, ""
    if deadline is not None and _left(deadline) <= VERIFY_LEFT_SEC:
        return True, "ai-skip-time"
    try:
        ok, why = AI_VERIFY_HOOK(query, raw)
    except Exception:
        return True, "ai-err"
    if ok:
        return True, str(why or "ai-approved")[:40]
    return False, str(why or "rejected")[:60]


def _ai_gate_ok(query):
    """v8.6 SELECTION GATE: may the AI photo pipeline search/download
    AT ALL for this request? (the local-vision approval layer). Always
    (ok, note): a missing hook or a broken gate can never brick the
    fill - only a clear False blocks, with an honest note."""
    if AI_GATE_HOOK is None or not ai_layers_on():
        return True, ""
    try:
        ok, note = AI_GATE_HOOK(str(query or ""))
    except Exception:
        return True, ""
    if ok:
        return True, str(note or "")[:80]
    return False, str(note or "selection refused")[:80]


def available():
    """True when image fetching can actually work (enabled + network layer)."""
    return enabled() and _ns_mod is not None


# --------------------------------------------------------------- time budget
def _left(deadline):
    return 1e9 if deadline is None else deadline - time.monotonic()


# --------------------------------------------------------------- tiny utils
def slug(text):
    """ASCII, filesystem-safe, URL-safe slug for an image name. Persian or
    any non-latin text folds to the stable 'img' base (the hash suffix
    keeps names unique)."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = t.encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return (t[:40] or "img")


def _norm_query(q):
    return " ".join(str(q or "").split()).strip().lower()


# ------------------------------------------------ v7.6 query intelligence
# The weak local models keep writing Persian / one-word / mangled image
# descriptions. On the providers that is a lottery: «رز» is the ARABIC
# word for rice (the user asked for a rose and got rice recipes), «قرمز»
# alone returns ANY red object, and a candidate titled "branch on red
# background" always passed the v7.4 quality gates (it IS a clean photo).
# v7.6 answered with three deterministic layers, all offline, zero model
# calls:
#    1. translate_query - Persian subjects -> English (offline dict),
#       fillers stripped, colors identified;
#    2. build_ladder    - the search ladder (English first for Persian,
#       v7.4 word-by-word tail relaxation preserved for English);
#    3. _relevance      - weighted token-overlap ranking of the merged
#       candidate pool (a "branch on red background" can no longer beat
#       real roses for "red rose"), plus an Arabic-recipe penalty;
# and after the download a PIL pixel check (_passes_color) verifies the
# required color («قرمز» -> red) actually exists in the photo.
#
# v7.10 SEMANTIC HARDENING (the user asked for it "خیلی خیلی قوی‌تر"):
#    4. SUBJECT ANCHORING in _relevance - a candidate that never
#       mentions the SUBJECT of the query in its title is penalized
#       hard, and one whose title carries it is boosted harder still
#       (title > url > absent). The branch-on-red-background class of
#       miss can no longer ride on the color word alone.
#    5. CROSS-RUNG POOL MERGE in smart_search - rungs no longer stop at
#       the FIRST one that returns anything; the pools of consecutive
#       rungs are merged (URL-deduped) and ranked together, and the
#       ladder keeps climbing until the pool holds enough SUBJECT-
#       MATCHING candidates. A weak first rung no longer hides a
#       perfect second rung.
#    6. A FOURTH PROVIDER - Bing images (no key, m="{json}" tiles)
#       widens the candidate pool for niche subjects; still strictly
#       fail-soft and deadline-bounded.
#    7. DICTIONARY EXPANSION - ~120 more Persian subjects (Iranian
#       landmarks, professions, foods, animals, objects) translate
#       offline, so more weak-model queries land on real anchors.
_ZWNJ = "\u200c"

_FA_STOP = frozenset("""
عکس عکسها تصویر تصاویر عکسهایی یک ی ای از با برای در روی زیر بین به تا و
که این آن آنها اون چند همه هر کامل عالی جدید جدیدترین قدیمی زیبا زیباترین
قشنگ بهترین خوب خیلی بزرگ کوچک متوسط رایگان دانلود دریافت والپر پس زمینه
کیفیت شفاف برداری لوگو آیکون نه بله چی چه کدام کجا چرا چطور چگونه می خوام
میخوام لطفا پیدا کن کن بذار بذارید بگیر بگیرید نشون بده بدهید حالا الان یه
چیزی مورد سایت وبسایت وب صفحه هدر فوتر بنر قهرمان کارت بخش جای داره بدون
کنید باشه باش اینکه چون وقتی قبل بعد بالا پایین وسط کنار سمت تم عکس پروفایل
""".split())

_EN_STOP = frozenset("""
a an the of with on in at for and or to from by is are be
photo picture image pic pics photos images wallpapers wallpaper
hd 4k free download file high full size best good nice beautiful
pretty new old big small background backdrop banner hero section
page website web site card panel box style modern elegant luxury
amazing awesome stunning wonderful lovely cute real top great super
ultra pro please find show give me want need some this that these
those it its here there
""".split())

# trailing frame-words a weak model appends ("... with dew drops",
# "... website hero") - they must never become the subject of a rung
_EN_TAIL_TRIM = frozenset({
    "background", "backdrop", "drops", "dew", "wall", "theme", "concept",
    "closeup", "close", "up", "view", "shot", "theme", "idea", "design",
    "hero", "banner", "section", "page", "card", "panel", "frame", "art",
})

_FA_EN_PHRASES = {
    # flowers (the classic request that started v7.6)
    "گل رز": "rose", "رز قرمز": "red rose", "گل رز قرمز": "red rose",
    "گل رز سفید": "white rose", "گل رز زرد": "yellow rose",
    "گل رز صورتی": "pink rose", "رز سفید": "white rose",
    "دسته گل": "flower bouquet", "دسته گل رز": "rose bouquet",
    "گل لاله": "tulip", "لاله قرمز": "red tulip",
    "گل آفتابگردان": "sunflower", "گل بنفشه": "violet flower",
    "گل ارکیده": "orchid flower", "گل نیلوفر": "lotus flower",
    "نیلوفر آبی": "water lily", "گل مریم": "jasmine flower",
    "گل محمدی": "damask rose", "گل شقایق": "poppy flower",
    "گل داوودی": "chrysanthemum flower", "گل زنبق": "iris flower",
    "گل ژربرا": "gerbera flower", "گل صدتومی": "chrysanthemum flower",
    # animals
    "بچه گربه": "kitten", "بچه سگ": "puppy", "خرس قطبی": "polar bear",
    "اسب سواری": "horse riding", "پرنده مهاجر": "migratory birds",
    # nature / places
    "غروب آفتاب": "sunset", "طلوع آفتاب": "sunrise",
    "آسمان شب": "night sky", "شب پرستاره": "starry night",
    "رنگین کمان": "rainbow", "برج میلاد": "milad tower",
    "برج آزادی": "azadi tower", "میدان آزادی": "azadi square",
    "کوه دماوند": "mount damavand", "تخت جمشید": "persepolis",
    "دیوار چین": "great wall of china", "باغ وحش": "zoo animals",
    "فانوس دریایی": "lighthouse",
    "جنگل بارانی": "rainforest", "دشت گل": "flower field",
    # food
    "تخم مرغ": "egg", "سیب زمینی": "potato",
    "سیب زمینی سرخ کرده": "french fries", "آب پرتقال": "orange juice",
    "چای سبز": "green tea", "قهوه تلخ": "black coffee",
    "بستنی قیفی": "ice cream cone", "کیک تولد": "birthday cake",
    "غذای دریایی": "seafood", "خوراک گیاهی": "vegetarian food",
    # tech / sport
    "لپ تاپ": "laptop", "هوش مصنوعی":
        "artificial intelligence", "توپ فوتبال": "soccer ball",
    "زمین فوتبال": "football field", "بازیکن فوتبال": "football player",
    "دوچرخه سواری": "cycling", "پارک آبی": "water park",
    # people
    "دختر بچه": "little girl", "پسر بچه": "little boy",
    "دانش آموز": "student", "برنامه نویس": "programmer",
    "آتش نشان": "firefighter",
    # v7.10: Iranian landmarks & places (weak models write these a lot)
    # note: the «و» inside a name is a STOPWORD and is stripped before
    # phrase matching - so the stopword-folded key goes here too
    "سی و سه پل": "si o se pol bridge", "سی سه پل": "si o se pol bridge",
    "پل خواجو": "khaju bridge",
    "کاخ گلستان": "golestan palace", "باغ ارم": "eram garden",
    "میدان نقش جهان": "naqsh e jahan square", "مسجد شیخ لطف الله":
        "sheikh lotfollah mosque",
    "حافظیه شیراز": "tomb of hafez", "سعدیه شیراز": "tomb of saadi",
    "برج قابوس": "gonbad e qabus tower", "گنبد سلطانیه":
        "soltaniyeh dome",
    "باغ فین کاشان": "fin garden kashan",
    "کویر مصر": "dasht e kavir desert", "تالاب انزلی": "anzali wetland",
    "غار علیصدر": "alisadr cave", "دریاچه ارومیه": "lake urmia",
    "کوه سبلان": "mount sabalan", "کوه الوند": "mount alvand",
    "جزیره کیش": "kish island", "جزیره قشم": "qeshm island",
    "بازار تبریز": "tabriz bazaar", "میدان امام": "imam square isfahan",
    # v7.10: common compound subjects
    "توپ والیبال": "volleyball ball", "توپ بسکتبال": "basketball ball",
    "دوچرخه کوهستان": "mountain bike", "ماشین مسابقه": "race car",
    "هواپیمای جنگی": "fighter jet", "کشتی بادبانی": "sailboat",
    "قطار سریع السیر": "high speed train",
    "شفق قطبی": "aurora borealis", "صحرای کویر": "desert dunes",
    "آبگرم طبیعی": "hot spring", "چشمه آب گرم": "hot spring",
    "بادگیر یزد": "windcatcher yazd", "خانه تاریخی": "historic house",
    "حمام تاریخی": "historic bathhouse",
    "آب انبار": "water reservoir", "آسیاب آبی": "watermill",
    "صنایع دستی": "handicrafts", "فرش دستباف": "handmade persian carpet",
    "کاشی کاری": "tilework", "مینیاتور ایرانی": "persian miniature painting",
    "نقاشی رنگ روغن": "oil painting",
    "ساعت مچی": "wristwatch",
    "عینک آفتابی": "sunglasses", "کیف پول": "wallet",
    "کارت اعتباری": "credit card", "سکه طلا": "gold coin",
    "دسته کلید": "key bunch",
    "چراغ قوه": "flashlight",
    "سیم برق": "electric wire", "پریز برق": "power outlet",
    "کلید برق": "light switch", "جعبه ابزار": "toolbox",
    "پیچ گوشتی": "screwdriver",
    "متر نواری": "tape measure", "نردبان فلزی": "metal ladder",
}

_FA_EN_WORDS = {
    # colors (modifiers - also color-gate the downloaded pixels)
    "قرمز": "red", "سرخ": "red", "آبی": "blue", "سبز": "green",
    "زرد": "yellow", "سیاه": "black", "مشکی": "black", "سفید": "white",
    "صورتی": "pink", "بنفش": "purple", "نارنجی": "orange",
    "نقره": "silver", "نقره ای": "silver", "خاکستری": "gray",
    "قهوه ای": "brown", "طلایی": "golden", "طلائی": "golden",
    # nature
    "گل": "flower", "درخت": "tree", "شاخه": "branch", "برگ": "leaf",
    "جنگل": "forest", "کوه": "mountain", "کوهستان": "mountains",
    "تپه": "hill", "دریا": "sea", "اقیانوس": "ocean", "دریاچه": "lake",
    "رودخانه": "river", "آبشار": "waterfall", "ساحل": "beach",
    "صحرا": "desert", "کویر": "desert", "آسمان": "sky", "ابر": "cloud",
    "باران": "rain", "برف": "snow", "طوفان": "storm", "مه": "fog",
    "غروب": "sunset", "طلوع": "sunrise", "شب": "night", "خورشید": "sun",
    "ماه": "moon", "ستاره": "star", "کهکشان": "galaxy", "سیاره": "planet",
    "آتشفشان": "volcano", "طبیعت": "nature", "باغ": "garden",
    "چمن": "grass", "گیاه": "plant", "آتش": "fire", "دود": "smoke",
    "آب": "water", "سنگ": "rock", "شن": "sand", "غار": "cave",
    "جزیره": "island", "رعد": "lightning", "آذرخش": "lightning",
    "بهار": "spring", "تابستان": "summer", "پاییز": "autumn",
    "زمستان": "winter", "برج": "tower", "قلعه": "castle", "کاخ": "palace",
    "مسجد": "mosque", "کلیسا": "church", "معبد": "temple", "هرم": "pyramid",
    "آسمانخراش": "skyscraper",
    # animals
    "حیوان": "animal", "گربه": "cat", "سگ": "dog", "اسب": "horse",
    "الاغ": "donkey", "گاو": "cow", "گوسفند": "sheep", "بز": "goat",
    "شتر": "camel", "فیل": "elephant", "زرافه": "giraffe", "شیر": "lion",
    "ببر": "tiger", "پلنگ": "leopard", "یوزپلنگ": "cheetah",
    "خرس": "bear", "گرگ": "wolf", "روباه": "fox", "گوزن": "deer",
    "خرگوش": "rabbit", "موش": "mouse", "سنجاب": "squirrel",
    "میمون": "monkey", "گوریل": "gorilla", "نهنگ": "whale",
    "دلفین": "dolphin", "کوسه": "shark", "ماهی": "fish",
    "تمساح": "crocodile", "مار": "snake", "قورباغه": "frog",
    "لاک پشت": "turtle", "زنبور": "bee", "پروانه": "butterfly",
    "مورچه": "ant", "عنکبوت": "spider", "پرنده": "bird", "عقاب": "eagle",
    "شاهین": "falcon", "جغد": "owl", "طوطی": "parrot", "گنجشک": "sparrow",
    "کلاغ": "crow", "فلامینگو": "flamingo", "قو": "swan",
    "مرغابی": "duck", "خروس": "rooster", "مرغ": "chicken",
    "پنگوئن": "penguin", "شترمرغ": "ostrich", "طاووس": "peacock",
    "کبوتر": "pigeon", "قناری": "canary",
    # «شیر» is lion AND milk - lion is the far more common photo subject
    # (v7.6 audit: the duplicated literal key silently kept 'milk' and
    # 'lion' was unreachable)
    # flowers / plants
    "رز": "rose", "لاله": "tulip", "آفتابگردان": "sunflower",
    "بنفشه": "violet", "ارکیده": "orchid", "نیلوفر": "lotus",
    "یاس": "jasmine", "شقایق": "poppy", "کاکتوس": "cactus",
    "شبنم": "dew", "سدر": "cedar", "نارون": "elm", "بید": "willow",
    "توسکا": "alder", "نارنج": "bitter orange", "انار": "pomegranate",
    "کوهنوردی": "mountain hiking", "شنا": "swimming",
    # food
    "غذا": "food", "صبحانه": "breakfast", "ناهار": "lunch", "شام": "dinner",
    "پیتزا": "pizza", "برگر": "burger", "ساندویچ": "sandwich",
    "ماکارونی": "pasta", "اسپاگتی": "spaghetti", "برنج": "rice",
    "خورش": "stew", "کباب": "kebab", "استیک": "steak", "سوپ": "soup",
    "سالاد": "salad", "کیک": "cake", "شیرینی": "pastry",
    "بیسکویت": "cookie", "شکلات": "chocolate", "بستنی": "ice cream",
    "دونات": "donut", "نان": "bread", "میوه": "fruit", "سیب": "apple",
    "پرتقال": "orange fruit", "نارنگی": "tangerine", "لیمو": "lemon",
    "موز": "banana", "انگور": "grapes", "هندوانه": "watermelon",
    "طالبی": "melon", "خربزه": "melon", "توت": "berry",
    "توت فرنگی": "strawberry", "گیلاس": "cherry", "آلبالو": "sour cherry",
    "هلو": "peach", "زردآلو": "apricot", "انجیر": "fig", "خرما": "date",
    "نارگیل": "coconut", "آووکادو": "avocado", "کیوی": "kiwi",
    "آناناس": "pineapple", "قهوه": "coffee", "چای": "tea",
    "آبمیوه": "juice", "نوشابه": "soda",
    # v8.0.1: cafe menu vocabulary - Iranians order these in Latin-loan
    # words daily («یک اسپرسو و کروسان لطفا»); the coffee81 live run
    # showed them missing: 'espresso cup' / 'butter croissant bakery'
    # had NO dict-known noun and the quality gates starved
    "اسپرسو": "espresso", "لاته": "latte", "کاپوچینو": "cappuccino",
    "موکا": "mocha", "اسپرسو دبل": "double espresso",
    "کروسان": "croissant", "نانوایی": "bakery",
    # (v8.7: "نانوا" belonged ONLY to the people/jobs section below as
    # "baker" - the cafe line above used to repeat the key with the
    # value "bakery" and Python kept the LAST one, silently turning
    # baker portraits into bakery scenes since v8.0.1)
    "فنجان": "cup", "لیوان": "glass", "دسر": "dessert",
    "چیزکیک": "cheesecake", "براونی": "brownie", "وافل": "waffle",
    "اسموتی": "smoothie", "لیموناد": "lemonade", "هات چاکلت": "hot chocolate",
    # objects / tech
    "موبایل": "phone", "تلفن": "phone", "گوشی": "phone",
    "لپتاپ": "laptop", "کامپیوتر": "computer", "رایانه": "computer",
    "مانیتور": "monitor", "کیبورد": "keyboard", "تبلت": "tablet",
    "دوربین": "camera", "عکاسی": "photography", "هدفون": "headphones",
    "هدست": "headphones", "اسپیکر": "speaker", "تلویزیون": "tv",
    "رادیو": "radio", "یخچال": "refrigerator", "ماشین": "car",
    "خودرو": "car", "اتومبیل": "car", "سواری": "car", "کامیون": "truck",
    "اتوبوس": "bus", "قطار": "train", "هواپیما": "airplane",
    "هلیکوپتر": "helicopter", "کشتی": "ship", "قایق": "boat",
    "موتورسیکلت": "motorcycle", "دوچرخه": "bicycle", "اسکوتر": "scooter",
    "تراکتور": "tractor", "ربات": "robot", "فضا": "space",
    # buildings / places
    "خانه": "house", "منزل": "house", "ویلا": "villa",
    "آپارتمان": "apartment", "ساختمان": "building", "کارخانه": "factory",
    "مغازه": "shop", "فروشگاه": "store", "بازار": "market",
    "سوپرمارکت": "supermarket", "رستوران": "restaurant", "کافه": "cafe",
    "هتل": "hotel", "بیمارستان": "hospital", "داروخانه": "pharmacy",
    "مدرسه": "school", "دانشگاه": "university", "کتابخانه": "library",
    "موزه": "museum", "سینما": "cinema", "تئاتر": "theater",
    "استادیوم": "stadium", "ورزشگاه": "stadium", "پل": "bridge",
    "تونل": "tunnel", "جاده": "road", "بزرگراه": "highway",
    "اتوبان": "highway", "خیابان": "street", "کوچه": "alley",
    "میدان": "square", "فرودگاه": "airport", "ایستگاه": "station",
    "بندر": "port", "دیوار": "wall", "اتاق": "room",
    "آشپزخانه": "kitchen", "حمام": "bathroom", "پله": "stairs",
    "درب": "door", "پنجره": "window", "شهر": "city",
    "روستا": "village", "کشور": "country", "جهان": "world",
    # people
    "مرد": "man", "زن": "woman", "دختر": "girl", "پسر": "boy",
    "بچه": "child", "کودک": "child", "نوزاد": "baby",
    "خانواده": "family", "پدر": "father", "مادر": "mother",
    "برادر": "brother", "خواهر": "sister", "دوست": "friend",
    "عروس": "bride", "داماد": "groom", "زوج": "couple", "مردم": "people",
    "جمعیت": "crowd", "پزشک": "doctor", "دکتر": "doctor",
    "پرستار": "nurse", "معلم": "teacher", "دانشجو": "student",
    "مهندس": "engineer", "کارگر": "worker", "کشاورز": "farmer",
    "آشپز": "chef", "نقاش": "painter", "هنرمند": "artist",
    "خواننده": "singer", "ورزشکار": "athlete", "پلیس": "police",
    "سرباز": "soldier", "خلبان": "pilot", "فوتبالیست": "footballer",
    # sport / events
    "فوتبال": "soccer", "توپ": "ball", "بسکتبال": "basketball",
    "والیبال": "volleyball", "تنیس": "tennis", "استخر": "swimming pool",
    "اسکی": "skiing", "بوکس": "boxing", "یوگا": "yoga",
    "بدنسازی": "gym", "گلف": "golf", "عروسی": "wedding",
    "تولد": "birthday", "جشن": "party", "مهمانی": "party",
    "کنسرت": "concert", "مسابقه": "competition",
    # abstract / objects
    "عشق": "love", "قلب": "heart", "تاج": "crown", "الماس": "diamond",
    "جواهر": "jewel", "طلا": "gold", "پول": "money", "سکه": "coin",
    "کیف": "bag", "چمدان": "suitcase", "کتاب": "book",
    "دفتر": "notebook", "مداد": "pencil", "خودکار": "pen", "قلم": "pen",
    "رنگ": "color", "نقاشی": "painting", "تابلو": "painting",
    "آینه": "mirror", "شمع": "candle", "جعبه": "box", "کلید": "key",
    "قفل": "lock", "ساعت": "clock", "عینک": "glasses",
    "چتر": "umbrella", "بادکنک": "balloon", "هدیه": "gift",
    "کادو": "gift", "گلدان": "vase", "فرش": "carpet", "مبل": "sofa",
    "صندلی": "chair", "میز": "table", "تخت": "bed", "لامپ": "lamp",
    "چراغ": "lamp", "فانوس": "lantern", "بالش": "pillow",
    "پرده": "curtain", "نردبان": "ladder", "سبد": "basket",
    # v8.7: "فنجان"/"لیوان" already ride in the cafe section above -
    # the household duplicates had identical values today, but a
    # future one-sided edit would silently lose the other (the same
    # latent pattern as the fixed «نانوا»).
    "بطری": "bottle",
    "قاشق": "spoon", "چنگال": "fork", "چاقو": "knife",
    "بشقاب": "plate", "قابلمه": "pot", "هنر": "art", "موسیقی": "music",
    "رقص": "dance", "تاریخ": "history", "علم": "science",
    "فناوری": "technology", "آزادی": "freedom", "صلح": "peace",
    "افتاب": "sun", "ابرها": "clouds", "گلها": "flowers",
    "درختان": "trees", "شهرها": "cities",
    # v7.10: Iranian (and a few world) city names - weak models append
    # the city to a landmark («برج میلاد تهران») and the whole query
    # must translate for the ladder rungs to stay English
    "تهران": "tehran", "اصفهان": "isfahan",
    "شیراز": "shiraz", "تبریز": "tabriz", "مشهد": "mashhad",
    "کاشان": "kashan", "یزد": "yazd", "قم": "qom", "کرج": "karaj",
    "اهواز": "ahvaz", "رشت": "rasht", "بندرعباس": "bandar abbas",
    "کرمان": "kerman", "همدان": "hamadan", "ارومیه": "urmia",
    "زاهدان": "zahedan", "سنندج": "sanandaj",
    "سوادکوه": "savadkuh", "لواسان": "lavasan", "آبادان": "abadan",
    "پاریس": "paris", "لندن": "london", "رم": "rome", "ونیز": "venice",
    "توکیو": "tokyo", "استانبول": "istanbul", "دبی": "dubai",
    # v7.10 single-word subjects (live in the WORDS table - the phrases
    # table is pinned multi-word by tests)
    "چغازنبیل": "chogha zanbil", "تراموا": "tram",
    "مترو": "subway train", "پهپاد": "drone",
    "تلسکوپ": "telescope", "ریزش شهابی": "meteor shower",
    "کاروانسرا": "caravanserai", "خاتم": "khatam marquetry",
    "خطاطی": "calligraphy", "مجسمه": "sculpture",
    "اسکناس": "banknotes", "باتری": "battery",
    "آچار": "wrench", "چکش": "hammer", "اره": "saw",
    # ---- v7.10 dictionary expansion (~120 more subjects) ----
    # Iranian food & kitchen
    "قرمه سبزی": "ghormeh sabzi stew", "قیمه": "gheymeh stew",
    "زرشک پلو": "zereshk polo rice", "چلو کباب": "chelo kebab",
    "کباب کوبیده": "koobideh kebab", "جوجه کباب": "joojeh kebab",
    "آش رشته": "reshteh soup", "کوکو سبزی": "kuku sabzi",
    "کوکو سیب زمینی": "potato kuku", "کتلت": "cutlet",
    "شامی": "shami cutlet", "میرزا قاسمی": "mirza ghasemi",
    "کشک بادمجان": "kashke bademjan", "عدسی": "lentil stew",
    "حلیم": "halim", "کله پاچه": "kalle paho", "آبگوشت": "abgoosht",
    "دلمه": "dolma", "خوراک لوبیا": "bean stew",
    "ماست": "yogurt", "دوغ": "doogh yogurt drink",
    "نان بربری": "barbari bread", "نان سنگک": "sangak bread",
    "نان لواش": "lavash bread", "شیرینی نخودچی": "noghl cookies",
    "سوهان": "sohan candy", "گز": "gaz candy",
    "پولکی": "noghl", "معجون": "herbal mix",
    "شربت آبلیمو": "lemonade", "شربت خاکشیر": "khakshir drink",
    "چای ایرانی": "persian tea", "قلیان": "hookah",
    # nature / weather / space
    "صاعقه": "lightning bolt", "تگرگ": "hail",
    "بلور یخ": "ice crystal", "یخزدگی": "frost",
    "مه صبحگاهی": "morning fog", "نور خورشید": "sunlight",
    "پرتو خورشید": "sun rays", "سایه": "shadow",
    "افق": "horizon", "افق دریا": "sea horizon",
    "جزیره مرجانی": "coral island", "صخره دریایی": "sea cliff",
    "دره": "valley", "تنگه": "canyon", "بلندترین قله":
        "highest peak",
    "چمنزار": "meadow", "گلستان وحشی": "wildflower meadow",
    "شالیزار": "rice paddy", "مزرعه گندم": "wheat field",
    "باغ سیب": "apple orchard", "باغ پرتقال": "orange orchard",
    "نخلستان": "palm grove", "تاکستان": "vineyard",
    # animals 2
    "بز کوهی": "mountain goat", "آهو": "gazelle",
    "آبزیان": "marine life", "خرچنگ": "crab",
    "صدف": "seashell", "ستاره دریایی": "starfish",
    "عروس دریایی": "jellyfish", "اسب دریایی": "seahorse",
    "لاک پشت دریایی": "sea turtle", "کوسه سفید": "great white shark",
    "عقاب طلا": "golden eagle", "طوطی رنگی": "colorful parrot",
    "قناری زرد": "yellow canary", "گنجشک کوچک": "small sparrow",
    "دسته پرنده": "flock of birds", "لک لک": "stork",
    "حواصیل": "heron", "اردک مهاجر": "migratory ducks",
    "حشره": "insect", "کرم شبتاب": "firefly",
    "سنجاب پرنده": "flying squirrel", "خفاش": "bat",
    "جوجه": "chick", "بره": "lamb", "بزغاله": "baby goat",
    "گوساله": "calf", "کرگدن": "rhino", "اسب آبی": "hippo",
    "کوالا": "koala", "پاندا": "panda", "کانگورو": "kangaroo",
    "کنگورو": "kangaroo", "لاما": "llama", "الاغ کوهی": "wild donkey",
    # people / jobs 2
    "قاضی": "judge", "وکیل": "lawyer", "خبرنگار": "journalist",
    "عکاس": "photographer", "نجار": "carpenter",
    "آهنگر": "blacksmith", "خراط": "woodcarver",
    "قالیباف": "carpet weaver", "کشتی گیر": "wrestler",
    "قهرمان ورزشی": "sports champion", "داور فوتبال": "football referee",
    "خلبان هواپیما": "airplane pilot", "ملوان": "sailor",
    "رفتگر": "street sweeper", "راننده تاکسی": "taxi driver",
    "نانوا": "baker", "قصاب": "butcher", "میوه فروش":
        "fruit seller",
    "دانش آموز مدرسه": "school students", "کلاس درس": "classroom",
    "امتحان": "exam", "داوطلب کنکور": "university exam student",
    # city / transport 2
    "دوچرخه ثابت": "stationary bike", "اسکلت موتور": "motor frame",
    "کامیون باری": "cargo truck", "وانت": "pickup truck",
    "اتوبوس شهری": "city bus", "تاکسی": "taxi",
    "ایستگاه مترو": "subway station", "پل هوایی": "pedestrian bridge",
    "پل بزرگ": "large bridge", "بندرگاه": "harbor",
    "اسکله": "dock", "قایق بادبانی": "sailing boat",
    "لنج": "traditional boat", "شنای ساحلی": "beach swimming",
    "چراغ های شهر": "city lights", "آسمانخراش های شب":
        "skyscrapers at night",
    "محله قدیمی": "old neighborhood", "کوچه باغ": "garden alley",
    "خانه روستایی": "village house", "ییلاق": "mountain village",
    "قشلاق": "winter pasture", "عشایر": "nomads",
    "چادر عشایری": "nomad tent", "سیاه چادر": "black nomad tent",
    # sport 2
    "کوهنورد": "mountaineer", "سنگ نوردی": "rock climbing",
    "اسکی روی آب": "water skiing", "غواصی": "scuba diving",
    "شنا در دریا": "sea swimming", "قایقرانی": "rowing",
    "دو میدانی": "track and field", "دوی استقامت": "marathon running",
    "پیاده روی": "walking", "کوهپیمایی": "hiking",
    "کمپینگ": "camping", "چادر کمپ": "camping tent",
    "آتش کمپ": "campfire", "ساک کمپ": "backpack",
    # abstract 2 / objects 2
    "تاج گل": "flower wreath", "بوق گل": "flower cone",
    "گل خشک": "dried flowers", "پته گل": "flower petals",
    "برگ پاییزی": "autumn leaves", "برگ سبز": "green leaf",
    "شاخه گل": "flower branch", "جوانه": "bud",
    "نهال": "sapling", "بذر": "seeds",
    "خاک باغچه": "garden soil", "گلدان گل": "flower vase",
    "قطره آب": "water drop", "قطره شبنم": "dew drop",
    "حباب صابون": "soap bubble", "بادبادک": "kite",
    "فرفره": "pinwheel", "عروسک": "doll",
    "تاپ بازی": "spinning top", "اسباب بازی": "toy",
    "پازل": "jigsaw puzzle", "شطرنج": "chess",
    "تاس": "dice", "ورق بازی": "playing cards",
    "ماشین حساب": "calculator", "تقویم": "calendar",
    "دفترچه یادداشت": "notebook", "پاکت نامه": "envelope",
    "تمبر": "postage stamp", "مهر پستی": "postmark",
}


# module-load normalization: ZWNJ is REMOVED (not spaced) so compound
# words typed with ZWNJ («قهوه‌ای», «دسته‌گل») fold onto the dict keys,
# Arabic variants fold to the Persian letters.
def _fa_norm(t):
    t = str(t or "").replace(_ZWNJ, "")
    for a, b in (("ي", "ی"), ("ك", "ک"), ("أ", "ا"), ("إ", "ا"),
                 ("آ", "ا"), ("ؤ", "و"), ("ئ", "ی"), ("ة", "ه"), ("ۀ", "ه")):
        t = t.replace(a, b)
    return " ".join(t.split()).lower()


def _fa_plural(t):
    """Colloquial plural without ZWNJ: 'گلها' -> 'گل' (len-guard keeps
    words that genuinely end in ها)."""
    return t[:-2] if len(t) >= 4 and t.endswith("ها") else t


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_PHRASES = {}
for _k, _v in _FA_EN_PHRASES.items():
    _nk = _fa_norm(_k)
    _PHRASES[_nk] = _v
    _PHRASES.setdefault(_nk.replace(" ", ""), _v)   # ZWNJ-folded form
_WORDS = {}
for _k, _v in _FA_EN_WORDS.items():
    _nk = _fa_norm(_k)
    _WORDS.setdefault(_nk, _v)
    _WORDS.setdefault(_nk.replace(" ", ""), _v)
    # v7.10: multi-word keys living in the WORDS table («قرمه سبزی»,
    # «دسته پرنده», ...) are unreachable by the single-token lookup -
    # fold them into the PHRASE table so the 4/3/2-gram greedy matcher
    # translates them before their parts pass through untranslated
    if " " in _nk:
        _PHRASES.setdefault(_nk, _v)
        _PHRASES.setdefault(_nk.replace(" ", ""), _v)

# every English word the dictionary can produce - dict-produced tokens
# are STRONG anchors (2.5); unknown passthrough tokens (proper nouns,
# frame words) are weak (1.0); colors sit in between (2.0).
_EN_KNOWN = set()
for _v in list(_FA_EN_PHRASES.values()) + list(_FA_EN_WORDS.values()):
    _EN_KNOWN.update(_v.split())

_FA_SCRIPT_RE = re.compile(r"[\u0600-\u06FF]")
_FA_PERSIAN_RE = re.compile(r"[گچپژی]")

# name -> (h_lo, h_hi, sat_lo, sat_hi, val_lo, val_hi, min_share) on the
# PIL 0-255 HSV scale; red wraps around 0. min_share is the fraction of
# pixels the color must occupy for the photo to count as matching.
_COLOR_SPECS = {
    "red":    (244, 11, 90, 255, 60, 255, 0.06),
    "pink":   (227, 244, 30, 170, 120, 255, 0.05),
    "orange": (11, 32, 90, 255, 90, 255, 0.05),
    "yellow": (32, 52, 80, 255, 110, 255, 0.05),
    "green":  (52, 122, 50, 255, 40, 255, 0.06),
    "blue":   (122, 182, 60, 255, 40, 255, 0.05),
    "purple": (182, 214, 40, 255, 40, 255, 0.04),
    "brown":  (11, 37, 60, 255, 30, 140, 0.08),
    "golden": (33, 56, 120, 255, 120, 255, 0.05),
    "silver": (0, 255, 0, 30, 90, 220, 0.15),
    "gray":   (0, 255, 0, 30, 60, 200, 0.15),
    "black":  (0, 255, 0, 255, 0, 45, 0.15),
    "white":  (0, 255, 0, 35, 205, 255, 0.15),
}


def _stem_set(w):
    """ALL plausible stems of one word. 'roses' must match 'rose' - the
    naive es-strip gave 'ros' and the rose query matched nothing (found
    by the v7.6 tests)."""
    w = str(w or "").lower()
    out = {w}
    if len(w) > 4 and w.endswith("ies"):
        out.add(w[:-3] + "y")
    if len(w) > 3 and w.endswith("es"):
        out.add(w[:-2])
        out.add(w[:-1])
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        out.add(w[:-1])
    # colloquial PERSIAN plural «گلها» -> «گل» (candidate titles too)
    if len(w) >= 4 and w.endswith("ها"):
        out.add(w[:-2])
    # the >=3 guard is for latin noise ('as', 's'); 2-letter PERSIAN
    # words are real content («گل», «رز») and must survive
    return {o for o in out if len(o) >= 3 or not o.isascii()}


def translate_query(query):
    """Offline Persian->English image-subject translation + cleanup.
    -> {"orig", "fa", "en", "subject", "colors", "weights",
        "orig_tokens", "orig_extra"}
    Pure dict work (no network, no model); unknown tokens pass through
    unchanged so proper nouns still search."""
    orig = _norm_query(query)
    norm = _fa_norm(orig)
    fa = bool(_FA_SCRIPT_RE.search(norm))
    raw_tokens = [_fa_plural(t) for t in _TOKEN_RE.findall(norm)]
    orig_tokens = [t for t in raw_tokens if len(t) > 1]
    content = [t for t in orig_tokens if t not in _FA_STOP]
    # phrase-first greedy translation (4, 3, then 2 tokens - the 4-gram
    # lets 'سیب زمینی سرخ کرده' win before 'سرخ' becomes the color red),
    # then singles
    en_parts, i = [], 0
    while i < len(content):
        hit = None
        for n in (4, 3, 2):
            if i + n <= len(content):
                joined = " ".join(content[i:i + n])
                en = _PHRASES.get(joined) or _PHRASES.get(
                    joined.replace(" ", ""))
                if en:
                    hit = (n, en)
                    break
        if hit:
            en_parts.extend(hit[1].split())
            i += hit[0]
            continue
        t = content[i]
        # a ZWNJ-typed compound («دسته‌گل») arrives as ONE token whose
        # de-spaced form is a PHRASES key - try phrases before plurals
        en = _WORDS.get(t) or _PHRASES.get(t) \
            or _WORDS.get(_fa_plural(t)) or _WORDS.get(t.replace(" ", ""))
        en_parts.extend((en or t).split())
        i += 1
    en_tokens = [t for t in en_parts if t not in _EN_STOP and len(t) > 1]
    core = [t for t in en_tokens if t not in _EN_TAIL_TRIM]
    colors = [t for t in en_tokens if t in _COLOR_SPECS]
    if fa:
        # Persian order is HEAD-FIRST («گربه سیاه» -> cat black) - the
        # subject is the last NON-COLOR core token. (v7.6 audit: plain
        # core[-1] landed on the color and the ladder produced a junk
        # 'black black' rung that got REALLY searched.)
        # v8.0.1: prefer a token the dict actually KNOWS - the brand
        # name in «کافه نوا» must never become the subject: every
        # candidate would miss it (subject orphan) and the page would
        # fill with placeholders instead of cafe photos.
        noncolor = [t for t in core if t not in _COLOR_SPECS]
        pool = noncolor or core
        known_pool = [t for t in pool
                      if _stem_set(t) & _EN_KNOWN]
        subject = (known_pool or pool)[-1] if pool else ""
    else:
        # english photo descriptors lead with the subject ("espresso cup
        # dark coffee") but grammar can be head-last ("cup of coffee").
        # v8.0.1: the last DICT-KNOWN noun wins ("chocolate cake slice"
        # -> cake, "coffee shop interior warm" -> shop) - a trailing
        # unknown modifier ('slice', 'warm') can no longer hijack the
        # subject anchor. STEM-aware membership: 'roses' counts as the
        # known 'rose' (exact membership broke 'red roses bouquet hero').
        if core:
            known_pool = [t for t in core if _stem_set(t) & _EN_KNOWN]
            subject = (known_pool or core)[-1]
        else:
            subject = en_tokens[-1] if en_tokens else ""
    if fa and subject:
        # translated tokens arrive in PERSIAN order (head first: 'róz
        # ghermez') - rebuild natural English order: modifiers, colors,
        # subject. ENGLISH input is already natural - never reordered
        # (v7.6 fix: reordering scrambled 'red roses bouquet').
        others = [t for t in core if t != subject and t not in colors]
        ordered = list(dict.fromkeys(others + colors + [subject]))
    else:
        ordered = en_tokens
    seen, weights = set(), []
    for t in ordered:
        key = tuple(sorted(_stem_set(t)))
        if key in seen:
            continue
        seen.add(key)
        # v8.0.1: STEM-aware known check - 'roses' must weigh as the
        # dict 'rose' (exact membership starved it to 1.0, which then
        # let the orphan gate treat true subject words as junk)
        w = 2.0 if t in _COLOR_SPECS else \
            (2.5 if _stem_set(t) & _EN_KNOWN else 1.0)
        weights.append((t, w))
    # Persian candidates are matched against the ORIGINAL words too, but
    # only when the scripts actually differ (never double-count English)
    orig_extra = content if fa else []
    return {"orig": orig, "fa": fa,
            "en": " ".join(ordered) or orig,
            "subject": subject, "colors": colors, "weights": weights,
            "orig_tokens": orig_tokens, "orig_extra": orig_extra}


def build_ladder(tq):
    """The search ladder for one translated query. Persian queries search
    ENGLISH FIRST (that is the whole rice-trap fix) and keep the original
    Persian as a later rung for local niches; English queries keep the
    exact v7.4 word-by-word tail relaxation (head kept) so long weak-
    model descriptions degrade gracefully. Never empty."""
    out = []

    def add(q):
        q = _norm_query(q)
        if q and len(q) >= 2 and q not in out:
            out.append(q)

    if tq.get("fa"):
        add(tq.get("en"))
        subj = tq.get("subject") or ""
        colors = tq.get("colors") or []
        if subj:
            add(" ".join(colors + [subj]) if colors else subj)
        add(tq.get("orig"))
        add(subj)
    else:
        # v7.4 behavior, preserved verbatim: the RAW query first, then
        # drop the tail word by word, keep the head (the legacy fill/pick
        # relaxation tests pin these exact calls; never below 2 words,
        # so no single-token subject rung here)
        words = (tq.get("orig") or "").split()
        add(tq.get("orig"))
        while len(words) > 2:
            words = words[:-1]
            add(" ".join(words))
    return out[:5] or [tq.get("orig") or ""]


def smart_search(query, limit=5, deadline=None):
    """Translate + ladder + CROSS-RUNG MERGED, relevance-ranked provider
    search. v7.6 returned the FIRST rung that produced anything - a
    weak first rung ("red" matching any red object) could hide a
    perfect second rung forever. v7.10: consecutive rungs are searched
    and their pools MERGED (URL-deduped) and ranked TOGETHER; the ladder
    stops early only when the merged pool already holds enough
    SUBJECT-anchored candidates (title carries the subject) - a junk
    first rung can no longer satisfy the search. Every rung is
    deadline-checked, so the whole pass stays bounded.
    -> (results, tq)"""
    tq = translate_query(query)
    rungs = build_ladder(tq)
    # v8.1 AI LAYER 1: a connected cloud brain suggests precise English
    # photo phrases for this subject - they search right after the
    # PRIMARY rung (better than tail relaxation), deduped, capped.
    # Deadline-guarded: a slow brain cannot eat the whole fill budget.
    ai_rungs = _ai_extra_rungs(query) if _left(deadline) > 10.0 else []
    if ai_rungs:
        rungs = (rungs[:1] + [r for r in ai_rungs if r not in rungs]
                 + [r for r in rungs[1:] if r not in ai_rungs])[:8]
    limit = max(1, min(limit, MAX_SEARCH_RESULTS))
    # enough subject-carrying candidates before we stop climbing
    need = max(2, min(3, limit))
    merged, seen = [], set()
    for rung in rungs:
        if _left(deadline) <= 1.0:
            break
        try:
            results = search_images(rung, limit=limit, deadline=deadline)
        except Exception:
            results = []
        for r in results or []:
            u = str(r.get("url") or "").split("#")[0].strip()
            if not u or u in seen:
                continue
            seen.add(u)
            merged.append(r)
        if len(merged) >= limit and _subject_hits(merged, tq) >= need:
            break
    if not merged:
        return [], tq
    # one final ranking across ALL rung pools; ties broken by the
    # provider quality key then pool order (stable)
    merged.sort(key=lambda r: (-_relevance(r, tq), _quality_key(r)))
    return merged[:limit], tq


def _cand_tokens(r):
    """(title_token_set, url_token_set) for one candidate; percent-
    encoded Persian URLs decode into real words here; every token
    contributes ALL its plural stems (roses -> rose)."""
    from urllib.parse import unquote
    title = str(r.get("title") or "")
    try:
        path = unquote(str(r.get("url") or ""), errors="ignore")
    except Exception:
        path = str(r.get("url") or "")
    tt = set()
    for t in _TOKEN_RE.findall(title.lower()):
        if len(t) > 1:
            tt |= _stem_set(t)
    ut = set()
    for t in _TOKEN_RE.findall(path.lower()):
        if len(t) > 1:
            ut |= _stem_set(t)
    return tt, ut


def _relevance(r, tq):
    """Weighted token overlap of one candidate against the translated
    query. Dict nouns weigh 2.5, colors 2.0, unknown tokens 1.0; title
    matches outweigh URL matches; the ORIGINAL Persian words match at
    2.0 when the query is Persian; a Persian query whose best matches
    are Arabic-only titles (the rice trap) is penalized.
    v7.10 SUBJECT ANCHORING: the subject of the query is the anchor -
    a candidate whose TITLE carries it is boosted +3.0, one whose URL
    carries it +1.8, and one that never mentions it anywhere is
    penalized -2.0. A clean photo of anything else ("branch on red
    background" for "red rose") can no longer ride the color word into
    the top slots. Never raises."""
    try:
        tt, ut = _cand_tokens(r)
        s = 0.0
        for tok, w in tq.get("weights") or ():
            stems = _stem_set(tok)
            if stems & tt:
                s += w
            elif stems & ut:
                s += w * 0.6
        for tok in tq.get("orig_extra") or ():
            if tok in tt or tok in ut:
                s += 2.0
        subj = tq.get("subject") or ""
        if subj:
            subj_stems = _stem_set(subj)
            if subj_stems & tt:
                s += 3.0                    # the SUBJECT is in the title
            elif subj_stems & ut:
                s += 1.8                    # only the url knows it
            else:
                s -= 2.0                    # subject never mentioned
        if tq.get("fa") and s < 2.0:
            blob = f"{r.get('title') or ''} {r.get('url') or ''}"
            if not _FA_PERSIAN_RE.search(blob):
                s -= 2.5              # Arabic/other-script lookalike
        return s
    except Exception:
        return 0.0


def _subject_hits(pool, tq):
    """How many candidates in one pool carry the SUBJECT in their TITLE
    (the strongest anchor). Drives the smart_search early-stop."""
    subj = tq.get("subject") or ""
    if not subj:
        return len(pool)
    stems = _stem_set(subj)
    n = 0
    for r in pool:
        try:
            tt, _ut = _cand_tokens(r)
        except Exception:
            continue
        if stems & tt:
            n += 1
    return n


def _passes_color(raw, ext, colors):
    """Pixel verification of the query's color words (PIL, offline).
    Every required color must occupy its minimum share of pixels; an
    unreadable frame, a missing Pillow or a non-photo extension never
    rejects (soft gate - it can only demote, never empty the result)."""
    if not colors:
        return True
    if ext not in ("jpg", "png", "webp"):
        return True
    Image, _ops = _pil()
    if not Image:
        return True
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB").resize((64, 64))
        px = list(im.convert("HSV").getdata())
    except Exception:
        return True
    total = len(px) or 1
    for name in colors:
        spec = _COLOR_SPECS.get(name)
        if not spec:
            continue
        hlo, hhi, slo, shi, vlo, vhi, mins = spec
        cnt = 0
        for h, s, v in px:
            in_h = (hlo <= h <= hhi) if hlo <= hhi else (h >= hlo or h <= hhi)
            if in_h and slo <= s <= shi and vlo <= v <= vhi:
                cnt += 1
        if cnt / total < mins:
            return False
    return True


_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def _sniff_ext(raw, ctype=""):
    """Image extension from magic bytes (the ONLY trusted source - a
    lying Content-Type must never rename a payload)."""
    for magic, ext in _MAGIC:
        if raw.startswith(magic):
            return ext
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    head = raw[:512].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return "svg"
    return None


def _atomic_write_bytes(path: Path, data: bytes):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_text(path: Path, data: str):
    _atomic_write_bytes(path, data.encode("utf-8"))


# --------------------------------------------------------------- cache
def _cache_path(ws):
    return Path(ws) / CACHE_FILE


def _load_cache(ws):
    try:
        raw = _cache_path(ws).read_text(encoding="utf-8")
        m = json.loads(raw).get("map", {})
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _save_cache(ws, cache):
    if len(cache) > CACHE_MAX:                       # drop the oldest
        items = sorted(cache.items(),
                       key=lambda kv: kv[1].get("ts", 0) if isinstance(kv[1], dict) else 0)
        cache = dict(items[len(items) - CACHE_MAX:])
    try:
        p = _cache_path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(p, json.dumps(
            {"v": 1, "map": cache}, ensure_ascii=False, indent=0))
    except Exception:
        pass                                          # cache is best-effort


def _cache_get(cache, key):
    v = cache.get(key)
    if isinstance(v, dict) and v.get("rel"):
        return str(v["rel"])
    return None


# --------------------------------------------------------------- providers
def _ddg_search(query, limit, deadline):
    """DuckDuckGo images (no key). Two requests: HTML page -> vqd token,
    then the i.js JSON endpoint. Unofficial: every miss is fail-soft.
    Each request honors the remaining time budget (v7.2 audit fix)."""
    ns = _ns_mod
    import urllib.parse as up
    q = up.quote(query)
    to = _t_left(deadline, T_SEARCH)
    if to is None:
        return []
    html, _ = ns.http_get(
        f"https://duckduckgo.com/?q={q}&iax=images&ia=images",
        timeout=to)
    m = (re.search(r'vqd=["\']?([\d-]+)["\']?', html)
         or re.search(r"vqd=([\d-]+)&", html))
    if not m:
        return []
    to = _t_left(deadline, T_SEARCH)
    if to is None:
        return []
    js, _ = ns.http_get(
        f"https://duckduckgo.com/i.js?l=us-en&o=json&q={q}"
        f"&vqd={m.group(1)}&f=,,,&p=1", timeout=to)
    data = json.loads(js)
    out = []
    for r in (data.get("results") or [])[:limit * 2]:
        url = str(r.get("image") or "").strip()
        if not url:
            continue
        out.append({
            "title": (r.get("title") or "").strip()[:120],
            "url": url,
            "thumb": (r.get("thumbnail") or "").strip(),
            "width": _to_int(r.get("width")),
            "height": _to_int(r.get("height")),
            "source": "ddg",
        })
    return out


def _bing_search(query, limit, deadline):
    """Bing images (no key, v7.10 fourth provider - widens the pool for
    niche subjects and works on networks where DDG is blocked). Result
    tiles carry an HTML-escaped JSON in m="...": murl = media url,
    turl = thumbnail, t = title. Unofficial: every miss is fail-soft.
    Dimensions are unknown (0) - the gates treat unknown as pass and the
    quality key just ranks bing candidates after known-big ones."""
    ns = _ns_mod
    import html as _html
    import urllib.parse as up
    to = _t_left(deadline, T_SEARCH)
    if to is None:
        return []
    page, _ = ns.http_get(
        "https://www.bing.com/images/search?q=" + up.quote(query)
        + "&form=HDRSC2&first=1", timeout=to)
    out = []
    for mattr in re.findall(r'm="({&quot;.*?})"', page)[:limit * 3]:
        try:
            d = json.loads(_html.unescape(mattr))
        except Exception:
            continue
        url = str(d.get("murl") or "").strip()
        if not url:
            continue
        out.append({
            "title": str(d.get("t") or "").strip()[:120],
            "url": url,
            "thumb": str(d.get("turl") or "").strip(),
            "width": 0,
            "height": 0,
            "source": "bing",
        })
    return out


def _openverse_search(query, limit, deadline):
    """Openverse API (no key, CC-licensed). Geo-blocked on some networks -
    that is fine, it is one link in the chain."""
    ns = _ns_mod
    import urllib.parse as up
    to = _t_left(deadline, T_SEARCH)
    if to is None:
        return []
    js, _ = ns.http_get(
        "https://api.openverse.org/v1/images/?q=" + up.quote(query)
        + "&page_size=" + str(min(limit * 2, 20)) + "&mature=false",
        timeout=to)
    data = json.loads(js)
    out = []
    for r in (data.get("results") or [])[:limit * 2]:
        url = str(r.get("url") or "").strip()
        if not url:
            continue
        out.append({
            "title": (r.get("title") or "").strip()[:120],
            "url": url,
            "thumb": (r.get("thumbnail") or "").strip(),
            "width": _to_int(r.get("width")),
            "height": _to_int(r.get("height")),
            "source": "openverse",
        })
    return out


def _commons_search(query, limit, deadline):
    """Wikimedia Commons file search (no key). Great precision for
    landmarks, famous people/places, plants, animals."""
    ns = _ns_mod
    import urllib.parse as up
    to = _t_left(deadline, T_SEARCH)
    if to is None:
        return []
    js, _ = ns.http_get(
        "https://commons.wikimedia.org/w/api.php?action=query&format=json"
        "&generator=search&gsrnamespace=6&gsrlimit=" + str(min(limit * 2, 20))
        + "&gsrsearch=" + up.quote(query)
        + "&prop=imageinfo&iiprop=url%7Csize%7Cmime&iiurlwidth=1200",
        timeout=to)
    data = json.loads(js)
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        info = (p.get("imageinfo") or [{}])[0]
        mime = str(info.get("mime") or "")
        if not mime.startswith("image/"):
            continue
        out.append({
            "title": str(p.get("title") or "").replace("File:", "")[:120],
            "url": (info.get("thumburl") or info.get("url") or "").strip(),
            "thumb": (info.get("thumburl") or "").strip(),
            "width": _to_int(info.get("thumbwidth") or info.get("width")),
            "height": _to_int(info.get("thumbheight") or info.get("height")),
            "source": "commons",
        })
    return out


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _t_left(deadline, base):
    """v7.2 audit fix: clamp each request's timeout to the REMAINING time
    budget - providers used to accept `deadline` and ignore it, so one
    slow provider could overshoot the whole fill budget by ~1 min."""
    left = _left(deadline)
    if left <= 1.0:
        return None
    return max(1.0, min(base, left - 0.5))


# ------------------------------------------------------- quality gates
# v7.4: the user literally saw watermarked stock previews, logo/clip-art
# PNGs, meme gifs, sideways infographic crops and 80px thumbnails land on
# generated pages. These gates keep that class of result OUT. All gates
# are PREFIX gates (they only ever remove candidates); search_images
# still returns the raw leftovers when nothing passes, so a niche query
# can never end up with NOTHING on a flaky network.
_HOST_PARTS = (
    # watermarked / paid stock previews
    "shutterstock", "gettyimages", "istockphoto", "alamy", "dreamstime",
    "123rf", "depositphotos", "stock.adobe", "stockphoto", "agefotostock",
    "photodune", "bigstock", "pond5", "colourbox", "freeimages.com",
    # v7.6: Persian stock/watermark farms seen in the wild (tarh.ir serves
    # files under products_watwermark/ with a burned-in site mark)
    "tarh.ir", "tarhir", "picofile.com", "rozblog.com", "blogfa.com",
    # clip-art / sticker / logo farms (transparent PNG cut-outs)
    "freepik", "vecteezy", "clipartmax", "clipartkey", "clipart-library",
    "cleanpng", "pngwing", "pngegg", "pngtree", "stickpng", "flaticon",
    "icons8", "thenounproject", "iconfinder", "icon-icons", "svgrepo",
    "freeiconspng", "iconsdb", "iconarchive",
    # social/video frames (faces, captions, UI chrome, burned-in text)
    "pinterest", "pinimg", "ytimg", "youtube", "tiktok", "tiktokcdn",
    "fbcdn", "fbsbx", "instagram", "cdninstagram", "9cache", "9gag",
    "imgflip", "memegenerator", "makeameme", "memecreator", "quickmeme",
    "knowyourmeme", "redditmedia", "preview.redd", "redd.it", "reddit.com",
)
_BAD_TEXT_RE = re.compile(
    r"(?i)(?<![a-z0-9])(logo|icon|favicon|sprite|clipart|clip-art|clip_art|"
    r"infographic|infografía|diagram|flowchart|"
    # v7.4 audit fix: 'chart-topping hits' / 'graph-search' are REAL photo
    # subjects - the word only counts when the hyphen is NOT a compound
    r"chart(?![a-z0-9-])|graph(?![a-z0-9-])|scheme|"
    r"watermark|sticker|emoji|smiley|meme|screenshot|screengrab|"
    # v7.6: real-world misspellings on watermark-farm URLs
    # (tarh.ir ships 'products_watwermark/...' paths)
    r"watwermark|wattermark|watmark|water_mark|"
    r"qr[\s_-]*code|barcode|coupon|voucher|certificate|diploma|"
    r"text[\s_-]*(box|banner|overlay))(?![a-z0-9])")

# v7.6: Persian stock-site markers that never appear in english - the
# filename-only blob of _text_bad misses them
_BAD_TEXT_FA_RE = re.compile(r"کد\s*فایل|طرح\s*دات|دانلود\s*عکس\s*با\s*کیفیت|\bواترمارک\b")


def _host_bad(url):
    u = str(url or "").lower()
    for part in _HOST_PARTS:
        if part in u:
            return True
    return False


def _text_bad(r):
    blob = f"{r.get('title') or ''} {str(r.get('url') or '').rsplit('/', 1)[-1]}"
    if _BAD_TEXT_RE.search(blob):
        return True
    # v7.6: also sweep the DECODED full url - watermarked Persian stock
    # farms sign their PATHS (products_watwermark/), not the filename
    from urllib.parse import unquote
    try:
        full = unquote(str(r.get("url") or ""), errors="ignore")
    except Exception:
        full = str(r.get("url") or "")
    return bool(_BAD_TEXT_FA_RE.search(full)) or bool(
        _BAD_TEXT_RE.search(full))


def _dims_ok(r, strict):
    """Sanity dims: not tiny, not an extreme banner/infographic strip.
    Unknown dims never fail (providers omit them all the time)."""
    w = _to_int(r.get("width"))
    h = _to_int(r.get("height"))
    min_w = 450 if strict else 220
    min_h = 300 if strict else 150
    lo = 0.5 if strict else 0.4      # portrait floor  (tall infographics)
    hi = 2.0 if strict else 2.6      # landscape ceiling (wide banners)
    if w and h:
        if w < min_w or h < min_h:
            return False
        ratio = w / h
        if not (lo <= ratio <= hi):
            return False
    elif w:
        if w < min_w:
            return False
    return True


def _gif_bad(r):
    return str(r.get("url") or "").lower().split("?")[0].endswith(".gif")


def _svg_bad(r):
    return str(r.get("url") or "").lower().split("?")[0].endswith(".svg")


def _candidate_ok(r, strict):
    """strict=True  : watermark/clip-art hosts OUT, text-y titles OUT,
                       sane dims, no gif, no svg.
       strict=False : only the CERTAIN signals (hosts, gif, svg) plus
                       relaxed dims - title words can be false positives
                       and this is the fallback pass."""
    if not strict and _host_bad(r.get("url")):
        return False
    if strict and (_host_bad(r.get("url")) or _text_bad(r)):
        return False
    if _gif_bad(r) or _svg_bad(r):
        return False
    return _dims_ok(r, strict)


def _quality_key(r):
    """Stable relevance-preserving order: real photos first, svg logos
    and gifs last; bigger images before smaller ones; within one
    provider the search engine's own order wins (stable sort)."""
    u = str(r.get("url", "")).lower()
    svg = 1 if u.endswith(".svg") else 0
    gif = 1 if u.split("?")[0].endswith(".gif") else 0
    w = r.get("width") or 0
    small = 0 if w >= 800 else (1 if w >= 500 else (2 if w >= 250 else 3))
    return (svg, gif, small)


def search_images(query, limit=6, deadline=None):
    """Merged, deduped, QUALITY-GATED and RELEVANCE-RANKED photo results:
    [{title, url, thumb, width, height, source}]. v7.4 gates keep the
    junk the user actually saw OUT of the results; the pool is assembled
    as strict-pass -> relaxed-pass -> whatever is left, so the gates prune
    junk but a niche query on a flaky network can still never return less
    than the old behavior did. v7.6: within each tier candidates are
    ranked by weighted token overlap against the translated query
    (_relevance) BEFORE the size/quality key - a big "branch on red
    background" can no longer outrank actual roses for "red rose".
    v7.10: Bing images joins the provider chain (DDG -> Bing ->
    Openverse -> Commons). The total time is bounded by `deadline`
    (monotonic)."""
    query = _norm_query(query)
    if not query or not _ns_mod or len(query) > 200:
        return []
    limit = max(1, min(limit, MAX_SEARCH_RESULTS))
    # v8.0.1: the providers run in PARALLEL STAGES. The old sequential
    # fan-out let one hung provider (ddg 13 s+ while rate-limited)
    # delay the fast ones (bing answers in 0.2 s) - a 4-slot page could
    # burn its whole budget inside ONE rung and the tail slots
    # degraded to placeholders (coffee81 live run). But a blind all-at-
    # once fan-out also wastes provider calls (rate limits!) - so the
    # two GENERAL engines (ddg, bing) race first, and the niche
    # fallbacks (openverse, commons) only get asked when the strict
    # pool is still short. Every provider still clamps itself to the
    # shared deadline via _t_left, so stragglers cannot blow the pass.
    from concurrent.futures import ThreadPoolExecutor
    stages = ((_ddg_search, _bing_search), (_openverse_search,
                                            _commons_search))
    raw, seen = [], []

    def _strict_count():
        return sum(1 for r in raw if _candidate_ok(r, strict=True))

    for stage in stages:
        if _strict_count() >= limit or _left(deadline) <= 1.0:
            break
        pool = ThreadPoolExecutor(max_workers=len(stage))
        try:
            futs = [(p, pool.submit(p, query, limit, deadline))
                    for p in stage]
            for _p, fut in futs:       # declared order = priority order
                if _strict_count() >= limit or _left(deadline) <= 1.0:
                    break
                try:
                    got = fut.result(
                        timeout=min(T_SEARCH + 2.0,
                                    max(2.0, _left(deadline)))) or []
                except Exception:
                    got = []
                for r in got:
                    u = str(r.get("url") or "").split("#")[0].strip()
                    if not u or u in seen:
                        continue
                    seen.append(u)
                    raw.append(r)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    strict, soft, rest = [], [], []
    for i, r in enumerate(raw):
        if _candidate_ok(r, strict=True):
            strict.append(i)
        elif _candidate_ok(r, strict=False):
            soft.append(i)
        else:
            rest.append(i)
    order = strict + soft if len(strict) >= limit else \
        (strict + soft + rest if (strict or soft) else rest)
    tq = translate_query(query)
    tier_of = {}
    for i in strict:
        tier_of[i] = 0
    for i in soft:
        tier_of[i] = 1
    for i in rest:
        tier_of[i] = 2
    results = []
    for i in order:
        r = raw[i]
        # tier-first keeps the v7.4 guarantee (strict pool first);
        # relevance ranks INSIDE each tier, then size/quality, then the
        # provider's own order (index) as the final tiebreak
        results.append((tier_of.get(i, 2), -_relevance(r, tq),
                        _quality_key(r), len(results), r))
    results.sort(key=lambda t: t[:4])
    return [t[4] for t in results[:limit]]


# --------------------------------------------------------------- download
def _fetch_image(url, deadline=None, max_bytes=MAX_FILE_BYTES,
                 timeout=T_DOWNLOAD):
    """SSRF-safe image fetch WITHOUT writing anything:
    -> (ext, raw_bytes, meta). Magic bytes decide the extension; a
    text/HTML masquerading as an image is refused; the size cap is
    enforced before AND during the read."""
    meta = {"url": url, "bytes": 0}
    if not _ns_mod:
        meta["error"] = "no network module"
        return None, None, meta
    if _left(deadline) <= 1.0:
        meta["error"] = "time budget exhausted"
        return None, None, meta
    url = str(url or "").strip()
    if not url or len(url) > 2000:
        meta["error"] = "bad url"
        return None, None, meta
    # v8.0: the per-request timeout is clamped to the REMAINING deadline -
    # a fetch started with 1.1 s of budget used to run a full T_DOWNLOAD
    # (12 s) past the fill-pass bound and stalled the apply pipeline.
    left = _left(deadline)
    if left is not None and left < timeout:
        timeout = max(1.0, left)
    try:
        raw, ctype, final = _ns_mod.http_get_bytes(
            url, timeout=timeout, max_bytes=max_bytes)
    except Exception as e:
        meta["error"] = str(e)[:140]
        meta["code"] = getattr(e, "code", None)
        return None, None, meta
    ext = _sniff_ext(raw, ctype)
    if not ext:
        meta["error"] = "not an image (magic bytes)"
        meta["ctype"] = ctype
        return None, None, meta
    meta["bytes"] = len(raw)
    meta["ext"] = ext
    meta["final_url"] = final
    return ext, raw, meta


def image_name(url, base_slug, ext):
    """Idempotent asset name: same URL + slug always maps to the same
    file, so a re-apply can never spray junk copies."""
    return f"{slug(base_slug)}-{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}.{ext}"


def download_image(url, dest_dir, base_slug, deadline=None,
                   max_bytes=MAX_FILE_BYTES, timeout=T_DOWNLOAD):
    """SSRF-safe image download -> (relative_name_inside_dest or None, meta).
    Magic bytes decide the extension; a text/HTML masquerading as an image
    is refused; the size cap is enforced before AND during the read."""
    ext, raw, meta = _fetch_image(url, deadline=deadline,
                                  max_bytes=max_bytes, timeout=timeout)
    if not ext:
        return None, meta
    url = str(url or "").strip()
    name = image_name(url, base_slug, ext)
    dest_dir = Path(dest_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(dest_dir / name, raw)
    except OSError as e:
        meta["error"] = f"cannot write: {e}"
        return None, meta
    return name, meta


# ------------------------------------------------- page-photo normalizer
def _pil():
    try:
        from PIL import Image, ImageOps          # optional dependency
        return Image, ImageOps
    except Exception:
        return None, None


def _ratio_bucket(ratio):
    """Stable cache-key bucket for one declared aspect ratio."""
    if not ratio:
        return "l"                                # the 3:2 default
    if ratio < 0.85:
        return "p"
    if ratio <= 1.2:
        return "s"
    return "l"


def _tag_ratio(tag):
    """The aspect ratio the MODEL declared on this tag via width/height
    attributes (v7.4: the downloaded photo is center-cropped to exactly
    it). None when absent, unparsable or insane - callers fall back to
    the 3:2 default."""
    wv, _ = _attr(tag, "width")
    hv, _ = _attr(tag, "height")
    if not wv or not hv:
        return None
    try:
        w = float(str(wv).strip().removesuffix("px"))
        h = float(str(hv).strip().removesuffix("px"))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    r = w / h
    return round(r, 3) if 0.4 <= r <= 2.4 else None


def normalize_for_page(raw, ext, ratio=None, max_w=1600):
    """v7.4: make every photo the agent puts on a page LOOK consistent
    with its siblings - this is the fix for "سایز هر عکس با اونیکی فرق
    داره / روشون متن داره / سازشون عجیبه":

      - EXIF orientation applied (no more sideways phone shots)
      - center-crop to `ratio` (the model's own width/height ratio,
        3:2 default) - but never cut more than 55% of one side, so a
        portrait stays a portrait instead of a decapitated strip
      - downscaled to <= max_w wide (never upscaled)
      - re-encoded JPEG q85: uniform, small, metadata-free files
      - animated / svg / alpha (logo/sticker) payloads pass through
        untouched; UNPARSEABLE payloads pass through untouched too
        (fail-open: the download still counts, Pillow just cannot help)
      - a payload Pillow CAN read but finds TINY (<180x120) returns
        (None, None, None) - the caller drops this candidate and tries
        the next one, instead of putting a thumbnail on the page

    Without Pillow installed the function is an identity no-op."""
    if ext in ("svg", "gif"):
        return raw, ext, None
    Image, ImageOps = _pil()
    if not Image:
        return raw, ext, None
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        return raw, ext, None                     # fail-open (junk/truncated)
    try:
        animated = bool(getattr(im, "is_animated", False))
    except Exception:
        animated = False
    if animated:
        return raw, ext, None
    try:
        im = ImageOps.exif_transpose(im) or im
    except Exception:
        pass
    w, h = im.size
    if w < 180 or h < 120:
        return None, None, None                   # known-tiny -> next candidate
    resample = getattr(Image, "Resampling", Image).LANCZOS
    # v7.4 audit fix: 16-bit/float grayscale clips to pure white in a
    # plain convert("RGB") - scale the ACTUAL dynamic range down first
    if im.mode.startswith("I;16") or im.mode in ("I", "F"):
        try:
            vmax = im.getextrema()[1]
            if vmax > 255:
                scale = 255.0 / vmax
                im = im.point(lambda v: int(v * scale)).convert("L")
            else:
                im = im.convert("L")
        except Exception:
            pass
    # transparency = logos/stickers/clip-art: keep bytes (would go black)
    alpha = False
    if im.mode in ("RGBA", "LA") or (
            im.mode == "P" and "transparency" in im.info):
        try:
            lo, _hi = im.convert("RGBA").getchannel("A").getextrema()
            alpha = lo < 250
        except Exception:
            alpha = True
    if alpha:
        if w > max_w:
            try:
                im = im.resize((max_w, max(1, round(h * max_w / w))),
                               resample)
                buf = io.BytesIO()
                if ext == "jpg":
                    im.save(buf, "JPEG", quality=85, optimize=True)
                    return buf.getvalue(), "jpg", im.size
                im.save(buf, "PNG", optimize=True)
                return buf.getvalue(), "png", im.size
            except Exception:
                return raw, ext, (w, h)
        return raw, ext, (w, h)
    # opaque photo -> center-crop to the wanted ratio (protect extreme cuts)
    target = ratio if ratio and 0.4 <= ratio <= 2.4 else 1.5
    cur = w / h
    if abs(cur - target) > 0.02:
        if cur > target:
            nw = int(round(h * target))
            if nw / w >= 0.45:
                x = (w - nw) // 2
                im = im.crop((x, 0, x + nw, h))
        else:
            nh = int(round(w / target))
            if nh / h >= 0.45:
                y = (h - nh) // 2
                im = im.crop((0, y, w, y + nh))
    w2, h2 = im.size
    if w2 > max_w:
        try:
            im = im.resize((max_w, max(1, round(h2 * max_w / w2))), resample)
        except Exception:
            pass
    w2, h2 = im.size
    buf = io.BytesIO()
    try:
        im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
    except Exception:
        return raw, ext, (w, h)
    return buf.getvalue(), "jpg", (w2, h2)


# --------------------------------------------------------------- placeholder
def placeholder_svg(label, w=1200, h=800):
    """A DETERMINISTIC, genuinely pretty local SVG art card for the rare
    case the internet cannot provide a photo. Gradient mesh from the
    label hash + soft orbs + a labeled chip. Valid XML, <= ~1.5 KB."""
    label = " ".join(str(label or "").split())[:42] or " "
    # v7.2 audit fix: XML 1.0 forbids control characters - a label with
    # e.g. \x00 used to produce an SVG the browser itself refuses (the
    # fallback would be a broken image - the exact thing it exists to
    # prevent).
    label = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", label).strip()
    label = label[:42] or " "
    seed = int(hashlib.md5(label.encode("utf-8")).hexdigest()[:8], 16)
    h1 = seed % 360
    h2 = (h1 + 42 + seed % 76) % 360
    h3 = (h1 + 200 + seed % 60) % 360
    esc = (label.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    fs = 64 if len(esc) <= 18 else (46 if len(esc) <= 30 else 34)
    cx = [18 + (seed % 40), 62 + (seed >> 3) % 30, 38 + (seed >> 5) % 44]
    cy = [24 + (seed >> 2) % 30, 18 + (seed >> 4) % 36, 68 + (seed >> 6) % 24]
    rr = [30 + (seed >> 7) % 18, 24 + (seed >> 9) % 20, 34 + (seed >> 11) % 16]
    orbs = "".join(
        f'<circle cx="{cx[i]}%" cy="{cy[i]}%" r="{rr[i]}%" '
        f'fill="hsla({(h1 + i * 47) % 360},80%,70%,0.35)"/>' for i in range(3))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" '
        'preserveAspectRatio="xMidYMid slice" role="img" '
        f'aria-label="{esc}">'
        '<defs>'
        f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="hsl({h1},68%,56%)"/>'
        f'<stop offset=".55" stop-color="hsl({h2},70%,50%)"/>'
        f'<stop offset="1" stop-color="hsl({h3},72%,42%)"/>'
        '</linearGradient>'
        f'<filter id="b"><feGaussianBlur stdDeviation="70"/></filter>'
        '</defs>'
        '<rect width="1200" height="800" fill="url(#g)"/>'
        f'<g filter="url(#b)">{orbs}</g>'
        '<rect x="60" y="620" rx="34" width="'
        + str(min(1080, 190 + 26 * len(esc))) + '" height="96" '
        'fill="rgba(255,255,255,.82)"/>'
        f'<text x="96" y="682" font-family="system-ui,Segoe UI,sans-serif" '
        f'font-size="{fs}" font-weight="700" fill="#1c2130">{esc}</text>'
        '</svg>')


# --------------------------------------------------------------- html fill
# v7.2 audit fix: the tag regex is QUOTE-AWARE - `<img alt="a > b">` used
# to be cut at the `>` inside the quoted value and the rewrite mangled
# the markup.
_IMG_TAG_RE = re.compile(r"<img\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>",
                         re.IGNORECASE)
# v7.2 audit fix: the lookbehind keeps `data-src=` / `data-alt=` from
# matching (lazy-load templates were rewritten in the WRONG attribute
# while the real src stayed broken).
_ATTR_RE = {
    "src": re.compile(r"(?<![\w-])src\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
                      re.I),
    "alt": re.compile(r"(?<![\w-])alt\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
                      re.I),
    "loading": re.compile(r"(?<![\w-])loading\s*=", re.I),
    "width": re.compile(r"(?<![\w-])width\s*=\s*(\"([^\"]*)\"|'([^']*)'"
                        r"|([^\s>]+))", re.I),
    "height": re.compile(r"(?<![\w-])height\s*=\s*(\"([^\"]*)\"|'([^']*)'"
                         r"|([^\s>]+))", re.I),
}
_PLACEHOLDER_HOSTS = (
    "via.placeholder.com", "placeholder.com", "placehold.co", "placehold.it",
    "placekitten.com", "dummyimage.com", "picsum.photos", "loremflickr.com",
    "placeimg.com", "fakeimg.pl", "placeholder.pics", "hipsum.co",
)
_REMOTE_RE = re.compile(r"^(https?:)?//", re.I)
_DATA_RE = re.compile(r"^data:image/", re.I)
_PROTO_PREFIX_RE = re.compile(r"^img\s*:\s*", re.IGNORECASE)
# v8.0.1: IMG: literals inside generated JavaScript (data arrays that
# feed createElement-based card grids). Quote-aware like _IMG_TAG_RE;
# newline never joins a literal so a broken quote cannot eat the file.
_JS_IMG_RE = re.compile(r"([\"'`])IMG:\s*([^\"'`\n]{3,120}?)\1")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_H1_CLOSE_RE = re.compile(r"</h1\s*>", re.I)
_SECTION_OPEN_RE = re.compile(r"<section\b[^>]*>", re.I)
_BODY_OPEN_RE = re.compile(r"<body\b[^>]*>", re.I)

# v7.4: pages that carry the design floor already constrain imgs; for
# every OTHER page we fill, this zero-specificity rule guarantees no
# downloaded photo can overflow its container or distort (the model's
# own css always wins over :where()).
_IMG_FLOOR_CSS = ('<style id="nova-img-floor">'
                  ':where(img){max-width:100%;height:auto}</style>')
_BODY_CLOSE_RE = re.compile(r"</body\s*>", re.I)
_STYLE_ATTR_RE = re.compile(
    r"(?<![\w-])style\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)


def _has_working_floor_css(page: Path, html):
    """True when the page links a nova-ui.css that ACTUALLY exists at the
    linked location. v7.4 audit fix: the bare 'nova-ui.css' substring
    lied on legacy nested pages (link present, file 404) and the img
    guard was skipped exactly where no floor css was served."""
    if "nova-ui.css" not in html:
        return False
    for m in re.finditer(
            r"(?<![\w-])href\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
            html, re.I):
        val = m.group(2) or m.group(3) or m.group(4) or ""
        if "nova-ui.css" in val:
            try:
                if (page.parent / val).is_file():
                    return True
            except OSError:
                pass
    return False


def _ensure_img_floor_css(html):
    if "nova-img-floor" in html:
        return html
    # v7.4 audit fix: splice at the LAST </body> - an earlier one can
    # live inside a script string or a comment (the first-match splice
    # corrupted the JS string / landed inside a comment)
    last = None
    for m in _BODY_CLOSE_RE.finditer(html):
        last = m
    if last is not None:
        return html[:last.start()] + _IMG_FLOOR_CSS + html[last.start():]
    return html + _IMG_FLOOR_CSS


def _page_title(html):
    """v8.0.1: the <title> text of a page, whitespace-folded (or '')."""
    m = _TITLE_RE.search(html or "")
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:80]


def _hero_query(html):
    """v8.0.1: image query for the zero-img safety net - the page title
    minus delimiter tails ("کافه نوا — نسخه چندفایلی" -> "کافه نوا").
    translate_query() turns Persian subjects into an English search."""
    t = _page_title(html)
    if not t:
        return ""
    t = re.split(r"\s*[—–|·]\s*|\s+-\s+", t)[0].strip()
    return t[:80]


def _inject_hero(html, tag):
    """v8.0.1: splice one hero <img> into a photo-less page - after the
    first </h1>, else inside the first <section>, else right after
    <body>. Returns html unchanged when no anchor exists."""
    m = _H1_CLOSE_RE.search(html)
    if m:
        i = m.end()
        return html[:i] + "\n" + tag + "\n" + html[i:]
    m = _SECTION_OPEN_RE.search(html)
    if m:
        i = m.end()
        return html[:i] + "\n" + tag + "\n" + html[i:]
    m = _BODY_OPEN_RE.search(html)
    if m:
        i = m.end()
        return html[:i] + "\n" + tag + "\n" + html[i:]
    return html


def _attr(tag, name):
    """(value, span) of one attribute inside an img tag; unquoted values
    included; span covers VALUE ONLY (between the quotes) for rewriting.
    v7.2 audit fix: the span comes from the REGEX GROUP OFFSETS - the old
    `m.group(0).find(val)` picked a span INSIDE the attribute name for
    short unquoted values (`src=c` -> 'c' found at index 2 of 'src=c'),
    silently corrupting the tag on rewrite."""
    m = _ATTR_RE[name].search(tag)
    if not m:
        return None, None
    g = 2 if m.group(2) is not None else (
        3 if m.group(3) is not None else 4)
    return m.group(g), (m.start(g), m.end(g))


def _strip_url_parts(src):
    return re.split(r"[?#]", src or "", 1)[0]


def _tiny_data_uri(src):
    """v8.0.1: True when a data: URI payload is too small to be a real
    photo. Weak local models dodge the IMG: protocol by embedding 1-3 KB
    procedural pixel junk as src - the page then ships fake "photos"
    with zero internet images (the coffe8_after report). Size math is
    lenient: any decode error counts as NOT tiny (the tag is left alone
    rather than risk replacing a real embedded asset)."""
    try:
        head, _, payload = str(src or "").partition(",")
        if head.rstrip().lower().endswith("base64"):
            n = len(_b64.b64decode(
                payload + "=" * (-len(payload) % 4), validate=False))
        else:
            n = len(_urlparse.unquote(payload).encode("utf-8", "ignore"))
    except Exception:
        return False
    return n < MIN_EMBEDDED_PHOTO_BYTES


def _classify(tag, src, alt, ws: Path, page_dir: Path):
    """-> (kind, query) where kind is one of:
    'protocol'  src="IMG:..."        -> query is the description
    'broken'    local path missing   -> query from alt (or src slug)
    'remote'    http(s) URL          -> verify by downloading (alt query)
    'leave'     fine as-is (data:, existing local file, '#')"""
    if src is None:
        return ("broken", (alt or "").strip())
    s = src.strip()
    if not s or s == "#":
        return ("broken", (alt or "").strip())
    m = _PROTO_PREFIX_RE.match(s)
    if m:
        return ("protocol", s[m.end():].strip() or (alt or "").strip())
    if _DATA_RE.match(s):
        # v8.0.1: a TINY data: payload is procedural junk, not a photo -
        # refill it from the alt text exactly like a broken local path.
        # Large embedded photos (rare, but the model's own choice) stay.
        if _tiny_data_uri(s):
            return ("broken", (alt or "").strip())
        return ("leave", None)
    if _REMOTE_RE.match(s):
        host = ""
        try:
            from urllib.parse import urlparse
            host = (urlparse(s).hostname or "").lower()
        except Exception:
            pass
        if any(h in host for h in _PLACEHOLDER_HOSTS):
            return ("broken", (alt or "").strip() or slug(s))
        return ("remote", (alt or "").strip())
    # local path (relative to the page or workspace-root absolute)
    rel = _strip_url_parts(s).lstrip("/")
    if s.startswith("/"):
        target = ws / rel
    else:
        target = page_dir / rel
    try:
        target.resolve().relative_to(ws.resolve())
    except (ValueError, OSError):
        return ("leave", None)             # escapes the workspace - untouched
    if target.is_file():
        return ("leave", None)
    q = (alt or "").strip() or slug(Path(rel).stem)
    return ("broken", q)


def _rewrite_tag(tag, new_src, dims=None):
    """Point one img tag at a new source + perf attrs. Keeps every other
    attribute (class, style, width...) untouched. v7.4: when the real
    pixel size is known (normalizer) and the tag declares NEITHER width
    nor height, explicit width/height attributes are added - the
    browser reserves the exact box (no layout shift, no surprise
    sizes)."""
    out = tag
    val, span = _attr(out, "src")
    if span is not None:
        out = out[:span[0]] + new_src + out[span[1]:]
    else:
        out = out.replace("<img", '<img src="' + new_src + '"', 1)
    add = ""
    if not _ATTR_RE["loading"].search(out):
        # v7.2 audit fix: a self-closing `/>` used to keep its stray `
        # slash as a bogus attribute (` / loading=...`). Void tags do not
        # need the slash - drop it when appending.
        add += ' loading="lazy" decoding="async"'
    if dims:
        wv, _ww = _attr(out, "width")
        hv, _hh = _attr(out, "height")
        # v7.4 audit fix: a tag sized via inline style (style="height:220px")
        # would get BOTH the attr box and the css box -> distortion
        sm = _STYLE_ATTR_RE.search(out)
        style_val = (sm.group(2) or sm.group(3) or sm.group(4) or "") \
            if sm else ""
        css_sized = bool(style_val) and (
            "width" in style_val or "height" in style_val)
        if wv is None and hv is None and not css_sized:
            add += f' width="{int(dims[0])}" height="{int(dims[1])}"'
    if add:
        core = out[:-1].rstrip()
        if core.endswith("/"):
            core = core[:-1].rstrip()
        out = core + add + ">"
    return out


def fill_html_images(ws, applied_names, deadline=None):
    """The v7.2 deterministic image pass. `ws` = workspace Path,
    `applied_names` = [relpath] the apply just wrote. Rewrites applied
    .html files IN PLACE (atomic) and returns (extras, notes):
        extras = [(relpath, bytes)] NEW asset files (photos + placeholders)
                 - the caller joins them into the same undo unit,
        notes  = [str] one line per action (console + web).
    Fail-soft per file and per image; the whole call never raises."""
    extras, notes = [], []
    ws = Path(ws)
    try:
        if not enabled():
            return extras, notes
        htmls = [n for n in (applied_names or [])
                 if str(n).lower().endswith((".html", ".htm"))][:6]
        jss = [n for n in (applied_names or [])
               if str(n).lower().endswith(".js")][:4]
        if not htmls and not jss:
            return extras, notes
        if deadline is None:
            # v8.0.1: scale the budget with the REAL workload. The old
            # flat 90 s starved multi-photo builds under load - the tail
            # slots degraded to placeholders / IMG: literals left in
            # place (coffee81 live run). Count the actual slots cheaply;
            # a slow 6-photo page now gets 150 s+, small pages keep the
            # snappy 90 s floor, hostile sizes cannot blow past 300 s.
            slots = 0
            for _n in htmls:
                _p = ws / _n
                try:
                    if _p.is_file() and _p.stat().st_size <= 3_000_000:
                        slots += len(_IMG_TAG_RE.findall(
                            _p.read_text(encoding="utf-8")))
                except Exception:
                    pass
            for _n in jss:
                _p = ws / _n
                try:
                    if _p.is_file() and _p.stat().st_size <= 1_000_000:
                        slots += len(_JS_IMG_RE.findall(
                            _p.read_text(encoding="utf-8")))
                except Exception:
                    pass
            deadline = time.monotonic() + min(
                420, max(DEFAULT_DEADLINE, 30 * slots))
        ws_r = ws.resolve()
        assets_dir = ws.joinpath(*ASSETS_DIR)
        cache = _load_cache(ws)
        cache_dirty = False
        extra_rels = set()      # dedupe: one extras entry per unique asset

        def _live_hit(key):
            """v7.2 audit fix: a cache hit is only reusable when the asset
            STILL EXISTS on disk - after /undo (which deletes downloaded
            photos) the stale rel used to be re-written into pages with
            no re-download and no placeholder: a permanently dead image."""
            hit = _cache_get(cache, key)
            if hit and hit != "gone" and (ws / hit).is_file():
                return hit
            return None

        def _save(rel_key, rel, dims=None):
            nonlocal cache_dirty
            entry = {"rel": rel, "ts": int(time.time())}
            if dims:
                entry["w"], entry["h"] = int(dims[0]), int(dims[1])
            cache[rel_key] = entry
            cache_dirty = True
            return rel

        def _hit_dims(key):
            """(w, h) recorded for a cached asset - lets cache hits also
            carry exact width/height attributes into the tag."""
            v = cache.get(key)
            if isinstance(v, dict) and v.get("w") and v.get("h"):
                return (int(v["w"]), int(v["h"]))
            return None

        def _asset_rel(name):
            return "/".join(ASSETS_DIR) + "/" + name

        def _rel_href(page_dir: Path, name):
            href = os.path.relpath(str(assets_dir / name), str(page_dir))
            return Path(href).as_posix()

        def _get_photo(query, page_dir, ratio=None, bucket="l"):
            """Real photo for one query -> (href, dims, note_tail) or
            (None, None, err). v7.2 fix: the fetched BYTES join `extras`
            (the undo unit) here - the download must never be an
            untracked orphan on disk. v7.4: every candidate is run
            through normalize_for_page (EXIF, ratio crop, cap, jpeg
            re-encode); svg 'photos', known-tiny thumbnails and
            unreadable-tiny payloads are skipped in favour of the next
            candidate. v7.6: smart_search (Persian->English translation
            ladder + relevance ranking) feeds the candidates and the
            query's color words are VERIFIED IN THE PIXELS - a photo
            that does not contain the required color is demoted to the
            soft fallback, so «قرمز» can no longer land as a green
            plant or a white rice dish."""
            qn = _norm_query(query)
            if not qn:
                return None, None, "empty query"
            qkey = f"q{bucket}:{qn}"
            hit = _live_hit(qkey)
            if hit:
                return _rel_href(page_dir, Path(hit).name), \
                    _hit_dims(qkey), "cache"
            # v8.6 SELECTION GATE: the local-vision approval layer may
            # refuse internet photo selection for this page entirely.
            ok_g, gnote = _ai_gate_ok(qn)
            if not ok_g:
                return None, None, (gnote or "vision-off")
            tq = None
            colors = []

            def _store(r, url, raw, ext, dims):
                """Write one verified candidate into assets + caches and
                return (href, note_tail). The filename base is the
                ENGLISH query (readable assets even for Persian input);
                the CACHE key stays the original query."""
                base = ((tq or {}).get("en") or qn) if tq else qn
                name = image_name(str(url).strip().split("#")[0],
                                  f"{base} {bucket}", ext)
                rel = _asset_rel(name)
                dest = assets_dir / name
                if dest.is_file():
                    # v7.4 audit fix: the asset already exists (earlier
                    # turn, /img, or a lost cache) - keep the user's
                    # bytes and just reference them; an overwrite here
                    # made /undo delete a file Nova never created
                    _save("u" + bucket + ":" + _strip_url_parts(url),
                          rel, dims)
                    _save(qkey, rel, dims)
                    return (_rel_href(page_dir, name), dims,
                            f"{r.get('source', '?')}, {ext} (existing)")
                try:
                    assets_dir.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
                _atomic_write_bytes(dest, raw)
                extras.append((rel, raw))
                extra_rels.add(rel)
                _save("u" + bucket + ":" + _strip_url_parts(url),
                      rel, dims)
                _save(qkey, rel, dims)
                return (_rel_href(page_dir, name), dims,
                        f"{r.get('source', '?')}, "
                        f"{ext}, "
                        f"{len(raw) // 1024} KB"
                        + (f", {dims[0]}x{dims[1]}" if dims else ""))

            # v7.4 fix: a provider hiccup (DDG rate-limit blips are common)
            # used to fall straight to the placeholder - one in-budget
            # retry keeps a transient miss from becoming a fake image
            results, tq = smart_search(qn, limit=5, deadline=deadline)
            if not results and _left(deadline) > 8.0:
                time.sleep(0.6)
                results, tq = smart_search(qn, limit=5, deadline=deadline)
            colors = (tq or {}).get("colors") or []
            # v8.0.1 SUBJECT ORPHAN GATE: the coffee81 live run shipped a
            # Japanese DVD poster as a cafe hero and a random man as a
            # croissant - hygiene tiers say "downloadable photo", but a
            # candidate that never mentions ANY major noun of the query
            # (dict-known tokens, weight >= 2.5, subject included) is a
            # wrong photo, and a wrong photo is WORSE than the clean
            # subject-labelled art placeholder. When the translated query
            # names at least one major noun, orphans are skipped; if
            # nothing anchored survives, the caller falls through to the
            # placeholder path. No major noun known -> gate is off.
            major = {(tq or {}).get("subject") or ""}
            strong = [_tok for _tok, _w in (tq or {}).get("weights") or ()
                      if _w >= 2.5]
            if strong:
                major.update(strong)
            else:
                # v8.0.1: NO dict-known noun in the whole query ('butter
                # croissant bakery' on the Persian-centric dict) - the
                # single subject is then a guess and a real croissant
                # photo failed the gate while bing junk passed it. Gate
                # on EVERY content word instead: any of them in a
                # candidate is honest evidence of relatedness.
                major.update(_tok for _tok, _w in
                             (tq or {}).get("weights") or ())
            major_stems = set()
            for _m in major:
                if _m:
                    major_stems |= _stem_set(_m)
            missed = None            # first subject-match WITHOUT the color
            ai_rej = 0               # v8.1: photos the AI said NO to
            # v8.1 LAYER 2: the verification query - ENGLISH first (the
            # reviewer brain reads it best) with the original attached.
            vq = (tq or {}).get("en") or qn
            if qn and qn != vq:
                vq = f"{vq} (original: {qn})"
            for r in results:
                if _svg_bad(r):
                    continue                 # a logo is not a photo
                if major_stems:
                    try:
                        _tt, _ut = _cand_tokens(r)
                    except Exception:
                        _tt, _ut = set(), set()
                    if not (major_stems & _tt or major_stems & _ut):
                        continue             # subject orphan - junk risk
                for url in (r.get("url"), r.get("thumb")):
                    if not url or _left(deadline) <= 1.0:
                        continue
                    ext, raw, meta = _fetch_image(url, deadline=deadline)
                    if not ext:
                        continue
                    if ext == "svg":
                        continue             # searched svg = logo/clip-art
                    nraw, next_ext, dims = normalize_for_page(raw, ext, ratio)
                    if nraw is None:
                        continue             # known-tiny - try the next one
                    if colors and not _passes_color(nraw, next_ext, colors):
                        # subject matched but the color is absent - keep
                        # the best such candidate as the soft fallback
                        if missed is None:
                            missed = (r, url, nraw, next_ext, dims)
                        continue
                    ok_v, vtail = _ai_verify_ok(vq, nraw, deadline)
                    if not ok_v:
                        ai_rej += 1          # the AI's final NO - next one
                        continue
                    href, dims, tail = _store(r, url, nraw, next_ext, dims)
                    if vtail:
                        tail += f", {vtail}"
                    return href, dims, tail
            if missed is not None:
                # v7.6 soft gate: a color-imperfect PHOTO still beats a
                # placeholder (never emptier than v7.5) - but v8.1: the
                # AI still gets the final say on the softened pick too
                r, url, raw, ext, dims = missed
                ok_v, vtail = _ai_verify_ok(vq, raw, deadline)
                if ok_v:
                    href, dims, tail = _store(r, url, raw, ext, dims)
                    if vtail:
                        tail += f", {vtail}"
                    return href, dims, tail + " (color softened)"
                ai_rej += 1
            if ai_rej:
                return None, None, f"ai-rejected {ai_rej} candidate(s)"
            return None, None, ("no result" if results
                                else "search failed/offline")

        def _placeholder(query, page_dir):
            """Local art fallback -> (href, extra written)."""
            svg = placeholder_svg(query or "image")
            name = f"_ph-{slug(query or 'image')}-" \
                   f"{hashlib.md5(svg.encode('utf-8')).hexdigest()[:8]}.svg"
            rel = _asset_rel(name)
            dest = assets_dir / name
            if dest.is_file():
                return _rel_href(page_dir, name), None   # idempotent
            try:
                assets_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _atomic_write_bytes(dest, svg.encode("utf-8"))
            extras.append((rel, svg.encode("utf-8")))
            extra_rels.add(rel)
            return _rel_href(page_dir, name), None

        for name in htmls:
            try:
                page = ws / name
                # v7.2 audit fix: containment - the function is public API;
                # a hostile name used to be able to read/rewrite a file
                # OUTSIDE the workspace (ws_r was computed but unused).
                try:
                    page.resolve().relative_to(ws_r)
                except ValueError:
                    notes.append(f"{name}: outside the workspace - skipped")
                    continue
                if not page.is_file() or page.stat().st_size > 3_000_000:
                    continue
                # v7.2 audit fix: strict UTF-8 - a latin-1 page used to be
                # read with errors="replace" and RE-WRITTEN with U+FFFD
                # loss whenever any img inside it was filled. Non-UTF-8
                # pages are now left untouched instead of corrupted.
                try:
                    raw = page.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                tags = _IMG_TAG_RE.findall(raw)
                # v8.0.1 zero-img safety net: a COMPLETE page (doctype or
                # a closing </html>) that ships without a single <img>
                # is a broken landing page (coffe8_after shipped 4
                # products and zero photos). Inject one hero slot BEFORE
                # the fill sub so the injected IMG: goes through the
                # normal pipeline. Snippets/partials stay untouched.
                doc = raw.lower()
                if not tags and "<img" not in doc \
                        and "<body" in doc \
                        and ("<!doctype" in doc or "</html>" in doc) \
                        and _left(deadline) > 1.0:
                    hq = _hero_query(raw)
                    if hq:
                        htag = ('<img src="IMG:%s" alt="%s" '
                                'width="1200" height="800">' % (
                                    hq.replace('"', ""),
                                    (_page_title(raw) or hq)
                                    .replace('"', "")))
                        injected = _inject_hero(raw, htag)
                        if injected != raw:
                            raw = injected
                            tags = _IMG_TAG_RE.findall(raw)
                            notes.append(
                                "[img] %s: page ships without a single "
                                "<img> - hero slot injected ('%s')"
                                % (name, hq[:50]))
                if not tags:
                    continue
                page_dir = page.parent.resolve()
                stats = {"net": 0, "remote": 0, "cache": 0, "ph": 0}
                changed = [False]

                def _sub(m, page_dir=page_dir, stats=stats, name=name):
                    tag = m.group(0)
                    if len(tag) > 8000:
                        return tag
                    src, _sp = _attr(tag, "src")
                    alt, _ap = _attr(tag, "alt")
                    alt_v = alt if alt is not None else ""
                    kind, query = _classify(tag, src, alt_v, ws, page_dir)
                    if kind == "leave":
                        return tag
                    # v7.4: the ratio the model declared on THIS tag
                    # decides the crop; the bucket keeps cache keys
                    # apart so a square slot never reuses a 3:2 file.
                    ratio = _tag_ratio(tag)
                    bucket = _ratio_bucket(ratio)
                    qkey = f"q{bucket}:{_norm_query(query)}" if query \
                        else None
                    new_src = None
                    new_dims = None
                    if qkey and kind in ("protocol", "broken", "remote"):
                        hit = _live_hit(qkey)
                        if hit:
                            new_src = _rel_href(page_dir, Path(hit).name)
                            new_dims = _hit_dims(qkey)
                            stats["cache"] += 1
                            notes.append(
                                f"[img] '{query[:50]}' <- {new_src} (cache)")
                    if new_src is None and kind == "remote":
                        rurl = src.strip()
                        if rurl.startswith("//"):
                            rurl = "https:" + rurl   # protocol-relative
                        ukey = "u" + bucket + ":" + _strip_url_parts(rurl)
                        uhit = _live_hit(ukey)
                        if uhit:
                            new_src = _rel_href(page_dir, Path(uhit).name)
                            new_dims = _hit_dims(ukey)
                            stats["cache"] += 1
                            notes.append(f"[img] remote pinned from cache: "
                                         f"{new_src}")
                        elif _cache_get(cache, ukey) == "gone":
                            # v7.2 audit fix: negative cache - a 404 URL is
                            # known dead; go straight to the alt-refill
                            # instead of re-paying the download timeout on
                            # every later apply.
                            kind = "broken"
                    if new_src is None and kind == "remote":
                        if stats["remote"] >= MAX_REMOTE_TRIES_PER_PAGE:
                            return tag              # budget out - leave URL
                        stats["remote"] += 1
                        saved, meta = None, {}
                        tiny = False
                        if _left(deadline) > 1.0 and _ns_mod:
                            ext, rbytes, meta = _fetch_image(
                                rurl, deadline=deadline)
                            if ext:
                                # v7.4: a JPEG the model pointed at is a
                                # photo - give it the same consistency
                                # pass; png/webp/gif/svg graphics stay as
                                # the model chose them.
                                rdims = None
                                if ext == "jpg":
                                    rbytes, ext, rdims = normalize_for_page(
                                        rbytes, ext, ratio)
                                    if rbytes is None:
                                        # v7.4 audit fix: a known-tiny
                                        # remote jpeg used to crash the
                                        # whole page fill (None bytes)
                                        tiny = True
                                if not tiny:
                                    fname = image_name(
                                        _strip_url_parts(rurl),
                                        f"{query or 'img'} {bucket}", ext)
                                    rel = _asset_rel(fname)
                                    try:
                                        assets_dir.mkdir(parents=True,
                                                         exist_ok=True)
                                    except OSError:
                                        pass
                                    dest = assets_dir / fname
                                    if dest.is_file():
                                        # v7.4 audit fix: the file already
                                        # exists (earlier turn / /img) -
                                        # keep it, just reference it (an
                                        # overwrite made /undo delete the
                                        # user's own asset)
                                        saved = fname
                                        new_dims = rdims
                                    else:
                                        _atomic_write_bytes(dest, rbytes)
                                        saved = fname
                                        if rel not in extra_rels:
                                            extras.append((rel, rbytes))
                                            extra_rels.add(rel)
                                        new_dims = rdims
                        if saved:
                            rel = _save("u" + bucket + ":"
                                        + _strip_url_parts(rurl),
                                        _asset_rel(saved), new_dims)
                            new_src = _rel_href(page_dir, saved)
                            notes.append(f"[img] remote photo pinned local: "
                                         f"{new_src}")
                        else:
                            code = meta.get("code")
                            if tiny or code in (404, 410):
                                kind = "broken"     # dead/tiny - refill below
                                if code in (404, 410):
                                    _save("u" + bucket + ":"
                                          + _strip_url_parts(rurl), "gone")
                            else:
                                return tag          # hotlink-protected etc.
                    if new_src is None and kind in ("protocol", "broken"):
                        query = (query or "").strip() or "image"
                        if stats["net"] >= MAX_FILLS_PER_PAGE \
                                or _left(deadline) <= 1.0:
                            new_src, _e = _placeholder(query, page_dir)
                            stats["ph"] += 1
                            notes.append(f"[img] '{query[:50]}' -> local "
                                         "art placeholder (budget/offline)")
                        else:
                            stats["net"] += 1
                            href, dims, tail = _get_photo(
                                query, page_dir, ratio, bucket)
                            if href:
                                new_src = href
                                new_dims = dims
                                notes.append(f"[img] '{query[:50]}' <- "
                                             f"{href} ({tail})")
                            else:
                                new_src, _e = _placeholder(query, page_dir)
                                stats["ph"] += 1
                                notes.append(f"[img] '{query[:50]}' -> local "
                                             f"art placeholder ({tail})")
                    if new_src is None:
                        return tag
                    changed[0] = True
                    return _rewrite_tag(tag, new_src, new_dims)

                new_text = _IMG_TAG_RE.sub(_sub, raw)
                if changed[0]:
                    # v7.4: pages WITHOUT a WORKING design floor get the
                    # tiny zero-specificity img rule (no overflow, no
                    # squash) - the marker alone lied on legacy nested
                    # pages whose nova-ui.css link 404'd
                    if not _has_working_floor_css(page, new_text):
                        new_text = _ensure_img_floor_css(new_text)
                    _atomic_write_text(page, new_text)
            except Exception as e:            # one bad page never stops the rest
                notes.append(f"{name}: image fill skipped "
                             f"({type(e).__name__})")

        # v8.0.1: JS card grids - a renderer that builds cards with
        # document.createElement never puts an <img> tag in the HTML, so
        # the pass above had nothing to fill (coffe8_after). When the
        # model keeps an IMG: literal in its data array ("img: 'IMG:
        # espresso cup'"), string-replace it with the downloaded asset.
        # Browsers resolve the URL against the PAGE (script scope), so
        # hrefs stay workspace-root relative - pages live at the root.
        js_net = 0
        for name in jss:
            if _left(deadline) <= 1.0:
                break
            try:
                p = ws / name
                try:
                    p.resolve().relative_to(ws_r)
                except ValueError:
                    notes.append(f"{name}: outside the workspace - skipped")
                    continue
                if not p.is_file() or p.stat().st_size > 1_000_000:
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if "IMG:" not in text:
                    continue

                def _js_sub(m):
                    nonlocal js_net
                    query = m.group(2).strip()
                    qn = _norm_query(query)
                    if not qn:
                        return m.group(0)
                    qkey = f"ql:{qn}"
                    hit = _live_hit(qkey)
                    if hit:
                        href = _rel_href(ws_r, Path(hit).name)
                    elif js_net < MAX_FILLS_PER_PAGE \
                            and _left(deadline) > 1.0:
                        js_net += 1
                        href, _d, _t = _get_photo(qn, ws_r, None, "l")
                        if not href:
                            return m.group(0)   # offline - keep the literal
                    else:
                        return m.group(0)       # budget out - keep literal
                    notes.append(f"[img] js '{qn[:50]}' <- {href}")
                    return m.group(1) + href + m.group(1)

                new_text = _JS_IMG_RE.sub(_js_sub, text)
                if new_text != text:
                    _atomic_write_text(p, new_text)
            except Exception as e:           # one bad js never stops the rest
                notes.append(f"{name}: js image fill skipped "
                             f"({type(e).__name__})")

        if cache_dirty:
            _save_cache(ws, cache)
    except Exception as e:
        notes.append(f"image fill skipped ({type(e).__name__})")
    return extras, notes


# --------------------------------------------------------------- tools API
def pick_and_save(query, ws, deadline=None):
    """Search + download the best real photo for a query into the
    workspace assets. Returns (rel, source, meta); rel=None when nothing
    usable was found. Used by the [IMG: ...] model token and /img.
    v7.4: the photo goes through normalize_for_page (watermark-free
    candidates + EXIF + 3:2 crop + size cap), like every page photo.
    v7.6: smart_search (Persian->English ladder + relevance ranking)
    picks the candidates and the color words are verified in the pixels
    (soft gate - the best color-imperfect candidate is still used when
    nothing better exists)."""
    ws = Path(ws)
    query = _norm_query(query)
    if not query:
        return None, "", {"error": "empty query"}
    # v8.6 SELECTION GATE: the local-vision approval layer may refuse
    # the whole search before a single request leaves the machine.
    ok_g, gnote = _ai_gate_ok(query)
    if not ok_g:
        return None, "", {"ai_gate": gnote}
    if deadline is None:
        deadline = time.monotonic() + 40
    cache = _load_cache(ws)
    qkey = "ql:" + query
    hit = _cache_get(cache, qkey)
    if hit and (ws / hit).is_file():
        return hit, "cache", {}
    assets_dir = ws.joinpath(*ASSETS_DIR)
    results, tq = smart_search(query, limit=5, deadline=deadline)
    colors = (tq or {}).get("colors") or []
    # v8.1 LAYER 2: English-first review string for the verify brain
    vq = (tq or {}).get("en") or query
    if query and query != vq:
        vq = f"{vq} (original: {query})"
    missed = None
    ai_rej = 0
    for r in results:
        if _svg_bad(r):
            continue
        for url in (r.get("url"), r.get("thumb")):
            if not url or _left(deadline) <= 1.0:
                continue
            ext, raw, meta = _fetch_image(url, deadline=deadline)
            if not ext or ext == "svg":
                continue
            raw, ext, dims = normalize_for_page(raw, ext, 1.5)
            if raw is None:
                continue
            if colors and not _passes_color(raw, ext, colors):
                if missed is None:
                    missed = (r, url, raw, ext, dims, meta)
                continue
            ok_v, vtail = _ai_verify_ok(vq, raw, deadline)
            if not ok_v:
                ai_rej += 1               # the AI's final NO - next one
                continue
            rel, src, meta2 = _pick_store(ws, cache, qkey, r, url, raw,
                                          ext, dims, meta, assets_dir,
                                          missed=None,
                                          base=(tq or {}).get("en") or query)
            if rel and vtail:
                meta2["ai"] = vtail
            return rel, src, meta2
    if missed is not None:
        r, url, raw, ext, dims, meta = missed
        ok_v, vtail = _ai_verify_ok(vq, raw, deadline)
        if ok_v:
            rel, src, meta2 = _pick_store(ws, cache, qkey, r, url, raw,
                                          ext, dims, meta, assets_dir,
                                          missed=True,
                                          base=(tq or {}).get("en") or query)
            if rel and vtail:
                meta2["ai"] = vtail
            return rel, src, meta2
        ai_rej += 1
    _save_cache(ws, cache)
    info = {"candidates": len(results)}
    if ai_rej:
        info["ai_rejected"] = ai_rej
    return None, "", info


def _pick_store(ws, cache, qkey, r, url, raw, ext, dims, meta,
                assets_dir, missed, base=""):
    """Write the picked candidate for pick_and_save (asset + caches).
    qkey is 'ql:<normalized original query>' (cache identity); the FILE
    name base is the English query when available (readable assets)."""
    name = image_name(str(url).strip().split("#")[0],
                      f"{base or qkey[3:]} l", ext)
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        _atomic_write_bytes(assets_dir / name, raw)
    except OSError as e:
        meta["error"] = f"cannot write: {e}"
        return None, "", meta
    rel = "/".join(ASSETS_DIR) + "/" + name
    meta["w"] = dims[0] if dims else r.get("width")
    meta["h"] = dims[1] if dims else r.get("height")
    if missed:
        meta["color_softened"] = True
    entry = {"rel": rel, "ts": int(time.time())}
    if meta.get("w") and meta.get("h"):
        entry["w"], entry["h"] = int(meta["w"]), int(meta["h"])
    cache[qkey] = entry
    cache["ul:" + _strip_url_parts(url)] = dict(entry)
    _save_cache(ws, cache)
    return rel, r.get("source", ""), meta


def save_result(result, ws, deadline=None, verify=None):
    """/img: download ONE search-result dict ({url, thumb, ...}) into the
    workspace assets, trying the original URL then the thumbnail.
    v8.6: verify(raw) -> (ok, tail) is the local-AI APPROVAL gate - a
    REJECTED candidate is never written (meta.ai_rejected + reason).
    Returns (rel, meta)."""
    ws = Path(ws)
    result = result or {}
    url = str(result.get("url") or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    base = _norm_query(result.get("title") or "img")
    assets_dir = ws.joinpath(*ASSETS_DIR)
    meta = {}
    for cand in (url, str(result.get("thumb") or "").strip()):
        if not cand:
            continue
        ext, raw, meta = _fetch_image(cand, deadline=deadline
                                      or time.monotonic() + 30)
        if not ext or ext == "svg":
            continue
        raw, ext, dims = normalize_for_page(raw, ext, 1.5)
        if raw is None:
            continue
        if verify is not None:
            try:
                ok_v, vtail = verify(raw)
            except Exception:
                ok_v, vtail = True, "verify-err"
            if not ok_v:
                meta["ai_rejected"] = 1
                meta["ai_reason"] = str(vtail or "rejected")[:120]
                continue
        fname = image_name(_strip_url_parts(cand), f"{base} l", ext)
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(assets_dir / fname, raw)
        except OSError as e:
            meta["error"] = f"cannot write: {e}"
            continue
        rel = "/".join(ASSETS_DIR) + "/" + fname
        cache = _load_cache(ws)
        cache["ul:" + _strip_url_parts(cand)] = {
            "rel": rel, "ts": int(time.time())}
        _save_cache(ws, cache)
        meta["w"] = dims[0] if dims else result.get("width")
        meta["h"] = dims[1] if dims else result.get("height")
        if verify is not None and not meta.get("ai_rejected"):
            meta.setdefault("ai", "approved")
        return rel, meta
    if meta.get("ai_rejected"):
        return None, meta
    return None, meta or {"error": "no url in result"}


def save_from_url(url, ws, name=None, verify=None):
    """/imgdl: download ONE url into the workspace assets. v8.6: verify
    (raw) -> (ok, tail) is the local-AI APPROVAL gate - a rejected
    download is never written to disk. Returns (rel, meta).
    Protocol-relative urls are normalized to https."""
    ws = Path(ws)
    url = str(url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    base = slug(name) if name else slug(
        re.sub(r"^[a-z]+://[^/]+/", "", url) or "img")
    assets_dir = ws.joinpath(*ASSETS_DIR)
    ext, raw, meta = _fetch_image(url, deadline=time.monotonic() + 30)
    if not ext:
        return None, meta or {"error": "download failed"}
    if verify is not None:
        try:
            ok_v, vtail = verify(raw)
        except Exception:
            ok_v, vtail = True, "verify-err"
        if not ok_v:
            meta["ai_rejected"] = 1
            meta["ai_reason"] = str(vtail or "rejected")[:120]
            return None, meta
    url_clean = str(url).strip()
    fname = image_name(url_clean, base, ext)
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(assets_dir / fname, raw)
    except OSError as e:
        meta["error"] = f"cannot write: {e}"
        return None, meta
    cache = _load_cache(ws)
    rel = "/".join(ASSETS_DIR) + "/" + fname
    # v7.4 audit fix: the fill pass reads u<bucket>: keys (bucket 'l' for
    # ratio-less queries) - the bare 'u:' entry was never re-readable
    cache["ul:" + _strip_url_parts(url)] = {
        "rel": rel, "ts": int(time.time())}
    _save_cache(ws, cache)
    return rel, meta
