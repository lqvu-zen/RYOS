"""Entry point for ryos-cli.exe, the console build of the command line.

RYOS.exe is built with the GUI base, which has no stdout, so `RYOS.exe list`
could never print anything. This one is built with the console base and
only ever runs the command line (ryos.cli): with no command it prints the
help rather than opening the window from a console.
"""
import sys

from ryos import cli

if __name__ == "__main__":
    sys.exit(cli.main(sys.argv[1:] or ["--help"]))
