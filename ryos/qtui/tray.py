"""The Qt tray icon: `QSystemTrayIcon`, fed the same snapshot as the Tk one.

The tooltip and menu contents are `traypolicy`'s, shared with the pystray
tray. Unlike pystray, `QSystemTrayIcon` lives on the UI thread, so its
actions need no marshalling: they are signals, connected like any other.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import __version__, traypolicy


class Tray(QObject):
    """Shows RYOS in the system tray, with its running jobs in the menu."""

    show_requested = Signal()
    exit_requested = Signal()
    job_requested = Signal(int)

    def __init__(self, icon: QIcon, parent: QObject | None = None, *,
                 title: str | None = None):
        super().__init__(parent)
        self._base_title = title or f"RYOS v{__version__}"
        self._jobs: list[tuple[int, str]] = []
        self.icon = QSystemTrayIcon(icon, self)
        self.menu = QMenu()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self._rebuild()

    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def start(self) -> None:
        if self.available:
            self.icon.show()

    def stop(self) -> None:
        self.icon.hide()
        self._jobs = []
        self._rebuild()

    def set_jobs(self, jobs) -> None:
        """Replace the running-job snapshot: ``(job_id, label)`` pairs."""
        jobs = [(int(jid), str(label)) for jid, label in jobs]
        if jobs == self._jobs:
            return
        self._jobs = jobs
        self._rebuild()

    @property
    def tooltip(self) -> str:
        return self.icon.toolTip()

    def _rebuild(self) -> None:
        self.icon.setToolTip(traypolicy.tray_title(
            [label for _, label in self._jobs], self._base_title))
        self.menu.clear()
        for entry in traypolicy.tray_menu(self._jobs):
            if entry.key is None:
                self.menu.addSeparator()
                continue
            action = self.menu.addAction(entry.label)
            action.setData(entry.key)
            if entry.default:
                font = action.font()
                font.setBold(True)
                action.setFont(font)
            action.triggered.connect(lambda _c=False, k=entry.key: self._pick(k))

    def _pick(self, key: str) -> None:
        job_id = traypolicy.job_from_key(key)
        if job_id is not None:
            self.job_requested.emit(job_id)
        elif key == traypolicy.SHOW:
            self.show_requested.emit()
        elif key == traypolicy.EXIT:
            self.exit_requested.emit()

    def _on_activated(self, reason) -> None:
        # A click on the icon is "Show RYOS", as it is with pystray's default.
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_requested.emit()
