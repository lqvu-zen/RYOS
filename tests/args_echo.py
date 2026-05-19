"""Pass arguments to this script to see them echoed back."""
import sys

if len(sys.argv) < 2:
    print("Usage: args_echo.py <arg1> <arg2> ...")
    print("No arguments provided.")
    sys.exit(0)

print(f"Received {len(sys.argv) - 1} argument(s):")
for i, arg in enumerate(sys.argv[1:], 1):
    print(f"  [{i}] {arg!r}")
