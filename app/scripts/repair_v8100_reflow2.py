#!/usr/bin/env python3
"""Repair pass 2 for test_v890_design_layers.py (general).

Every reflow-damaged spot looks like:
    <head line ending with a stray ')'>      <- the ')' the buggy
    "grain": None, "neon": None, "aurora": None})   reflow appended

The buggy reflow appended ')' to body[:cut]; the correct join is ','.
So: for every tail line, take the previous non-empty line and if it
ends with ')' strip exactly one ')' and append ','. Iterate-friendly
(already-repaired lines end with ',' and are skipped).
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
        if j < 0:
            continue
        head = lines[j].rstrip()
        if head.endswith(")"):
            lines[j] = head[:-1] + ","
            fixed += 1
    P.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("repaired %d more head line(s)" % fixed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
