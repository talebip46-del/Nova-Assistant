#!/usr/bin/env python3
# =====================================================================
#  make_icon.py - generate build_assets/NovaAssistant.ico (zero-dep)
#
#  Draws the same pixel "spark" mark used by the web header, scaled to
#  256x256 RGBA, and wraps the PNG in an ICO container (PNG-compressed
#  icons are supported by Windows Vista+). Run once from app/:
#
#      python3 scripts/make_icon.py
#
#  The spec picks the .ico up automatically if the file exists; delete
#  it and re-run this script any time the mark changes.
# =====================================================================
import struct
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import nova_png  # noqa: E402  (our own zero-dep PNG writer)

# --- palette (matches web/index.html CSS vars) ---
def _rgba(c, a=255):
    return bytes((c[0], c[1], c[2], a))

BG     = _rgba((0x0a, 0x0d, 0x1c))
VIOLET = _rgba((0x9b, 0x6b, 0xff))
LILAC  = _rgba((0xc4, 0xa5, 0xff))
GOLD   = _rgba((0xff, 0xc8, 0x57))
WHITE  = _rgba((0xff, 0xff, 0xff))
TRANS  = _rgba((0, 0, 0), 0)

# 16x16 hand-drawn spark: 4-point star + gold core, pixel style.
# (each row is exactly 16 chars; T=transparent V=violet L=lilac G=gold W=white)
PIXELS = """
TTTTTTTTTTTTTTTT
TTTTTTTVVTTTTTTT
TTTTTVVLLVVTTTTT
TTTTVVLLLLVVTTTT
TTTVVLLLLLLVVTTT
TTVVLLGGGGLLVVTT
TVVLLGGWWGGLLVVT
VVLLLGWWWWGLLLVV
VVLLLGWWWWGLLLVV
TVVLLGGWWGGLLVVT
TTVVLLGGGGLLVVTT
TTTVVLLLLLLVVTTT
TTTTVVLLLLVVTTTT
TTTTTVVLLVVTTTTT
TTTTTTTVVTTTTTTT
TTTTTTTTTTTTTTTT
"""

COLORS = {"T": TRANS, "V": VIOLET, "L": LILAC, "G": GOLD, "W": WHITE}


def build_scanlines(scale=16):
    """16x16 grid -> 256x256 RGBA scanlines in nova_png's format."""
    rows = PIXELS.strip("\n").split("\n")
    if len(rows) != 16 or any(len(r) != 16 for r in rows):
        raise ValueError("icon grid must be exactly 16 rows of 16 chars")
    out = []
    for row in rows:
        line = b"".join(COLORS[ch] * scale for ch in row)
        out.extend([b"\x00" + line] * scale)   # filter byte 0 + w*4 bytes
    return out


def write_ico(png_bytes, path):
    """Wrap one PNG (256x256) in a minimal single-image ICO container."""
    hdr = struct.pack("<HHH", 0, 1, 1)                 # reserved, type=icon, 1 image
    entry = struct.pack("<BBBBHHII",
                        0, 0, 0, 0,                    # w, h (0 means 256), colors, reserved
                        1, 32, len(png_bytes), 22)     # planes, bpp, data size, data offset
    path.write_bytes(hdr + entry + png_bytes)


def main():
    out_dir = APP / "build_assets"
    out_dir.mkdir(exist_ok=True)
    ico = out_dir / "NovaAssistant.ico"
    png = nova_png.encode_png(256, 256, build_scanlines(scale=16), alpha=True)
    write_ico(png, ico)
    print("wrote " + str(ico) + " (" + str(ico.stat().st_size) + " bytes)")


if __name__ == "__main__":
    main()
