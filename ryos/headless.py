"""Running scripts and pipelines with no window: the engine behind the
command line (and, later, the MCP server).

It hosts jobs through the same ``JobHost`` as the window, so a run here is
the same run -- same planning and refusals, same pipeline policies and
retries, same launcher release, same history row (marked ``cli`` or
``agent``). What it adds is what a caller without a window needs:

* finding a script or pipeline by what a person would type (`resolve`);
* each run's output, kept in a bounded buffer (`Run`);
* waiting for a run, with a timeout that stops it.

**Threading.** The controller is not thread-safe: everything that touches it
-- starting, stopping, pumping, a launcher's release -- happens on whichever
thread calls `HeadlessRunner` methods, one at a time. `wait` pumps on that
thread; `call_later` callbacks run inside `step`, never on a timer thread.
"""

from __future__ import annotations

import heapq
import itertools
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .db import SOURCE_CLI, ScriptDB
from .jobhost import PUMP_MS, JobHost
from .jobs import RUNNING, Job, own_runs

SCRIPT = "script"
PIPELINE = "pipeline"

#: A run stopped because it went past its timeout. Recorded in history as
#: stopped; reported to the caller as this.
TIMEOUT = "timeout"

#: Lines of output a run keeps; older lines are dropped (and counted).
MAX_LINES = 2000


class HeadlessError(Exception):
    """A request RYOS itself refused: not found, ambiguous, bad preset,
    already running, or a launch the planner turned down."""


@dataclass(frozen=True)
class Target:
    """A script or pipeline, found."""

    kind: str
    item_id: int
    name: str
    group: str

    @property
    def ref(self) -> str:
        """How to name it unambiguously: ``group/name``."""
        return f"{self.group}/{self.name}" if self.group else self.name


def _targets(db: ScriptDB, kind: str) -> list[Target]:
    if kind == SCRIPT:
        return [Target(SCRIPT, row[0], row[1], row[8] or "") for row in db.list_all()]
    groups = list(db.list_groups()) + [""]
    return [Target(PIPELINE, pid, name, group)
            for group in groups for pid, name, *_ in db.list_pipelines(group)]


def resolve(db: ScriptDB, kind: str, ref: str, allowed: set[int] | None = None) -> Target:
    """The script or pipeline ``ref`` names.

    ``#12`` is an id; otherwise ``ref`` matches an item's name, or its
    ``group/name``. Names repeat across groups, so a bare name that matches
    more than one is refused with the ones it could mean.

    ``allowed`` limits the search to those ids -- for an agent, the items
    made available to it. Anything else is not there at all: not found, and
    never named among the candidates of an ambiguous name.
    """
    ref = ref.strip()
    items = _targets(db, kind)
    if allowed is not None:
        items = [t for t in items if t.item_id in allowed]
    if ref.startswith("#") and ref[1:].isdigit():
        found = [t for t in items if t.item_id == int(ref[1:])]
    else:
        found = [t for t in items if ref in (t.name, t.ref)]
    if not found:
        where = " is available to agents" if allowed is not None else ""
        raise HeadlessError(f"No {kind} named {ref!r}{where}.")
    if len(found) > 1:
        names = ", ".join(f"{t.ref!r} (#{t.item_id})" for t in found)
        raise HeadlessError(f"{ref!r} could be any of {len(found)} {kind}s: {names}. "
                            "Name it as group/name, or by #id.")
    return found[0]


@dataclass
class Run:
    """One run started here: its state, and the output it has kept."""

    job_id: int
    target: Target
    started_at: datetime
    finished_at: datetime | None = None
    status: str = RUNNING
    exit_code: int | None = None
    timed_out: bool = False
    lines: deque = field(default_factory=lambda: deque(maxlen=MAX_LINES))
    #: Every line ever received; ``total - len(lines)`` were dropped.
    total: int = 0
    _partial: str = ""

    @property
    def done(self) -> bool:
        return self.status != RUNNING

    @property
    def dropped(self) -> int:
        return self.total - len(self.lines)

    def _add(self, text: str) -> None:
        text = self._partial + text
        parts = text.split("\n")
        self._partial = parts.pop()
        for line in parts:
            self.lines.append(line.rstrip("\r"))
            self.total += 1

    def _close(self) -> None:
        if self._partial:
            self._add("\n")

    def tail(self, n: int) -> list[str]:
        return list(self.lines)[-n:] if n > 0 else []

    def page(self, offset: int, limit: int) -> tuple[list[str], int]:
        """Lines from absolute line ``offset`` (0-based), at most ``limit``,
        and the offset to ask for next. Lines already dropped are skipped."""
        start = max(offset, self.dropped)
        kept = list(self.lines)[start - self.dropped:start - self.dropped + max(0, limit)]
        return kept, start + len(kept)


