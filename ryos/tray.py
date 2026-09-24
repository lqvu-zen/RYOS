"""System tray icon (minimize/close-to-tray). No ryos.ui.* imports.

The callbacks passed into TrayIcon fire on pystray's own thread (the
Win32 message pump thread), NOT the Tk main thread. This module does not
marshal them anywhere -- callers (ryos/ui/app.py) MUST wrap whatever they
do with self.after(0, ...) themselves.

set_jobs() goes the other way: the UI thread hands over a plain snapshot of
what is running, which becomes the icon's tooltip and its menu entries. Only
that snapshot crosses the boundary -- never a Job, a registry, or a widget --
so the tray never reads state the UI thread is concurrently mutating.
"""
import threading
from pathlib import Path
from typing import Any, Callable, Optional

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
    #
    # This is NOT a statement that pystray is optional: pyproject declares it
    # as a hard dependency so every user gets a tray. The guard is for a
    # broken install, and it is what lets the test suite and CI run without
    # the package at all.
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


# The tooltip, the menu contents and the clamp live in traypolicy, shared
# with the Qt tray; re-exported here for existing callers and tests.
from .traypolicy import (EXIT, MENU_LABEL_MAX, SHOW, TIP_MAX,  # noqa: E402,F401
                         _ellipsize, job_from_key, tray_menu, tray_title)


class TrayIcon:
    def __init__(self, on_show: Callable[[], None], on_exit: Callable[[], None],
                 icon_path: Path, title: Optional[str] = None,
                 on_job: Optional[Callable[[int], None]] = None):
        self._on_show = on_show
        self._on_exit = on_exit
        self._on_job = on_job            # (job_id) -> None, on pystray's thread
        self._icon_path = icon_path
        self._base_title = title or f"RYOS v{__version__}"
        self._title = self._base_title
        # pystray.Icon once started. Any, because pystray is an optional
        # dependency with no stubs -- the guards around it are what keep
        # this honest, not the annotation.
        self._icon: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._image = _load_tray_image(icon_path)
        self._jobs: list[tuple[int, str]] = []

    @property
    def available(self) -> bool:
        return _AVAILABLE and self._image is not None

    def _job_handler(self, job_id: int):
        """Menu action for one running job. Fires on pystray's thread."""
        def _activate():
            if self._on_job is not None:
                self._on_job(job_id)
        return _activate

    def _build_menu(self):
        """Menu descriptor for the current snapshot: jobs first, then the
        standing Show/Exit entries. 'Show RYOS' stays the default action, so a
        left-click still restores the window no matter what is running."""
        items = []
        for entry in tray_menu(self._jobs):
            if entry.key is None:
                items.append(pystray.Menu.SEPARATOR)
                continue
            job_id = job_from_key(entry.key)
            action = (self._job_handler(job_id) if job_id is not None
                      else self._on_show if entry.key == SHOW else self._on_exit)
            items.append(pystray.MenuItem(entry.label, action,
                                          default=entry.default))
        return pystray.Menu(*items)

    def set_jobs(self, jobs) -> None:
        """Replace the running-job snapshot behind the tooltip and menu.

        `jobs` is an iterable of (job_id, label). Call from the UI thread. It
        returns immediately when nothing visible changed, so the per-step
        pipeline renames don't turn into a stream of Win32 calls.
        """
        jobs = [(int(jid), str(label)) for jid, label in jobs]
        if jobs == self._jobs:
            return
        self._jobs = jobs
        self._apply_title()
        if self._icon is None:
            return
        try:
            # Assigning .menu runs pystray's update_menu(), its documented way
            # to refresh a menu whose contents changed outside the menu itself.
            self._icon.menu = self._build_menu()
        except Exception:
            _log.debug("Could not refresh tray menu", exc_info=True)

    def _apply_title(self) -> None:
        title = tray_title([label for _, label in self._jobs], self._base_title)
        if title == self._title:
            return
        self._title = title
        if self._icon is None:
            return
        try:
            self._icon.title = title
        except Exception:
            _log.debug("Could not update tray tooltip", exc_info=True)

    def start(self) -> None:
        # `available` already covers this, but it is a property over a module
        # global, so narrowing has to be restated where pystray is used.
        if not self.available or pystray is None:
            return
        self._icon = pystray.Icon("RYOS", self._image, self._title,
                                  self._build_menu())
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        # The snapshot resets whether or not an icon is live, so a stopped tray
        # never keeps reporting jobs that ended while it was down.
        self._jobs = []
        self._title = self._base_title
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:
            _log.debug("Error stopping tray icon", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=1.0)  # let NIM_DELETE run before the process exits
        self._icon = None
