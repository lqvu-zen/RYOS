"""Entry point — `uv run ryos` or `python -m ryos`."""
import logging

from .logger import install_excepthook, setup_logging
from .settings import _load_settings
from .ui.app import RYOSApp


def main():
    settings = _load_settings()
    setup_logging(settings.get("logging_enabled", True), settings.get("log_level", "INFO"))
    install_excepthook()
    from . import __version__
    log = logging.getLogger("ryos")
    log.info("RYOS %s starting", __version__)
    app = RYOSApp()
    try:
        app.mainloop()
    except Exception:
        log.exception("Fatal error in mainloop")
        raise
    finally:
        log.info("RYOS shutting down")


if __name__ == "__main__":
    main()
