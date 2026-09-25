"""Card widgets for scripts and pipelines."""
import tkinter as tk
from tkinter import messagebox, ttk

from .. import cardmenu, cardstyle, scriptform
from ..db import ScriptDB
from ..interpreter import _script_tag
from .dialogs import (RunHistoryDialog, ScheduleDialog, ScriptDialog,
                      _PresetEntryDialog, _TempParamDialog)
from .placement import place_near
from ..themes import _readable_on, ink_on
from .theme import C, highlight_fg
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


# The tables live in ryos.cardstyle so the Qt cards lay out identically; this
# module only holds the current mode and size and binds them in.
_PREVIEW_DELAY_MS = cardstyle.PREVIEW_DELAY_MS


def card_padding() -> tuple[int, int]:
    """(padx, pady) for the card body frame, at the current mode and size."""
    return cardstyle.card_padding(_COMPACT, _CARD_SIZE)


def row_metrics() -> tuple[int, int, int, int]:
    """(row_pady, row_ipady, stop_pady, name_pady) at the current mode and size."""
    return cardstyle.row_metrics(_COMPACT, _CARD_SIZE)


def run_button_style(last_status: str | None) -> tuple:
    """(text, fg, active_fg, bg, hover, tooltip) for a card's Run button.

    The rule — after a failure the Run button *becomes* the retry — lives in
    `cardstyle.run_button()`, which returns palette keys. This resolves them
    against the live Tk palette; the Qt cards resolve the same keys through
    their stylesheet, so the two cannot drift.

    `active_fg` is the ink for the hovered fill and is not always `fg`: the
    retry state sits on `error`, a mid red, but hovers to `btn_stop_active`,
    a near-black one, and no single ink clears both.
    """
    spec = cardstyle.run_button(last_status)
    return (spec.glyph, C[spec.fg_key], ink_on(C[spec.hover_fg_key]),
            C[spec.bg_key], C[spec.hover_key], spec.tooltip)


def _status_badge(parent, status: str) -> "tk.Label | None":
    """The last-run status chip. Reports only — the Run button carries retry."""
    spec = cardstyle.status_badge(status)
    if spec is None:
        return None
    return tk.Label(parent, text=spec.text, bg=C[spec.bg_key],
                    fg=C[spec.fg_key], font=("Segoe UI", 8, "bold"),
                    padx=5, pady=1)


def _tag_badge(parent, spec) -> tk.Label:
    """A `cardstyle.TagBadge`, packed beside the card's name."""
    badge = tk.Label(parent, text=spec.text, bg=C[spec.bg_key], fg=C["fg_on_dark"],
                     font=("Segoe UI", 8, "bold"), padx=5, pady=1)
    badge.pack(side="left", padx=(0, 6))
    Tooltip(badge, spec.tooltip)
    return badge


def _popup_menu(owner: tk.Misc, items, on_pick) -> tk.Menu:
    """A Tk menu built from `cardmenu` entries; picking one calls on_pick(key).

    Highlight swatches are resolved against the *menu* background, not the
    card's, so they stay readable in the dark popup even over light cards.
    """
    style = dict(tearoff=0, bg=C["menu_bg"], fg=C["fg_on_dark"],
                 activebackground=C["accent"], activeforeground=C["fg_on_dark"],
                 font=("Segoe UI", 10))
    menu = tk.Menu(owner, **style)

    def fill(target: tk.Menu, entries) -> None:
        for item in entries:
            if item.key is None:
                target.add_separator()
            elif item.children:
                sub = tk.Menu(target, **style)
                fill(sub, item.children)
                target.add_cascade(label=item.label, menu=sub)
            else:
                extra = {}
                if item.danger:
                    extra = dict(foreground=C["menu_danger"],
                                 activeforeground=C["menu_danger"])
                elif item.highlight:
                    extra = dict(foreground=highlight_fg(item.highlight, C["menu_bg"]),
                                 activeforeground=C["fg_on_dark"])
                target.add_command(
                    label=item.label, command=lambda k=item.key: on_pick(k),
                    state="normal" if item.enabled else "disabled", **extra)

    fill(menu, items)
    return menu


