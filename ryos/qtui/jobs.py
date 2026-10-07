"""Connecting the Qt shell to the job machinery.

Everything about running jobs lives in ``ryos/jobhost.py``, toolkit-free and
shared with the headless runner. What is Qt-shaped is here, and small:

* **Draining the queue.** A ``QTimer`` calls ``JobHost.pump`` every
  ``PUMP_MS``.
* **Later, on the UI thread.** A launcher's release goes through
  ``QTimer.singleShot``, so it reaches the controller on the thread that
  pumps it.
* **Schedules.** A second ``QTimer`` runs the host's schedule sweep.
* **Signals.** The controller's callbacks become signals for the window.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import schedule_runner
from ..db import SOURCE_MANUAL, ScriptDB
from ..jobhost import PUMP_MS, JobHost
from ..logger import get_logger

__all__ = ["JobBridge", "PUMP_MS"]

_log = get_logger(__name__)


class JobBridge(QObject):
    """A ``JobHost`` for a Qt window: its timers, and its callbacks as signals.

    Emitting rather than calling keeps the window free to connect whatever it
    likes, and makes the bridge testable without one.
    """

    output = Signal(str, str, object, object)  # (tab_key, text, tag, step or None)
    #: (tab_key, token, label, state): a step running beside others changed.
    step_state = Signal(str, int, str, str)
    status = Signal(str)
    notify = Signal(str, str)              # (title, body)
    started = Signal(object)
    finished = Signal(object)
    renamed = Signal(object)

    def __init__(self, db: ScriptDB, settings: dict | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._host = JobHost(
            db, settings,
            call_later=lambda secs, fn: QTimer.singleShot(int(secs * 1000), fn),
            on_output=lambda tab_key, text, tag=None, step=None:
                self.output.emit(tab_key, text, tag, step),
            on_status=self.status.emit,
            on_notify=lambda title, body: self.notify.emit(title, body),
            on_started=self.started.emit,
            on_finished=self.finished.emit,
            on_renamed=self.renamed.emit,
            on_step=self.step_state.emit,
        )
        self.db = db
        self.registry = self._host.registry
        self.queue = self._host.queue
        self.controller = self._host.controller
        #: The host's own dict: the window updates it in place.
        self._settings = self._host.settings
        self._timer = QTimer(self)
        self._timer.setInterval(PUMP_MS)
        self._timer.timeout.connect(self._host.pump)
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.timeout.connect(self._tick_schedules)

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._timer.start()
        self._schedule_timer.start(schedule_runner.FIRST_TICK_MS)

    def stop(self) -> None:
        """Stop draining and terminate anything still running (window close)."""
        self._timer.stop()
        self._schedule_timer.stop()
        self._host.stop_all()

    def stop_job(self, job) -> None:
        self._host.stop_job(job)

    # -- starting work -----------------------------------------------------
    def run_script(self, script_id: int, name: str, path: str, params: str,
                   interpreter: str, *, trigger: str = SOURCE_MANUAL,
                   active_group: str | None = None,
                   on_refusal: Callable[[object], None] | None = None) -> bool:
        """Start a script, or report why not. True when it started."""
        return self._host.run_script(
            script_id, name, path, params, interpreter, trigger=trigger,
            active_group=active_group, on_refusal=on_refusal) is not None

    def run_pipeline(self, pipeline_id: int, name: str, *,
                     trigger: str = SOURCE_MANUAL,
                     active_group: str | None = None,
                     candidate_groups=(),
                     on_refusal: Callable[[object], None] | None = None) -> bool:
        """Start a pipeline, or report why not. True when it started."""
        return self._host.run_pipeline(
            pipeline_id, name, trigger=trigger, active_group=active_group,
            candidate_groups=candidate_groups, on_refusal=on_refusal) is not None

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
        return self._host.run_due_schedules(now)
