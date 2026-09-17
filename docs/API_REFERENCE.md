# RYOS module reference

Reference for the public surface of RYOS's core (UI-independent) modules — the
parts that are imported, reused, and unit-tested. The Tkinter layer in
`ryos/ui/` is summarised at the end; for its internals read the source
alongside `docs/ARCHITECTURE.md`.

Names prefixed with `_` are internal helpers, included only where they're part
of understanding a module's behaviour.

---

## `ryos.db` — `ScriptDB`

SQLite wrapper for scripts, groups, pipelines, parameter presets, run history
and schedules. All methods open a short-lived connection that commits on
success and rolls back on error.

```python
ScriptDB(db_path: Path = DB_PATH)
```

Opens (creating if needed) the database at `db_path` and runs schema setup:
`_ensure_baseline()` creates/upgrades to the v1 schema, then `_MIGRATIONS` apply
any later versions once each, gated by `PRAGMA user_version`. Pass a temp path
in tests.

`_ensure_baseline()` is **frozen** — new schema goes in `_MIGRATIONS`, keyed by
the version it upgrades to, and each migration re-checks `PRAGMA table_info` so
it is safe to run twice. `SCHEMA_VERSION` is derived from the migration keys
(`max(_BASELINE_VERSION, *_MIGRATIONS)`), currently **7**.

> **Rows are sliced, not unpacked.** `get()` and `list_pipeline_steps()` have
> each grown columns several times, and a fixed-arity unpack at a call site
> broke in a shipped build each time. Read them as `rec[:7]` / `row[:8]`.
> `TestRowWidthsArePinned` in `tests/test_ryos.py` pins the widths as a
> tripwire.

Module-level constants:

| Group | Values |
| --- | --- |
| Schema | `SCHEMA_VERSION`, `_BASELINE_VERSION`, `_MIGRATIONS` |
| Step trigger | `TRIGGER_AFTER`, `TRIGGER_WITH` |
| Step failure policy | `FAIL_STOP`, `FAIL_CONTINUE` |
| Step condition | `WHEN_ALWAYS`, `WHEN_ON_SUCCESS`, `WHEN_ON_FAILURE` |
| Run kind | `RUN_SCRIPT`, `RUN_STEP`, `RUN_PIPELINE` |
| Trigger source | `SOURCE_MANUAL`, `SOURCE_PIPELINE`, `SOURCE_SCHEDULE`, `SOURCE_STARTUP` |

### Scripts

| Method | Returns | Notes |
| --- | --- | --- |
| `add(name, path, params, interpreter, group_name="", temp_param=0, detached=0, env_vars=None, work_dir="")` | `int` (new id) | Appends at the end of the order. |
| `update(script_id, name, path, params, interpreter, group_name="", temp_param=None, detached=None, env_vars=None, work_dir=None)` | — | Any `None` leaves that field untouched. |
| `delete(script_id)` | — | |
| `delete_many(ids: list[int])` | — | |
| `delete_all()` | — | Removes every script. |
| `get(script_id)` | 9-tuple or `None` | `(id, name, path, params, interpreter, group_name, temp_param, env_vars, work_dir)`. Slice it. |
| `list_all()` | list of 12-tuples | `(id, name, path, params, interpreter, created_at, last_run_at, last_run_status, group_name, temp_param, is_favorite, label_color)`, ordered by group then `order_index`. |
| `is_detached(script_id)` | `bool` | True for a launcher script — started and released, not waited on. |
| `mark_run(script_id)` | — | Stamps `last_run_at`, clears status (run started). |
| `mark_run_status(script_id, status)` | — | Records `"ok"` / `"error"` after completion. |
| `set_favorite_script(script_id, fav)` | — | |
| `set_favorite_pipeline(pipeline_id, fav)` | — | |
| `set_script_color(script_id, color)` | — | Card-label highlight key (see `ui.theme.HIGHLIGHT_SEEDS`); `None` clears it. |
| `set_pipeline_color(pipeline_id, color)` | — | As above, for a pipeline card. |

### Ordering and moving

| Method | Returns | Notes |
| --- | --- | --- |
| `swap_order(id_a, id_b)` | — | Swap two scripts' `order_index`. |
| `move_to_top(script_id)` | — | |
| `reorder_script(script_id, group_name, before_id)` | — | Insert before `before_id`; `None` = append. |
| `move_to_group(script_id, new_group)` | — | |

