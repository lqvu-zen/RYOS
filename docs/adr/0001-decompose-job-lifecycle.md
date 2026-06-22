# ADR-0001: Decompose the job lifecycle out of `RYOSApp`

**Status:** Accepted — increments 1-2 implemented (`JobController` owns step completion, pipeline stepping, and the drain loop)
**Date:** 2026-06-18
**Deciders:** RYOS maintainer(s) — owner of `ryos/ui/app.py` and the core modules
**Supersedes / relates to:** TECH_DEBT.md item #6 (`RYOSApp` god class), the last open structural item

## Context

`RYOSApp` in `ryos/ui/app.py` is still the project's god class — **2,276 lines, ~90 methods**, owning UI construction, drag-and-drop, tab management, group CRUD, the Quick Run subsystem, output routing, notifications, update checks, **and the job lifecycle**.

The tech-debt remediation has already peeled off the easy, self-contained cores, each now unit-tested without a display:

- `ryos/quickrun.py` — path-containment guard, index entry shape, suggestion ranking, name resolution, input parsing.
- `ryos/jobs.py` — the `Job` state container, `JobRegistry` (storage + id allocation), `format_elapsed`.
- `ryos/runner.py` — `run_subprocess` (the worker thread) and `decode_output_item` / `OutputAction` (the queue protocol decoder).

What remains entangled with the widgets is the **job lifecycle and pipeline sequencing**. These methods on `RYOSApp` each interleave genuine orchestration logic with direct Tk calls:

| Method | Orchestration (UI-free in principle) | Widget coupling (Tk) |
| --- | --- | --- |
| `_new_job` (382) | allocate id via `JobRegistry`, construct `Job`, start elapsed timer | `_get_or_create_tab(...)`, `self.after(...)` |
| `_launch` (1489) | `db.mark_run`, spawn worker thread | — (already clean) |
| `_run_script` (1500) | parallel-job cap, file/param validation, `db.get`, build `Job` | `messagebox`, `status_var`, `_append_output`, `_add_running_row` |
| `_run_next_pipeline_step` (1365) | pop step, build command, advance index, post errors to queue | `_append_output`, `status_var`, `name_var.set` |
| `_drain_output_queue` (2121) | drain queue, `decode_output_item`, `db.mark_run_status`, dispatch | `_append_output`, `self.after(80, ...)` |
| `_handle_step_done` (2137) | pipeline-vs-script branch, sequencing, completion/failure logic, notify | `_append_output`, `status_var`, `_show_notification` |
| `_finish_job` (408) | remove from registry, "no jobs left in group?" check | running-row `destroy()`, placeholder `Label` |

The forces at play:

- **Adding features here is getting slower and riskier** — this is the most-changed module and the lifecycle logic (parallel-job caps, pipeline branching, completion/notify rules) is exactly the kind of logic that benefits from tests, yet it can only be reached today through the widget code.
- **The headless test suite cannot touch any of it.** `tests/test_ryos.py` mocks `tkinter`; it exercises `db`, `interpreter`, `quickrun`, `jobs`, `runner` directly but stops at the lifecycle because the logic and the widget calls share a scope.
- **The seam is real but shallow.** The orchestration interacts with the UI through a small, recurring vocabulary: append text to a tab, set the status line, add/remove a running row, set a tab name, show a notification, schedule a tick. That is a candidate interface, not a tangle.

### Constraints

1. **Standard-library only at runtime** (just `tkinterdnd2`). No new dependencies, no event-bus library.
2. **Must stay testable without a display** — the win is hollow if the extracted code still needs a real `Tk()`.
3. **Behavior-preserving.** No user-visible change to how scripts/pipelines run, notify, or report. Backward compatible.
4. **Incremental, alongside feature work.** No big-bang rewrite or feature freeze — TECH_DEBT.md explicitly mandates the opportunistic, one-seam-at-a-time approach.
5. **Windows-first**, where the app actually ships (frozen `RYOS.exe`), but the core must remain cross-platform like the rest.

## Decision

