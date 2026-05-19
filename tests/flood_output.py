"""Rapidly prints 500 lines — tests output scrolling and performance."""
import sys

lines = int(sys.argv[1]) if len(sys.argv) > 1 else 500

for i in range(1, lines + 1):
    print(f"Line {i:>4}/{lines}  {'#' * (i % 40)}")

print(f"\nAll {lines} lines printed.")
