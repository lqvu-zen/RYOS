"""Modal dialogs: Add/Edit script, preset entry, param picker, advanced options."""
import json
import os
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..db import ScriptDB
from ..history import format_run_row, header_row, summarize
from ..scheduling import (CATCH_UP_ALL, CATCH_UP_ONCE, CATCH_UP_SKIP, DAILY,
                          INTERVAL, SPEC_TYPES, WEEKLY, next_occurrence,
                          normalize_spec, preview)
from ..interpreter import format_env_text, parse_env_text
from ..settings import (
    _CORNER_CHOICES,
    _CORNER_LABEL_TO_VAL,
    _CORNER_VAL_TO_LABEL,
    _SETTINGS_DEFAULTS,
)
from ..startup import _set_startup, _startup_enabled
from ..quickrun import _is_inside
from ..themes import (
    SEEDS, THEME_LABELS, delete_user_theme, export_theme, import_theme,
    load_user_themes, resolve_user_themes_dir, save_user_theme,
)
from .theme import (
    C, THEMES, _apply_snap_corner, _flat_button,
    available_themes, custom_themes, set_custom_themes,
)
from .placement import center_over_parent, offset_from_parent
from .theme_editor import ThemeEditorDialog


def _try_unlink(path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


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
        center_over_parent(self, parent)
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
        center_over_parent(self, parent)
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
                (_, name, path, params, interp, grp, temp_param,
                 env_vars, work_dir) = rec[:9]
                self.e_name.insert(0, name)
                self.e_path.insert(0, path)
                self.e_params.insert(0, params)
                self.e_interp.set(interp)
                self.e_group.set(grp or "")
                self.temp_param_var.set(bool(temp_param))
                self.launcher_var.set(bool(db.is_detached(script_id)))
                self.e_workdir.insert(0, work_dir or "")
                self.t_env.insert("1.0", format_env_text(env_vars))
            for _, label, pparams in db.list_param_presets(script_id):
                self._presets.append([label, pparams])
                self._preset_listbox.insert(tk.END, label)
            self._refresh_path_inputs()
        else:
            self.e_group.set(self.default_group)
            self._refresh_path_inputs()

        self.transient(parent)
        center_over_parent(self, parent)
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

        self.launcher_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, variable=self.launcher_var,
            text="Launcher — opens an app/project; don't keep in Running",
        ).grid(row=8, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(frame, text="Working dir:").grid(row=9, column=0, sticky="w", **pad)
        self.e_workdir = ttk.Entry(frame, width=38)
        self.e_workdir.grid(row=9, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="Browse", width=8,
                   command=self._browse_workdir).grid(row=9, column=2, **pad)

        ttk.Label(frame, text="Environment:").grid(row=10, column=0, sticky="nw", **pad)
        env_frame = ttk.Frame(frame)
        env_frame.grid(row=10, column=1, columnspan=2, sticky="ew", **pad)
        env_frame.columnconfigure(0, weight=1)
        # A plain KEY=value block rather than a row editor: it can be pasted
        # straight out of a .env file or a shell, which is where these values
        # actually come from.
        self.t_env = tk.Text(
            env_frame, height=4, wrap="none",
            bg=C["out_bg"], fg="#cccccc", insertbackground="#cccccc",
            relief="flat", highlightthickness=1,
            highlightbackground=C["border"], font=("Consolas", 9),
        )
        _env_scroll = ttk.Scrollbar(env_frame, orient="vertical",
                                    command=self.t_env.yview)
        self.t_env.configure(yscrollcommand=_env_scroll.set)
        self.t_env.grid(row=0, column=0, sticky="nsew")
        _env_scroll.grid(row=0, column=1, sticky="ns")
        ttk.Label(frame, text="One KEY=value per line; blank to inherit only the system environment",
                  foreground="#888").grid(row=11, column=1, columnspan=2, sticky="w", padx=8)

        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=12, column=0, columnspan=3, sticky="ew", pady=8)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=13, column=0, columnspan=3, sticky="ew")
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
                    _, name, path, _, interp, grp, _temp = rec[:7]
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

    def _browse_workdir(self):
        d = filedialog.askdirectory(
            initialdir=self.e_workdir.get().strip() or str(Path.home()), parent=self)
        if d:
            self.e_workdir.delete(0, tk.END)
            self.e_workdir.insert(0, os.path.normpath(d))

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
        detached = int(self.launcher_var.get())
        work_dir = self.e_workdir.get().strip()
        env_pairs = parse_env_text(self.t_env.get("1.0", tk.END))
        # "" rather than None: None means "leave untouched" on update, which
        # would make clearing the field impossible.
        env_vars = json.dumps(env_pairs) if env_pairs else ""
        if self.script_id:
            self.db.update(self.script_id, name, path, params, interp, group_name,
                           temp_param, detached, env_vars=env_vars, work_dir=work_dir)
        else:
            self.script_id = self.db.add(name, path, params, interp, group_name,
                                         temp_param, detached,
                                         env_vars=env_vars or None, work_dir=work_dir)

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
        center_over_parent(self, parent)
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


