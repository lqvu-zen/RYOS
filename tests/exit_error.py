"""Exits with a non-zero code — tests red error output and exit code display."""
import sys

code = int(sys.argv[1]) if len(sys.argv) > 1 else 1

print("This script prints to stdout...")
sys.stderr.write("...and this line goes to stderr.\n")
sys.stderr.flush()
print(f"Exiting with code {code}.")
sys.exit(code)
