#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - pure-Python PNG writer (v6.0)
#
#  The creative modules (Nova Pixel, Nova Photo offline engine, the
#  PWA icon factory) all need to emit real .png files WITHOUT a single
#  dependency. This is that writer: zlib + struct, filter type 0 per
#  scanline, RGB or RGBA, every check explicit.
#
#  Pure standard library. No network, no prints - a broken input is a
#  ValueError, never a half-written file (write_png is atomic-ish:
#  bytes are fully built before the file is touched).
# =====================================================================
import os
import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(typ, data):
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))


def _check_rows(rows, width, height, bpp):
    if not isinstance(rows, (list, tuple)) or len(rows) != height:
        raise ValueError("rows must be a sequence of %d scanlines" % height)
    out = []
    for y, row in enumerate(rows):
        if not isinstance(row, (bytes, bytearray)):
            raise ValueError("scanline %d is not bytes" % y)
        # 1 filter byte + bpp * width bytes
        if len(row) != 1 + bpp * width:
            raise ValueError("scanline %d has wrong length (%d != %d)"
                             % (y, len(row), 1 + bpp * width))
        if row[0] != 0:
            raise ValueError("scanline %d must use filter type 0" % y)
        out.append(bytes(row))
    return b"".join(out)


def encode_png(width, height, rows, alpha=False):
    """rows: list of scanlines, each b'\\x00' + width*3(RGB) or *4(RGBA)
    bytes. Returns the complete PNG byte string."""
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("width/height must be ints")
    if width <= 0 or height <= 0 or width > 8192 or height > 8192:
        raise ValueError("unsupported image size %dx%d" % (width, height))
    bpp = 4 if alpha else 3
    raw = _check_rows(rows, width, height, bpp)
    ihdr = struct.pack(">IIBBBBB", width, height, 8,
                       6 if alpha else 2, 0, 0, 0)
    return (_SIGNATURE + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 6))
            + _chunk(b"IEND", b""))


def write_png(path, width, height, rows, alpha=False):
    """Encode + write. Creates parent folders. Returns the byte count."""
    blob = encode_png(width, height, rows, alpha=alpha)
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)          # atomic on POSIX, sane on Windows
    return len(blob)


# --------------------------------------------------------------- builders
def rgb_row(pixels):
    """[ (r,g,b), ... ] -> one filter-0 scanline (RGB)."""
    row = bytearray(b"\x00")
    for p in pixels:
        row += bytes((int(p[0]) & 0xFF, int(p[1]) & 0xFF, int(p[2]) & 0xFF))
    return bytes(row)


def solid_rows(width, height, color):
    """Uniform image rows (RGB tuple) - the trivial case."""
    row = b"\x00" + bytes((color[0], color[1], color[2])) * width
    return [row] * height


def read_png_meta(path):
    """Tiny reader for files WE produced: (width, height, alpha?) or
    None for anything else. Only the IHDR is parsed - good enough for
    gallery listings and just as safe against junk files."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
    except OSError:
        return None
    if len(head) < 26 or head[:8] != _SIGNATURE or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    _depth, ctype = head[24], head[25]
    if ctype not in (2, 6):
        return None
    return {"width": w, "height": h, "alpha": ctype == 6}