class ScriptCard(tk.Frame):
    """A single styled card: accent strip + name/path + Modify + Run."""

    # Displayed label for the always-available empty preset; maps to "" params.
    _EMPTY_LABEL = scriptform.NO_PARAMS_LABEL

    def __init__(self, parent, record, db: ScriptDB, runner, on_refresh,
                 on_move_up, on_move_down, on_move_top, *,
                 group_base_dir: str = "", on_toggle_favorite=None,
                 scheduled: bool = False):
        super().__init__(parent, bg=C["card_bg"],
                         highlightbackground=C["border"], highlightthickness=1)
        sid, name, path, params, interp, _created, last_run, last_run_status, _group, temp_param = record[:10]
        is_favorite = record[10] if len(record) > 10 else 0
        self._is_favorite = bool(is_favorite)
        self._label_color = record[11] if len(record) > 11 else None
        self._scheduled = scheduled
        name_fg = highlight_fg(self._label_color) or C["name_fg"]
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
            for spec in cardstyle.script_badges(temp_param=bool(temp_param),
                                                 scheduled=bool(scheduled)):
                _tag_badge(name_row, spec)
            ScrollingLabel(name_row, name, name_fg, C["card_bg"]).pack(side="left", fill="both", expand=True)
        else:
            # Compact cards have no path/status row, so a failure would have
            # nowhere to show and the retry badge nowhere to live. Give it one
            # beside the name, and only when there is something to report --
            # a clean compact card stays exactly as it was.
            # Nothing extra in compact mode: a failure shows on the Run
            # button, which is present at every card size.
            ScrollingLabel(text_area, name, name_fg, C["card_bg"]).pack(fill="x")
        if not _COMPACT:
            display_path = cardstyle.display_path(path, group_base_dir or "")
            # Row 2: path + last-run timestamp + status badge on one line
            last_run = cardstyle.last_run_text(last_run)
            has_run = bool(last_run)
            if display_path or has_run:
                sub_row = tk.Frame(text_area, bg=C["card_bg"])
                sub_row.pack(fill="x")
                # Right-hand items are packed FIRST so they always get their
                # width; the path then takes whatever is left and is clipped.
                # Packed in reading order the path label (which can be very
                # long) consumed the whole row and squeezed the status badge to
                # 1px, so a failure was effectively invisible on any card with
                # a long path -- and the badge is now the retry control.
                if has_run:
                    badge = _status_badge(sub_row, last_run_status)
                    if badge is not None:
                        badge.pack(side="right", padx=(6, 0))
                    sep = "  ·  " if display_path else ""
                    tk.Label(sub_row, text=f"{sep}{last_run}", bg=C["card_bg"],
                             fg=C["path_fg"], font=("Segoe UI", 8),
                             anchor="e").pack(side="right")
                if display_path:
                    tk.Label(sub_row, text=display_path, bg=C["card_bg"], fg=C["path_fg"],
                             font=("Segoe UI", 8), anchor="w").pack(
                        side="left", fill="x", expand=True)

        self._params_combo = None
        choices = scriptform.card_param_choices(params, db.list_param_presets(sid))
        if choices and not _COMPACT:
            preset_values, selected = choices
            self._params_combo = ttk.Combobox(
                text_area, values=preset_values,
                state="readonly", font=("Segoe UI", 8),
                style="Card.TCombobox",
            )
            self._params_combo.pack(fill="x", pady=(4, 0))
            self._params_combo.set(selected)

        fav_text = "★" if self._is_favorite else "☆"
        fav_bg  = C["accent_wash"]    if self._is_favorite else C["btn_neutral_bg"]
        fav_hbg = C["btn_neutral_hover"]
        # Gold, shaded until it reads on the wash (1.2:1 on light themes).
        fav_fg  = (_readable_on(C["bolt"], (C["accent_wash"],)) if self._is_favorite
                   else C["btn_neutral_fg"])
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
        (_run_text, _run_fg, _run_afg,
         _run_bg, _run_hover, _run_tip) = run_button_style(last_run_status)
        _rbtn(_run_text, _run_bg, _run_hover, self._run,
              fg=_run_fg, active_fg=_run_afg, tip=_run_tip)

        for widget in (self, text_area):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        if _COMPACT and _HOVER_PREVIEW:
            HoverPreview(self, self._text_area, self._build_preview, delay=_PREVIEW_DELAY_MS)

        self._bind_right_click(self)

    def _build_preview(self, inner):
        inner.configure(padx=14, pady=10)

        tk.Label(inner, text=self._name, bg=C["card_bg"],
                 fg=highlight_fg(self._label_color) or C["name_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=(0, 6))

        def _row(label, value, value_fg=C["name_fg"]):
            r = tk.Frame(inner, bg=C["card_bg"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=C["card_bg"], fg=C["path_fg"],
                     font=("Segoe UI", 8), anchor="w", width=10).pack(side="left")
            tk.Label(r, text=value, bg=C["card_bg"], fg=value_fg,
                     font=("Segoe UI", 8), anchor="w").pack(side="left")

        for label, value, dim in cardstyle.script_preview_rows(self._path, self._params):
            _row(label, value, value_fg=C["path_fg"] if dim else C["name_fg"])

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
        items = cardmenu.script_menu(
            favorite=self._is_favorite, color=self._label_color,
            can_move_up=self._on_move_up is not None,
            can_move_down=self._on_move_down is not None)
        _popup_menu(self.winfo_toplevel(), items, self._on_menu).tk_popup(
            event.x_root, event.y_root)

    def _on_menu(self, key: str) -> None:
        is_pick, color = cardmenu.picked_highlight(key)
        if is_pick:
            self._set_label_color(color)
            return
        handler = {
            cardmenu.FAVORITE: self._toggle_favorite,
            cardmenu.MOVE_TOP: self._on_move_top,
            cardmenu.MOVE_UP: self._on_move_up,
            cardmenu.MOVE_DOWN: self._on_move_down,
            cardmenu.SCHEDULE: self._show_schedule,
            cardmenu.HISTORY: self._show_history,
            cardmenu.CLONE: self._clone,
            cardmenu.DELETE: self._delete_card,
        }.get(key)
        if handler is not None:
            handler()

    def _modify(self):
        ScriptDialog(self.winfo_toplevel(), self.db,
                     script_id=self.script_id, on_save=self.on_refresh,
                     existing_groups=self.db.list_groups(),
                     group_base_dirs={name: bd for name, bd in self.db.list_groups_with_meta()})

    def _clone(self):
        if cardmenu.clone(self.db, cardmenu.SCRIPT, self.script_id) is not None:
            self.on_refresh()

    def _delete_card(self):
        title, question = cardmenu.delete_prompt(
            cardmenu.SCRIPT, self._name, self.db.pipelines_using([self.script_id]))
        if messagebox.askyesno(title, question, parent=self):
            cardmenu.delete(self.db, cardmenu.SCRIPT, self.script_id)
            self.on_refresh()

    def _show_history(self):
        RunHistoryDialog(self.winfo_toplevel(), self.db,
                         script_id=self.script_id, title=self._name)

    def _show_schedule(self):
        ScheduleDialog(self.winfo_toplevel(), self.db, script_id=self.script_id,
                       title=self._name, on_save=self.on_refresh)

    def _set_label_color(self, key):
        self.db.set_script_color(self.script_id, key)
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
        return scriptform.params_from_choice(self._params_combo.get())

    def run(self) -> None:
        """Run this script exactly as its Run button does.

        The public entry point, so bulk actions go through the same path as a
        click rather than reimplementing preset and temp-param handling.
        """
        self._run()

    def _run(self):
        rec = self.db.get(self.script_id)
        if not rec:
            return
        _, name, path, params, interp, _grp, temp_param = rec[:7]
        params = self._selected_params(params)
        if temp_param:
            dlg = _TempParamDialog(self.winfo_toplevel(), saved_params=params,
                                   title=scriptform.temp_param_title(name))
            self.wait_window(dlg)
            if dlg.cancelled:
                return
            params = scriptform.with_temp_param(params, dlg.result)
        self.runner(self.script_id, name, path, params, interp)

    def _run_with_param(self):
        rec = self.db.get(self.script_id)
        if not rec:
            return
        _, name, path, default_params, interp, _grp, _temp = rec[:7]
        script_id = self.script_id
        runner = self.runner
        on_refresh = self.on_refresh
        db = self.db
        current = self._selected_params(default_params)

        dlg = _PresetEntryDialog(self.winfo_toplevel(), current,
                                 title=scriptform.RUN_WITH_PARAMS_TITLE)
        self.wait_window(dlg)
        if dlg.result is None:
            return

        chosen = dlg.result
        scriptform.remember_run_params(db, script_id, chosen)
        on_refresh()

        runner(script_id, name, path, chosen, interp)


class PipelineCard(tk.Frame):
    """Card displaying a pipeline and its steps summary."""
    _PIPE_ACCENT  = C["pipe_accent"]
    _PIPE_ACCENT2 = C["pipe_accent2"]

    def __init__(self, parent, pipeline_id: int, name: str, db: ScriptDB,
                 group_name: str, on_run, on_edit, on_refresh,
                 is_favorite: bool = False, on_toggle_favorite=None,
                 label_color: str | None = None, scheduled: bool = False,
                 last_status: str | None = None):
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
        self._label_color = label_color
        self._scheduled = scheduled
        self._last_status = last_status
        name_fg = highlight_fg(label_color) or C["name_fg"]

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
        pipe_fav_fg  = (_readable_on(C["bolt"], (C["accent_wash"],)) if is_favorite
                        else C["btn_neutral_fg"])
        pipe_fav_tip = "Remove from favorites" if is_favorite else "Add to favorites"
        self._fav_btn = _rbtn(pipe_fav_text, pipe_fav_bg, pipe_fav_hbg,
                              self._toggle_favorite,
                              fg=pipe_fav_fg, tip=pipe_fav_tip)
        _sep()
        _rbtn("⚙", C["btn_neutral_bg"], C["btn_neutral_hover"],
              lambda: on_edit(pipeline_id, name), tip="Edit",
              fg=C["btn_neutral_fg"])
        _sep()
        # A script card carries a fourth button here (▶+ Run with parameter),
        # which has no pipeline equivalent. Without this spacer the two card
        # types' button columns don't line up in a mixed list (issue #3). It is
        # built by _rbtn like every other cell, so it is the same widget with
        # the same padding and therefore exactly the same width — a Label or
        # Frame sized to width=3 comes out 4px narrower and shifts the whole
        # strip.
        #
        # It is painted in the strip's own colour, not btn_neutral_bg. Being
        # blank and disabled is not enough: a neutral-coloured slab sits 1.03:1
        # against the strip, so it read as a button whose icon had failed to
        # load rather than as empty space (issue #7).
        _rbtn("", C["border"], C["border"], None, state="disabled")
        _sep()
        (_run_text, _run_fg, _run_afg,
         _run_bg, _run_hover, _run_tip) = run_button_style(last_status)
        _rbtn(_run_text, _run_bg, _run_hover,
              lambda: on_run(pipeline_id, name),
              fg=_run_fg, active_fg=_run_afg, tip=_run_tip)

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
            for spec in cardstyle.pipeline_badges(scheduled=bool(scheduled)):
                _tag_badge(name_row, spec)
            name_label = ScrollingLabel(name_row, name, name_fg, C["card_bg"])
            name_label.pack(side="left", fill="both", expand=True)
        else:
            name_label = ScrollingLabel(content, name, name_fg, C["card_bg"])
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
            # Pipelines had no outcome badge at all; the status comes from the
            # run history, since there is no last_run_status column for them.
            pipe_badge = _status_badge(summary_row, last_status or "")
            if pipe_badge is not None:
                pipe_badge.pack(side="right", padx=(6, 0))

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

        tk.Label(inner, text=self._name, bg=C["card_bg"],
                 fg=highlight_fg(self._label_color) or C["name_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", pady=(0, 6))

        if not steps:
            tk.Label(inner, text=cardstyle.NO_STEPS, bg=C["card_bg"], fg=C["path_fg"],
                     font=("Segoe UI", 8)).pack(anchor="w")
        else:
            for idx_text, name, path, override in cardstyle.pipeline_preview_rows(steps):
                row = tk.Frame(inner, bg=C["card_bg"])
                row.pack(fill="x", pady=2)
                tk.Label(row, text=idx_text, bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 8), width=3, anchor="e").pack(side="left")
                tk.Label(row, text=name, bg=C["card_bg"], fg=C["name_fg"],
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=(6, 0))
                tk.Label(row, text=path, bg=C["card_bg"], fg=C["path_fg"],
                         font=("Segoe UI", 7), anchor="w").pack(side="left", padx=(6, 0))
                if override is not None:
                    tk.Label(row, text=f"[{override}]", bg=C["card_bg"], fg=C["accent"],
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

        # Anchored to the click (or the card, when opened without one) and
        # bounded by that point's monitor, not the primary one.
        ax = event.x_root if event else self.winfo_rootx()
        ay = event.y_root if event else self.winfo_rooty()
        place_near(popup, ax, ay, 12, 12)

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

    def run(self) -> None:
        """Run this pipeline exactly as its Run button does.

        Retry re-runs the whole pipeline rather than resuming from the failed
        step: resuming would assume the earlier steps' side effects are still
        valid, which is usually not true.
        """
        self.on_run(self.pipeline_id, self._name)

    def _show_history(self):
        RunHistoryDialog(self.winfo_toplevel(), self.db,
                         pipeline_id=self.pipeline_id, title=self._name)

    def _show_schedule(self):
        ScheduleDialog(self.winfo_toplevel(), self.db, pipeline_id=self.pipeline_id,
                       title=self._name, on_save=self.on_refresh)

    def _set_label_color(self, key):
        self.db.set_pipeline_color(self.pipeline_id, key)
        self.on_refresh()

    def _toggle_favorite(self):
        if self._on_toggle_favorite:
            self._on_toggle_favorite(self.pipeline_id, not self._is_favorite)
        else:
            self.on_refresh()

    def _context_menu(self, event):
        items = cardmenu.pipeline_menu(favorite=self._is_favorite,
                                       color=self._label_color)
        _popup_menu(self.winfo_toplevel(), items, self._on_menu).tk_popup(
            event.x_root, event.y_root)

    def _on_menu(self, key: str) -> None:
        is_pick, color = cardmenu.picked_highlight(key)
        if is_pick:
            self._set_label_color(color)
            return
        handler = {
            cardmenu.FAVORITE: self._toggle_favorite,
            cardmenu.EDIT: lambda: self.on_edit(self.pipeline_id, self._name),
            cardmenu.SCHEDULE: self._show_schedule,
            cardmenu.HISTORY: self._show_history,
            cardmenu.CLONE: self._clone,
            cardmenu.DELETE: self._delete,
        }.get(key)
        if handler is not None:
            handler()

    def _clone(self):
        self.db.clone_pipeline(self.pipeline_id)
        self.on_refresh()

    def _delete(self):
        title, question = cardmenu.delete_prompt(cardmenu.PIPELINE, self._name)
        if messagebox.askyesno(title, question, parent=self):
            cardmenu.delete(self.db, cardmenu.PIPELINE, self.pipeline_id)
            self.on_refresh()
