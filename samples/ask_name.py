"""Set to ask for a parameter on each run: whatever you type arrives here."""
import sys

print("You typed:", " ".join(sys.argv[1:]) or "(nothing)")
