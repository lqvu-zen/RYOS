"""The detail pane of the maximised layout: the chosen script or pipeline.

What it says comes from `ryos.detail`. What its buttons do is the chosen
row's own: Run presses the row's Run button, Edit its pencil, the star its
star. So the pane can never drift from the row -- the parameters drop-down,
the ask-each-run prompt and Retry all behave as they do there -- and it holds
no logic of its own beyond keeping itself up to date.

The pane is the chosen item's tabs: Overview, Output, History. The output
panel is lent to the Output tab while the layout is on (`attach_output`) and
handed back to the list's splitter when it is off; the History tab holds a
`RunHistoryView` the window makes for the chosen item.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QStackedWidget, QTabBar, QVBoxLayout,
                               QWidget)

from .. import cardmenu, cardstyle, detail
from ..interpreter import _script_tag
from ..themes import _readable_on, ink_on
from .icons import IconButton, IconLabel
from .widgets import ElidedLabel, FlowLayout, literal, set_tooltip

#: A step card's size: the same for every step, so the row reads as a sequence.
STEP_CARD = (196, 118)


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
            # Hidden now: it is only deleted once the event loop is back,
            # and until then it would show through what replaces it.
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


class DetailPane(QWidget):
    """The right-hand pane: one item's name and actions over its tabs."""

    def __init__(self, palette: dict, *,
                 on_menu: Callable[[str, int, str], None],
                 on_more: Callable[[str, int, QPoint], None],
                 make_history: Callable[[str, int], QWidget] | None = None,
                 step_statuses: Callable[[], dict] | None = None,
                 last_run: Callable[[str, int], object] | None = None,
                 can_open_output: Callable[[str, int], bool] | None = None,
                 open_output: Callable[[str, int], None] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("detailPane")
        self._palette = palette
        self._on_menu = on_menu
        self._on_more = on_more
        self._make_history = make_history
        # What the window knows and the pane shows: the steps' scripts' last
        # outcomes, the item's last run, and whether its output is still open.
        self._step_statuses = step_statuses or dict
        self._last_run = last_run or (lambda _k, _i: None)
        self._can_open_output = can_open_output or (lambda _k, _i: False)
        self._open_output = open_output or (lambda _k, _i: None)
        self.history_view = None
        self.card = None
        self.kind: str | None = None
        self.rec: dict = {}
        self._steps: list = []
        self._name_color: str | None = None

        col = QVBoxLayout(self)
        col.setContentsMargins(26, 20, 22, 10)
        col.setSpacing(12)

        # The name and its actions, over the tabs; hidden until one is chosen.
        self.head_box = QWidget()
        body = QVBoxLayout(self.head_box)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        col.addWidget(self.head_box)

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
        self.star = IconButton("star", size=18, palette=palette)
        self.star.setObjectName("detailStar")
        set_tooltip(self.star, "Add to favorites")
        self.edit = self._link(detail.EDIT, "Edit")
        self.more = IconButton("more", size=18, palette=palette)
        self.more.setObjectName("detailStar")
        set_tooltip(self.more, "More")
        for b in (self.star, self.edit, self.more):
            head.addWidget(b)
        body.addLayout(head)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.run = IconButton("play", size=14, palette=palette)
        self.run.setObjectName("detailRun")
        self.run.setFixedHeight(38)
        self.run_with = self._link(detail.RUN_WITH, "Run with parameters")
        self.schedule = self._link(detail.SCHEDULE, "Run it on a schedule")
        for b in (self.run, self.run_with, self.schedule):
            actions.addWidget(b)
        actions.addStretch(1)
        body.addLayout(actions)

        # -- the tabs: there even with nothing chosen, so the output is too
        self.tabs = QTabBar()
        self.tabs.setObjectName("detailTabs")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        for name in detail.TABS:
            self.tabs.addTab(name)
        col.addWidget(self.tabs)
        self.stack = QStackedWidget()
        col.addWidget(self.stack, 1)

        overview = QWidget()
        ocol = QVBoxLayout(overview)
        ocol.setContentsMargins(0, 4, 0, 0)
        ocol.setSpacing(14)
        self.empty = QLabel(detail.EMPTY)
        self.empty.setObjectName("cardPath")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        ocol.addWidget(self.empty, 1)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        ocol.addWidget(self.body)
        ocol.addStretch(1)
        self.stack.addWidget(overview)

        # -- the script's presets, or the pipeline's steps, as cards
        self.params_title = self._heading(detail.PARAMETERS)
        body.addWidget(self.params_title)
        self.chips_box = QWidget()
        self.chips = FlowLayout(self.chips_box, spacing=8)
        body.addWidget(self.chips_box)
        self.steps_title = self._heading(detail.STEPS)
        body.addWidget(self.steps_title)
        self.steps_panel = QWidget()
        self.steps_rows = FlowLayout(self.steps_panel, spacing=6)
        body.addWidget(self.steps_panel)

        self.facts = QGridLayout()
        self.facts.setHorizontalSpacing(24)
        self.facts.setVerticalSpacing(6)
        body.addLayout(self.facts)

        # -- how the last run went, and the way to its output
        self.last_box = QFrame()
        self.last_box.setObjectName("lastRun")
        last = QHBoxLayout(self.last_box)
        last.setContentsMargins(14, 10, 12, 10)
        last.setSpacing(12)
        self.last_dot = QLabel("●")
        self.last_dot.setObjectName("lastRunDot")
        last.addWidget(self.last_dot)
        words = QVBoxLayout()
        words.setSpacing(1)
        self.last_title = QLabel("")
        self.last_title.setObjectName("lastRunTitle")
        words.addWidget(self.last_title)
        self.last_meta = ElidedLabel("")
        self.last_meta.setObjectName("cardPath")
        words.addWidget(self.last_meta)
        last.addLayout(words, 1)
        self.last_button = QPushButton("")
        self.last_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.last_button.clicked.connect(self._on_last_button)
        last.addWidget(self.last_button)
        body.addWidget(self.last_box)

        # Where the output panel goes while the layout is on.
        output = QWidget()
        self.output_slot = QVBoxLayout(output)
        self.output_slot.setContentsMargins(0, 4, 0, 0)
        self.stack.addWidget(output)
        history = QWidget()
        self.history_slot = QVBoxLayout(history)
        self.history_slot.setContentsMargins(0, 4, 0, 0)
        self.history_empty = QLabel(detail.EMPTY)
        self.history_empty.setObjectName("cardPath")
        self.history_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_slot.addWidget(self.history_empty)
        self.stack.addWidget(history)
        self.tabs.currentChanged.connect(self._on_tab)

        self.run.clicked.connect(lambda: self._press("run_button"))
        self.edit.clicked.connect(lambda: self._press("edit_button"))
        self.star.clicked.connect(lambda: self._press("fav_button"))
        self.run_with.clicked.connect(lambda: self._press("param_button"))
        self.schedule.clicked.connect(lambda: self._menu(cardmenu.SCHEDULE))
        self.more.clicked.connect(self._show_more)
        self.show_empty()

    # -- pieces ---------------------------------------------------------------------
    @staticmethod
    def _link(text: str, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("detailLink")
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
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

    # -- the tabs ------------------------------------------------------------------------
    def current_tab(self) -> str:
        return detail.TABS[self.tabs.currentIndex()]

    def show_tab(self, name: str) -> None:
        self.tabs.setCurrentIndex(detail.TABS.index(name))

    def _on_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if detail.TABS[index] == detail.HISTORY_TAB:
            self._fill_history()

    def _fill_history(self) -> None:
        """The chosen item's runs, made afresh: a new item, or new runs."""
        if self.history_view is not None:
            self.history_slot.removeWidget(self.history_view)
            self.history_view.deleteLater()
            self.history_view = None
        if self.kind is None or self._make_history is None:
            self.history_empty.show()
            return
        self.history_empty.hide()
        self.history_view = self._make_history(self.kind, self._item_id())
        self.history_slot.addWidget(self.history_view, 1)

    # -- what is shown ------------------------------------------------------------------
    def show_empty(self) -> None:
        self.card, self.kind, self.rec, self._steps = None, None, {}, []
        self.head_box.hide()
        self.body.hide()
        self.empty.show()
        if self.current_tab() == detail.HISTORY_TAB:
            self._fill_history()

    def show_item(self, card, kind: str, rec: dict, *, steps=(),
                  name_color: str | None = None) -> None:
        """Show ``rec``, acting through ``card``, its row in the list."""
        self.card, self.kind, self.rec = card, kind, rec
        self._steps = list(steps)
        c = self._palette
        pipeline = kind == cardmenu.PIPELINE
        self.empty.hide()
        self.head_box.show()
        self.body.show()

        accent = c.get("pipe_accent", c["accent"]) if pipeline else c["accent"]
        self.rail.setStyleSheet(f"background: {accent}; border: none;")
        if pipeline:
            tag, tag_color = "PIPELINE", accent
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
        if self.current_tab() == detail.HISTORY_TAB:
            self._fill_history()

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
        self.run.set_shape(spec.icon)
        self.run.set_colors(c[spec.fg_key], ink_on(c[spec.hover_fg_key]))
        set_tooltip(self.run, spec.tooltip)
        self.run.setProperty("runState", spec.state)
        self.run.setStyleSheet(
            f"QPushButton#detailRun {{ background: {c[spec.bg_key]};"
            f" color: {c[spec.fg_key]}; border: none; border-radius: 19px;"
            f" padding: 0 22px 0 18px; font-size: 11pt; font-weight: 700; }}"
            f"QPushButton#detailRun:hover {{ background: {c[spec.hover_key]};"
            f" color: {ink_on(c[spec.hover_fg_key])}; }}")
        favorite = bool(self.rec.get("favorite"))
        if favorite:
            self.star.set_shape("star-filled", role="star")
        else:
            self.star.set_shape("star", role="muted")
        set_tooltip(self.star, "Remove from favorites" if favorite else "Add to favorites")
        self.star.setProperty("on", favorite)
        self.star.style().unpolish(self.star)
        self.star.style().polish(self.star)
        self.sub.setText(detail.subtitle(self.kind, self.rec, len(self._steps)))
        self._fill_facts(detail.pipeline_facts(self.rec)
                         if self.kind == cardmenu.PIPELINE
                         else detail.script_facts(self.rec))
        # A run just finished, most likely: the History tab shows it too,
        # the last-run box says how it went, and a step's card its outcome.
        if self.history_view is not None and self.current_tab() == detail.HISTORY_TAB:
            self.history_view.reload()
        self._fill_last_run()
        if self.kind == cardmenu.PIPELINE:
            self._fill_steps()

    def _fill_chips(self) -> None:
        """The script's presets as cards: pick one -- what Run passes -- or
        run it straight away with its own play button."""
        _clear(self.chips)
        combo = getattr(self.card, "params_combo", None)
        entries = ([combo.itemText(i) for i in range(combo.count())]
                   if combo is not None else [])
        self.params_title.setVisible(bool(entries))
        self.chips_box.setVisible(bool(entries))
        for text in entries:
            chosen = text == combo.currentText()
            card = QFrame()
            card.setObjectName("presetCard")
            card.setProperty("chosen", chosen)
            row = QHBoxLayout(card)
            row.setContentsMargins(3, 3, 3, 3)
            row.setSpacing(0)
            chip = QPushButton(literal(text))
            chip.setObjectName("paramChip")
            chip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            chip.setCheckable(True)
            chip.setChecked(chosen)
            chip.clicked.connect(lambda _c=False, t=text: self._choose_preset(t))
            row.addWidget(chip)
            go = IconButton("play", role="muted", hover_role="text", size=12,
                            palette=self._palette)
            go.setObjectName("presetRun")
            set_tooltip(go, f"Run with {text}")
            go.clicked.connect(lambda _c=False, t=text: self._run_preset(t))
            row.addWidget(go)
            self.chips.addWidget(card)

    def _run_preset(self, text: str) -> None:
        """Run with one preset, in one click: choose it, then Run."""
        self._choose_preset(text)
        self._press("run_button")

    def _choose_preset(self, text: str) -> None:
        combo = getattr(self.card, "params_combo", None)
        if combo is not None and _alive(combo):
            combo.setCurrentText(text)
        self._fill_chips()

    def _fill_steps(self) -> None:
        """The steps as cards in order, wrapping: an arrow into each step
        after the first, a + into one that starts with the step before. The
        mark travels with its card, so a wrapped line starts "→ step" rather
        than the line above ending in an arrow to nothing."""
        _clear(self.steps_rows)
        cards = detail.step_cards(self._steps, self._step_statuses())
        if not cards:
            empty = QLabel(cardstyle.NO_STEPS)
            empty.setObjectName("cardPath")
            self.steps_rows.addWidget(empty)
        for i, step in enumerate(cards):
            card = self._step_card(step)
            if i == 0:
                self.steps_rows.addWidget(card)
                continue
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            mark = IconLabel("plus" if step.together else "arrow-right", role="muted",
                             size=14, palette=self._palette)
            mark.setToolTip("Starts with the step before" if step.together else "Then")
            row.addWidget(mark)
            row.addWidget(card)
            self.steps_rows.addWidget(holder)

    def _step_card(self, step) -> QFrame:
        c = self._palette
        card = QFrame()
        card.setObjectName("stepCard")
        card.setFixedSize(*STEP_CARD)
        col = QVBoxLayout(card)
        col.setContentsMargins(12, 9, 10, 9)
        col.setSpacing(2)
        col.addWidget(self._heading(f"STEP {step.number}"))
        name = ElidedLabel(step.name)
        name.setObjectName("stepName")
        col.addWidget(name)
        where = ElidedLabel(step.file)
        where.setObjectName("cardPath")
        col.addWidget(where)
        col.addStretch(1)
        spec = cardstyle.status_badge(step.status)
        if spec is not None:
            word = QLabel(spec.text)
            word.setStyleSheet(f"color: {_readable_on(c[spec.bg_key], (c['card_bg'],))};"
                               " font-size: 9pt; font-weight: 600;")
            col.addWidget(word)
        # Their own line: beside the outcome, "only if something has failed"
        # was cut to "only if som… has failed".
        notes = ElidedLabel("  ·  ".join(step.notes))
        notes.setObjectName("cardPath")
        notes.setVisible(bool(step.notes))
        col.addWidget(notes)
        said = [f"Step {step.number}: {step.name}", step.file,
                cardstyle.status_words(step.status) or "", *step.notes]
        card.setToolTip("\n".join(s for s in said if s))
        card.setAccessibleName(", ".join(s for s in said if s))
        return card

    def _fill_last_run(self) -> None:
        """The last-run box: how it went, when, and the way to its output."""
        if self.kind is None:
            return
        from datetime import datetime
        item_id = self._item_id()
        row = self._last_run(self.kind, item_id)
        lines = detail.last_run_lines(row, datetime.now())
        c = self._palette
        if lines is None:
            self.last_title.setText(detail.NOT_RUN)
            self.last_meta.setText("")
            self.last_dot.hide()
            self.last_button.hide()
            return
        self.last_title.setText(lines[0])
        self.last_meta.setText(lines[1])
        spec = cardstyle.status_badge(row[7])
        if spec is not None:
            self.last_dot.setStyleSheet(
                f"color: {_readable_on(c[spec.bg_key], (c['card_bg'],))}; font-size: 16pt;")
        self.last_dot.setVisible(spec is not None)
        self.last_button.setText(detail.OPEN_OUTPUT
                                 if self._can_open_output(self.kind, item_id)
                                 else detail.SEE_HISTORY)
        self.last_button.show()

    def _on_last_button(self) -> None:
        if self.kind is None:
            return
        if self.last_button.text() == detail.OPEN_OUTPUT:
            self._open_output(self.kind, self._item_id())
        else:
            self.show_tab(detail.HISTORY_TAB)

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
