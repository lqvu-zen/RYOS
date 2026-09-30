"""One icon set for the whole app, drawn in the theme's colours.

Buttons used to take their icons from wherever a glyph could be found: two
text fonts (▶ ↻ ✎ ☆ ✕), the colour-emoji font (⚡ 📁 🗑 🕒 🎨 -- in their own
colours, whatever the theme), one shape painted by hand, and SVG chevrons.
They never looked like one family.

Every icon here is drawn on the same 24-unit grid with the same 2-unit
stroke, round caps and joins (the shapes follow the Lucide set), and tinted
at runtime with a palette colour. Outline by default; filled only where
filling carries meaning -- play and stop (the actions), the brand bolt, and a
favourite's star.

`IconButton` is a QPushButton that holds its icon by name and colour role, so
it re-tints on a theme change (`retint_all`) and darkens under the pointer
the way the stylesheet darkens a quiet button's words.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

#: The body of each icon, inside a 24x24 viewBox. ``{c}`` is the colour.
#: Outline icons are stroked by the wrapper; a filled one fills itself.
SHAPES: dict[str, str] = {
    "play": '<path d="M7 4.8v14.4l12-7.2z" fill="{c}" stroke-width="1.6"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="{c}"/>',
    "retry": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4v5h5"/>',
    "run-with": '<path d="M5 5.5v13l9-6.5z"/><path d="M19 3.5v6M16 6.5h6"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "star": ('<path d="m12 3.2 2.7 5.5 6 .9-4.35 4.25 1.03 6L12 17l-5.38 2.85 '
             '1.03-6L3.3 9.6l6-.9z"/>'),
    "star-filled": ('<path d="m12 3.2 2.7 5.5 6 .9-4.35 4.25 1.03 6L12 17l-5.38 '
                    '2.85 1.03-6L3.3 9.6l6-.9z" fill="{c}"/>'),
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "more": ('<circle cx="5" cy="12" r="1.4" fill="{c}"/><circle cx="12" cy="12" '
             'r="1.4" fill="{c}"/><circle cx="19" cy="12" r="1.4" fill="{c}"/>'),
    "bolt": '<path d="M13 2.5 4.5 13.5H11l-1 8 8.5-11H12z" fill="{c}"/>',
    "folder": ('<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h3.8l2 2h7.2a2 2 0 0 1 2 2v7.5'
               'a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>'),
    "trash": ('<path d="M4 7h16"/><path d="M9.5 7V4.5h5V7"/>'
              '<path d="M6.5 7l.9 12.5h9.2L17.5 7"/>'),
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "history": ('<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4v5h5"/>'
                '<path d="M12 8v4l2.8 1.8"/>'),
    "copy": ('<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2"/>'
             '<path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>'),
    "palette": ('<path d="M12 3.5a8.5 8.5 0 1 0 0 17c.9 0 1.4-.7 1.4-1.5 0-.8-.6-1.3'
                '-.6-2.1 0-.8.7-1.5 1.6-1.5h2.1a4 4 0 0 0 4-4c0-4.4-3.8-7.9-8.5-7.9z"/>'
                '<circle cx="7.8" cy="11" r="1.1" fill="{c}"/>'
                '<circle cx="12" cy="7.6" r="1.1" fill="{c}"/>'
                '<circle cx="16.2" cy="11" r="1.1" fill="{c}"/>'),
    "arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "arrow-top": '<path d="M5 4h14M12 20V9.5M7 14l5-5 5 5"/>',
    "export": ('<path d="M12 14.5V3.5M7.5 8 12 3.5 16.5 8"/>'
               '<path d="M4.5 14.5v4a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4"/>'),
    "import": ('<path d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5"/>'
               '<path d="M4.5 14.5v4a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4"/>'),
    "save": ('<path d="M5.5 3.5h10l3 3v12a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-13'
             'a2 2 0 0 1 2-2z"/><path d="M8 3.5v4.5h7V3.5M7.5 20.5v-6h9v6"/>'),
    "select": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "chevron-up": '<path d="m6 15 6-6 6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "settings": ('<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/>'
                 '<circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'),
}

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="{c}" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">{body}</svg>')

_cache: dict[tuple, QPixmap] = {}


def svg(name: str, color: str) -> str:
    """The icon's SVG source in ``color``. KeyError for an unknown name."""
    return _SVG.replace("{body}", SHAPES[name]).replace("{c}", color)


