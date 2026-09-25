#!/usr/bin/env python3
"""v8.10.0 mechanical update (the release discipline):

1. test_v890_design_layers.py: every exact spec-dict literal grows the
   three new layer keys (grain/neon/aurora = None) so the assertions
   keep matching the (now six-key) parse_layers/_merge_specs output.
2. version surfaces: nova.py header + VERSION/CODENAME, nova_think.py,
   nova_assistant.py header + argparse string, novacode_entry.py header
   -> 8.10.0 "texture & neon".
Nothing else is touched; the script is idempotent (running twice is a
no-op) and verifies every replacement it makes.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

NEW_KEYS = ', "grain": None, "neon": None, "aurora": None'
DICT_RE = re.compile(
    r'\{"shadow":[^{}]*(?:\{[^{}]*\})?[^{}]*\}')
CODENAME_OLD = "design layers"
CODENAME_NEW = "texture & neon"


def extend_spec_dicts():
    p = TESTS / "test_v890_design_layers.py"
    raw = p.read_text(encoding="utf-8")
    out, changed = [], 0
    pos = 0
    for m in DICT_RE.finditer(raw):
        lit = m.group(0)
        out.append(raw[pos:m.start()])
        if '"motion"' in lit and '"grain"' not in lit:
            lit = lit[:-1] + NEW_KEYS + "}"
            changed += 1
        out.append(lit)
        pos = m.end()
    out.append(raw[pos:])
    if changed:
        p.write_text("".join(out), encoding="utf-8")
    print("  test_v890 spec dicts extended: %d" % changed)
    return changed


def bump(path, pairs):
    p = ROOT / path
    raw = p.read_text(encoding="utf-8")
    n = 0
    for old, new in pairs:
        c = raw.count(old)
        if c:
            raw = raw.replace(old, new)
            n += c
    if n:
        p.write_text(raw, encoding="utf-8")
    print("  %-24s %d pin(s)" % (path, n))
    return n


def main():
    total = extend_spec_dicts()
    total += bump("nova.py", [
        ("Version 8.9.0", "Version 8.10.0"),
        ('VERSION = "8.9.0"', 'VERSION = "8.10.0"'),
        ('CODENAME = "%s"' % CODENAME_OLD, 'CODENAME = "%s"' % CODENAME_NEW),
        ('(release codename: "%s" - OPTIONAL polish layers the'
         % CODENAME_OLD,
         '(release codename: "%s" - OPTIONAL polish layers the'
         % CODENAME_NEW),
        ("model opts into per project: the 5-level shadow scale, the\n"
         "#   4-level frosted-glass scale and ready micro-motions. Options,",
         "model opts into per project: the 5-level shadow scale, the\n"
         "#   4-level frosted-glass scale, ready micro-motions, film\n"
         "#   grain, neon edges and an aurora wash. Options,"),
    ])
    total += bump("nova_think.py", [
        ('VERSION = "8.9.0"', 'VERSION = "8.10.0"'),
    ])
    total += bump("nova_assistant.py", [
        ("(v8.9.0)", "(v8.10.0)"),
        ("Nova Assistant v8.9.0", "Nova Assistant v8.10.0"),
    ])
    total += bump("novacode_entry.py", [
        ("(v8.9.0)", "(v8.10.0)"),
    ])
    print("synced %d pin(s)" % total)
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
