"""Colour palette, flat-button factory, and window snap-to-corner helper."""
import ctypes
import sys
import tkinter as tk

C = {
    "bg":         "#f0f2f5",
    "card_bg":    "#ffffff",
    "card_hover": "#f5f7ff",
    "accent":     "#4a6fa5",
    "accent2":    "#3d5d8a",
    "header_bg":  "#1e2a3a",
    "name_fg":    "#1a1a2e",
    "path_fg":    "#8892a0",
    "btn_run_bg": "#2ecc71",
    "btn_run_hover": "#27ae60",
    "btn_mod_bg": "#4a6fa5",
    "btn_mod_hover": "#3d5d8a",
    "btn_fg":     "#ffffff",
    "border":     "#dde2ea",
    "status_bg":  "#e8ebf0",
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