class HeadlessRunner:
    """Start, stop and wait for runs, with no window.

    ``on_output(run, text, tag)`` sees output as it arrives (the command line
    streams it); it is called on the pumping thread.
    """

    def __init__(self, db: ScriptDB, settings: dict | None = None, *,
                 trigger: str = SOURCE_CLI,
                 on_output: Callable[[Run, str, str | None], None] | None = None,
                 on_finished: Callable[[Run], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.db = db
        self._trigger = trigger
        self._on_output_cb = on_output
        self._on_finished_cb = on_finished
        self._sleep = sleep
        self._clock = clock
        self._later: list = []                  # heap of (due, seq, fn)
        self._seq = itertools.count()
        self.runs: dict[int, Run] = {}
        self._by_tab: dict[str, Run] = {}
        # No toasts (nobody watches one for a run started from a terminal or
        # an agent), so on_notify is left out.
        self.host = JobHost(db, settings, call_later=self._call_later,
                            on_output=self._output, on_finished=self._finished)

    # -- the pump ------------------------------------------------------------
    def _call_later(self, seconds: float, fn: Callable[[], object]) -> None:
        heapq.heappush(self._later, (self._clock() + seconds, next(self._seq), fn))

    def step(self) -> None:
        """Drain output, then run whatever ``call_later`` has made due."""
        self.host.pump()
        now = self._clock()
        while self._later and self._later[0][0] <= now:
            _due, _seq, fn = heapq.heappop(self._later)
            fn()

    def _output(self, tab_key: str, text: str, tag=None, _step=None) -> None:
        run = self._by_tab.get(tab_key)
        if run is None:
            return
        run._add(text)
        if self._on_output_cb is not None:
            self._on_output_cb(run, text, tag)

    def _finished(self, job: Job) -> None:
        run = self.runs.get(job.job_id)
        if run is None:
            return
        run._close()
        run.finished_at = datetime.now()
        run.exit_code = job.exit_code
        outcome = job.outcome or "error"
        # A run that finished OK just as its time ran out still passed.
        run.status = TIMEOUT if run.timed_out and outcome != "ok" else outcome
        if self._on_finished_cb is not None:
            self._on_finished_cb(run)

    # -- starting and stopping -----------------------------------------------
    def _refuse_if_running(self, target: Target) -> None:
        if (target.kind, target.item_id) in own_runs(self.host.registry.all()):
            raise HeadlessError(f"{target.ref!r} is already running.")

    def _begin(self, job: Job | None, target: Target, refusal: list) -> Run:
        if job is None:
            r = refusal[0] if refusal else None
            raise HeadlessError(f"{r.title}: {r.message}" if r else
                                f"{target.ref!r} could not start.")
        run = Run(job.job_id, target, started_at=job.start_time)
        self.runs[job.job_id] = run
        self._by_tab[job.tab_key] = run
        return run

    def start_script(self, target: Target, *, params: str | None = None,
                     preset: str | None = None) -> Run:
        """Start a script with its own parameters, ``params`` instead, or a
        saved preset's (by label)."""
        if params is not None and preset is not None:
            raise HeadlessError("Give parameters or a preset, not both.")
        self._refuse_if_running(target)
        rec = self.db.get(target.item_id)
        if not rec:
            raise HeadlessError(f"{target.ref!r} is gone.")
        _id, name, path, own_params, interp = rec[:5]
        if preset is not None:
            presets = {label: p for _pid, label, p in self.db.list_param_presets(target.item_id)}
            if preset not in presets:
                have = ", ".join(repr(k) for k in presets) or "none"
                raise HeadlessError(f"{target.ref!r} has no preset {preset!r} (it has: {have}).")
            params = presets[preset]
        if params is None:
            params = own_params or ""
        refusal: list = []
        job = self.host.run_script(
            target.item_id, name, path, params,
            interp or "", trigger=self._trigger, active_group=target.group,
            on_refusal=refusal.append)
        return self._begin(job, target, refusal)

    def start_pipeline(self, target: Target) -> Run:
        self._refuse_if_running(target)
        refusal: list = []
        job = self.host.run_pipeline(
            target.item_id, target.name, trigger=self._trigger,
            candidate_groups=[target.group], on_refusal=refusal.append)
        return self._begin(job, target, refusal)

    def stop(self, run: Run) -> None:
        job = self.host.registry.get(run.job_id)
        if job is not None:
            self.host.stop_job(job)

    def stop_all(self) -> None:
        self.host.stop_all()

    def forget(self, run: Run) -> None:
        """Drop a finished run's record and output (a long-lived host keeps
        only so many)."""
        if run.done:
            self.runs.pop(run.job_id, None)
            self._by_tab = {k: r for k, r in self._by_tab.items() if r is not run}

    # -- waiting -------------------------------------------------------------
    def wait(self, run: Run, timeout: float | None = None) -> Run:
        """Pump until ``run`` finishes. Past ``timeout`` seconds it is stopped,
        and reported as TIMEOUT once it has."""
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            self.step()
            if run.done:
                return run
            if deadline is not None and not run.timed_out and self._clock() >= deadline:
                run.timed_out = True
                self.stop(run)
            self._sleep(PUMP_MS / 1000)
