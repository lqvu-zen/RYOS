"""Start RYOS on Qt: build the window, give it the real world, run.

The shell (`qtui/shell.py`) takes every effect on the outside world as an
argument that does nothing by default -- saving settings, toasts, the update
fetch, run-at-login, quitting -- so tests can build it freely. This is the one
place that passes the real ones, and does what the Tk app did at start:
migrate and load custom themes, prune old run history, attach the jobs, the
tray and the single-instance listener, place the window, and check for an
update.
"""

from __future__ import annotations

import os
import sys

from .. import __version__
from ..logger import get_logger

_log = get_logger("qtui.main")

TITLE = f"RYOS v{__version__} — Run Your Own Scripts"
MIN_HEIGHT = 320


class RegistryStartup:
    """Run-at-login, in the Windows registry (`ryos.startup`)."""

    def enabled(self) -> bool:
        from ..startup import _startup_enabled
        return _startup_enabled()

    def set(self, on: bool) -> None:
        from ..startup import _set_startup
        _set_startup(on)


def _tray_wanted() -> bool:
    """Packaged builds get a tray; source runs only with RYOS_TRAY=1 -- as Tk."""
    from ..settings import _PACKAGED
    forced = os.environ.get("RYOS_TRAY", "").strip().lower() in ("1", "true", "yes")
    return _PACKAGED or forced


def run(*, settings: dict, launched_at_startup: bool = False, instance_lock=None,
        argv=None) -> int:
    """Start RYOS and run until it quits."""
    app, _win = build(settings=settings, launched_at_startup=launched_at_startup,
                      instance_lock=instance_lock, argv=argv)
    return app.exec()


def build(*, settings: dict, launched_at_startup: bool = False, instance_lock=None,
          argv=None, show: bool = True):
    """Everything start-up does, short of the event loop: (app, window).

    Split from `run` so a test can take the exact start-up path -- the real
    data, themes and settings -- and inspect the window it produces.
    """
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from ..db import ScriptDB
    from ..history import prune_run_history
    from ..logger import setup_logging
    from ..notifications import _fetch_latest_release, _show_notification
    from ..settings import _BASE, _save_settings
    from ..themes import (load_user_themes, migrate_legacy_custom_themes,
                          palette_for, resolve_user_themes_dir)
    from .jobs import JobBridge
    from .shell import MainWindow
    from .tray import Tray

    if sys.platform == "win32":
        import ctypes
        # Groups the windows under RYOS in the taskbar, not under python.exe.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "RYOS.RunYourOwnScripts")
    app = QApplication.instance() or QApplication(
        list(argv if argv is not None else sys.argv))
    app.setApplicationName("RYOS")
    # Hiding to the tray hides the last window; that must not end the app.
    app.setQuitOnLastWindowClosed(False)
    # The check-box tick is an SVG; a build that lost Qt's SVG plugin draws
    # ticked boxes with no tick and says nothing, so say it here.
    from PySide6.QtGui import QImageReader
    if b"svg" not in [bytes(f) for f in QImageReader.supportedImageFormats()]:
        _log.warning("Qt has no SVG image support here (imageformats plugin "
                     "missing?): ticked check boxes will show no tick")
    icon_path = _BASE / "icon.ico"
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    app.setWindowIcon(icon)

    themes_dir = resolve_user_themes_dir(settings.get("themes_dir"))
    try:
        migrate_legacy_custom_themes(themes_dir)
    except OSError:
        _log.warning("Could not migrate legacy custom themes", exc_info=True)
    customs = load_user_themes(themes_dir)
    palette = palette_for(settings.get("theme", "light"),
                          settings.get("accent_color"), customs)

    db = ScriptDB()
    prune_run_history(db, settings)

    win = MainWindow(palette, settings=settings, save_settings=_save_settings,
                     notifier=_show_notification,
                     fetch_release=_fetch_latest_release,
                     startup=RegistryStartup(),
                     configure_logging=setup_logging)
    win._set_customs(customs)
    win.setWindowTitle(TITLE)
    win.setMinimumSize(MainWindow.MIN_WIDTH, MIN_HEIGHT)
    win.on_quit = app.quit

    bridge = JobBridge(db, settings)
    win.attach_jobs(bridge)
    bridge.start()
    if _tray_wanted():
        try:
            tray = Tray(icon)
            if tray.available:
                win.attach_tray(tray)
        except Exception:
            # The tray is best-effort; start-up must never fail over it.
            _log.debug("Could not start the tray icon", exc_info=True)
    if instance_lock is not None:
        win.attach_instance(instance_lock)

    win.load_from_db(db)
    _log.info("Loaded %d group(s), %d script(s), %d pipeline(s)",
              len(db.list_groups()), len(db.list_all()),
              sum(len(db.list_pipelines(g)) for g in [*db.list_groups(), ""]))
    if show:
        # Placed before it is shown, so it first appears where it belongs:
        # shown first, it flashed at Qt's default spot (on the primary
        # screen) and then jumped. Placed again once shown, because Windows
        # may rescale a window that lands on a screen of another scale, and
        # set_geometry_string's guard holds it there.
        win.apply_placement(launched_at_startup=launched_at_startup)
        win.show()
        win.apply_placement(launched_at_startup=launched_at_startup)
        win.apply_start()
        _log.info("Window shown at %s", win.geometry_string())
    if settings.get("auto_check_update", True):
        win.check_for_updates()
    win.bridge = bridge
    return app, win
