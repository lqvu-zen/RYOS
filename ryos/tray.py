"""System tray icon (minimize/close-to-tray). No ryos.ui.* imports.

The two callbacks passed into TrayIcon fire on pystray's own thread (the
Win32 message pump thread), NOT the Tk main thread. This module does not
marshal them anywhere -- callers (ryos/ui/app.py) MUST wrap whatever they
do with self.after(0, ...) themselves.
"""
import threading
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .logger import get_logger

_log = get_logger("tray")

try:
    import pystray
    from PIL import Image
    _AVAILABLE = True
except Exception:
    # ryos.ui.app imports this module at load time, so any failure here
    # (missing wheel, or a broken backend on an unusual platform) must not
    # prevent the app itself from importing -- only the tray degrades.
    pystray = None
    Image = None
    _AVAILABLE = False


def _load_tray_image(path: Path):
    """Return a small PIL Image for the tray icon, or None on any failure."""
    if not _AVAILABLE:
        return None
    try:
        img = Image.open(path)
    except Exception:
        _log.debug("Could not open tray icon image %s", path, exc_info=True)
        return None
    # .ico files are multi-frame; Image.open() picks the largest frame by
    # default, which pystray then downscales -- mushy at 16x16. Try to pick
    # a small contained frame explicitly; fall back to the default image.
    try:
        sizes = getattr(img, "info", {}).get("sizes")
        if sizes:
            target = min(sizes, key=lambda s: abs(max(s) - 32))
            img.size = target
            img.load()
    except Exception:
        _log.debug("Could not select small icon frame from %s", path, exc_info=True)
    return img


class TrayIcon:
    def __init__(self, on_show: Callable[[], None], on_exit: Callable[[], None],
                 icon_path: Path, title: Optional[str] = None):
        self._on_show = on_show
        self._on_exit = on_exit
        self._icon_path = icon_path
        self._title = title or f"RYOS v{__version__}"
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._image = _load_tray_image(icon_path)

    @property
    def available(self) -> bool:
        return _AVAILABLE and self._image is not None

    def start(self) -> None:
        if not self.available:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show RYOS", self._on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_exit),
        )
        self._icon = pystray.Icon("RYOS", self._image, self._title, menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:
            _log.debug("Error stopping tray icon", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=1.0)  # let NIM_DELETE run before the process exits
        self._icon = None
