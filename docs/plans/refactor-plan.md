# RYOS Refactor — Summary & Plan

_Companion to `docs/tech-debt-2026-06-24.md`. Last updated 2026-06-24._

## Update — 2026-06-25: Theme Factory landed (plan additions)

The theming feature (`docs/plans/theme-factory.md`) shipped since this plan was
written: it added `ryos/themes.py` (634 lines, pure, well-tested), added
`ryos/ui/theme_editor.py` (248 lines, widget UI), and grew `dialogs.py`
1,219 → 1,425 lines. Tests are now 288. New refactor items:

1. **`ryos/themes.py` → mypy scope** *(Priority 20 · effort trivial).* A large,
   central, **mypy-clean** pure module that is **not** in the `[tool.mypy]`
   `files` list — a one-line gap against this plan's "fold clean modules into
   mypy" rule. Add it now.
2. **`ryos/ui/theme_editor.py` — untested widget file** *(deferred tail).* Push
   any remaining pure preview/validation logic into `themes.py`
   (`validate_seed` / `contrast_warnings` already live there) and lean on those
   tests; the dialog shell stays UI-bound.
3. **`dialogs.py` is getting worse** *(Priority 12, rising).* The Appearance-tab
   theme selector + editor entry were bolted on (+206 lines) rather than
   extracted — exactly the tail this plan warned about. The **next** touch of
   `dialogs.py` should extract the Appearance-tab logic, not add to it.
4. **`gui-smoke`: add a theme-switch scenario.** Live re-theming now runs
   `apply_theme()` → `_rebuild_ui()` across seven presets + custom themes — a
   full UI teardown/rebuild path with no live test. Switch theme in the smoke and
   assert the app survives and cards still render.

> **Active incident — mount corruption.** At this review the working tree had
> **four committed files truncated** by the `D:\Projects\RYOS` mount
> (`settings.py`, `themes.py`, `dialogs.py`, `tests/test_ryos.py` — all fail to
> parse; the HEAD versions are intact). Recover with
> `git restore <files>` (or `git checkout -- <files>`). The recurring corruption
> is no longer hypothetical — migrating to a non-mounted local clone is now the
> top operational priority.

## What's done

The job lifecycle and a layer of pure UI logic have been pulled out of the
`RYOSApp` god class into UI-free, unit-tested modules, each reaching the window
only through injected callbacks or as pure functions.

| Module | Owns | Tests |
| --- | --- | --- |
| `ryos/job_controller.py` | job allocation, capacity, pipeline stepping, completion, output drain | 18 |
| `ryos/search.py` | query normalization, match predicate, "found in other groups" hint decision | 11 |
| `ryos/dragdrop.py` | drag insertion-index + rectangle hit-test geometry | 10 |
| `ryos/grouping.py` | script→group bucketing for the "All" view | 4 |
| `ryos/screens.py` | window-geometry math (`relocate_geometry`, `geometry_origin`, `center_in_work_area`) | tested |

Alongside: `_refresh_cards` re-split 219 → 45 lines (9 sub-builders); broad
`except` guards narrowed 12 → 8; `mypy` scope grown 9 → 17 files; tests
206 → 237; CI runs `test` + `gui-smoke` (real Tk under Xvfb) + `typecheck`.

**Status:** pure-logic extraction is effectively complete. `app.py` is still
~2,560 lines / 115 methods — the remaining size is genuinely stateful,
widget-bound code.

## What's left

### 1. `SearchController` — the main remaining structural step
The search feature's *state* still lives on `RYOSApp`: `_search_var`,
`_search_ph` (placeholder flag), `_search_entry`, `_search_clear_btn`,
`_search_hint`, `_search_hint_dismissed`, and the methods `_clear_search`,
`_apply_search_filter`, `_update_search_hint`, `_dismiss_search_hint`,
`_update_section_visibility`. The pure decisions already live in `search.py`;
what remains is the orchestration glue.

**Approach** (mirror the `JobController` pattern): a `SearchController` holding
the query/placeholder/dismissed state and the `search.py` helpers, talking to
the window through injected callbacks — e.g. `filter_cards(query)`,
`set_clear_visible(bool)`, `render_hint(model)`, `set_section_visibility(...)`,
`switch_group(name)`. `RYOSApp` keeps the widgets (entry, clear button, hint
frame, section headers) and implements the callbacks; the controller decides.

**Why it's deferred, not done now:** unlike the pure helpers, this is stateful
and widget-bound — it can't be fully unit-tested without a display, the edit
touches a large span of the corruption-prone `app.py`, and the payoff is
organisational rather than a new test surface. It deserves its own focused pass.

**Validation:** lean on the `gui-smoke` CI job — add a scenario that types into
the search box and asserts cards filter (extends the existing card-rendering
check). Keep `search.py` as the tested decision core.

### 2. Deferred tails (do opportunistically)
- **`dialogs.py` (1,219 lines, untested):** extract validation/mapping cores
  when next touched; don't rewrite wholesale.
- **`mypy` into `app.py` / `dialogs.py` / `cards.py`:** fold each in *as* it is
  refactored (Tk's dynamic API needs `# type: ignore` otherwise — low payoff up
  front).
- **Deepen `gui-smoke`:** add pipeline-run, group-switch, and (if feasible)
  drag-reorder scenarios — these widget paths have no live coverage today.

## Suggested order
1. Get the current stack committed and CI green (done incrementally).
2. `SearchController` as a standalone effort, with a search scenario added to
   `gui-smoke` for validation.
3. Tails (2) folded in as those files are next touched — not as a dedicated push.

## Working notes
- The `D:\Projects\RYOS` mount corrupted files on most writes this session (NUL
  bytes, truncation) and repeatedly wedged `.git/index` / left a stale
  `.git/next-index-8.lock`. A `git fsck` + clearing stale `.git/*.lock`, or
  working from a non-mounted local clone, would de-risk all further work. The
  `TestSourceIntegrity` guard catches the corruption symptom in CI but does not
  prevent it.
- Each refactor step held the invariant: `ruff` + `mypy` + the unit suite green,
  whole-tree integrity clean. Keep that gate per increment.
