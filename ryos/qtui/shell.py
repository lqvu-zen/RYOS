"""The Qt main window.

Wires together everything ported in phases 2.1–2.5: the generated stylesheet,
the cards, the dialogs and the pipeline editor. Output routing and the
buffer-trim rule come from `ryos.outputpanel`, search from `ryos.search`, and
grouping from `ryos.grouping` — all shared with the Tk shell.

`attach_jobs()` connects a `JobBridge`, after which the window runs scripts
and shows them in the running section. It is optional and separate from
`__init__` so the window can be built and checked without the job machinery.

A group given a base folder in `set_cards()` gets a Quick Run bar, which
submits through the same `quickrun_actions` flow as the Tk bar.

Right-click menus on cards and group tabs are the `cardmenu` menus, drawn by
`menus.build_menu`. Every question they ask -- confirm, name, folder, file --
goes through an attribute (`ask_yes_no`, `ask_text`, ...) holding the real
dialog, so a test can answer in its place.

`RYOSApp` still owns the shipping app and `__main__` still starts it; flipping
over is the last step of the migration and has not happened. What the shell
still lacks is listed in docs/plans/qt-migration.md under "Parity".
"""

from __future__ import annotations

import sys

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QTabBar,
                               QMainWindow, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import activity, basefolder, bugreport
from .. import (__version__, cardmenu, cardstyle, configio, detail, grouping,
               notifications, outputpanel, pipelinesteps, screens, scriptform,
               search, sections, selection, traypolicy)
from . import placement
from ..themes import REFERENCE, readable_highlight, step_colour
from .cards import PipelineCard, ScriptCard
from .detail import DetailPane
from .rail import Rail
from .activity import ActivityPanel
from .dragdrop import GroupTabBar
from .sections import GroupPage
from .menus import build_menu
from .quickrun import MainThreadInvoker, QuickRunBar
from .running import RunningSection
from ..jobs import live_statuses, own_runs
from .stylesheet import stylesheet
from . import icons
from .icons import IconButton, IconLabel
from .widgets import literal, set_tooltip

#: Matches the Tk placeholder, so the two shells prompt identically.
SEARCH_PLACEHOLDER = "Search scripts and pipelines…"