### Groups

| Method | Returns | Notes |
| --- | --- | --- |
| `create_group(name, base_dir="")` | — | |
| `list_groups()` | `list[str]` | Names in sort order. |
| `list_groups_with_meta()` | `list[tuple[str, str]]` | `(name, base_dir)`. |
| `get_group_base_dir(name)` | `str` | `""` if unset. |
| `set_group_base_dir(name, new_dir)` | `tuple[int, list[str]]` | `(remapped_count, untouched_paths)` — rewrites script paths that lived under the old base dir. |
| `rename_group(old, new)` | — | |
| `reorder_groups(names)` | — | Persists tab order. |
| `delete_group(name)` | — | |
| `clone_group(source, new_name)` | `tuple[int, int]` | `(scripts_copied, pipelines_copied)`. |
| `group_match_counts(query)` | `list[tuple[str, int]]` | `(group_name, matches)` for the search bar; ungrouped bucket last, blank query → `[]`. `%` and `_` are escaped to literals. |
| `groups_with_match(query)` | `list[str]` | The names from `group_match_counts`, same order. |

### Pipelines and steps

| Method | Returns | Notes |
| --- | --- | --- |
| `create_pipeline(name, group_name)` | `int` (new id) | |
| `clone_pipeline(pipeline_id)` | `int` (new id) | Copies steps; names it `"… (copy)"`. Raises `ValueError` if not found. |
| `rename_pipeline(pipeline_id, name)` | — | |
| `delete_pipeline(pipeline_id)` | — | Also deletes its steps. |
| `list_pipelines(group_name)` | list of `(id, name, is_favorite, label_color)` | |
| `list_pipeline_steps(pipeline_id)` | list of **14-tuples** | `(step_id, script_id, name, path, params, interpreter, params_override, trigger_mode, env_vars, work_dir, on_failure, retries, run_when, detached)`. `env_vars`, `work_dir` and `detached` come from the **script**, not the step. Slice it (`row[:8]`). |
| `add_pipeline_step(pipeline_id, script_id)` | `int` (step id) | |
| `remove_pipeline_step(step_id)` | — | |
| `reorder_pipeline_steps(pipeline_id, ordered_step_ids)` | — | |
| `update_pipeline_step_params(step_id, params_override)` | — | `None` = use the script's own params. |
| `set_step_trigger_mode(step_id, mode)` | — | `TRIGGER_AFTER` (sequential) or `TRIGGER_WITH` (runs alongside the previous step). |
| `set_step_policy(step_id, *, on_failure=None, retries=None, run_when=None)` | — | Sets any subset; `None` leaves a field alone. Values are **clamped** to the known constants rather than trusted — these columns are `NOT NULL` and drive branching in `handle_step_done`. |
| `reorder_pipeline(pipeline_id, group_name, before_id)` | — | |
| `move_pipeline_to_group(pipeline_id, new_group)` | — | |

### Run history

Added in schema v5. Pipelines have no `last_run_status` column of their own —
a pipeline's outcome exists only here.

| Method | Returns | Notes |
| --- | --- | --- |
| `record_run(kind, *, name, started_at, finished_at=None, script_id=None, pipeline_id=None, status=None, exit_code=None, step_index=None, trigger_source=SOURCE_MANUAL)` | `int` (row id) | `kind` is one of `RUN_SCRIPT` / `RUN_STEP` / `RUN_PIPELINE`. Timestamps accept a `datetime` or an ISO string, and are stored at millisecond resolution so a sub-second run doesn't read as `0.0s`. |
| `list_runs(*, script_id=None, pipeline_id=None, kinds=None, limit=50)` | list of 11-tuples | Most recent first: `(id, script_id, pipeline_id, kind, name, started_at, finished_at, status, exit_code, step_index, trigger_source)`. Neither id given → whole history. |
| `last_pipeline_status()` | `dict` | `{pipeline_id: status}` from each pipeline's most recent run — one query per card refresh, not one per card. |
| `prune_runs(days)` | `int` (rows removed) | `days <= 0` **disables** pruning rather than deleting everything. |
| `clear_runs(*, script_id=None, pipeline_id=None)` | `int` (rows removed) | Neither given → clears all history. |

