# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
uv run ryos
```

`uv` reads `pyproject.toml`, provisions Python ≥3.10 in an isolated environment, installs `tkinterdnd2`, and invokes the `ryos` console-script entry (`ryos.__main__:main`). No manual `pip install` or virtualenv setup needed.

If `uv` is not installed: `pip install uv` or see https://docs.astral.sh/uv/getting-started/installation/

All dependencies are from the standard library (tkinter, sqlite3, subprocess, threading). On Linux, tkinter may require a separate system package (`python3-tk` on Debian/Ubuntu).

## Building the Executable

```bash
uv run --with cx_Freeze --with tkinterdnd2 python setup_cxfreeze.py build_exe
# or double-click build.bat / build_cxfreeze.bat
```

Output: `dist/cxfreeze/` folder containing `RYOS.exe` and required DLLs. Distribute the whole folder (or zip it). cx_Freeze is the only supported packager.

## Architecture

Tkinter desktop app organized as the `ryos/` package. Entry point is `ryos.__main__:main`, exposed as the `ryos` console-script via `pyproject.toml`.

| Concern                                        | Module                  |
| ---------------------------------------------- | ----------------------- |
| Paths, settings load/save                      | `ryos/settings.py`      |
| Windows "run at login" registry                | `ryos/startup.py`       |
| Toast + GitHub update check                    | `ryos/notifications.py` |
| `ScriptDB` (all SQLite logic)                  | `ryos/db.py`            |
| `detect_interpreter`, `build_command`          | `ryos/interpreter.py`   |
| Subprocess worker + output-queue protocol      | `ryos/runner.py`        |
| `Job` state, `JobRegistry`, capacity split     | `ryos/jobs.py`          |
| Pipeline sequencing, step policies             | `ryos/job_controller.py`|
| Recurring schedules (pure, naive local time)   | `ryos/scheduling.py`    |
| Firing due schedules (shared sweep)            | `ryos/schedule_runner.py` |
| Run-history formatting                         | `ryos/history.py`       |
| Card search / filtering                        | `ryos/search.py`        |
| Group ordering and collapse state              | `ryos/grouping.py`      |
| Card and tab right-click menus (as data)       | `ryos/cardmenu.py`      |
| Select mode: bar text, run-selected plan       | `ryos/selection.py`     |
| Card sections, favourites, collapse state      | `ryos/sections.py`      |
| Export / import / Delete All wording           | `ryos/configio.py`      |
| Drag-and-drop reordering rules                 | `ryos/dragdrop.py`      |
| Monitor work areas (pure geometry)             | `ryos/screens.py`       |
| Dialog placement on the right monitor          | `ryos/ui/placement.py`  |
| System-tray icon, tooltip, dynamic menu        | `ryos/tray.py`          |
| Tray contents, close/minimise/quit rules       | `ryos/traypolicy.py`    |
| Single-instance guard / handoff                | `ryos/single_instance.py` |
| Theme gallery + WCAG `contrast_ratio`          | `ryos/themes.py`        |
| Theme, widgets, dialogs, cards, app            | `ryos/ui/*`             |
| `__version__`                                  | `ryos/__init__.py`      |

Fuller detail, including which modules are unit-tested and why each was
extracted, lives in `docs/ARCHITECTURE.md`.

Execution runs in a `threading.Thread`; output is fed through a `queue.Queue` and drained by a recurring `after(80, ...)` timer on the main UI thread.

## Key Design Choices

- **Thread-safe output**: worker thread puts lines into a `Queue`; the main loop polls it — never write directly to the `Text` widget from the worker.
- **Interpreter detection**: extension-to-interpreter map in `detect_interpreter()`; users can override with a custom interpreter field.
- **Parameter parsing**: `shlex.split(params, posix=not sys.platform.startswith("win"))` — platform-aware.
- **Process termination**: a job may have several steps in flight, so handles live in `Job.processes` (`step_token -> Popen`); `Stop` walks `job.active_processes()` and calls `.terminate()` on each. `Job.current_process` still exists for the single-step path — don't reach for it when writing anything pipeline-aware.
- **One-way imports**: `ryos/ui/*` may import top-level modules; top-level modules must never import `ryos.ui`. That is what keeps the core unit-testable without a display.
- **Schema changes**: `_ensure_baseline()` in `db.py` is frozen. New columns and tables go in `_MIGRATIONS`, keyed by the `PRAGMA user_version` they upgrade to, and each one re-checks `PRAGMA table_info` so it is safe to run twice.
- **Widening an accessor row is a breaking change**: `db.get()` and `list_pipeline_steps()` are unpacked by name in the UI, and appending a column has silently broken those call sites three times. Slice to a fixed width (`rec[:7]`, `row[:8]`) at the call site, and `TestRowWidthsArePinned` in `tests/test_ryos.py` pins the widths as a tripwire.