Introduce a UI-independent **`JobController`** (`ryos/job_controller.py`) that owns the job lifecycle and pipeline sequencing. It holds the `JobRegistry`, the output `queue.Queue`, and a reference to `db`, and it talks to the UI **only through a narrow callback interface** (a small Protocol / set of injected callables, e.g. `on_output(tab_key, text, tag)`, `on_status(text)`, `on_job_started(job)`, `on_job_finished(job)`, `on_notify(title, body)`, `schedule(ms, fn)`).

`RYOSApp` keeps all widget work — it constructs tabs, running rows, the status bar, toasts — but implements those callbacks and delegates the *decisions* (when to advance a pipeline, when a job is done, whether the parallel cap is hit) to the controller. The drain loop's logic moves into `JobController.pump()`; `RYOSApp` keeps only the `after(80, ...)` scheduling and the widget side of each callback.

This is the **observer/callback** option (Option B below), chosen over both leaving it on `RYOSApp` (Option A) and a full event bus (Option C) or MVP framework (Option D).

## Options Considered

### Option A: Status quo — keep extracting pure helpers piecemeal

Continue lifting small pure functions (as already done for `format_elapsed`, `decode_output_item`) but leave the lifecycle methods themselves on `RYOSApp`.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | Lowest — no new module |
| Scalability | Poor — the orchestration stays untestable |
| Team familiarity | Highest — no new pattern |

**Pros:** Zero risk; matches what's been done so far; nothing new to learn.
**Cons:** The genuinely valuable logic (pipeline branching, completion/notify rules, parallel cap) stays welded to the widgets and untestable. The diminishing returns are real — the easy pure helpers are already gone; what's left *is* the entangled part. Item #6 stays open indefinitely.

### Option B: `JobController` with a narrow callback/observer interface (chosen)

A UI-free class owns the lifecycle; the UI injects callbacks and renders.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Cost | Medium — one new module + a callback Protocol |
| Scalability | Good — lifecycle becomes directly testable with fake callbacks |
| Team familiarity | Medium — plain callbacks, no framework |

**Pros:** The orchestration becomes testable by passing recording fakes for the callbacks (no `Tk()` needed) — the same trick already used across the suite. Matches the existing "core knows nothing about Tkinter, dependencies point downward" architecture exactly. Stdlib-only (`typing.Protocol` or just injected callables). Naturally incremental: move one method at a time behind the interface, suite green at each step.
**Cons:** Introduces a callback indirection where today it's a direct method call — a small readability cost. Requires defining and maintaining the callback contract. The drain loop must be split (logic to `pump()`, scheduling stays in the app).

### Option C: Event bus / pub-sub

The worker and controller publish typed events onto a bus; UI components subscribe.

| Dimension | Assessment |
|-----------|------------|
| Complexity | High |
| Cost | High — a bus, event types, subscription lifecycle |
| Scalability | Good in the large, overkill in the small |
| Team familiarity | Low — new mental model |

**Pros:** Maximal decoupling; many independent subscribers; conceptually clean.
**Cons:** Over-engineered for a single-window app with exactly one consumer of these events (the main window). RYOS already *has* a producer/consumer channel — the output `queue.Queue` — so a second bus would be a parallel, partly-redundant mechanism. Harder to follow control flow; more surface to get wrong around teardown. Violates the "no big-bang, no new dependency-shaped abstraction" constraint.

### Option D: Full MVP / MVC split of `RYOSApp`

Restructure the whole class into Model / View / Presenter layers in one effort.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Very high |
| Cost | Very high — touches all ~90 methods |
| Scalability | Excellent long-term |
| Team familiarity | Low |

**Pros:** The "correct" end-state textbook architecture; would make the entire UI testable, not just the lifecycle.
**Cons:** A big-bang rewrite of the most-changed file — directly against constraint #4 and the phased plan. High regression risk in code with no UI-level tests yet. Far more than the one open seam requires. If ever desirable, it should be *approached* incrementally — and Option B is the first increment of exactly that path.

## Trade-off Analysis

