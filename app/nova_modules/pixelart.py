#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - Nova PixelArt (v6.0)
#
#  A FULLY OFFLINE pixel-art engine. No model, no server, no network:
#  a prompt is parsed (subject / palette / size / symmetry), a seeded
#  RNG drives classic procedural-sprite techniques (mirrored blobs,
#  banded scenes, structured shapes), an outline+light pass finishes
#  the frame, and the grid is written as BOTH a real PNG (nova_png)
#  and a small JSON (for lossless upscaling / re-rendering later).
#
#  This is the engine that makes "creative" work on a machine with no
#  GPU and no downloads - and the deterministic core that the QA suite
#  can assert on: same prompt + seed => byte-identical PNG.
# =====================================================================
import hashlib
import json
import random
import time

import nova_png
from nova_modules import ModuleError, module_data_dir

MAX_DIM = 128
SAVED_GRIDS = 400          # gallery cap for the grid JSONs

PALETTES = {
    "pico8":   ["#1d2b53", "#7e2553", "#008751", "#ab5236", "#5f574f",
                "#c2c3c7", "#fff1e8", "#ff004d", "#ffa300", "#ffec27",
                "#00e436", "#29adff", "#83769c", "#ff77a8", "#ffccaa"],
    "gameboy": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
    "nes":     ["#000000", "#fcfcfc", "#f8f8f8", "#bcbcbc", "#7c7c7c",
                "#a4e4fc", "#3cbcfc", "#0078f8", "#0000fc", "#b8b8f8",
                "#6888fc", "#d8b8f8", "#f878f8", "#f8b8f8", "#f8a4c0",
                "#f87858", "#fca044", "#f8d878", "#b8f818", "#58d854",
                "#00a800", "#008888", "#503000"],
    "cga":     ["#000000", "#55ffff", "#ff5555", "#ffffff",
                "#0000aa", "#55ff55", "#ff55ff", "#ffff55",
                "#aaaaaa", "#00aaaa", "#aa00aa", "#aaaa55"],
    "mono":    ["#0d1020", "#262c4d", "#838ebb", "#e9ecf8"],
    "sunset":  ["#2b1055", "#4b1d6e", "#8a2c6d", "#d4547a", "#ff9760",
                "#ffd07b", "#ffe9a8"],
    "ocean":   ["#02111f", "#05355e", "#0a6291", "#2a97c2", "#6fc7de",
                "#b8ecf2", "#eafcf6"],
    "fire":    ["#1a0500", "#4d1200", "#8c2500", "#c94000", "#f26d13",
                "#ffa63f", "#ffe08a"],
}

# prompt keyword -> generator + palette hint. Ordered: first hit wins.
# (v8.0: the stray "minute" that force-selected 'creature' is gone -
# a time-related prompt like "5 minute sketch" used to pick the wrong
# sprite generator.)
SUBJECTS = [
    (("cat", "kitty", "گربه", "creature"), "creature", None),
    (("ship", "spaceship", "invader", "aliens", "سفینه"), "ship", None),
    (("rocket", "launch", "موشک"), "rocket", None),
    (("castle", "tower", "دژ", "قلعه"), "castle", None),
    (("tree", "forest", "jungle", "درخت", "جنگل"), "tree", None),
    (("sunset", "landscape", "mountain", "sky", "island", "منظره", "کوه"),
     "scene", "sunset"),
    (("ocean", "sea", "wave", "دریا"), "scene", "ocean"),
    (("fire", "lava", "volcano", "آتش"), "scene", "fire"),
    (("sprite", "blob", "monster", " invader", "اسپرایت"), "sprite", None),
    (("portrait", "face", "avatar", "چهره"), "face", None),
]

GOLD = "#ffc857"
VOID = "#0d1020"


