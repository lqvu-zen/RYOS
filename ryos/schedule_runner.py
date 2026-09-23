"""Firing due schedules: the sweep both UIs run on a timer.

`scheduling.py` answers "when is this next due"; this module answers "it is
due now -- may it run, and what is stored afterwards". It is toolkit-free: the
caller owns the timer and says how to check capacity and how to launch, so
the Tk app and the Qt bridge share one policy:

* an unusable spec is disabled rather than retried every tick forever;
* nothing launches past the parallel-job cap;
* a schedule never stacks a second run on one still going;
* a schedule whose script or pipeline has gone is disabled;
* ``next_run_at`` advances whether or not anything launched, so a skipped run
  never leaves the schedule permanently overdue.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Iterable

from .history import parse_stamp
from .logger import get_logger
from .scheduling import resolve_due

_log = get_logger(__name__)

TICK_MS = 30_000          # how often the sweep runs
FIRST_TICK_MS = 2_000     # the first sweep, shortly after the window opens


def is_running(row, jobs: Iterable) -> bool:
    """True when this schedule's script or pipeline is already in flight."""
    script_id, pipeline_id = row[2], row[3]
    for job in jobs:
        if script_id is not None and job.script_id == script_id:
            return True
        if pipeline_id is not None and job.pipeline_id == pipeline_id:
            return True
    return False


def pipeline_name(db, pipeline_id: int) -> "str | None":
    """The pipeline's name, or None when it no longer exists."""
    groups = list(db.list_groups()) + [""]
    for group in groups:
        for p in db.list_pipelines(group):
            if p[0] == pipeline_id:
                return p[1]
    return None


def run_due(db, now: datetime, *,
            at_capacity: Callable[[], bool],
            running: Callable[[object], bool],
            launch: Callable[[object], bool]) -> int:
    """Fire every schedule due at ``now``. Returns how many runs started.

    ``running(row)`` says whether the target is already in flight;
    ``launch(row)`` starts one run and returns False only when the target is
    missing -- a refusal (bad path, empty pipeline) is the launcher's to
    report and still counts as an attempt, so the schedule stays enabled.
    """
    total = 0
    for row in db.due_schedules(now):
        sched_id, spec_type, spec_raw, catch_up = row[0], row[4], row[5], row[7]
        try:
            spec = json.loads(spec_raw)
        except (TypeError, ValueError):
            spec = None
        times, next_at = resolve_due(spec_type, spec, parse_stamp(row[8]),
                                     now, catch_up)
        if next_at is None:
            _log.warning("Disabling schedule %s: unusable spec %r/%r",
                         sched_id, spec_type, spec_raw)
            db.set_schedule_enabled(sched_id, False)
            continue
        fired = 0
        for _ in range(times):
            if at_capacity():
                _log.info("Schedule %s skipped: job cap reached", sched_id)
                break
            if running(row):
                _log.info("Schedule %s skipped: previous run still going",
                          sched_id)
                break
            if not launch(row):
                _log.warning("Schedule %s targets a missing item; disabling",
                             sched_id)
                db.set_schedule_enabled(sched_id, False)
                break
            fired += 1
        db.mark_schedule_fired(sched_id, next_at, now if fired else None)
        total += fired
    return total
