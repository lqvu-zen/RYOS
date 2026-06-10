"""Colour palette, flat-button factory, and window snap-to-corner helper."""
import sys
import tkinter as tk
from tkinter import ttk

# Named theme palettes. C is always kept in sync with the active theme so
# all existing `from .theme import C` references continue to work without change.
THEMES: dict[str, dict] = {
    "light": {
        # ---------- SURFACES ----------
        "bg":          "#f0f2f5",  # app canvas — cool light blue-gray
        "card_bg":     "#ffffff",  # card / dialog surface
        "card_hover":  "#f5f7ff",  # card hover — faint blue wash
        "status_bg":   "#e8ebf0",  # bottom status bar
        "header_bg":   "#1e2a3a",  # top app header — deep navy
        "border":      "#dde2ea",  # hairline dividers, card outlines

        # ---------- BRAND / ACCENT ----------
        "accent":      "#4a6fa5",  # primary slate blue
        "accent2":     "#3d5d8a",  # primary pressed / hover-darker
        "accent_wash": "#eef2ff",  # active-tab hover tint
        "bolt":        "#FFD23F",  # logo lightning bolt — signature gold
        "bolt_hover":  "#e6bc00",  # bolt pressed / hover — darker gold

        # ---------- TEXT ----------
        "name_fg":      "#1a1a2e",  # primary text — near-black indigo
        "path_fg":      "#626975",  # secondary text — muted slate
        "fg_on_dark":   "#ffffff",  # text on navy / colored fills
        "fg_on_dark_2": "#aaaaaa",  # muted text on dark surfaces
        "tab_fg":       "#2d3748",  # inactive tab label

        # ---------- BUTTONS ----------
        "btn_fg":            "#ffffff",
        "btn_run_bg":        "#2ecc71",  # RUN — emerald green
        "btn_run_hover":     "#27ae60",
        "btn_mod_bg":        "#4a6fa5",
        "btn_mod_hover":     "#3d5d8a",
        "btn_create_bg":     "#4a6fa5",  # +Script / +Group / +Pipeline
        "btn_create_hover":  "#3d5d8a",
        "btn_neutral_bg":    "#eef1f6",  # row buttons: ⚙ ▶+
        "btn_neutral_hover": "#dde3ee",
        "btn_neutral_fg":    "#5a6573",
        "btn_stop_idle":           "#3a3a3a",  # ⏹ idle (dark, disabled look)
        "btn_stop_idle_fg":        "#666666",
        "btn_stop_idle_active_fg": "#888888",
        "btn_stop_idle_hover":     "#4a4a4a",
        "btn_stop_active":         "#8b0000",  # ⏹ live — dark red
        "btn_stop_active_hover":   "#5a1a1a",
        "btn_dark_bg":       "#3a3a3a",  # generic dark control (Cancel, ⚙)
        "btn_dark_hover":    "#555555",

        # ---------- TABS ----------
        "tab_inactive_bg":    "#e4e9f0",
        "tab_inactive_hover": "#d8dfe8",

        # ---------- STATUS / BADGES ----------
        "ok":          "#2ecc71",  # ✓ OK badge
        "running":     "#27ae60",  # ▶ RUNNING badge
        "error":       "#c0392b",  # ✕ Failed badge
        "warn_bg":     "#fff7e6",  # select-mode bar bg (amber)
        "warn_border": "#f3d99a",
        "warn_fg":     "#7a4a00",

        # ---------- PIPELINE ----------
        "pipe_accent":  "#5c4bbd",  # pipeline card accent — violet
        "pipe_accent2": "#7060d0",

        # ---------- DARK SURFACES (output / menus / tooltips) ----------
        "out_bg":         "#1e1e1e",  # terminal output body
        "out_header":     "#2d2d2d",  # output header / tab buttons
        "out_tabbar":     "#252525",  # output tab strip
        "out_stdout":     "#d4d4d4",  # default log text
        "out_stderr":     "#ff6b6b",  # stderr (red)
        "out_status":     "#5aa9e6",  # status lines (blue)
        "out_success":    "#4ec97a",  # success summary (green)
        "menu_bg":        "#2d2d2d",  # context / options menus
        "menu_danger":    "#ff8080",  # destructive menu item
        "tooltip_bg":     "#2d2d2d",
        "tooltip_border": "#555555",
    },
    "dark": {
        "bg":          "#14181f",
        "card_bg":     "#1d232d",
        "card_hover":  "#262e3a",
        "status_bg":   "#1a1f27",
        "header_bg":   "#0f141b",
        "border":      "#2c3440",
        "accent":      "#5b8bd0",
        "accent2":     "#4a72ad",
        "accent_wash": "#22304a",
        "bolt":        "#FFD23F",
        "bolt_hover":  "#e6bc00",
        "name_fg":     "#e8ebf0",
        "path_fg":     "#9aa3b2",
        "fg_on_dark":  "#ffffff",
        "fg_on_dark_2":"#aaaaaa",
        "tab_fg":      "#c2cad6",
        "btn_fg":            "#ffffff",
        "btn_run_bg":        "#2ecc71",
        "btn_run_hover":     "#27ae60",
        "btn_mod_bg":        "#5b8bd0",
        "btn_mod_hover":     "#4a72ad",
        "btn_create_bg":     "#5b8bd0",
        "btn_create_hover":  "#4a72ad",
        "btn_neutral_bg":    "#2a323e",
        "btn_neutral_hover": "#353f4e",
        "btn_neutral_fg":    "#c2cad6",
        "btn_stop_idle":           "#3a3a3a",
        "btn_stop_idle_fg":        "#777777",
        "btn_stop_idle_active_fg": "#999999",
        "btn_stop_idle_hover":     "#4a4a4a",
        "btn_stop_active":         "#a01818",
        "btn_stop_active_hover":   "#7a1414",
        "btn_dark_bg":       "#2a323e",
        "btn_dark_hover":    "#3a4452",
        "tab_inactive_bg":    "#222a35",
        "tab_inactive_hover": "#2c3440",
        "ok":          "#2ecc71",
        "running":     "#27ae60",
        "error":       "#e05a5a",
        "warn_bg":     "#3a2f1a",
        "warn_border": "#5c4a26",
        "warn_fg":     "#f0c980",
        "pipe_accent":  "#7c6bdd",
        "pipe_accent2": "#8f80e0",
        "out_bg":         "#1e1e1e",
        "out_header":     "#2d2d2d",
        "out_tabbar":     "#252525",
        "out_stdout":     "#d4d4d4",
        "out_stderr":     "#ff6b6b",
        "out_status":     "#5aa9e6",
        "out_success":    "#4ec97a",
        "menu_bg":        "#2d2d2d",
        "menu_danger":    "#ff8080",
        "tooltip_bg":     "#2d2d2d",
        "tooltip_border": "#555555",
    },
}

