"""Job state and helpers for running scripts and pipelines.

The Job container and the pure elapsed-time formatter live here, separate from
the Tkinter app, as the first step toward a self-contained job subsystem. Job
holds references to Tk widgets/vars, but only as annotations, so this module
does not import tkinter (``from __future__ import annotations`` keeps them lazy).
"""
from __future__ import annotations

from datetime import datetime


class Job:
    """One running job (script or pipeline)."""

    def __init__(self, job_id: int, kind: str, script_id, pipeline_id, name: str,
                 tab_key: str, group: str, pipeline_name: str = "",
                 pipeline_queue=None, pipeline_total: int = 0):
        self.job_id = job_id
        self.kind = kind
        self.script_id = script_id
        self.pipeline_id = pipeline_id
        self.name = name
        self.tab_key = tab_key
        self.group = group
        self.start_time: datetime = datetime.now()
        self.current_process = None
        self.stopped: bool = False
        self.pipeline_name = pipeline_name
        self.pipeline_queue: list = pipeline_queue if pipeline_queue is not None else []
        self.pipeline_step_idx: int = 0
        self.pipeline_total: int = pipeline_total
        self.name_var: tk.StringVar | None = None       # noqa: F821 (annotation only)
        self.time_var: tk.StringVar | None = None       # noqa: F821 (annotation only)
        self.running_row: tk.Frame | None = None        # noqa: F821 (annotation only)


def format_elapsed(start_time: datetime, now: datetime) -> str:
    """Return the running-row time label, e.g. '14:03:09  ·  1m 05s'.

    Below a minute it reads '… · 5s'; at/over a minute, '… · Xm YYs' (minutes
    are not capped at 60). Pure function of the two timestamps.
    """
    secs = int((now - start_time).total_seconds())
    elapsed = f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"
    return f"{start_time.strftime('%H:%M:%S')}  ·  {elapsed}"


class JobRegistry:
    """Owns the active jobs and allocates job ids.

    Pure bookkeeping — no Tk, no threads — so it can be unit-tested directly.
    The Tkinter app delegates its in-memory job table to an instance of this.
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
