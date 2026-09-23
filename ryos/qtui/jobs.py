"""Connecting the Qt shell to the job machinery.

`JobController` was written UI-free with its callbacks injected, so this is
wiring rather than a port: the same controller that drives the Tk app drives
the Qt one, given Qt-flavoured callbacks and a Qt timer to drain the queue.

The two toolkit-shaped pieces are both small and both live here:

* **Draining the queue.** Tk uses ``after(80, ...)``; Qt uses a ``QTimer`` at
  the same interval, so output appears at the same rate in both.
* **Launching.** A worker thread runs ``runner.run_subprocess``; nothing about
  it is Tk- or Qt-specific except which scheduler defers the launcher release.
* **Schedules.** A second ``QTimer`` runs the sweep in ``schedule_runner``,
  the same one the Tk app runs on ``after``.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import schedule_runner
from ..db import SOURCE_MANUAL, SOURCE_SCHEDULE, ScriptDB
from ..logger import get_logger
from ..job_controller import JobController
from ..jobs import JobRegistry
from ..runner import run_subprocess
from ..settings import _SETTINGS_DEFAULTS

#: Same cadence as the Tk drain loop, so output appears at the same rate.
PUMP_MS = 80

_log = get_logger(__name__)


class JobBridge(QObject):
    """Owns the registry, the queue and the controller for a Qt window.

    Signals are how the controller's callbacks reach widgets: the controller
    runs on the UI thread here (the pump is a QTimer), but emitting rather
    than calling keeps the window free to connect whatever it likes, and makes
    the bridge testable without one.
    """

    output = Signal(str, str, object)      # (tab_key, text, tag)
    status = Signal(str)
    notify = Signal(str, str)              # (title, body)
    started = Signal(object)
    finished = Signal(object)
    renamed = Signal(object)

    def __init__(self, db: ScriptDB, settings: dict | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.db = db
        self._settings = dict(settings or {})
        self.registry = JobRegistry()
        self.queue: "queue.Queue" = queue.Queue()
        self.controller = JobController(
            self.registry, self.queue, self.db,
            on_output=lambda tab_key, text, tag=None:
                self.output.emit(tab_key, text, tag),
            on_status=self.status.emit,
            on_notify=lambda title, body: self.notify.emit(title, body),
            on_started=self.started.emit,
            on_finish=self._on_finish,
            on_rename=self.renamed.emit,
            launch=self._launch,
        )
        self._timer = QTimer(self)
        self._timer.setInterval(PUMP_MS)
        self._timer.timeout.connect(self.controller.pump)
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.timeout.connect(self._tick_schedules)

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._timer.start()
        self._schedule_timer.start(schedule_runner.FIRST_TICK_MS)

    def stop(self) -> None:
        """Stop draining and terminate anything still running.

        Called on window close: a job left running past the window would keep
        a worker thread and a subprocess alive with nowhere to report.
        """
        self._timer.stop()
        self._schedule_timer.stop()
        for job in self.registry.all():
            job.stopped = True
            for proc in job.active_processes():
                try:
                    proc.terminate()
                except OSError:
                    pass

    def _on_finish(self, job) -> None:
        """Unregister a finished job, then tell whoever is listening.

        The controller leaves this to its host, as Tk's ``_finish_job`` does.
        A job left registered still counts toward the cap and still looks
        "running" to a schedule, which would then never fire again.
        """
        self.registry.remove(job.job_id)
        self.finished.emit(job)

    # -- launching ---------------------------------------------------------
    def _launch(self, job, spec, name: str, script_id: int,
                step_token=None) -> None:
        self.db.mark_run(script_id)
        # step_token and log_output are keyword-only in effect: run_subprocess
        # takes log_output first positionally, so passing the token positionally
        # would silently enable run logging and lose the token.
        threading.Thread(
            target=run_subprocess,
            args=(self.queue, job, spec, name, script_id),
            kwargs={
                "log_output": bool(self._settings.get("log_runs_output", False)),
                "step_token": step_token,
            },
            daemon=True,
        ).start()
        # A launcher step opens something and keeps running, so waiting for it
        # would stall the pipeline (issue #5). Released after the same grace
        # period the Tk app uses.
        if step_token is not None and self.db.is_detached(script_id):
            secs = max(0, int(self._settings.get(
                "launcher_release_seconds",
                _SETTINGS_DEFAULTS["launcher_release_seconds"])))
            QTimer.singleShot(
                secs * 1000,
                lambda: self.controller.release_launcher_step(
                    job, step_token, script_id))

    # -- starting work -----------------------------------------------------
    def run_script(self, script_id: int, name: str, path: str, params: str,
                   interpreter: str, *, trigger: str = SOURCE_MANUAL,
                   active_group: str | None = None,
                   on_refusal: Callable[[object], None] | None = None) -> bool:
        """Start a script, or report why not. True when it started."""
        plan = self.controller.plan_script(
            script_id, path, params, interpreter,
            max_jobs=self._settings.get(
                "max_parallel_jobs", _SETTINGS_DEFAULTS["max_parallel_jobs"]),
            active_group=active_group)
        if not plan.ok:
            if on_refusal is not None:
                on_refusal(plan.refusal)
            return False
        job = self.controller.new_job("script", script_id=script_id,
                                      pipeline_id=None, name=name,
                                      group=plan.group, trigger=trigger)
        job.start_time = datetime.now()
        self._launch(job, plan.spec, name, script_id)
        return True

    def run_pipeline(self, pipeline_id: int, name: str, *,
                     trigger: str = SOURCE_MANUAL,
                     active_group: str | None = None,
                     candidate_groups=(),
                     on_refusal: Callable[[object], None] | None = None) -> bool:
        """Start a pipeline, or report why not. True when it started."""
        plan = self.controller.plan_pipeline(
            pipeline_id,
            max_jobs=self._settings.get(
                "max_parallel_jobs", _SETTINGS_DEFAULTS["max_parallel_jobs"]),
            active_group=active_group, candidate_groups=candidate_groups)
        if not plan.ok:
            if on_refusal is not None:
                on_refusal(plan.refusal)
            return False
        job = self.controller.new_job(
            "pipeline", script_id=None, pipeline_id=pipeline_id,
            name=f"⚡ {name}", group=plan.group, pipeline_name=name,
            pipeline_queue=list(plan.steps), pipeline_total=len(plan.steps),
            trigger=trigger)
        job.start_time = datetime.now()
        self.controller.run_next_pipeline_step(job)
        return True

    # -- schedules ---------------------------------------------------------
    def _tick_schedules(self) -> None:
        """Fire whatever is due, then re-arm. One bad row never stops the timer."""
        try:
            self.run_due_schedules()
        except Exception:
            _log.warning("Schedule tick failed", exc_info=True)
        finally:
            self._schedule_timer.start(schedule_runner.TICK_MS)

    def run_due_schedules(self, now: datetime | None = None) -> int:
        """One sweep of the shared schedule policy. Returns runs started."""
        max_jobs = self._settings.get(
            "max_parallel_jobs", _SETTINGS_DEFAULTS["max_parallel_jobs"])
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
            self.status.emit(f"Scheduled run refused: {refusal.title}")

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
