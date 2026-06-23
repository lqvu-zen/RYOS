"""Entry point — `uv run ryos` or `python -m ryos`."""
import logging
import sys

from .logger import install_excepthook, setup_logging
from .settings import _load_settings
from .startup import _sync_startup_command
from .ui.app import RYOSApp


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
    log.info("RYOS %s starting (startup=%s)", __version__, launched_at_startup)
    app = RYOSApp(launched_at_startup=launched_at_startup)
    try:
        app.mainloop()
    except Exception:
        log.exception("Fatal error in mainloop")
        raise
    finally:
        log.info("RYOS shutting down")


if __name__ == "__main__":
    main()
