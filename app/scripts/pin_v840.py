#!/usr/bin/env python3
"""Sync the version pins 8.3.0 -> 8.4.0 across the test files
(the release discipline: ONE version, pinned everywhere)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "tests"


def main():
    changed = 0
    total = 0
    for p in sorted(ROOT.glob("test_*.py")):
        raw = p.read_text(encoding="utf-8")
        n = raw.count("8.3.0")
        if not n:
            continue
        new = raw.replace("8.3.0", "8.4.0")
        p.write_text(new, encoding="utf-8")
        changed += 1
        total += n
        print("  %-38s %d pin(s)" % (p.name, n))
    print("synced %d file(s), %d pin(s)" % (changed, total))
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
