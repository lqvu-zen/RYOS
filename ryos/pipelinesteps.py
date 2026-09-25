"""How a pipeline step reads in the editor, and what reordering does.

`ui/pipeline.py` built the row label inline while filling a Tk listbox, and
the move-up/move-down handlers each rebuilt the id list by hand. Both are the
same whichever toolkit draws the list, so they live here and the Tk and Qt
editors share them (docs/plans/qt-migration.md).

Pure: takes step rows as returned by `db.list_pipeline_steps()`, returns
strings and lists.
"""

from __future__ import annotations

from pathlib import PurePath

from .db import (FAIL_CONTINUE, FAIL_STOP, TRIGGER_AFTER, TRIGGER_WITH,
                 WHEN_ALWAYS, WHEN_ON_FAILURE, WHEN_ON_SUCCESS)

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


# --- the editor's controls ------------------------------------------------------
# What the policy combos offer and show, the trigger toggle, the per-step preset
# choice and the Add Step list. Shared so the two editors cannot drift -- they
# already had, with different "run when" wording and a different legend.

LEGEND = ("∥ = starts together with the step above   ·   "
          "! = keeps going if it fails   ·   ↻n = retries   ·   "
          "?ok / ?fail = only after success / failure   ·   "
          "→launch = launcher; doesn't hold up the next step")

FAIL_LABELS = {FAIL_STOP: "Stop the pipeline", FAIL_CONTINUE: "Keep going"}
WHEN_LABELS = {WHEN_ALWAYS: "Always",
               WHEN_ON_SUCCESS: "Only if nothing has failed",
               WHEN_ON_FAILURE: "Only if something has failed"}
RETRY_CHOICES = tuple(range(6))

DEFAULT_PRESET = "(Script default)"
NAME_REQUIRED = ("Name Required", "Enter a pipeline name.")


def policy_of(step) -> tuple:
    """(on_failure, retries, run_when) for a step row, defaulting what is absent."""
    on_failure = step[_ON_FAILURE] if len(step) > _ON_FAILURE else FAIL_STOP
    retries = step[_RETRIES] if len(step) > _RETRIES else 0
    run_when = step[_RUN_WHEN] if len(step) > _RUN_WHEN else WHEN_ALWAYS
    return (on_failure if on_failure in FAIL_LABELS else FAIL_STOP,
            int(retries or 0),
            run_when if run_when in WHEN_LABELS else WHEN_ALWAYS)


def policy_from_labels(fail_label: str, retries, when_label: str) -> dict:
    """The keyword arguments for `db.set_step_policy`, from what the combos show."""
    inv_fail = {v: k for k, v in FAIL_LABELS.items()}
    inv_when = {v: k for k, v in WHEN_LABELS.items()}
    try:
        n = int(retries)
    except (TypeError, ValueError):
        n = 0
    return {"on_failure": inv_fail.get(fail_label, FAIL_STOP),
            "retries": max(0, n),
            "run_when": inv_when.get(when_label, WHEN_ALWAYS)}


def runs_with_previous(step) -> bool:
    return len(step) > 7 and step[7] == TRIGGER_WITH


def trigger_button_label(step) -> str:
    """The toggle says which way it will go for *this* step."""
    return "→ After Prev" if runs_with_previous(step) else "∥ With Prev"


def toggled_trigger(step) -> str:
    return TRIGGER_AFTER if runs_with_previous(step) else TRIGGER_WITH


def preset_choices(presets) -> list:
    """The step-preset combo's entries: the default, then each preset's params."""
    return [DEFAULT_PRESET] + [p[2] for p in presets]


def preset_shown(override, choices) -> str:
    """Which entry to show for a step's stored override."""
    return override if override in choices else DEFAULT_PRESET


def override_from_choice(choice: str):
    """What to store for a chosen entry: None means use the script's own."""
    return None if choice == DEFAULT_PRESET else choice


def add_step_choices(scripts, group: str) -> dict:
    """Label -> script id for the Add Step list: the group's scripts.

    Two scripts with the same name are told apart by file name, since picking
    the wrong one of two "build" entries would be silent.
    """
    mine = [s for s in scripts if (s[8] or "") == group]
    counts: dict = {}
    for s in mine:
        counts[s[1]] = counts.get(s[1], 0) + 1
    choices = {}
    for s in mine:
        label = s[1] if counts[s[1]] == 1 else f"{s[1]}  ({PurePath(s[2]).name})"
        choices[label] = s[0]
    return choices


# --- creating one ---------------------------------------------------------------------

ADD_PIPELINE_LABEL = "+ Pipeline"
NEW_PIPELINE_PROMPT = ("New Pipeline", "Pipeline name:")
SELECT_GROUP_FIRST = ("Select a Group",
                      "Please select a group first to create a pipeline.")
