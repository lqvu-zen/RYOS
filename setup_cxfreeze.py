"""cx_Freeze build configuration for RYOS.

Usage (via build_cxfreeze.bat):
    uv run --with cx_Freeze --with tkinterdnd2 python setup_cxfreeze.py build_exe

Output: dist/cxfreeze/RYOS.exe  (plus supporting DLLs in the same folder)
"""
from cx_Freeze import Executable, setup

build_options = {
    "packages": ["ryos", "tkinterdnd2", "sqlite3"],
    "include_files": [("icon.ico", "icon.ico")],
    "excludes": [
        "unittest", "pydoc", "doctest", "difflib",
        "ftplib", "imaplib", "mailbox", "nntplib", "poplib",
        "smtplib", "telnetlib",
    ],
    "build_exe": "dist/cxfreeze",
}

setup(
    name="RYOS",
    version="1.4.4",
    description="RYOS - Run Your Own Scripts",
    options={"build_exe": build_options},
    executables=[
        Executable(
            script="_packed_entry.py",
            base="gui",               # suppresses the console window (cx_Freeze 7+)
            target_name="RYOS.exe",
            icon="icon.ico",
        )
    ],
)
