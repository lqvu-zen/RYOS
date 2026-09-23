"""UI-independent drag-and-drop rules for card reordering.

Pure functions extracted from ``RYOSApp``'s drag handlers so the geometry *and*
the decisions can be unit-tested without a display. Callers resolve screen
coordinates and widget state from widgets; these functions decide what should
happen. Nothing here imports a toolkit, which is also what lets the rules
survive the Qt migration (docs/plans/qt-migration.md).
"""

from __future__ import annotations

from dataclasses import dataclass

# What a completed drag does. The caller performs it; this module decides it.
MOVE_TO_GROUP = "move_to_group"   # the card was dropped on another group's tab
REORDER = "reorder"               # the card was dropped among its siblings
NOTHING = "nothing"               # no drag happened, or it changed nothing


@dataclass(frozen=True)
class DropAction:
    """The outcome of releasing a dragged card.

    ``group`` is the destination group for both real kinds: the tab dropped on
    for MOVE_TO_GROUP, and the list being reordered for REORDER. ``before_id``
    is the sibling to insert before, or None to append.
    """

    kind: str
    group: str | None = None
    before_id: int | None = None


def passed_threshold(dx: int, dy: int, threshold: int) -> bool:
    """Whether a press-and-move has travelled far enough to count as a drag.

    Both axes must stay inside the threshold for it to remain a click, which is
    what stops a card launching when the pointer twitches during a press.
    """
    return abs(dx) >= threshold or abs(dy) >= threshold


def shows_insertion_indicator(*, in_favorites: bool, active_group: str | None,
                              has_targets: bool) -> bool:
    """Whether an insertion line makes sense for this drag.

    In the "All" view (``active_group is None``) the main list spans several
    groups, so there is no single ordering to insert into -- but a favorites
    drag still reorders within the card's own group, so it stays legal there.
    """
    if not has_targets:
        return False
    return in_favorites or active_group is not None


def resolve_drop(*, dragged: bool, target_group: str | None, card_group: str,
                 in_favorites: bool, active_group: str | None,
                 insert_before: int | None) -> DropAction:
    """Decide what releasing the card does.

    ``dragged`` is False for a press that never passed the threshold -- a click,
    which must not reorder anything. Dropping a card back on its own tab is
    also a no-op rather than a redundant write.
    """
    if not dragged:
        return DropAction(NOTHING)
    if target_group is not None:
        if target_group == card_group:
            return DropAction(NOTHING)
        return DropAction(MOVE_TO_GROUP, group=target_group)
    if in_favorites:
        return DropAction(REORDER, group=card_group, before_id=insert_before)
    if active_group is not None:
        return DropAction(REORDER, group=active_group, before_id=insert_before)
    return DropAction(NOTHING)


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


#: Pixels the pointer must travel with the button down before a press becomes
#: a drag. Shared so a click that twitches behaves the same in both UIs.
DRAG_THRESHOLD = 6


def outside_base_warning(path: str, group: str, base_dir: str) -> "str | None":
    """The warning for a script moved into a group whose folder doesn't hold it.

    Moving is still allowed -- the group's base folder is a convenience for
    relative paths, not a fence -- but the user should know the script now
    lives somewhere its new group does not expect. None when there is nothing
    to say: no base folder, or the path is inside it.
    """
    from .quickrun import _is_inside

    if not base_dir or not path or _is_inside(path, base_dir):
        return None
    return (f"Warning: script moved to '{group}' but its path is outside "
            f"the group's base directory.")


# --- applying a drop ------------------------------------------------------------
# The database side of a drop, shared by both UIs. UI-independent: takes the
# ScriptDB and plain values, returns what to tell the user.

SCRIPT = "script"
PIPELINE = "pipeline"


def apply_move(db, kind: str, item_id: int, group: str) -> "str | None":
    """Move one card into ``group``. Returns a warning to show, or None."""
    if kind == PIPELINE:
        db.move_pipeline_to_group(item_id, group)
        return None
    db.move_to_group(item_id, group)
    rec = db.get(item_id)
    return outside_base_warning(rec[2] if rec else "", group,
                                db.get_group_base_dir(group))


def apply_reorder(db, kind: str, item_id: int, group: str,
                  before_id: "int | None") -> None:
    """Place one card before ``before_id`` in ``group`` (None appends)."""
    if kind == PIPELINE:
        db.reorder_pipeline(item_id, group, before_id)
    else:
        db.reorder_script(item_id, group, before_id)
