#!/usr/bin/env python3
"""Repair the reflow damage in test_v890_design_layers.py.

The buggy reflow turned
    ..., "motion": <X>)            <- extra ')' instead of ','
        "grain": None, "neon": None, "aurora": None})
into broken syntax. This script strips exactly ONE trailing ')' from
every mangled head line (the line right before a continuation line
that is exactly the grain/neon/aurora tail) and appends ','.
"""
import sys
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "tests" / \
    "test_v890_design_layers.py"

TAIL = '"grain": None, "neon": None, "aurora": None})'


def main():
    lines = P.read_text(encoding="utf-8").splitlines()
    fixed = 0
    for i, line in enumerate(lines):
        if line.strip() != TAIL:
            continue
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        head = lines[j]
        if head.rstrip().endswith(")") and '"motion"' in head:
            lines[j] = head.rstrip()[:-1] + ","
            fixed += 1
    P.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("repaired %d head line(s)" % fixed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
