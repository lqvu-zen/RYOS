"""The Qt main window.

Wires together everything ported in phases 2.1–2.5: the generated stylesheet,
the cards, the dialogs and the pipeline editor. Output routing and the
buffer-trim rule come from `ryos.outputpanel`, search from `ryos.search`, and
grouping from `ryos.grouping` — all shared with the Tk shell.

This is a shell in both senses: it is the window, and it is not yet wired to
the job machinery. `RYOSApp` still owns running scripts; flipping `__main__`
over is the last step of the migration and has not happened.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QPlainTextEdit, QScrollArea, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import outputpanel, search
from ..themes import REFERENCE
from .cards import PipelineCard, ScriptCard
from .stylesheet import stylesheet

#: Matches the Tk placeholder, so the two shells prompt identically.
SEARCH_PLACEHOLDER = "Search scripts and pipelines…"


class OutputPane(QWidget):
    """One output tab's text, with the same buffer cap as the Tk panel."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        self.text = QPlainTextEdit()
        self.text.setObjectName("output")
        self.text.setReadOnly(True)
        # Qt maintains this itself, which is the Tk trim done for us; the
        # shared rule still decides the number so the two agree.
        self.text.setMaximumBlockCount(0)
        col.addWidget(self.text)

    def append(self, text: str, max_lines: int, *, scroll: bool = True) -> None:
        self.text.appendPlainText(text.rstrip("\n"))
        drop = outputpanel.overflow_lines(
            self.text.blockCount(), max_lines)
        if drop:
            cursor = self.text.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            for _ in range(drop):
                cursor.movePosition(cursor.MoveOperation.Down,
                                    cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        if scroll:
            bar = self.text.verticalScrollBar()
            bar.setValue(bar.maximum())


class MainWindow(QMainWindow):
    """The window: group tabs, a card list, a search box and an output panel."""

    def __init__(self, palette: dict | None = None, *,
                 settings: dict | None = None,
                 on_run: Callable[[int], None] | None = None):
        super().__init__()
        self._palette = palette or REFERENCE["dark"]
        self._settings = dict(settings or {})
        self._on_run = on_run
        self._cards: list = []
        self._output_tabs: dict[str, OutputPane] = {}

        self.setWindowTitle("RYOS")
        self.resize(self._settings.get("window_width", 540),
                    self._settings.get("window_height", 640))
        self.setStyleSheet(stylesheet(self._palette))

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_top())
        splitter.addWidget(self._build_output())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Ready")
        self._build_menu()

    # -- construction ------------------------------------------------------
    def _build_top(self) -> QWidget:
        top = QWidget()
        col = QVBoxLayout(top)
        col.setContentsMargins(8, 8, 8, 4)

        row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(SEARCH_PLACEHOLDER)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_search)
        row.addWidget(self.search_box, 1)
        self.search_hint = QLabel("")
        self.search_hint.setObjectName("cardPath")
        row.addWidget(self.search_hint)
        col.addLayout(row)

        self.group_tabs = QTabWidget()
        self.group_tabs.setObjectName("groupTabs")
        col.addWidget(self.group_tabs, 1)
        return top

    def _build_output(self) -> QWidget:
        self.output_tabs = QTabWidget()
        self.output_tabs.setObjectName("outputTabs")
        self.output_tabs.setTabsClosable(True)
        self.output_tabs.tabCloseRequested.connect(self._close_output_tab)
        self.add_output_tab(outputpanel.ALL, "All")
        return self.output_tabs

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        quit_action = QAction("E&xit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # -- cards -------------------------------------------------------------
    def set_cards(self, group_name: str, records) -> None:
        """Replace one group tab's cards."""
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        compact = bool(self._settings.get("compact_mode", False))
        size = self._settings.get("card_size", "medium")
        made = []
        for rec in records:
            if rec.get("kind") == "pipeline":
                card = PipelineCard(pipeline_id=rec["id"], name=rec["name"],
                                    step_count=rec.get("steps", 0),
                                    palette=self._palette, compact=compact,
                                    size=size,
                                    last_status=rec.get("status"))
            else:
                card = ScriptCard(script_id=rec["id"], name=rec["name"],
                                  path=rec.get("path", ""),
                                  palette=self._palette, compact=compact,
                                  size=size, last_status=rec.get("status"))
            if self._on_run is not None:
                card.run_requested.connect(self._on_run)
            col.addWidget(card)
            made.append(card)
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.group_tabs.addTab(scroll, group_name)
        self._cards.extend(made)

    # -- search ------------------------------------------------------------
    def _apply_search(self, raw: str) -> None:
        """Hide cards that do not match, using the shared matcher."""
        query = search.normalize_query(raw, False)
        shown = 0
        for card in self._cards:
            name = getattr(card, "_name", "")
            visible = not query or search.matches(name, query)
            card.setVisible(visible)
            shown += bool(visible)
        if query:
            self.search_hint.setText(f"{shown} of {len(self._cards)}")
        else:
            self.search_hint.setText("")

    # -- output ------------------------------------------------------------
    def add_output_tab(self, key: str, label: str) -> OutputPane:
        pane = self._output_tabs.get(key)
        if pane is None:
            pane = OutputPane()
            self._output_tabs[key] = pane
            self.output_tabs.addTab(pane, label)
        return pane

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

    def append_output(self, text: str, tab_key: str | None = None) -> None:
        """Write a line wherever the shared routing rule says it belongs."""
        max_lines = self._settings.get("max_output_lines", 2000)
        scroll = self._settings.get("auto_scroll_output", True)
        for key in outputpanel.target_tabs(tab_key, self.active_output_key(),
                                           self._output_tabs):
            self._output_tabs[key].append(text, max_lines, scroll=scroll)

    # -- theming -----------------------------------------------------------
    def apply_palette(self, palette: dict) -> None:
        """Re-theme the whole window.

        One call, where the Tk shell tears the widget tree down and rebuilds
        it — the reason the stylesheet approach was worth the port.
        """
        self._palette = palette
        self.setStyleSheet(stylesheet(palette))
