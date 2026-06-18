"""UI-independent job lifecycle / pipeline sequencing for RYOS.

`JobController` owns the step-completion and pipeline-advance logic that used to
live on the `RYOSApp` god class. It knows nothing about Tkinter: it reaches the
UI only through callbacks injected at construction, so the sequencing and
completion rules can be unit-tested without a display.

See docs/adr/0001-decompose-job-lifecycle.md for the rationale and the planned
later increments (drain loop, job allocation).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .interpreter import build_command, resolve_interpreter

if TYPE_CHECKING:
    import queue

    from .jobs import Job, JobRegistry


def _format_elapsed_secs(secs: float) -> str:
    """Human-readable elapsed label, matching the original app formatting."""
    return f"{int(secs // 60)} m {secs % 60:.0f} s" if secs >= 60 else f"{secs:.1f} s"


class JobController:
    """Drives pipeline stepping and per-job completion.

    The UI injects callbacks; the controller decides *when* to advance a
    pipeline, finish a job, set the status line, emit output, or notify. Widget
    construction and teardown stay in the app, behind ``on_finish`` /
    ``on_rename``.
    """

    def __init__(
        self,
        registry: "JobRegistry",
        output_queue: "queue.Queue",
        *,
        on_output: Callable[[str, str, str | None], None],
        on_status: Callable[[str], None],
        on_notify: Callable[[str, str], None],
        on_finish: Callable[["Job"], None],
        on_rename: Callable[["Job"], None],
        launch: Callable[["Job", list, str, int], None],
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._registry = registry
        self._queue = output_queue
        self._on_output = on_output      # (tab_key, text, tag) -> None
        self._on_status = on_status      # (text) -> None
        self._on_notify = on_notify      # (title, body) -> None; app gates on the setting
        self._on_finish = on_finish      # (job) -> None; widget teardown stays in the app
        self._on_rename = on_rename      # (job) -> None; running-row label refresh
        self._launch = launch            # (job, cmd, name, script_id) -> None
        self._now = now

    def run_next_pipeline_step(self, job: "Job") -> None:
        """Pop and launch the next pipeline step, or no-op if stopped/empty."""
        if job.stopped or not job.pipeline_queue:
            return
        step_id, sid, name, path, params, interp, params_override = job.pipeline_queue.pop(0)
        if params_override is not None:
            params = params_override
        job.pipeline_step_idx += 1
        n, total = job.pipeline_step_idx, job.pipeline_total
        self._on_output(
            job.tab_key,
            f"{'─' * 40}\nStep {n}/{total}:  {name}\n{'─' * 40}\n",
            "info",
        )
        self._on_status(f"Pipeline step {n}/{total}: {name}")
        job.name = f"⚡ {job.pipeline_name}  —  Step {n}/{total}: {name}"
        self._on_rename(job)
        if not Path(path).exists():
            self._queue.put(("stderr", job.job_id, f"[ERROR] File not found: {path}\n"))
            self._queue.put(("done", job.job_id, sid, "error", ""))
            return
        final_interp = resolve_interpreter(path, interp)
        try:
            cmd = build_command(path, params, final_interp)
        except ValueError as e:
            self._queue.put(("stderr", job.job_id, f"[ERROR] Parameter error: {e}\n"))
            self._queue.put(("done", job.job_id, sid, "error", ""))
            return
        self._launch(job, cmd, name, sid)

    def handle_step_done(self, job: "Job", sid: int, status: str) -> None:
        """Dispatch a finished step: advance the pipeline, or finish the job."""
        secs = (self._now() - job.start_time).total_seconds()
        elapsed = _format_elapsed_secs(secs)

        if job.kind == "pipeline":
            if status == "ok" and job.pipeline_queue:
                self.run_next_pipeline_step(job)
                return
            elif status == "ok":
                self._on_output(
                    job.tab_key,
                    f"\n{'━' * 60}\n"
                    f"✓  Pipeline complete  ·  {self._now().strftime('%H:%M:%S')}\n"
                    f"{'━' * 60}\n",
                    "ok",
                )
                self._on_status("Pipeline complete.")
                total = job.pipeline_total
                self._on_finish(job)
                self._on_notify(
                    "RYOS — Pipeline passed",
                    f"✓  {job.pipeline_name}  ·  {total} step{'s' if total != 1 else ''}  ·  {elapsed}",
                )
            else:
                job.pipeline_queue.clear()
                self._on_output(job.tab_key, "\n[Pipeline stopped — step failed]\n", "stderr")
                self._on_status("Pipeline stopped (step failed).")
                failed_at = job.pipeline_step_idx
                total = job.pipeline_total
                self._on_finish(job)
                self._on_notify(
                    "RYOS — Pipeline failed",
                    f"✗  {job.pipeline_name}  ·  failed at step {failed_at}/{total}  ·  {elapsed}",
                )
        else:
            if status == "ok":
                self._on_status("Done.")
                self._on_notify("RYOS — Script passed", f"✓  {job.name}  ·  {elapsed}")
            else:
                self._on_status("Failed.")
                self._on_notify("RYOS — Script failed", f"✗  {job.name}  ·  {elapsed}")
            self._on_finish(job)
