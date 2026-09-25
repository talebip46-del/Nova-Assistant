#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - PyInstaller entry for the WINDOWED exe (no console)
#
#    NovaAssistant.exe              -> starts the web dashboard and
#                                      opens it in your browser
#    NovaAssistant.exe <any args>   -> behaves exactly like
#                                      `nova_assistant.py <args>` (the
#                                      full multi-module CLI gateway)
#
#  Why a separate entry? nova.py's terminal face needs a real console
#  (input(), ANSI colors, Ctrl+C). A double-clicked windowed exe has
#  none of those, so here the no-arg default becomes `serve` - the one
#  face that genuinely works without a console. For a classic terminal
#  session the dist also ships `novacode.exe` (console build of
#  nova.py) - use that for the REPL, or to stop a server started by
#  the windowed exe (Task Manager works too).
#
#  print() is safe in a windowed exe: PyInstaller gives us a
#  NullWriter, and CPython's print silently no-ops when stdout is
#  None, so banner code never crashes the GUI process.
# =====================================================================
import sys


def main():
    if len(sys.argv) <= 1:
        # double-click launch: serve on the default port and open the UI
        sys.argv = [sys.argv[0], "serve"]
    import nova_assistant
    nova_assistant.main()


if __name__ == "__main__":
    main()
