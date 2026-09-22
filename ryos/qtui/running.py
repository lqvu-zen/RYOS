"""The running-jobs section.

One row per in-flight job: a colour strip marking script or pipeline, the
job's name, how long it has been going, and a stop button. The elapsed label
is `jobs.format_elapsed`, shared with the Tk section, so both tick identically.

Rows are keyed by job id rather than held in a list: a job can finish while
the ticker is mid-sweep, and looking one up by id is what keeps a finished
job's row from being refreshed after its widget has gone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..jobs import format_elapsed

#: How often the elapsed labels are refreshed. Once a second is enough for a
#: seconds-resolution label and costs nothing.
TICK_MS = 1000

#: Width of the strip down the left of each row.
STRIP_WIDTH = 5


class RunningRow(QFrame):
    """One in-flight job."""

    stop_requested = Signal(object)

    def __init__(self, job, palette: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.job = job
        self.setObjectName("runningRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(8)

        strip = QWidget()
        strip.setFixedWidth(STRIP_WIDTH)
        colour = (palette.get("pipe_accent", palette["accent"])
                  if getattr(job, "kind", "") == "pipeline"
                  else palette.get("running", palette["accent"]))
        strip.setStyleSheet(f"background: {colour};")
        row.addWidget(strip)

        self.name_label = QLabel(job.name)
        self.name_label.setObjectName("cardName")
        row.addWidget(self.name_label, 1)

        self.time_label = QLabel(self._elapsed())
        self.time_label.setObjectName("cardPath")
        row.addWidget(self.time_label)

        self.stop_button = QPushButton("⏹ Stop")
        self.stop_button.setObjectName("stop")
        self.stop_button.clicked.connect(
            lambda: self.stop_requested.emit(self.job))
        row.addWidget(self.stop_button)

    def _elapsed(self) -> str:
        return format_elapsed(self.job.start_time, datetime.now())

    def tick(self) -> None:
        self.time_label.setText(self._elapsed())
        # A pipeline renames itself as it advances through its steps.
        if self.name_label.text() != self.job.name:
            self.name_label.setText(self.job.name)


class RunningSection(QWidget):
    """The list of running jobs, with its own empty state.

    `on_stop` is called with the job; stopping is the caller's business, and
    the row is removed when the job actually finishes rather than when the
    button is pressed -- a job that refuses to die should keep its row and its
    stop button.
    """

    def __init__(self, palette: dict, parent: QWidget | None = None, *,
                 on_stop: Callable[[object], None] | None = None):
        super().__init__(parent)
        self._palette = palette
        self._on_stop = on_stop
        self._rows: dict[int, RunningRow] = {}

        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(3)
        self._empty = QLabel("Nothing running.")
        self._empty.setObjectName("cardPath")
        self._col.addWidget(self._empty)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # -- rows --------------------------------------------------------------
    def add(self, job) -> RunningRow:
        """Show a job. Idempotent: a job already shown keeps its row."""
        existing = self._rows.get(job.job_id)
        if existing is not None:
            return existing
        row = RunningRow(job, self._palette)
        if self._on_stop is not None:
            row.stop_requested.connect(self._on_stop)
        self._rows[job.job_id] = row
        self._col.insertWidget(self._col.count() - 1, row)
        self._refresh_empty()
        if not self._timer.isActive():
            self._timer.start()
        return row

    def remove(self, job) -> None:
        """Drop a finished job's row. Safe to call for a job never added."""
        row = self._rows.pop(getattr(job, "job_id", job), None)
        if row is None:
            return
        self._col.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._refresh_empty()
        if not self._rows:
            self._timer.stop()

    def clear(self) -> None:
        for job_id in list(self._rows):
            self.remove(job_id)

    @property
    def count(self) -> int:
        return len(self._rows)

    # -- internals ---------------------------------------------------------
    def _refresh_empty(self) -> None:
        self._empty.setVisible(not self._rows)

    def _tick(self) -> None:
        for row in list(self._rows.values()):
            row.tick()
