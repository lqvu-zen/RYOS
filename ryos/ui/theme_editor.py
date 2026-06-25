"""Custom theme editor: pick the 7 seed colours, preview live, save.

The editor edits a seed (mode + 7 colours). It renders a small live preview by
running the same `build_palette` the app uses, and surfaces non-fatal contrast
warnings so a user is nudged away from unreadable combinations. On save it hands
the validated (name, seed) back to the caller, which persists and applies it.
"""
import tkinter as tk
from tkinter import colorchooser, messagebox

from ..themes import SEED_KEYS, build_palette, contrast_warnings, validate_seed
from .theme import C, _flat_button

# Human labels for each editable seed colour, in display order.
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
        self._on_save = on_save
        self._taken = {n.lower() for n in taken_names}

        self.title("Theme editor")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._name = tk.StringVar(value=name)
        self._mode = tk.StringVar(value=self._seed["mode"])
        self._swatches: dict[str, tk.Frame] = {}
        self._preview: tk.Frame | None = None
        self._warn_var = tk.StringVar(value="")

        self._build()
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        self.geometry(f"+{px + 40}+{py + 40}")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=16, pady=12)

        tk.Label(wrap, text="Name", bg=C["bg"], fg=C["path_fg"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        tk.Entry(wrap, textvariable=self._name, bg=C["card_bg"], fg=C["name_fg"],
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
        # Left: the colour pickers. Right: the live preview.
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
                 wraplength=220).pack(fill="x")

        btn_row = tk.Frame(wrap, bg=C["bg"])
        btn_row.pack(fill="x", pady=(12, 0))
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
        tk.Label(row, text=_COLOR_LABELS[key], bg=C["bg"], fg=C["name_fg"],
                 font=("Segoe UI", 9), anchor="w", cursor="hand2").pack(
            side="left", fill="x", expand=True)
        row.winfo_children()[-1].bind("<Button-1>", lambda _e, k=key: self._choose(k))

    # ---------------------------------------------------------------- actions
    def _choose(self, key: str) -> None:
        _, hex_str = colorchooser.askcolor(
            color=self._seed[key], title=_COLOR_LABELS[key], parent=self)
        if hex_str:
            self._seed[key] = hex_str
            self._refresh()

    def _on_mode(self) -> None:
        self._seed["mode"] = self._mode.get()
        self._refresh()

    def _refresh(self) -> None:
        for key, sw in self._swatches.items():
            sw.configure(bg=self._seed[key])
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

    def _save(self) -> None:
        name = self._name.get().strip()
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
