"""cx_Freeze build configuration for RYOS.

Usage (via build_cxfreeze.bat):
    uv run --with cx_Freeze python setup_cxfreeze.py build_exe

Output: dist/cxfreeze/RYOS.exe  (plus supporting DLLs in the same folder)
"""
from pathlib import Path

from cx_Freeze import Executable, setup


def _unused_qt_binaries() -> list:
    """Qt DLLs RYOS does not use, for bin_excludes.

    cx_Freeze's PySide6 hook copies every Qt library in the wheel -- web
    engine (195 MB on its own), 3D, QML, multimedia with its FFmpeg -- which
    made the build 383 MB. RYOS uses QtCore, QtGui and QtWidgets (and Svg for
    icons); everything else is left out. Worked out from the installed wheel,
    so a new Qt release's extra modules are excluded too.
    """
    import PySide6
    keep = {"Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Svg.dll"}
    folder = Path(PySide6.__file__).parent
    qt = [p.name for p in folder.glob("Qt6*.dll") if p.name not in keep]
    ffmpeg = [p.name for p in folder.glob("*.dll")
              if p.name.startswith(("av", "sw"))]
    return sorted(qt + ffmpeg)


build_options = {
    # "ryos" is named whole because the Qt app imports its UI modules lazily
    # (inside ryos.qtui.main.run). PySide6 is deliberately NOT named: that
    # copies every Qt module (web engine, 3D, multimedia...) -- 647 MB. Left
    # to the import graph, only QtCore/QtGui/QtWidgets come in, and
    # cx_Freeze's PySide6 hook adds the plugins they need.
    "packages": ["ryos", "sqlite3"],
    "bin_excludes": _unused_qt_binaries(),
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
    version="1.11.2",
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
