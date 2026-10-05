"""The maximised layout: when it applies, and what its detail pane says.

Maximised or full screen, the window becomes a rail of places, the list,
and the chosen script or pipeline in tabs: its overview, its output, its
run history. The Qt pane (`qtui/detail.py`) draws what this module decides;
nothing here imports a toolkit, so the wording and the rules are
unit-tested without a display.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import cardstyle

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


def run_label(last_status: str | None) -> str:
    """The pane's Run button's word; the button draws the row's icon beside it."""
    return "Retry" if cardstyle.run_button(last_status).is_retry else "Run"


def _or_dash(value) -> str:
    return str(value) if value else cardstyle.NO_VALUE


def subtitle(kind: str, rec: dict, step_count: int = 0) -> str:
    """The line under the name: what it is, and how its last run went."""
    status = {"ok": "OK", "error": "failed"}.get(rec.get("status") or "")
    if kind == "pipeline":
        plural = "s" if step_count != 1 else ""
        head = f"{step_count} step{plural}"
    else:
        head = cardstyle.display_path(rec.get("path", ""), rec.get("base_dir", ""))
    when = cardstyle.last_run_text(rec.get("last_run"))
    if status and when:
        return f"{head}  ·  last run {when}, {status}"
    if status:
        return f"{head}  ·  last run {status}"
    return head


def script_facts(rec: dict) -> list[tuple[str, str]]:
    """(label, value) rows for a script: where it is and how it runs."""
    return [
        ("Path", _or_dash(rec.get("path"))),
        ("Base folder", _or_dash(rec.get("base_dir"))),
        ("Parameters", _or_dash(rec.get("params"))),
        ("Asks each run", "Yes" if rec.get("temp_param") else "No"),
        ("Schedule", "Runs on a schedule" if rec.get("scheduled") else "None"),
        ("Last run", _or_dash(cardstyle.last_run_text(rec.get("last_run")))),
    ]


def pipeline_facts(rec: dict) -> list[tuple[str, str]]:
    """(label, value) rows for a pipeline; its steps are listed apart."""
    return [
        ("Schedule", "Runs on a schedule" if rec.get("scheduled") else "None"),
    ]
