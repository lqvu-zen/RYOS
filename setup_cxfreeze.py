"""cx_Freeze build configuration for RYOS.

Usage (via build_cxfreeze.bat):
    uv run --with cx_Freeze python setup_cxfreeze.py build_exe

Output: dist/cxfreeze/RYOS.exe  (plus supporting DLLs in the same folder)
"""
import os
import shutil
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

# ryos-cli.exe carries the MCP server (`ryos-cli mcp`), so the SDK must be
# in the build environment: without it cx_Freeze would quietly build an exe
# whose `mcp` says the SDK is missing. The extra installs it.
try:
    import mcp  # noqa: F401
except ImportError:
    sys.exit("The build needs the MCP SDK: run it as\n"
             "  uv run --extra mcp --with cx_Freeze python setup_cxfreeze.py build_exe")

BUILD_DIR = Path("dist/cxfreeze")

# Which download this build is (ryos/buildinfo.py): written into the package
# for the length of the build, so the frozen app knows, and removed after so
# the source tree stays "from source".
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ryos import buildinfo  # noqa: E402

VARIANT = os.environ.get("RYOS_VARIANT", buildinfo.WINDOWS)
BUILD_INFO = Path("ryos/_build_info.py")

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

EXECUTABLES = [
    Executable(
        script="_packed_entry.py",
        base="gui",               # suppresses the console window (cx_Freeze 7+)
        target_name="RYOS.exe",
        icon="icon.ico",
    ),
    # The command line (ryos list / run / pipeline / mcp): the console base,
    # so it has a stdout -- RYOS.exe's GUI base has none.
    Executable(
        script="_packed_cli.py",
        base="console",
        target_name="ryos-cli.exe",
        icon="icon.ico",
    ),
]

BUILD_INFO.write_text(buildinfo.build_info_source(VARIANT), encoding="utf-8")
try:
    setup(
        name="RYOS",
        version="2.2.0",
        description="RYOS - Run Your Own Scripts",
        options={"build_exe": build_options},
        executables=EXECUTABLES,
    )
finally:
    BUILD_INFO.unlink(missing_ok=True)

# Qt's own translations: data files, so bin_excludes cannot leave them out,
# and RYOS installs no QTranslator, so nothing reads them (6 MB).
shutil.rmtree(BUILD_DIR / "lib" / "PySide6" / "translations", ignore_errors=True)
