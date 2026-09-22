"""How a pipeline step reads in the editor, and what reordering does.

`ui/pipeline.py` built the row label inline while filling a Tk listbox, and
the move-up/move-down handlers each rebuilt the id list by hand. Both are the
same whichever toolkit draws the list, so they live here and the Tk and Qt
editors share them (docs/plans/qt-migration.md).

Pure: takes step rows as returned by `db.list_pipeline_steps()`, returns
strings and lists.
"""

from __future__ import annotations

from .db import FAIL_CONTINUE, TRIGGER_WITH, WHEN_ON_FAILURE, WHEN_ON_SUCCESS

# Step rows have grown three times; everything here reads defensively by
# index and length, so an older row simply shows fewer marks rather than
# raising. See db.list_pipeline_steps for the full shape.
_ON_FAILURE = 10
_RETRIES = 11
_RUN_WHEN = 12
_DETACHED = 13


def policy_marks(step) -> str:
    """Compact suffix showing a step's non-default policy, or "" if all default.

    Only deviations are marked, so an ordinary pipeline's rows look exactly as
    they did before step policies existed.
    """
    marks = []
    if len(step) > _ON_FAILURE and step[_ON_FAILURE] == FAIL_CONTINUE:
        marks.append("!")
    if len(step) > _RETRIES and step[_RETRIES]:
        marks.append(f"↻{step[_RETRIES]}")
    if len(step) > _RUN_WHEN and step[_RUN_WHEN] == WHEN_ON_SUCCESS:
        marks.append("?ok")
    elif len(step) > _RUN_WHEN and step[_RUN_WHEN] == WHEN_ON_FAILURE:
        marks.append("?fail")
    if len(step) > _DETACHED and step[_DETACHED]:
        # Not a policy the editor sets -- it comes from the script -- but the
        # list is where you would wonder why a step doesn't hold the pipeline
        # up.
        marks.append("→launch")
    return ("   " + " ".join(marks)) if marks else ""


def step_label(step, index: int) -> str:
    """One row of the step list.

    ``index`` is zero-based; the label numbers from 1. A step that starts
    alongside the one above is prefixed with ∥, and the two-space prefix on
    the others keeps the numbers aligned under it.
    """
    name = step[2]
    params_override = step[6] if len(step) > 6 else None
    trigger_mode = step[7] if len(step) > 7 else None
    prefix = "∥ " if trigger_mode == TRIGGER_WITH else "  "
    label = f"{prefix}{index + 1}.  {name}"
    if params_override is not None:
        label += f"  [{params_override}]"
    return label + policy_marks(step)


def step_labels(steps) -> list[str]:
    """Every row, in order."""
    return [step_label(step, i) for i, step in enumerate(steps)]


def can_move(index: int | None, count: int, delta: int) -> bool:
    """Whether the step at ``index`` can move by ``delta``."""
    if index is None:
        return False
    target = index + delta
    return 0 <= index < count and 0 <= target < count


def reorder(step_ids: list, index: int, delta: int) -> list:
    """The id order after moving one step, or the original if it cannot move.

    Returns a new list: the caller hands this straight to
    `db.reorder_pipeline_steps`, and mutating its own list in place would
    leave the editor inconsistent if the write then failed.
    """
    ids = list(step_ids)
    if not can_move(index, len(ids), delta):
        return ids
    target = index + delta
    ids[index], ids[target] = ids[target], ids[index]
    return ids


def first_step_cannot_run_with_previous(index: int | None) -> bool:
    """Whether "run with previous" should be unavailable.

    There is nothing above step 1 to run alongside, so the control is
    meaningless there rather than merely unused.
    """
    return index is None or index == 0
