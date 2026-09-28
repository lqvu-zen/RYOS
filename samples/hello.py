"""Prints a greeting, its arguments and an environment variable."""
import os
import sys

args = sys.argv[1:]
loud = "--loud" in args
name = "world"
if "--name" in args and args.index("--name") + 1 < len(args):
    name = args[args.index("--name") + 1]
text = f"Hello, {name}!"
print(text.upper() if loud else text)
print("arguments:", args or "(none)")
print("RYOS_SAMPLE =", os.environ.get("RYOS_SAMPLE", "(not set)"))