class CloseToTrayPromptDialog(tk.Toplevel):
    """Shown on X-close, offering to switch on close-to-tray, until the user
    enables it or ticks "don't ask again" to opt out."""

    def __init__(self, parent):
        super().__init__(parent)
        # Set before any widget exists so every destroy path (Escape, WM
        # delete, a grab conflict) leaves both attributes defined.
        self.result: str = "cancel"
        self.dont_ask: bool = False
        self._dont_ask_var = tk.BooleanVar(value=False)

        self.title("Close RYOS")
        self.resizable(False, False)
        self.grab_set()
        self.configure(bg=C["bg"])

        title_strip = tk.Frame(self, bg=C["card_bg"])
        title_strip.pack(fill="x")
        tk.Label(title_strip, text="Minimize to tray instead?",
                 bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"),
                 anchor="w", padx=16, pady=12).pack(fill="x")
        tk.Frame(title_strip, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(body,
                 text="RYOS can keep running in the system tray instead of "
                      "exiting when you click X. You can always change this "
                      "later in Advanced Options → Startup.",
                 bg=C["bg"], fg=C["name_fg"], font=("Segoe UI", 9),
                 justify="left", wraplength=320).pack(fill="x", anchor="w")

        tk.Checkbutton(body, text="Don't ask me again", variable=self._dont_ask_var,
                       bg=C["bg"], fg=C["name_fg"],
                       selectcolor=C["card_bg"],
                       activebackground=C["bg"], activeforeground=C["name_fg"],
                       font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(12, 0))

        btn_row = tk.Frame(self, bg=C["bg"])
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        tray_btn = _flat_button(btn_row, "Minimize to tray", C["accent"], C["accent2"],
                                lambda: self._choose("tray"), width=17)
        tray_btn.pack(side="right")
        _flat_button(btn_row, "Exit", C["btn_dark_bg"], C["btn_dark_hover"],
                     lambda: self._choose("quit"), width=6).pack(side="right", padx=(0, 6))

        self.bind("<Return>", lambda _e: self._choose("tray"))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.transient(parent)
        center_over_parent(self, parent)
        tray_btn.focus_set()

    def _choose(self, outcome: str):
        self.result = outcome
        self.dont_ask = self._dont_ask_var.get()
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
        center_over_parent(self, parent)
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
        center_over_parent(self, parent)

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
                 on_clear_qr_cache=None, jobs_running: bool = False):
        super().__init__(parent)
        self._settings = dict(settings)
        self._on_save  = on_save
        # on_appearance(appearance_subset, persist) applies theme/cards live and
        # rebuilds the UI. When jobs are running a rebuild would disrupt them, so
        # the Appearance tab is disabled and this callback is never fired.
        self._on_appearance = on_appearance
        self._on_clear_qr_cache = on_clear_qr_cache
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
        self._hover_preview = tk.BooleanVar(value=self._settings.get("hover_preview", True))
        self._original_appearance = self._appearance_subset()

        self._start_with_windows = tk.BooleanVar(value=_startup_enabled())
        self._always_on_top     = tk.BooleanVar(value=self._settings["always_on_top"])
        self._snap_corner       = tk.StringVar(
            value=_CORNER_VAL_TO_LABEL.get(self._settings.get("snap_corner") or "none", "Off"))
        self._snap_corner.trace_add("write", self._on_corner_change)
        self._remember_group    = tk.BooleanVar(value=self._settings["remember_last_group"])
        self._start_minimized   = tk.BooleanVar(value=self._settings["start_minimized"])
        self._close_to_tray     = tk.BooleanVar(value=self._settings["close_to_tray"])
        self._remember_geometry = tk.BooleanVar(value=self._settings["remember_window_geometry"])
        self._open_on_cursor    = tk.BooleanVar(value=self._settings.get("open_on_cursor_monitor", True))
        self._win_width         = tk.StringVar(value=str(self._settings.get("window_width",  540)))
        self._win_height        = tk.StringVar(value=str(self._settings.get("window_height", 640)))
        self._max_lines         = tk.StringVar(value=str(self._settings["max_output_lines"]))
        self._max_parallel      = tk.StringVar(value=str(self._settings.get("max_parallel_jobs", 10)))
        self._launcher_release  = tk.StringVar(value=str(self._settings.get("launcher_release_seconds", 3)))
        self._auto_clear        = tk.BooleanVar(value=self._settings["auto_clear_output"])
        self._auto_scroll       = tk.BooleanVar(value=self._settings["auto_scroll_output"])
        self._auto_check_update = tk.BooleanVar(value=self._settings.get("auto_check_update", True))
        self._notify_on_complete = tk.BooleanVar(value=self._settings.get("notify_on_complete", True))
        self._quick_run_enabled = tk.BooleanVar(value=self._settings.get("quick_run_enabled", True))
        self._quick_run_autocomplete = tk.BooleanVar(value=self._settings.get("quick_run_autocomplete", True))
        # Authoritative list of indexed extensions (survives dialog rebuilds);
        # the Listbox in the Quick Run tab is just a view onto it.
        self._qr_exts = [self._normalize_ext(e)
                         for e in (self._settings.get("quick_run_index_extensions") or [])]
        self._qr_new_ext = tk.StringVar()
        self._qr_index_max_files = tk.StringVar(
            value=str(self._settings.get("quick_run_index_max_files", 5000)))
        self._logging_enabled = tk.BooleanVar(value=self._settings.get("logging_enabled", True))
        self._log_level = tk.StringVar(value=self._settings.get("log_level", "INFO"))
        self._log_runs_output = tk.BooleanVar(value=self._settings.get("log_runs_output", False))

        self._build()
        offset_from_parent(self, parent, 60, 60)

        # Live-preview appearance changes (skipped while jobs run — see __init__).
        # A theme switch changes the palette, so the dialog re-themes itself too;
        # compact / card-size only affect the cards, so they don't.
        if self._on_appearance is not None and not self._jobs_running:
            self._theme.trace_add("write", lambda *_: self._live_appearance(retheme=True))
            self._compact.trace_add("write", lambda *_: self._live_appearance())
            self._card_size.trace_add("write", lambda *_: self._live_appearance())
            self._hover_preview.trace_add("write", lambda *_: self._live_appearance())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    # ------------------------------------------------------------------
    # Appearance helpers
    # ------------------------------------------------------------------

    def _appearance_subset(self) -> dict:
        return {
            "theme":         self._theme.get(),
            "accent_color":  self._accent,
            "compact_mode":  self._compact.get(),
            "card_size":     self._card_size.get(),
            "hover_preview": self._hover_preview.get(),
        }

    def _current_accent_hex(self) -> str:
        if self._accent:
            return self._accent
        tid = self._theme.get()
        customs = custom_themes()
        if tid in customs:
            return customs[tid]["accent"]
        return THEMES.get(tid, THEMES["light"])["accent"]

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

    # ------------------------------------------------------------------
    # Custom themes
    # ------------------------------------------------------------------

    def _current_seed(self) -> dict:
        """The seed to pre-fill the editor with (the selected theme's seed)."""
        tid = self._theme.get()
        customs = custom_themes()
        if tid in customs:
            return dict(customs[tid])
        if tid in SEEDS:
            return dict(SEEDS[tid])
        return dict(SEEDS["light"])

    def _taken_names(self, exclude: str | None = None) -> set:
        """Names a new/edited theme may not use: built-in labels + other customs."""
        names = set(THEME_LABELS.values()) | set(custom_themes())
        if exclude:
            names.discard(exclude)
        return names

    def _create_theme(self) -> None:
        ThemeEditorDialog(self, seed=self._current_seed(), name="",
                          taken_names=self._taken_names(),
                          on_save=self._save_custom_theme)

    def _edit_theme(self) -> None:
        tid = self._theme.get()
        customs = custom_themes()
        if tid not in customs:
            return
        ThemeEditorDialog(
            self, seed=customs[tid], name=tid,
            taken_names=self._taken_names(exclude=tid),
            on_save=lambda name, seed: self._save_custom_theme(name, seed, replacing=tid))

    def _themes_dir(self):
        return resolve_user_themes_dir(self._settings.get("themes_dir"))

    def _save_custom_theme(self, name: str, seed: dict, replacing: str | None = None) -> None:
        d = self._themes_dir()
        if replacing and replacing != name:
            delete_user_theme(d, replacing)
        save_user_theme(d, name, seed)
        set_custom_themes(load_user_themes(d))
        if self._theme.get() == name:
            self._live_appearance(retheme=True)  # same id: force re-apply + rebuild
        else:
            self._theme.set(name)                 # new id: trace re-applies + rebuilds

    def _delete_theme(self) -> None:
        tid = self._theme.get()
        customs = custom_themes()
        if tid not in customs:
            return
        if not messagebox.askyesno("Delete theme",
                                   f"Delete the “{tid}” theme?", parent=self):
            return
        d = self._themes_dir()
        delete_user_theme(d, tid)
        set_custom_themes(load_user_themes(d))
        self._theme.set("light")  # switch off the now-deleted theme

    def _browse_themes_dir(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title="Themes folder", initialdir=str(self._themes_dir()))
        if not chosen:
            return
        self._settings["themes_dir"] = chosen
        set_custom_themes(load_user_themes(resolve_user_themes_dir(chosen)))
        self._live_appearance(retheme=True)

    def _open_themes_dir(self) -> None:
        try:
            os.startfile(str(self._themes_dir()))  # noqa: S606 (Windows reveal)
        except (OSError, AttributeError):
            pass

    def _export_theme(self) -> None:
        tid = self._theme.get()
        customs = custom_themes()
        if tid not in customs:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Export theme", defaultextension=".json",
            initialfile=f"{tid}.json",
            filetypes=[("RYOS theme", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            export_theme(tid, customs[tid], path)
        except OSError as exc:
            messagebox.showerror("Export theme",
                                 f"Could not write file:\n{exc}", parent=self)

    def _unique_theme_name(self, base: str) -> str:
        base = base.strip() or "Imported theme"
        taken = {n.lower() for n in self._taken_names()}
        if base.lower() not in taken:
            return base
        i = 2
        while f"{base} ({i})".lower() in taken:
            i += 1
        return f"{base} ({i})"

    def _import_theme(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Import theme",
            filetypes=[("RYOS theme", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            name, seed = import_theme(path)
        except ValueError as exc:
            messagebox.showerror("Import theme", str(exc), parent=self)
            return
        name = self._unique_theme_name(name or Path(path).stem)
        self._save_custom_theme(name, seed)

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
        quick_run_tab  = tk.Frame(nb, bg=C["bg"])
        logging_tab    = tk.Frame(nb, bg=C["bg"])
        nb.add(appearance_tab, text="Appearance")
        nb.add(startup_tab,    text="Startup")
        nb.add(output_tab,     text="Output")
        nb.add(quick_run_tab,  text="Quick Run")
        nb.add(logging_tab,    text="Logging")

        self._build_appearance_tab(appearance_tab)
        self._build_startup_tab(startup_tab)
        self._build_output_tab(output_tab)
        self._build_quick_run_tab(quick_run_tab)
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
        # Dropdown of every selectable theme (built-ins + custom). The combobox
        # shows labels; picking one writes the theme id into self._theme, whose
        # trace drives the live preview (set up in __init__).
        choices = available_themes()  # [(id, label), ...]
        id_to_label = {tid: lab for tid, lab in choices}
        self._theme_label = tk.StringVar(
            value=id_to_label.get(self._theme.get(), id_to_label.get("light", "Light")))
        theme_combo = ttk.Combobox(
            f, textvariable=self._theme_label, state="readonly",
            values=[lab for _tid, lab in choices],
            style="Card.TCombobox", font=("Segoe UI", 9))
        theme_combo.pack(fill="x", pady=(2, 6))
        if self._jobs_running:
            theme_combo.configure(state="disabled")

        def _on_theme_pick(_e=None):
            picked = self._theme_label.get()
            for tid, lab in choices:
                if lab == picked:
                    self._theme.set(tid)
                    break
        theme_combo.bind("<<ComboboxSelected>>", _on_theme_pick)

        # Custom-theme actions. Edit/Delete apply only to a selected custom theme.
        is_custom = self._theme.get() in custom_themes()
        actions = tk.Frame(f, bg=C["bg"])
        actions.pack(fill="x", pady=(0, 2))
        create_btn = _flat_button(actions, "Create…", C["btn_dark_bg"],
                                  C["btn_dark_hover"], self._create_theme, width=8)
        create_btn.pack(side="left")
        edit_btn = _flat_button(actions, "Edit…", C["btn_dark_bg"],
                                C["btn_dark_hover"], self._edit_theme, width=6)
        edit_btn.pack(side="left", padx=4)
        del_btn = _flat_button(actions, "Delete", C["btn_dark_bg"],
                               C["btn_dark_hover"], self._delete_theme, width=7)
        del_btn.pack(side="left")

        share = tk.Frame(f, bg=C["bg"])
        share.pack(fill="x", pady=(2, 2))
        export_btn = _flat_button(share, "Export…", C["btn_dark_bg"],
                                  C["btn_dark_hover"], self._export_theme, width=8)
        export_btn.pack(side="left")
        import_btn = _flat_button(share, "Import…", C["btn_dark_bg"],
                                  C["btn_dark_hover"], self._import_theme, width=8)
        import_btn.pack(side="left", padx=4)

        if self._jobs_running:
            for b in (create_btn, edit_btn, del_btn, export_btn, import_btn):
                b.configure(state="disabled", cursor="")
        elif not is_custom:
            edit_btn.configure(state="disabled", cursor="")
            del_btn.configure(state="disabled", cursor="")
            export_btn.configure(state="disabled", cursor="")

        # Themes folder: auto-scanned for custom theme files; drop a .json in to
        # add a theme. Configurable so users can point it anywhere.
        tk.Label(f, text="Themes folder (drop .json files here)", bg=C["bg"],
                 fg=C["path_fg"], font=("Segoe UI", 8), anchor="w").pack(
            fill="x", pady=(8, 0))
        folder_row = tk.Frame(f, bg=C["bg"])
        folder_row.pack(fill="x", pady=(2, 2))
        tk.Label(folder_row, text=str(self._themes_dir()), bg=C["card_bg"],
                 fg=C["name_fg"], font=("Segoe UI", 8), anchor="w", relief="flat",
                 padx=6, pady=3).pack(side="left", fill="x", expand=True)
        browse_btn = _flat_button(folder_row, "Browse…", C["btn_dark_bg"],
                                  C["btn_dark_hover"], self._browse_themes_dir, width=8)
        browse_btn.pack(side="left", padx=(6, 0))
        open_btn = _flat_button(folder_row, "Open", C["btn_dark_bg"],
                                C["btn_dark_hover"], self._open_themes_dir, width=6)
        open_btn.pack(side="left", padx=(4, 0))
        if self._jobs_running:
            browse_btn.configure(state="disabled", cursor="")

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
        self._chk(f, "Preview details on hover (compact cards)", self._hover_preview, state)
        tk.Label(f, text="Card size", bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(8, 2))
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
        self._chk(f, "Close button minimizes to tray",   self._close_to_tray)
        self._chk(f, "Check for updates on startup",      self._auto_check_update)
        self._chk(f, "Remember window size and position", self._remember_geometry)
        self._chk(f, "Open on the screen where the cursor is", self._open_on_cursor)

        size_row = tk.Frame(f, bg=C["bg"])
        size_row.pack(fill="x", pady=(8, 2))
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
                     style="Card.TCombobox",
                     state="readonly", width=18,
                     font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

    def _build_output_tab(self, tab):
        vcmd = self._vcmd_int
        f = self._section(tab, "OUTPUT")
        self._chk(f, "Auto-clear output before each run",        self._auto_clear)
        self._chk(f, "Auto-scroll to bottom",                     self._auto_scroll)
        self._chk(f, "Notify when script / pipeline completes",   self._notify_on_complete)

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

        row3 = tk.Frame(f, bg=C["bg"])
        row3.pack(fill="x", pady=4)
        tk.Label(row3, text="Release launchers from Running after (seconds):",
                 bg=C["bg"], fg=C["name_fg"], font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(row3, from_=0, to=60, increment=1,
                   textvariable=self._launcher_release, width=7,
                   validate="key", validatecommand=vcmd,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

    @staticmethod
    def _normalize_ext(token: str) -> str:
        """Lowercase, dot-prefixed extension; '' for blank input."""
        token = token.strip().lower()
        if not token:
            return ""
        return token if token.startswith(".") else "." + token

    def _qr_refresh_list(self) -> None:
        self._qr_listbox.delete(0, "end")
        for ext in self._qr_exts:
            self._qr_listbox.insert("end", ext)

    def _qr_add(self) -> None:
        ext = self._normalize_ext(self._qr_new_ext.get())
        if ext and ext not in self._qr_exts:
            self._qr_exts.append(ext)
            self._qr_refresh_list()
        self._qr_new_ext.set("")

    def _qr_remove(self) -> None:
        # Remove every selected row, highest index first so positions stay valid.
        for i in sorted(self._qr_listbox.curselection(), reverse=True):
            del self._qr_exts[i]
        self._qr_refresh_list()

    def _build_quick_run_tab(self, tab):
        vcmd = self._vcmd_int
        f = self._section(tab, "QUICK RUN")
        self._chk(f, "Show Quick Run bar (requires group base directory)", self._quick_run_enabled)
        self._chk(f, "Show suggestions as you type",   self._quick_run_autocomplete)

        f = self._section(tab, "FILE INDEX")
        tk.Label(f, text="Index file types (empty = index everything):",
                 bg=C["bg"], fg=C["name_fg"], font=("Segoe UI", 9),
                 anchor="w").pack(fill="x", pady=(8, 2))

        list_row = tk.Frame(f, bg=C["bg"])
        list_row.pack(fill="x", pady=(0, 2))

        list_box = tk.Frame(list_row, bg=C["bg"])
        list_box.pack(side="left", fill="both", expand=True)
        self._qr_listbox = tk.Listbox(
            list_box, height=5, activestyle="none", exportselection=False,
            bg=C["card_bg"], fg=C["name_fg"],
            selectbackground=C["accent"], selectforeground=C["fg_on_dark"],
            highlightthickness=1, highlightbackground=C["border"],
            highlightcolor=C["accent"], relief="flat", borderwidth=0,
            font=("Segoe UI", 9))
        self._qr_listbox.pack(side="left", fill="both", expand=True)
        qr_scroll = ttk.Scrollbar(list_box, orient="vertical",
                                  command=self._qr_listbox.yview)
        self._qr_listbox.configure(yscrollcommand=qr_scroll.set)
        qr_scroll.pack(side="left", fill="y")
        self._qr_listbox.bind("<Delete>", lambda _e: self._qr_remove())
        self._qr_listbox.bind("<Double-Button-1>", lambda _e: self._qr_remove())

        btns = tk.Frame(list_row, bg=C["bg"])
        btns.pack(side="left", fill="y", padx=(8, 0))
        _flat_button(btns, "Remove", C["btn_dark_bg"], C["btn_dark_hover"],
                     self._qr_remove, width=8).pack(side="top")

        add_row = tk.Frame(f, bg=C["bg"])
        add_row.pack(fill="x", pady=(4, 2))
        add_entry = tk.Entry(add_row, textvariable=self._qr_new_ext, width=14,
                             bg=C["card_bg"], fg=C["name_fg"],
                             insertbackground=C["name_fg"], font=("Segoe UI", 9))
        add_entry.pack(side="left")
        add_entry.bind("<Return>", lambda _e: self._qr_add())
        _flat_button(add_row, "Add", C["accent"], C["accent2"],
                     self._qr_add, width=6).pack(side="left", padx=(8, 0))
        tk.Label(add_row, text="e.g. .py", bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8, "italic")).pack(side="left", padx=(8, 0))

        self._qr_refresh_list()

        qr_max_row = tk.Frame(f, bg=C["bg"])
        qr_max_row.pack(fill="x", pady=4)
        tk.Label(qr_max_row, text="Index max files (0 = unlimited):",
                 bg=C["bg"], fg=C["name_fg"], font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(qr_max_row, from_=0, to=100000, increment=500,
                   textvariable=self._qr_index_max_files, width=7,
                   validate="key", validatecommand=vcmd,
                   bg=C["card_bg"], fg=C["name_fg"],
                   buttonbackground=C["card_bg"],
                   font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        def _clear_cache():
            from ..settings import QR_INDEX_DIR
            cleared = sum(
                1 for p in QR_INDEX_DIR.glob("qr_index_*.json")
                if _try_unlink(p)
            )
            if self._on_clear_qr_cache:
                self._on_clear_qr_cache()
            messagebox.showinfo(
                "Cache cleared",
                f"Removed {cleared} cached index file(s).\n"
                "The index will rebuild automatically on next use.",
                parent=self)

        _flat_button(f, "Clear index cache", C["btn_dark_bg"], C["btn_dark_hover"],
                     _clear_cache, width=16).pack(anchor="w", pady=(8, 0))

    def _build_logging_tab(self, tab):
        import subprocess
        from ..settings import LOG_DIR, LOG_PATH
        f = self._section(tab, "LOGGING")
        self._chk(f, "Enable logging to file",           self._logging_enabled)
        self._chk(f, "Include script output in logs",    self._log_runs_output)
        level_row = tk.Frame(f, bg=C["bg"])
        level_row.pack(fill="x", pady=4)
        tk.Label(level_row, text="Log level:", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(level_row, textvariable=self._log_level,
                     values=["DEBUG", "INFO", "WARNING", "ERROR"],
                     style="Card.TCombobox",
                     state="readonly", width=12,
                     font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        def _open_file():
            if not LOG_PATH.exists():
                LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                LOG_PATH.touch()
            if sys.platform == "win32":
                os.startfile(str(LOG_PATH))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(LOG_PATH)])
            else:
                subprocess.Popen(["xdg-open", str(LOG_PATH)])

        def _open_folder():
            if sys.platform == "win32":
                os.startfile(str(LOG_DIR))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(LOG_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(LOG_DIR)])

        def _clear_log_file():
            if not LOG_PATH.exists():
                messagebox.showinfo("Clear log", "No log file found.", parent=self)
                return
            if messagebox.askyesno("Clear log file",
                                   "Truncate the log file? This cannot be undone.",
                                   parent=self):
                LOG_PATH.write_text("", encoding="utf-8")

        tk.Label(f, text=str(LOG_PATH), bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(10, 2))
        btn_row = tk.Frame(f, bg=C["bg"])
        btn_row.pack(fill="x", pady=(2, 0))
        _flat_button(btn_row, "View log",     C["btn_dark_bg"], C["btn_dark_hover"],
                     _open_file,   width=10).pack(side="left", padx=(0, 6))
        _flat_button(btn_row, "Open folder",  C["btn_dark_bg"], C["btn_dark_hover"],
                     _open_folder, width=12).pack(side="left")
        _flat_button(f, "Clear log file", C["btn_dark_bg"], C["btn_dark_hover"],
                     _clear_log_file, width=14).pack(anchor="w", pady=(6, 0))

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
            launcher_release = max(0, int(self._launcher_release.get() or 0))
        except ValueError:
            launcher_release = _SETTINGS_DEFAULTS["launcher_release_seconds"]
        try:
            win_w = max(400, int(self._win_width.get()  or 540))
            win_h = max(300, int(self._win_height.get() or 640))
        except ValueError:
            win_w, win_h = 540, 640
        try:
            qr_max_files = max(0, int(self._qr_index_max_files.get() or 0))
        except ValueError:
            qr_max_files = _SETTINGS_DEFAULTS["quick_run_index_max_files"]
        # Fold in any extension left typed-but-not-added so it isn't lost.
        self._qr_add()
        qr_exts = list(self._qr_exts)  # already normalized; blank = index everything
        self._settings.update({
            "theme":                    self._theme.get(),
            "accent_color":             self._accent,
            "compact_mode":             self._compact.get(),
            "card_size":                self._card_size.get(),
            "hover_preview":            self._hover_preview.get(),
            "always_on_top":            self._always_on_top.get(),
            "snap_corner":              _CORNER_LABEL_TO_VAL.get(self._snap_corner.get(), "none"),
            "window_width":             win_w,
            "window_height":            win_h,
            "remember_last_group":      self._remember_group.get(),
            "start_minimized":          self._start_minimized.get(),
            "close_to_tray":            self._close_to_tray.get(),
            "remember_window_geometry": self._remember_geometry.get(),
            "open_on_cursor_monitor":   self._open_on_cursor.get(),
            "themes_dir":               self._settings.get("themes_dir", ""),
            "max_output_lines":         max_lines,
            "max_parallel_jobs":        max_parallel,
            "launcher_release_seconds": launcher_release,
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
        except OSError as e:
            # winreg raises OSError on registry failure; show it. An unexpected
            # (non-OSError) error is a bug and should surface, not be masked.
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


class RunHistoryDialog(tk.Toplevel):
    """Recent runs for one script or pipeline.

    A Listbox with monospace columns rather than a ttk.Treeview: the Treeview
    needs its own style wiring to stay readable across the theme gallery, and
    this dialog shows a flat list with no hierarchy to justify that.
    """

    _LIMIT = 100

    def __init__(self, parent, db: ScriptDB, *, script_id: int | None = None,
                 pipeline_id: int | None = None, title: str = ""):
        super().__init__(parent)
        self.db = db
        self._script_id = script_id
        self._pipeline_id = pipeline_id

        self.title(f"Run History — {title}" if title else "Run History")
        self.resizable(True, True)
        self.configure(bg=C["card_bg"])
        self.grab_set()

        head = tk.Frame(self, bg=C["card_bg"], padx=16, pady=12)
        head.pack(fill="x")
        tk.Label(head, text=title or "Run history", bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        self._summary = tk.StringVar()
        tk.Label(head, textvariable=self._summary, bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(2, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        hdr = tk.Frame(self, bg=C["bg"], padx=14, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text=header_row(), bg=C["bg"], fg=C["path_fg"],
                 font=("Consolas", 9), anchor="w").pack(fill="x")

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        sb = ttk.Scrollbar(body)
        sb.pack(side="right", fill="y")
        self._list = tk.Listbox(
            body, yscrollcommand=sb.set, selectmode="single",
            font=("Consolas", 9), exportselection=False,
            bg=C["card_bg"], fg=C["name_fg"],
            selectbackground=C["accent"], selectforeground=C["fg_on_dark"],
            relief="flat", highlightthickness=1,
            highlightbackground=C["border"], activestyle="none",
        )
        sb.config(command=self._list.yview)
        self._list.pack(side="left", fill="both", expand=True)

        btns = tk.Frame(self, bg=C["card_bg"], padx=16, pady=12)
        btns.pack(fill="x")
        tk.Button(btns, text="Close", command=self.destroy,
                  bg=C["accent"], fg=C["fg_on_dark"], activebackground=C["accent2"],
                  activeforeground=C["fg_on_dark"], relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="right")
        tk.Button(btns, text="Clear History", command=self._clear,
                  bg=C["btn_neutral_bg"], fg=C["btn_neutral_fg"],
                  activebackground=C["btn_neutral_hover"],
                  activeforeground=C["btn_neutral_fg"], relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 9)).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _e: self.destroy())
        self._reload()
        self.transient(parent)
        center_over_parent(self, parent, 620, 420)

    def _reload(self) -> None:
        rows = self.db.list_runs(script_id=self._script_id,
                                 pipeline_id=self._pipeline_id,
                                 limit=self._LIMIT)
        self._list.delete(0, tk.END)
        self._summary.set(summarize(rows))
        if not rows:
            self._list.insert(tk.END, "  Nothing here yet — run it once and it will show up.")
            return
        for r in rows:
            self._list.insert(tk.END, format_run_row(r))

    def _clear(self) -> None:
        if not messagebox.askyesno("Clear History",
                                   "Delete the recorded runs for this item?",
                                   parent=self):
            return
        self.db.clear_runs(script_id=self._script_id, pipeline_id=self._pipeline_id)
        self._reload()


class ScheduleDialog(tk.Toplevel):
    """Create, edit or remove the recurring schedule for one script or pipeline.

    The next-runs list is the point of this dialog as much as the fields are:
    it is computed with the same function the tick uses, so what it shows is
    what will actually happen. Nothing fires at a time the user has not already
    seen written down.
    """

    _CATCH_UP_LABELS = {
        CATCH_UP_ONCE: "Run once",
        CATCH_UP_SKIP: "Skip them",
        CATCH_UP_ALL: "Run every missed one",
    }

    def __init__(self, parent, db: ScriptDB, *, script_id: int | None = None,
                 pipeline_id: int | None = None, title: str = "", on_save=None):
        super().__init__(parent)
        self.db = db
        self._script_id = script_id
        self._pipeline_id = pipeline_id
        self._on_save = on_save
        self._existing = db.get_schedule(script_id=script_id, pipeline_id=pipeline_id)

        self.title(f"Schedule — {title}" if title else "Schedule")
        self.resizable(False, False)
        self.configure(bg=C["card_bg"])
        self.grab_set()

        strip = tk.Frame(self, bg=C["card_bg"])
        strip.pack(fill="x")
        tk.Label(strip, text=title or "Schedule", bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 11, "bold"), anchor="w",
                 padx=16, pady=12).pack(fill="x")
        tk.Frame(strip, bg=C["border"], height=1).pack(fill="x")

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        pad = {"padx": 8, "pady": 4}

        self._enabled = tk.BooleanVar(value=bool(self._existing[6]) if self._existing else False)
        ttk.Checkbutton(frame, variable=self._enabled,
                        text="Run this on a schedule").grid(
            row=0, column=0, columnspan=3, sticky="w", **pad)

        self._mode = tk.StringVar(value=INTERVAL)
        self._minutes = tk.StringVar(value="30")
        self._at = tk.StringVar(value="09:00")
        self._days = {d: tk.BooleanVar(value=(d == 0)) for d in range(7)}

        ttk.Radiobutton(frame, text="Every", variable=self._mode,
                        value=INTERVAL).grid(row=1, column=0, sticky="w", **pad)
        iv = ttk.Frame(frame)
        iv.grid(row=1, column=1, columnspan=2, sticky="w", **pad)
        ttk.Entry(iv, textvariable=self._minutes, width=6).pack(side="left")
        ttk.Label(iv, text="minutes").pack(side="left", padx=(6, 0))

        ttk.Radiobutton(frame, text="Daily at", variable=self._mode,
                        value=DAILY).grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self._at, width=8).grid(
            row=2, column=1, sticky="w", **pad)

        ttk.Radiobutton(frame, text="Weekly on", variable=self._mode,
                        value=WEEKLY).grid(row=3, column=0, sticky="nw", **pad)
        days_row = ttk.Frame(frame)
        days_row.grid(row=3, column=1, columnspan=2, sticky="w", **pad)
        for d, label in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            ttk.Checkbutton(days_row, text=label, variable=self._days[d]).pack(side="left")

        ttk.Label(frame, text="If missed:").grid(row=4, column=0, sticky="w", **pad)
        self._catch_up = tk.StringVar(value=self._CATCH_UP_LABELS[CATCH_UP_ONCE])
        ttk.Combobox(frame, textvariable=self._catch_up, state="readonly", width=22,
                     values=list(self._CATCH_UP_LABELS.values())).grid(
            row=4, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(frame, text="RYOS only fires schedules while it is open",
                  foreground="#888").grid(row=5, column=1, columnspan=2,
                                          sticky="w", padx=8)

        ttk.Separator(frame, orient="horizontal").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=10)

        ttk.Label(frame, text="Next runs:").grid(row=7, column=0, sticky="nw", **pad)
        self._preview = tk.Label(frame, text="", justify="left", anchor="nw",
                                 bg=C["card_bg"], fg=C["path_fg"],
                                 font=("Consolas", 9))
        self._preview.grid(row=7, column=1, columnspan=2, sticky="w", **pad)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(btn_row, text="Save", command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        if self._existing:
            ttk.Button(btn_row, text="Remove", command=self._remove).pack(side="left", padx=4)

        self._load_existing()
        for var in (self._mode, self._minutes, self._at, *self._days.values()):
            var.trace_add("write", lambda *_: self._refresh_preview())
        self._refresh_preview()

        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        center_over_parent(self, parent)

    # ------------------------------------------------------------------ state

    def _load_existing(self) -> None:
        if not self._existing:
            return
        spec_type, raw, catch_up = self._existing[4], self._existing[5], self._existing[7]
        try:
            spec = json.loads(raw)
        except (TypeError, ValueError):
            spec = {}
        if spec_type in SPEC_TYPES:
            self._mode.set(spec_type)
        if spec_type == INTERVAL:
            self._minutes.set(str(spec.get("minutes", 30)))
        else:
            self._at.set(str(spec.get("at", "09:00")))
            if spec_type == WEEKLY:
                chosen = set(spec.get("days") or [])
                for d, var in self._days.items():
                    var.set(d in chosen)
        self._catch_up.set(self._CATCH_UP_LABELS.get(catch_up,
                                                     self._CATCH_UP_LABELS[CATCH_UP_ONCE]))

    def _current_spec(self):
        """(spec_type, normalized_spec) for the form, or (type, None) if invalid."""
        mode = self._mode.get()
        if mode == INTERVAL:
            raw = {"minutes": self._minutes.get().strip()}
        elif mode == DAILY:
            raw = {"at": self._at.get().strip()}
        else:
            raw = {"at": self._at.get().strip(),
                   "days": [d for d, v in self._days.items() if v.get()]}
        return mode, normalize_spec(mode, raw)

    def _current_catch_up(self) -> str:
        label = self._catch_up.get()
        for key, text in self._CATCH_UP_LABELS.items():
            if text == label:
                return key
        return CATCH_UP_ONCE

    # ---------------------------------------------------------------- actions

    def _refresh_preview(self) -> None:
        spec_type, spec = self._current_spec()
        if spec is None:
            self._preview.config(text="—  check the values above")
            return
        runs = preview(spec_type, spec, datetime.now(), 5)
        self._preview.config(
            text="\n".join(r.strftime("%a %d %b  %H:%M") for r in runs) or "—")

    def _save(self) -> None:
        spec_type, spec = self._current_spec()
        if spec is None:
            messagebox.showwarning(
                "Check the schedule",
                "That schedule can't run.\n\n"
                "Interval needs at least 1 minute, times look like 09:00, "
                "and a weekly schedule needs at least one day.",
                parent=self)
            return
        enabled = bool(self._enabled.get())
        raw = json.dumps(spec)
        next_at = next_occurrence(spec_type, spec, datetime.now())
        catch_up = self._current_catch_up()
        if self._existing:
            self.db.update_schedule(self._existing[0], spec_type=spec_type, spec=raw,
                                    catch_up=catch_up, enabled=enabled,
                                    next_run_at=next_at)
        else:
            self.db.add_schedule(
                "pipeline" if self._pipeline_id is not None else "script",
                script_id=self._script_id, pipeline_id=self._pipeline_id,
                spec_type=spec_type, spec=raw, catch_up=catch_up,
                enabled=enabled, next_run_at=next_at)
        if enabled:
            self._offer_run_at_login()
        if self._on_save:
            self._on_save()
        self.destroy()

    def _offer_run_at_login(self) -> None:
        """A schedule only fires while RYOS is open, so offer to start it at login.

        Asked once, when a schedule is first switched on and the setting is off;
        declining is remembered by simply never asking again unless run-at-login
        is still off and another schedule is enabled.
        """
        if sys.platform != "win32" or _startup_enabled():
            return
        if messagebox.askyesno(
                "Start RYOS at login?",
                "Schedules only run while RYOS is open.\n\n"
                "Start RYOS automatically when you log in?",
                parent=self):
            try:
                _set_startup(True)
            except OSError:
                messagebox.showwarning("Could not change startup",
                                       "RYOS could not update the startup setting.",
                                       parent=self)

    def _remove(self) -> None:
        if not messagebox.askyesno("Remove Schedule",
                                   "Stop running this on a schedule?", parent=self):
            return
        self.db.delete_schedule(self._existing[0])
        if self._on_save:
            self._on_save()
        self.destroy()