The decision turns on three things. **Testability**: A, alone, fails the actual goal — the remaining logic is the part worth testing, and A leaves it untestable. B, C, and D all fix this. **Proportionality**: there is one window and one stream of job events, so C's many-subscribers payoff never materializes, and D's whole-class scope dwarfs the one open item. **Fit with what exists**: B is the same move already made three times (`quickrun`, `jobs`, `runner`) — UI-free core, dependencies pointing downward, tested with mocked Tk — so it adds no new concept and no dependency. B also happens to be the smallest first step of D, so choosing it does not foreclose a fuller split later; it makes it cheaper.

The cost of B is a callback indirection and a contract to maintain. That is a modest, local readability tax in exchange for moving pipeline-sequencing and completion logic into a tested unit. Given the constraints, B is the only option that improves testability *and* respects the stdlib-only, incremental, behavior-preserving boundaries.

## Consequences

**Easier**
- Unit-testing pipeline sequencing, the parallel-job cap, and completion/failure/notify decisions with recording fake callbacks — no display required.
- Reasoning about `RYOSApp`: it shrinks toward "build widgets + render callbacks," and the lifecycle lives in one cohesive, named place.
- Future changes to *how* jobs start, advance, or finish land in one tested module rather than scattered across widget methods.

**Harder**
- Following a single run end-to-end now hops through one callback boundary instead of staying in direct calls — mitigated by keeping the callback set small and explicitly documented.
- The drain loop is split: `JobController.pump()` holds the logic, `RYOSApp` keeps the `after(80, ...)` scheduling. The split point must be drawn carefully so the worker still never touches a widget.

**To revisit**
- The exact callback surface — start minimal (`on_output`, `on_status`, `on_job_started`, `on_job_finished`, `on_notify`, `schedule`) and only widen if a method genuinely needs more.
- Whether `_run_script`'s validation (file exists, param parse, cap) belongs in the controller or stays in the app as pre-flight. Recommendation: validation that produces a `messagebox` stays in the app; the cap check moves to the controller (it's a pure registry-size decision).
- If/when more of `RYOSApp` wants the same treatment (TabBar, drag-and-drop), whether to generalize toward Option D.

## Action Items

1. [ ] Add `ryos/job_controller.py` with a `JobController` holding `JobRegistry`, the output queue, and `db`; define the callback Protocol (or accept callables in `__init__`).
2. [x] Move `_handle_step_done` and `_run_next_pipeline_step` logic into the controller, calling back for output/status/notify. Keep `RYOSApp` thin wrappers initially. *(Done: `ryos/job_controller.py`, callbacks `on_output`/`on_status`/`on_notify`/`on_finish`/`on_rename`/`launch`; 9 unit tests.)*
3. [x] Move the drain *logic* into `JobController.pump()`; leave `after(80, ...)` scheduling in `RYOSApp._drain_output_queue`, which just calls `pump()`. *(Done: `pump()` owns drain + `mark_run_status`; controller now holds the `db` ref; 5 pump tests.)*
4. [ ] Move the parallel-job-cap check and `Job` construction (`_new_job`) into the controller; have the app supply `on_job_started` to build the tab + running row.
5. [ ] Add `tests/` coverage: pipeline advance-on-ok, stop-on-failure, single-script ok/fail, cap enforcement, notify on/off — all via recording fake callbacks, no `Tk()`.
6. [ ] Run the gate at each increment: `uvx ruff check .` and `uv run --no-project --with pytest pytest -q` green; then a `run-ryos` driver smoke pass (run a script, run a pipeline, stop a job) since the widget paths stay headless-untested.
7. [ ] Update `docs/ARCHITECTURE.md` (add `job_controller ★` to the core subgraph) and close TECH_DEBT.md item #6.

## Notes

- This ADR is behavior-preserving by design; any user-visible change is out of scope and would warrant its own decision.
- The `runner` worker boundary is unchanged: the worker thread still communicates only via the output `queue.Queue`. This ADR concerns the *consumer* side of that queue and the lifecycle around it, not the producer.
