"""Card widgets for scripts and pipelines."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..db import ScriptDB
from ..interpreter import _script_tag
from .dialogs import ScriptDialog, _PresetEntryDialog, _TempParamDialog
from .theme import C
from .widgets import ScrollingLabel, Tooltip


class ScriptCard(tk.Frame):
    """A single styled card: accent strip + name/path + Modify + Run."""

    # Displayed label for the always-available empty preset; maps to "" params.
    _EMPTY_LABEL = "(no parameters)"

    def __init__(self, parent, record, db: ScriptDB, runner, on_refresh,
                 on_move_up, on_move_down, on_move_top, *,
                 group_base_dir: str = ""):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        sid, name, path, params, interp, _created, last_run, last_run_status, _group, temp_param = record
        self.script_id = sid
        self._name = name
        self._group_name = _group or ""
        self.db = db
        self.runner = runner
        self.on_refresh = on_refresh
        self.selected = tk.BooleanVar(value=False)

        tk.Frame(self, bg=C["accent"], width=5).pack(side="left", fill="y")

        self._chk = tk.Checkbutton(self, variable=self.selected,
                                   bg=C["card_bg"], activebackground=C["card_bg"],
                                   relief="flat", bd=0, cursor="hand2")

        self._on_move_top = on_move_top
        self._on_move_up  = on_move_up
        self._on_move_down = on_move_down

        btn_area = tk.Frame(self, bg=C["border"])
        btn_area.pack(side="right", fill="y")

        def _sep():
            tk.Frame(btn_area, bg=C["border"], width=1).pack(side="left", fill="y")

        def _rbtn(text, bg, hover_bg, cmd, tip=None, **kw):
            b = tk.Button(btn_area, text=text, bg=bg,
                          fg=kw.get("fg", C["name_fg"]),
                          activebackground=hover_bg,
                          activeforeground=kw.get("active_fg", kw.get("fg", C["name_fg"])),
                          disabledforeground=kw.get("disabled_fg", "#444444"),
                          relief="flat", bd=0, font=("Segoe UI", 10),
                          width=3, state=kw.get("state", "normal"),
                          cursor="hand2" if kw.get("state", "normal") == "normal" else "arrow",
                          command=cmd)
            b._bg  = bg
            b._hbg = hover_bg
            b.pack(side="left", fill="y")
            if kw.get("state", "normal") == "normal":
                b.bind("<Enter>", lambda e, _b=b: _b.config(bg=_b._hbg), add="+")
                b.bind("<Leave>", lambda e, _b=b: _b.config(bg=_b._bg),  add="+")
            if tip:
                Tooltip(b, tip)
            return b

        self._text_area = text_area = tk.Frame(self, bg=C["card_bg"], padx=12, pady=10)
        text_area.pack(side="left", fill="both", expand=True)

        tag_text, tag_bg = _script_tag(path)
        badge_row = tk.Frame(text_area, bg=C["card_bg"])
        badge_row.pack(anchor="w", fill="x", pady=(0, 2))
        tk.Label(badge_row, text=tag_text, bg=tag_bg, fg=C["fg_on_dark"],
                 font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left")
        if temp_param:
            temp_badge = tk.Label(badge_row, text="⏱ TEMP PARAM", bg=C["accent"],
                                  fg=C["fg_on_dark"], font=("Segoe UI", 8, "bold"),
                                  padx=5, pady=1)
            temp_badge.pack(side="left", padx=(4, 0))
            Tooltip(temp_badge, "Asks for a temporary parameter on each run (not saved)")
        ScrollingLabel(text_area, name, C["name_fg"], C["card_bg"]).pack(fill="x")
        display_path = path
        if group_base_dir and path:
            try:
                rel = os.path.relpath(path, group_base_dir)
                if not rel.startswith(".."):
                    display_path = rel
            except ValueError:
                pass
        tk.Label(text_area, text=display_path, bg=C["card_bg"], fg=C["path_fg"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x")

        if last_run and last_run != "-":
            meta_row = tk.Frame(text_area, bg=C["card_bg"])
            meta_row.pack(fill="x")
            tk.Label(meta_row, text=f"Last run: {last_run}", bg=C["card_bg"],
                     fg=C["path_fg"], font=("Segoe UI", 7, "italic"), anchor="w").pack(side="left")
            if last_run_status == "error":
                tk.Label(meta_row, text="✕ Failed", bg=C["error"], fg=C["fg_on_dark"],
                         font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left", padx=(6, 0))
            elif last_run_status == "ok":
                tk.Label(meta_row, text="✓ OK", bg=C["ok"], fg=C["fg_on_dark"],
                         font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left", padx=(6, 0))

        self._params_combo = None
        presets = db.list_param_presets(sid)
        if presets:
            # Always offer an empty preset at the top (shown with a clear label)
            # so a script can be run with no parameters regardless of its presets.
            preset_values = [self._EMPTY_LABEL] + [p[2] for p in presets if p[2] != ""]
            self._params_combo = ttk.Combobox(
                text_area, values=preset_values,
                state="readonly", font=("Segoe UI", 8),
                style="Card.TCombobox",
            )
            self._params_combo.pack(fill="x", pady=(4, 0))
            if params and params in preset_values:
                self._params_combo.set(params)
            else:
                self._params_combo.current(0)

        _sep()
        _rbtn("⚙", C["btn_neutral_bg"], C["btn_neutral_hover"], self._modify,
              fg=C["btn_neutral_fg"], tip="Edit")
        _sep()
        _rbtn("▶+", C["btn_neutral_bg"], C["btn_neutral_hover"], self._run_with_param,
              fg=C["btn_neutral_fg"], tip="Run with parameter")
        _sep()
        _rbtn("▶", C["btn_run_bg"], C["btn_run_hover"], self._run, tip="Run")

        for widget in (self, text_area):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self._bind_right_click(self)

    def show_checkbox(self, command=None):
        self._chk.config(command=command)
        self._chk.pack(side="left", padx=(6, 0), before=self._text_area)

    def hide_checkbox(self):
        self._chk.pack_forget()
        self.selected.set(False)

    def _on_enter(self, _e=None):
        self._set_card_bg(self, C["card_hover"])

    def _on_leave(self, _e=None):
        self._set_card_bg(self, C["card_bg"])

    def _set_card_bg(self, widget, color):
        try:
            if widget.cget("bg") in (C["card_bg"], C["card_hover"]):
                widget.config(bg=color)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._set_card_bg(child, color)

    def _bind_right_click(self, widget):
        widget.bind("<Button-3>", self._card_context_menu)
        for child in widget.winfo_children():
            self._bind_right_click(child)

    def _card_context_menu(self, event):
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg=C["menu_bg"], fg=C["fg_on_dark"],
                       activebackground=C["accent"], activeforeground=C["fg_on_dark"],
                       font=("Segoe UI", 10))
        menu.add_command(label="⤒  Move to Top", command=self._on_move_top)
        menu.add_command(label="▲  Move Up",     command=self._on_move_up)
        menu.add_command(label="▼  Move Down",   command=self._on_move_down)
        menu.add_separator()
        menu.add_command(label="⧉  Clone",       command=self._clone)
        menu.add_separator()
        menu.add_command(label="🗑  Delete",      command=self._delete_card,
                         foreground=C["menu_danger"], activeforeground=C["menu_danger"])
        menu.tk_popup(event.x_root, event.y_root)

    def _modify(self):
        ScriptDialog(self.winfo_toplevel(), self.db,
                     script_id=self.script_id, on_save=self.on_refresh,
                     existing_groups=self.db.list_groups(),
                     group_base_dirs={name: bd for name, bd in self.db.list_groups_with_meta()})

    def _clone(self):
        rec = self.db.get(self.script_id)
        if rec:
            _, name, path, params, interp, grp, temp_param = rec
            self.db.add(f"{name} (copy)", path, params, interp, grp, temp_param)
            self.on_refresh()

    def _delete_card(self):
        if messagebox.askyesno("Delete", f"Delete '{self._name}'?", parent=self):
            self.db.delete(self.script_id)
            self.on_refresh()

    def _selected_params(self, fallback: str) -> str:
        """Return the combo's selected params, mapping the empty-preset label to ''."""
        if not self._params_combo:
            return fallback
        value = self._params_combo.get()
        return "" if value == self._EMPTY_LABEL else value

    def _run(self):
        rec = self.db.get(self.script_id)
        if not rec:
            return
        _, name, path, params, interp, _grp, temp_param = rec
        params = self._selected_params(params)
        if temp_param:
            dlg = _TempParamDialog(self.winfo_toplevel(), saved_params=params,
                                   title=f"Run with temp param — {name}")
            self.wait_window(dlg)
            if dlg.cancelled:
                return
            extra = dlg.result.strip()
            if extra:
                params = f"{params} {extra}".strip()
        self.runner(self.script_id, name, path, params, interp)

    def _run_with_param(self):
        rec = self.db.get(self.script_id)
        if not rec:
            return
        _, name, path, default_params, interp, _grp, _temp = rec
        script_id = self.script_id
        runner = self.runner
        on_refresh = self.on_refresh
        db = self.db
        current = self._selected_params(default_params)

        dlg = _PresetEntryDialog(self.winfo_toplevel(), current, title="Run with Parameters")
        self.wait_window(dlg)
        if dlg.result is None:
            return

        chosen = dlg.result
        existing = db.list_param_presets(script_id)
        if not any(p[2] == chosen for p in existing):
            db.replace_param_presets(script_id, [(p[1], p[2]) for p in existing] + [(chosen, chosen)])
        db.update(script_id, name, path, chosen, interp, _grp)
        on_refresh()

        runner(script_id, name, path, chosen, interp)


