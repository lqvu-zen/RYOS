"""Qt script and pipeline cards.

The Tk cards build every colour into every widget at construction, so a theme
change means tearing the tree down and rebuilding it. These set an
``objectName`` and let the stylesheet do the painting, so re-theming is one
``setStyleSheet`` call on the application.

Layout metrics and the Run/Retry rule come from ``ryos.cardstyle``, shared with
the Tk cards — this module binds palette *keys* to real colours and nothing
else. Per the migration plan these are plain widgets in a scroll area rather
than a QListView with a delegate: it mirrors what exists and ports fast, and
card counts here are in the dozens, not the thousands.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .. import cardstyle
from ..interpreter import _script_tag
from ..themes import ink_on
from .widgets import ScrollingLabel, set_tooltip

# The four button columns every card carries, so a mixed list lines up. The
# pipeline card has no "run with parameter", and issue #3 was that omitting the
# cell misaligned every column after it; issue #7 was that filling it with a
# button-coloured slab made the gap read as a broken control. Here it is an
# empty transparent placeholder of the same fixed width.
BUTTON_WIDTH = 34


class _CardBase(QFrame):
    """Shared chrome: object names, the button strip, and the size policy."""

    def __init__(self, palette: dict, compact: bool, size: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._palette = palette
        self._compact = compact
        self._size = size
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.NoFrame)
        padx, pady = cardstyle.card_padding(compact, size)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(padx, pady, padx, pady)
        self._row.setSpacing(6)

    # -- button strip ------------------------------------------------------
    def _button(self, glyph: str, tooltip: str = "",
                object_name: str = "") -> QPushButton:
        b = QPushButton(glyph)
        b.setFixedWidth(BUTTON_WIDTH)
        if object_name:
            b.setObjectName(object_name)
        if tooltip:
            set_tooltip(b, tooltip)
        return b

    def _spacer(self) -> QWidget:
        """An empty cell the width of a button, so columns line up (#3).

        Transparent rather than button-coloured, so it reads as a gap and not
        as a control whose icon failed to load (#7).
        """
        w = QWidget()
        w.setFixedWidth(BUTTON_WIDTH)
        w.setObjectName("cardSpacer")
        return w

    def _run_button(self, last_status: str | None) -> QPushButton:
        """The Run button, which becomes Retry after a failure."""
        spec = cardstyle.run_button(last_status)
        b = self._button(spec.glyph, spec.tooltip, object_name="run")
        c = self._palette
        # Per-button colours, because the state is per-card rather than
        # per-class; everything else is left to the stylesheet.
        b.setStyleSheet(
            f"QPushButton#run {{ background: {c[spec.bg_key]};"
            f" color: {c[spec.fg_key]}; }}"
            f"QPushButton#run:hover {{ background: {c[spec.hover_key]};"
            f" color: {ink_on(c[spec.hover_fg_key])}; }}")
        b.setProperty("runState", spec.state)
        return b

    def _status_chip(self, status: str | None) -> QLabel | None:
        spec = cardstyle.status_badge(status)
        if spec is None:
            return None
        chip = QLabel(spec.text)
        chip.setObjectName("statusChip")
        c = self._palette
        chip.setStyleSheet(
            f"background: {c[spec.bg_key]}; color: {c[spec.fg_key]};"
            f" padding: 1px 5px; border-radius: 2px; font-weight: 600;")
        return chip


class ScriptCard(_CardBase):
    """One script: name, path, and the four-button strip."""

    run_requested = Signal(int)
    edit_requested = Signal(int)
    favorite_toggled = Signal(int, bool)

    def __init__(self, *, script_id: int, name: str, path: str,
                 palette: dict, compact: bool = False, size: str = "medium",
                 is_favorite: bool = False, last_status: str | None = None,
                 label_color: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(palette, compact, size, parent)
        self.script_id = script_id
        self._name = name

        self.checkbox = QCheckBox()
        self.checkbox.setVisible(False)
        self._row.addWidget(self.checkbox)

        text = QVBoxLayout()
        text.setSpacing(2)
        tag_text, tag_bg = _script_tag(path)
        header = QHBoxLayout()
        header.setSpacing(6)
        if not compact:
            badge = QLabel(tag_text)
            badge.setObjectName("scriptTag")
            badge.setStyleSheet(
                f"background: {tag_bg}; color: {ink_on(tag_bg)};"
                f" padding: 1px 5px; border-radius: 2px; font-size: 8pt;"
                f" font-weight: 700;")
            header.addWidget(badge)
        self.name_label = ScrollingLabel(name)
        self.name_label.setObjectName("cardName")
        if label_color:
            self.name_label.setStyleSheet(f"color: {label_color};")
        header.addWidget(self.name_label, 1)
        chip = self._status_chip(last_status)
        if chip is not None:
            header.addWidget(chip)
        text.addLayout(header)

        if not compact:
            self.path_label = QLabel(path)
            self.path_label.setObjectName("cardPath")
            self.path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            text.addWidget(self.path_label)
        self._row.addLayout(text, 1)

        # Four columns, in the same order as the Tk card.
        self.fav_button = self._button("★" if is_favorite else "☆",
                                       "Remove from favorites" if is_favorite
                                       else "Add to favorites")
        self.edit_button = self._button("⚙", "Edit")
        self.param_button = self._button("▶+", "Run with parameter")
        self.run_button = self._run_button(last_status)
        for b in (self.fav_button, self.edit_button, self.param_button,
                  self.run_button):
            self._row.addWidget(b)

        self.run_button.clicked.connect(
            lambda: self.run_requested.emit(self.script_id))
        self.edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.script_id))
        self.fav_button.clicked.connect(
            lambda: self.favorite_toggled.emit(self.script_id, not is_favorite))


class PipelineCard(_CardBase):
    """One pipeline: name, step count, and the same four columns."""

    run_requested = Signal(int)
    edit_requested = Signal(int)
    favorite_toggled = Signal(int, bool)

    def __init__(self, *, pipeline_id: int, name: str, step_count: int,
                 palette: dict, compact: bool = False, size: str = "medium",
                 is_favorite: bool = False, last_status: str | None = None,
                 label_color: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(palette, compact, size, parent)
        self.pipeline_id = pipeline_id
        self._name = name

        text = QVBoxLayout()
        text.setSpacing(2)
        header = QHBoxLayout()
        header.setSpacing(6)
        if not compact:
            badge = QLabel("⚡ PIPELINE")
            badge.setObjectName("pipeTag")
            accent = palette.get("pipe_accent", palette["accent"])
            badge.setStyleSheet(
                f"background: {accent}; color: {ink_on(accent)};"
                f" padding: 1px 5px; border-radius: 2px; font-size: 8pt;"
                f" font-weight: 700;")
            header.addWidget(badge)
        self.name_label = ScrollingLabel(name)
        self.name_label.setObjectName("cardName")
        if label_color:
            self.name_label.setStyleSheet(f"color: {label_color};")
        header.addWidget(self.name_label, 1)
        chip = self._status_chip(last_status)
        if chip is not None:
            header.addWidget(chip)
        text.addLayout(header)

        if not compact:
            plural = "s" if step_count != 1 else ""
            self.steps_label = QLabel(f"{step_count} step{plural}")
            self.steps_label.setObjectName("cardPath")
            text.addWidget(self.steps_label)
        self._row.addLayout(text, 1)

        self.fav_button = self._button("★" if is_favorite else "☆",
                                       "Remove from favorites" if is_favorite
                                       else "Add to favorites")
        self.edit_button = self._button("⚙", "Edit")
        self.spacer = self._spacer()          # where ▶+ sits on a script card
        self.run_button = self._run_button(last_status)
        for w in (self.fav_button, self.edit_button, self.spacer,
                  self.run_button):
            self._row.addWidget(w)

        self.run_button.clicked.connect(
            lambda: self.run_requested.emit(self.pipeline_id))
        self.edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.pipeline_id))
        self.fav_button.clicked.connect(
            lambda: self.favorite_toggled.emit(self.pipeline_id, not is_favorite))


def build_cards(parent: QWidget, records, palette: dict, *,
                compact: bool = False, size: str = "medium",
                on_run: Callable[[int], None] | None = None) -> list:
    """Build a card per record. Helper for the smoke checks and the shell."""
    cards = []
    for rec in records:
        if rec.get("kind") == "pipeline":
            card = PipelineCard(pipeline_id=rec["id"], name=rec["name"],
                                step_count=rec.get("steps", 0),
                                palette=palette, compact=compact, size=size,
                                is_favorite=rec.get("favorite", False),
                                last_status=rec.get("status"), parent=parent)
        else:
            card = ScriptCard(script_id=rec["id"], name=rec["name"],
                              path=rec.get("path", ""), palette=palette,
                              compact=compact, size=size,
                              is_favorite=rec.get("favorite", False),
                              last_status=rec.get("status"), parent=parent)
        if on_run is not None:
            card.run_requested.connect(on_run)
        cards.append(card)
    return cards