class OutputPane(QWidget):
    """One output tab: its lines, coloured by tag, found in, and filtered.

    Every line is kept with its tag (stdout, stderr, info, ok), up to the
    shared buffer cap. That is what lets "Errors only" hide lines and bring
    them back, and colour stderr as the Tk panel does. Find highlights with
    extra selections, so the text itself is never changed. The query, the
    current match and the filter are this tab's own, as in Tk.
    """

    #: Palette key for each tag's text colour; anything else is stdout.
    TAG_COLORS = {"stderr": "out_stderr", "info": "out_status", "ok": "out_success"}

    def __init__(self, palette: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._palette = palette or REFERENCE["dark"]
        # (line, tag, step): step is (token, label) for a line from a step
        # running beside others, else None.
        self.lines: list[tuple[str, str, tuple | None]] = []
        self.query = ""
        self.errors_only = False
        # The parallel steps seen in this tab, token -> (label, state), and
        # the one the chips narrow the view to (None = every line).
        self.steps: dict[int, tuple[str, str]] = {}
        self.step_filter: int | None = None
        self.match: int | None = None
        self.spans: list[tuple[int, int]] = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        # One chip per parallel step, shown once a group has run here: the
        # step's state at a glance, and a click to read its lines alone.
        chips = QWidget()
        chips.setObjectName("stepBar")
        self._step_row = QHBoxLayout(chips)
        self._step_row.setContentsMargins(6, 4, 6, 4)
        self._step_row.setSpacing(4)
        self.step_chips: dict[int | None, QPushButton] = {}
        self._add_step_chip(None, outputpanel.ALL_STEPS, "")
        self._step_row.addStretch(1)
        # A strip that scrolls sideways and never gives up its height: in a
        # short output panel the row was squeezed to a sliver, and in a
        # narrow window a long row of chips would have widened the panel.
        self.step_bar = QScrollArea()
        self.step_bar.setObjectName("stepBar")
        self.step_bar.setWidget(chips)
        self.step_bar.setWidgetResizable(True)
        self.step_bar.setFrameShape(QFrame.Shape.NoFrame)
        self.step_bar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.step_bar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.step_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._fit_step_bar()
        self.step_bar.hide()
        col.addWidget(self.step_bar)
        self.text = QPlainTextEdit()
        self.text.setObjectName("output")
        self.text.setReadOnly(True)
        col.addWidget(self.text)

    # -- writing -----------------------------------------------------------------------
    def _format(self, tag: str):
        from PySide6.QtGui import QColor, QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._palette[self.TAG_COLORS.get(tag, "out_stdout")]))
        return fmt

    def _write(self, line: str, tag: str, step: tuple | None = None) -> None:
        from PySide6.QtGui import QColor, QTextCursor
        cursor = QTextCursor(self.text.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.text.document().isEmpty():
            cursor.insertBlock()
        if step is not None:
            # The step's "[name] " in its own colour, so interleaved lines
            # can be told apart at a glance.
            prefix = outputpanel.step_prefix(step[1])
            if line.startswith(prefix):
                fmt = self._format(tag)
                fmt.setForeground(QColor(step_colour(step[0], self._palette["out_bg"])))
                fmt.setFontWeight(700)
                cursor.insertText(prefix, fmt)
                line = line[len(prefix):]
        cursor.insertText(line, self._format(tag))

    def _shown(self, tag: str, step: tuple | None) -> bool:
        return (outputpanel.shown_when_filtered(tag, self.errors_only)
                and outputpanel.shown_for_step(step[0] if step else None,
                                               self.step_filter))

    def append(self, text: str, max_lines: int, *, scroll: bool = True,
               tag: str | None = None, step: tuple | None = None) -> None:
        tag = tag or "stdout"
        line = text.rstrip("\n")
        self.lines.append((line, tag, step))
        if self._shown(tag, step):
            self._write(line, tag, step)
        drop = outputpanel.overflow_lines(len(self.lines), max_lines)
        if drop:
            dropped, self.lines = self.lines[:drop], self.lines[drop:]
            shown = sum(self._shown(tg, st) for _l, tg, st in dropped)
            self._drop_blocks(shown)
        if scroll:
            bar = self.text.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _drop_blocks(self, count: int) -> None:
        if count <= 0:
            return
        from PySide6.QtGui import QTextCursor
        doc = self.text.document()
        if count >= doc.blockCount():
            self.text.clear()
            return
        # From the start to the start of line ``count``: the selection takes
        # the dropped lines' breaks with it, so nothing is left behind.
        cursor = QTextCursor(doc)
        cursor.setPosition(doc.findBlockByNumber(count).position(),
                           QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()

    def rebuild(self) -> None:
        """Redraw from the kept lines -- for the filter, and a new palette."""
        self.text.clear()
        for line, tag, step in self.lines:
            if self._shown(tag, step):
                self._write(line, tag, step)
        self.search()

    def clear(self) -> None:
        self.lines = []
        self.text.clear()
        self.set_step_filter(None)
        self.search()

    def set_palette(self, palette: dict) -> None:
        self._palette = palette
        for token, (label, state) in self.steps.items():
            self.set_step_state(token, label, state)
        self.rebuild()

    def set_errors_only(self, on: bool) -> None:
        if on != self.errors_only:
            self.errors_only = on
            self.rebuild()

    def plain_text(self) -> str:
        """Everything this tab holds, whatever the filter shows."""
        return "\n".join(line for line, _tag, _step in self.lines)

    # -- parallel steps ----------------------------------------------------------------
    def _add_step_chip(self, token: int | None, text: str, tip: str) -> QPushButton:
        chip = QPushButton(text)
        chip.setObjectName("stepChip")
        chip.setCheckable(True)
        chip.setChecked(token is None)
        chip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if tip:
            set_tooltip(chip, tip)
        chip.clicked.connect(lambda _c=False, t=token: self.set_step_filter(t))
        self.step_chips[token] = chip
        # Before the stretch, in the order the steps ran.
        self._step_row.insertWidget(self._step_row.count() - 1
                                    if self._step_row.count() else 0, chip)
        return chip

    def set_step_state(self, token: int, label: str, state: str) -> None:
        """A parallel step started, retried, passed or failed."""
        self.steps[token] = (label, state)
        chip = self.step_chips.get(token)
        text = outputpanel.step_chip_text(token, label, state)
        tip = outputpanel.step_chip_tip(token, label, state)
        if chip is None:
            chip = self._add_step_chip(token, text, tip)
        else:
            chip.setText(text)
            set_tooltip(chip, tip)
        chip.setProperty("state", state)
        chip.style().unpolish(chip)
        chip.style().polish(chip)
        # A chip's own colour: the same hue as its step's lines.
        chip.setStyleSheet(f"QPushButton#stepChip {{ border-left: 3px solid "
                           f"{step_colour(token, self._palette['out_bg'])}; }}")
        self._fit_step_bar()
        self.step_bar.show()

    def _fit_step_bar(self) -> None:
        """The strip's height: its chips', plus room for its scroll bar."""
        inner = self.step_bar.widget()
        # Room for the scroll bar only when the chips overflow, so a row that
        # fits has no empty band under it.
        overflow = inner.sizeHint().width() > max(self.width(), 1)
        bar = self.step_bar.horizontalScrollBar().sizeHint().height() if overflow else 0
        self.step_bar.setFixedHeight(inner.sizeHint().height() + bar)

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        if not self.step_bar.isHidden():
            self._fit_step_bar()

    def set_step_filter(self, token: int | None) -> None:
        """Show only step ``token``'s lines, or every line for None."""
        if token is not None and token not in self.steps:
            token = None
        for key, chip in self.step_chips.items():
            chip.setChecked(key == token)
        if token != self.step_filter:
            self.step_filter = token
            self.rebuild()

    # -- finding ---------------------------------------------------------------------
    def set_query(self, query: str) -> None:
        self.query = query
        self.match = None
        self.search()

    def search(self) -> None:
        self.spans = search.find_spans(self.text.toPlainText(), self.query)
        if self.match is not None and self.match >= len(self.spans):
            self.match = None
        self._highlight()

    def step(self, forward: bool) -> None:
        nxt = search.step_match(len(self.spans), self.match, forward)
        if nxt is not None:
            self.match = nxt
            self._highlight()

    def match_label(self) -> str:
        return outputpanel.match_label(self.query, len(self.spans), self.match)

    def _highlight(self) -> None:
        from PySide6.QtGui import QColor, QTextCursor
        from PySide6.QtWidgets import QTextEdit
        selections = []
        for i, (start, end) in enumerate(self.spans):
            sel = QTextEdit.ExtraSelection()
            cursor = QTextCursor(self.text.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            current = i == self.match
            sel.format.setBackground(QColor(self._palette["bolt" if current else "out_status"]))
            sel.format.setForeground(QColor(self._palette["out_bg"]))
            selections.append(sel)
            if current:
                self.text.setTextCursor(cursor)
                self.text.ensureCursorVisible()
        self.text.setExtraSelections(selections)


class _NoStartup:
    """Run-at-login for a window that must not touch the registry."""

    def enabled(self) -> bool:
        return False

    def set(self, on: bool) -> None:
        pass


class MainWindow(QMainWindow):
    """The window: group tabs, a card list, a search box and an output panel."""

    def __init__(self, palette: dict | None = None, *,
                 settings: dict | None = None,
                 on_run: Callable[[int], None] | None = None,
                 save_settings: Callable[[dict], None] | None = None,
                 notifier: Callable[[str, str], None] | None = None,
                 fetch_release: Callable[[], object] | None = None,
                 startup=None,
                 configure_logging: Callable[[bool, str], None] | None = None):
        super().__init__()
        # Run-at-login lives in the Windows registry, not in settings. Like
        # the other real effects it is passed in; the default does nothing,
        # so no test can change the user's login entry.
        self._startup = startup or _NoStartup()
        # Like save_settings: inert unless the entry point passes the real
        # ones, so tests pop no toasts and make no network calls.
        self._notifier = notifier or (lambda _t, _b: None)
        self._fetch_release = fetch_release or (lambda: None)
        self.open_url: Callable[[str], None] = self._open_url
        self.update_banner = None
        # Monitor lookups, injectable so placement can be checked against a
        # made-up desktop rather than whatever screens the test machine has.
        self.cursor_area: Callable[[], object] = placement.cursor_work_area
        self.area_at: Callable[[int, int], object] = placement.work_area_at
        self._last_normal_geometry: str | None = None
        self._customs: dict | None = None     # custom themes, read on first use
        # Both inert unless the real entry point passes the real ones, so a
        # test that closes a window can never write the user's settings or
        # end the application.
        self._save_settings = save_settings or (lambda _s: None)
        # Points the log at the user's own file, so a test must not get it.
        self._configure_logging = configure_logging or (lambda _on, _level: None)
        self.on_quit: Callable[[], None] = lambda: None
        self._tray = None
        self._instance = None
        self._hidden_to_tray = False
        self._quitting = False
        self._palette = palette or REFERENCE["dark"]
        self._settings = dict(settings or {})
        self._on_run = on_run
        self._cards: list = []
        self._output_tabs: dict[str, OutputPane] = {}
        # (kind, id) -> the output tab of its latest run, for "Open output".
        self._latest_tab: dict[tuple, str] = {}
        self._bridge = None
        self.quick_run_bars: dict[str, QuickRunBar] = {}
        self._qr_index = None
        self._db = None
        self.card_lists: dict[str, GroupPage] = {}
        # (kind, id) -> (record, group), for the menus.
        self._records: dict[tuple, tuple] = {}
        self._collapse = sections.CollapseState()
        self.all_pages: dict[str, GroupPage] = {}
        self.all_headers: dict[str, QLabel] = {}
        self.all_no_match: QLabel | None = None
        self.group_banners: dict[str, QPushButton] = {}

        # Everything a menu action may ask. Real dialogs by default; a test
        # replaces them, since each of these blocks until a person answers.
        self.ask_yes_no: Callable[[str, str], bool] = self._ask_yes_no
        self.ask_import_mode: Callable[[], str | None] = self._ask_import_mode
        self.ask_text: Callable[[str, str, str], str | None] = self._ask_text
        self.warn: Callable[[str, str], None] = self._warn
        self.inform: Callable[[str, str], None] = self._inform
        self.select_mode = False
        self.ask_save_path: Callable[[str, str], str | None] = self._ask_save_path
        self.ask_open_path: Callable[[str], str | None] = self._ask_open_path
        self.run_dialog: Callable[[object], None] = lambda dlg: dlg.exec()
        self.popup: Callable[[object, QPoint], None] = \
            lambda menu, pos: menu.exec(pos)

        self.setWindowTitle("RYOS")
        self.resize(self._settings.get("window_width", 540),
                    self._settings.get("window_height", 640))
        self.setStyleSheet(stylesheet(self._palette))

        self.running = RunningSection(self._palette, on_stop=self._stop_job)

        self._menu_icons: list = []
        self.setMenuWidget(self._build_header())
        # The list over the output; and, maximised, the detail pane beside
        # them, which the output panel moves into (`set_workspace`).
        self.workspace = False
        self._selected: tuple | None = None
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self._build_top())
        self.splitter.addWidget(self._build_output())
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.detail = DetailPane(
            self._palette,
            on_menu=lambda kind, item_id, key: self.on_card_menu(kind, item_id, key),
            on_more=lambda kind, item_id, pos: self._show_card_menu(
                kind, item_id, pos, self._selected_section()),
            make_history=self._history_view,
            step_statuses=self._script_statuses,
            last_run=self._last_run_of,
            can_open_output=lambda kind, item_id: self._output_of(kind, item_id) is not None,
            open_output=self._open_output_of)
        self.outer = QSplitter(Qt.Orientation.Horizontal)
        self.outer.setObjectName("outerSplit")
        self.outer.addWidget(self.splitter)
        self.outer.addWidget(self.detail)
        # And beside the pane, what is running, what runs next, what ran.
        self.activity = ActivityPanel(self._palette, on_open=self._open_from_activity)
        self.outer.addWidget(self.activity)
        self.outer.setStretchFactor(1, 1)
        self.outer.setCollapsible(0, False)
        self.outer.setCollapsible(1, False)
        self.outer.setCollapsible(2, False)
        self.detail.hide()
        self.activity.hide()
        self.activity_shown = bool(self._settings.get("activity_shown", True))
        # While it shows, its day words ("Today", "Tomorrow") and times stay
        # current between runs.
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(60_000)
        self._activity_timer.timeout.connect(self.refresh_activity)
        # Maximised, the rail of places runs down the left of it all.
        self.rail = Rail(self._palette, self.go_to)
        self.rail.hide()
        self.rail.set_on("activity", self.activity_shown)
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.rail)
        row.addWidget(self.outer, 1)
        self.setCentralWidget(central)

        self.statusBar().showMessage("Ready")
        # Maximised: how many are running and what runs next, on the right.
        self.activity_status = QLabel("")
        self.activity_status.setObjectName("statusSummary")
        self.activity_status.hide()
        self.statusBar().addPermanentWidget(self.activity_status)
        # Always there, and quiet: one click to a filled-in bug report.
        self.bug_button = IconButton("bug", role="muted", hover_role="text", size=14,
                                     palette=self._palette)
        self.bug_button.setObjectName("statusBug")
        set_tooltip(self.bug_button, bugreport.TOOLTIP)
        self.bug_button.setAccessibleName("Report a bug")
        self.bug_button.clicked.connect(self.report_bug)
        self.statusBar().addPermanentWidget(self.bug_button)
        self.running.changed.connect(lambda _n: self.refresh_activity())
        self._build_menu()
        # Files dropped anywhere on the window become scripts, as in Tk.
        self.setAcceptDrops(True)
        self._let_bars_shrink()
        # The window's own buttons take focus from Tab, not from a click:
        # the stylesheet draws focus, and a clicked button kept the look.
        for button in (self.add_pipeline_button, self.add_group_button,
                       self.add_script_button, self.select_all_button):
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # Start in the search box, so typing filters. Qt gave the first
        # button focus instead, and drew "+ Pipeline" as if pressed.
        self.search_box.setFocus()

    #: The narrowest the window may be; the bars below must fit inside it.
    MIN_WIDTH = 480

    def _let_bars_shrink(self) -> None:
        """Let the header bars' buttons and labels give way before the window.

        A layout's minimum width becomes the window's, and a button's is its
        whole text. With a wider font -- larger text settings, or a platform's
        fallback font (the output header alone needed 600 px offscreen) -- the
        window could not be made as narrow as its own minimum, and a saved
        size was silently widened. Here the text clips instead.
        """
        from PySide6.QtWidgets import QAbstractButton
        rows = [self.select_bar, self.output_findbar, self.header,
                *self.findChildren(QFrame, "outputHeader")]
        loose = [self.search_hint]
        for widget in loose + [w for row in rows for kind in (QAbstractButton, QLabel)
                               for w in row.findChildren(kind)]:
            widget.setMinimumWidth(min(widget.minimumSizeHint().width(), 24))
        # The rows' layouts cached their sizes before this; recompute them.
        for row in rows:
            row.layout().invalidate()
            row.updateGeometry()

    # -- construction ------------------------------------------------------
    def menuBar(self):                                    # noqa: N802
        """The menus, which live in the header bar.

        QMainWindow's own would make a new bar in the header's place.
        """
        return self.menu_bar

    def _build_header(self) -> QWidget:
        """The header bar: the bolt and the name, the menus, and the buttons
        that make things -- + Script filled, as the window's main action."""
        from PySide6.QtWidgets import QMenuBar
        header = QFrame()
        header.setObjectName("appHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 6, 10, 6)
        row.setSpacing(4)
        # The brand bolt, drawn: the emoji came in its own orange, whatever
        # the theme's bolt colour.
        bolt = IconLabel("bolt", role="bolt", size=18, palette=self._palette)
        bolt.setObjectName("appBolt")
        row.addWidget(bolt)
        title = QLabel("RYOS")
        title.setObjectName("appTitle")
        row.addWidget(title)
        row.addSpacing(10)
        self.menu_bar = QMenuBar()
        self.menu_bar.setObjectName("appMenu")
        row.addWidget(self.menu_bar)
        row.addStretch(1)
        self.add_pipeline_button = QPushButton(pipelinesteps.ADD_PIPELINE_LABEL)
        self.add_pipeline_button.clicked.connect(self.new_pipeline)
        row.addWidget(self.add_pipeline_button)
        self.add_group_button = QPushButton("+ Group")
        self.add_group_button.clicked.connect(self.new_group)
        row.addWidget(self.add_group_button)
        self.add_script_button = QPushButton(sections.ADD_SCRIPT_LABEL)
        self.add_script_button.setObjectName("primary")
        self.add_script_button.clicked.connect(self.add_script)
        row.addWidget(self.add_script_button)
        self.header = header
        return header

    def _build_top(self) -> QWidget:
        top = QWidget()
        col = QVBoxLayout(top)
        col.setContentsMargins(14, 10, 14, 4)
        col.setSpacing(8)

        row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(SEARCH_PLACEHOLDER)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_search)
        self.search_box.installEventFilter(self)
        row.addWidget(self.search_box, 1)
        self.search_hint = QLabel("")
        self.search_hint.setObjectName("cardPath")
        row.addWidget(self.search_hint)
        col.addLayout(row)

        self._top_col = col
        col.addWidget(self._build_select_bar())
        # Maximised, the group pills give way to a picker over the list.
        # No folder icon: a group is not a folder, and the group's base
        # folder sits right under it with that icon.
        self.group_picker = QPushButton("")
        self.group_picker.setObjectName("groupPicker")
        self.group_picker.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        set_tooltip(self.group_picker, "Choose a group")
        self.group_picker.clicked.connect(self._show_group_picker)
        self.group_picker.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.group_picker.customContextMenuRequested.connect(
            lambda pos: self._show_group_menu(
                self.current_group(), self.group_picker.mapToGlobal(pos)))
        # The drop-downs' chevron, at the far end: a menu opens from it.
        chevron = QHBoxLayout(self.group_picker)
        chevron.setContentsMargins(0, 0, 10, 0)
        chevron.addStretch(1)
        chevron.addWidget(IconLabel("chevron-down", role="muted", size=14,
                                    palette=self._palette))
        self.group_picker.hide()
        col.insertWidget(0, self.group_picker)

        self.group_tabs = QTabWidget()
        self.group_tabs.setObjectName("groupTabs")
        self.group_tabs.currentChanged.connect(
            lambda _i: self._update_select_bar())
        self.group_tabs.currentChanged.connect(lambda _i: self._sync_group_picker())
        # Must be set before any tab is added.
        self.group_tab_bar = GroupTabBar()
        self.group_tab_bar.setObjectName("groupTabBar")
        self.group_tab_bar.setDrawBase(False)
        self.group_tabs.setTabBar(self.group_tab_bar)
        self.group_tab_bar.dropped_on_group.connect(self._on_drop_on_group)
        self.group_tab_bar.menu_requested.connect(self._show_group_menu)
        self.group_tab_bar.reordered.connect(self._on_tabs_reordered)
        self.new_group_button = IconButton("plus", size=14, palette=self._palette)
        self.new_group_button.setObjectName("newGroupPill")
        set_tooltip(self.new_group_button, "New group")
        self.new_group_button.clicked.connect(self.new_group)
        # Just after the last pill, where the next group will appear.
        self.group_tab_bar.set_trailing(self.new_group_button)
        col.addWidget(self.group_tabs, 1)
        col.addWidget(self.running)
        return top

    def _build_output(self) -> QWidget:
        """The output header -- show/hide, find, errors only, clear, close
        all -- over the tabs. Starts collapsed, as the Tk panel does."""
        from PySide6.QtWidgets import QCheckBox
        panel = QWidget()
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        header = QFrame()
        header.setObjectName("outputHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(8, 2, 8, 2)
        self.output_title = QLabel("Output")
        row.addWidget(self.output_title)
        self.output_toggle = IconButton("chevron-up", outputpanel.SHOW_OUTPUT,
                                        role="link", hover_role="link",
                                        size=14, palette=self._palette)
        self.output_toggle.setFlat(True)
        self.output_toggle.clicked.connect(lambda: self.set_output_expanded(
            not self.output_expanded))
        row.addWidget(self.output_toggle)
        row.addStretch(1)
        clear = IconButton("trash", outputpanel.CLEAR, role="link",
                           hover_role="link", size=14, palette=self._palette)
        clear.setFlat(True)
        clear.clicked.connect(self.clear_output)
        close_all = IconButton("close", outputpanel.CLOSE_ALL, role="link",
                               hover_role="link", size=14, palette=self._palette)
        close_all.setFlat(True)
        close_all.clicked.connect(self.close_all_output)
        row.addWidget(clear)
        row.addWidget(close_all)
        col.addWidget(header)

        # Find and the filter get a row of their own, shown with the tabs: one
        # row of everything is wider than the window's default 540 px, and a
        # layout's minimum width becomes the window's.
        self.output_findbar = QFrame()
        self.output_findbar.setObjectName("outputHeader")
        find = QHBoxLayout(self.output_findbar)
        find.setContentsMargins(8, 0, 8, 2)
        find_label = QLabel(outputpanel.FIND)
        find.addWidget(find_label)
        self.output_find = QLineEdit()
        self.output_find.setObjectName("outputFind")
        find_label.setBuddy(self.output_find)
        self.output_find.setMinimumWidth(60)
        self.output_find.textChanged.connect(self._on_output_query)
        self.output_find.installEventFilter(self)
        find.addWidget(self.output_find, 1)
        self.output_matches = QLabel("")
        find.addWidget(self.output_matches)
        self.output_errors = QCheckBox(outputpanel.ERRORS_ONLY)
        self.output_errors.toggled.connect(self._on_output_filter)
        find.addWidget(self.output_errors)
        col.addWidget(self.output_findbar)

        self.output_tabs = QTabWidget()
        self.output_tabs.setObjectName("outputTabs")
        self.output_tabs.setTabsClosable(True)
        self.output_tabs.tabCloseRequested.connect(self._close_output_tab)
        self.output_tabs.currentChanged.connect(lambda _i: self._sync_output_bar())
        self.output_tabs.currentChanged.connect(lambda _i: self._tint_tab_closes())
        bar = self.output_tabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._show_output_tab_menu)
        self.add_output_tab(outputpanel.ALL, "All")
        from PySide6.QtWidgets import QTabBar
        for side in (QTabBar.ButtonPosition.RightSide, QTabBar.ButtonPosition.LeftSide):
            self.output_tabs.tabBar().setTabButton(0, side, None)
        col.addWidget(self.output_tabs, 1)
        self.output_panel = panel
        self.output_expanded = True
        self._output_search_timer = QTimer(self)
        self._output_search_timer.setSingleShot(True)
        self._output_search_timer.setInterval(300)
        self._output_search_timer.timeout.connect(self._refresh_output_search)
        self.set_output_expanded(False)
        return panel

    # -- the output header -----------------------------------------------------------
    def set_output_expanded(self, on: bool, *, force: bool = False) -> None:
        if on == self.output_expanded and not force:
            return
        self.output_expanded = on
        self.output_tabs.setVisible(on)
        self.output_findbar.setVisible(on)
        self.output_toggle.setText(outputpanel.HIDE_OUTPUT if on
                                   else outputpanel.SHOW_OUTPUT)
        self.output_toggle.set_shape("chevron-down" if on else "chevron-up")
        # Collapsed, the panel is its header and no taller: capped here, so
        # the splitter cannot hand it empty space -- which it did when this
        # ran during construction, before the splitter existed.
        self.output_panel.setMaximumHeight(
            16777215 if on else self.output_panel.layout().itemAt(0).widget()
            .sizeHint().height())
        # Only while the panel is under the list: maximised, it is in the
        # detail pane, and the list has the whole height.
        splitter = getattr(self, "splitter", None)
        if splitter is not None and self.output_panel.parentWidget() is splitter:
            total = sum(splitter.sizes()) or self.height()
            header = self.output_panel.sizeHint().height() if not on else 0
            splitter.setSizes([total - header, header] if not on
                              else [int(total * 0.6), int(total * 0.4)])

    def active_output_pane(self):
        return self._output_tabs.get(self.active_output_key() or "")

    def _sync_output_bar(self) -> None:
        """Point the find box and the filter at the tab now in front."""
        pane = self.active_output_pane()
        if pane is None:
            return
        for widget, value in ((self.output_find, pane.query),
                              (self.output_errors, pane.errors_only)):
            widget.blockSignals(True)
            if widget is self.output_find:
                widget.setText(value)
            else:
                widget.setChecked(value)
            widget.blockSignals(False)
        pane.search()
        self.output_matches.setText(pane.match_label())

    def _on_output_query(self, text: str) -> None:
        pane = self.active_output_pane()
        if pane is not None:
            pane.set_query(text)
            self.output_matches.setText(pane.match_label())

    def _on_output_filter(self, on: bool) -> None:
        pane = self.active_output_pane()
        if pane is not None:
            pane.set_errors_only(on)
            self.output_matches.setText(pane.match_label())

    def step_output_match(self, forward: bool) -> None:
        pane = self.active_output_pane()
        if pane is not None:
            pane.step(forward)
            self.output_matches.setText(pane.match_label())

    def _refresh_output_search(self) -> None:
        pane = self.active_output_pane()
        if pane is not None and pane.query:
            pane.search()
            self.output_matches.setText(pane.match_label())

    def eventFilter(self, obj, event) -> bool:            # noqa: N802
        """Enter / Shift+Enter step through matches; Esc clears the find box.
        In the search box, Down goes to the first row and Esc clears it."""
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "search_box", None) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self.focus_first_row()
                return True
            if key == Qt.Key.Key_Escape and self.search_box.text():
                self.search_box.clear()
                return True
        if obj is getattr(self, "output_find", None) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.step_output_match(
                    not event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                return True
            if key == Qt.Key.Key_Escape:
                self.output_find.clear()
                return True
        return super().eventFilter(obj, event)

    def clear_output(self) -> None:
        pane = self.active_output_pane()
        if pane is not None:
            pane.clear()
            self.output_matches.setText(pane.match_label())

    def close_all_output(self) -> None:
        """Close every tab but All and those still running; clear All."""
        running = ([j.tab_key for j in self._bridge.registry.all()]
                   if self._bridge is not None else [])
        for key in outputpanel.closable(list(self._output_tabs), running):
            self._close_output_key(key)
        self._output_tabs[outputpanel.ALL].clear()
        self._sync_output_bar()

    def _show_output_tab_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        bar = self.output_tabs.tabBar()
        index = bar.tabAt(pos)
        if index < 0:
            return
        widget = self.output_tabs.widget(index)
        key = next((k for k, pane in self._output_tabs.items() if pane is widget), None)
        if key is None:
            return
        menu = QMenu(self)
        handlers = {outputpanel.TAB_COPY: lambda: self.copy_output(key),
                    outputpanel.TAB_SAVE: lambda: self.save_output(key),
                    outputpanel.TAB_CLOSE: lambda: self._close_output_key(key)}
        shapes = {outputpanel.TAB_COPY: "copy", outputpanel.TAB_SAVE: "save",
                  outputpanel.TAB_CLOSE: "close"}
        ink = icons.role_colors(self._palette)["menu"]
        for label in outputpanel.tab_menu(key):
            if label is None:
                menu.addSeparator()
            else:
                action = menu.addAction(icons.icon(shapes[label], ink), label)
                action.setData(label)
                action.triggered.connect(lambda _c=False, go=handlers[label]: go())
        self.popup(menu, bar.mapToGlobal(pos))

    def copy_output(self, key: str) -> None:
        from PySide6.QtWidgets import QApplication
        pane = self._output_tabs.get(key)
        text = pane.plain_text().strip() if pane else ""
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage(outputpanel.COPIED)

    def save_output(self, key: str) -> None:
        pane = self._output_tabs.get(key)
        text = pane.plain_text().strip() if pane else ""
        if not text:
            self.statusBar().showMessage(outputpanel.NOTHING_TO_SAVE)
            return
        path = self.ask_save_path(outputpanel.SAVE_TITLE, "output.txt")
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.statusBar().showMessage(outputpanel.saved_status(path))

    def _close_output_key(self, key: str) -> None:
        pane = self._output_tabs.get(key)
        if pane is not None and key != outputpanel.ALL:
            self._close_output_tab(self.output_tabs.indexOf(pane))

    def _build_menu(self) -> None:
        # File makes and moves things, Options changes how RYOS behaves, Help
        # checks for updates. Everything once sat under Options, with Exit
        # alone in File -- where people look for New and Import.
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        for label, slot, shape in (("New &Script…", self.add_script, "plus"),
                                   ("New &Pipeline…", self.new_pipeline, "bolt"),
                                   ("New &Group…", self.new_group, "folder")):
            action = QAction(label, self)
            action.triggered.connect(slot)
            self._menu_icon(action, shape)
            file_menu.addAction(action)
        file_menu.addSeparator()
        for label, slot, shape in (("&Import config…", self.import_config, "import"),
                                   ("&Export all groups…", self.export_all, "export")):
            action = QAction(label, self)
            action.triggered.connect(slot)
            self._menu_icon(action, shape)
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.triggered.connect(self.close)
        self._menu_icon(quit_action, "close")
        file_menu.addAction(quit_action)

        options = bar.addMenu("&Options")
        self.options_action = QAction("&Options…", self)
        self.options_action.triggered.connect(self.open_options)
        self._menu_icon(self.options_action, "settings")
        options.addAction(self.options_action)
        self.appearance_action = QAction("&Appearance…", self)
        self.appearance_action.triggered.connect(self.open_appearance)
        self._menu_icon(self.appearance_action, "palette")
        options.addAction(self.appearance_action)
        self.startup_action = QAction("Start with &Windows", self)
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(self._startup.enabled())
        self.startup_action.toggled.connect(self.set_start_with_windows)
        options.addAction(self.startup_action)
        options.addSeparator()
        self.select_action = QAction(selection.ENTER_LABEL, self)
        self._menu_icon(self.select_action, "select")
        self.select_action.triggered.connect(
            lambda: self.set_select_mode(not self.select_mode))
        options.addAction(self.select_action)
        options.addSeparator()
        self.delete_all_action = QAction("Delete All…", self)
        self._menu_icon(self.delete_all_action, "trash", danger=True)
        self.delete_all_action.triggered.connect(self.delete_all)
        options.addAction(self.delete_all_action)

        help_menu = bar.addMenu("&Help")
        self.update_action = QAction("Check for &updates", self)
        self.update_action.triggered.connect(
            lambda: self.check_for_updates(manual=True))
        self._menu_icon(self.update_action, "import")
        help_menu.addAction(self.update_action)
        self.report_bug_action = QAction(bugreport.MENU_LABEL, self)
        self.report_bug_action.triggered.connect(self.report_bug)
        self._menu_icon(self.report_bug_action, "bug")
        help_menu.addAction(self.report_bug_action)

    def _menu_icon(self, action, shape: str, *, danger: bool = False) -> None:
        """Give a menu action an icon from the set, re-tinted on a theme change."""
        self._menu_icons.append((action, shape, danger))
        roles = icons.role_colors(self._palette)
        action.setIcon(icons.icon(shape, roles["danger" if danger else "menu"]))

    # -- cards -------------------------------------------------------------
    def set_cards(self, group_name: str, records, base_dir: str = "", *,
                  label: str | None = None) -> None:
        """Add one group tab with its cards.

        ``group_name`` is the database key ("" for ungrouped); ``label`` is
        what the tab shows. The key is stored on the tab, so a card dropped
        on "Ungrouped" moves to "" rather than to a group named "Ungrouped".
        """
        page, made = self._build_page(group_name, records)
        self.card_lists[group_name] = page

        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        holder = QWidget()
        hcol = QVBoxLayout(holder)
        hcol.setContentsMargins(0, 0, 0, 0)
        hcol.setSpacing(2)
        quick = (self._build_quick_run(group_name, base_dir)
                 if base_dir and self._settings.get("quick_run_enabled", True)
                 else None)
        if group_name:
            from .widgets import ElidedLabel
            banner = ElidedLabel(sections.banner_text(base_dir))
            banner.setObjectName("groupBanner" if base_dir else "groupBannerEmpty")
            banner.setCursor(Qt.CursorShape.PointingHandCursor)
            # A label, so a long folder is shortened instead of widening the
            # page; clicking it opens the base-folder dialog.
            banner.mousePressEvent = (
                lambda _e, g=group_name: self.on_group_menu(g, cardmenu.BASE_DIR))
            # Quick Run shares the banner's row: on a row of its own it cost a
            # line of every group page before the first card.
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(IconLabel("folder", role="muted", size=15,
                                    palette=self._palette))
            row.addWidget(banner, 1)
            if quick is not None:
                row.addWidget(quick[0])
            hcol.addLayout(row)
            self.group_banners[group_name] = banner
        if quick is not None:
            hcol.addWidget(quick[1])
        hcol.addWidget(scroll, 1)
        index = self.group_tabs.addTab(
            holder, literal(label if label is not None else group_name))
        self.group_tab_bar.setTabData(index, group_name)
        self._cards.extend(made)

    def _build_page(self, group: str, records) -> tuple:
        """A group's sections filled with cards: (page, cards made)."""
        page = GroupPage(group, self._collapse)
        made = []
        by_section = sections.split(
            [dict(rec, kind=rec.get("kind") or "script") for rec in records])
        for key in sections.ORDER:
            section = page.section(key)
            section.dropped.connect(self._on_drop_in_list)
            for rec in by_section[key]:
                card = self._make_card(rec, group, key)
                section.add_card(card, rec["kind"], rec["id"])
                made.append(card)
            page.sections[key].refresh()
        return page, made

    def _add_all_tab(self, blocks) -> None:
        """The All tab: every group on one page, each under its own header.

        ``blocks`` is (group key, header or None, records) per group. The
        pages here are copies: ``card_lists`` keeps pointing at each group's
        own tab, so moves and neighbours are worked out there.
        """
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self.all_pages = {}
        self.all_headers = {}
        for group, header, records in blocks:
            if header:
                label = QLabel(header)
                label.setObjectName("groupHeader")
                self.all_headers[group] = label
                col.addWidget(label)
            page, made = self._build_page(group, records)
            self.all_pages[group] = page
            col.addWidget(page)
            self._cards.extend(made)
        if not blocks:
            self.all_empty = QLabel(sections.ALL_EMPTY)
            self.all_empty.setObjectName("cardPath")
            col.addWidget(self.all_empty)
        self.all_no_match = QLabel("")
        self.all_no_match.setObjectName("cardPath")
        self.all_no_match.setWordWrap(True)
        self.all_no_match.hide()
        col.addWidget(self.all_no_match)
        col.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        index = self.group_tabs.addTab(scroll, sections.ALL_LABEL)
        # No key: the All tab is not a group, so nothing can be dropped on,
        # renamed or reordered into it. Tabs keyed None are skipped by all three.
        self.group_tab_bar.setTabData(index, None)

    def showing_all(self) -> bool:
        index = self.group_tabs.currentIndex()
        return index >= 0 and self.group_tab_bar.tabData(index) is None

    def _make_card(self, rec: dict, group: str, section: str):
        """One card for ``rec`` in ``section``, wired to its handlers.

        A favourite is built twice, once for Favorites and once for its own
        section; ``card.section`` says which, so a move from the menu moves it
        among the neighbours it is shown with.
        """
        # Maximised, the list is a list: compact rows, the detail beside it.
        compact = bool(self._settings.get("compact_mode", False)) or self.workspace
        size = self._settings.get("card_size", "medium")
        shade = readable_highlight(rec.get("color"), self._palette["card_bg"],
                                   self._palette["card_hover"])
        kind = rec["kind"]
        chip = section == sections.FAVORITES
        # A card built mid-run (a search, a group switch) still says so.
        live = self._live_statuses().get((kind, rec["id"]))
        last_status = live or rec.get("status")
        if kind == cardmenu.PIPELINE:
            card = PipelineCard(pipeline_id=rec["id"], name=rec["name"],
                                step_count=rec.get("steps", 0), chip=chip,
                                palette=self._palette, compact=compact, size=size,
                                is_favorite=bool(rec.get("favorite")),
                                label_color=shade, last_status=last_status,
                                badges=cardstyle.pipeline_badges(
                                    scheduled=bool(rec.get("scheduled")),
                                    outside_steps=rec.get("outside_steps", ()),
                                    base_dir=rec.get("base_dir", "")),
                                step_names=rec.get("step_names"))
        else:
            card = ScriptCard(script_id=rec["id"], name=rec["name"],
                              path=rec.get("path", ""), palette=self._palette,
                              compact=compact, size=size, chip=chip,
                              is_favorite=bool(rec.get("favorite")),
                              label_color=shade, last_status=last_status,
                              param_choices=scriptform.card_param_choices(
                                  rec.get("params", ""), rec.get("presets") or []),
                              badges=cardstyle.script_badges(
                                  temp_param=bool(rec.get("temp_param")),
                                  scheduled=bool(rec.get("scheduled")),
                                  outside=rec.get("outside", ()),
                                  base_dir=rec.get("base_dir", "")),
                              base_dir=rec.get("base_dir", ""),
                              last_run=rec.get("last_run"))
        card.section = section
        status = {"ok": ", last run OK", "error": ", last run failed",
                  "stopped": ", last run stopped"}.get(
            rec.get("status") or "", "")
        card.setAccessibleName(f"{rec['name']}{status}")
        card.setAccessibleDescription(sections.ROW_KEYS_HINT)
        card.activated.connect(
            lambda k=kind, i=rec["id"], s=section: self.select_item(k, i, s))
        # No hover preview beside the detail pane, which says it all.
        if (compact and not self.workspace
                and self._settings.get("hover_preview", True)):
            from .widgets import HoverPreview
            card.preview = HoverPreview(
                card, lambda popup, r=rec: self._fill_preview(popup, r),
                delay_ms=cardstyle.PREVIEW_DELAY_MS)
        if kind == cardmenu.PIPELINE:
            card.steps_clicked.connect(
                lambda _pid, c=card, r=rec: self.show_steps_popup(c, r))
        if self._on_run is not None:
            card.run_requested.connect(self._on_run)
        elif "run_with" in rec:
            card.run_requested.connect(
                lambda _id, c=card, r=rec: self.run_script_card(c, r))
            card.run_with_param_requested.connect(
                lambda _id, c=card, r=rec: self.run_with_param(c, r))
        elif "run" in rec:
            card.run_requested.connect(lambda _id, go=rec["run"]: go())
        card.stop_requested.connect(lambda item_id, k=kind: self._stop_item(k, item_id))
        if getattr(self, "_bridge", None) is not None:
            card.set_own_run((kind, rec["id"]) in own_runs(self._bridge.registry.all()))
        self._records[(kind, rec["id"])] = (rec, group)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, c=card, k=kind, i=rec["id"], s=section:
                self._show_card_menu(k, i, c.mapToGlobal(pos), s))
        card.favorite_toggled.connect(
            lambda item_id, fav, k=kind: self._set_favorite(k, item_id, fav))
        card.copy_requested.connect(
            lambda k=kind, i=rec["id"]: self.copy_item(k, i))
        # On All, a row's own group is the one it belongs to.
        card.paste_requested.connect(lambda g=group: self.paste_into(g))
        if kind == cardmenu.PIPELINE:
            card.edit_requested.connect(
                lambda item_id, n=rec["name"]: self._edit_pipeline(item_id, n))
        else:
            card.edit_requested.connect(self.edit_script)
        return card

    # -- previews: the compact card's hover detail, and a pipeline's steps ----------
    def _fill_preview(self, popup, rec: dict) -> None:
        """The detail a compact card hides: a script's path and parameters, or a
        pipeline's steps -- the rows `cardstyle` gives both toolkits."""
        from PySide6.QtWidgets import QGridLayout
        col = popup.layout()
        title = QLabel(rec.get("name", ""))
        title.setObjectName("cardName")
        col.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        col.addLayout(grid)
        if rec.get("kind") == cardmenu.PIPELINE:
            steps = self._db.list_pipeline_steps(rec["id"]) if self._db else []
            rows = cardstyle.pipeline_preview_rows(steps)
            if not rows:
                empty = QLabel(cardstyle.NO_STEPS)
                empty.setObjectName("cardPath")
                grid.addWidget(empty, 0, 0)
            for r, (number, name, path, override) in enumerate(rows):
                cells = [number, name, path] + ([f"[{override}]"] if override else [])
                for c, text in enumerate(cells):
                    label = QLabel(text)
                    label.setObjectName("cardName" if c == 1 else "cardPath")
                    grid.addWidget(label, r, c)
        else:
            rows = cardstyle.script_preview_rows(rec.get("path", ""),
                                                 rec.get("params", ""))
            for r, (label, value, dim) in enumerate(rows):
                head = QLabel(label)
                head.setObjectName("cardPath")
                cell = QLabel(value)
                cell.setObjectName("cardPath" if dim else "cardName")
                grid.addWidget(head, r, 0)
                grid.addWidget(cell, r, 1)

    def show_steps_popup(self, card, rec: dict) -> None:
        """A pipeline's steps, from a click on its step count; a second click,
        or a click anywhere else, closes it."""
        existing = getattr(self, "steps_popup", None)
        if existing is not None and existing.isVisible():
            existing.close()
            self.steps_popup = None
            return
        from PySide6.QtCore import QPoint
        popup = QFrame(self, Qt.WindowType.Popup)
        popup.setObjectName("hoverPreview")
        QVBoxLayout(popup).setContentsMargins(12, 8, 12, 8)
        self._fill_preview(popup, rec)
        popup.adjustSize()
        anchor = card.steps_label if hasattr(card, "steps_label") else card
        popup.move(anchor.mapToGlobal(QPoint(0, anchor.height())))
        popup.show()
        self.steps_popup = popup

    # -- quick run ---------------------------------------------------------
    def _quick_run_index(self):
        """One index for the window, shared by every group's bar.

        Results come back through MainThreadInvoker, not QTimer.singleShot,
        which would never fire when called from the index's worker thread.
        """
        if self._qr_index is None:
            from ..quickrun_index import QuickRunIndex
            self._invoker = MainThreadInvoker(self)
            self._qr_index = QuickRunIndex(schedule=self._invoker,
                                           on_ready=self._on_qr_index_ready)
        return self._qr_index

    def _qr_index_args(self) -> dict:
        s = self._settings
        return {
            "ttl": s.get("quick_run_index_ttl", 300),
            "allowed_exts": {e.lower() for e in
                             (s.get("quick_run_index_extensions") or [])},
            "max_files": s.get("quick_run_index_max_files", 5000),
        }

    def _on_qr_index_ready(self, base_dir: str) -> None:
        for bar in self.quick_run_bars.values():
            bar.on_index_ready(base_dir)

    def _build_quick_run(self, group_name: str, base_dir: str) -> tuple:
        """(the toggle, the bar) -- the toggle sits beside the folder banner.

        Neutral, not filled: filled near-black in the light themes, it was the
        heaviest thing on the page, outweighing the green Run buttons.
        """
        toggle = IconButton("bolt", "Quick Run", role="link", hover_role="link",
                            size=14, palette=self._palette)
        toggle.setObjectName("quickRunToggle")
        bar = QuickRunBar(
            base_dir=base_dir, index=self._quick_run_index(),
            index_args=self._qr_index_args,
            max_suggestions=self._settings.get("quick_run_max_suggestions", 10),
            autocomplete=self._settings.get("quick_run_autocomplete", True))
        bar.hide()
        toggle.clicked.connect(
            lambda: bar.close_bar() if bar.isVisible() else bar.open())
        bar.submitted.connect(
            lambda raw, g=group_name, b=base_dir: self.quick_run_submit(g, b, raw))
        self.quick_run_bars[group_name] = bar
        return toggle, bar

    def quick_run_submit(self, group_name: str, base_dir: str, raw: str, *,
                         choose=None, on_error=None) -> bool:
        """Resolve, register and run what was typed. True when it started.

        The same flow as the Tk bar, through `quickrun_actions`: nothing typed
        does nothing; no match says why; several matches ask which; one match
        is reused or registered and then run. ``choose`` and ``on_error`` are
        injectable so the flow can be exercised without modal dialogs.
        """
        from ..quickrun import display_relpath
        from ..quickrun_actions import (CHOOSE, ERROR, NOTHING, chosen_path,
                                        ensure_script, plan_submit)

        plan = plan_submit(raw, base_dir)
        if plan.kind == NOTHING:
            return False
        bar = self.quick_run_bars.get(group_name)
        if bar is not None:
            bar.close_bar()
        if plan.kind == ERROR:
            (on_error or self._show_quick_run_error)(plan.error)
            return False
        abs_path = plan.abs_path
        if plan.kind == CHOOSE:
            pick = (choose or self._choose_candidate)(list(plan.candidates))
            if not pick:
                return False
            abs_path = chosen_path(base_dir, pick)
        if self._bridge is None:
            return False
        got = ensure_script(self._bridge.db, abs_path, group_name,
                            plan.params, plan.params_explicit)
        return self._bridge.run_script(
            got.script_id, display_relpath(abs_path, base_dir), abs_path,
            got.params, got.interpreter, active_group=group_name)

    def _show_quick_run_error(self, message: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Quick Run", message)

    def _choose_candidate(self, candidates: list) -> str | None:
        from PySide6.QtWidgets import QInputDialog
        pick, ok = QInputDialog.getItem(self, "Quick Run",
                                        "Several scripts match — which one?",
                                        candidates, 0, False)
        return pick if ok else None

    # -- loading from the database ------------------------------------------
    UNGROUPED_LABEL = "Ungrouped"

    def load_from_db(self, db) -> None:
        """Build every group tab from the database, replacing what is shown.

        Keeps whichever group was in front, so a reload after a drop does not
        throw the user back to the first tab.
        """
        self._db = db
        first_load = self.group_tabs.count() == 0
        current = self.current_group()
        self.set_select_mode(False)
        self._clear_groups()
        statuses = db.last_pipeline_status()
        scheduled_scripts, scheduled_pipes = db.scheduled_ids()
        scripts = db.list_all()
        work_dirs = db.script_work_dirs()
        groups = [(name, base) for name, base in db.list_groups_with_meta()]
        has_ungrouped = (any((rec[8] or "") == "" for rec in scripts)
                         or bool(db.list_pipelines("")))
        if has_ungrouped:
            groups.append(("", ""))
        by_group = {}
        for name, base in groups:
            records = []
            for rec in scripts:
                if (rec[8] or "") != name:
                    continue
                sid, sname, path, params, interp = rec[0], rec[1], rec[2], rec[3], rec[4]
                wd = work_dirs.get(sid, "")
                records.append({
                    "id": sid, "name": sname, "path": path, "status": rec[7],
                    "work_dir": wd,
                    "outside": basefolder.outside_parts(path, wd, base or ""),
                    "base_dir": base or "", "last_run": rec[6],
                    "favorite": bool(rec[10]), "color": rec[11],
                    "params": params or "", "temp_param": bool(rec[9]),
                    "scheduled": sid in scheduled_scripts,
                    "presets": db.list_param_presets(sid),
                    "run_with": (lambda prm, s=sid, n=sname, pth=path,
                                 i=interp, g=name: self._run_script_record(
                                     s, n, pth, prm, i or "", g)),
                })
            for pid, pname, fav, color in db.list_pipelines(name):
                steps = db.list_pipeline_steps(pid)
                records.append({
                    "id": pid, "kind": "pipeline", "name": pname,
                    "favorite": bool(fav), "color": color,
                    "scheduled": pid in scheduled_pipes,
                    "base_dir": base or "",
                    "outside_steps": tuple(
                        i for i, r in enumerate(steps, 1)
                        if basefolder.outside_parts(
                            r[3], r[9] if len(r) > 9 else "", base or "")),
                    "steps": len(steps),
                    "step_names": [row[2] for row in steps],
                    "status": statuses.get(pid),
                    "run": (lambda p=pid, n=pname, g=name:
                            self._run_pipeline_record(p, n, g)),
                })
            self.set_cards(name, records, base,
                           label=name or self.UNGROUPED_LABEL)
            by_group[name] = records
        named = [name for name, _base in groups if name]
        self._add_all_tab([(g, header, by_group.get(g, []))
                           for g, header in sections.all_view_groups(named,
                                                                     has_ungrouped)])
        if first_load:
            current = grouping.initial_group(self._settings, named)
        self.show_group(current)
        # The cards were all replaced: point the detail pane at the new one,
        # and filter them again -- a reload (a favourite, an edit) brought
        # every card back while the box still showed the search.
        self._show_selected()
        if self.search_box.text():
            self._apply_search(self.search_box.text())
        # A schedule saved, an item renamed or deleted: Up next may differ.
        self.refresh_activity()

    def reload(self) -> None:
        if self._db is not None:
            self.load_from_db(self._db)

    def _clear_groups(self) -> None:
        while self.group_tabs.count():
            widget = self.group_tabs.widget(0)
            self.group_tabs.removeTab(0)
            widget.deleteLater()
        self._cards.clear()
        self.card_lists.clear()
        self.all_pages = {}
        self.all_headers = {}
        self.all_no_match = None
        self.group_banners = {}
        self._records.clear()
        self.quick_run_bars.clear()

    def current_group(self) -> str | None:
        index = self.group_tabs.currentIndex()
        if index < 0:
            return None
        key = self.group_tab_bar.tabData(index)
        return key if isinstance(key, str) else None

    def show_group(self, group: str | None) -> None:
        for i in range(self.group_tabs.count()):
            if self.group_tab_bar.tabData(i) == group:
                self.group_tabs.setCurrentIndex(i)
                return

    def _run_script_record(self, sid, name, path, params, interp, group) -> None:
        if self._bridge is None:
            return
        if self._db is not None:
            parts, spath, work_dir, base = basefolder.script_outside(self._db, sid)
            if basefolder.should_warn(self._settings, parts) and not self._go_outside(
                    basefolder.warning_text(name, parts, spath, work_dir, base)):
                return
        self._bridge.run_script(sid, name, path, params, interp,
                                active_group=group,
                                on_refusal=self._show_refusal)

    def _run_pipeline_record(self, pid, name, group) -> None:
        if self._bridge is None:
            return
        if self._db is not None:
            steps, base = basefolder.pipeline_outside(self._db, pid, group)
            if basefolder.should_warn(self._settings, steps) and not self._go_outside(
                    basefolder.pipeline_warning_text(name, steps, base)):
                return
        self._bridge.run_pipeline(pid, name, active_group=group,
                                  candidate_groups=list(self.card_lists),
                                  on_refusal=self._show_refusal)

    def _go_outside(self, text: str) -> bool:
        """Ask before a run outside its group's base folder; True to run.
        Through run_dialog, so a test answers it without a box on screen."""
        from .smalldialogs import OutsideBaseWarningDialog
        dlg = OutsideBaseWarningDialog(text, self)
        self.run_dialog(dlg)
        run, save = basefolder.after_warning(self._settings, dlg.run, dlg.dont_warn)
        if save:
            self._save_settings(self._settings)
        return run

    def _show_refusal(self, refusal) -> None:
        """Say why a run did not start, in the register it asked for.

        Hitting the job cap is a notice, a missing file is an error -- the
        severity travels with the refusal, as in the Tk app.
        """
        show = self.inform if refusal.severity == "info" else self.warn
        show(refusal.title, refusal.message)

    # -- drag and drop -------------------------------------------------------
    def _on_drop_in_list(self, payload, before_id) -> None:
        """A card dropped among its siblings: reorder, by the shared rule."""
        from .. import dragdrop
        action = dragdrop.resolve_drop(
            dragged=True, target_group=None, card_group=payload.group,
            in_favorites=False, active_group=payload.group,
            insert_before=before_id)
        if action.kind != dragdrop.REORDER or self._db is None:
            return
        dragdrop.apply_reorder(self._db, payload.kind, payload.item_id,
                               action.group, action.before_id)
        # Deferred: this runs inside the dropped-on widget's own dropEvent,
        # and reload() replaces that widget.
        QTimer.singleShot(0, self.reload)

    def _on_drop_on_group(self, payload, group: str) -> None:
        """A card dropped on a group's tab: move it there, by the shared rule."""
        from .. import dragdrop
        action = dragdrop.resolve_drop(
            dragged=True, target_group=group, card_group=payload.group,
            in_favorites=False, active_group=payload.group,
            insert_before=None)
        if action.kind != dragdrop.MOVE_TO_GROUP or self._db is None:
            return
        warning = dragdrop.apply_move(self._db, payload.kind, payload.item_id,
                                      action.group)
        QTimer.singleShot(0, self.reload)
        self.statusBar().showMessage(warning or f"Moved to '{group or self.UNGROUPED_LABEL}'.")

    # -- where the window goes -------------------------------------------------------
    def geometry_string(self) -> str:
        return screens.format_geometry(self.width(), self.height(), self.x(), self.y())

    #: After placing the window: how long to hold it to that geometry, how
    #: many times to put it back, and the largest drift that counts as
    #: Windows' correction rather than a real move. See `set_geometry_string`.
    GEOMETRY_GUARD_S = 0.5
    GEOMETRY_GUARD_TRIES = 3
    GEOMETRY_DRIFT_PX = 24

    def set_geometry_string(self, geometry: str) -> None:
        """Put the window at 'WxH+X+Y', and keep it there across a DPI change.

        Moving a window between monitors with different scaling (100% and
        125%, say) makes Windows send its own resize and move a few
        milliseconds later -- its suggested rectangle, scaled from the old
        monitor, which lands a frame's width off: asked for 540x640+100+50,
        got 542x648+99+42. Saved on quit and re-applied on start, that grew
        the window on every start.

        It arrives after this call returns, and whether it is coming cannot
        be told reliably beforehand: a new window's screen is not known to Qt
        until Windows has shown it. So for a short while, a resize or move
        that leaves the window a *little* off target -- a frame's width, not
        a real drag or the app's own resize -- puts the requested geometry
        back, a bounded number of times.
        """
        parsed = screens.parse_geometry(geometry)
        if parsed is None:
            return
        import time
        self._geometry_target = parsed
        self._geometry_guard_until = time.monotonic() + self.GEOMETRY_GUARD_S
        self._geometry_tries = self.GEOMETRY_GUARD_TRIES
        self._apply_geometry(parsed)
        QTimer.singleShot(int(self.GEOMETRY_GUARD_S * 1000) + 100,
                          lambda: self._check_geometry(parsed))

    @classmethod
    def is_drift(cls, now: tuple, target: tuple) -> bool:
        """Off target, but only by a frame's width: Windows' correction."""
        deltas = [abs(a - b) for a, b in zip(now, target)]
        return any(deltas) and max(deltas) <= cls.GEOMETRY_DRIFT_PX

    def _apply_geometry(self, parsed) -> None:
        w, h, x, y = parsed
        self.resize(w, h)
        self.move(x, y)

    def _current_geometry(self) -> tuple:
        return (self.width(), self.height(), self.x(), self.y())

    def _guard_geometry(self) -> None:
        """A resize or move just happened: correct it if it undid a placement."""
        import time
        target = getattr(self, "_geometry_target", None)
        if (target is None or time.monotonic() > self._geometry_guard_until
                or self._geometry_tries <= 0 or getattr(self, "_geometry_fix_queued", False)):
            return
        self._geometry_fix_queued = True

        def fix():
            self._geometry_fix_queued = False
            if (self._geometry_tries > 0
                    and self.is_drift(self._current_geometry(), target)):
                self._geometry_tries -= 1
                self._apply_geometry(target)
        QTimer.singleShot(0, fix)

    def _check_geometry(self, parsed) -> None:
        """Log if, after the guard, the window still is not where it was put.

        Evidence rather than a fix: the guard should have corrected it, and if
        a real desktop defeats it, the log says with what.
        """
        if (self.isVisible() and not self.isMinimized()
                and self._current_geometry() != tuple(parsed)
                and getattr(self, "_geometry_target", None) == parsed):
            from ..logger import get_logger
            get_logger("qtui.shell").warning(
                "Window asked for %s, got %s (frame margins %s)",
                screens.format_geometry(*parsed),
                screens.format_geometry(*self._current_geometry()),
                self.windowHandle().frameMargins() if self.windowHandle() else None)

    def apply_placement(self, launched_at_startup: bool = False) -> None:
        """Open where the Tk app would: saved, moved to the cursor's monitor,
        or centred there; snapped to a corner; always-on-top if set.

        The final geometry, snap included, is worked out first and applied
        once, so the DPI guard in `set_geometry_string` holds the window to
        where it should end up rather than to a step on the way.
        """
        s = self._settings
        self.apply_topmost()
        target = (self.cursor_area()
                  if screens.follows_cursor(s, launched_at_startup) else None)
        size = (int(s.get("window_width", 540)), int(s.get("window_height", 640)))
        geometry = screens.initial_geometry(s, size=size, target=target,
                                            work_area_at=self.area_at)
        final = self._snapped(geometry or self.geometry_string(), target)
        if geometry or final != self.geometry_string():
            self.set_geometry_string(final)

    def _snapped(self, geometry: str, work_area=None) -> str:
        """``geometry`` moved into the snap corner, if one is set."""
        corner = screens.snapping(self._settings)
        parsed = screens.parse_geometry(geometry)
        if not corner or parsed is None:
            return geometry
        w, h, x, y = parsed
        area = work_area or self.area_at(x + w // 2, y + h // 2)
        if area is None:
            return geometry
        return screens.format_geometry(w, h, *screens.snap_position(corner, w, h, area))

    def snap_to_corner(self, work_area=None) -> None:
        final = self._snapped(self.geometry_string(), work_area)
        if final != self.geometry_string():
            self.set_geometry_string(final)

    def apply_topmost(self) -> None:
        on = bool(self._settings.get("always_on_top", False))
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != on:
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
            if visible:
                self.show()       # changing a window flag hides the window

    def _remember_normal(self) -> None:
        if self.isVisible() and self.windowState() == Qt.WindowState.WindowNoState:
            self._last_normal_geometry = self.geometry_string()

    def moveEvent(self, event) -> None:                   # noqa: N802
        super().moveEvent(event)
        self._guard_geometry()
        self._remember_normal()

    def resizeEvent(self, event) -> None:                 # noqa: N802
        super().resizeEvent(event)
        self._guard_geometry()
        self._remember_normal()

    def set_start_with_windows(self, on: bool) -> None:
        try:
            self._startup.set(on)
        except OSError:
            self.warn("Could not change startup",
                      "RYOS could not update the startup setting.")
        self.startup_action.blockSignals(True)
        self.startup_action.setChecked(self._startup.enabled())
        self.startup_action.blockSignals(False)

    def open_options(self) -> None:
        from .dialogs import OptionsDialog
        self.run_dialog(OptionsDialog(dict(self._settings), self,
                                      on_save=self.apply_settings))

    def apply_settings(self, new: dict) -> None:
        """Take saved options, as Tk's _apply does: store, log level, window."""
        self._settings.update(new)
        self._save_settings(self._settings)
        if self._bridge is not None:
            # The bridge keeps its own copy; a new job cap must reach it.
            self._bridge._settings.update(new)
        self._configure_logging(self._settings.get("logging_enabled", True),
                                self._settings.get("log_level", "INFO"))
        self.apply_topmost()
        self.resize(int(self._settings.get("window_width", self.width())),
                    int(self._settings.get("window_height", self.height())))
        self.snap_to_corner()
        # Compact mode and card size are read when cards are built.
        self._defer_reload()
        self.sync_layout()

    # -- appearance ------------------------------------------------------------------
    def themes_dir(self):
        from ..themes import resolve_user_themes_dir
        return resolve_user_themes_dir(self._settings.get("themes_dir"))

    def custom_themes(self) -> dict:
        """The custom-theme table, read from the themes folder on first use."""
        if self._customs is None:
            from ..themes import load_user_themes
            self._customs = load_user_themes(self.themes_dir())
        return dict(self._customs)

    def open_appearance(self) -> None:
        from .appearance import AppearanceDialog
        self.run_dialog(AppearanceDialog(
            self, settings=self._settings, customs=self.custom_themes(),
            themes_dir=self.themes_dir(),
            on_preview=lambda s: self.apply_appearance(s, persist=False),
            on_save=lambda s: self.apply_appearance(s, persist=True),
            on_customs=self._set_customs))

    def _set_customs(self, table: dict) -> None:
        self._customs = dict(table)

    def apply_appearance(self, subset: dict, persist: bool = True) -> None:
        """Theme and accent, applied live: one stylesheet, then the cards,
        whose highlight colours are shaded against the palette."""
        from ..themes import palette_for
        self._settings.update(subset)
        self.apply_palette(palette_for(self._settings.get("theme", "light"),
                                       self._settings.get("accent_color"),
                                       self.custom_themes()))
        self._defer_reload()
        if persist:
            self._save_settings(self._settings)

    # -- notifications and updates ------------------------------------------------
    def _on_job_notify(self, title: str, body: str) -> None:
        """A job finished: toast, gated by the same setting as Tk."""
        if self._settings.get("notify_on_complete", True):
            self._notifier(title, body)

    def check_for_updates(self, manual: bool = False) -> None:
        """Ask GitHub for the latest release, off the UI thread.

        The automatic check shows a banner only when there is something new;
        a manual one also says when there is nothing, or when GitHub could not
        be reached -- the same rules as the Tk app.
        """
        if not hasattr(self, "_update_invoker"):
            self._update_invoker = MainThreadInvoker(self)

        def work():
            result = self._fetch_release()
            self._update_invoker(lambda: self._update_result(result, manual))
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, result, manual: bool) -> None:
        status, tag, url = notifications.update_status(result, __version__)
        if status == notifications.NEWER:
            self.show_update_banner(tag, url)
        elif manual:
            self.inform(*(notifications.UNREACHABLE_NOTICE
                          if status == notifications.UNREACHABLE
                          else notifications.up_to_date_notice(__version__)))

    def show_update_banner(self, tag: str, url: str) -> None:
        if self.update_banner is not None:
            return
        banner = QFrame()
        banner.setObjectName("updateBanner")
        row = QHBoxLayout(banner)
        row.setContentsMargins(10, 4, 6, 4)
        self.update_label = QLabel(notifications.banner_text(tag, __version__))
        row.addWidget(self.update_label, 1)
        self.update_download = QPushButton("Download")
        self.update_download.setObjectName("primary")
        self.update_download.clicked.connect(lambda: self.open_url(url))
        row.addWidget(self.update_download)
        dismiss = IconButton("close", role="ink", size=14)
        dismiss.setObjectName("quiet")
        set_tooltip(dismiss, "Dismiss")
        dismiss.clicked.connect(self.dismiss_update_banner)
        row.addWidget(dismiss)
        self._top_col.insertWidget(0, banner)
        self.update_banner = banner

    def dismiss_update_banner(self) -> None:
        if self.update_banner is not None:
            self.update_banner.deleteLater()
            self.update_banner = None

    def report_bug(self) -> None:
        """Open a new GitHub issue, filled in with this machine's versions.
        Nothing is sent: the person reviews and submits it on GitHub."""
        import platform

        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion
        if self.workspace:
            layout = "maximised"
        elif self._settings.get("compact_mode", False):
            layout = "compact"
        else:
            layout = "normal"
        env = bugreport.environment(
            __version__, frozen=bool(getattr(sys, "frozen", False)),
            os_name=platform.platform(), python=platform.python_version(),
            qt=f"{qVersion()} (PySide6 {pyside_version})",
            theme=str(self._settings.get("theme", "light")), layout=layout)
        self.open_url(bugreport.issue_url(env))
        self.statusBar().showMessage(bugreport.OPENED, 8000)

    def _open_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    # -- tray, second launches, and closing ---------------------------------------
    def attach_tray(self, tray) -> None:
        """Wire a `qtui.tray.Tray` in: show, exit, and jump to a job's output."""
        self._tray = tray
        tray.show_requested.connect(self.restore_from_tray)
        tray.exit_requested.connect(self.quit_app)
        tray.job_requested.connect(self.show_job_from_tray)
        tray.start()
        self._sync_tray()

    def attach_instance(self, lock, interval_ms: int = 500) -> None:
        """Poll a `single_instance` lock for a second launch asking to restore.

        The lock's listener runs on its own thread and only fills a queue;
        draining it on a UI-thread timer keeps every widget call here.
        """
        self._instance = lock
        self._instance_timer = QTimer(self)
        self._instance_timer.setInterval(interval_ms)
        self._instance_timer.timeout.connect(self._poll_instance)
        self._instance_timer.start()

    def _poll_instance(self) -> None:
        import queue
        try:
            while True:
                verb = self._instance.signals.get_nowait()
                if traypolicy.is_reload(verb):
                    self._refresh_card_statuses()
                    continue
                self.restore_from_tray(
                    follow_cursor=traypolicy.restore_follows_cursor(verb))
        except queue.Empty:
            pass

    def tray_available(self) -> bool:
        return self._tray is not None and self._tray.available

    def _sync_tray(self) -> None:
        if self._tray is not None and self._bridge is not None:
            self._tray.set_jobs([(j.job_id, j.name)
                                 for j in self._bridge.registry.all()])

    def apply_start(self) -> None:
        """Honour start-minimised, once the window has been shown."""
        action = traypolicy.on_start(self._settings, self.tray_available())
        if action == traypolicy.HIDE:
            self.hide_to_tray()
        elif action == traypolicy.MINIMIZE:
            self.showMinimized()

    @property
    def hidden_to_tray(self) -> bool:
        return self._hidden_to_tray

    def hide_to_tray(self) -> None:
        # Maximised (minimised from there or not): it comes back maximised.
        self._restore_maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
        self._hidden_to_tray = True
        self.hide()

    def restore_from_tray(self, follow_cursor: bool = False) -> None:
        target = (self.cursor_area()
                  if follow_cursor and self._settings.get("open_on_cursor_monitor")
                  else None)
        saved = self._last_normal_geometry or self.geometry_string()
        src = (self.area_at(*screens.geometry_origin(saved)) or target
               if target is not None else None)
        move, show = traypolicy.restore_plan(
            getattr(self, "_restore_maximized", False), src, target)
        if move:
            if show == traypolicy.SHOW_MAXIMIZED:
                # Normal first, so it maximises on the monitor it moves to.
                self.setWindowState(Qt.WindowState.WindowNoState)
            self.set_geometry_string(screens.relocate_geometry(saved, src, target))
        if show == traypolicy.SHOW_MAXIMIZED:
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        self._hidden_to_tray = False

    def show_job_from_tray(self, job_id: int) -> None:
        """Restore the window and bring a job's output tab forward."""
        self.restore_from_tray()
        job = self._bridge.registry.get(job_id) if self._bridge else None
        if job is not None and job.tab_key in self._output_tabs:
            self.set_output_expanded(True)
            self.output_tabs.setCurrentWidget(self._output_tabs[job.tab_key])

    def closeEvent(self, event) -> None:                  # noqa: N802
        if self._quitting:
            event.accept()
            return
        event.ignore()
        action = traypolicy.on_close(self._settings, self.tray_available())
        if action == traypolicy.PROMPT:
            from .smalldialogs import CloseToTrayPromptDialog
            dlg = CloseToTrayPromptDialog(self)
            self.run_dialog(dlg)
            action, save = traypolicy.after_prompt(self._settings, dlg.result,
                                                   dlg.dont_ask)
            if save:
                self._save_settings(self._settings)
        if action == traypolicy.HIDE:
            self.hide_to_tray()
        elif action == traypolicy.QUIT:
            self.quit_app()

    def changeEvent(self, event) -> None:                 # noqa: N802
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowStateChange and not self.isMinimized():
            # Maximised or back: after the state settles, like the tray hide.
            QTimer.singleShot(0, self.sync_layout)
        if (event.type() == QEvent.Type.WindowStateChange and self.isMinimized()
                and traypolicy.on_minimize(self._settings, self.tray_available(),
                                           self._hidden_to_tray) == traypolicy.HIDE):
            # Hiding from inside the state change fights the window manager;
            # do it on the next turn.
            QTimer.singleShot(0, self.hide_to_tray)

    def quit_app(self) -> bool:
        """Quit: confirm if jobs are alive, stop them, save, let go. True if quit."""
        alive = ([j for j in self._bridge.registry.all() if j.active_processes()]
                 if self._bridge is not None else [])
        prompt = traypolicy.quit_prompt(len(alive))
        if prompt is not None:
            if self.isHidden() or self.isMinimized():
                self.restore_from_tray()    # the question needs a window
            if not self.ask_yes_no(*prompt):
                return False
        if self._bridge is not None:
            self._bridge.stop()             # terminates what is still running
        grouping.remember_group(self._settings, self.current_group())
        if self._settings.get("remember_window_geometry", True):
            geometry = (self.geometry_string()
                        if self.isVisible() and not self.isMinimized()
                        else self._last_normal_geometry)
            if geometry:
                self._settings["window_geometry"] = geometry
        self._save_settings(self._settings)
        if self._tray is not None:
            self._tray.stop()
        if self._instance is not None:
            self._instance_timer.stop()
            self._instance.release()
        self._quitting = True
        self.close()
        self.on_quit()
        return True

    # -- running with parameters ---------------------------------------------------
    def run_script_card(self, card, rec: dict) -> None:
        """Run as the card's Run button does: the drop-down's parameters, and
        the ask-each-run prompt when the script wants one."""
        params = card.selected_params(rec.get("params", ""))
        if rec.get("temp_param"):
            from .smalldialogs import TempParamDialog
            dlg = TempParamDialog(self, saved_params=params,
                                  title=scriptform.temp_param_title(rec["name"]))
            self.run_dialog(dlg)
            if dlg.result is None:
                return                          # cancelled: no run
            params = scriptform.with_temp_param(params, dlg.result)
        rec["run_with"](params)

    def run_with_param(self, card, rec: dict) -> None:
        """▶+: ask for parameters, keep them as the script's, and run."""
        from .smalldialogs import PresetEntryDialog
        dlg = PresetEntryDialog(self, params=card.selected_params(rec.get("params", "")),
                                title=scriptform.RUN_WITH_PARAMS_TITLE,
                                ok_text="Run")
        self.run_dialog(dlg)
        if dlg.result is None or self._db is None:
            return
        scriptform.remember_run_params(self._db, rec["id"], dlg.result)
        rec["run_with"](dlg.result)
        self._defer_reload()

    # -- pipelines: create -----------------------------------------------------------
    def new_pipeline(self) -> None:
        """Name a pipeline in the group on screen, then open it to add steps."""
        if self._db is None:
            return
        if self.showing_all():
            self.inform(*pipelinesteps.SELECT_GROUP_FIRST)
            return
        group = self.current_group() or ""
        name = self.ask_text(*pipelinesteps.NEW_PIPELINE_PROMPT, "")
        if not (name and name.strip()):
            return
        pid = self._db.create_pipeline(name.strip(), group)
        self.reload()
        self.show_group(group)
        self._edit_pipeline(pid, name.strip())

    # -- files dropped onto the window ------------------------------------------------
    @staticmethod
    def _dropped_files(mime) -> list:
        if mime is None or not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, event) -> None:              # noqa: N802
        # Only files: a card being dragged is the card lists' and tabs' to take.
        if self._dropped_files(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:               # noqa: N802
        if self._dropped_files(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:                   # noqa: N802
        paths = self._dropped_files(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        # After the drop returns: adding reloads the cards under the cursor.
        QTimer.singleShot(0, lambda: self.add_dropped_files(paths))

    def add_dropped_files(self, paths) -> int:
        """Add dropped files as scripts in the group on screen. Returns how many.

        With no groups yet, asks for one first; on the All tab they go to
        ungrouped, as in Tk. Folders are ignored; files outside the group's
        base folder are skipped with a warning.
        """
        if self._db is None:
            return 0
        if not self._db.list_groups():
            name = self.ask_text(*scriptform.FIRST_GROUP_PROMPT, "")
            if not (name and name.strip()):
                return 0
            self._db.create_group(name.strip())
            self.reload()
            self.show_group(name.strip())
        group = self.current_group() or ""
        to_add, skipped = scriptform.plan_file_drop(
            paths, self._db.get_group_base_dir(group), lambda p: Path(p).is_file())
        for path in to_add:
            name, full, interp = scriptform.dropped_script(path)
            self._db.add(name, full, "", interp, group)
        if skipped:
            self.warn(*scriptform.outside_base_notice(group, skipped))
        if to_add:
            self.reload()                   # keeps the tab on screen, All included
        return len(to_add)

    # -- scripts: add and edit ----------------------------------------------------
    def add_script(self) -> None:
        """Open the script dialog for a new script in the group on screen.

        With no groups at all, asks for one first, as the Tk app does.
        """
        if self._db is None:
            return
        if not self._db.list_groups():
            name = self.ask_text(*scriptform.FIRST_GROUP_PROMPT, "")
            if not (name and name.strip()):
                return
            self._db.create_group(name.strip())
            self.reload()
            self.show_group(name.strip())
        self._open_script_dialog(None, self.current_group() or "")

    def edit_script(self, script_id: int) -> None:
        if self._db is not None:
            self._open_script_dialog(script_id, "")

    def _open_script_dialog(self, script_id, group: str) -> None:
        from .scriptdialog import ScriptDialog
        dlg = ScriptDialog(self, db=self._db, script_id=script_id,
                           default_group=group, on_save=self._defer_reload)
        self.run_dialog(dlg)

    # -- groups: create, reorder, import, export, delete all ---------------------
    def new_group(self) -> None:
        if self._db is None:
            return
        from .smalldialogs import NewGroupDialog
        dlg = NewGroupDialog(self, existing=self._db.list_groups())
        self.run_dialog(dlg)
        if not dlg.result:
            return
        name, base_dir = dlg.result
        self._db.create_group(name, base_dir)
        QTimer.singleShot(0, lambda: (self.reload(), self.show_group(name)))

    def _on_tabs_reordered(self, keys: list) -> None:
        if self._db is None:
            return
        self._db.reorder_groups(grouping.group_order(keys))
        tail = [k for k in ("", None) if k in keys]
        if keys[len(keys) - len(tail):] != tail:
            self._defer_reload()        # Ungrouped and All go back to the end

    def export_all(self) -> None:
        if self._db is None:
            return
        path = self.ask_save_path(configio.export_title(None),
                                  configio.export_filename(None))
        if not path:
            return
        try:
            n_scripts, n_pipes = self._db.export_to_file(path)
        except Exception as exc:                # noqa: BLE001 - shown to the user
            self.warn("Export Failed", str(exc))
            return
        self.statusBar().showMessage(configio.export_status(n_scripts, n_pipes,
                                                            path))

    def import_config(self) -> None:
        if self._db is None:
            return
        path = self.ask_open_path(configio.IMPORT_TITLE)
        if not path:
            return
        mode = self.ask_import_mode()
        if mode is None:
            return                              # cancelled
        try:
            added, skipped = self._db.import_from_file(
                path, replace=mode == configio.REPLACE)
        except Exception as exc:                # noqa: BLE001 - shown to the user
            self.warn("Import failed", str(exc))
            return
        self._defer_reload()
        self.statusBar().showMessage(configio.import_status(added, skipped))

    def delete_all(self) -> None:
        if self._db is None:
            return
        prompt = configio.delete_all_prompt_from(self._db)
        if prompt is None or not self.ask_yes_no(*prompt):
            return
        self._db.delete_all()
        self._defer_reload()

    # -- select mode -------------------------------------------------------------
    def _build_select_bar(self) -> QWidget:
        self.select_bar = QFrame()
        self.select_bar.setObjectName("selectBar")
        row = QHBoxLayout(self.select_bar)
        row.setContentsMargins(10, 4, 6, 4)
        self.select_label = QLabel(selection.HINT)
        self.select_label.setWordWrap(True)
        row.addWidget(self.select_label, 1)
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.toggle_select_all)
        self.run_selected_button = IconButton("play", "Run selected", size=12,
                                              palette=self._palette)
        self.run_selected_button.set_colors(self._palette["btn_run_fg"])
        self.run_selected_button.setObjectName("run")
        self.run_selected_button.clicked.connect(self.run_selected)
        self.delete_selected_button = IconButton("trash", "Delete selected", size=14,
                                                 palette=self._palette)
        self.delete_selected_button.clicked.connect(self.delete_selected)
        for b in (self.select_all_button, self.run_selected_button,
                  self.delete_selected_button):
            row.addWidget(b)
        self.select_bar.setVisible(False)
        return self.select_bar

    def selectable_cards(self) -> list:
        """The script cards select mode acts on: those on the current tab."""
        if self.showing_all():
            pages = list(self.all_pages.values())
        else:
            page = self.card_lists.get(self.current_group())
            pages = [page] if page else []
        return [c for page in pages for c in page.cards
                if isinstance(c, ScriptCard)]

    def selected_cards(self) -> list:
        return [c for c in self.selectable_cards() if c.checkbox.isChecked()]

    def set_select_mode(self, on: bool) -> None:
        if on == self.select_mode:
            return
        self.select_mode = on
        self.select_action.setText(selection.LEAVE_LABEL if on
                                   else selection.ENTER_LABEL)
        self.select_bar.setVisible(on)
        for page in [*self.card_lists.values(), *self.all_pages.values()]:
            for card in page.cards:
                if isinstance(card, ScriptCard):
                    card.checkbox.setChecked(False)
                    card.checkbox.setVisible(on)
                    if on:
                        card.checkbox.toggled.connect(self._update_select_bar)
                    else:
                        try:
                            card.checkbox.toggled.disconnect(
                                self._update_select_bar)
                        except (RuntimeError, TypeError):
                            pass
        self._update_select_bar()

    def _update_select_bar(self, *_args) -> None:
        if not self.select_mode:
            return
        n, total = len(self.selected_cards()), len(self.selectable_cards())
        self.select_label.setText(selection.bar_text(n, total))
        self.select_all_button.setText(selection.select_all_label(n, total))

    def toggle_select_all(self) -> None:
        cards = self.selectable_cards()
        target = selection.select_all_target(c.checkbox.isChecked() for c in cards)
        for card in cards:
            card.checkbox.setChecked(target)
        self._update_select_bar()

    def run_selected(self) -> None:
        """Run every ticked script, up to the job cap, by the shared plan."""
        from ..settings import _SETTINGS_DEFAULTS
        cards = self.selected_cards()
        running = len(self._bridge.registry) if self._bridge is not None else 0
        max_jobs = self._settings.get("max_parallel_jobs",
                                      _SETTINGS_DEFAULTS["max_parallel_jobs"])
        plan = selection.plan_run(len(cards), running, max_jobs)
        for card in cards[:plan.start]:
            card.run_requested.emit(card.script_id)
        if plan.notice:
            self.inform(*plan.notice)
        elif plan.status:
            self.statusBar().showMessage(plan.status)

    def delete_selected(self) -> None:
        ids = [c.script_id for c in self.selected_cards()]
        if not ids:
            self.inform(*selection.NOTHING_TO_DELETE)
            return
        if self._db is None or not self.ask_yes_no(
                *selection.delete_prompt(len(ids), self._db.pipelines_using(ids))):
            return
        self._db.delete_many(ids)
        self._defer_reload()

    # -- right-click menus ------------------------------------------------------
    def card_menu_items(self, kind: str, item_id: int,
                        section: str = sections.SCRIPTS) -> list:
        """The menu for one card, by the shared definition."""
        rec, group = self._records[(kind, item_id)]
        targets = cardmenu.copy_targets(
            self._db.list_groups() if self._db is not None else [], group)
        if kind == cardmenu.PIPELINE:
            return cardmenu.pipeline_menu(favorite=bool(rec.get("favorite")),
                                          color=rec.get("color"),
                                          copy_targets=targets)
        up, down = self._script_neighbours(item_id, group, section)
        return cardmenu.script_menu(favorite=bool(rec.get("favorite")),
                                    color=rec.get("color"),
                                    can_move_up=up is not None,
                                    can_move_down=down is not None,
                                    copy_targets=targets)

    def _script_neighbours(self, item_id: int, group: str,
                           section: str = sections.SCRIPTS) -> tuple:
        """Neighbours among the scripts shown with it: a favourite moves among
        favourites, as in Tk, which shares one stored script order."""
        page = self.card_lists.get(group)
        cards = page.section(section).cards if page else []
        ids = [c.drag_payload.item_id for c in cards
               if c.drag_payload.kind == cardmenu.SCRIPT]
        return cardmenu.neighbours(ids, item_id)

    def _show_card_menu(self, kind: str, item_id: int, pos: QPoint,
                        section: str = sections.SCRIPTS) -> None:
        menu = build_menu(self, self.card_menu_items(kind, item_id, section),
                          lambda key: self.on_card_menu(kind, item_id, key, section),
                          self._palette)
        self.popup(menu, pos)

    def on_card_menu(self, kind: str, item_id: int, key: str,
                     section: str = sections.SCRIPTS) -> None:
        """Carry out one card-menu entry."""
        if self._db is None or (kind, item_id) not in self._records:
            return
        db = self._db
        rec, group = self._records[(kind, item_id)]
        name = rec.get("name", "")
        is_pick, color = cardmenu.picked_highlight(key)
        target = cardmenu.picked_copy_target(key)
        if key == cardmenu.COPY:
            self.copy_item(kind, item_id)
            return
        if target is not None:
            self._copy_into(kind, item_id, target)
            return
        if is_pick:
            cardmenu.set_highlight(db, kind, item_id, color)
        elif key == cardmenu.FAVORITE:
            cardmenu.set_favorite(db, kind, item_id, not rec.get("favorite"))
        elif key in (cardmenu.MOVE_TOP, cardmenu.MOVE_UP, cardmenu.MOVE_DOWN):
            up, down = self._script_neighbours(item_id, group, section)
            if not cardmenu.move(db, key, item_id, up_id=up, down_id=down):
                return
        elif key == cardmenu.CLONE:
            cardmenu.clone(db, kind, item_id)
        elif key == cardmenu.DELETE:
            used_in = db.pipelines_using([item_id]) if kind == cardmenu.SCRIPT else []
            if not self.ask_yes_no(*cardmenu.delete_prompt(kind, name, used_in)):
                return
            cardmenu.delete(db, kind, item_id)
        elif key in (cardmenu.SCHEDULE, cardmenu.HISTORY):
            from .smalldialogs import RunHistoryDialog, ScheduleDialog
            ids = ({"pipeline_id": item_id} if kind == cardmenu.PIPELINE
                   else {"script_id": item_id})
            if key == cardmenu.SCHEDULE:
                dlg = ScheduleDialog(self, db=db, title=name,
                                     on_save=self._defer_reload, **ids)
                dlg.startup = self._startup
                self.run_dialog(dlg)
            else:
                self.run_dialog(RunHistoryDialog(self, db=db, title=name, **ids))
            return
        elif key == cardmenu.EDIT and kind == cardmenu.PIPELINE:
            self._edit_pipeline(item_id, name)
            return
        elif key == cardmenu.EDIT:
            self.edit_script(item_id)
            return
        elif key == cardmenu.RUN_WITH and kind == cardmenu.SCRIPT:
            # Through the row, as its ▶+ does: its preset is the starting point.
            card = self._card_for(kind, item_id, section)
            if card is not None:
                self.run_with_param(card, rec)
            return
        else:
            return
        self._defer_reload()

    def page_on_screen(self):
        """The group page in front: a group's own, or the first on All."""
        group = self.current_group()
        if group is not None:
            return self.card_lists.get(group)
        return next((p for p in self.all_pages.values() if p.rows()), None)

    def focus_first_row(self) -> None:
        """From the search box: into the list, on the first row showing."""
        page = self.page_on_screen()
        rows = page.rows() if page is not None else []
        if rows:
            rows[0].setFocus(Qt.FocusReason.TabFocusReason)
            page.show_row(rows[0])

    def _card_for(self, kind: str, item_id: int, section: str = sections.SCRIPTS):
        """The row showing an item: in ``section`` if it is there, else any."""
        rows = [c for c in self._cards if c.drag_payload is not None
                and (c.drag_payload.kind, c.drag_payload.item_id) == (kind, item_id)]
        return next((c for c in rows if c.section == section), rows[0] if rows else None)

    def _set_favorite(self, kind: str, item_id: int, favorite: bool) -> None:
        if self._db is not None:
            cardmenu.set_favorite(self._db, kind, item_id, favorite)
            self._defer_reload()

    def _edit_pipeline(self, pipeline_id: int, name: str) -> None:
        from .pipeline import PipelineEditorDialog
        if self._db is None:
            return
        _rec, group = self._records.get((cardmenu.PIPELINE, pipeline_id),
                                        ({}, self.current_group() or ""))
        dlg = PipelineEditorDialog(self, db=self._db, pipeline_id=pipeline_id,
                                   name=name, group=group)
        self.run_dialog(dlg)
        # Steps are written as they change, so reload even after Cancel.
        self._defer_reload()

    def _defer_reload(self) -> None:
        # A menu action runs inside the menu's own event handling, on a card
        # the reload is about to replace; rebuilding on the next turn is safe.
        QTimer.singleShot(0, self.reload)

    # -- copy and paste between groups ----------------------------------------------
    def copy_item(self, kind: str, item_id: int) -> None:
        """Hold a script or pipeline for Paste. Only the id is held: Paste
        copies it as it is then, and says so if it was deleted meanwhile."""
        self._copied = (kind, item_id)
        name = self._records.get((kind, item_id), ({}, ""))[0].get("name", "")
        self.statusBar().showMessage(
            f"Copied \u201c{name}\u201d \u2014 right-click a group tab, or press "
            "Ctrl+V on a row, to paste it there.")

    def copied_name(self) -> str | None:
        """The name of what Paste would paste, or None."""
        held = getattr(self, "_copied", None)
        if held is None or self._db is None:
            return None
        return cardmenu.item_name(self._db, *held)

    def paste_into(self, group: str | None) -> None:
        """Paste what Copy holds into ``group``."""
        held = getattr(self, "_copied", None)
        if held is None or group is None:
            return
        self._copy_into(*held, group)

    def _copy_into(self, kind: str, item_id: int, group: str) -> None:
        if self._db is None:
            return
        name = cardmenu.item_name(self._db, kind, item_id)
        if name is None:
            self._copied = None
            self.statusBar().showMessage("Nothing to paste: it was deleted.")
            return
        new_id = cardmenu.copy_to_group(self._db, kind, item_id, group)
        withdrawn = ([name] if new_id is not None
                     and self._db.is_agent_exposed(kind, item_id)
                     and not self._db.is_agent_exposed(kind, new_id) else [])
        self.statusBar().showMessage(cardmenu.copied_status(kind, name, group, withdrawn))
        self._defer_reload()

    # -- the group-tab menu --------------------------------------------------------
    def _show_group_menu(self, group: str, pos: QPoint) -> None:
        if not group:
            return                  # "Ungrouped" is not a group to rename
        menu = build_menu(self, cardmenu.group_menu(self.copied_name()),
                          lambda key: self.on_group_menu(group, key),
                          self._palette)
        self.popup(menu, pos)

    def on_group_menu(self, group: str, key: str) -> None:
        """Carry out one group-tab menu entry."""
        if self._db is None or not group:
            return
        db = self._db
        status = None
        show = self.current_group()
        if key == cardmenu.PASTE:
            self.paste_into(group)
            return
        if key == cardmenu.RENAME_GROUP:
            new, problem = grouping.rename_target(
                group, self.ask_text("Rename Group", f"New name for '{group}':",
                                     group), db.list_groups())
            if problem:
                self.warn("Rename Group", problem)
            if new is None:
                return
            db.rename_group(group, new)
            show = grouping.active_after_rename(show, group, new)
        elif key == cardmenu.CLONE_GROUP:
            existing = db.list_groups()
            new = self.ask_text("Clone Group", f"Name for clone of '{group}':",
                                grouping.unique_clone_name(group, existing))
            if new is None:
                return
            problem = grouping.validate_group_name(new, existing)
            if problem:
                if new.strip():     # blank means they just cleared the box
                    self.warn("Clone Group", problem)
                return
            scripts_n, pipes_n = db.clone_group(group, new.strip())
            show = new.strip()
            status = (f"Cloned '{group}' → '{show}' ({scripts_n} scripts, "
                      f"{pipes_n} pipelines).")
        elif key == cardmenu.BASE_DIR:
            from .smalldialogs import GroupBaseDirDialog
            current = db.get_group_base_dir(group)
            dlg = GroupBaseDirDialog(self, group_name=group, current_dir=current)
            self.run_dialog(dlg)
            change = grouping.base_dir_change(group, current, dlg.result)
            if change is None:
                return
            if change.confirm and not self.ask_yes_no(*change.confirm):
                return
            status, warning = grouping.apply_base_dir_change(db, group, change)
            if warning:
                self.warn(*warning)
        elif key == cardmenu.EXPORT_GROUP:
            path = self.ask_save_path(configio.export_title(group),
                                      configio.export_filename(group))
            if not path:
                return
            try:
                n_scripts, n_pipes = db.export_to_file(path, group_name=group)
            except Exception as exc:            # noqa: BLE001 - shown to the user
                self.warn("Export Failed", str(exc))
                return
            self.statusBar().showMessage(
                configio.export_status(n_scripts, n_pipes, path))
            return
        elif key == cardmenu.DELETE_GROUP:
            if not self.ask_yes_no(*cardmenu.delete_group_prompt(group)):
                return
            db.delete_group(group)
            show = grouping.active_after_delete(show, group, db.list_groups())
        else:
            return
        QTimer.singleShot(0, lambda: (self.reload(), self.show_group(show)))
        if status:
            self.statusBar().showMessage(status)

    # -- the real prompts ------------------------------------------------------------
    def _ask_import_mode(self) -> str | None:
        """Merge, Replace or cancel, on buttons that say which."""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Icon.Question, *configio.IMPORT_MODE, parent=self)
        buttons = {box.addButton(label, QMessageBox.ButtonRole.AcceptRole): mode
                   for mode, label in configio.IMPORT_CHOICES}
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(next(b for b, m in buttons.items() if m == configio.MERGE))
        box.setEscapeButton(cancel)
        box.exec()
        return buttons.get(box.clickedButton())

    def _ask_yes_no(self, title: str, question: str) -> bool:
        from PySide6.QtWidgets import QMessageBox
        return QMessageBox.question(self, title, question) == \
            QMessageBox.StandardButton.Yes

    def _ask_text(self, title: str, prompt: str, initial: str) -> str | None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, title, prompt, text=initial)
        return text if ok else None

    def _inform(self, title: str, message: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, title, message)

    def _warn(self, title: str, message: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, title, message)

    def _ask_open_path(self, title: str) -> str | None:
        from PySide6.QtWidgets import QFileDialog
        path, _filter = QFileDialog.getOpenFileName(
            self, title, "", "JSON (*.json);;All Files (*.*)")
        return path or None

    def _ask_save_path(self, title: str, initial: str) -> str | None:
        from PySide6.QtWidgets import QFileDialog
        path, _filter = QFileDialog.getSaveFileName(
            self, title, initial, "JSON (*.json);;All Files (*.*)")
        return path or None

    # -- search ------------------------------------------------------------
    def _apply_search(self, raw: str) -> None:
        """Hide cards that do not match, using the shared matcher."""
        query = search.normalize_query(raw, False)
        items: set = set()
        matched: set = set()
        for card in self._cards:
            name = getattr(card, "_name", "")
            visible = not query or search.matches(name, query)
            card.setVisible(visible)
            # Count items, not cards: a favourite, or the All tab, shows the
            # same item more than once.
            item = (card.drag_payload.kind, card.drag_payload.item_id)
            items.add(item)
            if visible:
                matched.add(item)
        if query:
            self.search_hint.setText(f"{len(matched)} of {len(items)}")
        else:
            self.search_hint.setText("")
        shown = raw.strip() if query else ""
        for page in self.card_lists.values():
            page.apply_search(shown)
        # On All, a group with no match goes, heading and all; if none is
        # left, one line says so.
        any_found = False
        for group, page in self.all_pages.items():
            found = page.apply_search(shown, say_when_empty=False)
            page.setVisible(found or not shown)
            header = self.all_headers.get(group)
            if header is not None:
                header.setVisible(found or not shown)
            any_found = any_found or found
        if self.all_no_match is not None:
            self.all_no_match.setText(sections.no_match_text(shown) if shown else "")
            self.all_no_match.setVisible(bool(shown) and not any_found
                                         and bool(self.all_pages))

    # -- output ------------------------------------------------------------
    def add_output_tab(self, key: str, label: str) -> OutputPane:
        pane = self._output_tabs.get(key)
        if pane is None:
            pane = OutputPane(self._palette)
            self._output_tabs[key] = pane
            index = self.output_tabs.addTab(pane, literal(label))
            if key != outputpanel.ALL:
                # The app's own cross, in place of Qt's: it was the last icon
                # outside the set, 16 px, and out of Tab's reach.
                close = IconButton("close", size=12, palette=self._palette)
                close.setObjectName("tabClose")
                close.setFixedSize(24, 24)
                set_tooltip(close, "Close tab")
                close.clicked.connect(lambda _c=False, k=key: self._close_output_key(k))
                self.output_tabs.tabBar().setTabButton(
                    index, QTabBar.ButtonPosition.RightSide, close)
                self._tint_tab_closes()
        return pane

    def _tint_tab_closes(self) -> None:
        """The chosen pill is filled with the text colour: its cross takes
        the pill's ink there, the muted ink on the others."""
        from .stylesheet import drawn_colors
        d = drawn_colors(self._palette)
        bar = self.output_tabs.tabBar()
        for i in range(bar.count()):
            close = bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(close, IconButton):
                ink = d["pill_fg"] if i == bar.currentIndex() else d["muted_fg"]
                close.set_colors(ink, d["pill_fg"] if i == bar.currentIndex()
                                 else self._palette["name_fg"])

    def _close_output_tab(self, index: int) -> None:
        widget = self.output_tabs.widget(index)
        for key, pane in list(self._output_tabs.items()):
            if pane is widget:
                if key == outputpanel.ALL:
                    return          # the mirror tab is not closeable
                del self._output_tabs[key]
        self.output_tabs.removeTab(index)

    def active_output_key(self) -> str | None:
        widget = self.output_tabs.currentWidget()
        for key, pane in self._output_tabs.items():
            if pane is widget:
                return key
        return None

    def append_output(self, text: str, tab_key: str | None = None,
                      tag: str | None = None, step: tuple | None = None) -> None:
        """Write a line wherever the shared routing rule says it belongs.
        ``step`` is (token, label) for a line from a step running beside
        others."""
        max_lines = self._settings.get("max_output_lines", 2000)
        scroll = self._settings.get("auto_scroll_output", True)
        for key in outputpanel.target_tabs(tab_key, self.active_output_key(),
                                           self._output_tabs):
            # Only the job's own tab knows its steps: on All, tokens from
            # different jobs would collide, so the line goes in plain.
            self._output_tabs[key].append(text, max_lines, scroll=scroll, tag=tag,
                                          step=step if key == tab_key else None)
        # Re-run an active search once output settles, not on every line.
        if self.output_find.text():
            self._output_search_timer.start()

    def _on_step_state(self, tab_key: str, token: int, label: str, state: str) -> None:
        pane = self._output_tabs.get(tab_key)
        if pane is not None:
            pane.set_step_state(token, label, state)

    # -- jobs --------------------------------------------------------------
    def attach_jobs(self, bridge) -> None:
        """Wire a JobBridge in: output, status, and the running list.

        Kept separate from __init__ so the window can be built and checked
        without the job machinery, which is how tests/qt_smoke.py exercises
        the two independently.
        """
        self._bridge = bridge
        bridge.output.connect(
            lambda tab_key, text, tag=None, step=None:
                self.append_output(text, tab_key, tag, step))
        bridge.step_state.connect(self._on_step_state)
        bridge.status.connect(self.statusBar().showMessage)
        bridge.started.connect(self._on_job_started)
        bridge.finished.connect(self.running.remove)
        # Started, advanced to a step, retrying, finished: each one changes
        # what some card should say (issue #13).
        for sig in (bridge.started, bridge.renamed, bridge.finished):
            sig.connect(self._refresh_card_statuses)
        for sig in (bridge.started, bridge.finished, bridge.renamed):
            sig.connect(lambda _job: self._sync_tray())
        bridge.notify.connect(self._on_job_notify)

    def _on_job_started(self, job) -> None:
        self.add_output_tab(job.tab_key, job.name)
        kind = getattr(job, "kind", None)
        item = getattr(job, "pipeline_id" if kind == cardmenu.PIPELINE else "script_id", None)
        if kind is not None:
            self._latest_tab[(kind, item)] = job.tab_key
        if self.workspace:
            tab = detail.tab_when_run_starts(self._selected, kind,
                                             getattr(job, "script_id", None),
                                             getattr(job, "pipeline_id", None))
            if tab:
                self.detail.show_tab(tab)
        if getattr(job, "pipeline_name", None):
            # A pipeline's tab carries the drawn bolt, as its row's tag did.
            pane = self._output_tabs.get(job.tab_key)
            if pane is not None:
                self.output_tabs.setTabIcon(
                    self.output_tabs.indexOf(pane),
                    icons.icon("bolt", icons.role_colors(self._palette)["pipe"], 14))
        self.running.add(job)
        # Opening the panel on every run takes attention from the cards, so it
        # is opt-in, as in Tk; the tab is there either way.
        if self._settings.get("auto_open_output", False):
            self.set_output_expanded(True)

    def _refresh_card_statuses(self, _job=None) -> None:
        """Bring every card's Run button and chip up to date after a run.

        Every card, not just the job's: a pipeline also sets its steps'
        scripts. Two queries, and only cards whose status moved are touched.
        """
        if self._db is None:
            return
        rows = self._db.list_all()
        scripts = {row[0]: row[7] for row in rows}
        last_runs = {row[0]: row[6] for row in rows}
        pipelines = self._db.last_pipeline_status()
        live = self._live_statuses()
        own = (own_runs(self._bridge.registry.all())
               if getattr(self, "_bridge", None) is not None else set())
        for (kind, item_id), (rec, _group) in self._records.items():
            rec["status"] = (pipelines if kind == cardmenu.PIPELINE
                             else scripts).get(item_id)
            if kind != cardmenu.PIPELINE:
                rec["last_run"] = last_runs.get(item_id)
        for page in [*self.card_lists.values(), *self.all_pages.values()]:
            # The favourite copies too: `cards` leaves them out, and a
            # favourite's top card kept showing its old outcome.
            for card in [*page.cards, *page.favorite_cards]:
                if isinstance(card, PipelineCard):
                    card.set_own_run((cardmenu.PIPELINE, card.pipeline_id) in own)
                    card.set_last_status(
                        live.get((cardmenu.PIPELINE, card.pipeline_id))
                        or pipelines.get(card.pipeline_id))
                else:
                    card.set_own_run((cardmenu.SCRIPT, card.script_id) in own)
                    card.set_last_status(
                        live.get((cardmenu.SCRIPT, card.script_id))
                        or scripts.get(card.script_id))
                    card.set_last_run(last_runs.get(card.script_id))
        if self.workspace:
            self.detail.refresh()
            self.refresh_activity()

    def _live_statuses(self) -> dict:
        """Running / retrying, by card key, for whatever is in flight."""
        if getattr(self, "_bridge", None) is None:
            return {}
        return live_statuses(self._bridge.registry.all())

    def _stop_item(self, kind: str, item_id: int) -> None:
        """Stop the runs of this item's own: a row's Run pressed as Stop."""
        if self._bridge is None:
            return
        for job in list(self._bridge.registry.all()):
            if (kind, item_id) in own_runs([job]):
                self._stop_job(job)

    def _stop_job(self, job) -> None:
        """Stop one job. The row stays until the job actually finishes."""
        if self._bridge is not None:
            self._bridge.stop_job(job)
        self.statusBar().showMessage("Stopped.")

    # -- the maximised layout: list and detail ----------------------------------
    def sync_layout(self) -> None:
        """Put the detail pane beside the list when the window has the room."""
        self.set_workspace(detail.use_workspace(
            self.isMaximized(), self.isFullScreen(),
            bool(self._settings.get("workspace_when_maximized", True))))

    def set_workspace(self, on: bool) -> None:
        """Switch between the single list and the list beside the detail pane.

        The output panel moves with it: under the list, or into the detail's
        Output tab. The rail and the group picker come with the pane; the
        group pills give way to the picker.
        """
        if on == self.workspace:
            return
        self.workspace = on
        self.rail.setVisible(on)
        self.activity.setVisible(on and self.activity_shown)
        self.activity_status.setVisible(on)
        if on:
            self.activity.host_running(self.running)
            self._activity_timer.start()
        else:
            self.activity.release_running(self.running)
            self._top_col.addWidget(self.running)
            self._activity_timer.stop()
        self.group_picker.setVisible(on)
        self.group_tab_bar.setVisible(not on)
        # In its own tab the output is always open: no title, nothing to hide.
        self.output_title.setVisible(not on)
        self.output_toggle.setVisible(not on)
        self._sync_group_picker()
        if on:
            self._output_was_expanded = self.output_expanded
            self.detail.attach_output(self.output_panel)
            self.detail.show()
            self.set_output_expanded(True, force=True)
            total = self.outer.width() or self.width()
            side = activity.WIDTH if self.activity_shown else 0
            self.outer.setSizes([detail.LIST_WIDTH,
                                 max(total - detail.LIST_WIDTH - side, 1), side])
            self.refresh_activity()
        else:
            self.splitter.insertWidget(1, self.output_panel)
            self.splitter.setStretchFactor(1, 2)
            self.detail.hide()
            self.set_output_expanded(getattr(self, "_output_was_expanded", False),
                                     force=True)
        # The list's rows are compact beside the detail: rebuild them to suit.
        if not self._settings.get("compact_mode", False) and self._db is not None:
            self.reload()
        else:
            self._show_selected()

    # -- the rail and the group picker ------------------------------------------------
    def go_to(self, place: str) -> None:
        """Do what a place on the rail stands for."""
        if place == "library":
            card = self._selected_card()
            if card is not None and card.isVisible():
                card.setFocus(Qt.FocusReason.TabFocusReason)
            else:
                self.focus_first_row()
        elif place == "activity":
            self.set_activity_shown(not self.activity_shown)
        elif place == "search":
            self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.search_box.selectAll()
        elif place == "appearance":
            self.open_appearance()
        elif place == "options":
            self.open_options()

    def set_activity_shown(self, on: bool) -> None:
        """Show or hide the Activity bar (maximised); the rail marks it, and
        the choice is remembered."""
        self.activity_shown = on
        self.rail.set_on("activity", on)
        if self._settings.get("activity_shown", True) != on:
            self._settings["activity_shown"] = on
            self._save_settings(self._settings)
        if self.workspace:
            self.activity.setVisible(on)
            if on:
                sizes = self.outer.sizes()
                self.outer.setSizes([sizes[0], max(sizes[1] - activity.WIDTH, 1),
                                     activity.WIDTH])
                self.refresh_activity()

    def refresh_activity(self) -> None:
        """Bring the Activity bar, the rail's count and the status line up
        to date. Only maximised: nothing shows them otherwise."""
        count = self.running.count
        self.rail.set_badge("activity", activity.badge(count))
        if not self.workspace or self._db is None:
            return
        from datetime import datetime
        now = datetime.now()
        names = {key: rec.get("name", "") for key, (rec, _g) in self._records.items()}
        up = activity.up_next(self._db.list_schedules(enabled_only=True), names, now)
        recent = activity.recent(self._db.list_runs(limit=60), now)
        if self.activity_shown:
            self.activity.show_entries(up, recent)
        self.activity_status.setText(activity.summary(count, up[0] if up else None))

    def _open_from_activity(self, kind: str, item_id: int, tab: str) -> None:
        """Show an item from the Activity bar: its group, its row, its tab."""
        found = self._records.get((kind, item_id))
        if found is None:
            return
        _rec, group = found
        if not self.showing_all() and self.current_group() != group:
            self.show_group(group)
        self.select_item(kind, item_id, sections.PIPELINES
                         if kind == cardmenu.PIPELINE else sections.SCRIPTS)
        self.detail.show_tab(tab)

    def _group_labels(self) -> list[tuple[int, str]]:
        """(tab index, label) for each group and All, as the pills read."""
        bar = self.group_tab_bar
        return [(i, bar.tabText(i).replace("&&", "&")) for i in range(bar.count())]

    def _sync_group_picker(self) -> None:
        index = self.group_tabs.currentIndex()
        labels = dict(self._group_labels())
        self.group_picker.setText(labels.get(index, ""))
        self.group_picker.setAccessibleName(f"Group: {labels.get(index, '')}")

    def _show_group_picker(self) -> None:
        """The groups as a menu: one to go to, or a new one."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        current = self.group_tabs.currentIndex()
        for index, label in self._group_labels():
            action = menu.addAction(literal(label))
            action.setCheckable(True)
            action.setChecked(index == current)
            action.triggered.connect(
                lambda _c=False, i=index: self.group_tabs.setCurrentIndex(i))
        menu.addSeparator()
        menu.addAction(detail.NEW_GROUP).triggered.connect(lambda _c=False: self.new_group())
        self.popup(menu, self.group_picker.mapToGlobal(
            QPoint(0, self.group_picker.height())))

    def _script_statuses(self) -> dict:
        """Each script's last outcome as its row shows it -- live, so a
        pipeline's running step says so on its card."""
        return {c.script_id: getattr(c, "_last_status", None) for c in self._cards
                if getattr(c, "script_id", None) is not None}

    def _last_run_of(self, kind: str, item_id: int):
        if self._db is None:
            return None
        ids = ({"pipeline_id": item_id} if kind == cardmenu.PIPELINE
               else {"script_id": item_id})
        return detail.last_run_row(self._db.list_runs(limit=20, **ids), kind)

    def _output_of(self, kind: str, item_id: int):
        """The output tab of the item's latest run, while it is still open."""
        return self._output_tabs.get(self._latest_tab.get((kind, item_id), ""))

    def _open_output_of(self, kind: str, item_id: int) -> None:
        pane = self._output_of(kind, item_id)
        if pane is not None:
            self.output_tabs.setCurrentWidget(pane)
        self.detail.show_tab(detail.OUTPUT_TAB)

    def _history_view(self, kind: str, item_id: int):
        """The History tab's view of ``item_id``'s runs."""
        from .smalldialogs import RunHistoryView
        ids = ({"pipeline_id": item_id} if kind == cardmenu.PIPELINE
               else {"script_id": item_id})
        return RunHistoryView(db=self._db, **ids)

    def select_item(self, kind: str, item_id: int,
                    section: str = sections.SCRIPTS) -> None:
        """Choose one item; maximised, the detail pane shows it."""
        self._selected = (kind, item_id, section)
        self._show_selected()

    def _selected_section(self) -> str:
        return self._selected[2] if self._selected else sections.SCRIPTS

    def _selected_card(self):
        """The chosen item's row: the one clicked, in the tab now showing if
        it is there -- a favourite has a second row, and All a copy of each."""
        if not self._selected:
            return None
        kind, item_id, section = self._selected
        rows = [c for c in self._cards if c.drag_payload is not None
                and (c.drag_payload.kind, c.drag_payload.item_id) == (kind, item_id)]
        page = self.group_tabs.currentWidget()
        in_view = [c for c in rows if page is not None and page.isAncestorOf(c)]
        for pool in (in_view, rows):
            for c in pool:
                if c.section == section:
                    return c
        return (in_view or rows or [None])[0]

    def _show_selected(self) -> None:
        """Mark the chosen row and fill the detail pane from it."""
        card = self._selected_card() if self.workspace else None
        for c in self._cards:
            on = c is card
            if bool(c.property("selected")) != on:
                c.setProperty("selected", on)
                c.style().unpolish(c)
                c.style().polish(c)
        if not self.workspace:
            return
        if card is None or self._selected is None:
            self.detail.show_empty()
            return
        kind, item_id, _section = self._selected
        rec, _group = self._records[(kind, item_id)]
        steps = (self._db.list_pipeline_steps(item_id)
                 if kind == cardmenu.PIPELINE and self._db is not None else [])
        self.detail.show_item(card, kind, rec, steps=steps,
                              name_color=readable_highlight(rec.get("color"),
                                                            self._palette["bg"]))

    # -- theming -----------------------------------------------------------
    def apply_palette(self, palette: dict) -> None:
        """Re-theme the whole window.

        One call, where the Tk shell tears the widget tree down and rebuilds
        it — the reason the stylesheet approach was worth the port.
        """
        self._palette = palette
        self.setStyleSheet(stylesheet(palette))
        icons.retint_all(self, palette)
        self._tint_tab_closes()
        roles = icons.role_colors(palette)
        for action, shape, danger in self._menu_icons:
            action.setIcon(icons.icon(shape, roles["danger" if danger else "menu"]))
        for pane in self._output_tabs.values():
            pane.set_palette(palette)
        self.detail.set_palette(palette)
        self.activity.set_palette(palette)
