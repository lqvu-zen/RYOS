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


def clamp_to_work_area(x: int, y: int, w: int, h: int, work_area) -> tuple[int, int]:
    """Nudge a w x h rect so it sits fully inside `work_area`.

    A rect too large to fit is pinned to the area origin, so its top-left stays
    reachable rather than being pushed off the opposite edge.
    """
    left, top, aw, ah = work_area
    nx = max(left, min(x, left + aw - w)) if w <= aw else left
    ny = max(top, min(y, top + ah - h)) if h <= ah else top
    return nx, ny


def center_on_rect(parent_rect, w: int, h: int, work_area) -> tuple[int, int]:
    """Top-left for a w x h window centred on `parent_rect` (x, y, width, height).

    Centring on the parent rather than on a screen is what keeps a dialog on
    the same monitor as the window that opened it; the clamp then stops it
    hanging off an edge when the parent sits near one.
    """
    px, py, pw, ph = parent_rect
    return clamp_to_work_area(px + (pw - w) // 2, py + (ph - h) // 2, w, h, work_area)


def anchored_position(ax: int, ay: int, w: int, h: int, work_area,
                      dx: int = 12, dy: int = 12) -> tuple[int, int]:
    """Top-left for a w x h popup placed near anchor point (ax, ay).

    Overflow flips the popup to the opposite side of the anchor instead of
    clamping it: clamping would slide the popup back underneath the pointer,
    which for a hover-triggered popup means <Leave> fires on the card and the
    popup flickers open/closed. Anything still outside after the flip is
    clamped, so the popup can never leave the monitor.
    """
    left, top, aw, ah = work_area
    x = ax + dx if ax + dx + w <= left + aw else ax - dx - w
    y = ay + dy if ay + dy + h <= top + ah else ay - dy - h
    return clamp_to_work_area(x, y, w, h, work_area)


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


def geometry_origin(geometry: str) -> tuple[int, int]:
    """Best-effort (x, y) origin from a 'WxH+X+Y' string; (0, 0) if unparseable."""
    m = re.search(r"\+(-?\d+)\+(-?\d+)\s*$", geometry or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def center_in_work_area(w: int, h: int, work_area: tuple[int, int, int, int]) -> str:
    """Tk geometry string centering a w×h window in a work area (left, top, width, height)."""
    left, top, aw, ah = work_area
    x = left + max(0, (aw - w) // 2)
    y = top + max(0, (ah - h) // 2)
    return f"{w}x{h}+{x}+{y}"


# --- where the main window goes: decisions shared by the Tk and Qt shells -----
# Work areas come in as (x, y, width, height). Tk (DPI-unaware, so Windows
# virtualises it) and Qt (device-independent pixels) see the same numbers,
# including on a mixed-scaling multi-monitor desktop, so one saved
# "WxH+X+Y" means the same place to both.

def parse_geometry(geometry: str):
    """(w, h, x, y) from 'WxH+X+Y', or None."""
    m = _GEOMETRY_RE.fullmatch((geometry or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None


def format_geometry(w: int, h: int, x: int, y: int) -> str:
    return f"{w}x{h}+{x}+{y}"


def snapping(settings: dict) -> str:
    """The snap corner in force, or "" for none."""
    corner = settings.get("snap_corner") or ""
    return "" if corner == "none" else corner


def follows_cursor(settings: dict, launched_at_startup: bool) -> bool:
    """A manual launch opens on the cursor's monitor; a login launch does not."""
    return (not launched_at_startup
            and bool(settings.get("open_on_cursor_monitor", True)))


def saved_geometry(settings: dict) -> str | None:
    if not settings.get("remember_window_geometry", True):
        return None
    return settings.get("window_geometry") or None


def initial_geometry(settings: dict, *, size: tuple[int, int], target,
                     work_area_at) -> str | None:
    """Where the window opens, as 'WxH+X+Y', or None to leave it be.

    ``target`` is the cursor monitor's work area, or None (login launch, the
    setting off, or detection failed). ``work_area_at(x, y)`` finds the work
    area the saved geometry was on. With a snap corner the corner decides the
    position later; this only puts the window on the right monitor first.
    """
    w, h = size
    saved = saved_geometry(settings)
    if target is None:
        return saved if saved and not snapping(settings) else None
    if snapping(settings):
        return format_geometry(w, h, target[0], target[1])
    if saved:
        src = work_area_at(*geometry_origin(saved)) or target
        return relocate_geometry(saved, src, target)
    return center_in_work_area(w, h, target)


def snap_position(corner: str, w: int, h: int, work_area,
                  margin: int = 10) -> tuple[int, int]:
    """Top-left that puts a w x h window in ``corner`` of ``work_area``."""
    ax, ay, aw, ah = work_area
    x = ax + margin if "left" in corner else ax + aw - w - margin
    y = ay + margin if "top" in corner else ay + ah - h - margin
    return x, y
