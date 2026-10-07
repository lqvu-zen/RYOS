"""What an AI agent may do with RYOS, as plain methods: the tools the MCP
server (``ryos/mcpserver.py``) publishes, without the MCP SDK.

The rules an agent meets are all here, so they are tested without a client:

* **Only what was made available.** An agent sees and runs only scripts and
  pipelines whose owner ticked "Available to agents"; everything else is not
  there at all -- not found, never named. The flag is read on every call, so
  unticking takes effect at once.
* **A preset, not free text.** A script runs with its own parameters or a
  saved preset, picked by label. Free text from an agent into a script that
  hands it to a shell is how an injected prompt would get a foothold.
* **Output in pages.** A run's output is read a page at a time, each line
  capped, so a chatty script cannot flood the agent's context.

**Threading.** The MCP SDK calls each tool on a worker thread of its own.
The job engine takes one caller at a time, so every call into it holds one
lock, and a pump thread of this object's own drives it in between.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .db import SOURCE_AGENT, ScriptDB
from .headless import (PIPELINE, SCRIPT, HeadlessError, HeadlessRunner, Run, Target,
                       resolve)
from .jobhost import PUMP_MS

#: Most lines one ``get_run`` returns, and the longest line it returns whole.
MAX_PAGE = 500
MAX_LINE = 2000
#: Longest ``get_run`` will wait for news, so a call never hangs a client.
MAX_WAIT = 30.0
#: Finished runs kept for ``get_run``; older ones are forgotten.
KEEP_RUNS = 100


class AgentError(Exception):
    """A request refused, in words meant for the agent."""


def _clip(line: str) -> str:
    return line if len(line) <= MAX_LINE else line[:MAX_LINE] + " …[line cut]"


class AgentTools:
    """The agent's tools over one database. ``close()`` when done."""

    def __init__(self, db: ScriptDB, settings: dict | None = None, *,
                 notify_window: Callable[[], object] = lambda: None,
                 pump: bool = True) -> None:
        self.db = db
        self._notify_window = notify_window
        self._lock = threading.RLock()
        self._finished_since_notify = False
        self._runner = HeadlessRunner(db, settings, trigger=SOURCE_AGENT,
                                      on_finished=self._on_finished)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if pump:
            self._thread = threading.Thread(target=self._pump, name="ryos-agent-pump",
                                            daemon=True)
            self._thread.start()

    # -- the pump ------------------------------------------------------------
    def _pump(self) -> None:
        while not self._stop.is_set():
            self.step()
            self._stop.wait(PUMP_MS / 1000)

    def step(self) -> None:
        """One turn of the engine; then, outside the lock, tell a running
        window if a run finished (a socket call has no business holding it)."""
        with self._lock:
            self._runner.step()
            tell, self._finished_since_notify = self._finished_since_notify, False
        if tell:
            self._notify_window()

    def _on_finished(self, _run: Run) -> None:
        self._finished_since_notify = True

    def close(self) -> None:
        """Stop the pump and whatever is still running."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._lock:
            self._runner.stop_all()

    # -- what is available ---------------------------------------------------
    def _allowed(self, kind: str) -> set[int]:
        return self.db.agent_exposed_ids(kind)

    def _find(self, kind: str, ref: str) -> Target:
        try:
            return resolve(self.db, kind, ref, allowed=self._allowed(kind))
        except HeadlessError as e:
            raise AgentError(str(e)) from None

    def list_scripts(self) -> list[dict]:
        allowed = self._allowed(SCRIPT)
        return [{"ref": Target(SCRIPT, row[0], row[1], row[8] or "").ref,
                 "id": row[0], "name": row[1], "group": row[8] or "",
                 "presets": [label for _pid, label, _p in self.db.list_param_presets(row[0])]}
                for row in self.db.list_all() if row[0] in allowed]

    def list_pipelines(self) -> list[dict]:
        allowed = self._allowed(PIPELINE)
        found = []
        for group in [*self.db.list_groups(), ""]:
            for pid, name, *_ in self.db.list_pipelines(group):
                if pid in allowed:
                    found.append({"ref": Target(PIPELINE, pid, name, group).ref,
                                  "id": pid, "name": name, "group": group,
                                  "steps": len(self.db.list_pipeline_steps(pid))})
        return found

    # -- running -------------------------------------------------------------
    def _summary(self, run: Run) -> dict:
        finished = run.finished_at
        return {
            "run_id": run.job_id, "kind": run.target.kind, "ref": run.target.ref,
            "status": run.status, "done": run.done, "exit_code": run.exit_code,
            "started_at": run.started_at.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds") if finished else None,
            "duration_seconds": (round((finished - run.started_at).total_seconds(), 3)
                                 if finished else None),
            "total_lines": run.total,
        }

    def _keep_bounded(self) -> None:
        done = [r for r in self._runner.runs.values() if r.done]
        for run in sorted(done, key=lambda r: r.job_id)[:max(0, len(done) - KEEP_RUNS)]:
            self._runner.forget(run)

    def _start(self, start: Callable[[], Run]) -> dict:
        with self._lock:
            try:
                run = start()
            except HeadlessError as e:
                raise AgentError(str(e)) from None
            self._keep_bounded()
            return self._summary(run)

    def run_script(self, script: str, preset: str | None = None) -> dict:
        target = self._find(SCRIPT, script)
        return self._start(lambda: self._runner.start_script(target, preset=preset))

    def run_pipeline(self, pipeline: str) -> dict:
        target = self._find(PIPELINE, pipeline)
        return self._start(lambda: self._runner.start_pipeline(target))

    def _run(self, run_id: int) -> Run:
        run = self._runner.runs.get(run_id)
        if run is None:
            raise AgentError(f"No run {run_id} (it may have finished long ago).")
        return run

    def get_run(self, run_id: int, offset: int = 0, limit: int = 200,
                wait_seconds: float = 0) -> dict:
        """The run's state and a page of its output from line ``offset``.

        With ``wait_seconds``, waits (up to MAX_WAIT) until the run finishes
        or has output past ``offset`` -- one call instead of a polling loop.
        """
        deadline = time.monotonic() + min(max(0.0, wait_seconds), MAX_WAIT)
        while True:
            with self._lock:
                run = self._run(run_id)
                news = run.done or run.total > offset
            if news or time.monotonic() >= deadline:
                break
            time.sleep(PUMP_MS / 1000)
        with self._lock:
            run = self._run(run_id)
            lines, next_offset = run.page(max(0, offset), min(max(0, limit), MAX_PAGE))
            return {**self._summary(run), "lines": [_clip(x) for x in lines],
                    "next_offset": next_offset,
                    "dropped_lines": max(0, run.dropped - max(0, offset))}

    def stop_run(self, run_id: int) -> dict:
        with self._lock:
            run = self._run(run_id)
            self._runner.stop(run)
            return self._summary(run)
