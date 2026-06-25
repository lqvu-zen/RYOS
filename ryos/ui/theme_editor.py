"""Custom theme editor: pick the curated seed colours, optionally override
advanced colours, preview live, save.

The editor edits a seed (mode + 7 required colours + optional advanced colours).
It renders a small live preview by running the same `build_palette` the app
uses, and surfaces non-fatal contrast warnings. Advanced colours are optional:
each shows its *effective* value (an explicit override, or the colour
build_palette would derive) and can be reset back to auto. On save it hands the
validated (name, seed) back to the caller, which persists and applies it.
"""
import tkinter as tk
from tkinter import colorchooser, messagebox

from ..themes import (
    ADVANCED_KEYS, SEED_KEYS, build_palette, contrast_warnings, is_hex_color,
    validate_seed,
)
from .theme import C, _flat_button

# Human labels for each required seed colour, in display order.
_COLOR_LABELS = {
    "bg":         "Background",
    "surface":    "Cards & dialogs",
    "border":     "Borders & dividers",
    "header_bg":  "Header bar",
    "accent":     "Accent",
    "text":       "Primary text",
    "text_muted": "Secondary text",
}


class ThemeEditorDialog(tk.Toplevel):
    """Modal editor. `on_save(name, seed)` is called once with a valid theme."""

    def __init__(self, parent, *, seed: dict, name: str = "",
                 taken_names=(), on_save=None):
        super().__init__(parent)
        self._seed = {"mode": seed.get("mode", "light")}
        for key in SEED_KEYS:
            self._seed[key] = seed.get(key, "#888888")
        for key, _label in ADVANCED_KEYS:
            if is_hex_color(seed.get(key)):
                self._seed[key] = seed[key]
        self._on_save = on_save
        self._taken = {n.lower() for n in taken_names}

        self.title("Theme editor")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._name_var = tk.StringVar(value=name)
        self._mode = tk.StringVar(value=self._seed["mode"])
        self._swatches: dict[str, tk.Frame] = {}
        self._adv_swatches: dict[str, tk.Frame] = {}
        self._adv_resets: dict[str, tk.Label] = {}
        self._warn_var = tk.StringVar(value="")

        self._build()
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        self.geometry(f"+{px + 40}+{py + 30}")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=16, pady=12)

        tk.Label(wrap, text="Name", bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        tk.Entry(wrap, textvariable=self._name_var, bg=C["card_bg"], fg=C["name_fg"],
                 insertbackground=C["name_fg"], relief="flat", bd=4,
                 font=("Segoe UI", 10)).pack(fill="x", pady=(2, 10))

        mode_row = tk.Frame(wrap, bg=C["bg"])
        mode_row.pack(fill="x", pady=(0, 8))
        tk.Label(mode_row, text="Base", bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 10))
        for label, val in (("☀ Light", "light"), ("🌙 Dark", "dark")):
            tk.Radiobutton(mode_row, text=label, value=val, variable=self._mode,
                           command=self._on_mode, bg=C["bg"], fg=C["name_fg"],
                           selectcolor=C["card_bg"], activebackground=C["bg"],
                           activeforeground=C["name_fg"], font=("Segoe UI", 9),
                           bd=0, highlightthickness=0).pack(side="left", padx=4)

        body = tk.Frame(wrap, bg=C["bg"])
        body.pack(fill="both", expand=True)
        pickers = tk.Frame(body, bg=C["bg"])
        pickers.pack(side="left", fill="y", padx=(0, 16))
        for key in _COLOR_LABELS:
            self._build_picker_row(pickers, key)

        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="Preview", bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        self._preview_holder = tk.Frame(right, bg=C["bg"])
        self._preview_holder.pack(fill="both", expand=True, pady=(4, 8))
        tk.Label(right, textvariable=self._warn_var, bg=C["bg"], fg=C["warn_fg"],
                 font=("Segoe UI", 8), anchor="w", justify="left",
                 wraplength=240).pack(fill="x")

        # Advanced (optional) colours, in a 2-column grid.
        tk.Label(wrap, text="ADVANCED  (optional — ↺ resets to auto)", bg=C["bg"],
                 fg=C["accent"], font=("Segoe UI", 8, "bold"), anchor="w").pack(
            fill="x", pady=(12, 2))
        grid = tk.Frame(wrap, bg=C["bg"])
        grid.pack(fill="x")
        for i, (key, label) in enumerate(ADVANCED_KEYS):
            self._build_adv_cell(grid, key, label, row=i // 2, col=i % 2)

        btn_row = tk.Frame(wrap, bg=C["bg"])
        btn_row.pack(fill="x", pady=(14, 0))
        _flat_button(btn_row, "Cancel", C["btn_dark_bg"], C["btn_dark_hover"],
                     self.destroy, width=8).pack(side="right")
        _flat_button(btn_row, "Save", C["accent"], C["accent2"],
                     self._save, width=8).pack(side="right", padx=(0, 6))

        self._refresh()

    def _build_picker_row(self, parent, key: str) -> None:
        row = tk.Frame(parent, bg=C["bg"])
        row.pack(fill="x", pady=3)
        sw = tk.Frame(row, width=26, height=20, relief="solid", bd=1,
                      bg=self._seed[key], cursor="hand2")
        sw.pack(side="left", padx=(0, 8))
        sw.pack_propagate(False)
        sw.bind("<Button-1>", lambda _e, k=key: self._choose(k))
        self._swatches[key] = sw
        lbl = tk.Label(row, text=_COLOR_LABELS[key], bg=C["bg"], fg=C["name_fg"],
                       font=("Segoe UI", 9), anchor="w", cursor="hand2")
        lbl.pack(side="left", fill="x", expand=True)
        lbl.bind("<Button-1>", lambda _e, k=key: self._choose(k))

    def _build_adv_cell(self, grid, key: str, label: str, row: int, col: int) -> None:
        cell = tk.Frame(grid, bg=C["bg"])
        cell.grid(row=row, column=col, sticky="w", padx=(0, 14), pady=2)
        sw = tk.Frame(cell, width=20, height=16, relief="solid", bd=1,
                      bg=self._effective(key), cursor="hand2")
        sw.pack(side="left", padx=(0, 6))
        sw.pack_propagate(False)
        sw.bind("<Button-1>", lambda _e, k=key: self._choose_adv(k))
        self._adv_swatches[key] = sw
        tk.Label(cell, text=label, bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 8), anchor="w").pack(side="left")
        reset = tk.Label(cell, text="↺", bg=C["bg"], fg=C["path_fg"],
                         font=("Segoe UI", 9), cursor="hand2")
        reset.pack(side="left", padx=(4, 0))
        reset.bind("<Button-1>", lambda _e, k=key: self._reset_adv(k))
        self._adv_resets[key] = reset

    # ---------------------------------------------------------------- helpers
    def _effective(self, key: str) -> str:
        """The colour shown for an advanced key: explicit override or derived."""
        if is_hex_color(self._seed.get(key)):
            return self._seed[key]
        return build_palette(self._seed)[key]

    # ---------------------------------------------------------------- actions
    def _choose(self, key: str) -> None:
        _, hex_str = colorchooser.askcolor(
            color=self._seed[key], title=_COLOR_LABELS[key], parent=self)
        if hex_str:
            self._seed[key] = hex_str
            self._refresh()

    def _choose_adv(self, key: str) -> None:
        _, hex_str = colorchooser.askcolor(
            color=self._effective(key), title="Advanced colour", parent=self)
        if hex_str:
            self._seed[key] = hex_str
            self._refresh()

    def _reset_adv(self, key: str) -> None:
        if key in self._seed:
            del self._seed[key]
            self._refresh()

    def _on_mode(self) -> None:
        self._seed["mode"] = self._mode.get()
        self._refresh()

    def _refresh(self) -> None:
        for key, sw in self._swatches.items():
            sw.configure(bg=self._seed[key])
        for key, sw in self._adv_swatches.items():
            sw.configure(bg=self._effective(key))
            overridden = is_hex_color(self._seed.get(key))
            self._adv_resets[key].configure(fg=C["accent"] if overridden else C["path_fg"])
        warnings = contrast_warnings(self._seed)
        self._warn_var.set("⚠ " + "  ".join(warnings) if warnings else "")
        self._render_preview()

    def _render_preview(self) -> None:
        for child in self._preview_holder.winfo_children():
            child.destroy()
        p = build_palette(self._seed)
        frame = tk.Frame(self._preview_holder, bg=p["bg"],
                         highlightbackground=p["border"], highlightthickness=1)
        frame.pack(fill="both", expand=True)
        header = tk.Frame(frame, bg=p["header_bg"])
        header.pack(fill="x")
        tk.Label(header, text="⚡ RYOS", bg=p["header_bg"], fg=p["fg_on_dark"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=8, pady=5)
        card = tk.Frame(frame, bg=p["card_bg"], highlightbackground=p["border"],
                        highlightthickness=1)
        card.pack(fill="x", padx=10, pady=10)
        tk.Label(card, text="deploy.py", bg=p["card_bg"], fg=p["name_fg"],
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(card, text="C:\\scripts\\deploy.py", bg=p["card_bg"], fg=p["path_fg"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=8, pady=(0, 8))
        btns = tk.Frame(card, bg=p["card_bg"])
        btns.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(btns, text="Run", bg=p["btn_run_bg"], fg=p["btn_fg"],
                 font=("Segoe UI", 8, "bold"), padx=10, pady=3).pack(side="left")
        tk.Label(btns, text="Modify", bg=p["btn_mod_bg"], fg=p["btn_fg"],
                 font=("Segoe UI", 8, "bold"), padx=10, pady=3).pack(side="left", padx=6)
        # A strip of the terminal output colours.
        term = tk.Frame(frame, bg=p["out_bg"])
        term.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(term, text="stdout", bg=p["out_bg"], fg=p["out_stdout"],
                 font=("Consolas", 8)).pack(side="left", padx=(8, 6), pady=4)
        tk.Label(term, text="stderr", bg=p["out_bg"], fg=p["out_stderr"],
                 font=("Consolas", 8)).pack(side="left", padx=6)
        tk.Label(term, text="status", bg=p["out_bg"], fg=p["out_status"],
                 font=("Consolas", 8)).pack(side="left", padx=6)

    def _save(self) -> None:
        name = self._name_var.get().strip()
        if not name:
            messagebox.showerror("Theme editor", "Give the theme a name.", parent=self)
            return
        if name.lower() in self._taken:
            messagebox.showerror("Theme editor",
                                 f"A theme named “{name}” already exists.", parent=self)
            return
        problems = validate_seed(self._seed)
        if problems:
            messagebox.showerror("Theme editor",
                                 "Fix these first:\n• " + "\n• ".join(problems),
                                 parent=self)
            return
        if self._on_save is not None:
            self._on_save(name, dict(self._seed))
        self.destroy()
