import sys
import platform

print("Hello from Python!")
print(f"  Version : {platform.python_version()}")
print(f"  Platform: {platform.system()} {platform.release()}")
print(f"  Args    : {sys.argv[1:]}")
