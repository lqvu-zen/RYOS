"""The maximised layout: when it applies, and what its detail pane says.

Maximised or full screen, the window becomes a rail of places, the list,
and the chosen script or pipeline in tabs: its overview, its output, its
run history. The Qt pane (`qtui/detail.py`) draws what this module decides;
nothing here imports a toolkit, so the wording and the rules are
unit-tested without a display.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import activity, basefolder, cardstyle, history, pipelinesteps

#: What the pane shows before anything is chosen.
EMPTY = "Choose a script or pipeline on the left to see it here."
#: The pane's section headings.
PARAMETERS = "PARAMETERS"
STEPS = "STEPS"
#: The pane's buttons.
RUN_WITH = "Run with…"
SCHEDULE = "Schedule…"
EDIT = "Edit"

#: The list pane's width when the layout opens; the splitter can change it.
LIST_WIDTH = 380

#: The chosen item's views, as tabs over the pane, in this order.
OVERVIEW_TAB, OUTPUT_TAB, HISTORY_TAB = "Overview", "Output", "History"
TABS = (OVERVIEW_TAB, OUTPUT_TAB, HISTORY_TAB)


@dataclass(frozen=True)
class Place:
    """A button on the rail: where it goes, its icon, its name."""
    key: str
    icon: str
    name: str
    #: Kept to the rail's foot, apart from the places you work in.
    foot: bool = False


#: The rail down the window's left edge, top to bottom. Places, not actions:
#: what makes things stays in the header.
RAIL = (
    Place("library", "list", "Library"),
    Place("search", "search", "Search"),
    Place("activity", "activity", "Activity"),
    Place("appearance", "palette", "Appearance…", foot=True),
    Place("options", "settings", "Options…", foot=True),
)

#: The group picker's last entry, under the groups.
NEW_GROUP = "New group…"


def tab_when_run_starts(selected, job_kind: str, script_id, pipeline_id) -> str | None:
    """The tab to show when a run starts: Output, if it is the chosen item's.

    ``selected`` is the window's (kind, item id, section) or None. A run of
    anything else leaves the pane where it is -- a schedule firing in the
    background must not pull the view away from what is being read.
    """
    if not selected:
        return None
    kind, item_id = selected[0], selected[1]
    started = pipeline_id if job_kind == "pipeline" else script_id
    return OUTPUT_TAB if (kind, item_id) == (job_kind, started) else None


def use_workspace(maximized: bool, full_screen: bool, enabled: bool = True) -> bool:
    """Whether the window should show the list and the detail side by side.

    Only when it has the room: maximised or full screen. A window merely
    dragged wide keeps the single list, so resizing never swaps the layout
    out from under the pointer.
    """
    return enabled and (maximized or full_screen)


def run_label(last_status: str | None, own_run: bool = False) -> str:
    """The pane's Run button's word; the button draws the row's icon beside it."""
    spec = cardstyle.run_button(last_status, own_run)
    return "Stop" if spec.is_stop else "Retry" if spec.is_retry else "Run"


def _or_dash(value) -> str:
    return str(value) if value else cardstyle.NO_VALUE


def _when_words(stamp, now) -> str:
    """When a run started, as the Activity bar and the last-run box say it:
    "Today 22:33", "Yesterday 08:00", "Mon 08:00", "09-29 20:43"."""
    started = history.parse_stamp(stamp)
    if started is None:
        return ""
    when = activity.ago_text(started, now)
    return f"Today {when}" if started.date() == now.date() else when


