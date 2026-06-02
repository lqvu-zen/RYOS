"""Colour palette, flat-button factory, and window snap-to-corner helper."""
import ctypes
import sys
import tkinter as tk

# Master palette. Mirrors the RYOS design system tokens
# (ryos-design-system/colors_and_type.css) — the single source of
# truth for every colour in the app. Group with the CSS sections.
C = {
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
}


def _flat_button(parent, text, bg, hover_bg, command, width=9):
    """Borderless button with hover color swap."""
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=C["btn_fg"],
        activebackground=hover_bg, activeforeground=C["btn_fg"],
        relief="flat", bd=0, padx=12, pady=5,
        font=("Segoe UI", 9, "bold"), cursor="hand2", width=width,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn


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
