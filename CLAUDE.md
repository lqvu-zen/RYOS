# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
uv run script_runner.py
```

`uv` reads the PEP 723 inline metadata at the top of `script_runner.py` and automatically provisions the correct Python version (≥3.10) in an isolated environment. No manual `pip install` or virtualenv setup needed.

If `uv` is not installed: `pip install uv` or see https://docs.astral.sh/uv/getting-started/installation/

All dependencies are from the standard library (tkinter, sqlite3, subprocess, threading). On Linux, tkinter may require a separate system package (`python3-tk` on Debian/Ubuntu).

## Building the Executable

```bash
uv run --with pyinstaller pyinstaller RYOS.spec --noconfirm
# or double-click build.bat
```

Output: `dist/RYOS.exe`

## Architecture

Single-file desktop app (`script_runner.py`) with three layers:

1. **`ScriptDB` class** — SQLite wrapper using context managers. Database file `scripts.db` is created on first run in the working directory (or next to `RYOS.exe` when frozen).

2. **Helper functions** — `detect_interpreter()` maps file extensions to executables; `build_command()` assembles the subprocess command list.

3. **`RYOSApp` class** — Tkinter (`tk.Tk`) UI. Execution runs in a `threading.Thread`; output is fed through a `queue.Queue` and drained by a recurring `after(80, ...)` timer to keep the UI responsive. Subprocess stdout/stderr are merged via `STDOUT`.

## Key Design Choices

- **Thread-safe output**: worker thread puts lines into a `Queue`; the main loop polls it — never write directly to the `Text` widget from the worker.
- **Interpreter detection**: extension-to-interpreter map in `detect_interpreter()`; users can override with a custom interpreter field.
- **Parameter parsing**: `shlex.split(params, posix=not sys.platform.startswith("win"))` — platform-aware.
- **Process termination**: stored in `self.current_process`; `Stop` button calls `.terminate()` / `.kill()`.
