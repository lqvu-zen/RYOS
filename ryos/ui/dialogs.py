"""Modal dialogs: Add/Edit script, preset entry, param picker, advanced options."""
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..db import ScriptDB
from ..settings import (
    _CORNER_CHOICES,
    _CORNER_LABEL_TO_VAL,
    _CORNER_VAL_TO_LABEL,
    _SETTINGS_DEFAULTS,
)
from ..startup import _set_startup, _startup_enabled
from .theme import C, _apply_snap_corner, _flat_button


def _is_inside(path: str, base: str) -> bool:
    if not path or not base:
        return False
    norm_path = os.path.normcase(os.path.normpath(path))
    norm_base = os.path.normcase(os.path.normpath(base))
    return norm_path == norm_base or norm_path.startswith(norm_base + os.sep)


class _PresetEntryDialog(tk.Toplevel):
    """Small dialog for entering/editing a param preset value."""

    def __init__(self, parent, params: str, title: str = "Preset"):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        pad = {"padx": 6, "pady": 4}
        ttk.Label(frame, text="Parameters:").grid(row=0, column=0, sticky="w", **pad)
        self._e_params = ttk.Entry(frame, width=36)
        self._e_params.grid(row=0, column=1, sticky="ew", **pad)
        self._e_params.insert(0, params)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btn_row, text="OK",     command=self._ok).pack(side="right", padx=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right")

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(parent)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self._e_params.focus_set()

    def _ok(self):
        params = self._e_params.get().strip()
        if not params:
            messagebox.showwarning("Required", "Please enter parameters.", parent=self)
            return
        self.result = params
        self.destroy()


class ScriptDialog(tk.Toplevel):
    """Modal dialog for adding or editing a script entry."""

    def __init__(self, parent, db: ScriptDB, script_id: int | None = None,
                 on_save=None, existing_groups: list[str] | None = None,
                 default_group: str = "", group_base_dirs: dict | None = None):
        super().__init__(parent)
        self.db = db
        self.script_id = script_id
        self.on_save = on_save
        self.result = None
        self.existing_groups = existing_groups or []
        self.default_group = default_group
        self.group_base_dirs = group_base_dirs or {}

        self.title("Edit Script" if script_id else "Add Script")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        self._presets = []

        self._build()

        if script_id:
            rec = db.get(script_id)
            if rec:
                _, name, path, params, interp, grp = rec
                self.e_name.insert(0, name)
                self.e_path.insert(0, path)
                self.e_params.insert(0, params)
                self.e_interp.set(interp)
                self.e_group.set(grp or "")
            for _, label, pparams in db.list_param_presets(script_id):
                self._presets.append([label, pparams])
                self._preset_listbox.insert(tk.END, label)
        else:
            self.e_group.set(self.default_group)

        self.transient(parent)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self.wait_visibility()
        self.focus_set()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        title_strip = tk.Frame(self, bg=C["card_bg"])
        title_strip.pack(fill="x")
        tk.Label(title_strip,
                 text="Edit Script" if self.script_id else "Add Script",
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", padx=16, pady=12).pack(fill="x")
        tk.Frame(title_strip, bg=C["border"], height=1).pack(fill="x")

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Name:").grid(row=0, column=0, sticky="w", **pad)
        self.e_name = ttk.Entry(frame, width=40)
        self.e_name.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frame, text="Path:").grid(row=1, column=0, sticky="w", **pad)
        self.e_path = ttk.Entry(frame, width=40)
        self.e_path.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="Browse…", command=self._browse).grid(row=1, column=2, **pad)

        ttk.Label(frame, text="Parameters:").grid(row=2, column=0, sticky="w", **pad)
        self.e_params = ttk.Entry(frame, width=40)
        self.e_params.grid(row=2, column=1, sticky="ew", **pad)
        self.e_params.bind("<FocusOut>", self._auto_name_from_params)
        self.e_params.bind("<Return>", lambda _: self._preset_add_from_params())
        ttk.Button(frame, text="+ Preset", width=8,
                   command=self._preset_add_from_params).grid(row=2, column=2, **pad)

        ttk.Label(frame, text="Presets:").grid(row=3, column=0, sticky="nw", **pad)
        preset_frame = ttk.Frame(frame)
        preset_frame.grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        preset_frame.columnconfigure(0, weight=1)

        preset_frame.columnconfigure(0, weight=1)
        self._preset_listbox = tk.Listbox(
            preset_frame, height=4, selectmode=tk.SINGLE,
            bg="#1e1e1e", fg="#cccccc", selectbackground=C["accent"],
            selectforeground="#ffffff", relief="flat", highlightthickness=1,
            highlightbackground=C["border"], font=("Segoe UI", 9),
        )
        _preset_scroll = ttk.Scrollbar(preset_frame, orient="vertical",
                                       command=self._preset_listbox.yview)
        self._preset_listbox.configure(yscrollcommand=_preset_scroll.set)
        self._preset_listbox.grid(row=0, column=0, sticky="nsew")
        _preset_scroll.grid(row=0, column=1, sticky="ns")
        self._preset_listbox.bind("<Double-Button-1>", lambda _: self._preset_use())
        self._preset_listbox.bind("<Button-3>", self._preset_context_menu)

        ttk.Label(frame, text="Interpreter:").grid(row=4, column=0, sticky="w", **pad)
        self.e_interp = ttk.Combobox(frame, width=38, values=[
            "cmd /c", "powershell -File", "pwsh -File", "python", "node", "bash",
        ])
        self.e_interp.grid(row=4, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, text="Leave blank for auto-detection, or pick a preset", foreground="#888").grid(
            row=5, column=1, columnspan=2, sticky="w", padx=8
        )

        ttk.Label(frame, text="Group:").grid(row=6, column=0, sticky="w", **pad)
        self.e_group = ttk.Combobox(frame, values=self.existing_groups, width=38)
        self.e_group.grid(row=6, column=1, columnspan=2, sticky="ew", **pad)

        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=8, column=0, columnspan=3, sticky="ew")
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=4)

        if self.script_id:
            ttk.Button(btn_row, text="Delete", command=self._delete).pack(side="left", padx=4)

    def _preset_add_from_params(self):
        params = self.e_params.get().strip()
        if params and not any(p[1] == params for p in self._presets):
            self._presets.append([params, params])
            self._preset_listbox.insert(tk.END, params)
            self._autosave_presets(new_params=params)

    def _autosave_presets(self, new_params=None):
        if self.script_id:
            self.db.replace_param_presets(self.script_id, [(l, p) for l, p in self._presets])
            if new_params is not None:
                rec = self.db.get(self.script_id)
                if rec:
                    _, name, path, _, interp, grp = rec
                    self.db.update(self.script_id, name, path, new_params, interp, grp)
            if self.on_save:
                self.on_save()

    def _preset_context_menu(self, event):
        self._preset_listbox.selection_clear(0, tk.END)
        idx = self._preset_listbox.nearest(event.y)
        if idx < 0 or idx >= len(self._presets):
            return
        self._preset_listbox.selection_set(idx)
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg="#2d2d2d", fg="#ffffff",
                       activebackground=C["accent"], activeforeground="#ffffff",
                       font=("Segoe UI", 10))
        menu.add_command(label="← Use",  command=self._preset_use)
        menu.add_command(label="Edit",   command=self._preset_edit)
        menu.add_separator()
        menu.add_command(label="Remove", command=self._preset_remove,
                         foreground="#ff8080", activeforeground="#ff8080")
        menu.tk_popup(event.x_root, event.y_root)

    def _preset_edit(self):
        sel = self._preset_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        _, params = self._presets[idx]
        dlg = _PresetEntryDialog(self, params)
        self.wait_window(dlg)
        if dlg.result:
            new_params = dlg.result
            self._presets[idx] = [new_params, new_params]
            self._preset_listbox.delete(idx)
            self._preset_listbox.insert(idx, new_params)
            self._preset_listbox.selection_set(idx)

    def _preset_use(self):
        sel = self._preset_listbox.curselection()
        if not sel:
            return
        _, params = self._presets[sel[0]]
        self.e_params.delete(0, tk.END)
        self.e_params.insert(0, params)

    def _preset_remove(self):
        sel = self._preset_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self._presets.pop(idx)
        self._preset_listbox.delete(idx)

    def _auto_name_from_params(self, _event=None):
        if not self.e_name.get().strip():
            params = self.e_params.get().strip()
            if params:
                self.e_name.delete(0, tk.END)
                self.e_name.insert(0, params)

    def _browse(self):
        base_dir = self.group_base_dirs.get(self.e_group.get().strip(), "")
        kwargs = {}
        if base_dir:
            kwargs["initialdir"] = base_dir
        path = filedialog.askopenfilename(
            title="Select Script",
            filetypes=[("All Files", "*.*"), ("Python", "*.py"), ("Shell", "*.sh"),
                       ("Batch", "*.bat;*.cmd"), ("Executable", "*.exe")],
            **kwargs,
        )
        if path:
            self.e_path.delete(0, tk.END)
            self.e_path.insert(0, path)
            if not self.e_name.get().strip():
                self.e_name.insert(0, Path(path).stem)

    def _save(self):
        name = self.e_name.get().strip()
        path = self.e_path.get().strip()
        params = self.e_params.get().strip()
        interp = self.e_interp.get().strip()
        group_name = self.e_group.get().strip()

        if not name or (not path and not interp):
            messagebox.showwarning("Missing Info", "Name is required. Path is required when no interpreter is set.", parent=self)
            return
        if path:
            base_dir = self.group_base_dirs.get(group_name, "")
            if base_dir and not _is_inside(path, base_dir):
                messagebox.showerror(
                    "Path outside group directory",
                    f"The path\n{path}\nis outside the base directory for group '{group_name}':\n{base_dir}",
                    parent=self,
                )
                return
        if not interp and not Path(path).exists():
            if not messagebox.askyesno("Warning", f"File not found:\n{path}\n\nSave anyway?", parent=self):
                return

        if self.script_id:
            self.db.update(self.script_id, name, path, params, interp, group_name)
        else:
            self.script_id = self.db.add(name, path, params, interp, group_name)

        self.db.replace_param_presets(self.script_id, [(l, p) for l, p in self._presets])

        if self.on_save:
            self.on_save()
        self.destroy()

    def _delete(self):
        if messagebox.askyesno("Delete", "Delete this script?", parent=self):
            self.db.delete(self.script_id)
            if self.on_save:
                self.on_save()
            self.destroy()


