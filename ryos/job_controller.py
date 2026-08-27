"""UI-independent job lifecycle / pipeline sequencing for RYOS.

`JobController` owns the job allocation, step-completion, and pipeline-advance
logic that used to live on the `RYOSApp` god class. It knows nothing about
Tkinter: it reaches the UI only through callbacks injected at construction, so
the lifecycle rules can be unit-tested without a display.

See docs/adr/0001-decompose-job-lifecycle.md for the rationale and remaining
increment (running-row teardown).
"""

from __future__ import annotations

import queue
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .db import TRIGGER_WITH
from .interpreter import build_command, resolve_interpreter
from .jobs import Job
from .logger import get_logger
from .runner import decode_output_item

if TYPE_CHECKING:
    from .db import ScriptDB
    from .jobs import JobRegistry

_log = get_logger("job_controller")


def _format_elapsed_secs(secs: float) -> str:
    """Human-readable elapsed label, matching the original app formatting."""
    return f"{int(secs // 60)} m {secs % 60:.0f} s" if secs >= 60 else f"{secs:.1f} s"


def _tag_lines(text: str, label: str) -> str:
    """Prefix each non-empty line with a short step label, for concurrent-group output."""
    tag = f"[{label[:12]}] "
    return "".join(tag + line if line.strip() else line for line in text.splitlines(keepends=True))


