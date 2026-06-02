"""Pipeline editor dialog — manage step order and per-step param overrides."""
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..db import ScriptDB
from .theme import C


class PipelineEditorDialog(tk.Toplevel):
    def __init__(self, parent, db: ScriptDB, pipeline_id: int,
                 pipeline_name: str, group_name: str, on_save):
        super().__init__(parent)
        self.db = db
        self.pipeline_id = pipeline_id
        self.group_name = group_name
        self.on_save = on_save
        self._steps: list = []

        self.title("Edit Pipeline")
        self.resizable(True, True)
        self.configure(bg=C["card_bg"])
        self.grab_set()
        self.geometry("440x520")
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 440) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 520) // 2
        self.geometry(f"440x520+{x}+{y}")

        nf = tk.Frame(self, bg=C["card_bg"], padx=16, pady=12)
        nf.pack(fill="x")
        tk.Label(nf, text="Pipeline Name", bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._name_var = tk.StringVar(value=pipeline_name)
        tk.Entry(nf, textvariable=self._name_var,
                 font=("Segoe UI", 10)).pack(fill="x", pady=(4, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        sh = tk.Frame(self, bg=C["bg"], padx=16, pady=8)
        sh.pack(fill="x")
        tk.Label(sh, text="Steps", bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")

        list_frame = tk.Frame(self, bg=C["bg"])
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")
        self._listbox = tk.Listbox(
            list_frame, yscrollcommand=sb.set,
            selectmode="single", font=("Segoe UI", 10),
            exportselection=False,
            bg="#f8f9fc", fg=C["name_fg"],
            selectbackground=C["accent"], selectforeground=C["fg_on_dark"],
            relief="flat", highlightthickness=1,
            highlightbackground=C["border"], activestyle="none",
        )
        sb.config(command=self._listbox.yview)
        self._listbox.pack(side="left", fill="both", expand=True)

        ctrl = tk.Frame(self, bg=C["card_bg"], padx=12, pady=4)
        ctrl.pack(fill="x")
        for label, cmd in (("▲ Up", self._move_up), ("▼ Down", self._move_down),
                           ("✕ Remove", self._remove_selected)):
            tk.Button(ctrl, text=label, command=cmd,
                      bg="#e8eaf0", fg=C["name_fg"],
                      activebackground=C["card_hover"], relief="flat",
                      bd=0, padx=10, pady=4, cursor="hand2",
                      font=("Segoe UI", 9)).pack(side="left", padx=2)

        pf = tk.Frame(self, bg=C["card_bg"], padx=12, pady=6)
        pf.pack(fill="x")
        tk.Label(pf, text="Step preset:", bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8)).pack(side="left")
        self._step_preset_var = tk.StringVar()
        self._step_preset_combo = ttk.Combobox(
            pf, textvariable=self._step_preset_var,
            state="disabled", font=("Segoe UI", 9), width=30,
        )
        self._step_preset_combo.pack(side="left", padx=(6, 0), fill="x", expand=True)
        self._step_preset_combo.bind("<<ComboboxSelected>>", self._on_step_preset_change)
        self._listbox.bind("<ButtonRelease-1>", self._on_step_select)
        self._listbox.bind("<KeyRelease>", self._on_step_select)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        af = tk.Frame(self, bg=C["card_bg"], padx=16, pady=10)
        af.pack(fill="x")
        tk.Label(af, text="Add Step", bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        combo_row = tk.Frame(af, bg=C["card_bg"])
        combo_row.pack(fill="x")
        scripts = [s for s in db.list_all() if (s[8] or "") == group_name]
        name_count: dict[str, int] = {}
        for s in scripts:
            name_count[s[1]] = name_count.get(s[1], 0) + 1
        self._script_map: dict[str, int] = {}
        for s in scripts:
            lbl = s[1] if name_count[s[1]] == 1 else f"{s[1]}  ({Path(s[2]).name})"
            self._script_map[lbl] = s[0]
        keys = list(self._script_map.keys())
        self._combo_var = tk.StringVar(value=keys[0] if keys else "")
        self._add_combo = ttk.Combobox(
            combo_row, textvariable=self._combo_var,
            values=keys, state="readonly", font=("Segoe UI", 9),
        )
        self._add_combo.pack(side="left", fill="x", expand=True)
        tk.Button(combo_row, text="Add", command=self._add_step,
                  bg=C["accent"], fg=C["fg_on_dark"], activebackground=C["accent2"],
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="left", padx=(6, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        br = tk.Frame(self, bg=C["card_bg"], padx=16, pady=12)
        br.pack(fill="x")
        tk.Button(br, text="Save", command=self._save,
                  bg=C["accent"], fg=C["fg_on_dark"], activebackground=C["accent2"],
                  relief="flat", padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="right")
        tk.Button(br, text="Cancel", command=self.destroy,
                  bg="#e0e0e0", fg="#333333",
                  activebackground="#d0d0d0", relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 9)).pack(side="right", padx=(0, 8))

        self._reloading = False
        self._preset_changing = False
        self._reload_steps()

    def _on_step_select(self, _event=None):
        if self._reloading or self._preset_changing:
            return
        idx = self._selected_index()
        if idx is None:
            self._step_preset_combo.configure(state="disabled", values=[])
            self._step_preset_var.set("")
            return
        step_id, sid, name, path, params, interp, params_override = self._steps[idx]
        presets = self.db.list_param_presets(sid)
        values = ["(Script default)"] + [p[2] for p in presets]
        self._step_preset_combo.configure(
            state="readonly" if presets else "disabled", values=values)
        self._step_preset_var.set(
            params_override if params_override in values else "(Script default)")

    def _on_step_preset_change(self, _event=None):
        self._preset_changing = True
        try:
            idx = self._selected_index()
            if idx is None:
                return
            step_id, sid, name = self._steps[idx][0], self._steps[idx][1], self._steps[idx][2]
            chosen = self._step_preset_var.get()
            override = None if chosen == "(Script default)" else chosen
            self.db.update_pipeline_step_params(step_id, override)
            step = list(self._steps[idx])
            step[6] = override
            self._steps[idx] = tuple(step)
            label = f"  {idx + 1}.  {name}"
            if override is not None:
                label += f"  [{override}]"
            self._listbox.delete(idx)
            self._listbox.insert(idx, label)
            self._listbox.selection_set(idx)
        finally:
            self._preset_changing = False

    def _reload_steps(self):
        self._reloading = True
        self._steps = list(self.db.list_pipeline_steps(self.pipeline_id))
        self._listbox.delete(0, tk.END)
        for i, (step_id, sid, name, path, params, interp, params_override) in enumerate(self._steps):
            label = f"  {i + 1}.  {name}"
            if params_override is not None:
                label += f"  [{params_override}]"
            self._listbox.insert(tk.END, label)
        self._reloading = False

    def _selected_index(self) -> int | None:
        sel = self._listbox.curselection()
        return sel[0] if sel else None

    def _add_step(self):
        sel = self._combo_var.get()
        script_id = self._script_map.get(sel)
        if script_id is None:
            return
        self.db.add_pipeline_step(self.pipeline_id, script_id)
        self._reload_steps()
        self._listbox.selection_set(tk.END)

    def _remove_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        step_id = self._steps[idx][0]
        self.db.remove_pipeline_step(step_id)
        self._reload_steps()

    def _move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return
        ids = [s[0] for s in self._steps]
        ids[idx], ids[idx - 1] = ids[idx - 1], ids[idx]
        self.db.reorder_pipeline_steps(self.pipeline_id, ids)
        self._reload_steps()
        self._listbox.selection_set(idx - 1)

    def _move_down(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self._steps) - 1:
            return
        ids = [s[0] for s in self._steps]
        ids[idx], ids[idx + 1] = ids[idx + 1], ids[idx]
        self.db.reorder_pipeline_steps(self.pipeline_id, ids)
        self._reload_steps()
        self._listbox.selection_set(idx + 1)

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Name Required", "Enter a pipeline name.", parent=self)
            return
        self.db.rename_pipeline(self.pipeline_id, name)
        self.on_save()
        self.destroy()
