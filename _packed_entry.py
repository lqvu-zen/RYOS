"""Top-level entry point for PyInstaller and cx_Freeze builds.

Both packagers run ryos/__main__.py as a standalone script, which breaks
relative imports. This shim imports ryos as a proper package and delegates
to its main() function.
"""
from ryos.__main__ import main

if __name__ == "__main__":
    main()
