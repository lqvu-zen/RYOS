"""Select mode: tick scripts or pipelines, then run or delete them together.

The wording and the decisions, shared by the Tk and Qt select bars. Both UIs
own the checkboxes; everything they show or decide about the ticked set comes
from here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cardmenu import PIPELINE, SCRIPT, steps_note
from .jobs import split_by_capacity

HINT = "Tick the boxes next to the scripts or pipelines you want to run or delete."
ENTER_LABEL = "Select scripts or pipelines"
LEAVE_LABEL = "Cancel select"

NOTHING_TO_RUN = ("Nothing Selected",
                  "Tick the boxes next to the scripts or pipelines you want to run.")
NOTHING_TO_DELETE = ("Nothing Selected",
                     "Tick the boxes next to the scripts or pipelines you want to delete.")

#: The select bar's agent buttons (hidden in a build without agents).
AGENTS_ON_LABEL = "Make available to agents"
AGENTS_OFF_LABEL = "Make unavailable to agents"
NOTHING_TO_EXPOSE = ("Nothing Selected",
                     "Tick the boxes next to the scripts or pipelines agents may run.")


def count_words(scripts: int, pipelines: int) -> str:
    """Like '2 scripts and 1 pipeline', '1 pipeline' or '3 scripts'."""
    parts = []
    if scripts or not pipelines:
        parts.append(f"{scripts} script{'s' if scripts != 1 else ''}")
    if pipelines:
        parts.append(f"{pipelines} pipeline{'s' if pipelines != 1 else ''}")
    return " and ".join(parts)


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


def _noun(kinds) -> str:
    p = sum(1 for k in kinds if k == PIPELINE)
    if p and p != len(kinds):
        return "scripts and pipelines"
    return ("pipeline" if p else "script") + ("s" if len(kinds) != 1 else "")


def plan_run(selected, running: int, max_jobs: int) -> RunPlan:
    """Resolve capacity once, up front.

    `selected` is the ticked kinds (cardmenu.SCRIPT / PIPELINE) in launch
    order, or a count of scripts. Launching until each run refused itself
    would pop one "too many jobs" box per item. The selection is left in
    place either way, so the skipped ones can be run again once something
    finishes.
    """
    kinds = ([] if isinstance(selected, int) and selected <= 0
             else [SCRIPT] * selected if isinstance(selected, int)
             else list(selected))
    if not kinds:
        return RunPlan(0, 0, NOTHING_TO_RUN, None)
    can, skipped = split_by_capacity(len(kinds), running, max_jobs)
    if skipped:
        return RunPlan(can, skipped, (
            "Job limit reached",
            f"Started {can} of {len(kinds)} selected {_noun(kinds)}.\n\n"
            f"{skipped} could not start because the limit of {max_jobs} "
            "parallel jobs was reached. They are still selected — run them "
            "again once something finishes."), None)
    p = sum(1 for k in kinds[:can] if k == PIPELINE)
    return RunPlan(can, 0, None, f"Started {count_words(can - p, p)}.")


def delete_prompt(count: int, used_in=(), pipelines: int = 0) -> tuple[str, str]:
    return ("Delete Selected",
            f"Delete {count_words(count, pipelines)}?" + steps_note(used_in, "Their"))
