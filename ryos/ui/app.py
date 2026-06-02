"""Main RYOS window: header, tabs, card list, output panel, and run engine."""
import ctypes
import os
import queue
import shlex
import subprocess
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
from ..interpreter import build_command, detect_interpreter
from ..logger import get_logger, setup_logging
from ..notifications import _fetch_latest_release, _parse_version, _show_notification
from ..settings import _BASE, _NUITKA, _PACKAGED, _load_settings, _save_settings
from .cards import PipelineCard, ScriptCard
from .dialogs import AdvancedOptionsDialog, GroupBaseDirDialog, NewGroupDialog, ScriptDialog, _is_inside
from .pipeline import PipelineEditorDialog
from .theme import C, _apply_snap_corner, _flat_button

_log = get_logger("app")

_BaseWindow = TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk


class RYOSApp(_BaseWindow):
    def __init__(self):
        super().__init__()
        self.report_callback_exception = self._log_tk_exception
        if sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RYOS.RunYourOwnScripts")

        self.title("RYOS — Run Your Own Scripts")
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

        self.update_idletasks()
        w = self._settings.get("window_width",  540)
        h = self._settings.get("window_height", 640)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.current_process = None
        self.output_queue: queue.Queue = queue.Queue()
        self._cards: list[ScriptCard] = []
        self._pipeline_cards: list[PipelineCard] = []
        self._select_mode = False
        self._pipeline_queue: list = []
        self._pipeline_step_idx = 0
        self._pipeline_total = 0
        self._running_script_id: int | None = None
        self._running_pipeline_id: int | None = None
        self._run_start_time: datetime | None = None
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

        groups = self.db.list_groups()
        if self._settings["remember_last_group"] and self._settings.get("last_group") in groups:
            self._active_group: str | None = self._settings["last_group"]
        else:
            self._active_group = groups[0] if groups else None

        corner = self._settings.get("snap_corner") or ""
        if not corner or corner == "none":
            if self._settings["remember_window_geometry"] and self._settings.get("window_geometry"):
                self.geometry(self._settings["window_geometry"])

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
        header = tk.Frame(self, bg=C["header_bg"], pady=14, padx=18)
        header.pack(fill="x")
        wm = tk.Frame(header, bg=C["header_bg"])
        wm.pack(side="left")
        header_btn_size = 6
        tk.Label(wm, text="⚡", bg=C["header_bg"], fg="#FFD23F",
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(wm, text=" RYOS", bg=C["header_bg"], fg="#ffffff",
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        add_btn = _flat_button(header, "+ Script", C["accent"], C["accent2"],
                               self._add_script, width=header_btn_size)
        add_btn.config(bg=C["accent"])
        add_btn.pack(side="right")
        add_group_btn = _flat_button(header, "+ Group", "#2e7d32", "#388e3c",
                                     self._create_group, width=header_btn_size)
        add_group_btn.pack(side="right", padx=(0, 6))
        self._pipeline_btn = _flat_button(header, "+ Pipeline", "#5c4bbd", "#7060d0",
                                           self._add_pipeline, width=header_btn_size)
        self._pipeline_btn.pack(side="right", padx=(0, 6))

        self._options_menu = tk.Menu(self, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                                     activebackground=C["accent"], activeforeground="#ffffff",
                                     borderwidth=0, relief="flat")
        self._options_menu.add_command(label="☑  Select scripts",     command=self._toggle_select_mode)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="📤  Export all groups",  command=self._export_config)
        self._options_menu.add_command(label="📥  Import config",      command=self._import_config)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="⚙  Advanced options…",  command=self._open_advanced_options)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="🔔  Check for updates",  command=self._manual_update_check)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="📁  Open log folder",    command=self._open_log_folder)
        self._options_menu.add_command(label="📄  View logs",          command=self._view_logs)
        self._options_menu.add_separator()
        self._options_menu.add_command(label="🗑  Delete All",         command=self._delete_all)

        options_btn = _flat_button(header, "⚙", "#3a3a3a", "#555",
                                   self._show_options_menu, width=4)
        options_btn.pack(side="right", padx=8)
        self._options_btn = options_btn

        self._select_btn = None

        self._select_bar = tk.Frame(self, bg="#fff7e6",
                                    highlightbackground="#f3d99a", highlightthickness=1)
        self._select_bar_var = tk.StringVar(value="Tick the checkboxes next to scripts you want to delete.")
        tk.Label(self._select_bar, textvariable=self._select_bar_var,
                 bg="#fff7e6", fg="#7a4a00", font=("Segoe UI", 9),
                 padx=14, pady=5, anchor="w").pack(side="left", fill="x", expand=True)
        self._del_selected_btn = _flat_button(self._select_bar, "🗑 Delete Selected",
                                              "#5a2d2d", "#7a3d3d", self._delete_selected, width=15)
        self._del_selected_btn.pack(side="right", padx=10, pady=4)
        self._sel_all_btn = tk.Button(
            self._select_bar, text="Select All",
            bg="#fff7e6", fg="#7a4a00",
            activebackground="#f3d99a", activeforeground="#7a4a00",
            relief="flat", bd=0, padx=10, pady=5,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
            command=self._toggle_select_all,
        )
        self._sel_all_btn.bind("<Enter>", lambda e: self._sel_all_btn.config(bg="#f3d99a"))
        self._sel_all_btn.bind("<Leave>", lambda e: self._sel_all_btn.config(bg="#fff7e6"))
        self._sel_all_btn.pack(side="right", padx=4, pady=4)

        self.status_var = tk.StringVar(value="Ready.")
        self._status_bar = tk.Label(self, textvariable=self.status_var, anchor="w",
                                    bg=C["status_bg"], fg="#555", font=("Segoe UI", 8),
                                    padx=10, pady=4)
        self._status_bar.pack(fill="x", side="bottom")

        self._paned = ttk.PanedWindow(self, orient="vertical")
        self._paned.pack(fill="both", expand=True)

        cards_pane = tk.Frame(self._paned, bg=C["bg"])
        self._paned.add(cards_pane, weight=3)

        self._tab_bar = tk.Frame(cards_pane, bg=C["bg"])
        self._tab_bar.pack(fill="x", padx=12, pady=(8, 0))
        tk.Frame(cards_pane, bg=C["border"], height=1).pack(fill="x", padx=12)

        container = tk.Frame(cards_pane, bg=C["bg"])
        container.pack(fill="both", expand=True, padx=12, pady=(8, 12))

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

        self._out_expanded = False
        self.out_panel = tk.Frame(self._paned, bg="#1e1e1e")

        out_header = tk.Frame(self.out_panel, bg="#2d2d2d", pady=4, padx=10)
        out_header.pack(fill="x")
        tk.Label(out_header, text="Output", bg="#2d2d2d", fg="#aaa",
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
        self._toggle_btn = tk.Button(out_header, text="▲  Show Output", bg="#2d2d2d", fg="#aaa",
                                     activebackground="#3d3d3d", activeforeground="#fff",
                                     relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                                     command=self._toggle_output)
        self._toggle_btn.pack(side="right")
        tk.Button(out_header, text="🗑 Clear", bg="#2d2d2d", fg="#aaa",
                  activebackground="#3d3d3d", activeforeground="#fff",
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._clear_log).pack(side="right", padx=4)
        tk.Button(out_header, text="✕ Close All", bg="#2d2d2d", fg="#aaa",
                  activebackground="#3d3d3d", activeforeground="#fff",
                  relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9),
                  command=self._close_all_tabs).pack(side="right", padx=4)

        self._out_tab_bar = tk.Frame(self.out_panel, bg="#252525")
        self._out_tab_body = tk.Frame(self.out_panel, bg="#1e1e1e")
        self._init_all_tab()

        self._paned.add(self.out_panel, weight=0)

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

        hdr = tk.Frame(section_frame, bg=C["bg"], cursor="hand2")
        hdr.pack(fill="x", padx=2, pady=(6, 0))

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
            bg=C["bg"], fg="#2d3748",
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
            hover_bg = "#eef2ff"
            border   = C["card_bg"]
        else:
            btn_bg, fg, fw = "#e4e9f0", "#2d3748", "normal"
            bar_bg   = "#e4e9f0"
            hover_bg = "#d8dfe8"
            border   = "#b8c4d0"

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
            bar_bg, hover_bg, border = C["accent"], "#eef2ff", C["card_bg"]
        else:
            btn_bg, fg, fw = "#e4e9f0", "#2d3748", "normal"
            bar_bg, hover_bg, border = "#e4e9f0", "#d8dfe8", "#b8c4d0"
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
                pbtn.config(bg=C["card_bg"] if self._active_group == pname else "#e4e9f0")
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
        menu = tk.Menu(self, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="✏  Rename", command=lambda: self._rename_group(group))
        menu.add_command(label="📋  Clone Group", command=lambda: self._clone_group(group))
        menu.add_command(label="📁  Base directory…", command=lambda: self._manage_group_base_dir(group))
        menu.add_command(label="📤  Export group", command=lambda: self._export_config(group_name=group))
        menu.add_separator()
        menu.add_command(label="🗑  Delete Group", command=lambda: self._delete_group(group),
                         foreground="#ff8080", activeforeground="#ff8080")
        menu.tk_popup(event.x_root, event.y_root)

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
                _gn = gname
                qr_btn = _flat_button(banner, "⚡", C["accent"], C["accent2"],
                                      lambda g=_gn: self._toggle_quick_run_bar(g),
                                      width=4)
                qr_btn.pack(side="right", padx=(0, 6))
                if self._running_script_id is not None or self._running_pipeline_id is not None:
                    qr_btn.config(state="disabled")
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
                _flat_button(bar_frame, "✕", "#3a3a3a", "#555",
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

            _open = lambda e, g=gname: self._manage_group_base_dir(g)
            for w in (banner, icon_lbl, path_lbl):
                w.bind("<Button-1>", _open)

            pipe_content = self._make_section_header(
                self.cards_frame, gname, "pipelines", "Pipelines"
            )
            pipelines = self.db.list_pipelines(gname)
            if pipelines:
                for p_id, p_name in pipelines:
                    pc = PipelineCard(
                        pipe_content, p_id, p_name, self.db,
                        group_name=gname,
                        on_run=self._run_pipeline,
                        on_edit=self._edit_pipeline,
                        on_refresh=self._refresh_cards,
                        on_stop=self._stop_running,
                        is_running=(p_id == self._running_pipeline_id),
                    )
                    pc.pack(fill="x", pady=5, ipady=2)
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
                        on_stop         = self._stop_running,
                        is_running      = (sid == self._running_script_id),
                        group_base_dir  = group_base_dir,
                    )
                    card.pack(fill="x", pady=5, ipady=2)
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
                 bg=C["accent"], fg="#ffffff",
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
        if self.current_process and self.current_process.poll() is None:
            messagebox.showinfo("Already Running",
                                "A script is already running. Stop it first.",
                                parent=self)
            return
        steps = self.db.list_pipeline_steps(pipeline_id)
        if not steps:
            messagebox.showinfo("Empty Pipeline",
                                "This pipeline has no steps.\nClick ⚙ to add scripts.",
                                parent=self)
            return
        self._pipeline_queue = list(steps)
        self._pipeline_step_idx = 0
        self._pipeline_total = len(steps)
        self._running_pipeline_id = pipeline_id
        self._running_pipeline_name = pipeline_name
        self._running_script_id = None
        self._run_start_time = datetime.now()
        for _pc in self._pipeline_cards:
            _pc.set_running(_pc.pipeline_id == pipeline_id,
                            self._stop_running if _pc.pipeline_id == pipeline_id else None)
        for _c in self._cards:
            _c.set_running(False)
        self._get_or_create_tab(f"pipeline:{pipeline_id}", f"⚡ {pipeline_name}")
        self._append_output(
            f"\n{'━' * 60}\n"
            f"⚡  {pipeline_name}  ·  {self._pipeline_total} step"
            f"{'s' if self._pipeline_total != 1 else ''}\n"
            f"{'━' * 60}\n\n",
            tag="info",
        )
        self._run_next_pipeline_step()

    def _run_next_pipeline_step(self):
        if not self._pipeline_queue:
            return
        step_id, sid, name, path, params, interp, params_override = self._pipeline_queue.pop(0)
        if params_override is not None:
            params = params_override
        self._pipeline_step_idx += 1
        n, total = self._pipeline_step_idx, self._pipeline_total
        self._append_output(
            f"{'─' * 40}\nStep {n}/{total}:  {name}\n{'─' * 40}\n",
            tag="info",
        )
        self.status_var.set(f"Pipeline step {n}/{total}: {name}")
        if not Path(path).exists():
            self.output_queue.put(("stderr", f"[ERROR] File not found: {path}\n"))
            self.output_queue.put(("done", sid, "error", ""))
            return
        final_interp = interp if interp.strip() else detect_interpreter(path)
        try:
            cmd = build_command(path, params, final_interp)
        except ValueError as e:
            self.output_queue.put(("stderr", f"[ERROR] Parameter error: {e}\n"))
            self.output_queue.put(("done", sid, "error", ""))
            return
        self.db.mark_run(sid)
        self._running_script_id = sid
        for _c in self._cards:
            _c.set_running(_c.script_id == sid,
                           self._stop_running if _c.script_id == sid else None)
        threading.Thread(
            target=self._run_subprocess, args=(cmd, name, sid), daemon=True,
        ).start()

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

    def _run_script(self, script_id, name, path, params, interpreter):
        if self.current_process and self.current_process.poll() is None:
            messagebox.showinfo("Already Running",
                                "A script is already running. Wait for it to finish or close its output window.")
            return

        if not Path(path).exists():
            messagebox.showerror("File Not Found", f"File does not exist:\n{path}")
            return

        final_interp = interpreter if interpreter.strip() else detect_interpreter(path)
        try:
            cmd = build_command(path, params, final_interp)
        except ValueError as e:
            messagebox.showerror("Parameter Error", f"Could not parse parameters:\n{e}")
            return

        _log.info("Run: %s | cmd: %s", name, " ".join(cmd))
        self._get_or_create_tab(f"script:{script_id}", name)
        self._append_output(
            f"\n{'━'*60}\n"
            f"  ▶  {name}\n"
            f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}    {' '.join(cmd)}\n"
            f"{'━'*60}\n\n",
            tag="info",
        )
        self.status_var.set(f"Running: {name}")
        self.db.mark_run(script_id)
        self._running_script_id = script_id
        self._running_script_name = name
        self._running_pipeline_id = None
        self._run_start_time = datetime.now()
        for _c in self._cards:
            _c.set_running(_c.script_id == script_id,
                           self._stop_running if _c.script_id == script_id else None)
        for _pc in self._pipeline_cards:
            _pc.set_running(False)
        self._set_quick_run_enabled(False)

        thread = threading.Thread(
            target=self._run_subprocess, args=(cmd, name, script_id), daemon=True
        )
        thread.start()

    def _quick_run_resolve(self, base_dir: str, query: str) -> tuple[str | None, list[str], str]:
        """Search base_dir for a script matching query (exact stem, case-insensitive).

        Returns:
            (abs_path, [], "")         — exactly one match
            (None, [rel, ...], "")     — multiple matches (caller shows disambiguation)
            (None, [], error_msg)      — zero matches or path error
        """
        query = query.strip()
        if not query:
            return None, [], "Please enter a script name."

        base = Path(base_dir)

        if os.sep in query or "/" in query or (Path(query).suffix and Path(query).suffix != query):
            candidate = (base / query).resolve()
            if not _is_inside(str(candidate), base_dir):
                return None, [], f"Path '{query}' is outside the base directory."
            if not candidate.exists():
                return None, [], f"File not found:\n{candidate}"
            return str(candidate), [], ""

        query_lower = query.lower()
        _SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}

        matches: list[Path] = []
        try:
            for p in base.rglob("*"):
                if any(part in _SKIP for part in p.parts):
                    continue
                if p.is_file() and p.stem.lower() == query_lower:
                    matches.append(p)
        except PermissionError:
            pass

        if not matches:
            return None, [], f"No script found matching '{query}' in:\n{base_dir}"
        if len(matches) == 1:
            return str(matches[0]), [], ""
        base_resolved = base.resolve()
        rels = [str(m.relative_to(base_resolved)) for m in matches]
        return None, rels, ""

    def _quick_run_get_index(self, base_dir: str) -> list | None:
        cached = self._quick_run_index_cache.get(base_dir)
        if cached is not None:
            return cached[1]
        self._quick_run_build_index_async(base_dir)
        return None

    def _quick_run_build_index_async(self, base_dir: str) -> None:
        import time
        _SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}
        def _worker():
            base = Path(base_dir)
            base_resolved = base.resolve()
            paths: list = []
            try:
                for p in base.rglob("*"):
                    if any(part in _SKIP for part in p.parts):
                        continue
                    if p.is_file():
                        try:
                            rel_str = str(p.relative_to(base_resolved))
                        except ValueError:
                            rel_str = p.name
                        paths.append((rel_str, p.name.lower(), p.stem.lower(), rel_str.lower()))
            except PermissionError:
                pass
            ts = time.monotonic()
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
        q = query.lower()
        results = []
        for entry in index:
            rel, name_lower, stem_lower, rel_lower = entry
            if stem_lower == q:
                tier = 0
            elif stem_lower.startswith(q):
                tier = 1
            elif name_lower.startswith(q):
                tier = 2
            elif name_lower.find(q) != -1:
                tier = 3
            elif rel_lower.find(q) != -1:
                tier = 4
            else:
                continue
            results.append((tier, len(stem_lower), rel))
        results.sort(key=lambda x: (x[0], x[1], x[2]))
        return [r[2] for r in results[:max_n]]

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
                            selectbackground=C["accent"], selectforeground="#fff",
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
                        selectforeground="#fff", relief="flat", bd=0,
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
        _flat_button(btn_row, "Cancel", "#3a3a3a", "#555", dlg.destroy, width=8).pack(side="right", padx=(4, 0))
        _flat_button(btn_row, "Run", C["accent"], C["accent2"], _pick, width=8).pack(side="right")

        dlg.wait_window()
        return chosen[0]

    def _set_quick_run_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for btn in self._quick_run_buttons.values():
            try:
                btn.config(state=state)
            except tk.TclError:
                pass
        if not enabled and self._quick_run_open_group is not None:
            self._hide_quick_run_bar(self._quick_run_open_group)

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
        if self.current_process and self.current_process.poll() is None:
            messagebox.showinfo("Already Running",
                                "A script is already running. Wait for it to finish.",
                                parent=self)
            return
        bar = self._quick_run_bars.get(group_name)
        if not bar:
            return
        if bar["is_placeholder"][0]:
            return
        raw = bar["var"].get().strip()
        if not raw:
            return
        try:
            tokens = shlex.split(raw, posix=(os.name != "nt"))
        except ValueError:
            tokens = raw.split()
        query = tokens[0] if tokens else ""
        typed_params = " ".join(tokens[1:])
        params_explicitly_set = len(tokens) >= 2
        if not query:
            return
        base_dir = self.db.get_group_base_dir(group_name) or bar["base_dir"]
        self._hide_quick_run_bar(group_name)

        abs_path, candidates, err = self._quick_run_resolve(base_dir, query)
        if err:
            messagebox.showerror("Quick Run", err, parent=self)
            return
        if candidates:
            chosen = self._quick_run_pick(base_dir, candidates)
            if not chosen:
                return
            abs_path = str(Path(base_dir) / chosen)

        try:
            display = str(Path(abs_path).relative_to(Path(base_dir).resolve()))
        except ValueError:
            display = Path(abs_path).name

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

    def _run_subprocess(self, cmd, name, script_id):
        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                cwd=str(Path(next((c for c in cmd if Path(c).is_file()), cmd[0])).parent),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except FileNotFoundError as e:
            _log.error("Interpreter/file not found for %s: %s", name, e)
            self.output_queue.put(("stderr", f"[ERROR] {e}\n"))
            self.output_queue.put(("done", script_id, "error", f"❌ Interpreter/file not found: {name}\n"))
            return
        except Exception as e:
            _log.error("Failed to launch %s: %s", name, e)
            self.output_queue.put(("stderr", f"[ERROR] {e}\n"))
            self.output_queue.put(("done", script_id, "error", f"❌ Error: {name}\n"))
            return

        assert self.current_process.stdout is not None
        log_output = self._settings.get("log_runs_output", False)
        for line in self.current_process.stdout:
            self.output_queue.put(("stdout", line))
            if log_output:
                _log.debug("[%s] %s", name, line.rstrip())

        self.current_process.wait()
        rc = self.current_process.returncode
        tag = "ok" if rc == 0 else "stderr"
        status = "ok" if rc == 0 else "error"
        if rc == 0:
            _log.info("Done: %s | exit=%s", name, rc)
        else:
            _log.error("Done: %s | exit=%s", name, rc)
        self.output_queue.put((
            "done_tag", script_id, status, tag,
            f"\n  exit code {rc}  ·  {datetime.now().strftime('%H:%M:%S')}\n",
        ))

    def _init_all_tab(self):
        text = scrolledtext.ScrolledText(
            self._out_tab_body, wrap="word", height=10, font=("Consolas", 10),
            bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc",
        )
        text.tag_config("stderr", foreground="#ff8080")
        text.tag_config("info",   foreground="#7ec0ee")
        text.tag_config("ok",     foreground="#90ee90")
        btn = tk.Frame(self._out_tab_bar, bg="#2d2d2d", cursor="hand2")
        btn.pack(side="left", padx=(1, 0), pady=(2, 0))
        name_lbl = tk.Label(btn, text="All", bg="#2d2d2d", fg="#aaa",
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
                bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc",
            )
            text.tag_config("stderr", foreground="#ff8080")
            text.tag_config("info",   foreground="#7ec0ee")
            text.tag_config("ok",     foreground="#90ee90")

            btn = tk.Frame(self._out_tab_bar, bg="#2d2d2d", cursor="hand2")
            btn.pack(side="left", padx=(1, 0), pady=(2, 0), before=all_btn)
            name_lbl = tk.Label(btn, text=name, bg="#2d2d2d", fg="#aaa",
                                font=("Segoe UI", 9), cursor="hand2", padx=8, pady=3)
            name_lbl.pack(side="left")
            close_lbl = tk.Label(btn, text="×", bg="#2d2d2d", fg="#555",
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
                w.config(bg="#2d2d2d")
            old["name_lbl"].config(fg="#aaa")
            if old["close_lbl"]:
                old["close_lbl"].config(fg="#555")
            old["text"].pack_forget()
        self._active_tab_key = key
        tab = self._output_tabs[key]
        for w in [tab["btn"], tab["name_lbl"]] + ([tab["close_lbl"]] if tab["close_lbl"] else []):
            w.config(bg="#1e1e1e")
        tab["name_lbl"].config(fg="#ffffff")
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
        if key.startswith("script:"):
            return self._running_script_id == int(key.split(":")[1])
        if key.startswith("pipeline:"):
            return self._running_pipeline_id == int(key.split(":")[1])
        return False

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

    def _append_output(self, text: str, tag: str | None = None):
        if not self._active_tab_key or self._active_tab_key not in self._output_tabs:
            return
        keys = [self._active_tab_key]
        if self._active_tab_key != "all" and "all" in self._output_tabs:
            keys.append("all")
        max_lines = self._settings.get("max_output_lines", 2000)
        scroll = self._settings.get("auto_scroll_output", True)
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

    def _stop_running(self):
        self._pipeline_queue.clear()
        self._pipeline_total = 0
        self._running_pipeline_id = None
        self._running_script_id = None
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()
            self._append_output("\n[STOPPED by user]\n", tag="stderr")
            self.status_var.set("Stopped.")
        else:
            self.status_var.set("No script is currently running.")
        self._clear_running_state()

    def _drain_output_queue(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item[0] == "done":
                    _, sid, status, text = item
                    self._append_output(text, tag="info")
                    self.db.mark_run_status(sid, status)
                    self._handle_step_done(status)
                elif item[0] == "done_tag":
                    _, sid, status, tag, text = item
                    self._append_output(text, tag=tag)
                    self.db.mark_run_status(sid, status)
                    self._handle_step_done(status)
                elif item[0] == "stderr":
                    self._append_output(item[1], tag="stderr")
                else:
                    self._append_output(item[1])
        except queue.Empty:
            pass
        self.after(80, self._drain_output_queue)

    def _clear_running_state(self):
        for _c in self._cards:
            _c.set_running(False)
        for _pc in self._pipeline_cards:
            _pc.set_running(False)

    def _handle_step_done(self, status: str):
        notify = self._settings.get("notify_on_complete", True)
        elapsed = ""
        if self._run_start_time:
            secs = (datetime.now() - self._run_start_time).total_seconds()
            elapsed = f"{int(secs // 60)} m {secs % 60:.0f} s" if secs >= 60 else f"{secs:.1f} s"

        if self._pipeline_total > 0:
            if status == "ok" and self._pipeline_queue:
                self._run_next_pipeline_step()
                return  # pipeline continues; Quick Run bar stays disabled
            elif status == "ok":
                self._append_output(
                    f"\n{'━' * 60}\n"
                    f"✓  Pipeline complete  ·  {datetime.now().strftime('%H:%M:%S')}\n"
                    f"{'━' * 60}\n",
                    tag="ok",
                )
                self.status_var.set("Pipeline complete.")
                name = getattr(self, "_running_pipeline_name", "Pipeline")
                total = self._pipeline_total
                self._pipeline_total = 0
                self._running_pipeline_id = None
                self._running_script_id = None
                self._clear_running_state()
                if notify:
                    _show_notification(
                        "RYOS — Pipeline passed",
                        f"✓  {name}  ·  {total} step{'s' if total != 1 else ''}  ·  {elapsed}",
                    )
            else:
                self._pipeline_queue.clear()
                self._append_output("\n[Pipeline stopped — step failed]\n", tag="stderr")
                self.status_var.set("Pipeline stopped (step failed).")
                name = getattr(self, "_running_pipeline_name", "Pipeline")
                failed_at = getattr(self, "_pipeline_step_idx", 1)
                total = self._pipeline_total
                self._pipeline_total = 0
                self._running_pipeline_id = None
                self._running_script_id = None
                self._clear_running_state()
                if notify:
                    _show_notification(
                        "RYOS — Pipeline failed",
                        f"✗  {name}  ·  failed at step {failed_at}/{total}  ·  {elapsed}",
                    )
        else:
            name = getattr(self, "_running_script_name", "Script")
            self._running_script_id = None
            if status == "ok":
                self.status_var.set("Done.")
                if notify:
                    _show_notification(
                        "RYOS — Script passed",
                        f"✓  {name}  ·  {elapsed}",
                    )
            else:
                self.status_var.set("Failed.")
                if notify:
                    _show_notification(
                        "RYOS — Script failed",
                        f"✗  {name}  ·  {elapsed}",
                    )
            self._clear_running_state()
        self._set_quick_run_enabled(True)

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
        tk.Button(banner, text="Download", bg="#2b6cb0", fg="#ffffff",
                  activebackground="#2c5282", activeforeground="#ffffff",
                  relief="flat", bd=0, font=("Segoe UI", 9, "bold"),
                  padx=8, pady=1, cursor="hand2",
                  command=lambda: webbrowser.open(url)).pack(side="left", padx=(10, 0))
        tk.Button(banner, text="✕", bg="#1a3a5c", fg="#90cdf4",
                  activebackground="#2a4a6c", activeforeground="#ffffff",
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
        if self.current_process and self.current_process.poll() is None:
            if not messagebox.askyesno("Still Running", "A script is still running. Exit anyway?"):
                return
            try:
                self.current_process.terminate()
            except Exception:
                pass
        if self._settings["remember_window_geometry"]:
            self._settings["window_geometry"] = self.geometry()
        if self._settings["remember_last_group"]:
            self._settings["last_group"] = self._active_group
        _save_settings(self._settings)
        self.destroy()
