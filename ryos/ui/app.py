"""Main RYOS window: header, tabs, card list, output panel, and run engine."""
import ctypes
import hashlib
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False
    DND_FILES = None

from .. import __version__
from ..db import ScriptDB
from ..interpreter import build_command, detect_interpreter, resolve_interpreter
from ..logger import get_logger, setup_logging
from ..notifications import _fetch_latest_release, _parse_version, _show_notification
from ..runner import run_subprocess
from ..settings import QR_INDEX_DIR, _BASE, _NUITKA, _load_settings, _save_settings
from ..quickrun import (
    _SKIP_DIRS, _is_inside, build_entry, display_relpath, parse_input, rank_suggestions, resolve,
)
from ..jobs import Job as _Job, JobRegistry, format_elapsed
from .cards import PipelineCard, ScriptCard
from .dialogs import AdvancedOptionsDialog, AppearanceDialog, GroupBaseDirDialog, NewGroupDialog, ScriptDialog
from .pipeline import PipelineEditorDialog
from .theme import C, _apply_snap_corner, _configure_ttk_styles, _flat_button, apply_theme
from .widgets import Tooltip

_log = get_logger("app")

_BaseWindow = TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk

MAX_PARALLEL_JOBS = 10
_QUICK_RUN_INDEX_TTL = 30.0  # seconds before the file-index cache is considered stale


def _qr_index_path(base_dir: str) -> Path:
    key = os.path.normcase(os.path.normpath(base_dir))
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return QR_INDEX_DIR / f"qr_index_{h}.json"


def _quick_run_load_disk_index(base_dir: str, ttl: float) -> "tuple[float, list] | None":
    import json as _json
    import time
    try:
        raw = _qr_index_path(base_dir).read_text(encoding="utf-8")
        data = _json.loads(raw)
        # Hash-collision guard: verify the stored base_dir matches exactly.
        if data["base_dir"] != base_dir:
            return None
        # Reject if the on-disk index is older than the configured TTL.
        if time.time() - data["ts"] >= ttl:
            return None
        paths = [tuple(e) for e in data["paths"]]
        return (data["ts"], paths)
    except (OSError, ValueError, KeyError, TypeError) as e:
        _log.debug("Quick Run index cache unreadable for %s: %s", base_dir, e)
        return None


def _quick_run_save_disk_index(base_dir: str, wall_ts: float, paths: list) -> None:
    import json as _json
    try:
        dest = _qr_index_path(base_dir)
        tmp = Path(str(dest) + ".tmp")
        payload = {"base_dir": base_dir, "ts": wall_ts, "paths": paths}
        tmp.write_text(_json.dumps(payload), encoding="utf-8")
        # Atomic swap so a concurrent read never sees a partial file.
        os.replace(tmp, dest)
    except OSError as e:
        _log.debug("Could not write Quick Run index cache for %s: %s", base_dir, e)


