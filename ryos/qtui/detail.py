"""The detail pane of the maximised layout: the chosen script or pipeline.

What it says comes from `ryos.detail`. What its buttons do is the chosen
row's own: Run presses the row's Run button, Edit its pencil, the star its
star. So the pane can never drift from the row -- the parameters drop-down,
the ask-each-run prompt and Retry all behave as they do there -- and it holds
no logic of its own beyond keeping itself up to date.

The output panel is lent to the pane while the layout is on
(`attach_output`) and handed back to the list's splitter when it is off.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .. import cardmenu, cardstyle, detail
from ..interpreter import _script_tag
from ..themes import _readable_on, ink_on
from .widgets import ElidedLabel, literal, set_tooltip


def _alive(widget) -> bool:
    """Whether ``widget`` still exists: a reload replaces every card."""
    if widget is None:
        return False
    try:
        import shiboken6
        return shiboken6.isValid(widget)
    except ImportError:                         # pragma: no cover
        return True


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


class DetailPane(QWidget):
    """The right-hand pane: one item's name, actions, settings and output."""

    def __init__(self, palette: dict, *,
                 on_menu: Callable[[str, int, str], None],
                 on_more: Callable[[str, int, QPoint], None],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("detailPane")
        self._palette = palette
        self._on_menu = on_menu
        self._on_more = on_more
        self.card = None
        self.kind: str | None = None
        self.rec: dict = {}
        self._steps: list = []
        self._name_color: str | None = None

        col = QVBoxLayout(self)
        col.setContentsMargins(26, 20, 22, 10)
        col.setSpacing(14)

        self.empty = QLabel(detail.EMPTY)
        self.empty.setObjectName("cardPath")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        col.addWidget(self.empty)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        col.addWidget(self.body)

        # -- the name, and what to do with it
        head = QHBoxLayout()
        head.setSpacing(12)
        self.rail = QFrame()
        self.rail.setFixedSize(3, 42)
        head.addWidget(self.rail)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.kind_label = QLabel()
        name_row.addWidget(self.kind_label)
        self.name = ElidedLabel("")
        self.name.setObjectName("detailName")
        name_row.addWidget(self.name, 1)
        titles.addLayout(name_row)
        self.sub = ElidedLabel("")
        self.sub.setObjectName("cardPath")
        titles.addWidget(self.sub)
        head.addLayout(titles, 1)
        self.star = self._link("☆", "Add to favorites")
        self.star.setObjectName("detailStar")
        self.edit = self._link(detail.EDIT, "Edit")
        self.more = self._link("⋯", "More")
        self.more.setObjectName("detailStar")
        for b in (self.star, self.edit, self.more):
            head.addWidget(b)
        body.addLayout(head)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.run = QPushButton()
        self.run.setObjectName("detailRun")
        self.run.setFixedHeight(38)
        self.run_with = self._link(detail.RUN_WITH, "Run with parameters")
        self.schedule = self._link(detail.SCHEDULE, "Run it on a schedule")
        self.history = self._link(detail.HISTORY, "Earlier runs")
        for b in (self.run, self.run_with, self.schedule, self.history):
            actions.addWidget(b)
        actions.addStretch(1)
        body.addLayout(actions)

        # -- the script's presets, or the pipeline's steps
        self.params_title = self._heading(detail.PARAMETERS)
        body.addWidget(self.params_title)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        body.addLayout(self.chips)
        self.steps_title = self._heading(detail.STEPS)
        body.addWidget(self.steps_title)
        self.steps_panel = QWidget()
        self.steps_panel.setObjectName("sectionPanel")
        self.steps_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.steps_rows = QVBoxLayout(self.steps_panel)
        self.steps_rows.setContentsMargins(0, 0, 0, 0)
        self.steps_rows.setSpacing(0)
        body.addWidget(self.steps_panel)

        self.facts = QGridLayout()
        self.facts.setHorizontalSpacing(24)
        self.facts.setVerticalSpacing(6)
        body.addLayout(self.facts)

        # Where the output panel goes while the layout is on.
        self.output_slot = QVBoxLayout()
        self.output_slot.setContentsMargins(0, 6, 0, 0)
        col.addLayout(self.output_slot, 1)

        self.run.clicked.connect(lambda: self._press("run_button"))
        self.edit.clicked.connect(lambda: self._press("edit_button"))
        self.star.clicked.connect(lambda: self._press("fav_button"))
        self.run_with.clicked.connect(lambda: self._press("param_button"))
        self.schedule.clicked.connect(lambda: self._menu(cardmenu.SCHEDULE))
        self.history.clicked.connect(lambda: self._menu(cardmenu.HISTORY))
        self.more.clicked.connect(self._show_more)
        self.show_empty()

    # -- pieces ---------------------------------------------------------------------
    @staticmethod
    def _link(text: str, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("detailLink")
        set_tooltip(b, tip)
        return b

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("detailHeading")
        return label

    def _ink(self, color: str) -> str:
        c = self._palette
        return _readable_on(color, (c["bg"],))

    # -- what is shown ------------------------------------------------------------------
    def show_empty(self) -> None:
        self.card, self.kind, self.rec, self._steps = None, None, {}, []
        self.body.hide()
        self.empty.show()

    def show_item(self, card, kind: str, rec: dict, *, steps=(),
                  name_color: str | None = None) -> None:
        """Show ``rec``, acting through ``card``, its row in the list."""
        self.card, self.kind, self.rec = card, kind, rec
        self._steps = list(steps)
        c = self._palette
        pipeline = kind == cardmenu.PIPELINE
        self.empty.hide()
        self.body.show()

        accent = c.get("pipe_accent", c["accent"]) if pipeline else c["accent"]
        self.rail.setStyleSheet(f"background: {accent}; border: none;")
        if pipeline:
            tag, tag_color = "⚡ PIPELINE", accent
        else:
            tag, tag_color = _script_tag(rec.get("path", ""))
        self.kind_label.setText(tag.upper())
        self.kind_label.setStyleSheet(f"color: {self._ink(tag_color)}; font-size: 8pt;"
                                      f" font-weight: 700; letter-spacing: 0.4px;")
        self._name_color = name_color
        self.name.setText(rec.get("name", ""))
        self.name.setStyleSheet(f"color: {name_color};" if name_color else "")
        self.run_with.setVisible(not pipeline)

        self._fill_chips()
        self.steps_title.setVisible(pipeline)
        self.steps_panel.setVisible(pipeline)
        if pipeline:
            self._fill_steps()
        self.refresh()

    def refresh(self) -> None:
        """Bring the Run button, the star and the subtitle up to date."""
        if self.kind is None:
            return
        if not _alive(self.card):
            self.show_empty()
            return
        status = getattr(self.card, "_last_status", None)
        spec = cardstyle.run_button(status)
        c = self._palette
        self.run.setText(detail.run_label(status))
        set_tooltip(self.run, spec.tooltip)
        self.run.setProperty("runState", spec.state)
        self.run.setStyleSheet(
            f"QPushButton#detailRun {{ background: {c[spec.bg_key]};"
            f" color: {c[spec.fg_key]}; border: none; border-radius: 19px;"
            f" padding: 0 22px 0 18px; font-size: 11pt; font-weight: 700; }}"
            f"QPushButton#detailRun:hover {{ background: {c[spec.hover_key]};"
            f" color: {ink_on(c[spec.hover_fg_key])}; }}")
        favorite = bool(self.rec.get("favorite"))
        self.star.setText("★" if favorite else "☆")
        set_tooltip(self.star, "Remove from favorites" if favorite else "Add to favorites")
        self.star.setProperty("on", favorite)
        self.star.style().unpolish(self.star)
        self.star.style().polish(self.star)
        self.sub.setText(detail.subtitle(self.kind, self.rec, len(self._steps)))
        self._fill_facts(detail.pipeline_facts(self.rec)
                         if self.kind == cardmenu.PIPELINE
                         else detail.script_facts(self.rec))

    def _fill_chips(self) -> None:
        """The script's presets as chips; the chosen one is what Run passes."""
        _clear(self.chips)
        combo = getattr(self.card, "params_combo", None)
        entries = ([combo.itemText(i) for i in range(combo.count())]
                   if combo is not None else [])
        self.params_title.setVisible(bool(entries))
        for text in entries:
            chip = QPushButton(literal(text))
            chip.setObjectName("paramChip")
            chip.setCheckable(True)
            chip.setChecked(text == combo.currentText())
            chip.clicked.connect(lambda _c=False, t=text: self._choose_preset(t))
            self.chips.addWidget(chip)
        self.chips.addStretch(1)

    def _choose_preset(self, text: str) -> None:
        combo = getattr(self.card, "params_combo", None)
        if combo is not None and _alive(combo):
            combo.setCurrentText(text)
        self._fill_chips()

    def _fill_steps(self) -> None:
        _clear(self.steps_rows)
        rows = cardstyle.pipeline_preview_rows(self._steps)
        if not rows:
            empty = QLabel(cardstyle.NO_STEPS)
            empty.setObjectName("cardPath")
            empty.setContentsMargins(12, 8, 12, 8)
            self.steps_rows.addWidget(empty)
        for i, (number, name, path, override) in enumerate(rows):
            row = QFrame()
            row.setObjectName("stepRow")
            row.setProperty("last", i == len(rows) - 1)
            line = QHBoxLayout(row)
            line.setContentsMargins(12, 7, 12, 7)
            line.setSpacing(10)
            n = QLabel(number)
            n.setObjectName("cardPath")
            n.setFixedWidth(22)
            line.addWidget(n)
            title = QLabel(name)
            title.setObjectName("cardName")
            line.addWidget(title)
            where = ElidedLabel(path)
            where.setObjectName("cardPath")
            line.addWidget(where, 1)
            if override:
                extra = QLabel(f"[{override}]")
                extra.setObjectName("cardPath")
                line.addWidget(extra)
            self.steps_rows.addWidget(row)

    def _fill_facts(self, facts) -> None:
        _clear(self.facts)
        for i, (key, value) in enumerate(facts):
            k = QLabel(key)
            k.setObjectName("factKey")
            v = ElidedLabel(value)
            v.setObjectName("factValue")
            v.setToolTip(value)
            r, c = divmod(i, 2)
            self.facts.addWidget(k, r * 2, c)
            self.facts.addWidget(v, r * 2 + 1, c)
        for c in (0, 1):
            self.facts.setColumnStretch(c, 1)

    # -- acting through the row ---------------------------------------------------------
    def _press(self, button: str) -> None:
        widget = getattr(self.card, button, None) if _alive(self.card) else None
        if widget is not None:
            widget.click()

    def _item_id(self):
        return self.rec.get("id")

    def _menu(self, key: str) -> None:
        if self.kind is not None:
            self._on_menu(self.kind, self._item_id(), key)

    def _show_more(self) -> None:
        if self.kind is not None:
            self._on_more(self.kind, self._item_id(),
                          self.more.mapToGlobal(QPoint(0, self.more.height())))

    # -- the output panel -------------------------------------------------------------
    def attach_output(self, panel: QWidget) -> None:
        self.output_slot.addWidget(panel)

    def set_palette(self, palette: dict) -> None:
        self._palette = palette
        if self.kind is not None and _alive(self.card):
            self.show_item(self.card, self.kind, self.rec, steps=self._steps,
                           name_color=self._name_color)
