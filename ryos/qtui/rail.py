"""The rail down the maximised window's left edge: the places in the app.

Which places, in what order, comes from `ryos.detail.RAIL`; this draws them
as icon buttons and says which was pressed. What a place does is the
window's business (`MainWindow.go_to`).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from .. import detail
from .icons import IconButton
from .widgets import set_tooltip

#: The rail's width, and its buttons' side.
WIDTH = 56
BUTTON = 40


class Rail(QFrame):
    """A column of place buttons, the working ones at the top."""

    def __init__(self, palette: dict, on_place: Callable[[str], None],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("rail")
        self.setFixedWidth(WIDTH)
        col = QVBoxLayout(self)
        col.setContentsMargins(8, 10, 8, 10)
        col.setSpacing(6)
        self.buttons: dict[str, IconButton] = {}
        feet = []
        for place in detail.RAIL:
            b = IconButton(place.icon, role="muted", hover_role="text", size=20,
                           palette=palette)
            b.setObjectName("railButton")
            b.setFixedSize(BUTTON, BUTTON)
            b.setAccessibleName(place.name)
            set_tooltip(b, place.name)
            b.clicked.connect(lambda _c=False, key=place.key: on_place(key))
            self.buttons[place.key] = b
            if place.foot:
                feet.append(b)
            else:
                col.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addStretch(1)
        for b in feet:
            col.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        self.set_current("library")

    def set_current(self, key: str) -> None:
        """Mark the place the window is showing."""
        icons = {place.key: place.icon for place in detail.RAIL}
        for k, b in self.buttons.items():
            on = k == key
            b.set_shape(icons[k], role="link" if on else "muted")
            if bool(b.property("on")) != on:
                b.setProperty("on", on)
                b.style().unpolish(b)
                b.style().polish(b)