class RYOSApp(_BaseWindow):
    def __init__(self):
        super().__init__()
        _configure_ttk_styles()
        self.report_callback_exception = self._log_tk_exception
        if sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RYOS.RunYourOwnScripts")

        self.title(f"RYOS v{__version__} — Run Your Own Scripts")
        self.minsize(480, 320)
        self.configure(bg=C["bg"])
        if hasattr(sys, "_MEIPASS"):
            _icon_base = Path(sys._MEIPASS)          # PyInstaller: temp extraction dir
        elif _NUITKA:
            _icon_base = Path(__file__).resolve().parents[2]  # Nuitka onefile: temp extraction dir
        else:
            _icon_base = _BASE                        # cx_Freeze or dev: next to exe / project root
        _icon = _icon_base / "icon.ico"
        if _icon.exists():
            self.iconbitmap(str(_icon))
        self.db = ScriptDB()
        self._settings: dict = _load_settings()
        # Apply the saved theme before building any widgets so that C is
        # already populated with the correct palette when _build_ui() runs.
        apply_theme(self._settings.get("theme", "light"), self._settings.get("accent_color"))
        from ryos.ui import cards as _cards_mod
        _cards_mod.set_compact_mode(self._settings.get("compact_mode", False))
        _cards_mod.set_card_size(self._settings.get("card_size", "medium"))
        self.configure(bg=C["bg"])

        self.update_idletasks()
        w = self._settings.get("window_width",  540)
        h = self._settings.get("window_height", 640)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.output_queue: queue.Queue = queue.Queue()
        self._jobreg = JobRegistry()
        self._cards: list[ScriptCard] = []
        self._pipeline_cards: list[PipelineCard] = []
        self._select_mode = False
        self._drag_card: ScriptCard | None = None
        self._drag_start_x = self._drag_start_y = 0
        self._drag_ghost: tk.Toplevel | None = None
        self._drag_indicator: tk.Frame | None = None
        self._drag_insert_before: int | None = None
        self._drag_target_group: str | None = None
        self._drag_tab_highlight: tuple | None = None
        self._section_collapsed: dict[str, dict[str, bool]] = {}
        self._output_tabs: dict = {}
        self._active_tab_key: str | None = None
        self._quick_run_buttons: dict[str, tk.Button] = {}
        self._quick_run_bars: dict[str, dict] = {}
        self._quick_run_open_group: str | None = None
        self._quick_run_index_cache: dict[str, tuple[float, list]] = {}
        self._quick_run_disk_loaded: set[str] = set()

        groups = self.db.list_groups()
        if self._settings["remember_last_group"] and self._settings.get("last_group") in groups:
            self._active_group: str | None = self._settings["last_group"]
        else:
            self._active_group = groups[0] if groups else None

        corner = self._settings.get("snap_corner") or ""
        if not corner or corner == "none":
            if self._settings["remember_window_geometry"] and self._settings.get("window_geometry"):
                self.geometry(self._settings["window_geometry"])

        self._running_slots: dict = {}
        self._elapsed_timer_id: str | None = None
        self._build_ui()
        self._refresh()
        self.after(80, self._drain_output_queue)
        self.after(0,  self._setup_file_drop)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if self._settings.get("auto_check_update", True):
            threading.Thread(target=self._check_for_update, daemon=True).start()
        self.attributes("-topmost", self._settings["always_on_top"])
        if corner and corner != "none":
            self.after(0, lambda c=corner: _apply_snap_corner(self, c))
        if self._settings["start_minimized"]:
            self.after(0, self.iconify)

    def _log_tk_exception(self, exc, val, tb):
        _log.error("Unhandled Tk callback exception", exc_info=(exc, val, tb))
        tk.Tk.report_callback_exception(self, exc, val, tb)

    def _setup_file_drop(self):
        if not _DND_AVAILABLE:
            return
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop_event)

    def _on_drop_event(self, event):
        paths = self.tk.splitlist(event.data)
        self._on_files_dropped(list(paths))

    def _on_files_dropped(self, paths: list[str]):
        groups = self.db.list_groups()
        if not groups:
            name = simpledialog.askstring(
                "Create a Group First",
                "You have no groups yet.\nEnter a group name to continue:",
                parent=self,
            )
            if not (name and name.strip()):
                return
            self.db.create_group(name.strip())
            self._active_group = name.strip()
            self._refresh_tabs()
            groups = self.db.list_groups()

        group = self._active_group or ""
        base_dir = self.db.get_group_base_dir(group)
        added = 0
        skipped = []
        for path in paths:
            p = Path(path)
            if p.is_file():
                if base_dir and not _is_inside(str(p), base_dir):
                    skipped.append(p)
                    continue
                self.db.add(p.stem, str(p), "", detect_interpreter(str(p)), group)
                added += 1
        if skipped:
            messagebox.showwarning(
                "Files outside base directory",
                f"{len(skipped)} file(s) were skipped because their paths are outside the base directory for group '{group}':\n"
                + "\n".join([str(p) for p in skipped[:10]]),
                parent=self,
            )
        if added:
            self._refresh_cards()

    def _build_ui(self):
        self._build_header()
        self._build_select_bar()
        self._build_status_bar()
        self._build_cards_pane()
        self._build_output_panel()

    def _build_header(self):
        """Top header: brand, create buttons, and the options menu."""
        header = tk.Frame(self, bg=C["header_bg"], pady=14, padx=18)
        header.pack(fill="x")
        wm = tk.Frame(header, bg=C["header_bg"])
        wm.pack(side="left")
        header_btn_size = 6
        tk.Label(wm, text="⚡", bg=C["header_bg"], fg=C["bolt"],
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(wm, text=" RYOS", bg=C["header_bg"], fg=C["fg_on_dark"],
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        add_btn = _flat_button(header, "+ Script", C["btn_create_bg"], C["btn_create_hover"],
                               self._add_script, width=header_btn_size)
        add_btn.config(bg=C["btn_create_bg"])
        add_btn.pack(side="right")
        Tooltip(add_btn, "Create a script")
        add_group_btn = _flat_button(header, "+ Group", C["btn_create_bg"], C["btn_create_hover"],
                                     self._create_group, width=header_btn_size)
        add_group_btn.pack(side="right", padx=(0, 6))
        Tooltip(add_group_btn, "Create a group")
        self._pipeline_btn = _flat_button(header, "+ Pipeline", C["btn_create_bg"], C["btn_create_hover"],
                                           self._add_pipeline, width=header_btn_size)
        self._pipeline_btn.pack(side="right", padx=(0, 6))
        Tooltip(self._pipeline_btn, "Create a pipeline")

        self._options_menu = tk.Menu(self, tearoff=0, bg=C["menu_bg"], fg=C["fg_on_dark"],
                                     activebackground=C["accent"], activeforeground=C["fg_on_dark"],
                                     borderwidth=0, relief="flat")
        self._options_menu.add_command(label="☑  Select scripts",     command=self._toggle_select_mode)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="📤  Export all groups",  command=self._export_config)
        self._options_menu.add_command(label="📥  Import config",      command=self._import_config)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="⚙  Advanced options…",  command=self._open_advanced_options)
        self._options_menu.add_command(label="🎨  Appearance…",        command=self._open_appearance)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="🔔  Check for updates",  command=self._manual_update_check)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="📁  Open log folder",    command=self._open_log_folder)
        self._options_menu.add_command(label="📄  View logs",          command=self._view_logs)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="🗑  Delete All",         command=self._delete_all)

        options_btn = _flat_button(header, "⚙", C["btn_dark_bg"], C["btn_dark_hover"],
                                   self._show_options_menu, width=4)
        options_btn.pack(side="right", padx=8)
        self._options_btn = options_btn

        self._select_btn = None

    def _build_select_bar(self):
        """The multi-select delete bar (packed on demand by select mode)."""
        self._select_bar = tk.Frame(self, bg=C["warn_bg"],
                                    highlightbackground=C["warn_border"], highlightthickness=1)
        self._select_bar_var = tk.StringVar(value="Tick the checkboxes next to scripts you want to delete.")
        tk.Label(self._select_bar, textvariable=self._select_bar_var,
                 bg=C["warn_bg"], fg=C["warn_fg"], font=("Segoe UI", 9),
                 padx=14, pady=5, anchor="w").pack(side="left", fill="x", expand=True)
        self._del_selected_btn = _flat_button(self._select_bar, "🗑 Delete Selected",
                                              "#5a2d2d", "#7a3d3d", self._delete_selected, width=15)
        self._del_selected_btn.pack(side="right", padx=10, pady=4)
        self._sel_all_btn = tk.Button(
            self._select_bar, text="Select All",
            bg=C["warn_bg"], fg=C["warn_fg"],
            activebackground=C["warn_border"], activeforeground=C["warn_fg"],
            relief="flat", bd=0, padx=10, pady=5,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
            command=self._toggle_select_all,
        )
        self._sel_all_btn.bind("<Enter>", lambda e: self._sel_all_btn.config(bg=C["warn_border"]))
        self._sel_all_btn.bind("<Leave>", lambda e: self._sel_all_btn.config(bg=C["warn_bg"]))
        self._sel_all_btn.pack(side="right", padx=4, pady=4)

    def _build_status_bar(self):
        """The bottom status bar."""
        self.status_var = tk.StringVar(value="Ready.")
        self._status_bar = tk.Label(self, textvariable=self.status_var, anchor="w",
                                    bg=C["status_bg"], fg=C["btn_dark_hover"], font=("Segoe UI", 8),
                                    padx=10, pady=4)
        self._status_bar.pack(fill="x", side="bottom")

    def _build_cards_pane(self):
        """Scrollable cards area in the top pane of the vertical splitter."""
        self._paned = ttk.PanedWindow(self, orient="vertical")
        self._paned.pack(fill="both", expand=True)

        cards_pane = tk.Frame(self._paned, bg=C["bg"])
        self._paned.add(cards_pane, weight=3)

        self._tab_bar = tk.Frame(cards_pane, bg=C["bg"])
        self._tab_bar.pack(fill="x", padx=12, pady=(8, 0))
        tk.Frame(cards_pane, bg=C["border"], height=1).pack(fill="x", padx=12)

        container = tk.Frame(cards_pane, bg=C["bg"])
        container.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self._cards_container = container

        canvas = tk.Canvas(container, highlightthickness=0, bg=C["bg"])
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(canvas, bg=C["bg"])
        self._canvas_window = canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")

        self.cards_frame.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            self._canvas_window, width=e.width))
        def _on_wheel(e):
            content_h = self.cards_frame.winfo_reqheight()
            viewport_h = canvas.winfo_height()
            if content_h > viewport_h:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._canvas = canvas

    def _build_output_panel(self):
        """The collapsible output panel in the bottom pane."""
        self._out_expanded = False
        self.out_panel = tk.Frame(self._paned, bg=C["out_bg"])

        out_header = tk.Frame(self.out_panel, bg=C["out_header"], pady=4, padx=10)
        out_header.pack(fill="x")
        tk.Label(out_header, text="Output", bg=C["out_header"], fg=C["fg_on_dark_2"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
        self._toggle_btn = tk.Button(out_header, text="▲  Show Output", bg=C["out_header"], fg=C["fg_on_dark_2"],
                                     activebackground="#3d3d3d", activeforeground=C["fg_on_dark"],
                                     relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                                     command=self._toggle_output)
        self._toggle_btn.pack(side="right")
        tk.Button(out_header, text="🗑 Clear", bg=C["out_header"], fg=C["fg_on_dark_2"],
                  activebackground="#3d3d3d", activeforeground=C["fg_on_dark"],
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._clear_log).pack(side="right", padx=4)
        tk.Button(out_header, text="✕ Close All", bg=C["out_header"], fg=C["fg_on_dark_2"],
                  activebackground="#3d3d3d", activeforeground=C["fg_on_dark"],
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._close_all_tabs).pack(side="right", padx=4)

        self._out_tab_bar = tk.Frame(self.out_panel, bg=C["out_tabbar"])
        self._out_tab_body = tk.Frame(self.out_panel, bg=C["out_bg"])
        self._init_all_tab()

        self._paned.add(self.out_panel, weight=0)

    def _new_job(self, kind: str, script_id, pipeline_id, name: str, group: str,
                 pipeline_name: str = "", pipeline_queue=None, pipeline_total: int = 0) -> "_Job":
        """Allocate a new job, register it, create its output tab, return it."""
        job_id = self._jobreg.new_id()
        tab_key = f"job:{job_id}"
        tab_name = pipeline_name if pipeline_name else name
        job = _Job(job_id, kind, script_id, pipeline_id, name, tab_key, group,
                   pipeline_name=pipeline_name,
                   pipeline_queue=pipeline_queue if pipeline_queue is not None else [],
                   pipeline_total=pipeline_total)
        self._jobreg.add(job)
        self._get_or_create_tab(tab_key, tab_name)
        if self._elapsed_timer_id is None:
            self._elapsed_timer_id = self.after(1000, self._tick_elapsed_timers)
        return job

    def _tick_elapsed_timers(self):
        if not self._jobreg:
            self._elapsed_timer_id = None
            return
        now = datetime.now()
        for job in self._jobreg.all():
            if job.time_var is not None:
                job.time_var.set(format_elapsed(job.start_time, now))
        self._elapsed_timer_id = self.after(1000, self._tick_elapsed_timers)

    def _finish_job(self, job: "_Job"):
        """Remove job from registry, tear down its running row, update card states."""
        self._jobreg.remove(job.job_id)
        if job.running_row is not None:
            try:
                if job.running_row.winfo_exists():
                    job.running_row.destroy()
            except tk.TclError:
                pass
        # If no more jobs in this group, show placeholder
        group_jobs = self._running_jobs_in_group(job.group)
        content = self._running_slots.get(job.group)
        if not group_jobs and content is not None:
            try:
                if content.winfo_exists() and not content.winfo_children():
                    tk.Label(content, text="No script is currently running.",
                             bg=C["bg"], fg=C["path_fg"],
                             font=("Segoe UI", 9), padx=6).pack(anchor="w", pady=(2, 4))
            except tk.TclError:
                pass

    def _add_running_row(self, content: tk.Frame, job: "_Job"):
        """Create a running-job row inside the Running section and store refs on job."""
        # Remove placeholder label if present
        for w in content.winfo_children():
            if isinstance(w, tk.Label):
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        from ryos.ui import cards as _cards_mod
        _row_pady, _row_ipady, _stop_pady, _name_pady = _cards_mod.row_metrics()
        row = tk.Frame(content, bg=C["card_bg"],
                       highlightbackground=C["border"], highlightthickness=1)
        row.pack(fill="x", pady=_row_pady, ipady=_row_ipady)
        _strip_color = C["pipe_accent"] if job.kind == "pipeline" else C["running"]
        tk.Frame(row, bg=_strip_color, width=5).pack(side="left", fill="y")
        stop_btn = tk.Button(
            row, text="⏹ Stop",
            bg=C["btn_stop_active"], fg=C["fg_on_dark"],
            activebackground=C["btn_stop_active_hover"], activeforeground=C["fg_on_dark"],
            relief="flat", bd=0, padx=10, pady=_stop_pady,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
            command=lambda j=job: self._stop_job(j),
        )
        stop_btn.pack(side="right", padx=6, pady=max(0, _stop_pady - 1))
        secs = int((datetime.now() - job.start_time).total_seconds())
        elapsed = f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"
        time_var = tk.StringVar(value=f"{job.start_time.strftime('%H:%M:%S')}  ·  {elapsed}")
        tk.Label(row, textvariable=time_var,
                 bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8), padx=6).pack(side="right")
        name_var = tk.StringVar(value=job.name)
        tk.Label(row, textvariable=name_var,
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9), anchor="w",
                 width=1, padx=8, pady=_name_pady).pack(side="left", fill="x", expand=True)
        job.running_row = row
        job.name_var = name_var
        job.time_var = time_var

    def _stop_job(self, job: "_Job"):
        """Stop one specific job."""
        job.stopped = True
        job.pipeline_queue.clear()
        if job.current_process is not None and job.current_process.poll() is None:
            try:
                job.current_process.terminate()
            except OSError:
                pass  # process may have already exited
            self._append_output("\n[STOPPED by user]\n", tag="stderr", tab_key=job.tab_key)
        self.status_var.set("Stopped.")
        self._finish_job(job)

    def _running_jobs_in_group(self, group: str) -> list:
        return self._jobreg.in_group(group)

    def _make_group_header(self, name: str):
        hdr = tk.Frame(self.cards_frame, bg=C["bg"])
        hdr.pack(fill="x", pady=(16, 2))
        tk.Label(hdr, text=name.upper(), bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Frame(hdr, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=4)

    def _make_section_header(self, parent, group: str, section: str, label: str) -> tk.Frame:
        collapsed = self._section_collapsed.get(group, {}).get(section, False)

        section_frame = tk.Frame(parent, bg=C["bg"])
        section_frame.pack(fill="x")

        from ryos.ui import cards as _cards_mod
        hdr = tk.Frame(section_frame, bg=C["bg"], cursor="hand2")
        hdr.pack(fill="x", padx=2, pady=(4 if _cards_mod._COMPACT else 10, 2))

        arrow_var = tk.StringVar(value="▶" if collapsed else "▼")
        arrow_lbl = tk.Label(hdr, textvariable=arrow_var, bg=C["bg"], fg=C["path_fg"],
                             font=("Segoe UI", 8), cursor="hand2", width=2)
        arrow_lbl.pack(side="left")
        tk.Label(hdr, text=label.upper(), bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8, "bold"), cursor="hand2").pack(side="left")
        tk.Frame(hdr, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(6, 0), pady=4)

        content = tk.Frame(section_frame, bg=C["bg"])
        if not collapsed:
            content.pack(fill="x")

        def _toggle(_e=None):
            is_col = self._section_collapsed.get(group, {}).get(section, False)
            if group not in self._section_collapsed:
                self._section_collapsed[group] = {}
            self._section_collapsed[group][section] = not is_col
            if is_col:
                arrow_var.set("▼")
                content.pack(fill="x")
            else:
                arrow_var.set("▶")
                content.pack_forget()

        for w in (hdr, arrow_lbl) + tuple(hdr.winfo_children()):
            w.bind("<Button-1>", _toggle)

        return content

    def _refresh_tabs(self):
        for w in self._tab_bar.winfo_children():
            w.destroy()
        self._group_tab_btns: list[tuple[str, tk.Button]] = []
        self._drag_state: dict | None = None

        for g in self.db.list_groups():
            btn, wrapper, inner, indicator = self._add_tab_btn(g, g, self._active_group == g)
            idx = len(self._group_tab_btns)
            self._group_tab_btns.append((g, btn, wrapper, inner, indicator))
            btn.bind("<ButtonPress-1>",   lambda e, i=idx: self._drag_start(e, i))
            btn.bind("<B1-Motion>",       self._drag_motion)
            btn.bind("<ButtonRelease-1>", self._drag_end)

        plus = tk.Button(
            self._tab_bar, text="+",
            bg=C["bg"], fg=C["tab_fg"],
            activebackground=C["card_hover"], activeforeground=C["accent"],
            relief="flat", bd=0, padx=10, pady=7,
            font=("Segoe UI", 10), cursor="hand2",
            command=self._create_group,
        )
        plus.bind("<Enter>", lambda e: plus.config(bg=C["card_hover"]))
        plus.bind("<Leave>", lambda e: plus.config(bg=C["bg"]))
        plus.pack(side="left", padx=(8, 2))

        self._all_tab_refs = self._add_tab_btn(None, "All", self._active_group is None, side="right")

    def _add_tab_btn(self, group, label, is_active, side="left"):
        if is_active:
            btn_bg, fg, fw = C["card_bg"], C["accent"], "bold"
            bar_bg   = C["accent"]
            hover_bg = C["accent_wash"]
            border   = C["card_bg"]
        else:
            btn_bg, fg, fw = C["tab_inactive_bg"], C["tab_fg"], "normal"
            bar_bg   = C["tab_inactive_bg"]
            hover_bg = C["tab_inactive_hover"]
            border   = C["border"]

        wrapper = tk.Frame(self._tab_bar, bg=border,
                           highlightthickness=0, padx=1, pady=1)
        inner = tk.Frame(wrapper, bg=btn_bg)
        inner.pack(fill="both", expand=True)

        btn = tk.Button(
            inner, text=label,
            bg=btn_bg, fg=fg,
            activebackground=hover_bg, activeforeground=fg,
            relief="flat", bd=0, padx=14, pady=6,
            font=("Segoe UI", 10, fw), cursor="hand2",
            command=lambda g=group: self._switch_group(g),
        )
        btn.pack(fill="x")
        indicator = tk.Frame(inner, bg=bar_bg, height=3)
        indicator.pack(fill="x")

        btn.bind("<Enter>", lambda e, b=btn, h=hover_bg: b.config(bg=h))
        btn.bind("<Leave>", lambda e, b=btn, ob=btn_bg: b.config(bg=ob))
        if group is not None:
            btn.bind("<Button-3>", lambda e, g=group: self._tab_context_menu(e, g))
        wrapper.pack(side=side, padx=3, pady=(3, 0))
        return btn, wrapper, inner, indicator

    def _apply_tab_style(self, is_active, btn, wrapper, inner, indicator):
        if is_active:
            btn_bg, fg, fw = C["card_bg"], C["accent"], "bold"
            bar_bg, hover_bg, border = C["accent"], C["accent_wash"], C["card_bg"]
        else:
            btn_bg, fg, fw = C["tab_inactive_bg"], C["tab_fg"], "normal"
            bar_bg, hover_bg, border = C["tab_inactive_bg"], C["tab_inactive_hover"], C["border"]
        wrapper.config(bg=border)
        inner.config(bg=btn_bg)
        btn.config(bg=btn_bg, fg=fg, font=("Segoe UI", 10, fw),
                   activebackground=hover_bg, activeforeground=fg)
        indicator.config(bg=bar_bg)
        btn.bind("<Enter>", lambda e, b=btn, h=hover_bg: b.config(bg=h))
        btn.bind("<Leave>", lambda e, b=btn, ob=btn_bg: b.config(bg=ob))

    def _update_tab_styles(self):
        for name, btn, wrapper, inner, indicator in self._group_tab_btns:
            self._apply_tab_style(self._active_group == name, btn, wrapper, inner, indicator)
        if hasattr(self, "_all_tab_refs"):
            self._apply_tab_style(self._active_group is None, *self._all_tab_refs)

    def _switch_group(self, group):
        self._active_group = group
        self._update_tab_styles()
        self._refresh_cards()
        self._canvas.yview_moveto(0)

    def _create_group(self):
        dlg = NewGroupDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            name, base_dir = dlg.result
            self.db.create_group(name, base_dir)
            _log.info("Group created: %s", name)
            self._active_group = name
            self._refresh()

    def _drag_start(self, event, idx: int):
        self._drag_state = {
            "src_idx": idx,
            "start_x": event.x_root,
            "active": False,
            "hover_idx": None,
        }

    def _drag_motion(self, event):
        if self._drag_state is None:
            return
        if abs(event.x_root - self._drag_state["start_x"]) > 5:
            self._drag_state["active"] = True
        if not self._drag_state["active"]:
            return

        hover_idx = None
        for i, (_, btn, *_rest) in enumerate(self._group_tab_btns):
            bx = btn.winfo_rootx()
            if bx <= event.x_root <= bx + btn.winfo_width():
                hover_idx = i
                break

        prev = self._drag_state["hover_idx"]
        if prev != hover_idx:
            if prev is not None:
                pname, pbtn = self._group_tab_btns[prev][0], self._group_tab_btns[prev][1]
                pbtn.config(bg=C["card_bg"] if self._active_group == pname else C["tab_inactive_bg"])
            if hover_idx is not None and hover_idx != self._drag_state["src_idx"]:
                self._group_tab_btns[hover_idx][1].config(bg="#4a4a6a")
            self._drag_state["hover_idx"] = hover_idx

    def _drag_end(self, event):
        if self._drag_state is None:
            return
        state = self._drag_state
        self._drag_state = None

        if not state["active"]:
            return

        hover_idx = state["hover_idx"]
        src_idx = state["src_idx"]
        if hover_idx is not None and hover_idx != src_idx:
            groups = [entry[0] for entry in self._group_tab_btns]
            groups.insert(hover_idx, groups.pop(src_idx))
            self.db.reorder_groups(groups)
            self._refresh_tabs()

        return "break"

    def _rename_group(self, old: str):
        new = simpledialog.askstring("Rename Group", f"New name for '{old}':",
                                     initialvalue=old, parent=self)
        if new and new.strip() and new.strip() != old:
            self.db.rename_group(old, new.strip())
            _log.info("Group renamed: %s -> %s", old, new.strip())
            if self._active_group == old:
                self._active_group = new.strip()
            self._refresh()

    def _delete_group(self, name: str):
        if messagebox.askyesno(
            "Delete Group",
            f"Delete group '{name}'?\n\nScripts in this group will be moved to ungrouped.",
            parent=self,
        ):
            self.db.delete_group(name)
            _log.info("Group deleted: %s", name)
            if self._active_group == name:
                remaining = self.db.list_groups()
                self._active_group = remaining[0] if remaining else None
            self._refresh()

    def _clone_group(self, source: str):
        existing = self.db.list_groups()
        default = f"{source} (copy)"
        if default in existing:
            n = 2
            while f"{source} (copy {n})" in existing:
                n += 1
            default = f"{source} (copy {n})"
        name = simpledialog.askstring("Clone Group", f"Name for clone of '{source}':",
                                      initialvalue=default, parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.db.list_groups():
            messagebox.showerror("Clone Group", f"A group named '{name}' already exists.", parent=self)
            return
        scripts_n, pipes_n = self.db.clone_group(source, name)
        _log.info("Group cloned: %s -> %s (%d scripts, %d pipelines)", source, name, scripts_n, pipes_n)
        self._active_group = name
        self._refresh()
        self.status_var.set(f"Cloned '{source}' → '{name}' ({scripts_n} scripts, {pipes_n} pipelines).")

    def _manage_group_base_dir(self, group: str):
        current = self.db.get_group_base_dir(group)
        dlg = GroupBaseDirDialog(self, group, current)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        new_dir = dlg.result
        if new_dir == current:
            return
        if not new_dir:
            if not messagebox.askyesno(
                "Clear base directory",
                f"Remove base directory restriction for '{group}'?\n\nExisting script paths will not be changed.",
                parent=self,
            ):
                return
            self.db.set_group_base_dir(group, "")
            self.status_var.set(f"Base directory cleared for '{group}'.")
        else:
            if current:
                if not messagebox.askyesno(
                    "Re-map paths",
                    f"Re-map script paths from\n{current}\nto\n{new_dir}?\n\n"
                    "Paths already outside the old base will be left unchanged.",
                    parent=self,
                ):
                    return
            remapped, untouched = self.db.set_group_base_dir(group, new_dir)
            if untouched:
                messagebox.showwarning(
                    "Some paths not remapped",
                    f"{len(untouched)} script(s) have paths outside the old base directory and were not remapped:\n"
                    + "\n".join(untouched[:10]),
                    parent=self,
                )
            self.status_var.set(f"Base directory set for '{group}'. {remapped} path(s) remapped.")
        self._refresh()

    def _tab_context_menu(self, event, group: str):
        menu = tk.Menu(self, tearoff=0, bg=C["menu_bg"], fg=C["fg_on_dark"],
                       activebackground=C["accent"], activeforeground=C["fg_on_dark"],
                       font=("Segoe UI", 10))
        menu.add_command(label="✏  Rename", command=lambda: self._rename_group(group))
        menu.add_command(label="📋  Clone Group", command=lambda: self._clone_group(group))
        menu.add_command(label="📁  Base directory…", command=lambda: self._manage_group_base_dir(group))
        menu.add_command(label="📤  Export group", command=lambda: self._export_config(group_name=group))
        menu.add_separator()
        menu.add_command(label="🗑  Delete Group", command=lambda: self._delete_group(group),
                         foreground=C["menu_danger"], activeforeground=C["menu_danger"])
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # Appearance / theme
    # ------------------------------------------------------------------

    def _rebuild_ui(self) -> None:
        """Tear down and reconstruct all widgets after a theme switch.
        Toplevel windows (open dialogs) are skipped — destroying the caller
        from inside its own callback would crash Tcl."""
        for child in self.winfo_children():
            if not isinstance(child, tk.Toplevel):
                child.destroy()
        self._build_ui()
        self._refresh()

    def _open_appearance(self) -> None:
        if self._jobreg:
            self.status_var.set("Stop running jobs before changing theme.")
            return

        def _apply(new_settings: dict, persist: bool = True) -> None:
            self._settings.update(new_settings)
            apply_theme(
                self._settings.get("theme", "light"),
                self._settings.get("accent_color"),
            )
            from ryos.ui import cards as _cards_mod
            _cards_mod.set_compact_mode(self._settings.get("compact_mode", False))
            _cards_mod.set_card_size(self._settings.get("card_size", "medium"))
            if persist:
                _save_settings(self._settings)
            self._rebuild_ui()

        AppearanceDialog(self, self._settings, _apply)

    # ------------------------------------------------------------------

    def _refresh(self):
        self._cards = []
        if self._select_mode:
            self._select_mode = False
            self._select_bar.pack_forget()
            self._options_menu.entryconfig(0, label="☑  Select scripts")
        self._refresh_tabs()
        self._refresh_cards()

    def _refresh_cards(self):
        for gn in list(self._quick_run_bars):
            self._quick_run_hide_suggestions(gn)
        self._quick_run_buttons.clear()
        self._quick_run_bars.clear()
        self._running_slots = {}
        for w in self.cards_frame.winfo_children():
            w.destroy()
        self._cards = []
        self._pipeline_cards = []

        def make_move(a, b):
            def _move():
                self.db.swap_order(a, b)
                self._refresh()
            return _move

        def make_top(s):
            def _top():
                self.db.move_to_top(s)
                self._refresh()
            return _top

        def render_group_sections(gname: str, scripts: list):
            group_base_dir = self.db.get_group_base_dir(gname)
            banner = tk.Frame(self.cards_frame, bg=C["card_bg"],
                              highlightbackground=C["border"], highlightthickness=1,
                              cursor="hand2")
            banner.pack(fill="x", padx=8, pady=(10, 0))
            icon_lbl = tk.Label(banner, text="📁", bg=C["card_bg"], fg=C["path_fg"],
                                font=("Segoe UI", 11), padx=10, pady=8, cursor="hand2")
            icon_lbl.pack(side="left")
            path_text = group_base_dir if group_base_dir else "No base directory — click to set"
            path_fg = C["name_fg"] if group_base_dir else C["path_fg"]
            path_lbl = tk.Label(banner, text=path_text, bg=C["card_bg"], fg=path_fg,
                                font=("Segoe UI", 10), anchor="w", pady=8, cursor="hand2")
            path_lbl.pack(side="left")

            if group_base_dir and self._settings.get("quick_run_enabled", True):
                self._build_quick_run_bar(gname, group_base_dir, banner)

            def _open(e, g=gname):
                self._manage_group_base_dir(g)
            for w in (banner, icon_lbl, path_lbl):
                w.bind("<Button-1>", _open)

            run_content = self._make_section_header(
                self.cards_frame, gname, "running", "Running"
            )
            self._running_slots[gname] = run_content
            jobs_here = self._running_jobs_in_group(gname)
            if jobs_here:
                for job in jobs_here:
                    self._add_running_row(run_content, job)
            else:
                tk.Label(run_content, text="No script is currently running.",
                         bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 9), padx=6).pack(anchor="w", pady=(2, 4))

            pipe_content = self._make_section_header(
                self.cards_frame, gname, "pipelines", "Pipelines"
            )
            pipelines = self.db.list_pipelines(gname)
            if pipelines:
                from ryos.ui import cards as _cards_mod
                _pad_y, _ipad_y = _cards_mod.row_metrics()[:2]
                for p_id, p_name in pipelines:
                    pc = PipelineCard(
                        pipe_content, p_id, p_name, self.db,
                        group_name=gname,
                        on_run=self._run_pipeline,
                        on_edit=self._edit_pipeline,
                        on_refresh=self._refresh_cards,
                    )
                    pc.pack(fill="x", pady=_pad_y, ipady=_ipad_y)
                    self._bind_pipeline_drag(pc)
                    self._pipeline_cards.append(pc)
            else:
                tk.Label(pipe_content, text="No pipelines yet.",
                         bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 9), padx=6).pack(anchor="w", pady=(2, 4))

            scr_content = self._make_section_header(
                self.cards_frame, gname, "scripts", "Scripts"
            )
            if scripts:
                from ryos.ui import cards as _cards_mod
                _pad_y, _ipad_y = _cards_mod.row_metrics()[:2]
                gids = [r[0] for r in scripts]
                for gi, rec in enumerate(scripts):
                    sid = rec[0]
                    up_id   = gids[gi - 1] if gi > 0 else None
                    down_id = gids[gi + 1] if gi < len(gids) - 1 else None
                    card = ScriptCard(
                        scr_content, rec, self.db, self._run_script, self._refresh,
                        on_move_up      = make_move(sid, up_id)   if up_id   else lambda: None,
                        on_move_down    = make_move(sid, down_id) if down_id else lambda: None,
                        on_move_top     = make_top(sid)           if up_id   else lambda: None,
                        group_base_dir  = group_base_dir,
                    )
                    card.pack(fill="x", pady=_pad_y, ipady=_ipad_y)
                    self._bind_card_drag(card)
                    self._cards.append(card)
            else:
                tk.Label(scr_content, text="No scripts yet.",
                         bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 9), padx=6).pack(anchor="w", pady=(2, 4))

        if self._active_group is None:
            all_scripts = self.db.list_all()
            groups = self.db.list_groups()
            if not groups and not all_scripts:
                tk.Label(self.cards_frame,
                         text="No scripts yet.\nClick '+ Script' to get started.",
                         bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 10), justify="center").pack(pady=60)
                return
            group_scripts: dict[str, list] = {g: [] for g in groups}
            group_scripts.setdefault("", [])
            for rec in all_scripts:
                g = rec[8] or ""
                group_scripts.setdefault(g, [])
                group_scripts[g].append(rec)
            any_named = bool(groups)
            for gname in groups:
                self._make_group_header(gname)
                render_group_sections(gname, group_scripts.get(gname, []))
            ungrouped = group_scripts.get("", [])
            if ungrouped:
                if any_named:
                    self._make_group_header("Other")
                render_group_sections("", ungrouped)
        else:
            scripts = [s for s in self.db.list_all()
                       if (s[8] or "") == self._active_group]
            render_group_sections(self._active_group, scripts)


    def _build_quick_run_bar(self, gname, group_base_dir, banner):
        """Build the per-group quick-run button, entry bar, and key
        bindings, registering them into self._quick_run_buttons/_bars.
        Extracted from _refresh_cards to keep that method focused."""
        _gn = gname
        qr_btn = _flat_button(banner, "⚡", C["bolt"], C["bolt_hover"],
                              lambda g=_gn: self._toggle_quick_run_bar(g),
                              width=4, fg=C["name_fg"])
        qr_btn.pack(side="right", padx=(0, 6))
        Tooltip(qr_btn, "Toggle quick-run bar")
        self._quick_run_buttons[gname] = qr_btn

        bar_frame = tk.Frame(self.cards_frame, bg=C["bg"],
                             highlightbackground=C["border"], highlightthickness=1)
        _PH = "script name [params...]"
        entry_var = tk.StringVar()
        is_ph = [True]
        entry = tk.Entry(bar_frame, textvariable=entry_var, bg=C["card_bg"], fg=C["path_fg"],
                         insertbackground=C["name_fg"], relief="flat", bd=4,
                         font=("Segoe UI", 10))
        entry_var.set(_PH)
        entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=6)

        def _ph_key(e, _ev=entry_var, _en=entry, _f=is_ph):
            if _f[0]:
                _ev.set("")
                _en.config(fg=C["name_fg"])
                _f[0] = False

        def _ph_focus_out(e, _ev=entry_var, _en=entry, _f=is_ph):
            if not _ev.get().strip():
                _ev.set(_PH)
                _en.config(fg=C["path_fg"])
                _f[0] = True

        entry.bind("<KeyPress>", _ph_key)
        entry.bind("<FocusOut>", _ph_focus_out)

        _flat_button(bar_frame, "Run", C["accent"], C["accent2"],
                     lambda g=_gn: self._quick_run_submit(g), width=6).pack(side="left", pady=6)
        _flat_button(bar_frame, "✕", C["btn_dark_bg"], C["btn_dark_hover"],
                     lambda g=_gn: self._hide_quick_run_bar(g), width=3).pack(side="left", padx=(4, 8), pady=6)

        def _on_key_release(e, _g=_gn):
            if e.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R",
                            "Control_L", "Control_R", "Alt_L", "Alt_R"):
                return
            bar = self._quick_run_bars.get(_g)
            if bar is None:
                return
            after_id = bar.get("suggest_after_id")
            if after_id:
                self.after_cancel(after_id)
            bar["suggest_after_id"] = self.after(120, lambda g=_g: self._quick_run_refresh_suggestions(g))
        entry.bind("<KeyRelease>", _on_key_release)

        def _on_down(e, _g=_gn):
            bar = self._quick_run_bars.get(_g)
            if bar and bar.get("suggest_win") and bar["suggest_win"].winfo_exists():
                lb = bar["suggest_lb"]
                sel = lb.curselection()
                nxt = (sel[0] + 1) if sel else 0
                if nxt < lb.size():
                    lb.selection_clear(0, "end")
                    lb.selection_set(nxt)
                    lb.see(nxt)
                return "break"
        entry.bind("<Down>", _on_down)

        def _on_up(e, _g=_gn):
            bar = self._quick_run_bars.get(_g)
            if bar and bar.get("suggest_win") and bar["suggest_win"].winfo_exists():
                lb = bar["suggest_lb"]
                sel = lb.curselection()
                prev = (sel[0] - 1) if sel else lb.size() - 1
                if prev >= 0:
                    lb.selection_clear(0, "end")
                    lb.selection_set(prev)
                    lb.see(prev)
                return "break"
        entry.bind("<Up>", _on_up)

        def _on_tab(e, _g=_gn):
            bar = self._quick_run_bars.get(_g)
            if bar and bar.get("suggest_win") and bar["suggest_win"].winfo_exists():
                lb = bar["suggest_lb"]
                sel = lb.curselection()
                if sel:
                    rel = lb.get(sel[0])
                    if rel != "Indexing files…":
                        self._quick_run_accept_suggestion(_g, rel, submit=False)
                return "break"
        entry.bind("<Tab>", _on_tab)

        def _on_return(e, _g=_gn):
            bar = self._quick_run_bars.get(_g)
            if bar and bar.get("suggest_win") and bar["suggest_win"].winfo_exists():
                lb = bar["suggest_lb"]
                sel = lb.curselection()
                if sel:
                    rel = lb.get(sel[0])
                    if rel != "Indexing files…":
                        self._quick_run_accept_suggestion(_g, rel, submit=True)
                        return "break"
            self._quick_run_submit(_g)
            return "break"
        entry.bind("<Return>", _on_return)

        def _on_escape(e, _g=_gn):
            bar = self._quick_run_bars.get(_g)
            if bar and bar.get("suggest_win") and bar["suggest_win"].winfo_exists():
                self._quick_run_hide_suggestions(_g)
                return "break"
            self._hide_quick_run_bar(_g)
            return "break"
        entry.bind("<Escape>", _on_escape)

        def _on_focus_out_ext(e, _g=_gn):
            self.after(150, lambda g=_g: self._quick_run_maybe_hide_suggestions(g))
        entry.bind("<FocusOut>", _on_focus_out_ext, add=True)

        self._quick_run_bars[gname] = {
            "frame": bar_frame,
            "entry": entry,
            "var": entry_var,
            "is_placeholder": is_ph,
            "base_dir": group_base_dir,
            "banner": banner,
            "suggest_win": None,
            "suggest_lb": None,
            "suggest_after_id": None,
        }

        if self._quick_run_open_group == gname:
            bar_frame.pack(fill="x", padx=8, pady=(2, 0), after=banner)
            entry.focus_set()

    def _add_script(self):
        groups = self.db.list_groups()
        if not groups:
            name = simpledialog.askstring(
                "Create a Group First",
                "You have no groups yet.\nEnter a group name to continue:",
                parent=self,
            )
            if not (name and name.strip()):
                return
            self.db.create_group(name.strip())
            self._active_group = name.strip()
            self._refresh_tabs()
            groups = self.db.list_groups()
        group_base_dirs = {name: bd for name, bd in self.db.list_groups_with_meta()}
        ScriptDialog(self, self.db, on_save=self._refresh,
                     existing_groups=groups,
                     default_group=self._active_group or "",
                     group_base_dirs=group_base_dirs)

    _DRAG_THRESHOLD = 6

    def _bind_card_drag(self, card: "ScriptCard"):
        def recurse(w):
            w.bind("<ButtonPress-1>",   lambda e, c=card: self._card_drag_press(e, c))
            w.bind("<B1-Motion>",       lambda e, c=card: self._card_drag_motion(e, c))
            w.bind("<ButtonRelease-1>", lambda e:         self._card_drag_release(e))
            for ch in w.winfo_children():
                recurse(ch)
        recurse(card._text_area)

    def _bind_pipeline_drag(self, card: "PipelineCard"):
        def recurse(w):
            if w is card._summary_row:
                return
            w.bind("<ButtonPress-1>",   lambda e, c=card: self._card_drag_press(e, c))
            w.bind("<B1-Motion>",       lambda e, c=card: self._card_drag_motion(e, c))
            w.bind("<ButtonRelease-1>", lambda e:         self._card_drag_release(e))
            for ch in w.winfo_children():
                recurse(ch)
        recurse(card._content)

    def _card_drag_press(self, event, card: "ScriptCard"):
        self._drag_card = card
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root

    def _card_drag_motion(self, event, card: "ScriptCard"):
        if self._drag_card is None:
            return
        if (abs(event.x_root - self._drag_start_x) < self._DRAG_THRESHOLD and
                abs(event.y_root - self._drag_start_y) < self._DRAG_THRESHOLD):
            return
        if self._drag_ghost is None:
            self._create_drag_ghost(card)
        self._drag_ghost.geometry(f"+{event.x_root + 14}+{event.y_root + 8}")
        self._update_drag_target(event)

    def _create_drag_ghost(self, card: "ScriptCard"):
        self._drag_ghost = tk.Toplevel(self)
        self._drag_ghost.overrideredirect(True)
        self._drag_ghost.attributes("-alpha", 0.85)
        self._drag_ghost.configure(bg=C["accent"])
        tk.Label(self._drag_ghost, text=f"  {card._name}  ",
                 bg=C["accent"], fg=C["fg_on_dark"],
                 font=("Segoe UI", 10, "bold"), padx=6, pady=4).pack()

    def _update_drag_target(self, event):
        over_tab = self._find_tab_at(event.x_root, event.y_root)

        if self._drag_tab_highlight:
            prev_btn, prev_bg = self._drag_tab_highlight
            if over_tab is None or over_tab[1] is not prev_btn:
                try:
                    prev_btn.config(bg=prev_bg)
                except tk.TclError:
                    pass
                self._drag_tab_highlight = None

        if over_tab is not None:
            btn = over_tab[1]
            if self._drag_tab_highlight is None:
                self._drag_tab_highlight = (btn, btn.cget("bg"))
                btn.config(bg="#6b7bbd")
            self._drag_target_group = over_tab[0]
            self._drag_insert_before = None
            if self._drag_indicator:
                self._drag_indicator.place_forget()
        else:
            self._drag_target_group = None
            self._update_insertion_indicator(event)

    def _find_tab_at(self, x_root, y_root):
        for entry in self._group_tab_btns:
            _, btn, *_ = entry
            try:
                if (btn.winfo_rootx() <= x_root <= btn.winfo_rootx() + btn.winfo_width() and
                        btn.winfo_rooty() <= y_root <= btn.winfo_rooty() + btn.winfo_height()):
                    return entry
            except tk.TclError:
                pass
        return None

    def _update_insertion_indicator(self, event):
        is_pipeline_drag = isinstance(self._drag_card, PipelineCard)
        active_list = self._pipeline_cards if is_pipeline_drag else self._cards
        if self._active_group is None or not active_list:
            if self._drag_indicator:
                self._drag_indicator.place_forget()
            return

        insert_y_screen = None
        before_id = None
        visible = [c for c in active_list if c is not self._drag_card]

        id_attr = "pipeline_id" if is_pipeline_drag else "script_id"
        for card in visible:
            try:
                mid = card.winfo_rooty() + card.winfo_height() // 2
            except tk.TclError:
                continue
            if event.y_root <= mid:
                before_id = getattr(card, id_attr)
                insert_y_screen = card.winfo_rooty()
                break

        if insert_y_screen is None and visible:
            last = visible[-1]
            try:
                insert_y_screen = last.winfo_rooty() + last.winfo_height()
            except tk.TclError:
                pass

        self._drag_insert_before = before_id

        if insert_y_screen is not None:
            if self._drag_indicator is None:
                self._drag_indicator = tk.Frame(self, bg=C["accent"], height=3)
            rel_y = insert_y_screen - self.winfo_rooty()
            cx    = self._canvas.winfo_rootx() - self.winfo_rootx()
            self._drag_indicator.place(x=cx, y=rel_y,
                                       width=self._canvas.winfo_width(), height=3)
            self._drag_indicator.lift()
        else:
            if self._drag_indicator:
                self._drag_indicator.place_forget()

    def _card_drag_release(self, _event):
        card = self._drag_card
        if card is None:
            return
        if self._drag_ghost is not None:
            is_pipeline = isinstance(card, PipelineCard)
            if self._drag_target_group is not None:
                if self._drag_target_group != card._group_name:
                    if is_pipeline:
                        self.db.move_pipeline_to_group(card.pipeline_id, self._drag_target_group)
                    else:
                        self.db.move_to_group(card.script_id, self._drag_target_group)
                        if not is_pipeline:
                            target_base = self.db.get_group_base_dir(self._drag_target_group)
                            rec = self.db.get(card.script_id)
                            if target_base and rec and not _is_inside(rec[2], target_base):
                                self.status_var.set(
                                    f"Warning: script moved to '{self._drag_target_group}' but its path is outside the group's base directory."
                                )
                    self._refresh()
            elif self._active_group is not None:
                if is_pipeline:
                    self.db.reorder_pipeline(card.pipeline_id, self._active_group,
                                             self._drag_insert_before)
                else:
                    self.db.reorder_script(card.script_id, self._active_group,
                                           self._drag_insert_before)
                self._refresh_cards()
        self._clear_drag_state()

    def _clear_drag_state(self):
        if self._drag_ghost:
            try:
                self._drag_ghost.destroy()
            except tk.TclError:
                pass
            self._drag_ghost = None
        if self._drag_indicator:
            try:
                self._drag_indicator.place_forget()
                self._drag_indicator.destroy()
            except tk.TclError:
                pass
            self._drag_indicator = None
        if self._drag_tab_highlight:
            btn, orig_bg = self._drag_tab_highlight
            try:
                btn.config(bg=orig_bg)
            except tk.TclError:
                pass
            self._drag_tab_highlight = None
        self._drag_card = None
        self._drag_insert_before = None
        self._drag_target_group = None

    def _show_options_menu(self):
        btn = self._options_btn
        self._options_menu.tk_popup(
            btn.winfo_rootx(),
            btn.winfo_rooty() + btn.winfo_height(),
        )

    def _add_pipeline(self):
        if not self._active_group:
            messagebox.showinfo("Select a Group",
                                "Please select a group first to create a pipeline.",
                                parent=self)
            return
        name = simpledialog.askstring("New Pipeline", "Pipeline name:", parent=self)
        if not (name and name.strip()):
            return
        pid = self.db.create_pipeline(name.strip(), self._active_group)
        self._refresh_cards()
        self._edit_pipeline(pid, name.strip())

    def _edit_pipeline(self, pipeline_id: int, name: str):
        PipelineEditorDialog(self, self.db, pipeline_id, name,
                             self._active_group or "", self._refresh_cards)

    def _run_pipeline(self, pipeline_id: int, pipeline_name: str):
        max_jobs = self._settings.get("max_parallel_jobs", MAX_PARALLEL_JOBS)
        if max_jobs > 0 and len(self._jobreg) >= max_jobs:
            messagebox.showinfo("Too many jobs",
                                f"Maximum of {max_jobs} parallel jobs reached.\n"
                                "Stop a running job before launching another.",
                                parent=self)
            return
        steps = self.db.list_pipeline_steps(pipeline_id)
        if not steps:
            messagebox.showinfo("Empty Pipeline",
                                "This pipeline has no steps.\nClick ⚙ to add scripts.",
                                parent=self)
            return
        # Resolve group for this pipeline
        group = self._active_group or ""
        for gname in self._running_slots:
            if any(p_id == pipeline_id for p_id, _ in self.db.list_pipelines(gname)):
                group = gname
                break
        job = self._new_job(
            "pipeline", script_id=None, pipeline_id=pipeline_id,
            name=f"⚡ {pipeline_name}", group=group,
            pipeline_name=pipeline_name,
            pipeline_queue=list(steps),
            pipeline_total=len(steps),
        )
        job.start_time = datetime.now()
        content = self._running_slots.get(group)
        if content and content.winfo_exists():
            self._add_running_row(content, job)
        self._append_output(
            f"\n{'━' * 60}\n"
            f"⚡  {pipeline_name}  ·  {job.pipeline_total} step"
            f"{'s' if job.pipeline_total != 1 else ''}\n"
            f"{'━' * 60}\n\n",
            tag="info",
            tab_key=job.tab_key,
        )
        self._run_next_pipeline_step(job)

    def _run_next_pipeline_step(self, job: "_Job"):
        if job.stopped or not job.pipeline_queue:
            return
        step_id, sid, name, path, params, interp, params_override = job.pipeline_queue.pop(0)
        if params_override is not None:
            params = params_override
        job.pipeline_step_idx += 1
        n, total = job.pipeline_step_idx, job.pipeline_total
        self._append_output(
            f"{'─' * 40}\nStep {n}/{total}:  {name}\n{'─' * 40}\n",
            tag="info",
            tab_key=job.tab_key,
        )
        self.status_var.set(f"Pipeline step {n}/{total}: {name}")
        _lbl = f"⚡ {job.pipeline_name}  —  Step {n}/{total}: {name}"
        job.name = _lbl
        if job.name_var is not None:
            job.name_var.set(_lbl)
        if not Path(path).exists():
            self.output_queue.put(("stderr", job.job_id, f"[ERROR] File not found: {path}\n"))
            self.output_queue.put(("done", job.job_id, sid, "error", ""))
            return
        final_interp = resolve_interpreter(path, interp)
        try:
            cmd = build_command(path, params, final_interp)
        except ValueError as e:
            self.output_queue.put(("stderr", job.job_id, f"[ERROR] Parameter error: {e}\n"))
            self.output_queue.put(("done", job.job_id, sid, "error", ""))
            return
        self._launch(job, cmd, name, sid)

    def _toggle_select_mode(self):
        self._select_mode = not self._select_mode
        if self._select_mode:
            self._options_menu.entryconfig(0, label="✕  Cancel select")
            self._select_bar_var.set("Tick the checkboxes next to scripts you want to delete.")
            self._select_bar.pack(fill="x", before=self._paned)
            for card in self._cards:
                card.show_checkbox(self._update_select_count)
        else:
            self._options_menu.entryconfig(0, label="☑  Select scripts")
            self._select_bar.pack_forget()
            for card in self._cards:
                card.hide_checkbox()

    def _update_select_count(self):
        n = sum(1 for c in self._cards if c.selected.get())
        total = len(self._cards)
        if n:
            self._select_bar_var.set(f"{n} of {total} selected")
        else:
            self._select_bar_var.set("Tick the checkboxes next to scripts you want to delete.")
        all_selected = n == total and total > 0
        self._sel_all_btn.config(text="Deselect All" if all_selected else "Select All")

    def _toggle_select_all(self):
        all_selected = all(c.selected.get() for c in self._cards) and self._cards
        for card in self._cards:
            card.selected.set(not all_selected)
        self._update_select_count()

    def _delete_selected(self):
        ids = [c.script_id for c in self._cards if c.selected.get()]
        if not ids:
            messagebox.showinfo("Nothing Selected", "Tick the checkboxes next to the scripts you want to delete.")
            return
        if messagebox.askyesno("Delete Selected", f"Delete {len(ids)} selected script(s)?"):
            self.db.delete_many(ids)
            self._refresh()

    def _delete_all(self):
        if not self._cards:
            return
        if messagebox.askyesno("Delete All", f"Delete all {len(self._cards)} scripts? This cannot be undone."):
            self.db.delete_all()
            self._refresh()

    def _export_config(self, group_name: str | None = None):
        if group_name:
            initial = f"ryos_{group_name}.json"
            title   = f"Export Group: {group_name}"
        else:
            initial = "ryos_all.json"
            title   = "Export All Groups"
        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
            initialfile=initial,
        )
        if not path:
            return
        try:
            n_scripts, n_pipelines = self.db.export_to_file(path, group_name=group_name)
            _log.info("Export: %d scripts, %d pipelines -> %s", n_scripts, n_pipelines, path)
            self.status_var.set(
                f"Exported {n_scripts} script(s), {n_pipelines} pipeline(s) → {Path(path).name}"
            )
        except Exception as e:
            _log.error("Export failed: %s", e)
            messagebox.showerror("Export Failed", str(e))

    def _import_config(self):
        path = filedialog.askopenfilename(
            title="Import Config",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            replace = messagebox.askyesno(
                "Import Mode",
                "How should existing data in the imported groups be handled?\n\n"
                "Yes = Replace (overwrite scripts/pipelines in the imported groups)\n"
                "No  = Merge (skip duplicates by path / name)",
            )
            added, skipped = self.db.import_from_file(path, replace=replace)
            _log.info("Import: %d added, %d skipped from %s", added, skipped, path)
            self._refresh()
            self.status_var.set(f"Import done — {added} script(s) added, {skipped} skipped.")
        except Exception as e:
            _log.error("Import failed: %s", e)
            messagebox.showerror("Import Failed", str(e))

    def _launch(self, job: "_Job", cmd, name, script_id) -> None:
        """Mark the script as run and start its worker thread.

        Single entry point for both ad-hoc script runs and pipeline steps, so
        any change to how jobs are spawned lives in one place.
        """
        self.db.mark_run(script_id)
        threading.Thread(
            target=self._run_subprocess, args=(job, cmd, name, script_id), daemon=True,
        ).start()

    def _run_script(self, script_id, name, path, params, interpreter):
        max_jobs = self._settings.get("max_parallel_jobs", MAX_PARALLEL_JOBS)
        if max_jobs > 0 and len(self._jobreg) >= max_jobs:
            messagebox.showinfo("Too many jobs",
                                f"Maximum of {max_jobs} parallel jobs reached.\n"
                                "Stop a running job before launching another.")
            return

        if not Path(path).exists():
            messagebox.showerror("File Not Found", f"File does not exist:\n{path}")
            return

        final_interp = resolve_interpreter(path, interpreter)
        try:
            cmd = build_command(path, params, final_interp)
        except ValueError as e:
            messagebox.showerror("Parameter Error", f"Could not parse parameters:\n{e}")
            return

        rec = self.db.get(script_id)
        group = (rec[5] or "") if rec else (self._active_group or "")
        job = self._new_job("script", script_id=script_id, pipeline_id=None,
                            name=name, group=group)
        job.start_time = datetime.now()

        _log.info("Run: %s | cmd: %s", name, " ".join(cmd))
        self._append_output(
            f"\n{'━'*60}\n"
            f"  ▶  {name}\n"
            f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}    {' '.join(cmd)}\n"
            f"{'━'*60}\n\n",
            tag="info",
            tab_key=job.tab_key,
        )
        self.status_var.set(f"Running: {name}")
        content = self._running_slots.get(group)
        if content and content.winfo_exists():
            self._add_running_row(content, job)
        self._launch(job, cmd, name, script_id)

    def _quick_run_get_index(self, base_dir: str) -> list | None:
        import time
        cached = self._quick_run_index_cache.get(base_dir)
        if cached is not None:
            if time.monotonic() - cached[0] > _QUICK_RUN_INDEX_TTL:
                self._quick_run_build_index_async(base_dir)  # rebuild in background
            return cached[1]  # return stale data while rebuild runs
        # First access this session: try disk before kicking a full rescan.
        if base_dir not in self._quick_run_disk_loaded:
            self._quick_run_disk_loaded.add(base_dir)
            disk = _quick_run_load_disk_index(base_dir, self._settings.get("quick_run_index_ttl", 300))
            if disk is not None:
                wall_ts, paths = disk
                age = time.time() - wall_ts
                # Reconstruct a monotonic timestamp consistent with the wall-clock age.
                mono_ts = time.monotonic() - age
                self._quick_run_index_cache[base_dir] = (mono_ts, paths)
                # If the disk data is already older than the in-memory TTL, refresh in background.
                if age > _QUICK_RUN_INDEX_TTL:
                    self._quick_run_build_index_async(base_dir)
                return paths
        self._quick_run_build_index_async(base_dir)
        return None

    def _quick_run_build_index_async(self, base_dir: str) -> None:
        import time
        def _worker():
            base = Path(base_dir)
            base_resolved = base.resolve()
            paths: list = []
            try:
                for p in base.rglob("*"):
                    if any(part in _SKIP_DIRS for part in p.parts):
                        continue
                    if p.is_file():
                        try:
                            rel_str = str(p.relative_to(base_resolved))
                        except ValueError:
                            rel_str = p.name
                        paths.append(build_entry(rel_str, p.name))
            except PermissionError:
                pass
            ts = time.monotonic()
            wall_ts = time.time()
            _quick_run_save_disk_index(base_dir, wall_ts, paths)
            self.after(0, lambda: self._quick_run_on_index_ready(base_dir, ts, paths))
        threading.Thread(target=_worker, daemon=True).start()

    def _quick_run_on_index_ready(self, base_dir: str, ts: float, paths: list) -> None:
        self._quick_run_index_cache[base_dir] = (ts, paths)
        for gn, bar in self._quick_run_bars.items():
            if bar.get("base_dir") == base_dir:
                if self._quick_run_open_group == gn:
                    self._quick_run_refresh_suggestions(gn)

    def _quick_run_compute_suggestions(self, base_dir: str, query: str) -> list:
        max_n = self._settings.get("quick_run_max_suggestions", 10)
        index = self._quick_run_get_index(base_dir)
        if index is None:
            return []
        return rank_suggestions(index, query, max_n)

    def _quick_run_refresh_suggestions(self, group_name: str) -> None:
        if not self._settings.get("quick_run_autocomplete", True):
            return
        bar = self._quick_run_bars.get(group_name)
        if bar is None or self._quick_run_open_group != group_name:
            return
        if bar["is_placeholder"][0]:
            self._quick_run_hide_suggestions(group_name)
            return
        full = bar["var"].get().strip()
        if not full:
            self._quick_run_hide_suggestions(group_name)
            return
        head = full.split(None, 1)[0]
        if " " in full:
            self._quick_run_hide_suggestions(group_name)
            return
        base_dir = bar["base_dir"]
        cached = self._quick_run_index_cache.get(base_dir)
        if cached is None:
            self._quick_run_show_suggestions(group_name, ["Indexing files…"])
            return
        items = self._quick_run_compute_suggestions(base_dir, head)
        if not items:
            self._quick_run_hide_suggestions(group_name)
        else:
            self._quick_run_show_suggestions(group_name, items)

    def _quick_run_show_suggestions(self, group_name: str, items: list) -> None:
        bar = self._quick_run_bars.get(group_name)
        if bar is None:
            return
        entry = bar["entry"]
        win = bar.get("suggest_win")
        if win is None or not win.winfo_exists():
            win = tk.Toplevel(self)
            win.overrideredirect(True)
            win.transient(self)
            win.configure(bg=C["border"])
            lb = tk.Listbox(win, bg=C["card_bg"], fg=C["name_fg"],
                            selectbackground=C["accent"], selectforeground=C["fg_on_dark"],
                            relief="flat", bd=0, font=("Consolas", 9),
                            highlightthickness=0, activestyle="none")
            lb.pack(fill="both", expand=True, padx=1, pady=1)
            lb.bind("<ButtonRelease-1>", lambda e, g=group_name: self._quick_run_on_lb_click(g))
            bar["suggest_win"] = win
            bar["suggest_lb"] = lb
        lb = bar["suggest_lb"]
        lb.delete(0, "end")
        for item in items:
            lb.insert("end", item)
        visible = min(len(items), self._settings.get("quick_run_max_suggestions", 10))
        lb.config(height=visible)
        x = entry.winfo_rootx()
        y = entry.winfo_rooty() + entry.winfo_height()
        w = entry.winfo_width()
        win.geometry(f"{w}x{visible * 18 + 2}+{x}+{y}")
        win.deiconify()
        win.lift()
        if items and items[0] != "Indexing files…":
            lb.selection_set(0)

    def _quick_run_hide_suggestions(self, group_name: str) -> None:
        bar = self._quick_run_bars.get(group_name)
        if bar is None:
            return
        win = bar.get("suggest_win")
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
            bar["suggest_win"] = None
            bar["suggest_lb"] = None

    def _quick_run_maybe_hide_suggestions(self, group_name: str) -> None:
        bar = self._quick_run_bars.get(group_name)
        if bar is None:
            return
        try:
            focused = self.focus_get()
        except (tk.TclError, KeyError):
            return
        lb = bar.get("suggest_lb")
        if focused is not lb and focused is not bar["entry"]:
            self._quick_run_hide_suggestions(group_name)

    def _quick_run_accept_suggestion(self, group_name: str, rel: str, submit: bool) -> None:
        bar = self._quick_run_bars.get(group_name)
        if bar is None:
            return
        if submit:
            bar["var"].set(rel)
        else:
            bar["var"].set(rel + " ")
        bar["entry"].config(fg=C["name_fg"])
        bar["is_placeholder"][0] = False
        bar["entry"].icursor("end")
        self._quick_run_hide_suggestions(group_name)
        if submit:
            self._quick_run_submit(group_name)

    def _quick_run_on_lb_click(self, group_name: str) -> None:
        bar = self._quick_run_bars.get(group_name)
        if bar is None:
            return
        lb = bar.get("suggest_lb")
        if lb is None:
            return
        sel = lb.curselection()
        if sel:
            rel = lb.get(sel[0])
            if rel != "Indexing files…":
                self._quick_run_accept_suggestion(group_name, rel, submit=True)

    def _quick_run_pick(self, base_dir: str, candidates: list[str]) -> str | None:
        """Show a modal listbox for the user to pick among multiple matches. Returns relative path or None."""
        dlg = tk.Toplevel(self)
        dlg.title("Quick Run — Multiple Matches")
        dlg.configure(bg=C["bg"])
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Multiple scripts match. Pick one:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9), padx=14, pady=8).pack(anchor="w")

        lb = tk.Listbox(dlg, bg=C["card_bg"], fg=C["name_fg"], selectbackground=C["accent"],
                        selectforeground=C["fg_on_dark"], relief="flat", bd=0,
                        font=("Consolas", 9), width=60, height=min(len(candidates), 12))
        lb.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        for rel in candidates:
            lb.insert("end", rel)
        lb.selection_set(0)

        chosen: list[str | None] = [None]

        def _pick():
            sel = lb.curselection()
            if sel:
                chosen[0] = candidates[sel[0]]
            dlg.destroy()

        lb.bind("<Double-1>", lambda e: _pick())

        btn_row = tk.Frame(dlg, bg=C["bg"])
        btn_row.pack(fill="x", padx=14, pady=(0, 12))
        _flat_button(btn_row, "Cancel", C["btn_dark_bg"], C["btn_dark_hover"], dlg.destroy, width=8).pack(side="right", padx=(4, 0))
        _flat_button(btn_row, "Run", C["accent"], C["accent2"], _pick, width=8).pack(side="right")

        dlg.wait_window()
        return chosen[0]

    def _toggle_quick_run_bar(self, group_name: str):
        if self._quick_run_open_group == group_name:
            self._hide_quick_run_bar(group_name)
            return
        if self._quick_run_open_group is not None:
            self._hide_quick_run_bar(self._quick_run_open_group)
        self._show_quick_run_bar(group_name)

    def _show_quick_run_bar(self, group_name: str):
        bar = self._quick_run_bars.get(group_name)
        if not bar:
            return
        bar["var"].set("script name [params...]")
        bar["entry"].config(fg=C["path_fg"])
        bar["is_placeholder"][0] = True
        bar["frame"].pack(fill="x", padx=8, pady=(2, 0), after=bar["banner"])
        bar["entry"].focus_set()
        self._quick_run_open_group = group_name
        if self._settings.get("quick_run_autocomplete", True):
            self._quick_run_get_index(bar["base_dir"])
        btn = self._quick_run_buttons.get(group_name)
        if btn:
            try:
                btn.config(bg=C["accent2"])
            except tk.TclError:
                pass

    def _hide_quick_run_bar(self, group_name: str):
        self._quick_run_hide_suggestions(group_name)
        bar = self._quick_run_bars.get(group_name)
        if bar:
            after_id = bar.get("suggest_after_id")
            if after_id:
                self.after_cancel(after_id)
                bar["suggest_after_id"] = None
            try:
                bar["frame"].pack_forget()
            except tk.TclError:
                pass
            bar["var"].set("")
        if self._quick_run_open_group == group_name:
            self._quick_run_open_group = None
        btn = self._quick_run_buttons.get(group_name)
        if btn:
            try:
                btn.config(bg=C["accent"])
            except tk.TclError:
                pass

    def _quick_run_submit(self, group_name: str):
        bar = self._quick_run_bars.get(group_name)
        if not bar:
            return
        if bar["is_placeholder"][0]:
            return
        raw = bar["var"].get().strip()
        if not raw:
            return
        query, typed_params, params_explicitly_set = parse_input(raw)
        if not query:
            return
        base_dir = self.db.get_group_base_dir(group_name) or bar["base_dir"]
        self._hide_quick_run_bar(group_name)

        abs_path, candidates, err = resolve(base_dir, query)
        if err:
            messagebox.showerror("Quick Run", err, parent=self)
            return
        if candidates:
            chosen = self._quick_run_pick(base_dir, candidates)
            if not chosen:
                return
            abs_path = str(Path(base_dir) / chosen)

        display = display_relpath(abs_path, base_dir)

        existing_id = None
        existing_name = ""
        existing_params = ""
        existing_interp = ""
        abs_path_p = Path(abs_path)
        for rec in self.db.list_all():
            if Path(rec[2]) == abs_path_p and (rec[8] or "") == (group_name or ""):
                existing_id = rec[0]
                existing_name = rec[1]
                existing_params = rec[3] or ""
                existing_interp = rec[4] or ""
                break

        if existing_id is not None:
            script_id = existing_id
            interpreter = existing_interp
            params = typed_params if params_explicitly_set else existing_params
            if params_explicitly_set:
                presets = self.db.list_param_presets(existing_id)
                preset_values = {p[2] for p in presets}
                if typed_params not in preset_values:
                    self.db.replace_param_presets(
                        existing_id,
                        [(p[1], p[2]) for p in presets] + [(typed_params, typed_params)],
                    )
                if typed_params != existing_params:
                    self.db.update(existing_id, existing_name, abs_path, typed_params, existing_interp, group_name or "")
                self._refresh_cards()
            elif not any(c.script_id == existing_id for c in self._cards):
                self._refresh_cards()
        else:
            interpreter = detect_interpreter(abs_path)
            script_id = self.db.add(
                name=Path(abs_path).stem,
                path=abs_path,
                params=typed_params,
                interpreter=interpreter,
                group_name=group_name or "",
            )
            params = typed_params
            if typed_params:
                self.db.replace_param_presets(script_id, [(typed_params, typed_params)])
            self._refresh_cards()

        self._run_script(script_id, display, abs_path, params, interpreter)

    def _run_subprocess(self, job: "_Job", cmd, name, script_id):
        run_subprocess(self.output_queue, job, cmd, name, script_id,
                       log_output=self._settings.get("log_runs_output", False))

    def _init_all_tab(self):
        text = scrolledtext.ScrolledText(
            self._out_tab_body, wrap="word", height=10, font=("Consolas", 10),
            bg=C["out_bg"], fg=C["out_stdout"], insertbackground=C["out_stdout"],
        )
        text.tag_config("stderr", foreground=C["out_stderr"])
        text.tag_config("info",   foreground=C["out_status"])
        text.tag_config("ok",     foreground=C["out_success"])
        btn = tk.Frame(self._out_tab_bar, bg=C["out_header"], cursor="hand2")
        btn.pack(side="left", padx=(1, 0), pady=(2, 0))
        name_lbl = tk.Label(btn, text="All", bg=C["out_header"], fg=C["fg_on_dark_2"],
                            font=("Segoe UI", 9, "bold"), cursor="hand2", padx=8, pady=3)
        name_lbl.pack(side="left")
        self._output_tabs["all"] = {"text": text, "btn": btn,
                                    "name_lbl": name_lbl, "close_lbl": None}
        name_lbl.bind("<Button-1>", lambda e: self._activate_tab("all"))
        btn.bind("<Button-1>",      lambda e: self._activate_tab("all"))
        self._bind_tab_context_menu(btn, name_lbl, None, "all")
        self._active_tab_key = "all"
        text.pack(fill="both", expand=True)

    def _get_or_create_tab(self, key: str, name: str):
        all_btn = self._output_tabs["all"]["btn"]
        if key in self._output_tabs:
            tab = self._output_tabs[key]
            tab["text"].configure(state="normal")
            tab["text"].delete("1.0", tk.END)
            tab["name_lbl"].config(text=name)
            self._activate_tab(key)
        else:
            text = scrolledtext.ScrolledText(
                self._out_tab_body, wrap="word", height=10, font=("Consolas", 10),
                bg=C["out_bg"], fg=C["out_stdout"], insertbackground=C["out_stdout"],
            )
            text.tag_config("stderr", foreground=C["out_stderr"])
            text.tag_config("info",   foreground=C["out_status"])
            text.tag_config("ok",     foreground=C["out_success"])

            btn = tk.Frame(self._out_tab_bar, bg=C["out_header"], cursor="hand2")
            btn.pack(side="left", padx=(1, 0), pady=(2, 0), before=all_btn)
            name_lbl = tk.Label(btn, text=name, bg=C["out_header"], fg=C["fg_on_dark_2"],
                                font=("Segoe UI", 9), cursor="hand2", padx=8, pady=3)
            name_lbl.pack(side="left")
            close_lbl = tk.Label(btn, text="×", bg=C["out_header"], fg=C["btn_dark_hover"],
                                 font=("Segoe UI", 9), cursor="hand2", padx=4, pady=3)
            close_lbl.pack(side="left")

            self._output_tabs[key] = {"text": text, "btn": btn,
                                      "name_lbl": name_lbl, "close_lbl": close_lbl}
            name_lbl.bind("<Button-1>", lambda e, k=key: self._activate_tab(k))
            btn.bind("<Button-1>",      lambda e, k=key: self._activate_tab(k))
            close_lbl.bind("<Button-1>", lambda e, k=key: self._close_tab(k))
            self._bind_tab_context_menu(btn, name_lbl, close_lbl, key)
            self._activate_tab(key)

        if not self._out_expanded:
            self._toggle_output()

    def _bind_tab_context_menu(self, btn, name_lbl, close_lbl, key: str):
        def show(e):
            self._show_tab_context_menu(e, key)
        for w in [btn, name_lbl] + ([close_lbl] if close_lbl else []):
            w.bind("<Button-3>", show)

    def _show_tab_context_menu(self, event, key: str):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="⎘  Copy", command=lambda: self._copy_log(key))
        menu.add_command(label="💾  Save", command=lambda: self._save_log(key))
        if key != "all":
            menu.add_separator()
            menu.add_command(label="✕  Close", command=lambda: self._close_tab(key))
        menu.tk_popup(event.x_root, event.y_root)

    def _activate_tab(self, key: str):
        if self._active_tab_key and self._active_tab_key in self._output_tabs:
            old = self._output_tabs[self._active_tab_key]
            for w in [old["btn"], old["name_lbl"]] + ([old["close_lbl"]] if old["close_lbl"] else []):
                w.config(bg=C["out_header"])
            old["name_lbl"].config(fg=C["fg_on_dark_2"])
            if old["close_lbl"]:
                old["close_lbl"].config(fg=C["btn_dark_hover"])
            old["text"].pack_forget()
        self._active_tab_key = key
        tab = self._output_tabs[key]
        for w in [tab["btn"], tab["name_lbl"]] + ([tab["close_lbl"]] if tab["close_lbl"] else []):
            w.config(bg=C["out_bg"])
        tab["name_lbl"].config(fg=C["fg_on_dark"])
        if tab["close_lbl"]:
            tab["close_lbl"].config(fg="#888")
        tab["text"].pack(fill="both", expand=True)

    def _close_tab(self, key: str):
        if key == "all" or key not in self._output_tabs:
            return
        tab = self._output_tabs.pop(key)
        tab["text"].pack_forget()
        tab["text"].destroy()
        tab["btn"].destroy()
        if key == self._active_tab_key:
            self._active_tab_key = None
            self._activate_tab("all")

    def _is_tab_running(self, key: str) -> bool:
        return any(j.tab_key == key for j in self._jobreg.all())

    def _close_all_tabs(self):
        keys_to_close = [k for k in list(self._output_tabs) if k != "all" and not self._is_tab_running(k)]
        for key in keys_to_close:
            tab = self._output_tabs.pop(key)
            tab["text"].pack_forget()
            tab["text"].destroy()
            tab["btn"].destroy()
        if self._active_tab_key not in self._output_tabs:
            self._active_tab_key = None
            self._activate_tab("all")
        all_text = self._output_tabs["all"]["text"]
        all_text.configure(state="normal")
        all_text.delete("1.0", tk.END)

    def _toggle_output(self):
        if self._out_expanded:
            self._saved_sash_pos = self._paned.sashpos(0)
            self._out_tab_bar.pack_forget()
            self._out_tab_body.pack_forget()
            self._toggle_btn.config(text="▲  Show Output")
            self._out_expanded = False
            self.update_idletasks()
            h = self._paned.winfo_height()
            self._paned.sashpos(0, h - self.out_panel.winfo_reqheight())
        else:
            self._out_tab_bar.pack(fill="x")
            self._out_tab_body.pack(fill="both", expand=True)
            self._toggle_btn.config(text="▼  Hide Output")
            self._out_expanded = True
            self.update_idletasks()
            h = self._paned.winfo_height()
            sash = getattr(self, "_saved_sash_pos", max(50, h - 200))
            self._paned.sashpos(0, min(sash, h - 50))

    def _append_output(self, text: str, tag: str | None = None, tab_key: str | None = None):
        max_lines = self._settings.get("max_output_lines", 2000)
        scroll = self._settings.get("auto_scroll_output", True)
        if tab_key is not None:
            # Background job: always write to its own tab + "all"
            keys = [tab_key] if tab_key in self._output_tabs else []
            if "all" in self._output_tabs and tab_key != "all":
                keys.append("all")
        else:
            if not self._active_tab_key or self._active_tab_key not in self._output_tabs:
                return
            keys = [self._active_tab_key]
            if self._active_tab_key != "all" and "all" in self._output_tabs:
                keys.append("all")
        for k in keys:
            out_text = self._output_tabs[k]["text"]
            out_text.configure(state="normal")
            if tag:
                out_text.insert(tk.END, text, tag)
            else:
                out_text.insert(tk.END, text)
            line_count = int(out_text.index(tk.END).split(".")[0]) - 1
            if line_count > max_lines:
                out_text.delete("1.0", f"{line_count - max_lines + 1}.0")
            if scroll:
                out_text.see(tk.END)

    def _clear_log(self):
        if not self._active_tab_key or self._active_tab_key not in self._output_tabs:
            return
        out_text = self._output_tabs[self._active_tab_key]["text"]
        out_text.configure(state="normal")
        out_text.delete("1.0", tk.END)

    def _save_log(self, key: str | None = None):
        k = key or self._active_tab_key
        if not k or k not in self._output_tabs:
            self.status_var.set("Nothing to save.")
            return
        text = self._output_tabs[k]["text"].get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Nothing to save.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save output",
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.status_var.set(f"Saved to {path}")

    def _copy_log(self, key: str | None = None):
        k = key or self._active_tab_key
        if not k or k not in self._output_tabs:
            return
        text = self._output_tabs[k]["text"].get("1.0", tk.END).strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("Log copied to clipboard.")

    def _stop_all_jobs(self):
        """Stop every running job (used from on_close)."""
        for job in list(self._jobreg.all()):
            self._stop_job(job)

    def _drain_output_queue(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                kind = item[0]
                job_id = item[1]
                job = self._jobreg.get(job_id)
                if kind == "done":
                    _, _jid, sid, status, text = item
                    if job:
                        self._append_output(text, tag="info", tab_key=job.tab_key)
                    self.db.mark_run_status(sid, status)
                    if job:
                        self._handle_step_done(job, sid, status)
                elif kind == "done_tag":
                    _, _jid, sid, status, tag, text = item
                    if job:
                        self._append_output(text, tag=tag, tab_key=job.tab_key)
                    self.db.mark_run_status(sid, status)
                    if job:
                        self._handle_step_done(job, sid, status)
                elif kind == "stderr":
                    if job:
                        self._append_output(item[2], tag="stderr", tab_key=job.tab_key)
                else:  # stdout
                    if job:
                        self._append_output(item[2], tab_key=job.tab_key)
        except queue.Empty:
            pass
        self.after(80, self._drain_output_queue)

    def _handle_step_done(self, job: "_Job", sid: int, status: str):
        notify = self._settings.get("notify_on_complete", True)
        secs = (datetime.now() - job.start_time).total_seconds()
        elapsed = f"{int(secs // 60)} m {secs % 60:.0f} s" if secs >= 60 else f"{secs:.1f} s"

        if job.kind == "pipeline":
            if status == "ok" and job.pipeline_queue:
                self._run_next_pipeline_step(job)
                return
            elif status == "ok":
                self._append_output(
                    f"\n{'━' * 60}\n"
                    f"✓  Pipeline complete  ·  {datetime.now().strftime('%H:%M:%S')}\n"
                    f"{'━' * 60}\n",
                    tag="ok",
                    tab_key=job.tab_key,
                )
                self.status_var.set("Pipeline complete.")
                total = job.pipeline_total
                self._finish_job(job)
                if notify:
                    _show_notification(
                        "RYOS — Pipeline passed",
                        f"✓  {job.pipeline_name}  ·  {total} step{'s' if total != 1 else ''}  ·  {elapsed}",
                    )
            else:
                job.pipeline_queue.clear()
                self._append_output("\n[Pipeline stopped — step failed]\n", tag="stderr",
                                    tab_key=job.tab_key)
                self.status_var.set("Pipeline stopped (step failed).")
                failed_at = job.pipeline_step_idx
                total = job.pipeline_total
                self._finish_job(job)
                if notify:
                    _show_notification(
                        "RYOS — Pipeline failed",
                        f"✗  {job.pipeline_name}  ·  failed at step {failed_at}/{total}  ·  {elapsed}",
                    )
        else:
            if status == "ok":
                self.status_var.set("Done.")
                if notify:
                    _show_notification(
                        "RYOS — Script passed",
                        f"✓  {job.name}  ·  {elapsed}",
                    )
            else:
                self.status_var.set("Failed.")
                if notify:
                    _show_notification(
                        "RYOS — Script failed",
                        f"✗  {job.name}  ·  {elapsed}",
                    )
            self._finish_job(job)

    def _check_for_update(self):
        result = _fetch_latest_release()
        if result is None:
            return
        tag, url = result
        if _parse_version(tag) > _parse_version(__version__):
            self.after(0, lambda: self._show_update_banner(tag, url))

    def _show_update_banner(self, tag: str, url: str):
        if getattr(self, "_update_banner", None):
            return
        banner = tk.Frame(self, bg="#1a3a5c", pady=6, padx=12)
        banner.pack(fill="x", before=self._paned)
        self._update_banner = banner

        tk.Label(banner, text=f"🔔  Update available: {tag}  (you have v{__version__})",
                 bg="#1a3a5c", fg="#90cdf4",
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Button(banner, text="Download", bg="#2b6cb0", fg=C["fg_on_dark"],
                  activebackground="#2c5282", activeforeground=C["fg_on_dark"],
                  relief="flat", bd=0, font=("Segoe UI", 9, "bold"),
                  padx=8, pady=1, cursor="hand2",
                  command=lambda: webbrowser.open(url)).pack(side="left", padx=(10, 0))
        tk.Button(banner, text="✕", bg="#1a3a5c", fg="#90cdf4",
                  activebackground="#2a4a6c", activeforeground=C["fg_on_dark"],
                  relief="flat", bd=0, font=("Segoe UI", 9),
                  cursor="hand2",
                  command=banner.destroy).pack(side="right")

    def _manual_update_check(self):
        def _check():
            result = _fetch_latest_release()
            if result is None:
                self.after(0, lambda: messagebox.showinfo(
                    "Update Check",
                    "Could not reach GitHub. Check your internet connection.",
                    parent=self))
                return
            tag, url = result
            if _parse_version(tag) > _parse_version(__version__):
                self.after(0, lambda: self._show_update_banner(tag, url))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Up to date",
                    f"You are running the latest version ({__version__}).",
                    parent=self))
        threading.Thread(target=_check, daemon=True).start()

    def _open_advanced_options(self):
        def _apply(new_settings: dict):
            self._settings = new_settings
            _save_settings(self._settings)
            setup_logging(self._settings.get("logging_enabled", True),
                          self._settings.get("log_level", "INFO"))
            self.attributes("-topmost", self._settings["always_on_top"])
            self.geometry(f"{self._settings['window_width']}x{self._settings['window_height']}")
            corner = self._settings.get("snap_corner") or ""
            if corner and corner != "none":
                _apply_snap_corner(self, corner)
        AdvancedOptionsDialog(self, self._settings, _apply)

    def _open_log_folder(self):
        import subprocess
        from ..settings import LOG_DIR
        if sys.platform == "win32":
            os.startfile(str(LOG_DIR))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(LOG_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(LOG_DIR)])

    def _view_logs(self):
        import subprocess
        from ..settings import LOG_PATH
        if not LOG_PATH.exists():
            messagebox.showinfo("View Logs", "No log file found yet.")
            return
        if sys.platform == "win32":
            os.startfile(str(LOG_PATH))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(LOG_PATH)])
        else:
            subprocess.Popen(["xdg-open", str(LOG_PATH)])

    def _on_close(self):
        alive = [j for j in self._jobreg.all()
                 if j.current_process is not None and j.current_process.poll() is None]
        if alive:
            n = len(alive)
            label = "jobs are" if n > 1 else "job is"
            if not messagebox.askyesno("Still Running",
                                       f"{n} script {label} still running. Exit anyway?"):
                return
            for job in list(self._jobreg.all()):
                try:
                    if job.current_process is not None:
                        job.current_process.terminate()
                except OSError:
                    pass  # process may have already exited
        if self._settings["remember_window_geometry"]:
            self._settings["window_geometry"] = self.geometry()
        _save_settings(self._settings)
        self.destroy()