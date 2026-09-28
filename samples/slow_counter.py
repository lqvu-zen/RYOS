"""Counts for a minute -- try Stop, the Running list and the tray."""
import time

for i in range(1, 61):
    print(f"tick {i}/60", flush=True)
    time.sleep(1)
print("done counting")
