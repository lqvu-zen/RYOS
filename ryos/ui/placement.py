"""Multi-monitor placement for dialogs, popups and tooltips.

Tk's ``winfo_screenwidth()`` / ``winfo_screenheight()`` report the PRIMARY
monitor on Windows -- not the virtual desktop, and not the monitor the app is
actually on. Every centring or clamping calculation built on them therefore
lands on the primary display: a dialog opened from a window on the second
monitor is centred on the first, and a popup anchored to a card whose
coordinates lie outside the primary monitor gets clamped back onto it.

These helpers resolve the work area of the monitor under a given point
instead (via ryos.screens, which wraps the Win32 query), and fall back to
Tk's numbers only where that query is unavailable -- off Windows, or if the
API call fails -- which reproduces exactly the old single-monitor behaviour.

The geometry math itself is pure and lives in ryos.screens; this module only
resolves work areas from widgets and applies the result.
"""
import tkinter as tk

from ..screens import (anchored_position, center_on_rect, clamp_to_work_area,
                       work_area_at_point)


def _tk_screen_area(widget) -> tuple[int, int, int, int]:
    """Last-resort work area: Tk's own screen, anchored at the origin."""
    try:
        return (0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight())
    except tk.TclError:
        return (0, 0, 1920, 1080)


def work_area_for_point(widget, x: int, y: int) -> tuple[int, int, int, int]:
    """Work area of the monitor containing root point (x, y)."""
    return work_area_at_point(x, y) or _tk_screen_area(widget)


def work_area_for_widget(widget) -> tuple[int, int, int, int]:
    """Work area of the monitor holding the centre of `widget`.

    The centre rather than the top-left, so a window straddling two monitors
    resolves to the one showing most of it -- which is the one the user is
    looking at.
    """
    try:
        x = widget.winfo_rootx() + widget.winfo_width() // 2
        y = widget.winfo_rooty() + widget.winfo_height() // 2
    except tk.TclError:
        return _tk_screen_area(widget)
    return work_area_for_point(widget, x, y)


def _parent_rect(parent) -> tuple[int, int, int, int] | None:
    try:
        w, h = parent.winfo_width(), parent.winfo_height()
        if w <= 1 or h <= 1:          # not yet mapped; nothing useful to centre on
            return None
        return (parent.winfo_rootx(), parent.winfo_rooty(), w, h)
    except tk.TclError:
        return None


def center_over_parent(window, parent, width: int = 0, height: int = 0) -> None:
    """Centre `window` on `parent`, kept within that monitor's work area.

    Pass width/height to place a window before it is mapped (``winfo_width``
    reports 1 until then); they default to the requested size. Falls back to
    centring in the work area when the parent has no usable geometry.
    """
    try:
        window.update_idletasks()
        w = width or window.winfo_reqwidth()
        h = height or window.winfo_reqheight()
        rect = _parent_rect(parent)
        area = (work_area_for_widget(parent) if rect
                else work_area_for_widget(window))
        if rect is None:
            left, top, aw, ah = area
            rect = (left, top, aw, ah)
        x, y = center_on_rect(rect, w, h, area)
        window.geometry(f"{w}x{h}+{x}+{y}" if width and height else f"+{x}+{y}")
    except tk.TclError:
        pass


def offset_from_parent(window, parent, dx: int, dy: int) -> None:
    """Place `window` at the parent's origin plus (dx, dy), clamped to its monitor.

    The cascade offset dialogs use to avoid covering the window that opened
    them; the clamp keeps that offset from pushing a tall dialog off the
    bottom of the screen.
    """
    try:
        window.update_idletasks()
        w, h = window.winfo_reqwidth(), window.winfo_reqheight()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        area = work_area_for_widget(parent)
        x, y = clamp_to_work_area(px + dx, py + dy, w, h, area)
        window.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


def place_near(window, x: int, y: int, dx: int = 12, dy: int = 12) -> None:
    """Place `window` beside root point (x, y) on that point's monitor.

    Flips to the other side of the anchor rather than clamping when it would
    overflow -- see ryos.screens.anchored_position for why that matters for
    hover popups.
    """
    try:
        window.update_idletasks()
        w, h = window.winfo_reqwidth(), window.winfo_reqheight()
        area = work_area_for_point(window, x, y)
        nx, ny = anchored_position(x, y, w, h, area, dx, dy)
        window.geometry(f"+{nx}+{ny}")
    except tk.TclError:
        pass
