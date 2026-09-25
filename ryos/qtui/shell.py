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

from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QPlainTextEdit, QPushButton,
                               QScrollArea,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import (__version__, cardmenu, configio, grouping, notifications,
               outputpanel, pipelinesteps, screens, scriptform, search,
               sections, selection, traypolicy)
from . import placement
from ..themes import REFERENCE, readable_highlight
from .cards import PipelineCard, ScriptCard
from .dragdrop import GroupTabBar
from .sections import GroupPage
from .menus import build_menu
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
                 on_run: Callable[[int], None] | None = None,
                 save_settings: Callable[[dict], None] | None = None,
                 notifier: Callable[[str, str], None] | None = None,
                 fetch_release: Callable[[], object] | None = None):
        super().__init__()
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
        self._bridge = None
        self.quick_run_bars: dict[str, QuickRunBar] = {}
        self._qr_index = None
        self._db = None
        self.card_lists: dict[str, GroupPage] = {}
        # (kind, id) -> (record, group), for the menus.
        self._records: dict[tuple, tuple] = {}
        self._collapse = sections.CollapseState()
        self.all_pages: dict[str, GroupPage] = {}

        # Everything a menu action may ask. Real dialogs by default; a test
        # replaces them, since each of these blocks until a person answers.
        self.ask_yes_no: Callable[[str, str], bool] = self._ask_yes_no
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
        self.add_script_button = QPushButton(sections.ADD_SCRIPT_LABEL)
        self.add_script_button.setObjectName("primary")
        self.add_script_button.clicked.connect(self.add_script)
        row.addWidget(self.add_script_button)
        self.add_pipeline_button = QPushButton(pipelinesteps.ADD_PIPELINE_LABEL)
        self.add_pipeline_button.clicked.connect(self.new_pipeline)
        row.addWidget(self.add_pipeline_button)
        col.addLayout(row)

        self._top_col = col
        col.addWidget(self._build_select_bar())

        self.group_tabs = QTabWidget()
        self.group_tabs.setObjectName("groupTabs")
        self.group_tabs.currentChanged.connect(
            lambda _i: self._update_select_bar())
        # Must be set before any tab is added.
        self.group_tab_bar = GroupTabBar()
        self.group_tabs.setTabBar(self.group_tab_bar)
        self.group_tab_bar.dropped_on_group.connect(self._on_drop_on_group)
        self.group_tab_bar.menu_requested.connect(self._show_group_menu)
        self.group_tab_bar.reordered.connect(self._on_tabs_reordered)
        self.new_group_button = QPushButton("+")
        self.new_group_button.setToolTip("New group")
        self.new_group_button.clicked.connect(self.new_group)
        self.group_tabs.setCornerWidget(self.new_group_button)
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
        options = bar.addMenu("&Options")
        self.select_action = QAction(selection.ENTER_LABEL, self)
        self.select_action.triggered.connect(
            lambda: self.set_select_mode(not self.select_mode))
        options.addAction(self.select_action)
        options.addSeparator()
        for label, slot in (("＋  New group…", self.new_group),
                            ("📤  Export all groups", self.export_all),
                            ("📥  Import config", self.import_config)):
            action = QAction(label, self)
            action.triggered.connect(slot)
            options.addAction(action)
        options.addSeparator()
        self.delete_all_action = QAction("🗑  Delete All", self)
        self.delete_all_action.triggered.connect(self.delete_all)
        options.addAction(self.delete_all_action)
        options.addSeparator()
        self.options_action = QAction("⚙  Advanced options…", self)
        self.options_action.triggered.connect(self.open_options)
        options.addAction(self.options_action)
        self.appearance_action = QAction("🎨  Appearance…", self)
        self.appearance_action.triggered.connect(self.open_appearance)
        options.addAction(self.appearance_action)
        options.addSeparator()
        self.update_action = QAction("🔔  Check for updates", self)
        self.update_action.triggered.connect(
            lambda: self.check_for_updates(manual=True))
        options.addAction(self.update_action)

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
        if base_dir and self._settings.get("quick_run_enabled", True):
            hcol.addWidget(self._build_quick_run(group_name, base_dir))
        hcol.addWidget(scroll, 1)
        index = self.group_tabs.addTab(
            holder, label if label is not None else group_name)
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
        for group, header, records in blocks:
            if header:
                label = QLabel(header)
                label.setObjectName("groupHeader")
                col.addWidget(label)
            page, made = self._build_page(group, records)
            self.all_pages[group] = page
            col.addWidget(page)
            self._cards.extend(made)
        if not blocks:
            self.all_empty = QLabel(sections.ALL_EMPTY)
            self.all_empty.setObjectName("cardPath")
            col.addWidget(self.all_empty)
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
        compact = bool(self._settings.get("compact_mode", False))
        size = self._settings.get("card_size", "medium")
        shade = readable_highlight(rec.get("color"), self._palette["card_bg"],
                                   self._palette["card_hover"])
        kind = rec["kind"]
        if kind == cardmenu.PIPELINE:
            card = PipelineCard(pipeline_id=rec["id"], name=rec["name"],
                                step_count=rec.get("steps", 0),
                                palette=self._palette, compact=compact, size=size,
                                is_favorite=bool(rec.get("favorite")),
                                label_color=shade, last_status=rec.get("status"))
        else:
            card = ScriptCard(script_id=rec["id"], name=rec["name"],
                              path=rec.get("path", ""), palette=self._palette,
                              compact=compact, size=size,
                              is_favorite=bool(rec.get("favorite")),
                              label_color=shade, last_status=rec.get("status"),
                              param_choices=scriptform.card_param_choices(
                                  rec.get("params", ""), rec.get("presets") or []))
        card.section = section
        if self._on_run is not None:
            card.run_requested.connect(self._on_run)
        elif "run_with" in rec:
            card.run_requested.connect(
                lambda _id, c=card, r=rec: self.run_script_card(c, r))
            card.run_with_param_requested.connect(
                lambda _id, c=card, r=rec: self.run_with_param(c, r))
        elif "run" in rec:
            card.run_requested.connect(lambda _id, go=rec["run"]: go())
        self._records[(kind, rec["id"])] = (rec, group)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, c=card, k=kind, i=rec["id"], s=section:
                self._show_card_menu(k, i, c.mapToGlobal(pos), s))
        card.favorite_toggled.connect(
            lambda item_id, fav, k=kind: self._set_favorite(k, item_id, fav))
        if kind == cardmenu.PIPELINE:
            card.edit_requested.connect(
                lambda item_id, n=rec["name"]: self._edit_pipeline(item_id, n))
        else:
            card.edit_requested.connect(self.edit_script)
        return card

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
        first_load = self.group_tabs.count() == 0
        current = self.current_group()
        self.set_select_mode(False)
        self._clear_groups()
        statuses = db.last_pipeline_status()
        scripts = db.list_all()
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
                records.append({
                    "id": sid, "name": sname, "path": path, "status": rec[7],
                    "favorite": bool(rec[10]), "color": rec[11],
                    "params": params or "", "temp_param": bool(rec[9]),
                    "presets": db.list_param_presets(sid),
                    "run_with": (lambda prm, s=sid, n=sname, pth=path,
                                 i=interp, g=name: self._run_script_record(
                                     s, n, pth, prm, i or "", g)),
                })
            for pid, pname, fav, color in db.list_pipelines(name):
                records.append({
                    "id": pid, "kind": "pipeline", "name": pname,
                    "favorite": bool(fav), "color": color,
                    "steps": len(db.list_pipeline_steps(pid)),
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
        if self._bridge is not None:
            self._bridge.run_script(sid, name, path, params, interp,
                                    active_group=group,
                                    on_refusal=self._show_refusal)

    def _run_pipeline_record(self, pid, name, group) -> None:
        if self._bridge is not None:
            self._bridge.run_pipeline(pid, name, active_group=group,
                                      candidate_groups=list(self.card_lists),
                                      on_refusal=self._show_refusal)

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

    def open_options(self) -> None:
        from .dialogs import OptionsDialog
        self.run_dialog(OptionsDialog(dict(self._settings), self,
                                      on_save=self.apply_settings))

    def apply_settings(self, new: dict) -> None:
        """Take saved options, as Tk's _apply does: store, log level, window."""
        from ..logger import setup_logging
        self._settings.update(new)
        self._save_settings(self._settings)
        setup_logging(self._settings.get("logging_enabled", True),
                      self._settings.get("log_level", "INFO"))
        self.apply_topmost()
        self.resize(int(self._settings.get("window_width", self.width())),
                    int(self._settings.get("window_height", self.height())))
        self.snap_to_corner()
        # Compact mode and card size are read when cards are built.
        self._defer_reload()

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
        dismiss = QPushButton("✕")
        dismiss.clicked.connect(self.dismiss_update_banner)
        row.addWidget(dismiss)
        self._top_col.insertWidget(0, banner)
        self.update_banner = banner

    def dismiss_update_banner(self) -> None:
        if self.update_banner is not None:
            self.update_banner.deleteLater()
            self.update_banner = None

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
        self._hidden_to_tray = True
        self.hide()

    def restore_from_tray(self, follow_cursor: bool = False) -> None:
        if follow_cursor and self._settings.get("open_on_cursor_monitor"):
            target = self.cursor_area()
            if target is not None:
                saved = self._last_normal_geometry or self.geometry_string()
                src = self.area_at(*screens.geometry_origin(saved)) or target
                self.set_geometry_string(
                    screens.relocate_geometry(saved, src, target))
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._hidden_to_tray = False

    def show_job_from_tray(self, job_id: int) -> None:
        """Restore the window and bring a job's output tab forward."""
        self.restore_from_tray()
        job = self._bridge.registry.get(job_id) if self._bridge else None
        if job is not None and job.tab_key in self._output_tabs:
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
        if (event.type() == QEvent.Type.WindowStateChange and self.isMinimized()
                and traypolicy.on_minimize(self.tray_available(),
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
                                title=scriptform.RUN_WITH_PARAMS_TITLE)
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
        replace = self.ask_yes_no(*configio.IMPORT_MODE)
        try:
            added, skipped = self._db.import_from_file(path, replace=replace)
        except Exception as exc:                # noqa: BLE001 - shown to the user
            self.warn("Import Failed", str(exc))
            return
        self._defer_reload()
        self.statusBar().showMessage(configio.import_status(added, skipped))

    def delete_all(self) -> None:
        if self._db is None:
            return
        prompt = configio.delete_all_prompt(len(self._db.list_all()))
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
        self.run_selected_button = QPushButton("▶ Run Selected")
        self.run_selected_button.setObjectName("run")
        self.run_selected_button.clicked.connect(self.run_selected)
        self.delete_selected_button = QPushButton("🗑 Delete Selected")
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
        if self._db is None or not self.ask_yes_no(*selection.delete_prompt(len(ids))):
            return
        self._db.delete_many(ids)
        self._defer_reload()

    # -- right-click menus ------------------------------------------------------
    def card_menu_items(self, kind: str, item_id: int,
                        section: str = sections.SCRIPTS) -> list:
        """The menu for one card, by the shared definition."""
        rec, group = self._records[(kind, item_id)]
        if kind == cardmenu.PIPELINE:
            return cardmenu.pipeline_menu(favorite=bool(rec.get("favorite")),
                                          color=rec.get("color"))
        up, down = self._script_neighbours(item_id, group, section)
        return cardmenu.script_menu(favorite=bool(rec.get("favorite")),
                                    color=rec.get("color"),
                                    can_move_up=up is not None,
                                    can_move_down=down is not None)

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
            if not self.ask_yes_no(*cardmenu.delete_prompt(kind, name)):
                return
            cardmenu.delete(db, kind, item_id)
        elif key in (cardmenu.SCHEDULE, cardmenu.HISTORY):
            from .smalldialogs import RunHistoryDialog, ScheduleDialog
            ids = ({"pipeline_id": item_id} if kind == cardmenu.PIPELINE
                   else {"script_id": item_id})
            if key == cardmenu.SCHEDULE:
                self.run_dialog(ScheduleDialog(self, db=db, title=name,
                                               on_save=self._defer_reload, **ids))
            else:
                self.run_dialog(RunHistoryDialog(self, db=db, title=name, **ids))
            return
        elif key == cardmenu.EDIT and kind == cardmenu.PIPELINE:
            self._edit_pipeline(item_id, name)
            return
        else:
            return
        self._defer_reload()

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

    # -- the group-tab menu --------------------------------------------------------
    def _show_group_menu(self, group: str, pos: QPoint) -> None:
        if not group:
            return                  # "Ungrouped" is not a group to rename
        menu = build_menu(self, cardmenu.group_menu(),
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
        for sig in (bridge.started, bridge.finished, bridge.renamed):
            sig.connect(lambda _job: self._sync_tray())
        bridge.notify.connect(self._on_job_notify)

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
