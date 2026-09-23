"""Qt menus built from `ryos.cardmenu` entries.

The menus are data, defined once and shared with Tk; this only draws them.
Picking an entry calls ``on_pick(key)`` with the entry's action key.

A `QAction` has no per-item text colour, so the Tk menu's coloured entries
become something else: highlight entries get a swatch icon, shaded by the same
`themes.readable_highlight` the Tk menu uses. Dangerous entries (Delete) are
not red in Qt -- a stylesheet cannot select one action -- and rely on their
🗑 glyph and their confirmation prompt.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from ..themes import readable_highlight

SWATCH_PX = 12


def _swatch(color: str) -> QIcon:
    pix = QPixmap(SWATCH_PX, SWATCH_PX)
    pix.fill(QColor(color))
    return QIcon(pix)


def build_menu(parent: QWidget, items, on_pick: Callable[[str], None],
               palette: dict) -> QMenu:
    """A QMenu for ``items``. Nothing is shown; the caller decides how."""
    menu = QMenu(parent)
    _fill(menu, items, on_pick, palette)
    return menu


def _fill(menu: QMenu, items, on_pick, palette: dict) -> None:
    for item in items:
        if item.key is None:
            menu.addSeparator()
            continue
        if item.children:
            sub = menu.addMenu(item.label)
            sub.menuAction().setData(item.key)
            _fill(sub, item.children, on_pick, palette)
            continue
        action = menu.addAction(item.label)
        action.setData(item.key)
        action.setEnabled(item.enabled)
        if item.highlight:
            color = readable_highlight(item.highlight, palette["menu_bg"])
            if color:
                action.setIcon(_swatch(color))
        action.triggered.connect(lambda _checked=False, k=item.key: on_pick(k))


def actions_by_key(menu: QMenu) -> dict:
    """Every action in ``menu`` and its submenus, keyed by action key."""
    found = {}
    for action in menu.actions():
        key = action.data()
        if isinstance(key, str):
            found[key] = action
        if action.menu() is not None:
            found.update(actions_by_key(action.menu()))
    return found
