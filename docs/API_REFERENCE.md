# RYOS module reference

Reference for the public surface of RYOS's core (UI-independent) modules — the
parts that are imported, reused, and unit-tested. The Tkinter layer in
`ryos/ui/` is summarised at the end; for its internals read the source
alongside `docs/ARCHITECTURE.md`.

Names prefixed with `_` are internal helpers, included only where they're part
of understanding a module's behaviour.

---

## `ryos.db` — `ScriptDB`

SQLite wrapper for scripts, groups, pipelines, and parameter presets. All
methods open a short-lived connection that commits on success and rolls back on
error.

```python
ScriptDB(db_path: Path = DB_PATH)
```

Opens (creating if needed) the database at `db_path` and runs schema setup:
`_ensure_baseline()` creates/upgrades to the v1 schema, then `_MIGRATIONS` apply
any later versions once each, gated by `PRAGMA user_version`. Pass a temp path
in tests.

Module-level constants: `SCHEMA_VERSION`, `_BASELINE_VERSION`, `_MIGRATIONS`.

### Scripts

| Method | Returns | Notes |
| --- | --- | --- |
| `add(name, path, params, interpreter, group_name="", temp_param=0)` | `int` (new id) | Appends at the end of the order. |
| `update(script_id, name, path, params, interpreter, group_name="", temp_param=None)` | — | `temp_param=None` leaves the flag untouched. |
| `delete(script_id)` | — | |
| `delete_many(ids: list[int])` | — | |
| `delete_all()` | — | Removes every script. |
| `get(script_id)` | tuple or `None` | `(id, name, path, params, interpreter, group_name, temp_param)`. |
| `list_all()` | list of tuples | `(id, name, path, params, interpreter, created_at, last_run_at, last_run_status, group_name, temp_param)`, ordered by group then `order_index`. |
| `mark_run(script_id)` | — | Stamps `last_run_at`, clears status (run started). |
| `mark_run_status(script_id, status)` | — | Records `"ok"` / `"error"` after completion. |

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

### Pipelines and steps

| Method | Returns | Notes |
| --- | --- | --- |
| `create_pipeline(name, group_name)` | `int` (new id) | |
| `clone_pipeline(pipeline_id)` | `int` (new id) | Copies steps; names it `"… (copy)"`. Raises `ValueError` if not found. |
| `rename_pipeline(pipeline_id, name)` | — | |
| `delete_pipeline(pipeline_id)` | — | Also deletes its steps. |
| `list_pipelines(group_name)` | list of `(id, name)` | |
| `list_pipeline_steps(pipeline_id)` | list of tuples | `(step_id, script_id, name, path, params, interpreter, params_override)`. |
| `add_pipeline_step(pipeline_id, script_id)` | `int` (step id) | |
| `remove_pipeline_step(step_id)` | — | |
| `reorder_pipeline_steps(pipeline_id, ordered_step_ids)` | — | |
| `update_pipeline_step_params(step_id, params_override)` | — | `None` = use the script's own params. |
| `reorder_pipeline(pipeline_id, group_name, before_id)` | — | |
| `move_pipeline_to_group(pipeline_id, new_group)` | — | |

### Parameter presets

| Method | Returns | Notes |
| --- | --- | --- |
| `list_param_presets(script_id)` | list of `(id, label, params)` | |
| `replace_param_presets(script_id, presets)` | — | `presets = [(label, params), …]`; replaces all. |

### Export / import

| Method | Returns | Notes |
| --- | --- | --- |
| `export_to_file(path, group_name=None)` | — | JSON of groups/scripts/pipelines/presets; one group or all. |
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

## UI layer (`ryos.ui`) — summary

These modules import Tkinter and are exercised through the app, not unit-tested
directly.

| Module | Public surface |
| --- | --- |
| `app.py` | `RYOSApp` — the main window. Owns the job lifecycle, output panel, tabs, drag-and-drop, and Quick Run bar. |
| `cards.py` | `ScriptCard`, `PipelineCard`; module helpers `set_compact_mode`, `set_card_size`, `card_padding`, `row_metrics`. |
| `dialogs.py` | `ScriptDialog`, `NewGroupDialog`, `GroupBaseDirDialog`, `ParamPickerDialog`, `AdvancedOptionsDialog` (Appearance / Startup & Window / Output / Quick Run / Logging tabs). |
| `pipeline.py` | `PipelineEditorDialog`. |
| `theme.py` | `apply_theme(theme_name, accent=None)`, plus internal ttk-style and snap-to-corner helpers. |
| `widgets.py` | `Tooltip`, `ScrollingLabel`. |
