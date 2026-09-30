"""Drag-and-drop for the Qt cards: reorder within a group, or drop on a tab.

The Tk version draws its own ghost window, tracks the pointer with motion
events, and hit-tests the tab strip by hand. Qt has real drag-and-drop:
`QDrag` carries the payload and draws the preview, and each drop target
receives `dragMoveEvent` / `dropEvent` with the position already translated.
What stays the same are the rules, which live in `ryos.dragdrop` and are
shared with Tk: the threshold that separates a click from a drag, where an
insertion lands, and what a release actually does.

Two design points, both for the sake of being checkable:

* `dropEvent` computes the insertion from the drop position itself, rather
  than trusting whatever the last `dragMoveEvent` left behind -- so a drop can
  be delivered and verified on its own.
* `start_drag` takes the thing that runs the drag as a parameter. The real one,
  `QDrag.exec`, blocks until a physical mouse button is released.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Callable

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import QFrame, QTabBar, QVBoxLayout, QWidget

from .. import dragdrop

MIME = "application/x-ryos-card"
INDICATOR_HEIGHT = 3


@dataclass(frozen=True)
class CardPayload:
    """What a dragged card carries: enough to act on it, nothing else."""

    kind: str               # "script" or "pipeline"
    item_id: int
    group: str

    def encode(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @staticmethod
    def decode(raw) -> "CardPayload | None":
        """The payload from mime bytes, or None for anything that is not ours."""
        try:
            data = json.loads(bytes(raw).decode("utf-8"))
            return CardPayload(str(data["kind"]), int(data["item_id"]),
                               str(data["group"]))
        except (TypeError, ValueError, KeyError, UnicodeDecodeError):
            return None


def payload_from(mime: QMimeData) -> "CardPayload | None":
    if mime is None or not mime.hasFormat(MIME):
        return None
    return CardPayload.decode(mime.data(MIME).data())


def start_drag(source: QWidget, payload: CardPayload, press: QPoint,
               now: QPoint, *,
               run: "Callable[[QDrag], object] | None" = None) -> bool:
    """Begin a drag if the pointer has moved far enough. True if it did.

    ``run`` executes the drag; the default is ``QDrag.exec``, which blocks
    until a real mouse button is released, so a test passes its own.
    """
    delta = now - press
    if not dragdrop.passed_threshold(delta.x(), delta.y(),
                                     dragdrop.DRAG_THRESHOLD):
        return False
    mime = QMimeData()
    mime.setData(MIME, payload.encode())
    drag = QDrag(source)
    drag.setMimeData(mime)
    preview = source.grab()
    if not preview.isNull():
        drag.setPixmap(preview.scaledToWidth(
            min(preview.width(), 320),
            Qt.TransformationMode.SmoothTransformation))
        drag.setHotSpot(QPoint(12, 12))
    (run or (lambda d: d.exec(Qt.DropAction.MoveAction)))(drag)
    return True


def _set_last(card: QWidget, last: bool) -> None:
    """Mark ``card`` as its panel's last row, for the stylesheet."""
    card.setProperty("last", last)
    card.style().unpolish(card)
    card.style().polish(card)


