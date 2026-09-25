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


class CardList(QWidget):
    """A group's cards, accepting drops that reorder them.

    Scripts reorder among scripts and pipelines among pipelines -- they are
    stored in separate orderings, so an insertion point is only meaningful
    against cards of the dragged kind. Drops from another group are refused
    here; moving between groups is what the tab strip is for.
    """

    dropped = Signal(object, object)     # (CardPayload, before_id or None)

    def __init__(self, group: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.group = group
        self.setAcceptDrops(True)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(4)
        self.layout_.addStretch(1)
        self._cards: list = []
        self.indicator = QFrame(self)
        self.indicator.setObjectName("dropIndicator")
        self.indicator.setFixedHeight(INDICATOR_HEIGHT)
        self.indicator.hide()

    def add_card(self, card, kind: str, item_id: int) -> None:
        card.drag_payload = CardPayload(kind, item_id, self.group)
        self.layout_.insertWidget(self.layout_.count() - 1, card)
        self._cards.append(card)

    @property
    def cards(self) -> list:
        return list(self._cards)

    # -- where a drop lands ----------------------------------------------------
    def insertion_for(self, payload: CardPayload, y: int) -> tuple:
        """(before_id, indicator_y) for a drop at ``y``, by the shared rule."""
        rows = [(c.drag_payload.item_id, c.geometry().y(), c.geometry().height())
                for c in self._cards
                if c.drag_payload.kind == payload.kind
                and c.drag_payload.item_id != payload.item_id
                and c.isVisible()]
        return dragdrop.compute_insertion(y, rows)

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
        _before, y = self.insertion_for(payload, int(event.position().y()))
        if y is None:
            self.indicator.hide()
        else:
            self.indicator.setGeometry(0, max(0, y - 2), self.width(),
                                       INDICATOR_HEIGHT)
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
        before, _y = self.insertion_for(payload, int(event.position().y()))
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
