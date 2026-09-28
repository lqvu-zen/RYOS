"""Always fails: a line on stdout, two on stderr, exit code 3."""
import sys

print("Starting a job that is going to fail...")
print("ERROR: could not find config.yaml", file=sys.stderr)
print("(more detail on stderr)", file=sys.stderr)
sys.exit(3)