class CardList(QWidget):
    """A group's cards, accepting drops that reorder them.

    Scripts reorder among scripts and pipelines among pipelines -- they are
    stored in separate orderings, so an insertion point is only meaningful
    against cards of the dragged kind. Drops from another group are refused
    here; moving between groups is what the tab strip is for.
    """

    dropped = Signal(object, object)     # (CardPayload, before_id or None)

    def __init__(self, group: str, parent: QWidget | None = None, *,
                 flow: bool = False):
        super().__init__(parent)
        self.group = group
        self.flow = flow
        self.setAcceptDrops(True)
        # One panel per section, its cards rows of it (the stylesheet); or,
        # for the Favorites strip, chips that wrap.
        self.setObjectName("sectionPanel")
        self.setProperty("flow", flow)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if flow:
            from .widgets import FlowLayout
            self.layout_ = FlowLayout(self, spacing=6)
        else:
            self.layout_ = QVBoxLayout(self)
            self.layout_.setContentsMargins(0, 0, 0, 0)
            self.layout_.setSpacing(0)
            self.layout_.addStretch(1)
        self._cards: list = []
        self.indicator = QFrame(self)
        self.indicator.setObjectName("dropIndicator")
        if not flow:
            self.indicator.setFixedHeight(INDICATOR_HEIGHT)
        self.indicator.hide()

    def add_card(self, card, kind: str, item_id: int) -> None:
        card.drag_payload = CardPayload(kind, item_id, self.group)
        if self.flow:
            self.layout_.addWidget(card)
        else:
            self.layout_.insertWidget(self.layout_.count() - 1, card)
        # Rows are split by a hairline under each; the last row's would sit
        # on the panel's own edge and draw it twice.
        if self._cards:
            _set_last(self._cards[-1], False)
        _set_last(card, True)
        self._cards.append(card)

    @property
    def cards(self) -> list:
        return list(self._cards)

    # -- where a drop lands ----------------------------------------------------
    def insertion_for(self, payload: CardPayload, y: int) -> tuple:
        """(before_id, indicator_y) for a drop at ``y``, by the shared rule."""
        rows = [(c.drag_payload.item_id, c.geometry().y(), c.geometry().height())
                for c in self._others(payload)]
        return dragdrop.compute_insertion(y, rows)

    def _others(self, payload: CardPayload) -> list:
        return [c for c in self._cards
                if c.drag_payload.kind == payload.kind
                and c.drag_payload.item_id != payload.item_id
                and c.isVisible()]

    def flow_insertion_for(self, payload: CardPayload, pos: QPoint) -> tuple:
        """(before_id, indicator rect or None) for a drop at ``pos`` among
        chips that wrap: before the first chip that comes after the point in
        reading order -- a line further down, or on its line and to its right.
        """
        from PySide6.QtCore import QRect
        chips = self._others(payload)
        for c in chips:
            g = c.geometry()
            if pos.y() < g.top() or (pos.y() <= g.bottom() and pos.x() < g.center().x()):
                return c.drag_payload.item_id, QRect(g.left() - 4, g.top(),
                                                     INDICATOR_HEIGHT, g.height())
        if not chips:
            return None, None
        g = chips[-1].geometry()
        return None, QRect(g.right() + 2, g.top(), INDICATOR_HEIGHT, g.height())

    def _target(self, payload: CardPayload, pos: QPoint) -> tuple:
        """(before_id, where the indicator goes or None), for either layout."""
        if self.flow:
            return self.flow_insertion_for(payload, pos)
        from PySide6.QtCore import QRect
        before, y = self.insertion_for(payload, pos.y())
        return before, (None if y is None
                        else QRect(0, max(0, y - 2), self.width(), INDICATOR_HEIGHT))

    def _accepts(self, payload: "CardPayload | None") -> bool:
        return payload is not None and payload.group == self.group

    # -- Qt events ---------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:          # noqa: N802
        if self._accepts(payload_from(event.mimeData())):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:           # noqa: N802
        payload = payload_from(event.mimeData())
        if not self._accepts(payload):
            event.ignore()
            self.indicator.hide()
            return
        _before, rect = self._target(payload, event.position().toPoint())
        if rect is None:
            self.indicator.hide()
        else:
            self.indicator.setGeometry(rect)
            self.indicator.raise_()
            self.indicator.show()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:          # noqa: N802
        self.indicator.hide()

    def dropEvent(self, event) -> None:               # noqa: N802
        self.indicator.hide()
        payload = payload_from(event.mimeData())
        if not self._accepts(payload):
            event.ignore()
            return
        before, _rect = self._target(payload, event.position().toPoint())
        event.acceptProposedAction()
        self.dropped.emit(payload, before)


