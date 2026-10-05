"""The Activity bar down the maximised window's right edge.

What is running (the window's own running list, lent here while maximised,
with its Stop buttons), what runs next, and what ran last. What it lists and
how it says it comes from `ryos.activity`; a line is a button that shows its
item in the detail pane.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from .. import activity, cardstyle, detail
from ..themes import _readable_on
from .detail import _clear
from .icons import IconLabel
from .widgets import ElidedLabel


class ActivityPanel(QFrame):
    """Running now, Up next and Recent, in boxes under one heading."""

    def __init__(self, palette: dict, on_open: Callable[[str, int, str], None],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("activity")
        self.setMinimumWidth(220)
        self._palette = palette
        self._on_open = on_open
        self._running = None
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 16, 16, 12)
        col.setSpacing(8)
        title = QLabel(activity.TITLE)
        title.setObjectName("activityTitle")
        col.addWidget(title)

        def box(heading: str):
            label = QLabel(heading)
            label.setObjectName("detailHeading")
            col.addSpacing(4)
            col.addWidget(label)
            frame = QFrame()
            frame.setObjectName("activityBox")
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(8, 6, 6, 6)
            inner.setSpacing(2)
            col.addWidget(frame)
            return inner

        self.running_slot = box(activity.RUNNING_NOW)
        self.nothing_running = self._quiet(activity.NOTHING_RUNNING)
        self.running_slot.addWidget(self.nothing_running)
        self.up_slot = box(activity.UP_NEXT)
        self.recent_slot = box(activity.RECENT)
        col.addStretch(1)
        self.up_entries: list = []
        self.recent_entries: list = []

    @staticmethod
    def _quiet(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardPath")
        label.setContentsMargins(4, 4, 4, 4)
        return label

    # -- the running list, lent while maximised ----------------------------------------
    def host_running(self, section) -> None:
        """Show the window's running list here, without its own heading."""
        self._running = section
        section.heading.hide()
        section.set_narrow(True)
        self.running_slot.addWidget(section)
        section.changed.connect(self._sync_running)
        self._sync_running()

    def release_running(self, section) -> None:
        if self._running is section:
            section.changed.disconnect(self._sync_running)
            self._running = None
        section.heading.show()
        section.set_narrow(False)
        self.nothing_running.show()

    def _sync_running(self, *_args) -> None:
        busy = self._running is not None and self._running.count > 0
        self.nothing_running.setVisible(not busy)

    # -- the lists -----------------------------------------------------------------------
    def show_entries(self, up_next: list, recent: list) -> None:
        self.up_entries, self.recent_entries = list(up_next), list(recent)
        for slot, entries, empty, tab in (
                (self.up_slot, self.up_entries, activity.NOTHING_SCHEDULED,
                 detail.OVERVIEW_TAB),
                (self.recent_slot, self.recent_entries, activity.NO_RUNS,
                 detail.HISTORY_TAB)):
            _clear(slot)
            if not entries:
                slot.addWidget(self._quiet(empty))
            for entry in entries:
                slot.addWidget(self._row(entry, tab))

    def _row(self, entry, tab: str) -> QPushButton:
        """One line: a mark, the name, and what to say about it."""
        c = self._palette
        b = QPushButton()
        b.setObjectName("activityRow")
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setAccessibleName(f"{entry.name}, {entry.meta.replace('  ·  ', ', ')}")
        line = QHBoxLayout(b)
        line.setContentsMargins(6, 5, 6, 5)
        line.setSpacing(8)
        spec = cardstyle.status_badge(entry.status)
        if spec is None:
            mark = IconLabel("clock", role="muted", size=14, palette=c)
        else:
            mark = QLabel("●")
            mark.setStyleSheet(
                f"color: {_readable_on(c[spec.bg_key], (c['card_bg'], c['card_hover']))};"
                " font-size: 9pt; background: transparent;")
        mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        line.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(0)
        for text, name in ((entry.name, "activityName"), (entry.meta, "cardPath")):
            label = ElidedLabel(text)
            label.setObjectName(name)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            words.addWidget(label)
        line.addLayout(words, 1)
        # A button does not grow to the layout inside it: ask for its height.
        b.setMinimumHeight(line.sizeHint().height())
        b.clicked.connect(lambda _c=False, e=entry: self._on_open(e.kind, e.item_id, tab))
        return b

    def set_palette(self, palette: dict) -> None:
        self._palette = palette
        self.show_entries(self.up_entries, self.recent_entries)
