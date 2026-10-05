"""The maximised window's Activity bar: what is running, what runs next,
what ran last -- and the status bar's one-line summary of it.

What it lists and how it words it; the Qt bar (`qtui/activity.py`) draws it.
Nothing here imports a toolkit, so it is unit-tested without a display.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from . import history, scheduling

TITLE = "ACTIVITY"
RUNNING_NOW, UP_NEXT, RECENT = "RUNNING NOW", "UP NEXT", "RECENT"
NOTHING_RUNNING = "Nothing running."
NOTHING_SCHEDULED = "Nothing scheduled."
NO_RUNS = "No runs yet."
#: How many of each the bar lists.
UP_NEXT_COUNT, RECENT_COUNT = 3, 6
#: The bar's width when it opens.
WIDTH = 300

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class Entry:
    """One line in the bar: the item it is about, and what to say."""
    kind: str               # "script" or "pipeline"
    item_id: int
    name: str
    meta: str
    status: str | None = None   # "ok" / "error" for a run; None for a schedule


def _day(at: datetime, now: datetime) -> str:
    days = (at.date() - now.date()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days == -1:
        return "Yesterday"
    if -6 <= days <= 6:
        return _DAYS[at.weekday()]
    return at.strftime("%m-%d")


def when_text(at: datetime, now: datetime) -> str:
    """When a run is due: "Today 08:00", "Tomorrow 08:00", "Fri 18:30"."""
    return f"{_day(at, now)} {at:%H:%M}"


def ago_text(at: datetime, now: datetime) -> str:
    """When a run started: "21:09" today, else with the day, "Mon 21:09"."""
    if at.date() == now.date():
        return f"{at:%H:%M}"
    return when_text(at, now)


def up_next(schedules, names: dict, now: datetime,
            limit: int = UP_NEXT_COUNT) -> list[Entry]:
    """The next scheduled runs, soonest first.

    ``schedules`` are `ScriptDB.list_schedules` rows; ``names`` maps
    (kind, id) to the item's name, and a schedule whose item is gone is left
    out. One not yet given a time (enabled a moment ago) gets one on the
    scheduler's next tick, so it is left out until then too.
    """
    found = []
    for row in schedules:
        _id, kind, script_id, pipeline_id, spec_type, spec, enabled = row[:7]
        at = history.parse_stamp(row[8])
        item_id = pipeline_id if kind == "pipeline" else script_id
        name = names.get((kind, item_id))
        if not enabled or at is None or name is None:
            continue
        try:
            rule = json.loads(spec) if isinstance(spec, str) else spec
        except ValueError:
            rule = None         # still listed: the time is what matters here
        meta = f"{when_text(at, now)}  ·  {scheduling.describe_spec(spec_type, rule)}"
        found.append((at, Entry(kind, item_id, name, meta)))
    found.sort(key=lambda pair: pair[0])
    return [entry for _at, entry in found[:limit]]


def recent(runs, now: datetime, limit: int = RECENT_COUNT) -> list[Entry]:
    """The last runs, newest first, as `ScriptDB.list_runs` gives them.

    A pipeline's steps are rows of their own in the history; here the
    pipeline stands for them. A run with no outcome yet is still going, and
    is under Running now instead.
    """
    out = []
    for row in runs:
        kind, status = row[3], row[7]
        if kind not in ("script", "pipeline") or status not in ("ok", "error"):
            continue
        item_id = row[2] if kind == "pipeline" else row[1]
        if item_id is None:
            continue
        started = history.parse_stamp(row[5])
        when = ago_text(started, now) if started else "—"
        if status == "ok":
            meta = f"OK  ·  {when}  ·  {history.format_duration(row[5], row[6])}"
        elif row[8] is None:
            meta = f"Failed  ·  {when}  ·  did not start"
        else:
            meta = f"Failed  ·  {when}  ·  exit code {row[8]}"
        out.append(Entry(kind, item_id, row[4] or "", meta, status))
        if len(out) == limit:
            break
    return out


def badge(running: int) -> str:
    """The count on the rail's Activity button; nothing when idle."""
    if running <= 0:
        return ""
    return str(running) if running < 10 else "9+"


def summary(running: int, next_entry: Entry | None) -> str:
    """The status bar's right-hand line: "1 running  ·  next: Backup, Today 08:00"."""
    parts = []
    if running:
        parts.append(f"{running} running")
    if next_entry is not None:
        when = next_entry.meta.split("  ·  ")[0]
        parts.append(f"next: {next_entry.name}, {when}")
    return "  ·  ".join(parts)
