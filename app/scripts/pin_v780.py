#!/usr/bin/env python3
"""Pin the version string 7.7.0 -> 7.8.0 in every test file that asserts it."""
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
TESTS = APP / "tests"

changed = []
for p in sorted(TESTS.glob("test_*.py")):
    text = p.read_text(encoding="utf-8")
    new = text.replace('"7.7.0"', '"7.8.0"')
    if new != text:
        p.write_text(new, encoding="utf-8")
        changed.append(p.name)

print("updated pins:", len(changed))
for name in changed:
    print(" -", name)

# sanity: no stray 7.7.0 assertions left anywhere in tests
left = []
for p in TESTS.glob("test_*.py"):
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if '"7.7.0"' in line or "'7.7.0'" in line:
            left.append(f"{p.name}:{i}: {line.strip()}")
if left:
    print("LEFTOVER 7.7.0 PINS:")
    for x in left:
        print("  ", x)
    sys.exit(1)
print("no leftovers - all pins are 7.8.0")
