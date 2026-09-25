#!/usr/bin/env python3
"""Sync every test version pin 7.11.0 -> 7.12.0 (v7.12 release)."""
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent / "tests"
# assertEqual(nova.VERSION, "7.11.0") / assertEqual(_nova.VERSION, "7.11.0")
# / assertEqual(info["version"], "7.11.0")
pat = re.compile(r'((?:nova|_nova)\.VERSION|info\["version"\]),\s*"7\.11\.0"')

changed = []
for p in sorted(TESTS.glob("test_*.py")):
    t = p.read_text(encoding="utf-8")
    new = pat.sub(r'\g<1>, "7.12.0"', t)
    if new != t:
        p.write_text(new, encoding="utf-8")
        changed.append(p.name)
print("re-pinned:", len(changed))
for c in changed:
    print("  -", c)
