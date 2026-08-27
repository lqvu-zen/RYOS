"""Card widgets for scripts and pipelines."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

from ..db import TRIGGER_WITH, ScriptDB
from ..interpreter import _script_tag
from .dialogs import ScriptDialog, _PresetEntryDialog, _TempParamDialog
from .theme import C
from .widgets import HoverPreview, ScrollingLabel, Tooltip

_COMPACT: bool = False


def set_compact_mode(enabled: bool) -> None:
    global _COMPACT
    _COMPACT = enabled


_HOVER_PREVIEW: bool = True


def set_hover_preview(enabled: bool) -> None:
    global _HOVER_PREVIEW
    _HOVER_PREVIEW = enabled


_CARD_SIZE: str = "medium"


def set_card_size(size: str) -> None:
    global _CARD_SIZE
    _CARD_SIZE = size


# Padding table: (padx, pady) for card body frame.
_CARD_PADDING = {
    # (compact, size): (padx, pady)
    (False, "small"):  (12,  6),
    (False, "medium"): (12, 10),
    (False, "large"):  (12, 14),
    (True,  "small"):  (10,  2),
    (True,  "medium"): (10,  4),
    (True,  "large"):  (10,  8),
}

# Hover dwell before the compact-mode detail preview appears.
_PREVIEW_DELAY_MS = 1000

# Row metrics: (row_pady, row_ipady, stop_pady, name_pady)
_ROW_METRICS = {
    (False, "small"):  (3, 1, 3, 4),
    (False, "medium"): (5, 2, 5, 6),
    (False, "large"):  (8, 4, 7, 9),
    (True,  "small"):  (1, 0, 1, 1),
    (True,  "medium"): (2, 0, 2, 2),
    (True,  "large"):  (5, 2, 4, 5),
}


def card_padding() -> tuple[int, int]:
    """Return (padx, pady) for the card body frame based on current mode and size."""
    return _CARD_PADDING.get((_COMPACT, _CARD_SIZE), _CARD_PADDING[(_COMPACT, "medium")])


def row_metrics() -> tuple[int, int, int, int]:
    """Return (row_pady, row_ipady, stop_pady, name_pady) for running rows and card packing."""
    return _ROW_METRICS.get((_COMPACT, _CARD_SIZE), _ROW_METRICS[(_COMPACT, "medium")])


class ScriptCard(tk.Frame):
    """A single styled card: accent strip + name/path + Modify + Run."""

    # Displayed label for the always-available empty preset; maps to "" params.
    _EMPTY_LABEL = "(no parameters)"

    def __init__(self, parent, record, db: ScriptDB, runner, on_refresh,
                 on_move_up, on_move_down, on_move_top, *,
                 group_base_dir: str = "", on_toggle_favorite=None):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        sid, name, path, params, interp, _created, last_run, last_run_status, _group, temp_param = record[:10]
        is_favorite = record[10] if len(record) > 10 else 0
        self._is_favorite = bool(is_favorite)
        self._sid = sid
        self._on_toggle_favorite = on_toggle_favorite
        self.script_id = sid
        self._name = name
        self._path = path
        self._params = params
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

        _pad_x, _pad_y = card_padding()
        self._text_area = text_area = tk.Frame(self, bg=C["card_bg"], padx=_pad_x, pady=_pad_y)
        text_area.pack(side="left", fill="both", expand=True)

        if not _COMPACT:
            tag_text, tag_bg = _script_tag(path)
            # Row 1: type badge(s) + name on one line
            name_row = tk.Frame(text_area, bg=C["card_bg"])
            name_row.pack(fill="x", pady=(0, 2))
            tk.Label(name_row, text=tag_text, bg=tag_bg, fg=C["fg_on_dark"],
                     font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left", padx=(0, 6))
            if temp_param:
                temp_badge = tk.Label(name_row, text="⏱ TEMP PARAM", bg=C["accent"],
                                      fg=C["fg_on_dark"], font=("Segoe UI", 8, "bold"),
                                      padx=5, pady=1)
                temp_badge.pack(side="left", padx=(0, 6))
                Tooltip(temp_badge, "Asks for a temporary parameter on each run (not saved)")
            ScrollingLabel(name_row, name, C["name_fg"], C["card_bg"]).pack(side="left", fill="both", expand=True)
        else:
            ScrollingLabel(text_area, name, C["name_fg"], C["card_bg"]).pack(fill="x")
        if not _COMPACT:
            display_path = path
            if group_base_dir and path:
                try:
                    rel = os.path.relpath(path, group_base_dir)
                    if not rel.startswith(".."):
                        display_path = rel
                except ValueError:
                    pass
            # Row 2: path + last-run timestamp + status badge on one line
            has_run = last_run and last_run != "-"
            if display_path or has_run:
                sub_row = tk.Frame(text_area, bg=C["card_bg"])
                sub_row.pack(fill="x")
                if display_path:
                    tk.Label(sub_row, text=display_path, bg=C["card_bg"], fg=C["path_fg"],
                             font=("Segoe UI", 8), anchor="w").pack(side="left")
                if has_run:
                    sep = "  ·  " if display_path else ""
                    tk.Label(sub_row, text=f"{sep}{last_run}", bg=C["card_bg"],
                             fg=C["path_fg"], font=("Segoe UI", 8), anchor="w").pack(side="left")
                    if last_run_status == "error":
                        tk.Label(sub_row, text="✕ Failed", bg=C["error"], fg=C["fg_on_dark"],
                                 font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left", padx=(6, 0))
                    elif last_run_status == "ok":
                        tk.Label(sub_row, text="✓ OK", bg=C["ok"], fg=C["fg_on_dark"],
                                 font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left", padx=(6, 0))

        self._params_combo = None
        presets = db.list_param_presets(sid)
        if presets and not _COMPACT:
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

        fav_text = "★" if self._is_favorite else "☆"
        fav_bg  = C["accent_wash"]    if self._is_favorite else C["btn_neutral_bg"]
        fav_hbg = C["btn_neutral_hover"]
        fav_fg  = C["bolt"]           if self._is_favorite else C["btn_neutral_fg"]
        fav_tip = "Remove from favorites" if self._is_favorite else "Add to favorites"
        self._fav_btn = _rbtn(fav_text, fav_bg, fav_hbg,
                              self._toggle_favorite,
                              fg=fav_fg, tip=fav_tip)
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

        if _COMPACT and _HOVER_PREVIEW:
            HoverPreview(self, self._text_area, self._build_preview, delay=_PREVIEW_DELAY_MS)

        self._bind_right_click(self)

    def _build_preview(self, inner):
        inner.configure(padx=14, pady=10)

        tk.Label(inner, text=self._name, bg=C["card_bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=(0, 6))

        def _row(label, value, value_fg=C["name_fg"]):
            r = tk.Frame(inner, bg=C["card_bg"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=C["card_bg"], fg=C["path_fg"],
                     font=("Segoe UI", 8), anchor="w", width=10).pack(side="left")
            tk.Label(r, text=value, bg=C["card_bg"], fg=value_fg,
                     font=("Segoe UI", 8), anchor="w").pack(side="left")

        _row("Path", self._path or "—")
        _row("Params", self._params if self._params else "—",
             value_fg=C["name_fg"] if self._params else C["path_fg"])

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
        except tk.TclError:
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
        fav_label = "☆ Remove from Favorites" if self._is_favorite else "★ Add to Favorites"
        menu.add_command(label=fav_label, command=self._toggle_favorite)
        menu.add_separator()
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

    def _toggle_favorite(self):
        if self._on_toggle_favorite:
            self._on_toggle_favorite(self._sid, not self._is_favorite)
        else:
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
                 group_name: str, on_run, on_edit, on_refresh,
                 is_favorite: bool = False, on_toggle_favorite=None):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        self.pipeline_id = pipeline_id
        self._name = name
        self._group_name = group_name
        self.db = db
        self.on_run = on_run
        self.on_edit = on_edit
        self.on_refresh = on_refresh
        self._is_favorite = is_favorite
        self._on_toggle_favorite = on_toggle_favorite

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

        pipe_fav_text = "★" if is_favorite else "☆"
        pipe_fav_bg  = C["accent_wash"]    if is_favorite else C["btn_neutral_bg"]
        pipe_fav_hbg = C["btn_neutral_hover"]
        pipe_fav_fg  = C["bolt"]           if is_favorite else C["btn_neutral_fg"]
        pipe_fav_tip = "Remove from favorites" if is_favorite else "Add to favorites"
        self._fav_btn = _rbtn(pipe_fav_text, pipe_fav_bg, pipe_fav_hbg,
                              self._toggle_favorite,
                              fg=pipe_fav_fg, tip=pipe_fav_tip)
        _sep()
        _rbtn("⚙", C["btn_neutral_bg"], C["btn_neutral_hover"],
              lambda: on_edit(pipeline_id, name), tip="Edit",
              fg=C["btn_neutral_fg"])
        _sep()
        _rbtn("▶", C["btn_run_bg"], C["btn_run_hover"],
              lambda: on_run(pipeline_id, name), tip="Run")

        _pad_x, _pad_y = card_padding()
        content = tk.Frame(self, bg=C["card_bg"], padx=_pad_x, pady=_pad_y)
        content.pack(side="left", fill="both", expand=True)
        self._content = content

        if not _COMPACT:
            # Badge + name on one line
            name_row = tk.Frame(content, bg=C["card_bg"])
            name_row.pack(fill="x")
            tk.Label(name_row, text="⚡ PIPELINE", bg=self._PIPE_ACCENT, fg=C["fg_on_dark"],
                     font=("Segoe UI", 8, "bold"), padx=5, pady=1).pack(side="left", padx=(0, 6))
            name_label = ScrollingLabel(name_row, name, C["name_fg"], C["card_bg"])
            name_label.pack(side="left", fill="both", expand=True)
        else:
            name_label = ScrollingLabel(content, name, C["name_fg"], C["card_bg"])
            name_label.pack(fill="x")

        n = len(steps)
        if _COMPACT:
            # Steps summary hidden; bind popup to name label so step detail stays reachable.
            self._summary_row = None
            if n > 0:
                name_label.bind("<Button-1>", self._show_steps_popup)
        else:
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

        if _COMPACT and _HOVER_PREVIEW:
            HoverPreview(self, self._content, self._build_preview, delay=_PREVIEW_DELAY_MS)

        self._bind_right_click_all(self)

    def _render_steps_into(self, inner):
        """Build the ordered step list into `inner`. Shared by the click popup
        and the hover preview so both always show the current step list."""
        steps = self.db.list_pipeline_steps(self.pipeline_id)

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
                idx_text = "∥" if len(step) > 7 and step[7] == TRIGGER_WITH else f"{i}."
                tk.Label(row, text=idx_text, bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 8), width=3, anchor="e").pack(side="left")
                tk.Label(row, text=step[2], bg=C["card_bg"], fg=C["name_fg"],
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=(6, 0))
                tk.Label(row, text=step[3], bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(6, 0))
                if len(step) > 6 and step[6] is not None:
                    tk.Label(row, text=f"[{step[6]}]", bg=C["card_bg"], fg=C["accent"],
                             font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(4, 0))

    def _build_preview(self, inner):
        inner.configure(padx=14, pady=10)
        self._render_steps_into(inner)

    def _show_steps_popup(self, event=None):
        existing = getattr(self, "_steps_popup", None)
        if existing:
            try:
                existing.destroy()
            except tk.TclError:
                pass
            self._steps_popup = None
            return

        popup = tk.Toplevel(self.winfo_toplevel())
        popup.overrideredirect(True)
        popup.configure(bg=C["border"])
        self._steps_popup = popup

        inner = tk.Frame(popup, bg=C["card_bg"], padx=14, pady=10)
        inner.pack(padx=1, pady=1)

        self._render_steps_into(inner)

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

    def _toggle_favorite(self):
        if self._on_toggle_favorite:
            self._on_toggle_favorite(self.pipeline_id, not self._is_favorite)
        else:
            self.on_refresh()

    def _context_menu(self, event):
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg=C["menu_bg"], fg=C["fg_on_dark"],
                       activebackground=C["accent"], activeforeground=C["fg_on_dark"],
                       font=("Segoe UI", 10))
        pipe_fav_label = "☆ Remove from Favorites" if self._is_favorite else "★ Add to Favorites"
        menu.add_command(label=pipe_fav_label, command=self._toggle_favorite)
        menu.add_separator()
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