class PipelineCard(tk.Frame):
    """Card displaying a pipeline and its steps summary."""
    _PIPE_ACCENT  = C["pipe_accent"]
    _PIPE_ACCENT2 = C["pipe_accent2"]

    def __init__(self, parent, pipeline_id: int, name: str, db: ScriptDB,
                 group_name: str, on_run, on_edit, on_refresh):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.pipeline_id = pipeline_id
        self._name = name
        self._group_name = group_name
        self.db = db
        self.on_run = on_run
        self.on_edit = on_edit
        self.on_refresh = on_refresh

        steps = db.list_pipeline_steps(pipeline_id)

        tk.Frame(self, bg=self._PIPE_ACCENT, width=5).pack(side="left", fill="y")

        btn_area = tk.Frame(self, bg=C["border"])
        btn_area.pack(side="right", fill="y")

        def _sep():
            tk.Frame(btn_area, bg=C["border"], width=1).pack(side="left", fill="y")

        def _rbtn(text, bg, hover_bg, cmd, tip=None, **kw):
            b = tk.Button(btn_area, text=text, bg=bg,
                          fg=kw.get("fg", C["name_fg"]),
                          activebackground=hover_bg,
                          activeforeground=kw.get("active_fg", kw.get("fg", C["name_fg"])),
                          disabledforeground=kw.get("disabled_fg", "#444444"),
                          relief="flat", bd=0, font=("Segoe UI", 10),
                          width=3, state=kw.get("state", "normal"),
                          cursor="hand2" if kw.get("state", "normal") == "normal" else "arrow",
                          command=cmd)
            b._bg  = bg
            b._hbg = hover_bg
            b.pack(side="left", fill="y")
            if kw.get("state", "normal") == "normal":
                b.bind("<Enter>", lambda e, _b=b: _b.config(bg=_b._hbg), add="+")
                b.bind("<Leave>", lambda e, _b=b: _b.config(bg=_b._bg),  add="+")
            if tip:
                Tooltip(b, tip)
            return b

        _sep()
        _rbtn("⚙", C["btn_neutral_bg"], C["btn_neutral_hover"],
              lambda: on_edit(pipeline_id, name), tip="Edit",
              fg=C["btn_neutral_fg"])
        _sep()
        _rbtn("▶", C["btn_run_bg"], C["btn_run_hover"],
              lambda: on_run(pipeline_id, name), tip="Run")

        content = tk.Frame(self, bg=C["card_bg"], padx=12, pady=10)
        content.pack(side="left", fill="both", expand=True)
        self._content = content

        badge_row = tk.Frame(content, bg=C["card_bg"])
        badge_row.pack(fill="x")
        tk.Label(badge_row, text="⚡ PIPELINE", bg=self._PIPE_ACCENT, fg=C["fg_on_dark"],
                 font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left")

        ScrollingLabel(content, name, C["name_fg"], C["card_bg"]).pack(fill="x", pady=(2, 0))

        n = len(steps)
        if n == 0:
            summary_text = "No steps — click ⚙ to add scripts"
        else:
            parts = [s[2] for s in steps[:4]]
            summary_text = "  →  ".join(parts)
            if n > 4:
                summary_text += f"  →  +{n - 4} more"
            if len(summary_text) > 55:
                summary_text = summary_text[:55] + "…"

        summary_row = tk.Frame(content, bg=C["card_bg"],
                               cursor="hand2" if n > 0 else "")
        summary_row.pack(fill="x")
        self._summary_row = summary_row
        if n > 0:
            tk.Label(summary_row, text="▸ ", bg=C["card_bg"], fg=C["path_fg"],
                     font=("Segoe UI", 8), cursor="hand2").pack(side="left")
        tk.Label(summary_row, text=f"{n} step{'s' if n != 1 else ''}  ·  {summary_text}",
                 bg=C["card_bg"], fg=C["path_fg"], font=("Segoe UI", 8), anchor="w",
                 cursor="hand2" if n > 0 else "").pack(side="left", fill="x", expand=True)

        if n > 0:
            for w in (summary_row, *summary_row.winfo_children()):
                w.bind("<Button-1>", self._show_steps_popup)

        for widget in (self, content):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self._bind_right_click_all(self)

    def _show_steps_popup(self, event=None):
        existing = getattr(self, "_steps_popup", None)
        if existing:
            try:
                existing.destroy()
            except tk.TclError:
                pass
            self._steps_popup = None
            return

        steps = self.db.list_pipeline_steps(self.pipeline_id)

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=C["border"])
        self._steps_popup = popup

        inner = tk.Frame(popup, bg=C["card_bg"], padx=14, pady=10)
        inner.pack(padx=1, pady=1)

        tk.Label(inner, text=self._name, bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=(0, 6))

        if not steps:
            tk.Label(inner, text="No steps yet.", bg=C["card_bg"], fg=C["path_fg"],
                     font=("Segoe UI", 8)).pack(anchor="w")
        else:
            for i, step in enumerate(steps, 1):
                row = tk.Frame(inner, bg=C["card_bg"])
                row.pack(fill="x", pady=2)
                tk.Label(row, text=f"{i}.", bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 8), width=3, anchor="e").pack(side="left")
                tk.Label(row, text=step[2], bg=C["card_bg"], fg=C["name_fg"],
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=(6, 0))
                tk.Label(row, text=step[3], bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(6, 0))
                if len(step) > 6 and step[6] is not None:
                    tk.Label(row, text=f"[{step[6]}]", bg=C["card_bg"], fg=C["accent"],
                             font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(4, 0))

        popup.update_idletasks()
        pw, ph = popup.winfo_reqwidth(), popup.winfo_reqheight()
        sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
        x = min((event.x_root + 12) if event else self.winfo_rootx(), sw - pw - 8)
        y = min((event.y_root + 12) if event else self.winfo_rooty(), sh - ph - 8)
        popup.geometry(f"+{x}+{y}")

        popup.bind("<Escape>", lambda e: popup.destroy())
        popup.bind("<FocusOut>", lambda e: popup.destroy())
        popup.focus_set()

    def _bind_right_click_all(self, widget):
        widget.bind("<Button-3>", self._context_menu)
        for ch in widget.winfo_children():
            self._bind_right_click_all(ch)

    def _on_enter(self, _e=None):
        self._set_bg(self, C["card_hover"])

    def _on_leave(self, _e=None):
        self._set_bg(self, C["card_bg"])

    def _set_bg(self, widget, color):
        try:
            if widget.cget("bg") in (C["card_bg"], C["card_hover"]):
                widget.configure(bg=color)
        except tk.TclError:
            pass
        for ch in widget.winfo_children():
            self._set_bg(ch, color)

    def _context_menu(self, event):
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg=C["menu_bg"], fg=C["fg_on_dark"],
                       activebackground=C["accent"], activeforeground=C["fg_on_dark"],
                       font=("Segoe UI", 10))
        menu.add_command(label="⚙  Edit",
                         command=lambda: self.on_edit(self.pipeline_id, self._name))
        menu.add_command(label="⧉  Clone", command=self._clone)
        menu.add_separator()
        menu.add_command(label="🗑  Delete", command=self._delete,
                         foreground=C["menu_danger"], activeforeground=C["menu_danger"])
        menu.tk_popup(event.x_root, event.y_root)

    def _clone(self):
        self.db.clone_pipeline(self.pipeline_id)
        self.on_refresh()

    def _delete(self):
        if messagebox.askyesno("Delete Pipeline",
                                f"Delete pipeline '{self._name}'?", parent=self):
            self.db.delete_pipeline(self.pipeline_id)
            self.on_refresh()
