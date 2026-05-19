"""Prints a snapshot of the runtime environment."""
import sys
import os
import platform

print("=== Python Environment ===")
print(f"  Executable : {sys.executable}")
print(f"  Version    : {sys.version}")
print(f"  Platform   : {platform.platform()}")
print(f"  CWD        : {os.getcwd()}")
print(f"  PATH entries: {len(os.environ.get('PATH', '').split(os.pathsep))}")
