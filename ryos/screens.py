"""Multi-monitor helpers.

Pure geometry math (relocate_geometry) is platform-independent and unit-tested.
The monitor-detection wrappers use the Win32 API via ctypes and degrade to
None on non-Windows or on any failure, so callers must handle None.
"""
import re
import sys

# A Tk geometry string: "WIDTHxHEIGHT+X+Y". X/Y may be negative (monitors left
# of / above the primary), which Tk renders as e.g. "540x640+-1920+0".
_GEOMETRY_RE = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")


def relocate_geometry(geometry: str, src_work, dst_work) -> str:
    """Move a window geometry from one monitor's work area to another's,
    preserving the window's offset relative to the monitor origin and clamping
    so the window stays fully on the destination (when it fits).

    `src_work` / `dst_work` are (x, y, width, height) work-area rectangles.
    Returns a new geometry string, or the input unchanged if it carries no
    parseable "+X+Y" position (e.g. a size-only "540x640").
    """
    m = _GEOMETRY_RE.fullmatch((geometry or "").strip())
    if not m:
        return geometry
    w, h, x, y = (int(g) for g in m.groups())
    sx, sy = src_work[0], src_work[1]
    dx, dy, dw, dh = dst_work
    nx = dx + (x - sx)
    ny = dy + (y - sy)
    nx = max(dx, min(nx, dx + dw - w)) if w <= dw else dx
    ny = max(dy, min(ny, dy + dh - h)) if h <= dh else dy
    return f"{w}x{h}+{nx}+{ny}"


def _work_area_from_monitor(hmon):
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32 = ctypes.windll.user32
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    r = mi.rcWork
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def work_area_at_point(x: int, y: int):
    """(x, y, width, height) work area of the monitor nearest point (x, y), or
    None on non-Windows / failure."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        MONITOR_DEFAULTTONEAREST = 2
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        hmon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                       MONITOR_DEFAULTTONEAREST)
        return _work_area_from_monitor(hmon)
    except Exception:
        return None


def cursor_work_area():
    """(x, y, width, height) work area of the monitor the mouse cursor is on, or
    None on non-Windows / failure."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        pt = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return work_area_at_point(pt.x, pt.y)
    except Exception:
        return None