def subtitle(kind: str, rec: dict, step_count: int = 0, now=None) -> str:
    """The line under the name: what it is, and how its last run went --
    in the same words as the last-run box below it."""
    from datetime import datetime
    status = {"ok": "OK", "error": "failed", "stopped": "stopped"}.get(
        rec.get("status") or "")
    if kind == "pipeline":
        plural = "s" if step_count != 1 else ""
        head = f"{step_count} step{plural}"
    else:
        head = cardstyle.display_path(rec.get("path", ""), rec.get("base_dir", ""))
    when = _when_words(rec.get("last_run"), now or datetime.now())
    if status and when:
        # Mid-sentence: "today", "yesterday"; a day's name keeps its capital.
        if when.startswith(("Today", "Yesterday")):
            when = when[0].lower() + when[1:]
        return f"{head}  ·  last run {when}, {status}"
    if status:
        return f"{head}  ·  last run {status}"
    return head


def script_facts(rec: dict) -> list[tuple[str, str]]:
    """(label, value) rows for a script: where it is and how it runs."""
    rows = [
        ("Path", _or_dash(rec.get("path"))),
        ("Base folder", _or_dash(rec.get("base_dir"))),
        ("Parameters", _or_dash(rec.get("params"))),
        ("Asks each run", "Yes" if rec.get("temp_param") else "No"),
        ("Schedule", "Runs on a schedule" if rec.get("scheduled") else "None"),
    ]
    if rec.get("outside"):
        rows.insert(2, ("Outside base folder",
                        basefolder.facts_value(tuple(rec["outside"]))))
    return rows


def pipeline_facts(rec: dict) -> list[tuple[str, str]]:
    """(label, value) rows for a pipeline; its steps are listed apart."""
    rows = [
        ("Schedule", "Runs on a schedule" if rec.get("scheduled") else "None"),
    ]
    if rec.get("outside_steps"):
        rows.append(("Outside base folder",
                     basefolder.step_label(tuple(rec["outside_steps"]))))
    return rows


# -- the Overview: steps as cards, the last run -------------------------------------

#: What the last-run box says before anything has run.
NOT_RUN = "Not run yet."
#: Its buttons: the run's output while its tab is open, else the history.
OPEN_OUTPUT, SEE_HISTORY = "Open output", "History"


@dataclass(frozen=True)
class StepCard:
    """One step of a pipeline, as a card in the Overview."""
    number: int
    name: str
    file: str
    status: str | None
    #: Starts with the step before it rather than after it.
    together: bool
    notes: tuple


def _file_name(path: str) -> str:
    return re.split(r"[\\/]", path or "")[-1]


def step_cards(steps, statuses: dict) -> list[StepCard]:
    """The pipeline's steps as cards: what each runs and how it behaves.

    ``steps`` are `ScriptDB.list_pipeline_steps` rows; ``statuses`` maps a
    script id to its last outcome. Notes are only what differs from the
    default -- the parameters it passes instead of the script's own, and the
    policies `pipelinesteps.policy_marks` words for the editor's list.
    """
    cards = []
    for i, step in enumerate(steps, 1):
        override = step[6] if len(step) > 6 else None
        notes = []
        if override is not None:
            notes.append(override or "no parameters")
        notes += [m for m in pipelinesteps.policy_marks(step).split("  ·  ") if m]
        cards.append(StepCard(i, step[2], _file_name(step[3]),
                              statuses.get(step[1]),
                              pipelinesteps.runs_with_previous(step), tuple(notes)))
    return cards


def last_run_lines(row, now) -> tuple[str, str] | None:
    """The last-run box's two lines, from a `ScriptDB.list_runs` row:
    ("Last run  ·  OK", "Today 21:09  ·  12.4s"); None before any run."""
    if row is None:
        return None
    status = row[7]
    word = {"ok": "OK", "error": "Failed"}.get(status, "Stopped")
    parts = [_when_words(row[5], now) or "—", history.format_duration(row[5], row[6])]
    if status == "error":
        parts.append("did not start" if row[8] is None else f"exit code {row[8]}")
    return f"Last run  ·  {word}", "  ·  ".join(p for p in parts if p != "—")


def last_run_row(rows, kind: str):
    """The row for an item's last run: a pipeline's own, not one of its steps."""
    for row in rows:
        if kind != "pipeline" or row[3] == "pipeline":
            return row
    return None
