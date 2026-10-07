"""Entry point — `uv run ryos` or `python -m ryos`. Runs the Qt app
(`ryos.qtui.main`), or, given a command (`ryos run build`), the command line
(`ryos.cli`)."""
import logging
import sys

from . import single_instance
from .logger import install_excepthook, setup_logging
from .settings import _load_settings
from .startup import _sync_startup_command


def _qt_available(log) -> bool:
    """Whether PySide6 imports. It is RYOS's one dependency; without it there
    is no interface to start, so say why rather than fail on a bare import."""
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:
        log.error("PySide6 is not available (%s); RYOS cannot start", exc)
        print(f"RYOS needs PySide6, which could not be imported: {exc}\n"
              "Run it with `uv run ryos`, which installs it.", file=sys.stderr)
        return False
    return True


def main():
    # `ryos list` / `ryos run ...`: the command line, decided before anything
    # else -- it takes no instance lock, writes no run-at-login entry and
    # never imports Qt, so it works beside a running window.
    from . import cli
    if cli.is_cli(sys.argv[1:]):
        return cli.main(sys.argv[1:])

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
    if not _qt_available(log):
        return 1

    # A --startup launch stays silent if something's already running (no
    # window pop); a manual launch signals the existing instance to restore.
    lock = single_instance.acquire(
        restore_existing=not launched_at_startup,
        verb="RESTORE_CURSOR" if settings.get("open_on_cursor_monitor") else "RESTORE",
    )
    if lock is None:
        log.info("Another RYOS instance is already running; exiting")
        return 0

    log.info("RYOS %s starting (startup=%s, ui=qt)", __version__, launched_at_startup)
    try:
        from .qtui.main import run
        run(settings=settings, launched_at_startup=launched_at_startup,
            instance_lock=lock)
    except Exception:
        log.exception("Fatal error in the main loop")
        raise
    finally:
        lock.release()
        log.info("RYOS shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