def pixmap(name: str, color: str, size: int = 16) -> QPixmap:
    """The icon drawn ``size`` px square, sharp on a scaled screen."""
    key = (name, color, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    from PySide6.QtSvg import QSvgRenderer
    scale = 2
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(scale)
    renderer = QSvgRenderer(QByteArray(svg(name, color).encode("utf-8")))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    _cache[key] = pix
    return pix


def icon(name: str, color: str, size: int = 16, disabled: str | None = None) -> QIcon:
    """A QIcon of the shape; ``disabled`` is the colour it greys to."""
    result = QIcon(pixmap(name, color, size))
    if disabled:
        result.addPixmap(pixmap(name, disabled, size), QIcon.Mode.Disabled)
    return result


# -- colour roles -----------------------------------------------------------------------
def role_colors(palette: dict) -> dict:
    """The colour each role stands for in ``palette``: icons are tinted by
    role, so a theme change re-tints them all the same way."""
    from .stylesheet import drawn_colors
    d = drawn_colors(palette)
    return {
        "muted": d["muted_fg"],
        "text": palette["name_fg"],
        "link": d["tab_selected_fg"],
        "header": d["header_fg"],
        "primary": d["primary_fg"],
        "bolt": palette.get("bolt", "#FFD23F"),
        "star": d["star"],
        "pipe": palette.get("pipe_accent", palette["accent"]),
        "menu": palette.get("fg_on_dark", "#ffffff"),
        "danger": palette.get("menu_danger", palette["error"]),
        "disabled": palette["btn_disabled_fg"],
    }


class IconButton(QPushButton):
    """A button whose icon is a named shape in a colour role.

    ``hover_role`` is the colour under the pointer (quiet buttons darken like
    their words); ``retint`` redraws it for a new palette.
    """

    def __init__(self, name: str, text: str = "", *, role: str = "muted",
                 hover_role: str | None = "text", size: int = 16,
                 palette: dict | None = None, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._name, self._role, self._hover_role, self._size = name, role, hover_role, size
        self._colors: dict = {}
        self._hovered = False
        self.setIconSize(QSize(size, size))
        if palette is not None:
            self.retint(palette)

    def set_shape(self, name: str, role: str | None = None) -> None:
        self._name = name
        if role is not None:
            self._role = role
        self._draw()

    def set_colors(self, color: str, hover: str | None = None) -> None:
        """Tint with explicit colours rather than roles (Run on its fill)."""
        self._colors = {"role": color, "hover": hover or color,
                        "disabled": self._colors.get("disabled", color)}
        self._role, self._hover_role = "role", "hover"
        self._draw()

    def retint(self, palette: dict) -> None:
        roles = role_colors(palette)
        if self._role == "ink":
            pass                            # follows the stylesheet by itself
        elif self._role != "role":
            self._colors = roles
        else:
            self._colors["disabled"] = roles["disabled"]
        self._draw()

    def _draw(self) -> None:
        if self._role == "ink":
            # The button's own text colour, as the stylesheet set it: for
            # buttons in dialogs and bars that are not handed the palette.
            from PySide6.QtGui import QPalette
            ink = self.palette().color(QPalette.ColorRole.ButtonText).name()
            dim = self.palette().color(QPalette.ColorGroup.Disabled,
                                       QPalette.ColorRole.ButtonText).name()
            self.setIcon(icon(self._name, ink, self._size, disabled=dim))
            return
        if not self._colors:
            return
        role = self._hover_role if self._hovered and self._hover_role else self._role
        self.setIcon(icon(self._name, self._colors[role], self._size,
                          disabled=self._colors.get("disabled")))

    def changeEvent(self, event) -> None:              # noqa: N802
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if self._role == "ink" and event.type() in (QEvent.Type.StyleChange,
                                                    QEvent.Type.PaletteChange):
            self._draw()

    def showEvent(self, event) -> None:                # noqa: N802
        if self._role == "ink":
            self._draw()                    # polished by now: the ink is final
        super().showEvent(event)

    def enterEvent(self, event) -> None:               # noqa: N802
        self._hovered = True
        self._draw()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:               # noqa: N802
        self._hovered = False
        self._draw()
        super().leaveEvent(event)


class IconLabel(QLabel):
    """A picture-only label: the bolt in the header, the folder by its path."""

    def __init__(self, name: str, *, role: str = "muted", size: int = 16,
                 palette: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._name, self._role, self._size = name, role, size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if palette is not None:
            self.retint(palette)

    def retint(self, palette: dict) -> None:
        self.setPixmap(pixmap(self._name, role_colors(palette)[self._role], self._size))


def retint_all(root: QWidget, palette: dict) -> None:
    """Redraw every icon under ``root`` for a new palette."""
    for widget in root.findChildren(IconButton) + root.findChildren(IconLabel):
        widget.retint(palette)
