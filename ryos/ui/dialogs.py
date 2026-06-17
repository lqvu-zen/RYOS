"""Modal dialogs: Add/Edit script, preset entry, param picker, advanced options."""
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..db import ScriptDB
from ..settings import (
    _CORNER_CHOICES,
    _CORNER_LABEL_TO_VAL,
    _CORNER_VAL_TO_LABEL,
    _SETTINGS_DEFAULTS,
)
from ..startup import _set_startup, _startup_enabled
from ..quickrun import _is_inside
from .theme import C, THEMES, _apply_snap_corner, _flat_button


def _relative_under_base(path: str, base: str) -> str | None:
    """Return the relative path string if path is inside base, else None."""
    if not path or not base:
        return None
    norm_path = os.path.normcase(os.path.normpath(path))
    norm_base = os.path.normcase(os.path.normpath(base))
    if norm_path == norm_base or not norm_path.startswith(norm_base + os.sep):
        return None
    return os.path.normpath(path)[len(os.path.normpath(base)):].lstrip(os.sep)


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


class _TempParamDialog(tk.Toplevel):
    """One-time parameter prompt shown before a run; nothing is saved.

    An empty value is allowed (the script just runs with its saved params).
    ``cancelled`` distinguishes Cancel/closing the window from an empty OK.
    """

    def __init__(self, parent, saved_params: str = "", title: str = "Temporary Parameter"):
        super().__init__(parent)
        self.result = ""
        self.cancelled = True
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        pad = {"padx": 6, "pady": 4}
        if saved_params:
            ttk.Label(frame, text=f"Saved params: {saved_params}",
                      foreground="#888").grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(frame, text="Temp param:").grid(row=1, column=0, sticky="w", **pad)
        self._e_params = ttk.Entry(frame, width=36)
        self._e_params.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Label(frame, text="Used for this run only — not saved. Appended to saved params.",
                  foreground="#888").grid(row=2, column=0, columnspan=2, sticky="w", **pad)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btn_row, text="Run",    command=self._ok).pack(side="right", padx=(4, 0))
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
        self.result = self._e_params.get().strip()
        self.cancelled = False
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
        self._current_base_dir = ""

        self.title("Edit Script" if script_id else "Add Script")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["card_bg"])

        self._presets = []

        self._build()

        if script_id:
            rec = db.get(script_id)
            if rec:
                _, name, path, params, interp, grp, temp_param = rec
                self.e_name.insert(0, name)
                self.e_path.insert(0, path)
                self.e_params.insert(0, params)
                self.e_interp.set(interp)
                self.e_group.set(grp or "")
                self.temp_param_var.set(bool(temp_param))
            for _, label, pparams in db.list_param_presets(script_id):
                self._presets.append([label, pparams])
                self._preset_listbox.insert(tk.END, label)
            self._refresh_path_inputs()
        else:
            self.e_group.set(self.default_group)
            self._refresh_path_inputs()

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

        self._path_frame = ttk.Frame(frame)
        self._path_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        self._path_frame.columnconfigure(1, weight=1)

        self._lbl_path = ttk.Label(self._path_frame, text="Path:")
        self.e_path = ttk.Entry(self._path_frame, width=40)
        self._btn_browse_full = ttk.Button(self._path_frame, text="Browse…", command=self._browse)

        self._lbl_basedir_label = ttk.Label(self._path_frame, text="Base dir:")
        self._lbl_basedir_val = ttk.Label(self._path_frame, text="", foreground="#888",
                                          wraplength=300, anchor="w")
        self._lbl_relpath = ttk.Label(self._path_frame, text="Path:")
        self.e_relpath = ttk.Entry(self._path_frame, width=40)
        self._btn_browse_basedir = ttk.Button(self._path_frame, text="Browse…", command=self._browse)

        for w in (self._lbl_path, self.e_path, self._btn_browse_full,
                  self._lbl_basedir_label, self._lbl_basedir_val,
                  self._lbl_relpath, self.e_relpath, self._btn_browse_basedir):
            w.grid_remove()

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

        self._preset_listbox = tk.Listbox(
            preset_frame, height=4, selectmode=tk.SINGLE,
            bg=C["out_bg"], fg="#cccccc", selectbackground=C["accent"],
            selectforeground=C["fg_on_dark"], relief="flat", highlightthickness=1,
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
        self.e_group.bind("<<ComboboxSelected>>", lambda _: self._refresh_path_inputs())
        self.e_group.bind("<FocusOut>", lambda _: self._refresh_path_inputs())

        self.temp_param_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, variable=self.temp_param_var,
            text="Ask for a temporary parameter on each run (not saved)",
        ).grid(row=7, column=1, columnspan=2, sticky="w", **pad)

        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=8, column=0, columnspan=3, sticky="ew", pady=8)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=9, column=0, columnspan=3, sticky="ew")
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=4)

        if self.script_id:
            ttk.Button(btn_row, text="Delete", command=self._delete).pack(side="left", padx=4)

        self._refresh_path_inputs()

    def _refresh_path_inputs(self):
        pad = {"padx": 8, "pady": 4}
        base_dir = self.group_base_dirs.get(self.e_group.get().strip(), "")

        if base_dir:
            if self.e_relpath.winfo_ismapped() and self._current_base_dir:
                relpath_val = self.e_relpath.get().strip()
                if relpath_val:
                    candidate = os.path.normpath(os.path.join(self._current_base_dir, relpath_val))
                else:
                    candidate = self.e_path.get().strip()
            else:
                candidate = self.e_path.get().strip()

            rel = _relative_under_base(candidate, base_dir)
            self.e_relpath.delete(0, tk.END)
            self.e_relpath.insert(0, rel if rel is not None else (os.path.basename(candidate) if candidate else ""))
            self.e_path.delete(0, tk.END)

            self._lbl_basedir_val.configure(text=base_dir)
            self._current_base_dir = base_dir

            self._lbl_path.grid_remove()
            self.e_path.grid_remove()
            self._btn_browse_full.grid_remove()

            self._lbl_basedir_label.grid(row=0, column=0, sticky="w", **pad)
            self._lbl_basedir_val.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
            self._lbl_relpath.grid(row=1, column=0, sticky="w", **pad)
            self.e_relpath.grid(row=1, column=1, sticky="ew", **pad)
            self._btn_browse_basedir.grid(row=1, column=2, **pad)
        else:
            if self.e_relpath.winfo_ismapped() and self._current_base_dir:
                relpath_val = self.e_relpath.get().strip()
                if relpath_val and not self.e_path.get().strip():
                    self.e_path.delete(0, tk.END)
                    self.e_path.insert(0, os.path.normpath(os.path.join(self._current_base_dir, relpath_val)))

            self._current_base_dir = ""

            self._lbl_basedir_label.grid_remove()
            self._lbl_basedir_val.grid_remove()
            self._lbl_relpath.grid_remove()
            self.e_relpath.grid_remove()
            self._btn_browse_basedir.grid_remove()

            self._lbl_path.grid(row=0, column=0, sticky="w", **pad)
            self.e_path.grid(row=0, column=1, sticky="ew", **pad)
            self._btn_browse_full.grid(row=0, column=2, **pad)

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
                    _, name, path, _, interp, grp, _temp = rec
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
                       bg=C["menu_bg"], fg=C["fg_on_dark"],
                       activebackground=C["accent"], activeforeground=C["fg_on_dark"],
                       font=("Segoe UI", 10))
        menu.add_command(label="← Use",  command=self._preset_use)
        menu.add_command(label="Edit",   command=self._preset_edit)
        menu.add_separator()
        menu.add_command(label="Remove", command=self._preset_remove,
                         foreground=C["menu_danger"], activeforeground=C["menu_danger"])
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
                       ("Batch", "*.bat;*.cmd"), ("Executable", "*.exe"),
                       ("VS Solution", "*.sln"), ("VS Code Workspace", "*.code-workspace")],
            **kwargs,
        )
        if not path:
            return

        if base_dir and self.e_relpath.winfo_ismapped():
            if not _is_inside(path, base_dir):
                messagebox.showerror(
                    "Path outside group directory",
                    f"The selected file\n{path}\nis outside the base directory:\n{base_dir}",
                    parent=self,
                )
                return
            rel = _relative_under_base(path, base_dir)
            self.e_relpath.delete(0, tk.END)
            self.e_relpath.insert(0, rel or "")
            if not self.e_name.get().strip():
                self.e_name.insert(0, Path(path).stem)
        else:
            self.e_path.delete(0, tk.END)
            self.e_path.insert(0, path)
            if not self.e_name.get().strip():
                self.e_name.insert(0, Path(path).stem)

    def _save(self):
        name = self.e_name.get().strip()
        params = self.e_params.get().strip()
        interp = self.e_interp.get().strip()
        group_name = self.e_group.get().strip()
        base_dir = self.group_base_dirs.get(group_name, "")

        if base_dir and self.e_relpath.winfo_ismapped():
            relpath = self.e_relpath.get().strip().lstrip(os.sep + "/")
            path = os.path.normpath(os.path.join(base_dir, relpath)) if relpath else ""
        else:
            path = self.e_path.get().strip()

        if not name or (not path and not interp):
            messagebox.showwarning("Missing Info", "Name is required. Path is required when no interpreter is set.", parent=self)
            return
        if path:
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

        temp_param = int(self.temp_param_var.get())
        if self.script_id:
            self.db.update(self.script_id, name, path, params, interp, group_name, temp_param)
        else:
            self.script_id = self.db.add(name, path, params, interp, group_name, temp_param)

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
    """Tabbed settings dialog grouping every preference by topic.

    Appearance (theme / accent / cards) is merged in here too. It keeps the
    live-preview behaviour of the old standalone Appearance dialog via
    ``on_appearance``; all other settings persist together through ``on_save``.
    """

    # Remembered across opens within a session so reopening lands on the
    # same tab the user last looked at.
    _last_tab = 0

    def __init__(self, parent, settings: dict, on_save, on_appearance=None,
                 jobs_running: bool = False):
        super().__init__(parent)
        self._settings = dict(settings)
        self._on_save  = on_save
        # on_appearance(appearance_subset, persist) applies theme/cards live and
        # rebuilds the UI. When jobs are running a rebuild would disrupt them, so
        # the Appearance tab is disabled and this callback is never fired.
        self._on_appearance = on_appearance
        self._jobs_running = jobs_running
        self.title("Advanced Options")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Appearance
        self._theme     = tk.StringVar(value=self._settings.get("theme", "light"))
        self._accent    = self._settings.get("accent_color")
        self._compact   = tk.BooleanVar(value=self._settings.get("compact_mode", False))
        self._card_size = tk.StringVar(value=self._settings.get("card_size", "medium"))
        self._original_appearance = self._appearance_subset()

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
        self._max_parallel      = tk.StringVar(value=str(self._settings.get("max_parallel_jobs", 10)))
        self._auto_clear        = tk.BooleanVar(value=self._settings["auto_clear_output"])
        self._auto_scroll       = tk.BooleanVar(value=self._settings["auto_scroll_output"])
        self._auto_check_update = tk.BooleanVar(value=self._settings.get("auto_check_update", True))
        self._notify_on_complete = tk.BooleanVar(value=self._settings.get("notify_on_complete", True))
        self._quick_run_enabled = tk.BooleanVar(value=self._settings.get("quick_run_enabled", True))
        self._quick_run_autocomplete = tk.BooleanVar(value=self._settings.get("quick_run_autocomplete", True))
        self._qr_index_exts = tk.StringVar(
            value=" ".join(self._settings.get("quick_run_index_extensions") or []))
        self._qr_index_max_files = tk.StringVar(
            value=str(self._settings.get("quick_run_index_max_files", 5000)))
        self._logging_enabled = tk.BooleanVar(value=self._settings.get("logging_enabled", True))
        self._log_level = tk.StringVar(value=self._settings.get("log_level", "INFO"))
        self._log_runs_output = tk.BooleanVar(value=self._settings.get("log_runs_output", False))

        self._build()
        self.update_idletasks()
        pw, ph = parent.winfo_rootx(), parent.winfo_rooty()
        self.geometry(f"+{pw + 60}+{ph + 60}")

        # Live-preview appearance changes (skipped while jobs run — see __init__).
        # A theme switch changes the palette, so the dialog re-themes itself too;
        # compact / card-size only affect the cards, so they don't.
        if self._on_appearance is not None and not self._jobs_running:
            self._theme.trace_add("write", lambda *_: self._live_appearance(retheme=True))
            self._compact.trace_add("write", lambda *_: self._live_appearance())
            self._card_size.trace_add("write", lambda *_: self._live_appearance())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    # ------------------------------------------------------------------
    # Appearance helpers
    # ------------------------------------------------------------------

    def _appearance_subset(self) -> dict:
        return {
            "theme":        self._theme.get(),
            "accent_color": self._accent,
            "compact_mode": self._compact.get(),
            "card_size":    self._card_size.get(),
        }

    def _current_accent_hex(self) -> str:
        return self._accent if self._accent else THEMES[self._theme.get()]["accent"]

    def _refresh_swatch(self) -> None:
        self._swatch.configure(bg=self._current_accent_hex())

    def _live_appearance(self, retheme: bool = False) -> None:
        if self._on_appearance is not None:
            self._on_appearance(self._appearance_subset(), persist=False)
        # Rebuild the dialog's own widgets onto the new palette. Deferred so we
        # don't destroy the widget whose callback we're inside (crashes Tcl).
        if retheme:
            self.after(0, self._retheme_dialog)

    def _retheme_dialog(self) -> None:
        if not self.winfo_exists():
            return
        self._on_tab_changed()  # stash current tab before tearing down
        for child in self.winfo_children():
            child.destroy()
        self.configure(bg=C["bg"])
        self._build()

    def _pick_accent(self) -> None:
        _, hex_str = colorchooser.askcolor(
            color=self._current_accent_hex(), title="Accent color", parent=self)
        if hex_str:
            self._accent = hex_str
            self._refresh_swatch()
            self._live_appearance(retheme=True)

    def _reset_accent(self) -> None:
        self._accent = None
        self._refresh_swatch()
        self._live_appearance(retheme=True)

    def _cancel(self) -> None:
        # Revert any live preview to the appearance we opened with.
        if self._on_appearance is not None and not self._jobs_running:
            self._on_appearance(self._original_appearance, persist=False)
        self.destroy()

    def _on_corner_change(self, *_):
        val = _CORNER_LABEL_TO_VAL.get(self._snap_corner.get(), "none")
        if val and val != "none":
            _apply_snap_corner(self.master, val)

    def _section(self, parent: tk.Widget, text: str) -> tk.Frame:
        tk.Label(parent, text=text, bg=C["bg"], fg=C["accent"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(
            fill="x", padx=16, pady=(14, 2))
        sep = tk.Frame(parent, bg=C["accent"], height=1)
        sep.pack(fill="x", padx=16, pady=(0, 6))
        frame = tk.Frame(parent, bg=C["bg"])
        frame.pack(fill="x", padx=24, pady=2)
        return frame

    def _chk(self, parent, text: str, var: tk.BooleanVar,
             state: str = "normal") -> tk.Checkbutton:
        cb = tk.Checkbutton(parent, text=text, variable=var, state=state,
                            bg=C["bg"], fg=C["name_fg"],
                            selectcolor=C["card_bg"],
                            activebackground=C["bg"], activeforeground=C["name_fg"],
                            font=("Segoe UI", 9), anchor="w")
        cb.pack(fill="x", pady=2)
        return cb

    def _rb(self, parent, text: str, var: tk.StringVar, value: str,
            state: str = "normal") -> tk.Radiobutton:
        rb = tk.Radiobutton(parent, text=text, variable=var, value=value, state=state,
                            bg=C["bg"], fg=C["name_fg"],
                            selectcolor=C["card_bg"],
                            activebackground=C["bg"], activeforeground=C["name_fg"],
                            font=("Segoe UI", 9), anchor="w", cursor="hand2")
        rb.pack(fill="x", pady=1)
        return rb

    def _build(self):
        self._vcmd_int = (self.register(lambda s: s.isdigit() or s == ""), "%P")
        nb = ttk.Notebook(self, style="Card.TNotebook")
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        self._nb = nb

        appearance_tab = tk.Frame(nb, bg=C["bg"])
        startup_tab    = tk.Frame(nb, bg=C["bg"])
        output_tab     = tk.Frame(nb, bg=C["bg"])
        logging_tab    = tk.Frame(nb, bg=C["bg"])
        nb.add(appearance_tab, text="Appearance")
        nb.add(startup_tab,    text="Startup & Window")
        nb.add(output_tab,     text="Output")
        nb.add(logging_tab,    text="Logging")

        self._build_appearance_tab(appearance_tab)
        self._build_startup_tab(startup_tab)
        self._build_output_tab(output_tab)
        self._build_logging_tab(logging_tab)

        # Reopen on the tab the user last viewed (remembered for the session).
        try:
            nb.select(AdvancedOptionsDialog._last_tab)
        except tk.TclError:
            pass
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        btn_row = tk.Frame(self, bg=C["bg"])
        btn_row.pack(fill="x", padx=16, pady=12)
        _flat_button(btn_row, "Cancel", C["btn_dark_bg"], C["btn_dark_hover"],
                     self._cancel, width=10).pack(side="right", padx=(6, 0))
        _flat_button(btn_row, "Save", C["accent"], C["accent2"],
                     self._save, width=10).pack(side="right")

    def _on_tab_changed(self, _event=None):
        try:
            AdvancedOptionsDialog._last_tab = self._nb.index("current")
        except tk.TclError:
            pass

    def _build_appearance_tab(self, tab):
        state = "disabled" if self._jobs_running else "normal"
        if self._jobs_running:
            tk.Label(tab, text="Stop running jobs to change appearance.",
                     bg=C["bg"], fg=C["path_fg"], font=("Segoe UI", 8, "italic"),
                     anchor="w").pack(fill="x", padx=16, pady=(10, 0))

        f = self._section(tab, "THEME")
        self._rb(f, "☀  Light", self._theme, "light", state)
        self._rb(f, "🌙  Dark",  self._theme, "dark",  state)

        f = self._section(tab, "ACCENT COLOR")
        swatch_row = tk.Frame(f, bg=C["bg"])
        swatch_row.pack(fill="x", pady=(2, 6))
        self._swatch = tk.Frame(swatch_row, width=32, height=22,
                                relief="solid", bd=1, bg=self._current_accent_hex())
        self._swatch.pack(side="left", padx=(0, 8))
        self._swatch.pack_propagate(False)
        choose = _flat_button(swatch_row, "Choose…", C["btn_dark_bg"],
                              C["btn_dark_hover"], self._pick_accent, width=8)
        choose.pack(side="left", padx=(0, 4))
        reset = _flat_button(swatch_row, "Reset", C["btn_dark_bg"],
                             C["btn_dark_hover"], self._reset_accent, width=6)
        reset.pack(side="left")
        if self._jobs_running:
            choose.configure(state="disabled", cursor="")
            reset.configure(state="disabled", cursor="")

        f = self._section(tab, "DISPLAY")
        self._chk(f, "Compact cards (denser layout)", self._compact, state)
        tk.Label(f, text="Card size", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(8, 2))
        self._rb(f, "Small",  self._card_size, "small",  state)
        self._rb(f, "Medium", self._card_size, "medium", state)
        self._rb(f, "Large",  self._card_size, "large",  state)

    def _build_startup_tab(self, tab):
        f = self._section(tab, "STARTUP")
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
                   validate="key", validatecommand=self._vcmd_int,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
        tk.Label(size_row, text="×", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left", padx=4)
        tk.Spinbox(size_row, from_=300, to=2160, increment=10,
                   textvariable=self._win_height, width=6,
                   validate="key", validatecommand=self._vcmd_int,
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

    def _build_output_tab(self, tab):
        vcmd = self._vcmd_int
        f = self._section(tab, "OUTPUT")
        self._chk(f, "Auto-clear output before each run",        self._auto_clear)
        self._chk(f, "Auto-scroll to bottom",                     self._auto_scroll)
        self._chk(f, "Notify when script / pipeline completes",   self._notify_on_complete)
        self._chk(f, "Show Quick Run bar (requires group base directory)", self._quick_run_enabled)
        self._chk(f, "Quick Run: show suggestions as you type",   self._quick_run_autocomplete)
        self._chk(f, "Check for updates on startup",              self._auto_check_update)

        row = tk.Frame(f, bg=C["bg"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text="Max output lines:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(row, from_=100, to=50000, increment=100,
                   textvariable=self._max_lines, width=7,
                   validate="key", validatecommand=vcmd,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        row2 = tk.Frame(f, bg=C["bg"])
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="Max parallel jobs (0 = unlimited):", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(row2, from_=0, to=50, increment=1,
                   textvariable=self._max_parallel, width=7,
                   validate="key", validatecommand=vcmd,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        qr_ext_row = tk.Frame(f, bg=C["bg"])
        qr_ext_row.pack(fill="x", pady=4)
        tk.Label(qr_ext_row, text="Quick Run index file types (blank = all):",
                 bg=C["bg"], fg=C["name_fg"], font=("Segoe UI", 9)).pack(side="left")
        tk.Entry(qr_ext_row, textvariable=self._qr_index_exts, width=22,
                 bg=C["card_bg"], fg=C["name_fg"], insertbackground=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        qr_max_row = tk.Frame(f, bg=C["bg"])
        qr_max_row.pack(fill="x", pady=4)
        tk.Label(qr_max_row, text="Quick Run index max files (0 = unlimited):",
                 bg=C["bg"], fg=C["name_fg"], font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(qr_max_row, from_=0, to=100000, increment=500,
                   textvariable=self._qr_index_max_files, width=7,
                   validate="key", validatecommand=vcmd,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

    def _build_logging_tab(self, tab):
        f = self._section(tab, "LOGGING")
        self._chk(f, "Enable logging to file",           self._logging_enabled)
        self._chk(f, "Include script output in logs",    self._log_runs_output)
        level_row = tk.Frame(f, bg=C["bg"])
        level_row.pack(fill="x", pady=4)
        tk.Label(level_row, text="Log level:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(level_row, textvariable=self._log_level,
                     values=["DEBUG", "INFO", "WARNING", "ERROR"],
                     state="readonly", width=12,
                     font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

    def _save(self):
        try:
            max_lines = max(100, int(self._max_lines.get() or 100))
        except ValueError:
            max_lines = _SETTINGS_DEFAULTS["max_output_lines"]
        try:
            max_parallel = max(0, int(self._max_parallel.get() or 0))
        except ValueError:
            max_parallel = _SETTINGS_DEFAULTS["max_parallel_jobs"]
        try:
            win_w = max(400, int(self._win_width.get()  or 540))
            win_h = max(300, int(self._win_height.get() or 640))
        except ValueError:
            win_w, win_h = 540, 640
        try:
            qr_max_files = max(0, int(self._qr_index_max_files.get() or 0))
        except ValueError:
            qr_max_files = _SETTINGS_DEFAULTS["quick_run_index_max_files"]
        # Free-text list, separated by spaces and/or commas; normalize each
        # token to a lowercase, dot-prefixed extension. Blank = index everything.
        qr_exts = []
        for tok in self._qr_index_exts.get().replace(",", " ").split():
            tok = tok.lower()
            qr_exts.append(tok if tok.startswith(".") else "." + tok)
        self._settings.update({
            "theme":                    self._theme.get(),
            "accent_color":             self._accent,
            "compact_mode":             self._compact.get(),
            "card_size":                self._card_size.get(),
            "always_on_top":            self._always_on_top.get(),
            "snap_corner":              _CORNER_LABEL_TO_VAL.get(self._snap_corner.get(), "none"),
            "window_width":             win_w,
            "window_height":            win_h,
            "remember_last_group":      self._remember_group.get(),
            "start_minimized":          self._start_minimized.get(),
            "remember_window_geometry": self._remember_geometry.get(),
            "max_output_lines":         max_lines,
            "max_parallel_jobs":        max_parallel,
            "auto_clear_output":        self._auto_clear.get(),
            "auto_scroll_output":       self._auto_scroll.get(),
            "notify_on_complete":       self._notify_on_complete.get(),
            "quick_run_enabled":        self._quick_run_enabled.get(),
            "quick_run_autocomplete":   self._quick_run_autocomplete.get(),
            "quick_run_index_extensions": qr_exts,
            "quick_run_index_max_files":  qr_max_files,
            "auto_check_update":        self._auto_check_update.get(),
            "logging_enabled":          self._logging_enabled.get(),
            "log_level":                self._log_level.get(),
            "log_runs_output":          self._log_runs_output.get(),
        })
        try:
            _set_startup(self._start_with_windows.get())
        except Exception as e:
            messagebox.showerror("Startup Error",
                                 f"Could not update Windows startup entry:\n{e}",
                                 parent=self)
            return
        self._on_save(self._settings)
        # Apply theme / card changes and rebuild the UI (on_save already
        # persisted them, so don't write to disk again). Skipped while jobs run.
        if self._on_appearance is not None and not self._jobs_running:
            self._on_appearance(self._appearance_subset(), persist=False)
        self.destroy()
