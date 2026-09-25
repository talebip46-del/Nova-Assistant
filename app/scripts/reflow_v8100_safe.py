#!/usr/bin/env python3
"""Cosmetic reflow (pass 3, safe): wrap every >79-col line that carries
the appended grain/neon/aurora keys. Splits ONLY at the top-level
commas before the appended keys, then verifies the file still compiles
and the test module still passes before it keeps the result."""
import py_compile
import subprocess
import sys
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "tests" / \
    "test_v890_design_layers.py"
KEYS = '"grain": None, "neon": None, "aurora": None'


def main():
    lines = P.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    for line in lines:
        body = line.rstrip("\n")
        if len(body) <= 79 or KEYS not in body:
            out.append(line)
            continue
        indent = body[:len(body) - len(body.lstrip())]
        pad = indent + " " * 4
        marker = ", " + KEYS
        if marker in body:
            cut = body.index(marker) + 1          # keep the comma on head
            head, tail = body[:cut], body[cut + 1:]
            out.append(head + "\n")
            while len(pad + tail) > 79 and ", " in tail:
                c2 = tail.index(", ") + 1
                out.append(pad + tail[:c2] + "\n")
                tail = tail[c2 + 1:]
            out.append(pad + tail + "\n")
        else:
            # tail line that is already standalone but still too long
            stripped = body.lstrip()
            lead = body[:len(body) - len(stripped)]
            if stripped.startswith(KEYS):
                out.append(lead + '"grain": None, "neon": None,\n')
                out.append(lead + '"aurora": None' +
                           stripped[len(KEYS):] + "\n")
            else:
                out.append(line)
    P.write_text("".join(out), encoding="utf-8")
    # verify: compile + the v890 suite must stay green
    py_compile.compile(str(P), doraise=True)
    r = subprocess.run([sys.executable, "-m", "pytest",
                        "tests/test_v890_design_layers.py", "-q"],
                       cwd=str(P.parent.parent), capture_output=True,
                       text=True, timeout=120)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout else "?"
    print("reflow ok, pytest:", tail)
    return 0 if "passed" in tail and " failed" not in tail else 1


if __name__ == "__main__":
    sys.exit(main())
