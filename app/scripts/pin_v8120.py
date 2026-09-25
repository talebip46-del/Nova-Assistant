#!/usr/bin/env python3
"""v8.12.0 release pin: update every version assertion in the test
suite from 8.11.0 to 8.12.0 (the project law - each release pins the
WHOLE suite to the new version so a stale build is caught instantly)."""
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
OLD, NEW = "8.11.0", "8.12.0"

changed = 0
pinned = 0
for t in sorted((APP / "tests").glob("*.py")):
    src = t.read_text(encoding="utf-8")
    n = src.count(f'"{OLD}"')
    if not n:
        continue
    # only version-string assertions touch the release pins
    new_src = src.replace(f'"{OLD}"', f'"{NEW}"')
    t.write_text(new_src, encoding="utf-8")
    changed += 1
    pinned += n
    print(f"{t.name}: {n} pin(s)")
print(f"\n{changed} file(s), {pinned} pin(s) updated {OLD} -> {NEW}")
sys.exit(0)
