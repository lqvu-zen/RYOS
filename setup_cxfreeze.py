"""cx_Freeze build configuration for RYOS.

Usage (via build_cxfreeze.bat):
    uv run --with cx_Freeze --with tkinterdnd2 python setup_cxfreeze.py build_exe

Output: dist/cxfreeze/RYOS.exe  (plus supporting DLLs in the same folder)
"""
from cx_Freeze import Executable, setup

build_options = {
    # pystray and PIL resolve backends/plugins dynamically at import time,
    # which cx_Freeze's static import finder can't follow, so they must be
    # named explicitly -- otherwise the frozen exe would be silently broken.
    "packages": ["ryos", "tkinterdnd2", "sqlite3", "pystray", "PIL"],
    "include_files": [
        ("icon.ico", "icon.ico"),
        # Bundled preset themes are data files, not modules, so cx_Freeze won't
        # pick them up via "packages"; copy them next to the frozen package so
        # themes.PRESETS_DIR (Path(__file__).parent / "presets") resolves.
        ("ryos/presets", "lib/ryos/presets"),
    ],
    "excludes": [
        "unittest", "pydoc", "doctest", "difflib",
        "ftplib", "imaplib", "mailbox", "nntplib", "poplib",
        "smtplib", "telnetlib",
    ],
    "build_exe": "dist/cxfreeze",
}

setup(
    name="RYOS",
    version="1.8.2",
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
