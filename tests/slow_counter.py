"""Counts to 30 with 1-second delay — use to test the Stop button."""
import time
import sys

total = int(sys.argv[1]) if len(sys.argv) > 1 else 30

print(f"Counting to {total}. Use the Stop button to cancel.")
for i in range(1, total + 1):
    print(f"  {i}/{total}")
    sys.stdout.flush()
    time.sleep(1)

print("Done!")
