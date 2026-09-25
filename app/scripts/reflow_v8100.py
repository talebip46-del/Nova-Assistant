#!/usr/bin/env python3
"""Reflow the long spec-dict lines the v8.10 update created in
test_v890_design_layers.py: put the appended grain/neon/aurora keys on
their own continuation line (project style <= 79 cols)."""
import re
import sys
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "tests" / \
    "test_v890_design_layers.py"

TAIL = ', "grain": None, "neon": None, "aurora": None})'


def main():
    lines = P.read_text(encoding="utf-8").splitlines(keepends=True)
    out, n = [], 0
    for line in lines:
        body = line.rstrip("\n")
        if len(body) <= 79 or not body.rstrip().endswith(
                '"aurora": None})') or '"grain": None' not in body:
            out.append(line)
            continue
        indent = re.match(r"\s*", body).group(0)
        cut = body.rindex(', "grain": None')
        head = body[:cut] + ")"
        new_indent = indent + " " * 4
        out.append(head + "\n")
        out.append(new_indent + '"grain": None, "neon": None,'
                   ' "aurora": None})\n')
        n += 1
    P.write_text("".join(out), encoding="utf-8")
    print("reflowed %d line(s)" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
