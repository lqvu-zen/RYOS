"""Monitor work areas from Qt, for the placement rules in `ryos.screens`.

`QScreen.availableGeometry()` is the work area (the screen minus the taskbar),
cross-platform, where `screens.py` has to ask Win32 through ctypes. Both
report the same numbers on Windows, including on a mixed-scaling desktop, so
the Tk and Qt shells can share one saved geometry.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor, QGuiApplication


def _area(screen):
    if screen is None:
        return None
    r = screen.availableGeometry()
    return (r.x(), r.y(), r.width(), r.height())


def work_area_at(x: int, y: int):
    """The work area of the screen containing (x, y), else the nearest one."""
    point = QPoint(int(x), int(y))
    screen = QGuiApplication.screenAt(point)
    if screen is None:
        screens = QGuiApplication.screens()
        if not screens:
            return None

        def distance(s):
            g = s.geometry()
            dx = max(g.left() - point.x(), 0, point.x() - g.right())
            dy = max(g.top() - point.y(), 0, point.y() - g.bottom())
            return dx * dx + dy * dy
        screen = min(screens, key=distance)
    return _area(screen)


def cursor_work_area():
    """The work area of the screen the mouse is on."""
    pos = QCursor.pos()
    return work_area_at(pos.x(), pos.y())