class NewGroupDialog(tk.Toplevel):
    """Popup to enter a group name and optional base directory when creating a group."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None  # None = cancelled; (name, base_dir) on OK
        self._name_var = tk.StringVar()
        self._dir_var  = tk.StringVar()

        self.title("New Group")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        title_strip = tk.Frame(self, bg=C["card_bg"])
        title_strip.pack(fill="x")
        tk.Label(title_strip, text="New Group",
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", padx=16, pady=12).pack(fill="x")
        tk.Frame(title_strip, bg=C["border"], height=1).pack(fill="x")

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        pad = {"padx": 6, "pady": 4}
        ttk.Label(frame, text="Name:").grid(row=0, column=0, sticky="w", **pad)
        self._e_name = ttk.Entry(frame, textvariable=self._name_var, width=40)
        self._e_name.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frame, text="Base directory:").grid(row=1, column=0, sticky="w", **pad)
        self._e_dir = ttk.Entry(frame, textvariable=self._dir_var, width=34)
        self._e_dir.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="Browse…", command=self._browse).grid(row=1, column=2, **pad)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=2, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(btn_row, text="OK",     command=self._ok).pack(side="right", padx=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right")

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(parent)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self._e_name.focus_set()

    def _browse(self):
        current = self._dir_var.get().strip()
        d = filedialog.askdirectory(initialdir=current or str(Path.home()), parent=self)
        if d:
            self._dir_var.set(d)

    def _ok(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Required", "Please enter a group name.", parent=self)
            return
        self.result = (name, self._dir_var.get().strip())
        self.destroy()


class GroupBaseDirDialog(tk.Toplevel):
    """Popup to view, change, or clear a group's base directory."""

    def __init__(self, parent, group_name: str, current_dir: str = ""):
        super().__init__(parent)
        self.result = None  # None = cancelled; "" = cleared; str = new path
        self._dir_var = tk.StringVar(value=current_dir)

        self.title(f"Base Directory — {group_name}")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        title_strip = tk.Frame(self, bg=C["card_bg"])
        title_strip.pack(fill="x")
        tk.Label(title_strip, text=f"Base directory for '{group_name}'",
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", padx=16, pady=12).pack(fill="x")
        tk.Frame(title_strip, bg=C["border"], height=1).pack(fill="x")

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Directory:").grid(row=0, column=0, sticky="w", pady=(0, 4))

        path_row = ttk.Frame(frame)
        path_row.grid(row=1, column=0, sticky="ew")
        path_row.columnconfigure(0, weight=1)
        self._e_dir = ttk.Entry(path_row, textvariable=self._dir_var, width=44)
        self._e_dir.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(path_row, text="Browse…", command=self._browse).grid(row=0, column=1)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(btn_row, text="OK",     command=self._ok).pack(side="right", padx=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btn_row, text="Clear",  command=self._clear).pack(side="left")

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(parent)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self._e_dir.focus_set()

    def _browse(self):
        current = self._dir_var.get().strip()
        d = filedialog.askdirectory(initialdir=current or str(Path.home()), parent=self)
        if d:
            self._dir_var.set(d)

    def _clear(self):
        self._dir_var.set("")

    def _ok(self):
        self.result = self._dir_var.get().strip()
        self.destroy()


class ParamPickerDialog(tk.Toplevel):
    """Let the user pick which param preset to use before running a script."""

    def __init__(self, parent, script_name: str, default_params: str, presets: list):
        """presets: list of (id, label, params)"""
        super().__init__(parent)
        self.result = None
        self.title(f"Run — {script_name}")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        title_strip = tk.Frame(self, bg=C["card_bg"])
        title_strip.pack(fill="x")
        tk.Label(title_strip, text="Select parameters",
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", padx=16, pady=12).pack(fill="x")
        tk.Frame(title_strip, bg=C["border"], height=1).pack(fill="x")

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        self._choice = tk.StringVar(value="__default__")

        options = [("__default__", "Default", default_params)] + \
                  [(str(pid), lbl, prm) for pid, lbl, prm in presets]

        for val, lbl, prm in options:
            row = tk.Frame(body, bg=C["card_bg"], pady=3)
            row.pack(fill="x")
            tk.Radiobutton(
                row, variable=self._choice, value=val,
                text=lbl if lbl != prm else prm,
                bg=C["card_bg"], fg=C["name_fg"],
                selectcolor=C["card_bg"],
                activebackground=C["card_bg"],
                font=("Segoe UI", 10),
                anchor="w", cursor="hand2",
            ).pack(side="left")

        self._params_map = {val: prm for val, _, prm in options}

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        btn_row = ttk.Frame(self, padding=(16, 8))
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="▶ Run",   command=self._run).pack(side="right", padx=(4, 0))
        ttk.Button(btn_row, text="Cancel",  command=self.destroy).pack(side="right")

        self.bind("<Return>", lambda _: self._run())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(parent)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _run(self):
        self.result = self._params_map[self._choice.get()]
        self.destroy()


class AdvancedOptionsDialog(tk.Toplevel):
    def __init__(self, parent, settings: dict, on_save):
        super().__init__(parent)
        self._settings = dict(settings)
        self._on_save  = on_save
        self.title("Advanced Options")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._start_with_windows = tk.BooleanVar(value=_startup_enabled())
        self._always_on_top     = tk.BooleanVar(value=self._settings["always_on_top"])
        self._snap_corner       = tk.StringVar(
            value=_CORNER_VAL_TO_LABEL.get(self._settings.get("snap_corner") or "none", "Off"))
        self._snap_corner.trace_add("write", self._on_corner_change)
        self._remember_group    = tk.BooleanVar(value=self._settings["remember_last_group"])
        self._start_minimized   = tk.BooleanVar(value=self._settings["start_minimized"])
        self._remember_geometry = tk.BooleanVar(value=self._settings["remember_window_geometry"])
        self._win_width         = tk.StringVar(value=str(self._settings.get("window_width",  540)))
        self._win_height        = tk.StringVar(value=str(self._settings.get("window_height", 640)))
        self._max_lines         = tk.StringVar(value=str(self._settings["max_output_lines"]))
        self._auto_clear        = tk.BooleanVar(value=self._settings["auto_clear_output"])
        self._auto_scroll       = tk.BooleanVar(value=self._settings["auto_scroll_output"])
        self._auto_check_update = tk.BooleanVar(value=self._settings.get("auto_check_update", True))
        self._notify_on_complete = tk.BooleanVar(value=self._settings.get("notify_on_complete", True))

        self._build()
        self.update_idletasks()
        pw, ph = parent.winfo_rootx(), parent.winfo_rooty()
        self.geometry(f"+{pw + 60}+{ph + 60}")

    def _on_corner_change(self, *_):
        val = _CORNER_LABEL_TO_VAL.get(self._snap_corner.get(), "none")
        if val and val != "none":
            _apply_snap_corner(self.master, val)

    def _section(self, text: str) -> tk.Frame:
        tk.Label(self._body, text=text, bg=C["bg"], fg=C["accent"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(
            fill="x", padx=16, pady=(14, 2))
        sep = tk.Frame(self._body, bg=C["accent"], height=1)
        sep.pack(fill="x", padx=16, pady=(0, 6))
        frame = tk.Frame(self._body, bg=C["bg"])
        frame.pack(fill="x", padx=24, pady=2)
        return frame

    def _chk(self, parent, text: str, var: tk.BooleanVar) -> tk.Checkbutton:
        cb = tk.Checkbutton(parent, text=text, variable=var,
                            bg=C["bg"], fg=C["name_fg"],
                            selectcolor=C["card_bg"],
                            activebackground=C["bg"], activeforeground=C["name_fg"],
                            font=("Segoe UI", 9), anchor="w")
        cb.pack(fill="x", pady=2)
        return cb

    def _build(self):
        self._body = tk.Frame(self, bg=C["bg"])
        self._body.pack(fill="both", expand=True)

        f = self._section("STARTUP")
        if sys.platform == "win32":
            self._chk(f, "Start with Windows",               self._start_with_windows)
        self._chk(f, "Always on top",                     self._always_on_top)
        self._chk(f, "Remember last active group",        self._remember_group)
        self._chk(f, "Start minimized",                  self._start_minimized)
        self._chk(f, "Remember window size and position", self._remember_geometry)

        size_row = tk.Frame(f, bg=C["bg"])
        size_row.pack(fill="x", pady=(8, 2))
        vcmd_int = (self.register(lambda s: s.isdigit() or s == ""), "%P")
        tk.Label(size_row, text="Window size:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(size_row, from_=400, to=3840, increment=10,
                   textvariable=self._win_width, width=6,
                   validate="key", validatecommand=vcmd_int,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
        tk.Label(size_row, text="×", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left", padx=4)
        tk.Spinbox(size_row, from_=300, to=2160, increment=10,
                   textvariable=self._win_height, width=6,
                   validate="key", validatecommand=vcmd_int,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left")

        row = tk.Frame(f, bg=C["bg"])
        row.pack(fill="x", pady=(8, 2))
        tk.Label(row, text="Snap to screen corner:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(row, textvariable=self._snap_corner,
                     values=[l for l, _ in _CORNER_CHOICES],
                     state="readonly", width=18,
                     font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        f = self._section("OUTPUT")
        self._chk(f, "Auto-clear output before each run",        self._auto_clear)
        self._chk(f, "Auto-scroll to bottom",                     self._auto_scroll)
        self._chk(f, "Notify when script / pipeline completes",   self._notify_on_complete)
        self._chk(f, "Check for updates on startup",              self._auto_check_update)

        row = tk.Frame(f, bg=C["bg"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text="Max output lines:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        vcmd = (self.register(lambda s: s.isdigit() or s == ""), "%P")
        tk.Spinbox(row, from_=100, to=50000, increment=100,
                   textvariable=self._max_lines, width=7,
                   validate="key", validatecommand=vcmd,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        btn_row = tk.Frame(self, bg=C["bg"])
        btn_row.pack(fill="x", padx=16, pady=12)
        _flat_button(btn_row, "Cancel", "#3a3a3a", "#555",
                     self.destroy, width=10).pack(side="right", padx=(6, 0))
        _flat_button(btn_row, "Save", C["accent"], C["accent2"],
                     self._save, width=10).pack(side="right")

    def _save(self):
        try:
            max_lines = max(100, int(self._max_lines.get() or 100))
        except ValueError:
            max_lines = _SETTINGS_DEFAULTS["max_output_lines"]
        try:
            win_w = max(400, int(self._win_width.get()  or 540))
            win_h = max(300, int(self._win_height.get() or 640))
        except ValueError:
            win_w, win_h = 540, 640
        self._settings.update({
            "always_on_top":            self._always_on_top.get(),
            "snap_corner":              _CORNER_LABEL_TO_VAL.get(self._snap_corner.get(), "none"),
            "window_width":             win_w,
            "window_height":            win_h,
            "remember_last_group":      self._remember_group.get(),
            "start_minimized":          self._start_minimized.get(),
            "remember_window_geometry": self._remember_geometry.get(),
            "max_output_lines":         max_lines,
            "auto_clear_output":        self._auto_clear.get(),
            "auto_scroll_output":       self._auto_scroll.get(),
            "notify_on_complete":       self._notify_on_complete.get(),
            "auto_check_update":        self._auto_check_update.get(),
        })
        try:
            _set_startup(self._start_with_windows.get())
        except Exception as e:
            messagebox.showerror("Startup Error",
                                 f"Could not update Windows startup entry:\n{e}",
                                 parent=self)
            return
        self._on_save(self._settings)
        self.destroy()
