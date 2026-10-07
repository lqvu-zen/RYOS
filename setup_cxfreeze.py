"""cx_Freeze build configuration for RYOS.

Usage (via build_cxfreeze.bat):
    uv run --with cx_Freeze python setup_cxfreeze.py build_exe

Output: dist/cxfreeze/RYOS.exe  (plus supporting DLLs in the same folder)
"""
import shutil
from pathlib import Path

from cx_Freeze import Executable, setup

BUILD_DIR = Path("dist/cxfreeze")

#: The Qt plugin folders RYOS loads: the platform (windows, offscreen), the
#: widget style, image formats and the SVG icon engine for its icons, and
#: input (IMEs, input devices). cx_Freeze's hook copies a different set of the
#: rest -- Designer, QML tooling, SQL drivers, 3D, multimedia, sensors, web
#: view... -- on different runs, which made the build swing between 71 and
#: 80 MB; every other folder in the wheel is left out, so it is the same each
#: time, and a new Qt's new folders are left out too.
KEEP_PLUGIN_DIRS = {"platforms", "styles", "imageformats", "iconengines",
                    "platforminputcontexts", "generic"}


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
    # Newer cx_Freeze hooks also copy Qt's software OpenGL (20 MB; RYOS draws
    # no OpenGL) and the QML plugins (useless without Qt6Quick, left out above).
    qml = [p.name for p in (folder / "qml").rglob("*.dll")]
    plugins = [p.name for d in (folder / "plugins").iterdir()
               if d.is_dir() and d.name not in KEEP_PLUGIN_DIRS
               for p in d.glob("*.dll")]
    return sorted(set(qt + ffmpeg + qml + plugins + ["opengl32sw.dll"]))


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
        # The stylesheet's images (the check-box tick); see qtui/stylesheet.py.
        ("ryos/qtui/icons", "lib/ryos/qtui/icons"),
        # Bundled preset themes are data files, not modules, so cx_Freeze won't
        # pick them up via "packages"; copy them next to the frozen package so
        # themes.PRESETS_DIR (Path(__file__).parent / "presets") resolves.
        ("ryos/presets", "lib/ryos/presets"),
    ],
    "excludes": [
        # The Tk interface is gone; without this, Tcl/Tk (~7 MB) still ships.
        "tkinter",
        "unittest", "pydoc", "doctest", "difflib",
        "ftplib", "imaplib", "mailbox", "nntplib", "poplib",
        "smtplib", "telnetlib",
    ],
    "build_exe": str(BUILD_DIR),
}

setup(
    name="RYOS",
    version="2.2.0",
    description="RYOS - Run Your Own Scripts",
    options={"build_exe": build_options},
    executables=[
        Executable(
            script="_packed_entry.py",
            base="gui",               # suppresses the console window (cx_Freeze 7+)
            target_name="RYOS.exe",
            icon="icon.ico",
        ),
        # The command line (ryos list / run / pipeline): the console base, so
        # it has a stdout -- RYOS.exe's GUI base has none.
        Executable(
            script="_packed_cli.py",
            base="console",
            target_name="ryos-cli.exe",
            icon="icon.ico",
        ),
    ],
)

# Qt's own translations: data files, so bin_excludes cannot leave them out,
# and RYOS installs no QTranslator, so nothing reads them (6 MB).
shutil.rmtree(BUILD_DIR / "lib" / "PySide6" / "translations", ignore_errors=True)
