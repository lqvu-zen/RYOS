"""Job state and helpers for running scripts and pipelines.

The Job container and the pure elapsed-time formatter, free of any toolkit:
the window keeps its own widgets for a job (see qtui/running.py).
"""
from __future__ import annotations

from datetime import datetime


class Job:
    """One running job (script or pipeline)."""

    def __init__(self, job_id: int, kind: str, script_id, pipeline_id, name: str,
                 tab_key: str, group: str, pipeline_name: str = "",
                 pipeline_queue=None, pipeline_total: int = 0,
                 trigger: str = "manual"):
        self.job_id = job_id
        self.kind = kind
        # What started this run, recorded in the history row. "manual" until
        # something other than a click can start a job.
        self.trigger = trigger
        # step_token -> when that step launched, so a history row can record a
        # step's own duration rather than the whole pipeline's.
        self.step_started: dict = {}
        # Per-step failure policy, main-thread-owned.
        #   step_rows    token -> the step row, kept so a retry can relaunch it
        #   step_retries token -> attempts still available for that step
        self.step_rows: dict = {}
        # Launcher steps released before their process exited. Their real
        # completion arrives later and must be ignored, or it would be
        # mis-attributed to whatever step is pending by then.
        self.released_steps: set = set()
        self.step_retries: dict = {}
        # token -> "attempt/budget" while that step is on a retry attempt.
        self.retrying: dict = {}
        # Two distinct flags. pipeline_failed means *something* failed and
        # drives run_when; pipeline_stopping means a step whose policy is
        # 'stop' failed, which halts normal steps and fails the run. A step set
        # to continue can set the first without setting the second.
        self.pipeline_failed: bool = False
        self.pipeline_stopping: bool = False
        self.pipeline_failed_at: int | None = None
        self.script_id = script_id
        self.pipeline_id = pipeline_id
        self.name = name
        self.tab_key = tab_key
        self.group = group
        self.start_time: datetime = datetime.now()
        self.current_process = None
        self.processes: dict = {}          # step_token -> Popen; None key for non-pipeline scripts
        self.stopped: bool = False
        self.pipeline_name = pipeline_name
        self.pipeline_queue: list = pipeline_queue if pipeline_queue is not None else []
        self.pipeline_step_idx: int = 0
        self.pipeline_total: int = pipeline_total
        # Concurrent-group bookkeeping (main-thread-owned); empty/falsy means
        # no group is active, i.e. the legacy single-step path.
        self.group_pending: set = set()
        self.group_failed: bool = False
        self.group_failed_at: int | None = None
        self.group_labels: dict = {}       # token -> step name, for output prefixing
        self.group_size: int = 0

    def active_processes(self) -> list:
        """Live handles for every in-flight step of this job (snapshot)."""
        return [p for p in list(self.processes.values())
                if p is not None and p.poll() is None]


RUNNING = "running"
RETRYING = "retrying"
#: A run the user stopped -- recorded as neither passed nor failed.
STOPPED = "stopped"


def own_runs(jobs) -> set:
    """The ``(kind, id)`` of each item with a run of its OWN in flight.

    A script that is only running as a pipeline's step is not one: stopping
    it from its row would stop somebody else's pipeline. Its row says
    Running (`live_statuses`) but keeps Run.
    """
    out = set()
    for job in jobs:
        if job.kind == "pipeline":
            out.add(("pipeline", job.pipeline_id))
        else:
            out.add(("script", job.script_id))
    return out


def live_statuses(jobs) -> dict:
    """What each card should say while jobs are in flight (issue #13).

    Maps ``(kind, id)`` -- the window's card keys, "script" / "pipeline" --
    to RUNNING or RETRYING. A pipeline also lights up the scripts of its
    in-flight steps. Retrying wins over running, so a script that is both a
    step being retried and running on its own reads as retrying.
    """
    out: dict = {}

    def mark(key, state):
        if out.get(key) != RETRYING:
            out[key] = state

    for job in jobs:
        if job.kind == "pipeline":
            retrying = bool(job.retrying)
            mark(("pipeline", job.pipeline_id), RETRYING if retrying else RUNNING)
            for token in job.group_pending:
                row = job.step_rows.get(token)
                if row is not None:
                    mark(("script", row[1]),
                         RETRYING if token in job.retrying else RUNNING)
        elif job.script_id is not None:
            mark(("script", job.script_id), RUNNING)
    return out


def running_heading(count: int) -> str:
    """The Running list's heading: what the rows under it are, and how many.

    Without it the rows sat between the cards and the output bar looking like
    one more card -- hard to tell a run was going at all.
    """
    return f"● RUNNING  ·  {count}"


def format_elapsed(start_time: datetime, now: datetime) -> str:
    """Return the running-row time label, e.g. '14:03:09  ·  1m 05s'.

    Below a minute it reads '… · 5s'; at/over a minute, '… · Xm YYs' (minutes
    are not capped at 60). Pure function of the two timestamps.
    """
    secs = int((now - start_time).total_seconds())
    elapsed = f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"
    return f"{start_time.strftime('%H:%M:%S')}  ·  {elapsed}"


def split_by_capacity(requested: int, running: int, max_jobs: int) -> tuple[int, int]:
    """How many of `requested` launches fit: ``(can_start, skipped)``.

    ``max_jobs <= 0`` means no cap, which is what the setting uses for
    "unlimited". Pure, so the bulk-run decision can be tested without widgets —
    and so the caller can refuse the remainder once, with a count, instead of
    launching until each individual launch pops its own "too many jobs" box.
    """
    requested = max(0, int(requested))
    if max_jobs <= 0:
        return requested, 0
    free = max(0, max_jobs - max(0, int(running)))
    can = min(requested, free)
    return can, requested - can


class JobRegistry:
    """Owns the active jobs and allocates job ids.

    Pure bookkeeping — no toolkit, no threads — so it can be unit-tested
    directly. The job bridge (qtui/jobs.py) keeps its job table in one.
    """

    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        self._next_id = 0

    def new_id(self) -> int:
        """Allocate and return the next monotonic job id (never reused)."""
        self._next_id += 1
        return self._next_id

    def add(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    def remove(self, job_id: int) -> None:
        """Drop a job by id; a no-op if it isn't registered."""
        self._jobs.pop(job_id, None)

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        """A snapshot list of registered jobs (safe to iterate while mutating)."""
        return list(self._jobs.values())

    def in_group(self, group: str) -> list[Job]:
        return [j for j in self._jobs.values() if j.group == group]

    def __len__(self) -> int:
        return len(self._jobs)

    def __bool__(self) -> bool:
        return bool(self._jobs)