class GroupTabBar(QTabBar):
    """The group tabs, accepting a card dropped onto a tab to move it there."""

    dropped_on_group = Signal(object, str)   # (CardPayload, group name)
    menu_requested = Signal(str, QPoint)     # (group key, global position)
    reordered = Signal(list)                 # tab keys, once a tab drag ends

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMovable(True)
        self._hover_index = -1
        # tabMoved fires on every step of a tab drag; the new order is
        # reported once, on release, so nothing rebuilds mid-drag.
        self._moved = False
        self.tabMoved.connect(lambda _f, _t: setattr(self, "_moved", True))
        self._trailing: QWidget | None = None

    # -- a widget just after the last tab (the "+" for a new group) ---------------
    TRAILING_GAP = 4
    #: Space the stylesheet leaves under each pill, which the widget ignores.
    TAB_BOTTOM_MARGIN = 8

    def set_trailing(self, widget: QWidget) -> None:
        """Keep ``widget`` just after the last tab, wherever that is."""
        self._trailing = widget
        widget.setParent(self)
        widget.show()
        self._place_trailing()

    def sizeHint(self):                                # noqa: N802
        hint = super().sizeHint()
        if self._trailing is not None:
            hint.setWidth(hint.width() + self._trailing.sizeHint().width()
                          + 2 * self.TRAILING_GAP)
        return hint

    def tabLayoutChange(self) -> None:                 # noqa: N802
        super().tabLayoutChange()
        self._place_trailing()

    def resizeEvent(self, event) -> None:              # noqa: N802
        super().resizeEvent(event)
        self._place_trailing()

    def _place_trailing(self) -> None:
        w = self._trailing
        if w is None:
            return
        w.adjustSize()
        # In the gap the stylesheet leaves before All (the last tab): after
        # the last group, or -- with All alone, on a first launch -- before
        # it. It used to go after a lone All and was drawn over it.
        n = self.count()
        last = self.tabRect(n - 2 if n >= 2 else n - 1) if n else None
        if last is None:
            x = 0
        elif n >= 2:
            x = last.right() + self.TRAILING_GAP
        else:
            x = last.left() + self.TRAILING_GAP
        x = max(0, min(x, self.width() - w.width()))
        band = (last.height() - self.TAB_BOTTOM_MARGIN) if last is not None \
            else self.height()
        top = last.top() if last is not None else 0
        w.move(x, top + max(0, (band - w.height()) // 2))
        w.raise_()

    def tab_keys(self) -> list:
        return [self.tabData(i) for i in range(self.count())]

    def mouseReleaseEvent(self, event) -> None:       # noqa: N802
        super().mouseReleaseEvent(event)
        if self._moved:
            self._moved = False
            self.reordered.emit(self.tab_keys())

    def group_at(self, pos: QPoint) -> "str | None":
        """The group under ``pos``: the key stored in the tab, not its label.

        Labels are for people ("Ungrouped"); the key is what the database
        stores (""). Reading the label back would move a card into a group
        literally named "Ungrouped".
        """
        index = self.tabAt(pos)
        if index < 0:
            return None
        key = self.tabData(index)
        # A tab with no key (All) is not a group: nothing drops on it.
        return key if isinstance(key, str) else None

    def contextMenuEvent(self, event) -> None:        # noqa: N802
        group = self.group_at(event.pos())
        if group is None:
            event.ignore()
            return
        self.menu_requested.emit(group, event.globalPos())

    def dragEnterEvent(self, event) -> None:          # noqa: N802
        if payload_from(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:           # noqa: N802
        if payload_from(event.mimeData()) is None:
            event.ignore()
            return
        # Highlight the tab that would receive it, as the Tk strip does.
        # Deliberately not switching to it: that would swap out the page the
        # drag started on, and the card list the user may be heading back to.
        point = event.position().toPoint()
        self._highlight(self.tabAt(point) if self.group_at(point) is not None else -1)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:          # noqa: N802
        self._highlight(-1)

    def _highlight(self, index: int) -> None:
        if index == self._hover_index:
            return
        if self._hover_index >= 0:
            self.setTabTextColor(self._hover_index, QColor())   # back to default
        if index >= 0:
            self.setTabTextColor(index, self.palette().highlight().color())
        self._hover_index = index

    @property
    def hovered_index(self) -> int:
        return self._hover_index

    def dropEvent(self, event) -> None:               # noqa: N802
        self._highlight(-1)
        payload = payload_from(event.mimeData())
        group = self.group_at(event.position().toPoint())
        if payload is None or group is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.dropped_on_group.emit(payload, group)
