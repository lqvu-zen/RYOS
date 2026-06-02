"""Logging configuration for RYOS."""
import logging
import logging.handlers
import sys

from .settings import LOG_PATH

_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}

_ryos_logger = logging.getLogger("ryos")


def setup_logging(enabled: bool, level: str) -> None:
    """Configure the root ryos logger; idempotent — clears existing handlers on re-call."""
    _ryos_logger.handlers.clear()
    _ryos_logger.propagate = False

    if not enabled:
        _ryos_logger.addHandler(logging.NullHandler())
        return

    effective_level = level if level in _LEVELS else "INFO"
    _ryos_logger.setLevel(getattr(logging, effective_level))

    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=1_048_576, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")
    )
    _ryos_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of the ryos namespace."""
    return logging.getLogger("ryos." + name)


def log_exception(logger: logging.Logger, msg: str, exc_info=True) -> None:
    """Log at ERROR level with traceback."""
    logger.error(msg, exc_info=exc_info)


def install_excepthook() -> None:
    """Route uncaught exceptions through the logger while preserving prior hook."""
    _prior = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        _ryos_logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        _prior(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
