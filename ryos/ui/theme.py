"""Colour palette, flat-button factory, and window snap-to-corner helper.

The palette data and the seed -> palette derivation live in the pure, tkinter-free
``ryos.themes`` module; this module keeps the live ``C`` palette, applies themes,
and owns the tkinter-facing helpers (ttk styles, flat buttons, window snapping).
"""
import tkinter as tk
from tkinter import ttk

from ..cardmenu import HIGHLIGHTS
from ..screens import work_area_at_point
from ..themes import (  # noqa: F401 - re-exported for existing callers
    BUILTIN_THEMES, HIGHLIGHT_MIN_RATIO, HIGHLIGHT_SEEDS, SEEDS, THEME_LABELS,
    THEME_MODES, THEME_ORDER, _rel_luminance, _shade, build_palette,
    contrast_ratio, disabled_pair, disambiguate_custom_labels,
    readable_highlight,
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
    """(id, label) for every selectable theme: built-ins first (in order), then
    custom themes. A custom whose name collides with a built-in (or another
    custom) gets a ' (custom)' suffix on its label so the list has no duplicates;
    its id (settings value / filename) is unchanged."""
    items = [(slug, THEME_LABELS[slug]) for slug in THEME_ORDER]
    items += disambiguate_custom_labels(
        _custom_seeds.keys(), THEME_ORDER, THEME_LABELS.values())
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


# --- Per-item highlight colours ----------------------------------------------
# The seeds and the contrast shading live in `themes` (toolkit-free, shared
# with Qt); only the default surfaces -- the live `C` palette -- are Tk's.
# What the menu lists is defined in `cardmenu`.
HIGHLIGHT_LABELS: dict[str, str] = HIGHLIGHTS


def highlight_fg(key: str | None, *surfaces: str) -> str | None:
    """Readable text colour for a highlight key, or None when unset/unknown.

    Unknown keys return None — the caller falls back to the normal label
    colour — so a value left in the database by a future palette never renders
    as an invisible or garbage colour.

    Defaults to the live card surfaces, including the hover shade, so a
    highlighted label stays readable while the card is moused over too.
    """
    return readable_highlight(key, *(surfaces or (C["card_bg"], C["card_hover"])))


def _flat_button(parent, text, bg, hover_bg, command, width=9, fg=None):
    """Borderless button with hover color swap. Pass fg to override white text.

    The hover bindings check the button's state, because Tk keeps delivering
    <Enter> to a disabled widget -- without the check a dead button lights up
    under the pointer and looks clickable (issue #7). Use set_button_enabled()
    to flip one, so its colours change with its state.
    """
    _fg = fg if fg is not None else C["btn_fg"]
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=_fg,
        activebackground=hover_bg, activeforeground=_fg,
        disabledforeground=C["btn_disabled_fg"],
        relief="flat", bd=0, padx=12, pady=5,
        font=("Segoe UI", 9, "bold"), cursor="hand2", width=width,
    )
    btn._bg, btn._hbg, btn._fg = bg, hover_bg, _fg
    btn.bind("<Enter>", lambda e: _hover(btn, hover_bg))
    btn.bind("<Leave>", lambda e: _hover(btn, bg))
    return btn


def _hover(btn, colour) -> None:
    """Apply a hover colour, but only while the button can actually be used."""
    try:
        if str(btn.cget("state")) == "disabled":
            return
        btn.config(bg=colour)
    except tk.TclError:
        pass  # widget torn down mid-hover


def set_button_enabled(btn, enabled: bool, *, bg: str = "", fg: str = "") -> None:
    """Flip a flat button's state *and* its appearance.

    Tk only dims the label when a button is disabled, and on a custom palette
    it dims it to a Windows system colour that has nothing to do with the
    theme. Changing the slab too is what makes the state legible.

    Buttons from _flat_button carry their enabled colours, so `bg`/`fg` are
    only needed for one built by hand.
    """
    on_bg = bg or getattr(btn, "_bg", "") or str(btn.cget("bg"))
    on_fg = fg or getattr(btn, "_fg", "") or str(btn.cget("fg"))
    try:
        if enabled:
            btn.configure(state="normal", cursor="hand2", bg=on_bg, fg=on_fg)
        else:
            dis_bg, dis_fg = disabled_pair(on_bg, on_fg, C["card_bg"])
            btn.configure(state="disabled", cursor="",
                          bg=dis_bg, disabledforeground=dis_fg)
    except tk.TclError:
        pass  # widget already destroyed


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
    # Prefer an explicit target monitor work area (multi-monitor); otherwise
    # snap within the monitor the window is currently on. The old fallback here
    # was SPI_GETWORKAREA, which reports the PRIMARY monitor's work area and so
    # yanked a window on any other display back to the first one.
    if work_area is None:
        work_area = work_area_at_point(window.winfo_rootx() + w // 2,
                                       window.winfo_rooty() + h // 2)
    if work_area is not None:
        ax, ay, aw, ah = work_area
    else:
        ax, ay = 0, 0
        aw, ah = window.winfo_screenwidth(), window.winfo_screenheight()
    x = ax + margin if "left" in corner else ax + aw - w - margin
    y = ay + margin if "top"  in corner else ay + ah - h - margin
    window.geometry(f"+{x}+{y}")