class JobController:
    """Drives job allocation, pipeline stepping, and per-job completion.

    The UI injects callbacks; the controller decides *when* to start a job,
    advance a pipeline, finish a job, set the status line, emit output, or
    notify. Widget construction and teardown stay in the app, behind
    ``on_started`` / ``on_finish`` / ``on_rename``.
    """

    def __init__(
        self,
        registry: "JobRegistry",
        output_queue: "queue.Queue",
        db: "ScriptDB",
        *,
        on_output: Callable[[str, str, str | None], None],
        on_status: Callable[[str], None],
        on_notify: Callable[[str, str], None],
        on_started: Callable[[Job], None],
        on_finish: Callable[[Job], None],
        on_rename: Callable[[Job], None],
        launch: Callable[[Job, list, str, int, object], None],
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._registry = registry
        self._queue = output_queue
        self._db = db                    # persists per-step run status
        self._on_output = on_output      # (tab_key, text, tag) -> None
        self._on_status = on_status      # (text) -> None
        self._on_notify = on_notify      # (title, body) -> None; app gates on the setting
        self._on_started = on_started    # (job) -> None; app builds tab + elapsed ticker
        self._on_finish = on_finish      # (job) -> None; widget teardown stays in the app
        self._on_rename = on_rename      # (job) -> None; running-row label refresh
        self._launch = launch            # (job, cmd, name, script_id, step_token=None) -> None
        self._now = now

    def at_capacity(self, max_jobs: int) -> bool:
        """True when a positive cap is set and the registry is already that full."""
        return max_jobs > 0 and len(self._registry) >= max_jobs

    def new_job(
        self,
        kind: str,
        script_id,
        pipeline_id,
        name: str,
        group: str,
        pipeline_name: str = "",
        pipeline_queue=None,
        pipeline_total: int = 0,
    ) -> Job:
        """Allocate, construct, and register a job; fire on_started; return it."""
        job_id = self._registry.new_id()
        tab_key = f"job:{job_id}"
        job = Job(
            job_id, kind, script_id, pipeline_id, name, tab_key, group,
            pipeline_name=pipeline_name,
            pipeline_queue=pipeline_queue if pipeline_queue is not None else [],
            pipeline_total=pipeline_total,
        )
        self._registry.add(job)
        self._on_started(job)
        return job

    def pump(self) -> None:
        """Drain all pending output-queue items on the UI thread.

        For each item: append its text to the right tab, persist a finished
        step's run status, and dispatch completion. The caller owns the repeat
        scheduling (``after(80, ...)``); the worker never touches a widget — it
        only feeds this queue.
        """
        try:
            while True:
                item = self._queue.get_nowait()
                job = self._registry.get(item[1])
                act = decode_output_item(item)
                if act.text is not None and job:
                    text = act.text
                    # Gate on the group's fixed launch size (not the live
                    # count), so the prefix doesn't vanish mid-group as
                    # siblings finish one by one.
                    if job.group_size > 1 and act.token in job.group_labels:
                        text = _tag_lines(text, job.group_labels[act.token])
                    self._on_output(job.tab_key, text, act.tag)
                if act.status is not None:
                    # A completion item always carries its script id (protocol).
                    assert act.sid is not None
                    self._db.mark_run_status(act.sid, act.status)
                    if job:
                        self.handle_step_done(job, act.sid, act.status, act.token)
        except queue.Empty:
            pass

    def run_next_pipeline_step(self, job: Job) -> None:
        """Pop and launch the next step, or the whole concurrent group it leads.

        Group detection: the first popped step (the leader) starts unconditionally
        — its own trigger_mode is never consulted, which is what makes a stray
        'with' accidentally left on a first step harmless at runtime — then
        subsequent queue items are absorbed into the same group while their
        trigger_mode is TRIGGER_WITH.
        """
        if job.stopped or not job.pipeline_queue:
            return

        batch = [job.pipeline_queue.pop(0)]
        while job.pipeline_queue and job.pipeline_queue[0][7] == TRIGGER_WITH:
            batch.append(job.pipeline_queue.pop(0))

        # Reserve every token before launching any member, so no member can
        # report done into a group that does not yet know about its siblings.
        job.group_pending = set()
        job.group_failed = False
        job.group_failed_at = None
        job.group_labels = {}
        job.group_size = len(batch)
        prepared = []
        for step in batch:
            job.pipeline_step_idx += 1
            token = job.pipeline_step_idx
            job.group_pending.add(token)
            job.group_labels[token] = step[2]
            prepared.append((token, step))

        first, last = prepared[0][0], prepared[-1][0]
        total = job.pipeline_total
        if job.group_size == 1:
            # byte-identical to the pre-concurrent-group behavior
            name = prepared[0][1][2]
            header = f"{'─' * 40}\nStep {first}/{total}:  {name}\n{'─' * 40}\n"
            status_line = f"Pipeline step {first}/{total}: {name}"
            job.name = f"⚡ {job.pipeline_name}  —  Step {first}/{total}: {name}"
        else:
            names = ", ".join(job.group_labels[t] for t, _ in prepared)
            header = (f"{'─' * 40}\nSteps {first}-{last}/{total} (concurrent):  "
                      f"{names}\n{'─' * 40}\n")
            status_line = f"Pipeline steps {first}-{last}/{total}: {job.group_size} running"
            job.name = f"⚡ {job.pipeline_name}  —  Steps {first}-{last}/{total}"
        self._on_output(job.tab_key, header, "info")
        self._on_status(status_line)
        self._on_rename(job)

        for token, (step_id, sid, name, path, params, interp, override, _mode) in prepared:
            if override is not None:
                params = override
            if not Path(path).exists():
                self._queue.put(("stderr", job.job_id, f"[ERROR] File not found: {path}\n", token))
                self._queue.put(("done", job.job_id, sid, "error", "", token))
                continue                      # NOT `return` — siblings must still launch
            try:
                cmd = build_command(path, params, resolve_interpreter(path, interp))
            except ValueError as e:
                self._queue.put(("stderr", job.job_id, f"[ERROR] Parameter error: {e}\n", token))
                self._queue.put(("done", job.job_id, sid, "error", "", token))
                continue
            self._launch(job, cmd, name, sid, token)

    def handle_step_done(self, job: Job, sid: int, status: str, token=None) -> None:
        """Dispatch a finished step: advance the pipeline, or finish the job."""
        secs = (self._now() - job.start_time).total_seconds()
        elapsed = _format_elapsed_secs(secs)

        if job.kind == "pipeline":
            if job.group_pending:
                if token not in job.group_pending:
                    # Defensive: an untagged/unrecognized item still has to make
                    # forward progress, or group_pending never empties and the
                    # pipeline hangs forever with no diagnostics.
                    _log.warning(
                        "Untagged step-done for pipeline job %s; guessing at a pending step",
                        job.job_id,
                    )
                    token = job.group_pending.pop()
                else:
                    job.group_pending.discard(token)
                if status != "ok" and not job.group_failed:
                    job.group_failed = True
                    job.group_failed_at = token
                if job.group_pending:
                    # A sibling is still running; wait for it regardless of whether
                    # this one failed — we don't kill in-flight siblings.
                    return
                status = "error" if job.group_failed else "ok"

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
                failed_at = job.group_failed_at or job.pipeline_step_idx
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
