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

A card comes in three shapes:

* a **row** (the default): two lines -- kind, name and outcome; then the path
  or the steps, and the preset Run will pass -- beside a round Run. Its other
  buttons (star, edit, run with parameters) show only under the pointer, in
  space kept for them, so the row reads as one action and nothing shifts.
* a **compact** row: one line -- star, name, kind, outcome, Run.
* a **chip**, for the Favorites strip: a pill of name and Run.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Property, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from .. import cardstyle, scriptform
from ..interpreter import _script_tag
from ..themes import _readable_on, ink_on
from .icons import IconButton, IconLabel
from .widgets import ElidedLabel, ScrollingLabel, literal, set_tooltip

# The button columns every card carries, so a mixed list lines up. The
# pipeline card has no "run with parameter", and issue #3 was that omitting the
# cell misaligned every column after it; issue #7 was that filling it with a
# button-coloured slab made the gap read as a broken control. Here it is an
# empty transparent placeholder of the same fixed width.
BUTTON_WIDTH = 32
#: The longest a chip's name gets before it is shortened with an ellipsis.
CHIP_NAME_WIDTH = 170


class _CardBase(QFrame):
    """Shared chrome: object names, the button strip, and the size policy.

    A card is one row of its section's panel: no box of its own, a hairline
    under it, and a strip of the accent down its left edge. Its words are
    coloured text rather than filled chips, and its buttons are quiet glyphs
    beside a round Run -- the one filled thing on the row.
    """

    #: A click on the card itself, not on one of its buttons.
    activated = Signal()
    #: Ctrl+C / Ctrl+V on the focused row: copy it, or paste into its group.
    copy_requested = Signal()
    paste_requested = Signal()

    def __init__(self, palette: dict, compact: bool, size: str,
                 parent: QWidget | None = None, *, chip: bool = False):
        super().__init__(parent)
        self._palette = palette
        # A chip is a smaller compact row: everything compact holds for it.
        self._chip = chip
        self._compact = compact or chip
        self._size = size
        self._hover_only: list[QWidget] = []
        self._focus_edge = QColor(palette.get("accent", "#3a7bd5"))
        self.setObjectName("card")
        # The row is the list's keyboard stop (its buttons are not): arrows
        # move between rows, Enter runs, F2 edits, the Menu key does the rest.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("compact", self._compact)
        self.setProperty("chip", chip)
        self.setFrameShape(QFrame.Shape.NoFrame)
        padx, pady = (cardstyle.CHIP_PADDING if chip
                      else cardstyle.card_padding(self._compact, size))
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(padx, pady, padx if not chip else 3, pady)
        self._row.setSpacing(6)
        if chip:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _ink(self, color: str) -> str:
        """``color``, shaded until it reads as text on the row, hovered or not."""
        c = self._palette
        return _readable_on(color, (c["card_bg"], c["card_hover"]))

    def _tag(self, text: str, color: str, object_name: str) -> QLabel:
        """A kind label -- BATCH, PIPELINE -- as small coloured capitals."""
        label = QLabel(text.upper())
        label.setObjectName(object_name)
        label.setStyleSheet(f"color: {self._ink(color)}; font-size: 8pt;"
                            f" font-weight: 700; letter-spacing: 0.4px;")
        return label

    def _name_label(self, name: str, label_color: str | None) -> QWidget:
        """The name: scrolling when a row cuts it short; on a chip, shortened
        with an ellipsis instead, since a chip is sized to its text."""
        if self._chip:
            label: QWidget = QLabel()
            fm = label.fontMetrics()
            label.setText(fm.elidedText(name, Qt.TextElideMode.ElideRight,
                                        CHIP_NAME_WIDTH))
            if label.text() != name:
                label.setToolTip(name)
        else:
            label = ScrollingLabel(name)
        label.setObjectName("cardName")
        if label_color:
            label.setStyleSheet(f"color: {label_color};")
        return label

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
        # A press that did not become a drag is a click: it chooses the card
        # (the maximised layout shows the chosen one beside the list).
        clicked = (self._press_pos is not None
                   and event.button() == Qt.MouseButton.LeftButton)
        self._press_pos = None
        super().mouseReleaseEvent(event)
        if clicked:
            self.activated.emit()

    # -- the keyboard --------------------------------------------------------------
    #: Arrow and paging keys, by the move they make (`sections.step_row`).
    _STEPS = {Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
              Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
              Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown"}

    def keyPressEvent(self, event) -> None:            # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.run_button.click()
            return
        if key == Qt.Key.Key_F2:
            self.edit_button.click()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
            return
        tick = getattr(self, "checkbox", None)
        if key == Qt.Key.Key_Space and tick is not None and tick.isVisible():
            tick.toggle()
            return
        step = self._STEPS.get(key)
        page = self._page()
        if step is not None and page is not None:
            page.step_focus(self, step)
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:             # noqa: N802
        super().focusInEvent(event)
        # A click on a row (or its Run) focuses the row too; only a keyboard
        # arrival is marked, or every click would leave a highlight behind.
        # Coming back from a menu or a dialog keeps whatever it was.
        if event.reason() not in self._PASSING:
            self._set_keyboard_focus(event.reason() != Qt.FocusReason.MouseFocusReason)
        # Maximised, the detail pane follows the focused row, as it follows
        # a clicked one.
        self.activated.emit()

    def focusOutEvent(self, event) -> None:            # noqa: N802
        super().focusOutEvent(event)
        if event.reason() not in self._PASSING:
            self._set_keyboard_focus(False)

    #: Focus lost to a menu or another window, and got back from one.
    _PASSING = (Qt.FocusReason.PopupFocusReason, Qt.FocusReason.ActiveWindowFocusReason)

    def _set_keyboard_focus(self, on: bool) -> None:
        if bool(self.property("kbfocus")) != on:
            self.setProperty("kbfocus", on)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    # The outline's colour, set by the stylesheet (``qproperty-focusEdge``) so
    # it follows a theme change like every other colour.
    def _get_focus_edge(self) -> QColor:
        return self._focus_edge

    def _set_focus_edge(self, color) -> None:
        self._focus_edge = QColor(color)
        self.update()

    focusEdge = Property(QColor, _get_focus_edge, _set_focus_edge)

    def paintEvent(self, event) -> None:               # noqa: N802
        super().paintEvent(event)
        # Painted over the row rather than a stylesheet border, which would
        # move the row's contents as the focus arrives. A chip has a border
        # already; the stylesheet recolours it.
        if self._chip or not self.property("kbfocus"):
            return
        p = QPainter(self)
        p.setPen(QPen(self._focus_edge, 2))
        p.drawRect(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.end()

    def _page(self):
        w = self.parentWidget()
        while w is not None and not hasattr(w, "step_focus"):
            w = w.parentWidget()
        return w

    # -- the buttons that wait for the pointer --------------------------------
    def enterEvent(self, event) -> None:               # noqa: N802
        self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:               # noqa: N802
        self.set_hovered(False)
        super().leaveEvent(event)

    def set_hovered(self, on: bool) -> None:
        """Show or hide the buttons a row keeps for the pointer. Their space
        stays either way, so the name and Run never move."""
        for w in self._hover_only:
            w.setVisible(on)

    def _wait_for_hover(self, *widgets: QWidget) -> None:
        for w in widgets:
            policy = w.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            w.setSizePolicy(policy)
            w.hide()
            self._hover_only.append(w)

    # -- button strip ------------------------------------------------------
    def _button(self, shape: str, tooltip: str = "", object_name: str = "",
                role: str = "muted", hover_role: str = "text",
                size: int = 16) -> IconButton:
        """A quiet button showing one of the app's icons (`icons.py`)."""
        b = IconButton(shape, role=role, hover_role=hover_role, size=size,
                       palette=self._palette)
        # Reached through the row's keys and menu, not by Tab: four stops a
        # row made the list a slog to cross.
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        """The Run button, which becomes Retry after a failure: a circle,
        smaller on a compact row, smaller still on a chip."""
        side = (cardstyle.CHIP_RUN_DIAMETER if self._chip
                else cardstyle.RUN_DIAMETER[self._compact])
        b = self._button("play", "", object_name="run", size=max(10, side * 7 // 16))
        b.setFixedSize(side, side)
        self._style_run_button(b, last_status)
        return b

    def _fav_button(self, is_favorite: bool) -> QPushButton:
        if is_favorite:
            return self._button("star-filled", "Remove from favorites",
                                object_name="favOn", role="star", hover_role="star")
        return self._button("star", "Add to favorites")

    def _lay_out_buttons(self, fav, middle, run, is_favorite: bool) -> None:
        """The strip: star, the middle cells, Run.

        A row shows Run, and the star when it is a favourite; the rest wait
        for the pointer. A compact row is a list to run from: the star first,
        as a list's mark, and Run -- Edit and the rest stay on the right-click
        menu. A chip is its name and Run.
        """
        if self._chip:
            self._row.addWidget(fav)
            fav.hide()
            for w in middle:
                w.hide()
        elif self._compact:
            # Just before the name, which is the last thing laid out so far
            # (after the select-mode tick, on a card that has one).
            self._row.insertWidget(self._row.count() - 1, fav)
            for w in middle:
                w.hide()
        else:
            # The star next to Run, so a favourite's gold star sits with the
            # one button that always shows, not out in the row.
            self._wait_for_hover(*middle)
            if not is_favorite:
                self._wait_for_hover(fav)
            for w in middle:
                self._row.addWidget(w)
            self._row.addWidget(fav)
            self._row.addWidget(run)
            return
        for w in middle:
            self._row.addWidget(w)
        self._row.addWidget(run)

    def set_own_run(self, on: bool) -> None:
        """Run becomes Stop while this item's own run is going."""
        if on == getattr(self, "_own_run", False):
            return
        self._own_run = on
        self._style_run_button(self.run_button, self._last_status)

    def _press_run(self, item_id: int) -> None:
        if getattr(self, "_own_run", False):
            self.stop_requested.emit(item_id)
        else:
            self.run_requested.emit(item_id)

    def set_last_status(self, status: str | None) -> None:
        """Show a run's outcome as it lands: Retry after a failure, and the
        chip, without rebuilding the card (which a reload would do, losing
        select-mode ticks and the scroll position)."""
        if status == self._last_status:
            return
        self._last_status = status
        self._style_run_button(self.run_button, status)
        home = (self._header if self._result_slot is None
                else self._result_slot.layout())
        if self.status_chip is not None:
            home.removeWidget(self.status_chip)
            self.status_chip.deleteLater()
        self.status_chip = self._status_chip(status)
        if self.status_chip is not None:
            home.addWidget(self.status_chip)

    def _add_status(self, header: QHBoxLayout, status: str | None) -> None:
        """The outcome chip, last in the header. On a compact row it sits in
        a slot as wide as the widest outcome, kept even when empty, so the
        kind tag before it lines up down the list whatever each row's
        outcome (issue #10)."""
        self._result_slot: QWidget | None = None
        if self._compact and not self._chip:
            probe = self._status_chip("retrying")
            probe.ensurePolished()
            width = probe.sizeHint().width()
            probe.deleteLater()
            self._result_slot = QWidget()
            self._result_slot.setObjectName("resultSlot")
            self._result_slot.setFixedWidth(width)
            slot = QHBoxLayout(self._result_slot)
            slot.setContentsMargins(0, 0, 0, 0)
            slot.setSpacing(0)
            header.addWidget(self._result_slot)
        self.status_chip = self._status_chip(status)
        if self.status_chip is not None:
            (header if self._result_slot is None
             else self._result_slot.layout()).addWidget(self.status_chip)

    def _style_run_button(self, b: QPushButton, last_status: str | None) -> None:
        spec = cardstyle.run_button(last_status, getattr(self, "_own_run", False))
        c = self._palette
        b.set_shape(spec.icon)
        # The icon in the fill's own ink, and in the hover fill's under the
        # pointer -- the retry red and its dark hover need different inks.
        fg = ink_on(c[spec.fg_key]) if spec.is_stop else c[spec.fg_key]
        b.set_colors(fg, ink_on(c[spec.hover_fg_key]))
        set_tooltip(b, spec.tooltip)
        # The tooltip explains; the name is the action.
        verb = "Stop" if spec.is_stop else "Retry" if spec.is_retry else "Run"
        b.setAccessibleName(f"{verb} {self._name}")
        c = self._palette
        # Per-button colours, because the state is per-card rather than
        # per-class; everything else is left to the stylesheet. The radius
        # is here too: it is half the diameter, which only the card knows.
        # So is the size: a stylesheet's min-height replaces setFixedSize's,
        # and the layout then squeezed the circle flat.
        side = b.width()
        b.setStyleSheet(
            f"QPushButton#run {{ background: {c[spec.bg_key]};"
            f" color: {fg}; border-radius: {side // 2}px;"
            f" min-width: {side}px; max-width: {side}px;"
            f" min-height: {side}px; max-height: {side}px; }}"
            f"QPushButton#run:hover {{ background: {c[spec.hover_key]};"
            f" color: {ink_on(c[spec.hover_fg_key])}; }}"
            # Keyboard focus: a ring in the text colour, on any fill.
            f"QPushButton#run:focus {{ border: 2px solid {c['name_fg']}; }}")
        b.setProperty("runState", spec.state)

    def _tag_badges(self, header: QHBoxLayout, badges) -> None:
        """`cardstyle.TagBadge`s beside the name, as coloured words."""
        self.badges: list[QLabel] = []
        for spec in badges or ():
            badge = QLabel(spec.text)
            badge.setObjectName("tagBadge")
            badge.setStyleSheet(
                f"color: {self._ink(self._palette[spec.bg_key])};"
                f" font-size: 8pt; font-weight: 700;")
            set_tooltip(badge, spec.tooltip)
            header.addWidget(badge)
            self.badges.append(badge)

    def _status_chip(self, status: str | None) -> QLabel | None:
        """The last run's outcome as a coloured dot and word: ● OK, ● Failed.
        On a chip, the dot alone: the name and Run are all it has room for."""
        spec = cardstyle.status_badge(status)
        if spec is None:
            return None
        chip = QLabel("●" if self._chip else spec.text)
        chip.setObjectName("statusChip")
        if self._chip:
            # A dot alone is colour alone: say it, to the pointer and to a
            # screen reader.
            words = cardstyle.status_words(status)
            chip.setToolTip(words)
            chip.setAccessibleName(words.replace(":", ""))
        chip.setStyleSheet(f"color: {self._ink(self._palette[spec.bg_key])};"
                           f" font-size: {8 if self._chip else 9}pt; font-weight: 600;")
        return chip


class ScriptCard(_CardBase):
    """One script: name, path, the preset Run passes, and the button strip."""

    run_requested = Signal(int)
    #: Run pressed while its own run is going: stop it.
    stop_requested = Signal(int)
    run_with_param_requested = Signal(int)
    edit_requested = Signal(int)
    favorite_toggled = Signal(int, bool)

    #: Shows the preset menu. None means QMenu.exec, which waits for a
    #: person; tests put their own here.
    menu_runner: Callable[[QMenu, QPoint], object] | None = None

    def set_last_run(self, iso: str | None) -> None:
        """Update when it last ran, in place (see `set_last_status`)."""
        self._last_run = iso
        self._update_path_tip()

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
                 chip: bool = False,
                 parent: QWidget | None = None):
        super().__init__(palette, compact, size, parent, chip=chip)
        compact = self._compact
        self.script_id = script_id
        self._name = name
        self._path = path
        self._last_run = last_run
        self.params_combo: QComboBox | None = None
        self.params_pick: QPushButton | None = None

        self.checkbox = QCheckBox()
        self.checkbox.setVisible(False)
        self._row.addWidget(self.checkbox)

        text = QVBoxLayout()
        text.setSpacing(1)
        tag_text, tag_bg = _script_tag(path)
        header = QHBoxLayout()
        header.setSpacing(8)
        # The kind leads a full row, as a heading; on a compact row it
        # trails the name, which is what the eye looks for in a list.
        tag = self._tag(tag_text, tag_bg, "scriptTag")
        if not compact:
            header.addWidget(tag)
        self._tag_badges(header, () if compact else badges)
        self.name_label = self._name_label(name, label_color)
        header.addWidget(self.name_label, 0 if chip else 1)
        if compact and not chip:
            header.addWidget(tag)
        elif chip:
            tag.hide()
        self._header = header
        self._last_status = last_status
        self._add_status(header, last_status)
        text.addLayout(header)

        # The preset drop-down: which parameters Run passes. Offered, as in
        # Tk, only when the script has presets (`scriptform.card_param_choices`).
        # It is never shown: a row offers it as a small chip on its second
        # line, and the detail pane as chips, both choosing through it.
        if param_choices:
            entries, selected = param_choices
            self.params_combo = QComboBox(self)
            self.params_combo.setObjectName("paramCombo")
            self.params_combo.addItems(entries)
            self.params_combo.setCurrentText(selected)
            self.params_combo.hide()

        self.last_run_label: QLabel | None = None
        if not compact:
            # Relative to the group's base folder, as in Tk; the tooltip
            # keeps the whole path, and when it last ran.
            self.path_label = ElidedLabel(cardstyle.display_path(path, base_dir))
            self.path_label.setObjectName("cardPath")
            # Its own width when there is room -- the stretch after the
            # preset would otherwise take it all -- and shortened when not.
            self.path_label.setSizePolicy(QSizePolicy.Policy.Preferred,
                                          QSizePolicy.Policy.Preferred)
            # Not text-selectable, matching the Tk card: a selectable label
            # takes the mouse for itself, so dragging the card by its path
            # would select text instead of moving the card.
            sub = QHBoxLayout()
            sub.setSpacing(4)
            sub.addWidget(self.path_label)
            if self.params_combo is not None:
                self.params_pick = QPushButton()
                self.params_pick.setObjectName("paramPick")
                self.params_pick.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.params_pick.setCursor(Qt.CursorShape.PointingHandCursor)
                set_tooltip(self.params_pick, "Parameters Run passes -- click to choose")
                self.params_pick.clicked.connect(self._pick_preset)
                self.params_combo.currentTextChanged.connect(
                    lambda _t: self._show_preset())
                self._show_preset()
                sub.addWidget(self.params_pick)
            # The preset follows the path; the space is after both.
            sub.addStretch(1)
            text.addLayout(sub)
            self._update_path_tip()
        self._row.addLayout(text, 0 if chip else 1)

        self.fav_button = self._fav_button(is_favorite)
        # A pencil, the usual sign for Edit. It was ⚙, which Windows draws
        # from its colour-emoji font in pale lavender -- all but invisible on
        # Light -- and as a thin ring in Segoe UI Symbol.
        self.edit_button = self._button("edit", "Edit")
        self.param_button = self._button("run-with", "Run with parameters…", size=18)
        self.run_button = self._run_button(last_status)
        self._lay_out_buttons(self.fav_button,
                              (self.edit_button, self.param_button),
                              self.run_button, is_favorite)

        self.run_button.clicked.connect(lambda: self._press_run(self.script_id))
        self.edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.script_id))
        self.param_button.clicked.connect(
            lambda: self.run_with_param_requested.emit(self.script_id))
        self.fav_button.clicked.connect(
            lambda: self.favorite_toggled.emit(self.script_id, not is_favorite))

    # -- the second line --------------------------------------------------------------
    def _update_path_tip(self) -> None:
        label = getattr(self, "path_label", None)
        if label is None:
            return
        when = cardstyle.last_run_text(self._last_run)
        label.setToolTip(self._path + (f"\nLast run: {when}" if when else ""))

    def _show_preset(self) -> None:
        """The chip reads what Run will pass, shortened to fit."""
        if self.params_pick is None or self.params_combo is None:
            return
        text = self.params_combo.currentText()
        fm = self.params_pick.fontMetrics()
        self.params_pick.setText(literal(
            fm.elidedText(text, Qt.TextElideMode.ElideRight, 160) + "  ▾"))

    def _pick_preset(self) -> None:
        """Choose another preset from a menu under the chip."""
        if self.params_combo is None or self.params_pick is None:
            return
        menu = QMenu(self)
        current = self.params_combo.currentText()
        for i in range(self.params_combo.count()):
            entry = self.params_combo.itemText(i)
            action = menu.addAction(literal(entry))
            action.setCheckable(True)
            action.setChecked(entry == current)
            action.triggered.connect(
                lambda _c=False, t=entry: self.params_combo.setCurrentText(t))
        pos = self.params_pick.mapToGlobal(QPoint(0, self.params_pick.height()))
        (self.menu_runner or (lambda m, p: m.exec(p)))(menu, pos)


class PipelineCard(_CardBase):
    """One pipeline: name, its steps, and the same button columns."""

    run_requested = Signal(int)
    #: Run pressed while its own run is going: stop it.
    stop_requested = Signal(int)
    edit_requested = Signal(int)
    favorite_toggled = Signal(int, bool)
    steps_clicked = Signal(int)

    def __init__(self, *, pipeline_id: int, name: str, step_count: int,
                 palette: dict, compact: bool = False, size: str = "medium",
                 is_favorite: bool = False, last_status: str | None = None,
                 label_color: str | None = None,
                 badges=(), step_names=None, chip: bool = False,
                 parent: QWidget | None = None):
        super().__init__(palette, compact, size, parent, chip=chip)
        compact = self._compact
        self.pipeline_id = pipeline_id
        # Drawn with the pipeline accent down its left edge (stylesheet).
        self.setProperty("kind", "pipeline")
        self._name = name

        text = QVBoxLayout()
        text.setSpacing(1)
        header = QHBoxLayout()
        header.setSpacing(8)
        accent = palette.get("pipe_accent", palette["accent"])
        tag = self._tag("PIPE" if compact else "PIPELINE", accent, "pipeTag")
        if chip:
            # A favourite pill has no room for a word: the drawn bolt says
            # "pipeline", in the pipeline colour.
            header.addWidget(IconLabel("bolt", role="pipe", size=12, palette=palette))
            tag.hide()
        elif not compact:
            header.addWidget(tag)
        self._tag_badges(header, () if compact else badges)
        self.name_label = self._name_label(name, label_color)
        header.addWidget(self.name_label, 0 if chip else 1)
        if compact and not chip:
            header.addWidget(tag)
        self._header = header
        self._last_status = last_status
        self._add_status(header, last_status)
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
        self._row.addLayout(text, 0 if chip else 1)

        self.fav_button = self._fav_button(is_favorite)
        self.edit_button = self._button("edit", "Edit")
        self.spacer = self._spacer()          # where ▶+ sits on a script card
        self.run_button = self._run_button(last_status)
        self._lay_out_buttons(self.fav_button, (self.edit_button, self.spacer),
                              self.run_button, is_favorite)

        self.run_button.clicked.connect(lambda: self._press_run(self.pipeline_id))
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
