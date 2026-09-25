#!/usr/bin/env python3
"""Sync the version pins 8.8.0 -> 8.9.0 across the test files
(the release discipline: ONE version, pinned everywhere).
Also moves the CODENAME assertions to the new "design layers"."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "tests"


def main():
    changed = 0
    total = 0
    for p in sorted(ROOT.glob("test_*.py")):
        raw = p.read_text(encoding="utf-8")
        n = raw.count("8.8.0")
        new = raw.replace("8.8.0", "8.9.0")
        # the codename pins (assertion lines only; historical comments
        # that merely mention the old name stay untouched)
        pin = 'nova.CODENAME, "pre-run gate"'
        n += new.count(pin)
        new = new.replace(pin, 'nova.CODENAME, "design layers"')
        if not n:
            continue
        p.write_text(new, encoding="utf-8")
        changed += 1
        total += n
        print("  %-38s %d pin(s)" % (p.name, n))
    print("synced %d file(s), %d pin(s)" % (changed, total))
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
