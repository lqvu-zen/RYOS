"""Pipeline editor dialog — manage step order and per-step param overrides."""
import tkinter as tk
from tkinter import messagebox, ttk

from ..db import (FAIL_STOP, WHEN_ALWAYS, ScriptDB)
from .. import pipelinesteps
from .placement import center_over_parent
from .theme import C, set_button_enabled


class PipelineEditorDialog(tk.Toplevel):
    """Manage a pipeline's step order, param overrides and per-step policy."""

    _FAIL_LABELS = pipelinesteps.FAIL_LABELS
    _WHEN_LABELS = pipelinesteps.WHEN_LABELS

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
        # Centred on the parent (so it opens on the same monitor) and clamped
        # to that monitor's work area, which the raw offset above did not do.
        center_over_parent(self, parent, 440, 520)

        nf = tk.Frame(self, bg=C["card_bg"], padx=16, pady=12)
        nf.pack(fill="x")
        tk.Label(nf, text="Pipeline Name", bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._name_var = tk.StringVar(value=pipeline_name)
        tk.Entry(nf, textvariable=self._name_var,
                 bg=C["card_bg"], fg=C["name_fg"], insertbackground=C["name_fg"],
                 relief="flat", bd=4, highlightthickness=1,
                 highlightbackground=C["border"],
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
            bg=C["card_bg"], fg=C["name_fg"],
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
                      bg=C["btn_neutral_bg"], fg=C["btn_neutral_fg"],
                      activebackground=C["btn_neutral_hover"],
                      activeforeground=C["btn_neutral_fg"], relief="flat",
                      bd=0, padx=10, pady=4, cursor="hand2",
                      font=("Segoe UI", 9)).pack(side="left", padx=2)
        self._trigger_btn = tk.Button(
            ctrl, text="∥ With Prev", command=self._toggle_trigger,
            bg=C["btn_neutral_bg"], fg=C["btn_neutral_fg"],
            activebackground=C["btn_neutral_hover"],
            activeforeground=C["btn_neutral_fg"], relief="flat",
            bd=0, padx=10, pady=4, cursor="hand2",
            font=("Segoe UI", 9))
        set_button_enabled(self._trigger_btn, False,
                           bg=C["btn_neutral_bg"], fg=C["btn_neutral_fg"])
        self._trigger_btn.pack(side="left", padx=2)

        legend = tk.Frame(self, bg=C["card_bg"], padx=12)
        legend.pack(fill="x")
        tk.Label(legend, text=pipelinesteps.LEGEND, wraplength=400, justify="left",
                 bg=C["card_bg"], fg=C["path_fg"], font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))

        opt = tk.Frame(self, bg=C["card_bg"], padx=12, pady=4)
        opt.pack(fill="x")
        tk.Label(opt, text="If it fails:", bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8)).pack(side="left")
        self._on_failure_var = tk.StringVar(value=self._FAIL_LABELS[FAIL_STOP])
        self._on_failure_combo = ttk.Combobox(
            opt, textvariable=self._on_failure_var, state="disabled",
            font=("Segoe UI", 9), width=22,
            values=list(self._FAIL_LABELS.values()))
        self._on_failure_combo.pack(side="left", padx=(6, 12))
        self._on_failure_combo.bind("<<ComboboxSelected>>", self._on_policy_change)

        tk.Label(opt, text="Retries:", bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8)).pack(side="left")
        self._retries_var = tk.StringVar(value="0")
        self._retries_combo = ttk.Combobox(
            opt, textvariable=self._retries_var, state="disabled",
            font=("Segoe UI", 9), width=4,
            values=[str(n) for n in pipelinesteps.RETRY_CHOICES])
        self._retries_combo.pack(side="left", padx=(6, 0))
        self._retries_combo.bind("<<ComboboxSelected>>", self._on_policy_change)

        opt2 = tk.Frame(self, bg=C["card_bg"], padx=12)
        opt2.pack(fill="x", pady=(0, 4))
        tk.Label(opt2, text="Run this step:", bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8)).pack(side="left")
        self._run_when_var = tk.StringVar(value=self._WHEN_LABELS[WHEN_ALWAYS])
        self._run_when_combo = ttk.Combobox(
            opt2, textvariable=self._run_when_var, state="disabled",
            font=("Segoe UI", 9), width=34,
            values=list(self._WHEN_LABELS.values()))
        self._run_when_combo.pack(side="left", padx=(6, 0))
        self._run_when_combo.bind("<<ComboboxSelected>>", self._on_policy_change)

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
        self._script_map: dict[str, int] = pipelinesteps.add_step_choices(
            db.list_all(), group_name)
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
                  bg=C["btn_neutral_bg"], fg=C["btn_neutral_fg"],
                  activebackground=C["btn_neutral_hover"],
                  activeforeground=C["btn_neutral_fg"], relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 9)).pack(side="right", padx=(0, 8))

        self._reloading = False
        self._preset_changing = False
        self._reload_steps()

    def _on_step_select(self, _event=None):
        if self._reloading or self._preset_changing:
            return
        idx = self._selected_index()
        set_button_enabled(self._trigger_btn, idx not in (None, 0),
                           bg=C["btn_neutral_bg"], fg=C["btn_neutral_fg"])
        for combo in (self._on_failure_combo, self._retries_combo, self._run_when_combo):
            combo.configure(state="readonly" if idx is not None else "disabled")
        if idx is None:
            self._step_preset_combo.configure(state="disabled", values=[])
            self._step_preset_var.set("")
            self._trigger_btn.configure(text="∥ With Prev")
            return
        row = self._steps[idx]
        on_failure, retries, run_when = pipelinesteps.policy_of(row)
        self._on_failure_var.set(self._FAIL_LABELS[on_failure])
        self._retries_var.set(str(retries))
        self._run_when_var.set(self._WHEN_LABELS[run_when])
        self._trigger_btn.configure(text=pipelinesteps.trigger_button_label(row))
        # Slice rather than unpack the whole row: list_pipeline_steps has grown
        # twice (trigger_mode, then env_vars/work_dir) and a fixed-arity unpack
        # broke here both times, silently emptying the step list.
        (step_id, sid, name, path, params, interp,
         params_override, trigger_mode) = self._steps[idx][:8]
        presets = self.db.list_param_presets(sid)
        values = pipelinesteps.preset_choices(presets)
        self._step_preset_combo.configure(
            state="readonly" if presets else "disabled", values=values)
        self._step_preset_var.set(pipelinesteps.preset_shown(params_override, values))

    def _on_policy_change(self, _event=None):
        """Write the three policy fields for the selected step."""
        if self._reloading or self._preset_changing:
            return
        idx = self._selected_index()
        if idx is None:
            return
        self.db.set_step_policy(
            self._steps[idx][0],
            **pipelinesteps.policy_from_labels(self._on_failure_var.get(),
                                               self._retries_var.get(),
                                               self._run_when_var.get()))
        self._reload_steps()
        self._listbox.selection_set(idx)
        self._on_step_select()

    def _on_step_preset_change(self, _event=None):
        self._preset_changing = True
        try:
            idx = self._selected_index()
            if idx is None:
                return
            step_id = self._steps[idx][0]
            override = pipelinesteps.override_from_choice(self._step_preset_var.get())
            self.db.update_pipeline_step_params(step_id, override)
            step = list(self._steps[idx])
            step[6] = override
            self._steps[idx] = tuple(step)
            # The shared label, so the policy marks survive a preset change.
            label = pipelinesteps.step_label(step, idx)
            self._listbox.delete(idx)
            self._listbox.insert(idx, label)
            self._listbox.selection_set(idx)
        finally:
            self._preset_changing = False

    def _reload_steps(self):
        self._reloading = True
        self._steps = list(self.db.list_pipeline_steps(self.pipeline_id))
        self._listbox.delete(0, tk.END)
        for label in pipelinesteps.step_labels(self._steps):
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
        self._on_step_select()      # keep the controls in step with the selection

    def _remove_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        step_id = self._steps[idx][0]
        self.db.remove_pipeline_step(step_id)
        self._reload_steps()
        self._on_step_select()      # nothing is selected now; disable the controls

    def _toggle_trigger(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return                      # step 1 has no previous step
        self.db.set_step_trigger_mode(self._steps[idx][0],
                                      pipelinesteps.toggled_trigger(self._steps[idx]))
        self._reload_steps()
        self._listbox.selection_set(idx)
        self._on_step_select()

    def _move_up(self):
        self._move(-1)

    def _move_down(self):
        self._move(+1)

    def _move(self, delta: int):
        """Move the selected step by one place, if it can go there."""
        idx = self._selected_index()
        # can_move already rejects None, but say so here so the narrowing is
        # visible to a reader and to the type checker.
        if idx is None or not pipelinesteps.can_move(idx, len(self._steps),
                                                     delta):
            return
        ids = pipelinesteps.reorder([s[0] for s in self._steps], idx, delta)
        self.db.reorder_pipeline_steps(self.pipeline_id, ids)
        self._reload_steps()
        self._listbox.selection_set(idx + delta)
        # Step 1 can't be "with prev", so the button has to be re-evaluated.
        self._on_step_select()

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning(*pipelinesteps.NAME_REQUIRED, parent=self)
            return
        self.db.rename_pipeline(self.pipeline_id, name)
        self.on_save()
        self.destroy()
