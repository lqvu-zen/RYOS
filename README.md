# RYOS — Run Your Own Scripts

A lightweight Windows desktop app for organizing and running your scripts from a clean, card-based UI. Save your Python, Node, Bash, PowerShell, Batch — or any executable — once, then run it with a single click. No terminal juggling, no remembering paths and arguments.

Built with Python + Tkinter. Ships as a single standalone `.exe` (no Python required on the target machine) or runs straight from source.

## Contents

- [Features](#features)
- [Getting Started](#getting-started)
- [How to Use](#how-to-use)
  - [Scripts](#scripts)
  - [Groups](#groups)
  - [Pipelines](#pipelines)
  - [Parameter presets](#parameter-presets)
  - [Quick Run bar](#quick-run-bar)
  - [Output panel](#output-panel)
  - [Export / Import](#export--import)
- [Settings](#settings)
- [Supported Script Types](#supported-script-types)
- [Building the Executable](#building-the-executable)
- [Architecture](#architecture)

## Features

- **Card-based launcher** — every script is a card with a one-click **Run**, a language badge, and its last-run time.
- **Groups** — organize scripts into tabs, give each group a base directory, and rename, clone, or export a group on its own.
- **Pipelines** — chain several scripts into an ordered sequence and run them as one, with optional per-step parameter overrides.
- **Parameter presets** — save frequently-used argument sets per script and pick one at run time.
- **Quick Run bar** — type a filename (with autocomplete) to run a script in a group's base directory without adding a card first.
- **Drag & drop** — drop one or more script files onto the window to add them instantly.
- **Tabbed output** — live stdout/stderr per run, with **stderr in red**; copy or save any tab's log.
- **Desktop notifications** — optional Windows toast when a script or pipeline finishes.
- **Auto-update check** — checks GitHub for new releases on startup (or on demand).
- **Runs at login** — optionally start with Windows, minimized, always-on-top, snapped to a screen corner.
- **Logging** — built-in log viewer and a one-click "open log folder" for troubleshooting.

## Getting Started

**Option A — Standalone exe** (no Python needed)

Download the latest release, unzip, and run:

```
RYOS.exe
```

The script database (`scripts.db`) is created next to the exe on first run.

**Option B — Run from source** (requires [uv](https://docs.astral.sh/uv/getting-started/installation/))

```bash
uv run ryos
```

or double-click `run.bat`. `uv` provisions Python ≥3.10 in an isolated environment, installs the lone dependency (`tkinterdnd2`), and launches the app — no manual `pip install` or virtualenv needed. If `uv` isn't installed, run `install_uv.bat` or follow the [uv install guide](https://docs.astral.sh/uv/getting-started/installation/).

> On Linux, Tkinter may need a system package (`sudo apt install python3-tk` on Debian/Ubuntu).

## How to Use

### Scripts

Click **+ Add Script** (top-right) or **drag a script file onto the window**. Fill in:

| Field | Description |
|-------|-------------|
| **Name** | Display name shown on the card |
| **Path** | Full path to the script file (e.g. `C:\scripts\backup.py`) |
| **Interpreter** | Leave blank to auto-detect from the extension, or enter a custom command (e.g. `python -u`, `node`) |
| **Parameters** | Arguments passed to the script on each run (e.g. `--verbose output.txt`) |
| **Group** | Which group the card belongs to |

Click **Save** to add it. Then:

- **Run** — executes the script in the background; the card's last-run time updates afterward.
- **Modify** — edit the name, path, interpreter, or parameters (the edit dialog also has a **Delete** button).
- **↑ / ↓** — reorder a card within its group.

### Groups

Groups are tabs across the top that keep related scripts together. Right-click a group tab to:

- **Rename** or **Clone Group**
- Set a **Base directory** — the working directory for that group's scripts and the root for its Quick Run bar
- **Export group** to JSON
- **Delete Group**

### Pipelines

A pipeline runs several scripts in order, as a single unit. Create one from a group, add steps, drag to reorder, and optionally override the parameters for any individual step. Running the pipeline executes each step in sequence and (optionally) notifies you when the whole run completes.

### Parameter presets

For scripts you run with different arguments, save named presets so you can pick the right argument set at run time instead of editing the card each time.

### Quick Run bar

Enable **Show Quick Run bar** in settings (requires a group **base directory**). Type a filename — with optional autocomplete suggestions — to run a script located in that directory without first creating a card. Handy for one-off or ad-hoc scripts.

### Output panel

The output panel sits at the bottom of the window and is hidden by default.

- Click **Show Output / Hide Output** to toggle it; drag the **divider** to resize.
- Each run gets its own **tab**. **stdout** is shown in the default color, **stderr in red**.
- Right-click a tab to **Copy**, **Save**, or **Close** its log.
- **Stop** terminates the running process.

### Export / Import

- **Options → Export all groups** (or per-group export via right-click) saves your scripts, groups, and pipelines to a JSON file.
- **Options → Import config** restores from a JSON file, with **Merge** (keep existing, skip duplicates) or **Replace** (clear and load).

## Settings

Open **Options → Advanced options…**:

| Setting | What it does |
|---------|--------------|
| **Start with Windows** | Launch RYOS at login (Windows registry entry) |
| **Always on top** | Keep the window above others |
| **Start minimized** | Launch hidden / minimized |
| **Remember window size and position** | Restore geometry on next launch |
| **Snap to screen corner** | Dock the window to a chosen corner |
| **Auto-clear output before each run** | Wipe the log when a new run starts |
| **Auto-scroll to bottom** | Follow output as it streams |
| **Notify when script / pipeline completes** | Windows toast on completion |
| **Check for updates on startup** | Compare against the latest GitHub release |

Troubleshooting: **Options → View logs** opens the in-app log viewer, and **Open log folder** reveals the log files on disk.

## Supported Script Types

| Extension | Interpreter |
|-----------|-------------|
| `.py` | Python |
| `.js` | node |
| `.ts` | ts-node |
| `.rb` | ruby |
| `.pl` | perl |
| `.php` | php |
| `.sh` | bash |
| `.ps1` | powershell |
| `.bat` `.cmd` `.exe` | run directly |

Leave **Interpreter** blank for auto-detection, or type any custom command to run anything else.

## Building the Executable

The primary packager is **cx_Freeze** (produces a folder you distribute or zip):

```bash
uv run --with cx_Freeze --with tkinterdnd2 python setup_cxfreeze.py build_exe
# or double-click build.bat
```

Output: `dist/cxfreeze/` containing `RYOS.exe` plus the required DLLs — distribute the whole folder (or zip it).

## Architecture

Tkinter desktop app organized as the `ryos/` package. Entry point is `ryos.__main__:main`, exposed as the `ryos` console-script.

| Concern | Module |
|---------|--------|
| Paths, settings load/save | `ryos/settings.py` |
| Windows "run at login" registry | `ryos/startup.py` |
| Toast + GitHub update check | `ryos/notifications.py` |
| `ScriptDB` (all SQLite logic) | `ryos/db.py` |
| `detect_interpreter`, `build_command` | `ryos/interpreter.py` |
| Logging utility | `ryos/logger.py` |
| Theme, widgets, dialogs, cards, pipelines, app | `ryos/ui/*` |

Execution runs in a `threading.Thread`; output is piped through a `queue.Queue` and drained by a recurring `after(80, ...)` timer on the main UI thread, so the worker never touches the Tk widgets directly.

## Documentation

- [Tutorial](TUTORIAL.md) — step-by-step user guide.
- [Architecture](docs/ARCHITECTURE.md) — module map, threading model, data flow.
- [Module reference](docs/API_REFERENCE.md) — public API of the core modules.
- [Contributing](docs/CONTRIBUTING.md) — dev setup, conventions, build steps.
- [Tech debt](TECH_DEBT.md) — known rough edges.