### Schedules

Added in schema v6. An item carries at most one schedule. All times are naive
local time; the scheduling maths itself lives in `ryos.scheduling`.

| Method | Returns | Notes |
| --- | --- | --- |
| `add_schedule(kind, *, script_id=None, pipeline_id=None, spec_type, spec, catch_up="once", enabled=False, next_run_at=None)` | `int` (new id) | |
| `update_schedule(schedule_id, *, spec_type, spec, catch_up, enabled, next_run_at=None)` | — | |
| `delete_schedule(schedule_id)` | — | |
| `get_schedule(*, script_id=None, pipeline_id=None)` | tuple or `None` | The one schedule for that item. |
| `list_schedules(*, script_id=None, pipeline_id=None, enabled_only=False)` | list of 11-tuples | `(id, kind, script_id, pipeline_id, spec_type, spec, enabled, catch_up, next_run_at, last_run_at, created_at)`. |
| `due_schedules(now)` | list of 11-tuples | Enabled schedules whose `next_run_at` has passed **or is NULL** — a schedule enabled without one would otherwise sit inert forever. |
| `mark_schedule_fired(schedule_id, next_run_at, last_run_at=None)` | — | |
| `set_schedule_enabled(schedule_id, enabled)` | — | |
| `scheduled_ids()` | `tuple[set, set]` | `(script_ids, pipeline_ids)` carrying an enabled schedule — one query for the whole card list. |

### Parameter presets

| Method | Returns | Notes |
| --- | --- | --- |
| `list_param_presets(script_id)` | list of `(id, label, params)` | |
| `replace_param_presets(script_id, presets)` | — | `presets = [(label, params), …]`; replaces all. |

### Export / import

| Method | Returns | Notes |
| --- | --- | --- |
| `export_to_file(path, group_name=None)` | — | JSON of groups/scripts/pipelines/presets; one group or all. Payload version **6**. |
| `import_from_file(path, replace=False)` | `tuple[int, int]` | `(scripts_imported, pipelines_imported)`. `replace=True` overwrites matching groups; merge skips duplicate paths. |

---

## `ryos.interpreter`

Maps file extensions to interpreters and builds subprocess command lists. No UI,
fully tested.

```python
detect_interpreter(path: str) -> str
```
Returns the interpreter command for `path`'s extension (`.py` → a real Python,
`.js` → `node`, `.sh` → `bash`, `.bat`/`.cmd`/`.exe` → `""` run directly, …),
falling back to `"cmd"` for unknown types.

```python
resolve_interpreter(path: str, stored: str) -> str
```
The effective interpreter for a script: uses `stored` when non-empty, else
auto-detects. Also re-detects when `stored` resolves to `RYOS.exe` itself
(a stale entry from a frozen build).

```python
build_command(path: str, params: str, interpreter: str) -> list[str]
```
Assembles the argv list: `shlex`-split interpreter + script path + `shlex`-split
params, using platform-appropriate quoting (`posix=(os.name != "nt")`).

```python
working_dir_for(cmd: list[str]) -> str
```
The directory a command should run in — the parent of the first argument that
names an existing file (i.e. the script), even when interpreter-prefixed.

Internal: `_find_python()` (frozen-build-safe Python lookup),
`_script_tag(path)` (badge label + colour).

---

## `ryos.runner`

Subprocess worker and output-queue protocol. UI-free; the only channel back to
the app is the queue.

```python
run_subprocess(output_queue, job, cmd, name, script_id, log_output=False)
```
Runs on a worker thread. Launches `cmd` (combined stdout/stderr, line-buffered,
no console window on Windows), sets `job.current_process` so the UI can stop it,
streams each line onto `output_queue`, and posts a completion item. Never
raises — launch failures are reported as a `("done", …, "error", …)` queue item.

```python
@dataclass
class OutputAction:
    text: str | None   # text to append (None = nothing)
    tag: str | None    # "info" / "stderr" / "ok" / None (stdout)
    status: str | None # last_run_status to record, or None
    sid: int | None    # script id on completion, else None
    step_done: bool    # whether this item completes a run step

decode_output_item(item: tuple) -> OutputAction
```
Translates one queue item into a flat `OutputAction` so the UI drain loop is a
straight mapping to widget calls. See `docs/ARCHITECTURE.md` for the queue
protocol.

