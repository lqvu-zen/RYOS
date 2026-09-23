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

`RYOSApp` still owns the shipping app and `__main__` still starts it; flipping
over is the last step of the migration and has not happened. What the shell
still lacks is listed in docs/plans/qt-migration.md under "Parity".
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QPlainTextEdit, QPushButton, QScrollArea,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import outputpanel, search
from ..themes import REFERENCE
from .cards import PipelineCard, ScriptCard
from .quickrun import MainThreadInvoker, QuickRunBar
from .running import RunningSection
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
        self._bridge = None
        self.quick_run_bars: dict[str, QuickRunBar] = {}
        self._qr_index = None

        self.setWindowTitle("RYOS")
        self.resize(self._settings.get("window_width", 540),
                    self._settings.get("window_height", 640))
        self.setStyleSheet(stylesheet(self._palette))

        self.running = RunningSection(self._palette, on_stop=self._stop_job)

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
        col.addWidget(self.running)
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
    def set_cards(self, group_name: str, records, base_dir: str = "") -> None:
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

        holder = QWidget()
        hcol = QVBoxLayout(holder)
        hcol.setContentsMargins(0, 0, 0, 0)
        hcol.setSpacing(2)
        if base_dir and self._settings.get("quick_run_enabled", True):
            hcol.addWidget(self._build_quick_run(group_name, base_dir))
        hcol.addWidget(scroll, 1)
        self.group_tabs.addTab(holder, group_name)
        self._cards.extend(made)

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

    def _build_quick_run(self, group_name: str, base_dir: str) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        toggle = QPushButton("⚡ Quick Run")
        toggle.setObjectName("dark")
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
        col.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        col.addWidget(bar)
        self.quick_run_bars[group_name] = bar
        return box

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

    # -- jobs --------------------------------------------------------------
    def attach_jobs(self, bridge) -> None:
        """Wire a JobBridge in: output, status, and the running list.

        Kept separate from __init__ so the window can be built and checked
        without the job machinery, which is how tests/qt_smoke.py exercises
        the two independently.
        """
        self._bridge = bridge
        bridge.output.connect(
            lambda tab_key, text, _tag=None: self.append_output(text, tab_key))
        bridge.status.connect(self.statusBar().showMessage)
        bridge.started.connect(self._on_job_started)
        bridge.finished.connect(self.running.remove)

    def _on_job_started(self, job) -> None:
        self.add_output_tab(job.tab_key, job.name)
        self.running.add(job)

    def _stop_job(self, job) -> None:
        """Stop one job. The row stays until the job actually finishes."""
        job.stopped = True
        if getattr(job, "pipeline_queue", None):
            job.pipeline_queue.clear()
        for proc in job.active_processes():
            try:
                proc.terminate()
            except OSError:
                pass   # already gone
        self.statusBar().showMessage("Stopped.")

    # -- theming -----------------------------------------------------------
    def apply_palette(self, palette: dict) -> None:
        """Re-theme the whole window.

        One call, where the Tk shell tears the widget tree down and rebuilds
        it — the reason the stylesheet approach was worth the port.
        """
        self._palette = palette
        self.setStyleSheet(stylesheet(palette))
