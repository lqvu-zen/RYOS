"""Prints 3000 lines fast, every 10th to stderr -- try Find, Errors only
and the output line cap."""
import sys

for i in range(1, 3001):
    if i % 10 == 0:
        print(f"line {i}: WARNING something to look at", file=sys.stderr)
    else:
        print(f"line {i}: all good")
