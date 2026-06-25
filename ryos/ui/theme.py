"""Colour palette, flat-button factory, and window snap-to-corner helper.

The palette data and the seed -> palette derivation live in the pure, tkinter-free
``ryos.themes`` module; this module keeps the live ``C`` palette, applies themes,
and owns the tkinter-facing helpers (ttk styles, flat buttons, window snapping).
"""
import sys
import tkinter as tk
from tkinter import ttk

from ..themes import (
    BUILTIN_THEMES, SEEDS, THEME_LABELS, THEME_MODES, THEME_ORDER,
    _shade, build_palette,
)

# Named theme palettes, sourced from the engine. Kept here so existing
# `from .theme import THEMES` / `C` references keep working unchanged.
THEMES: dict[str, dict] = BUILTIN_THEMES

# User-created themes, loaded from themes.json at startup (name -> seed). The
# app registers them via set_custom_themes(); apply_theme and available_themes
# consult this so custom themes resolve and appear in the selector.
_custom_seeds: dict[str, dict] = {}

# Mutable live palette — mutated in-place by apply_theme() so that all modules
# that already hold a reference to C stay in sync without re-importing.
C: dict = dict(THEMES["light"])


def set_custom_themes(seeds: dict) -> None:
    """Replace the runtime custom-theme registry (name -> seed)."""
    global _custom_seeds
    _custom_seeds = dict(seeds or {})


def custom_themes() -> dict:
    """The current custom-theme registry (name -> seed)."""
    return dict(_custom_seeds)


def available_themes() -> list[tuple[str, str]]:
    """(id, label) for every selectable theme: built-ins first (in order),
    then custom themes alphabetically. The id is what settings['theme'] stores."""
    items = [(slug, THEME_LABELS[slug]) for slug in THEME_ORDER]
    items += [(name, name) for name in sorted(_custom_seeds)]
    return items


def theme_mode(theme_name: str) -> str:
    """'light' or 'dark' base for a theme id (built-in or custom)."""
    if theme_name in THEME_MODES:
        return THEME_MODES[theme_name]
    seed = _custom_seeds.get(theme_name)
    return seed.get("mode", "light") if seed else "light"


def _resolve_palette(theme_name: str) -> dict:
    """Full palette for a theme id: a built-in if known, then a custom theme,
    then a built-in seed, otherwise light as a safe fallback."""
    if theme_name in THEMES:
        return THEMES[theme_name]
    if theme_name in _custom_seeds:
        return build_palette(_custom_seeds[theme_name])
    seed = SEEDS.get(theme_name)
    if seed is not None:
        return build_palette(seed)
    return THEMES["light"]


def apply_theme(theme_name: str, accent: str | None = None) -> None:
    """Switch the live palette to the named theme, optionally overlaying a custom accent."""
    C.clear()
    C.update(_resolve_palette(theme_name))
    if accent:
        # Replace the accent family with the user-chosen color so every widget
        # that reads C["accent"] automatically picks up the new brand hue.
        C["accent"]           = accent
        C["accent2"]          = _shade(accent, -0.15)
        C["btn_mod_bg"]       = accent
        C["btn_create_bg"]    = accent
        C["btn_mod_hover"]    = C["accent2"]
        C["btn_create_hover"] = C["accent2"]
        wash_factor = 0.86 if theme_mode(theme_name) == "light" else -0.55
        C["accent_wash"]      = _shade(accent, wash_factor)
    _configure_ttk_styles()


def _flat_button(parent, text, bg, hover_bg, command, width=9, fg=None):
    """Borderless button with hover color swap. Pass fg to override white text."""
    _fg = fg if fg is not None else C["btn_fg"]
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=_fg,
        activebackground=hover_bg, activeforeground=_fg,
        relief="flat", bd=0, padx=12, pady=5,
        font=("Segoe UI", 9, "bold"), cursor="hand2", width=width,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn


def _configure_ttk_styles() -> None:
    """Configure ttk widget styles to harmonise with the flat card aesthetic."""
    style = ttk.Style()
    # Switch to 'clam' so ttk style overrides (especially Combobox) actually take
    # effect instead of being swallowed by the native Windows renderer.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass  # clam unavailable — fall back to whatever the platform provides

    style.configure(
        "Card.TCombobox",
        fieldbackground=C["card_bg"],
        background=C["card_bg"],
        foreground=C["name_fg"],
        selectbackground=C["accent_wash"],
        selectforeground=C["name_fg"],
        borderwidth=1,
        relief="flat",
        arrowcolor=C["path_fg"],
        arrowsize=12,
        padding=(4, 2),
    )
    style.map(
        "Card.TCombobox",
        fieldbackground=[("readonly", C["card_bg"]), ("disabled", C["bg"])],
        foreground=[("readonly", C["name_fg"])],
        selectbackground=[("readonly", C["accent_wash"])],
        selectforeground=[("readonly", C["name_fg"])],
        background=[("active", C["card_hover"]), ("readonly", C["card_bg"])],
        bordercolor=[("focus", C["accent"]), ("!focus", C["border"])],
    )
    # Keep the scrollbar slim and neutral.
    style.configure(
        "TScrollbar",
        background=C["border"],
        troughcolor=C["bg"],
        borderwidth=0,
        arrowsize=12,
        relief="flat",
    )
    style.map("TScrollbar", background=[("active", C["path_fg"])])
    # Tabbed dialogs (Advanced Options): flat notebook that picks up theme colors.
    style.configure("Card.TNotebook", background=C["bg"], borderwidth=0)
    style.configure(
        "Card.TNotebook.Tab",
        background=C["bg"],
        foreground=C["path_fg"],
        bordercolor=C["border"],
        padding=(12, 6),
        font=("Segoe UI", 9),
    )
    style.map(
        "Card.TNotebook.Tab",
        background=[("selected", C["card_bg"]), ("active", C["card_hover"])],
        foreground=[("selected", C["accent"]), ("active", C["name_fg"])],
    )
    # Remove the dotted grip marks from the PanedWindow sash.
    style.configure("Sash", gripcount=0, sashthickness=4, sashpad=0,
                    background=C["border"])


def _apply_snap_corner(window, corner: str, margin: int = 10, work_area=None) -> None:
    window.update_idletasks()
    w = window.winfo_width()
    h = window.winfo_height()
    # Prefer an explicit target monitor work area (multi-monitor); otherwise use
    # the primary monitor's work area on Windows, full screen elsewhere.
    if work_area is not None:
        ax, ay, aw, ah = work_area
    elif sys.platform == "win32":
        try:
            import ctypes.wintypes
            wa = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(wa), 0)
            ax, ay = wa.left, wa.top
            aw, ah = wa.right - wa.left, wa.bottom - wa.top
        except Exception:
            ax, ay = 0, 0
            aw, ah = window.winfo_screenwidth(), window.winfo_screenheight()
    else:
        ax, ay = 0, 0
        aw, ah = window.winfo_screenwidth(), window.winfo_screenheight()
    x = ax + margin if "left" in corner else ax + aw - w - margin
    y = ay + margin if "top"  in corner else ay + ah - h - margin
    window.geometry(f"+{x}+{y}")
