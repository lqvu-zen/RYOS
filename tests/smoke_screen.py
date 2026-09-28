"""Which screen the smokes open their windows on.

A second monitor when there is one, so a run never covers the screen someone
is working on. RYOS_SMOKE_SCREEN=<n> picks another (0 is the primary).
Toolkit-free (Win32 through ctypes), so a smoke can decide before it starts
a Qt application or a separate process.
"""

import os
import sys


def _monitor_work_areas() -> list:
    """Every monitor's work area as (x, y, w, h), primary first; [] off Windows."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    from ryos.screens import _work_area_from_monitor

    areas: list = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(wintypes.RECT), ctypes.c_void_p)

    def collect(hmon, _hdc, _rect, _data):
        area = _work_area_from_monitor(hmon)
        if area:
            areas.append(area)
        return 1
    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(collect), 0)
    areas.sort(key=lambda a: (a[0], a[1]) != (0, 0))     # primary first
    return areas


def smoke_screen():
    """The work area the smokes' windows use, as (x, y, w, h), or None."""
    areas = _monitor_work_areas()
    if not areas:
        return None
    wanted = os.environ.get("RYOS_SMOKE_SCREEN")
    index = int(wanted) if wanted and wanted.isdigit() else (1 if len(areas) > 1 else 0)
    return areas[min(index, len(areas) - 1)]
