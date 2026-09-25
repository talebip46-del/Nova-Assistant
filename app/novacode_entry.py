#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - PyInstaller entry for the CONSOLE exe (v8.12.0)
#
#    novacode.exe                    -> the classic terminal agent (nova.py)
#    novacode.exe serve [--port ..]  -> the web server  (was BROKEN: nova.py
#                                       has no subcommands, so 'serve' was
#                                       treated as a workspace name and a
#                                       junk ./serve folder was created)
#    novacode.exe --list-models      -> the model table
#    novacode.exe voice|stt|photo|pixel|flow|knowledge|models|platforms|
#    assign ...                      -> the multi-module CLI (nova_assistant)
#
#  The spec previously built novacode.exe straight from nova.py, but the
#  spec/docstring advertised subcommand parity with nova_assistant.py
#  that nova.py's argument parser never had. This tiny router makes the
#  advertised behavior real with zero dependency on a rebuild of the
#  individual faces.
# =====================================================================
import sys

try:
    from nova_assistant import MODULE_WORDS
except Exception:                       # frozen import must never hard-fail
    MODULE_WORDS = {"voice", "stt", "photo", "pixel", "flow", "knowledge",
                    "models", "platforms", "assign"}


def main():
    first = ""
    if len(sys.argv) > 1:
        first = str(sys.argv[1]).strip()
    if not first or first.startswith("-"):
        # plain REPL / flags -> the terminal agent
        import nova
        nova.main()
        return
    if first == "serve" or first in MODULE_WORDS:
        import nova_assistant
        nova_assistant.main()
        return
    # anything else is nova.py territory (a workspace path, mostly)
    import nova
    nova.main()


if __name__ == "__main__":
    main()
