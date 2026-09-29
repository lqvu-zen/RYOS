"""The maximised layout: when it applies, and what its detail pane says.

Maximised or full screen, the window becomes a list on the left and the
chosen script or pipeline on the right, with the output under it. The Qt
pane (`qtui/detail.py`) draws what this module decides; nothing here imports
a toolkit, so the wording and the rules are unit-tested without a display.
"""

from __future__ import annotations

from . import cardstyle

#: What the pane shows before anything is chosen.
EMPTY = "Choose a script or pipeline on the left to see it here."
#: The pane's section headings.
PARAMETERS = "PARAMETERS"
STEPS = "STEPS"
OUTPUT = "OUTPUT"
#: The pane's buttons.
RUN_WITH = "Run with…"
SCHEDULE = "Schedule…"
HISTORY = "Run history"
EDIT = "Edit"

#: The list pane's width when the layout opens; the splitter can change it.
LIST_WIDTH = 380


def use_workspace(maximized: bool, full_screen: bool, enabled: bool = True) -> bool:
    """Whether the window should show the list and the detail side by side.

    Only when it has the room: maximised or full screen. A window merely
    dragged wide keeps the single list, so resizing never swaps the layout
    out from under the pointer.
    """
    return enabled and (maximized or full_screen)


def run_label(last_status: str | None) -> str:
    """The pane's Run button: the row's glyph, with the word beside it."""
    spec = cardstyle.run_button(last_status)
    return f"{spec.glyph}  {'Retry' if spec.is_retry else 'Run'}"


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
