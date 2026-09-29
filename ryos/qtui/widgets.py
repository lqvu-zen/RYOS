"""Qt counterparts to `ui/widgets.py`.

Most of that module does not survive the port, and that is the point:

* **Tooltip** — Qt has `QWidget.setToolTip()`, with the delay handled by the
  style and the appearance by the `QToolTip` rule in `stylesheet.py`. The Tk
  class existed only because Tk has no tooltips. Use `set_tooltip()` below,
  which is a one-line wrapper kept so call sites read the same in both UIs.
* **HoverPreview** — the Tk version walks up from the widget under the pointer
  to decide whether the pointer really left the card, because Tk fires
  ``<Leave>`` for every child widget crossed. Qt sends `leaveEvent` only when
  the pointer leaves the widget *including* its children, so that machinery is
  not needed; `HoverPreview` here is a thin popup over `enterEvent` /
  `leaveEvent`.
* **ScrollingLabel** — Qt has no marquee either, so this is a real
  implementation. The arithmetic is `ryos.marquee`, shared with the Tk widget
  so the two cannot drift.

This module imports PySide6 and is therefore only importable when Qt is
installed; nothing outside `ryos/qtui/` imports it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (QFrame, QLabel, QLayout, QSizePolicy, QVBoxLayout,
                               QWidget)

from .. import marquee


def literal(text: str) -> str:
    """Text for a tab or menu item, shown as written.

    Qt reads "&" there as a keyboard-shortcut marker and hides it, so
    "Startup & Window" showed as "Startup  Window" and a group named "R&D"
    as "RD". Group, script and job names are the user's own text.
    """
    return text.replace("&", "&&")


def set_tooltip(widget: QWidget, text: str) -> None:
    """Attach a tooltip -- and, to a button drawn as a glyph, a name.

    Qt names a button after its text, so a screen reader announced Run as
    "black right-pointing triangle" and Edit as nothing useful. For a button
    whose text has no letters (▶ ✎ ☆ + ⋯ ✕, or an icon), the tooltip is the
    name worth saying; a worded button keeps its words as its name.
    """
    widget.setToolTip(text)
    from PySide6.QtWidgets import QAbstractButton
    if isinstance(widget, QAbstractButton) and not any(
            ch.isalpha() for ch in widget.text()):
        widget.setAccessibleName(text)


class ScrollingLabel(QWidget):
    """Clips and horizontally scrolls text wider than the widget.

    Same behaviour and same timings as the Tk widget, because both drive
    `ryos.marquee`. Scrolling pauses while the pointer is over the label, so
    text can be read without chasing it.
    """

    def __init__(self, text: str, parent: QWidget | None = None,
                 height: int = 22):
        super().__init__(parent)
        self._text = text
        self._offset = 0
        self._text_width = 0
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._measure()

    # -- content ----------------------------------------------------------
    def setText(self, text: str) -> None:
        self._text = text
        self._offset = 0
        self._measure()
        self.update()
        self._schedule()

    def text(self) -> str:
        return self._text

    def _measure(self) -> None:
        self._text_width = QFontMetrics(self.font()).horizontalAdvance(self._text)

    # -- animation --------------------------------------------------------
    def _schedule(self) -> None:
        self._timer.stop()
        if marquee.needs_scroll(self._text_width, self.width()):
            self._timer.start(marquee.IDLE_MS)

    def _tick(self) -> None:
        self._offset, wrapped = marquee.advance(self._offset, self._text_width)
        self.update()
        self._timer.start(marquee.next_delay(wrapped))

    def _pause(self) -> None:
        self._timer.stop()
        self._offset = 0
        self.update()

    # -- Qt events --------------------------------------------------------
    def resizeEvent(self, event) -> None:      # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._measure()
        self._offset = 0
        self._schedule()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:  # e.g. bold, by the stylesheet
            self._measure()
            self._schedule()

    def enterEvent(self, event: QEvent) -> None:   # noqa: N802
        super().enterEvent(event)
        self._pause()

    def leaveEvent(self, event: QEvent) -> None:   # noqa: N802
        super().leaveEvent(event)
        self._schedule()

    def paintEvent(self, event) -> None:       # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        painter.setFont(self.font())
        rect = self.rect().adjusted(-self._offset, 0, 0, 0)
        painter.drawText(rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self._text)
        painter.end()


class HoverPreview(QWidget):
    """A delayed popup showing caller-built detail for a card.

    The Tk version needed containment-aware leave detection, walking up from
    whatever widget sat under the pointer, because Tk fires ``<Leave>`` for
    each child crossed. Qt only sends `leaveEvent` when the pointer leaves the
    widget and all its children, so this is just a timer and a frameless
    window.
    """

    def __init__(self, host: QWidget, builder, delay_ms: int = 1000):
        super().__init__(host)
        self._host = host
        self._builder = builder
        self._delay_ms = delay_ms
        self._popup: QFrame | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show)
        host.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:      # noqa: N802
        if obj is self._host:
            kind = event.type()
            if kind == QEvent.Type.Enter:
                self._timer.start(self._delay_ms)
            elif kind in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress,
                          QEvent.Type.Hide):
                self.hide_now()
        return False

    def _show(self) -> None:
        if self._popup is not None:
            return
        popup = QFrame(self._host.window(),
                       Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("hoverPreview")
        QVBoxLayout(popup).setContentsMargins(8, 6, 8, 6)
        self._builder(popup)
        popup.adjustSize()
        popup.move(self._host.mapToGlobal(
            QPoint(self._host.width() // 2, self._host.height())))
        popup.show()
        self._popup = popup

    def hide_now(self) -> None:
        self._timer.stop()
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None


class ElidedLabel(QLabel):
    """A label that shortens text to fit, with "…" in the middle.

    For paths: a QLabel's minimum width is its whole text, so a long path
    made each card -- and the group page -- wider than the window, pushing the
    Run button off the right edge. This one asks for almost no width, shows
    the start and end of the path (the drive and the file name, the parts
    worth reading), and keeps the full text as the tooltip.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 mode=Qt.TextElideMode.ElideMiddle):
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setMinimumWidth(24)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)
        self._refit()

    def full_text(self) -> str:
        return self._full

    def setText(self, text: str) -> None:                  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._refit()

    def sizeHint(self):                                     # noqa: N802
        hint = super().sizeHint()
        hint.setWidth(QFontMetrics(self.font()).horizontalAdvance(self._full) + 4)
        return hint

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        self._refit()

    def _refit(self) -> None:
        width = max(0, self.width() - 2)
        QLabel.setText(self, QFontMetrics(self.font()).elidedText(
            self._full, self._mode, width) if width > 0 else self._full)


def button_row(buttons, destructive=None) -> QWidget:
    """A dialog's buttons, with any destructive one alone on the left.

    QDialogButtonBox places a DestructiveRole button by the platform's
    rules, which on Windows puts Delete right beside Save. Tk keeps it apart,
    on the left, where a slip of the mouse does not reach it.
    """
    from PySide6.QtWidgets import QHBoxLayout
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    if destructive is not None:
        lay.addWidget(destructive)
    lay.addStretch(1)
    lay.addWidget(buttons)
    return row


class FlowLayout(QLayout):
    """Lays widgets out left to right, wrapping onto a new line when full.

    Qt has none built in (it ships one as an example). Used for the
    Favorites strip, whose chips are sized to their names.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:                   # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):                      # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):                      # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):                     # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:               # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:       # noqa: N802
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect) -> None:               # noqa: N802
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self) -> QSize:                       # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:                    # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect, move: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line > 0:
                x, y, line = area.x(), y + line + self._spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()
