#!/usr/bin/env python3
"""v8.10.1 mechanical update (the release discipline):

Version surfaces -> 8.10.1 / codename "stability sweep II":
  - nova.py: header block + VERSION + CODENAME
  - nova_think.py: header + VERSION
  - nova_assistant.py: header + argparse string
  - novacode_entry.py: header
  - tests: every "8.10.0" version pin and the CODENAME assertion lines
Idempotent (running twice is a no-op) and verifies every replacement.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SURFACES = [
    (ROOT / "nova.py", [
        ("#  Version 8.10.0 - pure Python standard library, zero dependencies.",
         "#  Version 8.10.1 - pure Python standard library, zero dependencies."),
        ('VERSION = "8.10.0"', 'VERSION = "8.10.1"'),
        ('CODENAME = "texture & neon"', 'CODENAME = "stability sweep II"'),
    ]),
    (ROOT / "nova_think.py", [
        ('VERSION = "8.10.0"', 'VERSION = "8.10.1"'),
    ]),
    (ROOT / "nova_assistant.py", [
        ("#  Nova Assistant - multi-module CLI (v8.10.0)",
         "#  Nova Assistant - multi-module CLI (v8.10.1)"),
        ('description="Nova Assistant v8.10.0 - the multi-module local AI toolbox")',
         'description="Nova Assistant v8.10.1 - the multi-module local AI toolbox")'),
    ]),
    (ROOT / "novacode_entry.py", [
        ("#  Nova Assistant - PyInstaller entry for the CONSOLE exe (v8.10.0)",
         "#  Nova Assistant - PyInstaller entry for the CONSOLE exe (v8.10.1)"),
    ]),
]


def sync_tests():
    changed = 0
    total = 0
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        raw = p.read_text(encoding="utf-8")
        n = raw.count("8.10.0")
        new = raw.replace("8.10.0", "8.10.1")
        pin = 'nova.CODENAME, "texture & neon"'
        n += new.count(pin)
        new = new.replace(pin, 'nova.CODENAME, "stability sweep II"')
        if not n:
            continue
        p.write_text(new, encoding="utf-8")
        changed += 1
        total += n
        print("  %-38s %d pin(s)" % (p.name, n))
    print("tests: synced %d file(s), %d pin(s)" % (changed, total))


def main():
    ok = True
    for path, pairs in SURFACES:
        raw = path.read_text(encoding="utf-8")
        for old, new in pairs:
            if old in raw:
                raw = raw.replace(old, new)
                print("  %-22s %r" % (path.name, old[:52]))
            elif new in raw:
                print("  %-22s (already) %r" % (path.name, new[:52]))
            else:
                print("  !! MISSING in %s: %r" % (path.name, old[:60]))
                ok = False
        path.write_text(raw, encoding="utf-8")
    sync_tests()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
