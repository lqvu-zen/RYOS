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
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .. import cardstyle, scriptform
from ..interpreter import _script_tag
from ..themes import ink_on
from .widgets import ElidedLabel, ScrollingLabel, set_tooltip

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

    # -- dragging -----------------------------------------------------------
    #: Runs the drag once it starts. None means QDrag.exec, which blocks until
    #: a real mouse button is released; tests put a recorder here.
    drag_runner = None
    #: Set by the CardList that holds the card; a card outside one is inert.
    drag_payload = None
    _press_pos = None

    def mousePressEvent(self, event) -> None:          # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:           # noqa: N802
        if (self.drag_payload is not None and self._press_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            from .dragdrop import start_drag
            if start_drag(self, self.drag_payload, self._press_pos,
                          event.position().toPoint(), run=self.drag_runner):
                self._press_pos = None
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:        # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)

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
        b = self._button("", "", object_name="run")
        self._style_run_button(b, last_status)
        return b

    def set_last_status(self, status: str | None) -> None:
        """Show a run's outcome as it lands: Retry after a failure, and the
        chip, without rebuilding the card (which a reload would do, losing
        select-mode ticks and the scroll position)."""
        if status == self._last_status:
            return
        self._last_status = status
        self._style_run_button(self.run_button, status)
        if self.status_chip is not None:
            self._header.removeWidget(self.status_chip)
            self.status_chip.deleteLater()
        self.status_chip = self._status_chip(status)
        if self.status_chip is not None:
            self._header.addWidget(self.status_chip)

    def _style_run_button(self, b: QPushButton, last_status: str | None) -> None:
        spec = cardstyle.run_button(last_status)
        b.setText(spec.glyph)
        set_tooltip(b, spec.tooltip)
        c = self._palette
        # Per-button colours, because the state is per-card rather than
        # per-class; everything else is left to the stylesheet.
        b.setStyleSheet(
            f"QPushButton#run {{ background: {c[spec.bg_key]};"
            f" color: {c[spec.fg_key]}; }}"
            f"QPushButton#run:hover {{ background: {c[spec.hover_key]};"
            f" color: {ink_on(c[spec.hover_fg_key])}; }}")
        b.setProperty("runState", spec.state)

    def _tag_badges(self, header: QHBoxLayout, badges) -> None:
        """`cardstyle.TagBadge`s beside the name, drawn as the Tk cards draw them."""
        self.badges: list[QLabel] = []
        for spec in badges or ():
            badge = QLabel(spec.text)
            badge.setObjectName("tagBadge")
            badge.setStyleSheet(
                f"background: {self._palette[spec.bg_key]};"
                f" color: {self._palette['fg_on_dark']}; padding: 1px 5px;"
                f" border-radius: 2px; font-size: 8pt; font-weight: 700;")
            set_tooltip(badge, spec.tooltip)
            header.addWidget(badge)
            self.badges.append(badge)

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
    run_with_param_requested = Signal(int)
    edit_requested = Signal(int)
    favorite_toggled = Signal(int, bool)

    def set_last_run(self, iso: str | None) -> None:
        """Update when it last ran, in place (see `set_last_status`)."""
        if self.last_run_label is not None:
            self.last_run_label.setText(cardstyle.last_run_text(iso))

    def selected_params(self, fallback: str) -> str:
        """What Run should pass: the drop-down's choice, else ``fallback``."""
        if self.params_combo is None:
            return fallback
        return scriptform.params_from_choice(self.params_combo.currentText())

    def __init__(self, *, script_id: int, name: str, path: str,
                 palette: dict, compact: bool = False, size: str = "medium",
                 is_favorite: bool = False, last_status: str | None = None,
                 label_color: str | None = None,
                 param_choices: tuple | None = None,
                 badges=(),
                 base_dir: str = "", last_run: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(palette, compact, size, parent)
        self.script_id = script_id
        self._name = name
        self.params_combo: QComboBox | None = None

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
        self._tag_badges(header, () if compact else badges)
        self.name_label = ScrollingLabel(name)
        self.name_label.setObjectName("cardName")
        if label_color:
            self.name_label.setStyleSheet(f"color: {label_color};")
        header.addWidget(self.name_label, 1)
        self._header = header
        self._last_status = last_status
        self.status_chip = self._status_chip(last_status)
        if self.status_chip is not None:
            header.addWidget(self.status_chip)
        text.addLayout(header)

        self.last_run_label: QLabel | None = None
        if not compact:
            # Relative to the group's base folder, as in Tk; the tooltip
            # keeps the whole path.
            self.path_label = ElidedLabel(cardstyle.display_path(path, base_dir))
            self.path_label.setObjectName("cardPath")
            self.path_label.setToolTip(path)
            # Not text-selectable, matching the Tk card: a selectable label
            # takes the mouse for itself, so dragging the card by its path
            # would select text instead of moving the card.
            sub = QHBoxLayout()
            sub.setSpacing(6)
            sub.addWidget(self.path_label, 1)
            self.last_run_label = QLabel(cardstyle.last_run_text(last_run))
            self.last_run_label.setObjectName("cardPath")
            self.last_run_label.setToolTip("Last run")
            sub.addWidget(self.last_run_label)
            text.addLayout(sub)
        # The preset drop-down: which parameters Run passes. Offered, as in
        # Tk, only when the script has presets (`scriptform.card_param_choices`).
        if param_choices and not compact:
            entries, selected = param_choices
            self.params_combo = QComboBox()
            self.params_combo.setObjectName("paramCombo")
            # Its entries are parameters of any length; the card must not
            # grow to fit the longest.
            self.params_combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.params_combo.setMinimumContentsLength(6)
            self.params_combo.addItems(entries)
            self.params_combo.setCurrentText(selected)
            text.addWidget(self.params_combo)
        self._row.addLayout(text, 1)

        # Four columns, in the same order as the Tk card.
        self.fav_button = self._button("★" if is_favorite else "☆",
                                       "Remove from favorites" if is_favorite
                                       else "Add to favorites",
                                       object_name="favOn" if is_favorite else "")
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
        self.param_button.clicked.connect(
            lambda: self.run_with_param_requested.emit(self.script_id))
        self.fav_button.clicked.connect(
            lambda: self.favorite_toggled.emit(self.script_id, not is_favorite))


class PipelineCard(_CardBase):
    """One pipeline: name, step count, and the same four columns."""

    run_requested = Signal(int)
    edit_requested = Signal(int)
    favorite_toggled = Signal(int, bool)
    steps_clicked = Signal(int)

    def __init__(self, *, pipeline_id: int, name: str, step_count: int,
                 palette: dict, compact: bool = False, size: str = "medium",
                 is_favorite: bool = False, last_status: str | None = None,
                 label_color: str | None = None,
                 badges=(), step_names=None,
                 parent: QWidget | None = None):
        super().__init__(palette, compact, size, parent)
        self.pipeline_id = pipeline_id
        # Drawn with the pipeline accent down its left edge (stylesheet).
        self.setProperty("kind", "pipeline")
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
        self._tag_badges(header, () if compact else badges)
        self.name_label = ScrollingLabel(name)
        self.name_label.setObjectName("cardName")
        if label_color:
            self.name_label.setStyleSheet(f"color: {label_color};")
        header.addWidget(self.name_label, 1)
        self._header = header
        self._last_status = last_status
        self.status_chip = self._status_chip(last_status)
        if self.status_chip is not None:
            header.addWidget(self.status_chip)
        text.addLayout(header)

        if not compact:
            # The count and the first steps' names, as in Tk; elided to fit.
            if step_names is None:
                plural = "s" if step_count != 1 else ""
                self.steps_label = ElidedLabel(f"{step_count} step{plural}",
                                               mode=Qt.TextElideMode.ElideRight)
            else:
                self.steps_label = ElidedLabel(cardstyle.steps_summary(step_names),
                                               mode=Qt.TextElideMode.ElideRight)
            self.steps_label.setObjectName("cardPath")
            self.steps_label.setCursor(Qt.CursorShape.PointingHandCursor)
            # A click lists the steps, as in Tk. Release, not press: the press
            # still reaches the card, which may be starting a drag.
            self.steps_label.mouseReleaseEvent = (
                lambda _e: self.steps_clicked.emit(self.pipeline_id))
            text.addWidget(self.steps_label)
        self._row.addLayout(text, 1)

        self.fav_button = self._button("★" if is_favorite else "☆",
                                       "Remove from favorites" if is_favorite
                                       else "Add to favorites",
                                       object_name="favOn" if is_favorite else "")
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
