# RYOS — Run Your Own Scripts

A desktop app for saving and running scripts from a clean card-based UI. Supports Python, Node.js, Bash, PowerShell, Batch, and any other executable — with live output, execution history, and a standalone Windows build.

---

## Quick Start

**Run from source** (requires [uv](https://docs.astral.sh/uv/getting-started/installation/)):
```bash
uv run script_runner.py
# or double-click
run.bat
```

**Run the standalone exe** (no Python or uv needed):
```
dist/RYOS.exe
```

---

## Features

- Card-based script list — name, path, last run time
- One-click **Run** and **Modify** per card
- Auto-detect interpreter from file extension
- Override interpreter per script
- Pass parameters to scripts
- Real-time output panel with color-coded stdout/stderr
- Stop a running script at any time
- Copy or clear the log
- Collapsible output panel
- SQLite-backed — persists scripts and run history

---

## Building the Executable

```bash
# double-click, or:
build.bat
```

Output: `dist/RYOS.exe` — single file, no dependencies required on the target machine. The database (`scripts.db`) is created next to the exe on first run.

To rebuild after code changes:
```bash
uv run --with pyinstaller pyinstaller RYOS.spec --noconfirm
```

---

## Supported Script Types

| Extension | Interpreter |
|-----------|-------------|
| `.py` | Python (current) |
| `.js` | node |
| `.ts` | ts-node |
| `.sh` | bash |
| `.ps1` | powershell |
| `.rb` | ruby |
| `.pl` | perl |
| `.php` | php |
| `.bat` `.cmd` `.exe` | direct |

Leave the **Interpreter** field blank for auto-detection, or type any custom command (e.g. `python -u`).

---

## Test Scripts

Populate the database with 11 ready-made test scripts:

```bash
uv run tests/seed_db.py
```

| Script | Purpose |
|--------|---------|
| `hello_python.py` | Python version & platform info |
| `hello_node.js` | Node.js version & platform info |
| `hello_powershell.ps1` | PowerShell version info |
| `hello_batch.bat` | Windows Batch |
| `hello_cmd.cmd` | Windows CMD |
| `hello_bash.sh` | Bash version & hostname |
| `args_echo.py` | Echoes arguments back (pre-filled: `hello world`) |
| `slow_counter.py` | Counts to 30 at 1 s/step — test the Stop button |
| `exit_error.py` | Exits with code 2 — test red error output |
| `env_info.py` | Python executable, CWD, PATH |
| `flood_output.py` | 500 lines fast — test scroll performance |

Re-run `seed_db.py` at any time; it skips entries that already exist.

---

## Requirements

- **uv** — for running from source or building the exe
- **Linux only**: `sudo apt install python3-tk` (tkinter is bundled on Windows and macOS)
- All other dependencies are Python standard library

---

## Project Structure

```
script_runner.py   — main application (single file)
run.bat            — launch via uv run
build.bat          — rebuild dist/RYOS.exe
RYOS.spec          — PyInstaller build config
scripts.db         — SQLite database (created on first run)
tests/
  seed_db.py       — populate database with test scripts
  *.py / *.bat / *.sh / .ps1 / .js — sample test scripts
dist/
  RYOS.exe         — standalone Windows executable
```
