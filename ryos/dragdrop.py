"""UI-independent geometry helpers for drag-and-drop reordering.

Pure functions extracted from ``RYOSApp``'s drag handlers so the insertion-index
and hit-test math can be unit-tested without a display. Callers resolve screen
coordinates from widgets; these functions make the decisions.
"""

from __future__ import annotations


def compute_insertion(drop_y: int, cards: list[tuple]) -> tuple:
    """Decide where a dragged card lands among ``cards``.

    ``cards`` is ``[(card_id, top_y, height), ...]`` for the visible (non-dragged)
    cards in screen order. Returns ``(before_id, indicator_y)``:

    - ``before_id`` is the id of the card the drop lands *before*, or ``None`` to
      append at the end.
    - ``indicator_y`` is the screen-y at which to draw the insertion line, or
      ``None`` when there are no cards to drop against.
    """
    for card_id, top, height in cards:
        mid = top + height // 2
        if drop_y <= mid:
            return card_id, top
    if cards:
        _, last_top, last_height = cards[-1]
        return None, last_top + last_height
    return None, None


def first_rect_at(x: int, y: int, rects: list[tuple]):
    """Return the key of the first rect containing ``(x, y)``, else ``None``.

    ``rects`` is ``[(key, left, top, width, height), ...]`` in priority order.
    """
    for key, left, top, width, height in rects:
        if left <= x <= left + width and top <= y <= top + height:
            return key
    return None
