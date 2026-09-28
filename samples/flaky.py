"""Fails about half the time -- try it with retries in a pipeline."""
import random
import sys

if random.random() < 0.5:
    print("flaky: failed this time", file=sys.stderr)
    sys.exit(1)
print("flaky: worked this time")
