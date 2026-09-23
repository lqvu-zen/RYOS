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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QPlainTextEdit, QPushButton, QScrollArea,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import outputpanel, search
from ..themes import REFERENCE
from .cards import PipelineCard, ScriptCard
from .dragdrop import CardList, GroupTabBar
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
        self._db = None
        self.card_lists: dict[str, CardList] = {}

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
        # Must be set before any tab is added.
        self.group_tab_bar = GroupTabBar()
        self.group_tabs.setTabBar(self.group_tab_bar)
        self.group_tab_bar.dropped_on_group.connect(self._on_drop_on_group)
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
    def set_cards(self, group_name: str, records, base_dir: str = "", *,
                  label: str | None = None) -> None:
        """Add one group tab with its cards.

        ``group_name`` is the database key ("" for ungrouped); ``label`` is
        what the tab shows. The key is stored on the tab, so a card dropped
        on "Ungrouped" moves to "" rather than to a group named "Ungrouped".
        """
        page = CardList(group_name)
        page.dropped.connect(self._on_drop_in_list)
        self.card_lists[group_name] = page
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
            elif "run" in rec:
                card.run_requested.connect(lambda _id, go=rec["run"]: go())
            kind = "pipeline" if rec.get("kind") == "pipeline" else "script"
            page.add_card(card, kind, rec["id"])
            made.append(card)

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
        index = self.group_tabs.addTab(
            holder, label if label is not None else group_name)
        self.group_tab_bar.setTabData(index, group_name)
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

    # -- loading from the database ------------------------------------------
    UNGROUPED_LABEL = "Ungrouped"

    def load_from_db(self, db) -> None:
        """Build every group tab from the database, replacing what is shown.

        Keeps whichever group was in front, so a reload after a drop does not
        throw the user back to the first tab.
        """
        self._db = db
        current = self.current_group()
        self._clear_groups()
        statuses = db.last_pipeline_status()
        scripts = db.list_all()
        groups = [(name, base) for name, base in db.list_groups_with_meta()]
        if any((rec[8] or "") == "" for rec in scripts) or db.list_pipelines(""):
            groups.append(("", ""))
        for name, base in groups:
            records = []
            for rec in scripts:
                if (rec[8] or "") != name:
                    continue
                sid, sname, path, params, interp = rec[0], rec[1], rec[2], rec[3], rec[4]
                records.append({
                    "id": sid, "name": sname, "path": path, "status": rec[7],
                    "run": (lambda s=sid, n=sname, pth=path, prm=params,
                            i=interp, g=name: self._run_script_record(
                                s, n, pth, prm or "", i or "", g)),
                })
            for pid, pname, _fav, _color in db.list_pipelines(name):
                records.append({
                    "id": pid, "kind": "pipeline", "name": pname,
                    "steps": len(db.list_pipeline_steps(pid)),
                    "status": statuses.get(pid),
                    "run": (lambda p=pid, n=pname, g=name:
                            self._run_pipeline_record(p, n, g)),
                })
            self.set_cards(name, records, base,
                           label=name or self.UNGROUPED_LABEL)
        self.show_group(current)

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
        if self._bridge is not None:
            self._bridge.run_script(sid, name, path, params, interp,
                                    active_group=group)

    def _run_pipeline_record(self, pid, name, group) -> None:
        if self._bridge is not None:
            self._bridge.run_pipeline(pid, name, active_group=group,
                                      candidate_groups=list(self.card_lists))

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
