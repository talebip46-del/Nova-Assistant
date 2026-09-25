#!/usr/bin/env python3
"""v8.11.0 mechanical update (the release discipline):

Version surfaces -> 8.11.0 / codename "false alarm purge":
  - nova.py: header block + VERSION + CODENAME
  - nova_think.py: header + VERSION
  - nova_assistant.py: header + argparse string
  - novacode_entry.py: header
  - tests: every "8.10.1" version pin and the CODENAME assertion lines
Idempotent (running twice is a no-op) and verifies every replacement.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SURFACES = [
    (ROOT / "nova.py", [
        ("#  Version 8.10.1 - pure Python standard library, zero dependencies.",
         "#  Version 8.11.0 - pure Python standard library, zero dependencies."),
        ('VERSION = "8.10.1"', 'VERSION = "8.11.0"'),
        ('CODENAME = "stability sweep II"', 'CODENAME = "false alarm purge"'),
    ]),
    (ROOT / "nova_think.py", [
        ('VERSION = "8.10.1"', 'VERSION = "8.11.0"'),
    ]),
    (ROOT / "nova_assistant.py", [
        ("#  Nova Assistant - multi-module CLI (v8.10.1)",
         "#  Nova Assistant - multi-module CLI (v8.11.0)"),
        ('description="Nova Assistant v8.10.1 - the multi-module local AI toolbox")',
         'description="Nova Assistant v8.11.0 - the multi-module local AI toolbox")'),
    ]),
    (ROOT / "novacode_entry.py", [
        ("#  Nova Assistant - PyInstaller entry for the CONSOLE exe (v8.10.1)",
         "#  Nova Assistant - PyInstaller entry for the CONSOLE exe (v8.11.0)"),
    ]),
]


def sync_tests():
    changed = 0
    total = 0
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        raw = p.read_text(encoding="utf-8")
        n = raw.count("8.10.1")
        new = raw.replace("8.10.1", "8.11.0")
        pin = 'nova.CODENAME, "stability sweep II"'
        n += new.count(pin)
        new = new.replace(pin, 'nova.CODENAME, "false alarm purge"')
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