# --------------------------------------------------------------- prompt parsing
def parse_prompt(prompt, size=None, palette=None, symmetry=None):
    """Free text -> structured plan: {subject, size, palette, symmetry,
    hints}. Deterministic, never raises."""
    text = " ".join(str(prompt or "").lower().split())
    subject, pal_hint = "sprite", None
    for keys, subj, pal in SUBJECTS:
        if any(k in text for k in keys):
            subject, pal_hint = subj, pal
            break
    # explicit palette name beats the subject hint
    chosen = pal_hint or ""
    for name in PALETTES:
        if name in text:
            chosen = name
            break
    if palette and palette in PALETTES:
        chosen = palette
    if not chosen:
        chosen = "pico8"
    # size: explicit arg > "16x16"-style mention > keyword > default 32
    dim = 32
    if isinstance(size, int) and 8 <= size <= MAX_DIM:
        dim = size
    else:
        import re
        m = re.search(r"\b(\d{1,3})\s*[x×]\s*(\d{1,3})\b", text)
        if m and 8 <= int(m.group(1)) <= MAX_DIM:
            dim = int(m.group(1))
        elif "tiny" in text or "8x8" in text:
            dim = 16
    sym = symmetry if symmetry in ("h", "v", "none") else ("h" if subject in
                                                           ("sprite", "ship", "creature", "face") else "none")
    return {"subject": subject, "size": dim, "palette": chosen,
            "symmetry": sym, "prompt": text[:400]}


def hex2rgb(h):
    h = (h or "#000000").lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def _seed_from(prompt, seed):
    material = str(seed if seed not in (None, "") else prompt)
    return hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------- generators
# A grid is a list of rows; every cell is a palette INDEX (int) or -1
# for transparent. All generators are pure: (grid, rng) -> grid.
def _blank(n, bg=-1):
    return [[bg] * n for _ in range(n)]


