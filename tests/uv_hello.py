import sys
import platform

print("Hello from uv!")
print(f"  Version : {platform.python_version()}")
print(f"  Args    : {sys.argv[1:]}")
