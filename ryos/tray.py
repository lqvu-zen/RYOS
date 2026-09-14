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


# NOTIFYICONDATAW.szTip is WCHAR[128]; ctypes raises rather than truncating,
# so an over-long tooltip has to be clamped here or the update would fail.
TIP_MAX = 127
MENU_LABEL_MAX = 60


def _ellipsize(text: str, limit: int) -> str:
    """Clamp text to `limit` characters, marking the cut with an ellipsis."""
    text = " ".join(text.split())          # tooltips collapse whitespace anyway
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def tray_title(job_names, base: str) -> str:
    """Tooltip text for a set of running jobs. Pure; `base` is the idle text.

    One job shows its full label (that is the interesting case when you are
    waiting on a pipeline); several collapse to a count plus names, because the
    128-character cap would truncate them into uselessness otherwise.
    """
    job_names = list(job_names)
    if not job_names:
        return _ellipsize(base, TIP_MAX)
    if len(job_names) == 1:
        return _ellipsize(f"{base} — {job_names[0]}", TIP_MAX)
    return _ellipsize(
        f"{base} — {len(job_names)} running: " + ", ".join(job_names), TIP_MAX)


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
        self._icon = None
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
        for job_id, label in self._jobs:
            items.append(pystray.MenuItem(_ellipsize(label, MENU_LABEL_MAX),
                                          self._job_handler(job_id)))
        if items:
            items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Show RYOS", self._on_show, default=True))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Exit", self._on_exit))
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
        if not self.available:
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