---

## `ryos.jobs`

Job bookkeeping — no Tk, no threads.

```python
class Job:
    Job(job_id, kind, script_id, pipeline_id, name, tab_key, group,
        pipeline_name="", pipeline_queue=None, pipeline_total=0)
```
State for one running script or pipeline: identity, start time, the live
`current_process`, a `stopped` flag, pipeline progress fields
(`pipeline_queue`, `pipeline_step_idx`, `pipeline_total`), and lazy references
to the Tk vars/row that display it.

```python
class JobRegistry:
    new_id() -> int          # next monotonic id (never reused)
    add(job) / remove(job_id) / get(job_id) -> Job | None
    all() -> list[Job]       # snapshot, safe to iterate while mutating
    in_group(group) -> list[Job]
    # also supports len() and bool()
```

```python
format_elapsed(start_time: datetime, now: datetime) -> str
```
The running-row label, e.g. `"14:03:09  ·  1m 05s"` (`"… · 5s"` under a minute).

---

## `ryos.quickrun`

Pure helpers behind the Quick Run bar. An index entry is the tuple
`(rel_str, name_lower, stem_lower, rel_lower)` produced by `build_entry()`.

| Function | Returns | Purpose |
| --- | --- | --- |
| `build_entry(rel_str, filename)` | `Entry` | One index entry, comparison fields pre-lowercased. |
| `should_index(filename, allowed_exts)` | `bool` | Whether a file belongs in the index; empty `allowed_exts` = index everything. |
| `serialize_index(entries)` | `list[str]` | Reduce to relative paths for on-disk caching. |
| `deserialize_index(rels)` | `list[Entry]` | Rebuild entries from cached paths. |
| `rank_suggestions(index, query, max_n)` | `list[str]` | Up to `max_n` matches, best first (5 ranked tiers from exact-stem to path-contains). |
| `resolve(base_dir, query)` | `tuple[str\|None, list[str], str]` | `(abs_path, [], "")` one match · `(None, [rels], "")` ambiguous · `(None, [], error)` none/traversal. Guards against escaping `base_dir`. |
| `parse_input(raw)` | `tuple[str, str, bool]` | `(query, params, params_were_given)` — splits a Quick Run entry. |
| `display_relpath(abs_path, base_dir)` | `str` | Path relative to `base_dir`, else the bare filename. |

---

## `ryos.settings`

Resolves the per-user data directory and creates it on import.

- **Paths** (module constants): `DATA_DIR`, `DB_PATH`, `LOG_DIR`, `LOG_PATH`,
  `QR_INDEX_DIR`. On Windows these live under `%APPDATA%\RYOS`; otherwise
  `~/.local/share/RYOS`.
- `_SETTINGS_DEFAULTS: dict` — every setting and its default (window geometry,
  output limits, Quick Run tuning, logging, theme, `max_parallel_jobs`, …).
- `_load_settings() -> dict` — merges stored `settings.json` over the defaults;
  tolerant of a missing or corrupt file (logs a warning, returns defaults).
- `_save_settings(settings: dict)` — writes pretty-printed JSON; swallows and
  logs write errors.

On import the module also migrates a legacy `scripts.db` / `settings.json`
located next to the executable into the data directory.

---

## `ryos.logger`

| Function | Purpose |
| --- | --- |
| `setup_logging(enabled, level)` | Configure the `ryos` logger; idempotent. Adds a 1 MiB × 3 rotating file handler, or a `NullHandler` when disabled. |
| `get_logger(name)` | Child logger `ryos.<name>`. |
| `log_exception(logger, msg, exc_info=True)` | Error log with traceback. |
| `install_excepthook()` | Route uncaught exceptions through the logger, preserving the prior hook. |

---

## `ryos.notifications`

| Function | Purpose |
| --- | --- |
| `_show_notification(title, body)` | Fire-and-forget Windows 10/11 toast via PowerShell; no-op off Windows. |
| `_parse_version(tag)` | Parse a `vX.Y.Z` tag into a comparable tuple. |
| `_fetch_latest_release()` | `(tag_name, html_url)` of the latest GitHub release, or `None` on any failure. |

