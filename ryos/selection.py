"""Select mode: tick scripts, then run or delete them together.

The wording and the decisions, shared by the Tk and Qt select bars. Both UIs
own the checkboxes; everything they show or decide about the ticked set comes
from here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .jobs import split_by_capacity

HINT = "Tick the checkboxes next to the scripts you want to run or delete."
ENTER_LABEL = "☑  Select scripts"
LEAVE_LABEL = "✕  Cancel select"

NOTHING_TO_RUN = ("Nothing Selected",
                  "Tick the checkboxes next to the scripts you want to run.")
NOTHING_TO_DELETE = ("Nothing Selected",
                     "Tick the checkboxes next to the scripts you want to delete.")


def bar_text(selected: int, total: int) -> str:
    """The select bar's message: the hint until something is ticked."""
    return f"{selected} of {total} selected" if selected else HINT


def all_selected(selected: int, total: int) -> bool:
    return total > 0 and selected == total


def select_all_label(selected: int, total: int) -> str:
    return "Deselect All" if all_selected(selected, total) else "Select All"


def select_all_target(flags) -> bool:
    """What Select All sets every box to: off only when all are already on."""
    flags = list(flags)
    return not (flags and all(flags))


@dataclass(frozen=True)
class RunPlan:
    """How many ticked scripts to start, and what to tell the user."""

    start: int
    skipped: int
    notice: "tuple[str, str] | None"     # (title, text) for a dialog, or None
    status: "str | None"                 # a status-line message, or None


def plan_run(selected: int, running: int, max_jobs: int) -> RunPlan:
    """Resolve capacity once, up front.

    Launching until each run refused itself would pop one "too many jobs" box
    per script. The selection is left in place either way, so the skipped
    ones can be run again once something finishes.
    """
    if selected <= 0:
        return RunPlan(0, 0, NOTHING_TO_RUN, None)
    can, skipped = split_by_capacity(selected, running, max_jobs)
    if skipped:
        plural = "s" if selected != 1 else ""
        return RunPlan(can, skipped, (
            "Job limit reached",
            f"Started {can} of {selected} selected script{plural}.\n\n"
            f"{skipped} could not start because the limit of {max_jobs} "
            "parallel jobs was reached. They are still selected — run them "
            "again once something finishes."), None)
    return RunPlan(can, 0, None,
                   f"Started {can} script{'s' if can != 1 else ''}.")


def delete_prompt(count: int) -> tuple[str, str]:
    return "Delete Selected", f"Delete {count} selected script(s)?"
