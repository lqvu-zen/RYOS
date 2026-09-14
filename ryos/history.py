"""Presentation helpers for run-history rows.

Pure and Tk-free, in the same spirit as ``search`` / ``grouping`` /
``screens``: the formatting decisions are the part worth testing, and keeping
them out of the dialog means they can be tested without a display.

A row is the tuple ``ScriptDB.list_runs`` returns:
``(id, script_id, pipeline_id, kind, name, started_at, finished_at, status,
exit_code, step_index, trigger_source)``.
"""
from datetime import datetime

# Column widths for the monospace list in RunHistoryDialog. The dialog's header
# label is built from the same numbers, so the two can't drift apart.
_W_WHEN = 17
_W_STATUS = 9
_W_TOOK = 8
_W_EXIT = 5

_STATUS_MARK = {
    "ok": "✓ ok",
    "error": "✗ error",
    "stopped": "· stopped",
}


def parse_stamp(value) -> datetime | None:
    """Best-effort datetime from a stored ISO string; None when unusable.

    History rows can outlive the code that wrote them, so an unparseable
    timestamp renders as a blank column rather than raising in a list redraw.
    """
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def format_when(started_at) -> str:
    """'MM-DD HH:MM:SS' — no year, because history is pruned to months."""
    stamp = parse_stamp(started_at)
    return stamp.strftime("%m-%d %H:%M:%S") if stamp else "—"


def format_duration(started_at, finished_at) -> str:
    """Elapsed time between two stamps: '4.2s', '2m 05s', or '—'.

    Switches to minutes at 60s and pads the seconds, so the column stays
    aligned in a monospace list.
    """
    start, end = parse_stamp(started_at), parse_stamp(finished_at)
    if start is None or end is None:
        return "—"
    secs = (end - start).total_seconds()
    if secs < 0:
        return "—"
    if secs < 60:
        return f"{secs:.1f}s"
    return f"{int(secs // 60)}m {int(secs % 60):02d}s"


def format_status(status) -> str:
    """A marked status label; unknown values pass through unchanged."""
    return _STATUS_MARK.get(status, status or "—")


def format_exit_code(exit_code) -> str:
    """Exit code, or '—' when the run never produced one (a launch failure)."""
    return "—" if exit_code is None else str(exit_code)


def describe(row) -> str:
    """The 'what' column: the item's name, with a step number when it has one."""
    name = row[4] or ""
    step_index = row[9]
    if row[3] == "step" and step_index is not None:
        return f"step {step_index}  {name}"
    return name


def format_run_row(row) -> str:
    """One fixed-width line for the history list."""
    return (f"{format_when(row[5]):<{_W_WHEN}}"
            f"{format_status(row[7]):<{_W_STATUS}}"
            f"{format_duration(row[5], row[6]):>{_W_TOOK}}  "
            f"{format_exit_code(row[8]):>{_W_EXIT}}   "
            f"{describe(row)}")


def header_row() -> str:
    """Column headings aligned to format_run_row."""
    return (f"{'WHEN':<{_W_WHEN}}{'STATUS':<{_W_STATUS}}{'TOOK':>{_W_TOOK}}  "
            f"{'EXIT':>{_W_EXIT}}   WHAT")


def summarize(rows) -> str:
    """'12 runs · 10 passed · 2 failed', or a note when there are none."""
    rows = list(rows)
    if not rows:
        return "No runs recorded yet."
    ok = sum(1 for r in rows if r[7] == "ok")
    plural = "s" if len(rows) != 1 else ""
    return f"{len(rows)} run{plural} · {ok} passed · {len(rows) - ok} failed"