---

## `ryos.startup`

Windows "run at login" registry entry under
`HKCU\…\CurrentVersion\Run` (value name `RYOS`). No-ops off Windows.

| Function | Purpose |
| --- | --- |
| `_startup_command()` | The command Windows should run at login (frozen exe, or `uv run` / `pythonw -m ryos` from source). |
| `_startup_enabled()` | Whether the registry value exists. |
| `_set_startup(enable)` | Add or remove the value. |

---

## `ryos.job_controller`

Owns pipeline sequencing. UI-free — it reaches the window only through the
callbacks injected at construction (`on_output`, `on_status`, `on_finish`, …).
See `docs/adr/0001-decompose-job-lifecycle.md`.

Pure step-policy helpers, safe to call on any step row — including a short
row from an older schema, which is why each one has a default. They return
the plain string values of the `ryos.db` policy constants:

| Function | Returns | Purpose |
| --- | --- | --- |
| `step_on_failure(step)` | `str` | `FAIL_STOP` / `FAIL_CONTINUE`, defaulting safely on a short row. |
| `step_retries(step)` | `int` | Retry count, clamped to `>= 0`. |
| `step_run_when(step)` | `str` | `WHEN_ALWAYS` / `WHEN_ON_SUCCESS` / `WHEN_ON_FAILURE`. |
| `should_run_step(step, *, failed, stopping)` | `bool` | Whether this step runs given the pipeline's state so far. **Called lazily, on the head of the queue** — evaluating the whole queue up front drops an `on_failure` cleanup step before the failure it exists to handle. |

`JobController`:

| Method | Returns | Purpose |
| --- | --- | --- |
| `at_capacity(max_jobs)` | `bool` | Whether `max_parallel_jobs` is already used up. |
| `new_job(...)` | `Job` | Allocate and register a job. |
| `pump()` | — | Drain the output queue and dispatch each decoded item. |
| `run_next_pipeline_step(job)` | — | Launch the head of `job.pipeline_queue`, including a whole concurrent group. Skips unrunnable steps one at a time from the head. |
| `handle_step_done(job, sid, status, token=None)` | — | Settle one step: retries, failure policy, group bookkeeping, then advance or finish. Ignores a completion whose token is in `job.released_steps`. |
| `release_launcher_step(job, token, sid)` | `bool` | Settle a launcher step without waiting for its process. **Order matters**: it settles through the normal completion path *first*, then records the token as released — marking first would make `handle_step_done` ignore the very call releasing it. |

---

## `ryos.scheduling`

Pure scheduling maths over **naive local time**; no storage, no Tk. `db.py`
holds the rows, `ui/app.py` ticks it every `SCHEDULE_TICK_MS` (30 s).

Constants: `INTERVAL`, `DAILY`, `WEEKLY`, `SPEC_TYPES`; `CATCH_UP_SKIP`,
`CATCH_UP_ONCE`, `CATCH_UP_ALL`, `CATCH_UP_MODES`; `MAX_CATCH_UP = 20`,
`MIN_INTERVAL_MINUTES = 1`.