# Mutable live palette — mutated in-place by apply_theme() so that all modules
# that already hold a reference to C stay in sync without re-importing.
C: dict = dict(THEMES["light"])


def _shade(hex_str: str, factor: float) -> str:
    """Darken (factor < 0) or lighten (factor > 0) a #rrggbb hex color."""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if factor < 0:
        r = int(r * (1 + factor))
        g = int(g * (1 + factor))
        b = int(b * (1 + factor))
    else:
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def apply_theme(theme_name: str, accent: str | None = None) -> None:
    """Switch the live palette to the named theme, optionally overlaying a custom accent."""
    C.clear()
    C.update(THEMES.get(theme_name, THEMES["light"]))
    if accent:
        # Replace the accent family with the user-chosen color so every widget
        # that reads C["accent"] automatically picks up the new brand hue.
        C["accent"]           = accent
        C["accent2"]          = _shade(accent, -0.15)
        C["btn_mod_bg"]       = accent
        C["btn_create_bg"]    = accent
        C["btn_mod_hover"]    = C["accent2"]
        C["btn_create_hover"] = C["accent2"]
        wash_factor = 0.86 if theme_name == "light" else -0.55
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
    # Remove the dotted grip marks from the PanedWindow sash.
    style.configure("Sash", gripcount=0, sashthickness=4, sashpad=0,
                    background=C["border"])


def _apply_snap_corner(window, corner: str, margin: int = 10) -> None:
    window.update_idletasks()
    w = window.winfo_width()
    h = window.winfo_height()
    # Use work area (excludes taskbar) on Windows; fall back to full screen elsewhere
    if sys.platform == "win32":
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
