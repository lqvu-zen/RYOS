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

| Concern                                  | Module                  |
| ---------------------------------------- | ----------------------- |
| Paths, settings load/save                | `ryos/settings.py`      |
| Windows "run at login" registry          | `ryos/startup.py`       |
| Toast + GitHub update check              | `ryos/notifications.py` |
| `ScriptDB` (all SQLite logic)            | `ryos/db.py`            |
| `detect_interpreter`, `build_command`    | `ryos/interpreter.py`   |
| Theme, widgets, dialogs, cards, app      | `ryos/ui/*`             |
| `__version__`                            | `ryos/__init__.py`      |

Execution runs in a `threading.Thread`; output is fed through a `queue.Queue` and drained by a recurring `after(80, ...)` timer on the main UI thread.

## Key Design Choices

- **Thread-safe output**: worker thread puts lines into a `Queue`; the main loop polls it — never write directly to the `Text` widget from the worker.
- **Interpreter detection**: extension-to-interpreter map in `detect_interpreter()`; users can override with a custom interpreter field.
- **Parameter parsing**: `shlex.split(params, posix=not sys.platform.startswith("win"))` — platform-aware.
- **Process termination**: stored in `self.current_process`; `Stop` button calls `.terminate()` / `.kill()`.