| Function | Returns | Purpose |
| --- | --- | --- |
| `parse_time_of_day(value)` | `time \| None` | Tolerant `HH:MM` parse. |
| `normalize_spec(spec_type, spec)` | `dict \| None` | Validate and canonicalise a spec; `None` if unusable. |
| `next_occurrence(spec_type, spec, after)` | `datetime \| None` | The first firing strictly after `after`. |
| `preview(spec_type, spec, after, count=5)` | `list[datetime]` | The next few firings, for the dialog's "runs at" list. |
| `resolve_due(spec_type, spec, next_run_at, now, catch_up)` | `tuple[list, datetime \| None]` | `(firings_to_run_now, new_next_run_at)` — applies the catch-up policy for time the app spent closed, capped at `MAX_CATCH_UP`. |
| `describe_spec(spec_type, spec)` | `str` | Human summary, e.g. `"Every day at 09:00"`. (Named `describe_spec`, not `describe`, so it doesn't collide with `history.describe`.) |

---

## `ryos.history`

Formatting for the run-history view. Rows come from `db.list_runs()`; this
module never touches the database.

| Function | Returns | Purpose |
| --- | --- | --- |
| `parse_stamp(value)` | `datetime \| None` | Tolerant ISO parse. |
| `format_when(started_at)` | `str` | Relative-ish timestamp for the list. |
| `format_duration(started_at, finished_at)` | `str` | e.g. `"1m 05s"`; blank when still running. |
| `format_status(status)` | `str` | Status with its mark (`✓` / `✕` / `·`). |
| `format_exit_code(exit_code)` | `str` | Blank when `None`. |
| `describe(row)` | `str` | One-line summary of a run. |
| `format_run_row(row)` | `str` | A fixed-width row for the monospaced list. |
| `header_row()` | `str` | The matching column header. |
| `summarize(rows)` | `str` | Totals line (runs, failures, time). |

---

## `ryos.search`

Card search: what matches, and how the match is shown.

| Function | Returns | Purpose |
| --- | --- | --- |
| `normalize_query(raw, is_placeholder)` | `str` | Empty when the box still holds its placeholder text. |
| `matches(name, query)` | `bool` | Case-insensitive substring match. |
| `compute_hint(...)` | `str` | The "3 of 12" style hint under the box. |
| `find_spans(haystack, needle)` | `list[tuple[int, int]]` | Character ranges to highlight. |
| `step_match(count, current, forward=True)` | `int \| None` | Next/previous match index, wrapping. |

---

## `ryos.grouping`

| Function | Returns | Purpose |
| --- | --- | --- |
| `bucket_by_group(records, groups, …)` | `dict` | Split records into their groups, ungrouped bucket last, preserving group order. |

---

## `ryos.dragdrop`

Drag-and-drop reordering as geometry, separate from Tk's drag events.

| Function | Returns | Purpose |
| --- | --- | --- |
| `compute_insertion(drop_y, cards)` | `tuple` | Where a card dropped at `drop_y` lands. |
| `first_rect_at(x, y, rects)` | rect or `None` | Hit-test helper. |

---

## `ryos.screens` and `ryos.ui.placement`

Multi-monitor placement, split so the maths is testable without a display.
`screens.py` is pure geometry; `ui/placement.py` applies it to real widgets.
Together they are why a dialog opens on the monitor the app is on, fully
on-screen, rather than centred on the primary display.

`ryos.screens`:

| Function | Returns | Purpose |
| --- | --- | --- |
| `clamp_to_work_area(x, y, w, h, work_area)` | `tuple[int, int]` | Pull a window fully inside a work area. |
| `center_on_rect(parent_rect, w, h, work_area)` | `tuple[int, int]` | Centre over a parent, then clamp. |
| `anchored_position(ax, ay, w, h, work_area, …)` | `tuple[int, int]` | Place at an anchor — **flip, then clamp**, so a menu near an edge opens the other way rather than being shoved. |
| `relocate_geometry(geometry, src_work, dst_work)` | `str` | Move a saved geometry string between monitors. |
| `work_area_at_point(x, y)` | rect | Win32 `MonitorFromPoint` / `GetMonitorInfoW`. |
| `cursor_work_area()` | rect | The work area under the cursor. |
| `geometry_origin(geometry)` | `tuple[int, int]` | Parse `+x+y` out of a geometry string. |
| `center_in_work_area(w, h, work_area)` | `str` | A ready geometry string. |

`ryos.ui.placement`:

| Function | Purpose |
| --- | --- |
| `work_area_for_point(widget, x, y)` / `work_area_for_widget(widget)` | The work area a point or widget sits on. `_tk_screen_area` is the documented non-Windows fallback (Tk reports one virtual screen, so it cannot tell monitors apart). |
| `center_over_parent(window, parent, width=0, height=0)` | Centre a dialog over its parent window. |
| `offset_from_parent(window, parent, dx, dy)` | Cascade a window off its parent. |
| `place_near(window, x, y, dx=12, dy=12)` | Place near a point (context menus, pickers). |

---

## `ryos.themes`

The theme gallery and the colour maths behind it. `ui/theme.py` consumes this;
`ui/theme_editor.py` edits it.

Constants: `SEED_KEYS`, `ADVANCED_KEYS`, `CUSTOM_THEMES_PATH`, `PRESETS_DIR`,
`THEME_FILE_VERSION`, `USER_THEMES_DIR_DEFAULT`.

| Function | Returns | Purpose |
| --- | --- | --- |
| `contrast_ratio(c1, c2)` | `float` | WCAG contrast ratio — the check that keeps generated colours legible. |
| `build_palette(seed, overrides=None)` | `dict` | Derive a full palette from a handful of seed colours. |
| `is_hex_color(value)` | `bool` | |
| `validate_seed(seed)` | `list[str]` | Problems with a seed, empty when fine. |
| `contrast_warnings(seed)` | `list[str]` | Pairs that fall below the readable threshold. |
| `load_custom_themes(path=None)` / `save_custom_themes(themes, path=None)` | | User themes in `themes.json`. |
| `export_theme(name, seed, path)` / `import_theme(path)` | | Single-theme files. |
| `resolve_user_themes_dir(setting)` | `Path` | Where user theme files live. |

---

## `ryos.tray`

System-tray icon showing what is currently running. **`pystray` is optional** —
`available()` is false when it is missing and every entry point is a no-op, so
the app runs without it. CI exercises that path (`TestTrayWithoutPystray`);
a tray test that passes locally can fail on CI precisely because the dependency
is absent there.

Constants: `TIP_MAX = 127` (Windows truncates a longer tooltip),
`MENU_LABEL_MAX = 60`.

| Name | Returns | Purpose |
| --- | --- | --- |
| `tray_title(job_names, base)` | `str` | The tooltip text — base name plus running jobs, ellipsized to `TIP_MAX`. Pure, and unit-tested. |
| `TrayIcon.available()` | `bool` | Whether a tray is usable at all. |
| `TrayIcon.set_jobs(jobs)` | — | Refresh tooltip and menu from the running set. |
| `TrayIcon.start()` / `.stop()` | — | Run the icon on its own thread. |

---

## `ryos.single_instance`

Second-launch guard. A new process hands its arguments to the running window
and exits **0** — which looks identical to a crash to any liveness check, so
the release smoke test sets `RYOS_ALLOW_MULTIPLE=1` to bypass it.

| Function | Returns | Purpose |
| --- | --- | --- |
| `acquire(restore_existing=True, verb="RESTORE")` | `SingleInstance \| None` | `None` when another instance owns the mutex — the caller should exit. |

---

## UI layer (`ryos.ui`) — summary

These modules import Tkinter and are exercised through the app, not unit-tested
directly.

| Module | Public surface |
| --- | --- |
| `app.py` | `RYOSApp` — the main window. Owns the job lifecycle, output panel, tabs, drag-and-drop, Quick Run bar, the schedule tick (`_tick_schedules`, every 30 s) and output find/filter. |
| `cards.py` | `ScriptCard`, `PipelineCard`; module helpers `set_compact_mode`, `set_card_size`, `card_padding`, `row_metrics`, and `run_button_style(last_status)` — which turns the Run button into a red retry button after a failure. |
| `dialogs.py` | `ScriptDialog`, `NewGroupDialog`, `GroupBaseDirDialog`, `ParamPickerDialog`, `AdvancedOptionsDialog` (Appearance / Startup & Window / Output / Quick Run / Logging tabs), schedule and run-history dialogs. |
| `pipeline.py` | `PipelineEditorDialog`, plus `_policy_marks()` — the `!`, `↻n`, `?ok`, `?fail`, `→launch` annotations on a step row. |
| `theme.py` | `apply_theme(theme_name, accent=None)`, the `C` palette dict every widget reads its colours from, `HIGHLIGHT_SEEDS` / `highlight_fg(key, *surfaces)` for per-card label colours, plus ttk-style and snap-to-corner helpers. |
| `theme_editor.py` | `ThemeEditorDialog`. |
| `widgets.py` | `Tooltip`, `ScrollingLabel`. |
| `placement.py` | Documented above — it is pure enough to unit-test, unlike the rest of this layer. |

Two conventions hold across this layer: **every colour comes from the `C` dict**
in `theme.py` rather than a literal, and **worker threads never touch a
widget** — they post to the output queue instead.
