"""Entry point — `uv run ryos` or `python -m ryos`.

Runs the Qt app (`ryos.qtui.main`). The Tk app stays one step away while the
Qt one settles in: RYOS_UI=tk selects it, and it is also used, with a logged
reason, if PySide6 cannot be imported.
"""
import logging
import os
import sys

from . import single_instance
from .logger import install_excepthook, setup_logging
from .settings import _load_settings
from .startup import _sync_startup_command


def _wants_tk(log) -> bool:
    if os.environ.get("RYOS_UI", "").strip().lower() == "tk":
        return True
    try:
        import PySide6  # noqa: F401
    except ImportError:
        log.warning("PySide6 is not available; starting the Tk interface")
        return True
    return False


def main():
    # Launched at login? The startup registry entry passes --startup, which
    # tells the app to restore the last-used screen instead of following the
    # cursor's monitor.
    launched_at_startup = "--startup" in sys.argv[1:]
    settings = _load_settings()
    setup_logging(settings.get("logging_enabled", True), settings.get("log_level", "INFO"))
    install_excepthook()
    _sync_startup_command()  # upgrade an older registry entry in place
    from . import __version__
    log = logging.getLogger("ryos")

    # A --startup launch stays silent if something's already running (no
    # window pop); a manual launch signals the existing instance to restore.
    lock = single_instance.acquire(
        restore_existing=not launched_at_startup,
        verb="RESTORE_CURSOR" if settings.get("open_on_cursor_monitor") else "RESTORE",
    )
    if lock is None:
        log.info("Another RYOS instance is already running; exiting")
        return

    use_tk = _wants_tk(log)
    log.info("RYOS %s starting (startup=%s, ui=%s)", __version__,
             launched_at_startup, "tk" if use_tk else "qt")
    try:
        if use_tk:
            from .ui.app import RYOSApp
            app = RYOSApp(launched_at_startup=launched_at_startup, instance_lock=lock)
            app.mainloop()
        else:
            from .qtui.main import run
            run(settings=settings, launched_at_startup=launched_at_startup,
                instance_lock=lock)
    except Exception:
        log.exception("Fatal error in the main loop")
        raise
    finally:
        lock.release()
        log.info("RYOS shutting down")


if __name__ == "__main__":
    main()
