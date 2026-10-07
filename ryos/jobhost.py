"""Running jobs without a toolkit: the registry, the output queue, the
controller, and how a run is launched.

The window (``qtui/jobs.py``) and the headless runner (``headless.py``) both
host jobs through this, so there is one launch path, one launcher-release
rule and one schedule sweep for both. What differs between them comes in as
arguments:

* ``call_later(seconds, fn)`` runs ``fn`` later **on the thread that pumps**
  -- the controller is not thread-safe, so a launcher release must not reach
  it from a timer thread. The window passes ``QTimer.singleShot``.
* the controller's callbacks (output, status, notify, started, finished,
  renamed, step), which the window turns into signals.

Whoever hosts this calls ``pump()`` every ``PUMP_MS``; the worker threads only
ever feed the queue.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable

from . import schedule_runner
from .db import SOURCE_MANUAL, SOURCE_SCHEDULE, ScriptDB
from .job_controller import JobController
from .jobs import Job, JobRegistry
from .runner import run_subprocess, terminate_tree
from .settings import _SETTINGS_DEFAULTS

#: How often the host drains the queue: output appears at this rate.
PUMP_MS = 80


def _ignore(*_args) -> None:
    return None


class JobHost:
    """Owns the registry, the queue and the controller, and starts runs."""

    def __init__(self, db: ScriptDB, settings: dict | None = None, *,
                 call_later: Callable[[float, Callable[[], object]], None],
                 on_output: Callable[..., None] = _ignore,
                 on_status: Callable[[str], None] = _ignore,
                 on_notify: Callable[[str, str], None] = _ignore,
                 on_started: Callable[[Job], None] = _ignore,
                 on_finished: Callable[[Job], None] = _ignore,
                 on_renamed: Callable[[Job], None] = _ignore,
                 on_step: Callable[..., None] = _ignore,
                 base_notes: bool = False) -> None:
        self.db = db
        #: Live settings: the window updates this dict in place when the
        #: Options dialog saves, so a new cap applies to the next run.
        self.settings = dict(settings or {})
        self.registry = JobRegistry()
        self.queue: "queue.Queue" = queue.Queue()
        self._call_later = call_later
        self._on_status = on_status
        self._on_output = on_output
        self._on_finished = on_finished
        self.controller = JobController(
            self.registry, self.queue, self.db,
            on_output=on_output, on_status=on_status, on_notify=on_notify,
            on_started=on_started, on_finish=self._finish, on_rename=on_renamed,
            launch=self._launch, on_step=on_step,
            base_notes=base_notes,
        )

    # -- lifecycle ---------------------------------------------------------
    def pump(self) -> None:
        """Drain the output queue. Call it on one thread, every PUMP_MS."""
        self.controller.pump()

    def stop_all(self) -> None:
        """Terminate everything still running.

        For the host going away: a job left running past it would keep a
        worker thread and a subprocess alive with nowhere to report.
        """
        for job in self.registry.all():
            self.stop_job(job)

    def stop_job(self, job: Job) -> None:
        """Stop one job. It stays registered until it actually finishes, which
        is when its verdict (STOPPED) is recorded."""
        job.stopped = True
        job.pipeline_queue.clear()
        for proc in job.active_processes():
            terminate_tree(proc)

    def _finish(self, job: Job) -> None:
        """Unregister a finished job, then tell the host.

        A job left registered still counts toward the cap and still looks
        "running" to a schedule, which would then never fire again.
        """
        self.registry.remove(job.job_id)
        self._on_finished(job)

    def _max_jobs(self) -> int:
        return self.settings.get("max_parallel_jobs",
                                 _SETTINGS_DEFAULTS["max_parallel_jobs"])

    # -- launching ---------------------------------------------------------
    def _launch(self, job: Job, spec, name: str, script_id: int,
                step_token=None) -> None:
        self.db.mark_run(script_id)
        # step_token and log_output are keyword-only in effect: run_subprocess
        # takes log_output first positionally, so passing the token positionally
        # would silently enable run logging and lose the token.
        threading.Thread(
            target=run_subprocess,
            args=(self.queue, job, spec, name, script_id),
            kwargs={
                "log_output": bool(self.settings.get("log_runs_output", False)),
                "step_token": step_token,
            },
            daemon=True,
        ).start()
        # A launcher opens something and keeps running, so waiting for it
        # would stall the pipeline (issue #5) -- or, run on its own, leave it
        # in Running for as long as what it opened is up.
        if self.db.is_detached(script_id):
            secs = max(0, int(self.settings.get(
                "launcher_release_seconds",
                _SETTINGS_DEFAULTS["launcher_release_seconds"])))
            if step_token is not None:
                self._call_later(secs, lambda: self.controller.release_launcher_step(
                    job, step_token, script_id))
            elif job.kind == "script":
                self._call_later(secs, lambda: self.controller.release_launcher_script(
                    job, script_id))

    # -- starting work -----------------------------------------------------
    def run_script(self, script_id: int, name: str, path: str, params: str,
                   interpreter: str, *, trigger: str = SOURCE_MANUAL,
                   active_group: str | None = None,
                   on_refusal: Callable[[object], None] | None = None) -> Job | None:
        """Start a script, or report why not. The job when it started."""
        plan = self.controller.plan_script(
            script_id, path, params, interpreter,
            max_jobs=self._max_jobs(), active_group=active_group)
        if not plan.ok:
            if on_refusal is not None:
                on_refusal(plan.refusal)
            return None
        job = self.controller.new_job("script", script_id=script_id,
                                      pipeline_id=None, name=name,
                                      group=plan.group, trigger=trigger)
        job.start_time = datetime.now()
        if plan.note:
            self._on_output(job.tab_key, plan.note, "info")
        self._launch(job, plan.spec, name, script_id)
        return job

    def run_pipeline(self, pipeline_id: int, name: str, *,
                     trigger: str = SOURCE_MANUAL,
                     active_group: str | None = None,
                     candidate_groups=(),
                     on_refusal: Callable[[object], None] | None = None) -> Job | None:
        """Start a pipeline, or report why not. The job when it started."""
        plan = self.controller.plan_pipeline(
            pipeline_id, max_jobs=self._max_jobs(),
            active_group=active_group, candidate_groups=candidate_groups)
        if not plan.ok:
            if on_refusal is not None:
                on_refusal(plan.refusal)
            return None
        steps = list(plan.steps or [])
        job = self.controller.new_job(
            "pipeline", script_id=None, pipeline_id=pipeline_id,
            # No emoji bolt: the window's output tab draws one.
            name=name, group=plan.group, pipeline_name=name,
            pipeline_queue=steps, pipeline_total=len(steps),
            trigger=trigger)
        job.start_time = datetime.now()
        self.controller.run_next_pipeline_step(job)
        return job

    # -- schedules ---------------------------------------------------------
    def run_due_schedules(self, now: datetime | None = None) -> int:
        """One sweep of the shared schedule policy. Returns runs started."""
        max_jobs = self._max_jobs()
        return schedule_runner.run_due(
            self.db, now or datetime.now(),
            at_capacity=lambda: self.controller.at_capacity(max_jobs),
            running=lambda row: schedule_runner.is_running(
                row, self.registry.all()),
            launch=self._launch_scheduled)

    def _launch_scheduled(self, row) -> bool:
        """Start one scheduled run. False only when its target is gone.

        A refusal goes to the status line rather than a dialog: nobody clicked
        anything, and a modal box from a timer would sit over whatever the
        user is doing.
        """
        def refused(refusal) -> None:
            self._on_status(f"Scheduled run refused: {refusal.title}")

        script_id, pipeline_id = row[2], row[3]
        if pipeline_id is not None:
            name = schedule_runner.pipeline_name(self.db, pipeline_id)
            if name is None:
                return False
            # Every group is a candidate, so the pipeline's own group owns it.
            self.run_pipeline(pipeline_id, name, trigger=SOURCE_SCHEDULE,
                              candidate_groups=list(self.db.list_groups()) + [""],
                              on_refusal=refused)
            return True
        rec = self.db.get(script_id)
        if not rec:
            return False
        _, name, path, params, interp = rec[:5]
        self.run_script(script_id, name, path, params or "", interp or "",
                        trigger=SOURCE_SCHEDULE, active_group=rec[5] or "",
                        on_refusal=refused)
        return True