def _mirror_h(grid, n):
    for y in range(n):
        for x in range(n // 2):
            grid[y][n - 1 - x] = grid[y][x]
    return grid


def _blob(grid, n, rng, colors, fill=0.52, margin=1):
    """Classic invader: random cells on the left half, then mirror."""
    half = n // 2
    for y in range(margin, n - margin):
        for x in range(margin, half):
            if rng.random() < fill:
                grid[y][x] = rng.choice(colors)
    _mirror_h(grid, n)
    return grid


def _rect(g, x0, y0, x1, y1, c):
    for y in range(max(0, y0), min(len(g), y1)):
        for x in range(max(0, x0), min(len(g[0]), x1)):
            g[y][x] = c
    return g


def _px(g, x, y, c):
    if 0 <= y < len(g) and 0 <= x < len(g[0]):
        g[y][x] = c
    return g


def gen_sprite(n, rng, pal, subject):
    g = _blank(n)
    if subject == "face":
        # head block + mirrored eyes/mouth on the lower half
        skin = rng.randrange(len(pal))
        _rect(g, n // 4, n // 4, 3 * n // 4, 3 * n // 4, skin)
        _mirror_h(g, n)
        eye = (skin + 3) % len(pal)
        for ex in (n // 3, n // 3 + 1, 2 * n // 3 - 1, 2 * n // 3 - 2):
            _px(g, ex, n // 2, eye)
        mouth_c = (skin + 5) % len(pal)
        for x in range(2 * n // 5, 3 * n // 5):
            if rng.random() < 0.8:
                _px(g, x, 2 * n // 3, mouth_c)
        return g
    body = [rng.randrange(len(pal)) for _ in range(3)]
    _blob(g, n, rng, body, fill=0.55 if subject != "ship" else 0.42)
    if subject == "ship":
        # cockpit + wings: carve a bright core, extend wing tips
        core = rng.randrange(len(pal))
        _rect(g, n // 2 - 1, n // 3, n // 2 + 1, n // 3 + 2, core)
        tip = (core + 2) % len(pal)
        for y in range(n // 2, n - 2):
            _px(g, 1 + (y % 2), y, tip)
            _px(g, n - 2 - (y % 2), y, tip)
    elif subject == "creature":
        # legs + eye band
        leg = (body[0] + 2) % len(pal)
        for x in (n // 4, n // 2 - 1, n // 2, 3 * n // 4 - 1):
            _px(g, x, n - 1, leg)
        eye = (body[-1] + 4) % len(pal)
        for x in range(n // 3, n // 3 + 2):
            _px(g, x, n // 3, eye)
            _px(g, n - 1 - x, n // 3, eye)
    return g


def gen_scene(n, rng, pal, subject=None):
    g = _blank(n)
    bands = len(pal)
    horizon = n // 2 + rng.randrange(max(1, n // 6)) - n // 12
    # sky: banded gradient from the palette's dark end
    for y in range(horizon):
        c = int(bands * y / max(1, horizon))
        _rect(g, 0, y, n, y + 1, min(c, bands - 1))
    # sun / moon with a halo pixel
    sun_c = bands - 1
    sx = rng.randrange(n // 4, 3 * n // 4)
    sy = max(1, horizon // 3)
    r = max(2, n // 10)
    for y in range(sy - r, sy + r + 1):
        for x in range(sx - r, sx + r + 1):
            if (x - sx) ** 2 + (y - sy) ** 2 <= r * r:
                _px(g, x, y, sun_c)
    # mountains: midpoint-ish jagged ridge
    ridge = (bands + 0) % bands
    h = horizon - max(2, n // 8)
    x = 0
    while x < n:
        w = rng.randrange(max(2, n // 8), max(3, n // 4))
        peak = h + rng.randrange(0, max(2, n // 6))
        for dx in range(w):
            xx = x + dx
            if xx >= n:
                break
            fall = abs(dx - w // 2)
            for y in range(max(0, peak + fall // 2), horizon):
                _px(g, xx, y, ridge)
        x += w
    # ground band + trees / cacti silhouettes
    ground = (bands - 2) % bands
    _rect(g, 0, horizon, n, n, ground)
    dark = (ground - 1) % bands
    trees = rng.randrange(1, max(2, n // 12))
    for _ in range(trees):
        tx = rng.randrange(1, n - 1)
        th = rng.randrange(2, max(3, n // 6))
        for ty in range(horizon - th, horizon):
            _px(g, tx, ty, dark)
        _px(g, tx - 1, horizon - th // 2, dark)
        _px(g, tx + 1, horizon - th // 2, dark)
    return g


def gen_castle(n, rng, pal, subject=None):
    g = _blank(n)
    stone = rng.randrange(len(pal))
    dark = (stone + 1) % len(pal)
    bw = n // 2
    bx = n // 4
    by = n // 3
    _rect(g, bx, by, bx + bw, n, stone)                 # keep
    _rect(g, bx, n - n // 6, bx + bw, n, dark)          # base shadow band
    for tx in range(bx, bx + bw, max(2, n // 8)):       # battlements
        _rect(g, tx, by - max(1, n // 12), tx + max(1, n // 12), by, stone)
    door_w = max(1, n // 8)
    _rect(g, n // 2 - door_w // 2, n - n // 4, n // 2 + door_w // 2 + 1, n,
          (dark + 2) % len(pal))                        # door
    for wy in range(by + n // 6, n - n // 6, max(2, n // 6)):
        for wx in range(bx + n // 8, bx + bw - n // 8, max(3, n // 5)):
            _px(g, wx, wy, len(pal) - 1 if len(pal) > 8 else dark)   # lit windows
    return g


def gen_rocket(n, rng, pal, subject=None):
    g = _blank(n)
    body = rng.randrange(len(pal))
    flame = (body + 4) % len(pal)
    gold_i = len(pal) - 1                    # brightest shade as the accent
    cx = n // 2
    top = n // 8
    body_h = n // 2
    for y in range(top, top + body_h):
        t = (y - top) / max(1, body_h - 1)
        half = max(1, int((1 - abs(t - 0.35) * 1.2) * n // 6))
        for x in range(cx - half, cx + half + 1):
            _px(g, x, y, body)
    _px(g, cx, top, gold_i)                              # nose light
    _rect(g, cx - 1, top + body_h // 2, cx + 2, top + body_h // 2 + 2, flame)
    for y in range(top + body_h, n):                     # exhaust plume
        spread = (y - top - body_h) // 2 + 1
        for x in range(cx - spread, cx + spread + 1):
            if rng.random() < 0.75:
                _px(g, x, y, flame if rng.random() < 0.7 else gold_i)
    return g


def gen_tree(n, rng, pal, subject=None):
    g = _blank(n)
    leaf = rng.randrange(len(pal))
    trunk = (leaf + 2) % len(pal)
    cx = n // 2
    base = n - n // 8
    # canopy: stacked shrinking discs
    r = n // 3
    for dy in range(-r, r + 1, 2):
        width = int((r * r - dy * dy) ** 0.5) or 1
        _rect(g, cx - width, base - r + dy + r // 2, cx + width + 1,
              base - r + dy + r // 2 + 1, leaf)
    _rect(g, cx - n // 12, base - n // 4, cx + n // 12 + 1, base, trunk)
    _rect(g, 0, base, n, n, (trunk + 1) % len(pal))       # ground line
    for _ in range(n // 6):                               # sparkle leaves
        _px(g, rng.randrange(n // 4, 3 * n // 4), rng.randrange(n // 6, base - n // 4),
            (leaf + 3) % len(pal))
    return g


def gen_abstract(n, rng, pal, subject=None):
    g = _blank(n)
    for y in range(n):
        for x in range(n):
            v = (x * x + y * y + rng.randrange(3)) % len(pal)
            g[y][x] = v
    for _ in range(n // 4):                                # marching squares
        cx, cy = rng.randrange(n), rng.randrange(n)
        c = rng.randrange(len(pal))
        for _ in range(n):
            _px(g, cx, cy, c)
            cx = (cx + rng.choice((-1, 0, 1))) % n
            cy = (cy + rng.choice((-1, 0, 1))) % n
    return g


GENERATORS = {"sprite": gen_sprite, "ship": gen_sprite, "creature": gen_sprite,
              "face": gen_sprite, "scene": gen_scene, "castle": gen_castle,
              "rocket": gen_rocket, "tree": gen_tree, "abstract": gen_abstract}


# --------------------------------------------------------------- finish pass
def _outline_and_light(grid, n, pal):
    """1px dark outline + a top-light pass. Returns a new grid; palette
    indices only (palette[-1] is reserved as the outline shade)."""
    import copy
    g = copy.deepcopy(grid)
    # extend palette with outline/shadow colors at render time:
    # cell value OUTLINE (-2) draws as near-black.
    for y in range(n):
        for x in range(n):
            if g[y][x] == -1:
                # transparent cell that touches ink -> outline
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < n and 0 <= ny < n and g[ny][nx] not in (-1,):
                        g[y][x] = -2
                        break
    return g


def _render_rows(grid, pal_rgb, scale):
    n = len(grid)
    out = []
    void = hex2rgb(VOID)
    # build one scanline at a time (y-major) - memory-friendly
    # v6.2.1: removed the dead pre-loop that indexed pal_rgb[grid[0][gx]]
    # WITHOUT bounds checking - a hand-edited grid JSON with a huge first
    # cell crashed the render, while the main loop below is guarded
    for y in range(n):
        row = bytearray(b"\x00")
        for x in range(n):
            v = grid[y][x]
            if v == -2:
                col = (10, 8, 20)                    # outline ink
            elif isinstance(v, int) and 0 <= v < len(pal_rgb):
                col = pal_rgb[v]
            else:
                col = void                            # transparent / junk -> void
            row += bytes(col) * scale
        out_row = bytes(row)
        out.extend([out_row] * scale)                # square pixels
    return out


def generate(ws, prompt, size=None, palette=None, symmetry=None,
             seed=None, scale=8, save=True):
    """Prompt -> {path, png_bytes_len, grid, plan, name}. Deterministic:
    same (prompt, seed) => same output. Raises ModuleError only for
    genuinely unusable parameters."""
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ModuleError("empty prompt")
    if size is not None and not isinstance(size, int):
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = None
    plan = parse_prompt(prompt, size=size, palette=palette, symmetry=symmetry)
    n = plan["size"]
    # an EXPLICIT bad size is a caller bug -> raise; a size parsed out of
    # free text was already clamped by parse_prompt
    if size is not None and not 8 <= size <= MAX_DIM:
        raise ModuleError("size must be 8-%d" % MAX_DIM)
    if not 8 <= n <= MAX_DIM:
        raise ModuleError("size must be 8-%d" % MAX_DIM)
    if not isinstance(scale, int) or not 1 <= scale <= 16:
        scale = 8
    seedhex = _seed_from(plan["prompt"], seed)
    rng = random.Random(seedhex)
    pal = PALETTES[plan["palette"]]
    fn = GENERATORS.get(plan["subject"], gen_sprite)
    grid = fn(n, rng, pal, plan["subject"])
    grid = _outline_and_light(grid, n, pal)
    pal_rgb = [hex2rgb(c) for c in pal]
    rows = _render_rows(grid, pal_rgb, scale)
    png = nova_png.encode_png(n * scale, n * scale, rows, alpha=False)
    result = {"name": "", "path": "", "plan": plan, "seed": seedhex[:12],
              "size": n, "scale": scale, "bytes": len(png), "png": png,
              "grid": grid, "palette": plan["palette"]}
    if save:
        base = module_data_dir(ws, "pixel")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = "pixel-%s-%s.png" % (stamp, seedhex[:6])
        path = base / name
        # v6.7: atomic write via unique .part + replace - a crash mid-write
        # used to publish a truncated pixel-*.png that the gallery listed
        # and the upsloader choked on.
        tmp = path.with_suffix(".png.part")
        nova_png.write_png(str(tmp), n * scale, n * scale, rows, alpha=False)
        tmp.replace(path)
        # grid JSON: lossless re-render / upscale source
        # v6.7: prune loops (one call used to delete exactly ONE file per
        # generation - a burst of N overshoots the cap by N-1) and the
        # prune now covers orphaned .part files.
        _prune_gallery(base, SAVED_GRIDS)
        tmp_j = (base / (name[:-4] + ".json")).with_suffix(".json.part")
        tmp_j.write_text(json.dumps({
            "prompt": plan["prompt"], "grid": grid, "palette": plan["palette"],
            "size": n, "seed": result["seed"],
        }, ensure_ascii=False), encoding="utf-8")
        tmp_j.replace(base / (name[:-4] + ".json"))
        result["name"] = name
        result["path"] = str(path)
        del result["png"]                     # keep the dict JSON-safe
    return result


def _prune_gallery(base, cap):
    """Keep the pixel gallery bounded. v6.7: the old code deleted exactly
    ONE file per call (a burst of N generations overshot the cap by N-1),
    never touched orphaned .part files, and the JSON prune missed them
    too. Oldest-first, loops to the cap, sweeps .part orphans >1h."""
    import time as _t
    now = _t.time()
    for pattern in ("pixel-*.png", "pixel-*.json"):
        files = sorted(base.glob(pattern))
        i = 0
        while len(files) - i >= cap and i < len(files):
            try:
                files[i].unlink()
            except OSError:
                pass
            i += 1
    try:
        for f in base.glob("*.part"):
            if now - f.stat().st_mtime > 3600:
                f.unlink()
    except OSError:
        pass


def render_from_grid(ws, grid_name, scale):
    """Re-render a saved grid at a new scale (the 'upscale' feature -
    nearest-neighbour is EXACT for pixel art). Returns (path, bytes_len)."""
    if not isinstance(scale, int) or not 1 <= scale <= 16:
        raise ModuleError("scale must be 1-16")
    base = module_data_dir(ws, "pixel")
    safe = (str(grid_name or "").strip()
            .replace("/", "_").replace("\\", "_").replace("..", "_"))
    stem = safe
    if stem.endswith(".png"):
        stem = stem[:-4]
    if stem.endswith(".json"):
        stem = stem[:-5]
    src = base / (stem + ".json")
    if not src.is_file():
        raise ModuleError("grid file not found: %s" % src.name)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        raise ModuleError("corrupt grid file")
    grid, pal_name = data.get("grid"), data.get("palette", "pico8")
    n = len(grid)
    if (not isinstance(grid, list) or not n or n > MAX_DIM
            or any(not isinstance(r, list) or len(r) != n for r in grid)):
        raise ModuleError("corrupt grid shape")
    pal = PALETTES.get(pal_name, PALETTES["pico8"])
    pal_rgb = [hex2rgb(c) for c in pal]
    rows = _render_rows(grid, pal_rgb, scale)
    out_name = src.stem + "-x%d.png" % scale
    out = base / out_name
    nova_png.write_png(str(out), n * scale, n * scale, rows, alpha=False)
    try:
        size = out.stat().st_size
    except OSError:
        size = 0
    return str(out), size


def list_gallery(ws, cap=60):
    """Saved pixel artworks: PNG name + mtime + dims (newest first)."""
    import nova_png as _np
    base = module_data_dir(ws, "pixel", create=False)
    if not base.is_dir():
        return []
    out = []
    for f in base.glob("pixel-*.png"):
        meta = _np.read_png_meta(str(f)) or {}
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        out.append({"name": f.name, "mtime": mt,
                    "width": meta.get("width", 0),
                    "height": meta.get("height", 0)})
    out.sort(key=lambda e: -e["mtime"])
    return out[:cap]
