# RYOS Tutorial

**RYOS (Run Your Own Scripts)** keeps the scripts you run often in one window and runs any of them with one click. No terminal, no memorising paths — press the green play button.

The full guide, with real screenshots of every screen, is the **[illustrated user guide](docs/tutorial/README.md)**. This page covers installing RYOS and points you to the right chapter.

---

## Installation

### Option A — Standalone executable
Download `RYOS-windows.zip` from the latest release, extract it, and double-click `RYOS.exe`. No installation required. `ryos-cli.exe` beside it is the command line. For AI agents (Claude), download `RYOS-windows-ai.zip` instead: the same app with the MCP server built in. From 2.4 on, RYOS updates itself; see [Updating and rolling back](docs/tutorial/15-updating.md).

### Only want Claude to run your scripts?
Download `RYOS-agent.zip` instead: just `ryos-cli.exe`, no window. See [RYOS Agent](docs/tutorial/14-ryos-agent.md).

### Check your download
RYOS is not code-signed yet, so check what you downloaded before you run it:

1. Download only from [github.com/lqvu-zen/RYOS/releases](https://github.com/lqvu-zen/RYOS/releases).
2. In PowerShell, in the folder you downloaded to, run `Get-FileHash .\RYOS-windows-ai.zip -Algorithm SHA256` (or the zip you downloaded). The result must match that zip's line in the release's `SHA256SUMS.txt`. Capital or small letters do not matter.
3. Optional, and the strongest check: put `SHA256SUMS.txt` and `SHA256SUMS.txt.sig` from the release beside the zip and, with an RYOS you already trust, run `ryos-cli.exe verify .\RYOS-windows-ai.zip`. It must succeed. RYOS makes the same check itself before it installs an update.
4. Right-click `RYOS.exe` (or `ryos-cli.exe`) -> Properties -> Details. The company reads **Zenitus (Lê Quang Vũ)**.
5. Windows SmartScreen will say "Unknown publisher"; that is expected for an unsigned app. Choose **More info -> Run anyway** only for a download that passed the check.

### Option B — Portable (run from source)
1. Download and extract `RYOS-portable.zip`.
2. If you don't have [uv](https://docs.astral.sh/uv/) installed, double-click `install_uv.bat` once.
3. Double-click `run.bat` to launch.

> **Note:** RYOS stores your data (`scripts.db`, `settings.json`, and logs) in `%APPDATA%\RYOS` on Windows (or `~/.local/share/RYOS` elsewhere). If an older version kept these files next to the executable, RYOS migrates them automatically on first launch.

---

## The guide

1. [The main window](docs/tutorial/01-main-window.md) — the header, groups, favourites, pipelines and scripts, and a row's buttons.
2. [Adding a script](docs/tutorial/02-adding-a-script.md) — drop files in, or use the script dialog.
3. [Running a script and reading its output](docs/tutorial/03-running-and-output.md) — Run, Retry, Stop, and the output panel.
4. [Groups](docs/tutorial/04-groups.md) — organising, base folders, moving scripts between groups.
5. [Parameters and presets](docs/tutorial/05-parameters-and-presets.md) — saved parameters, presets, and asking each run.
6. [Pipelines](docs/tutorial/06-pipelines.md) — chaining scripts, and what each step does on failure.
7. [Schedules and run history](docs/tutorial/07-schedules-and-history.md) — running by itself, and looking back.
8. [Quick Run](docs/tutorial/08-quick-run.md) — running any file in a group's folder by name.
9. [The maximised layout](docs/tutorial/09-maximised-layout.md) — list on the left, details on the right.
10. [Import and export](docs/tutorial/10-import-export.md) — backing up and moving your setup.
11. [Settings and appearance](docs/tutorial/11-settings.md) — Options, themes and the accent colour.
12. [Tips](docs/tutorial/12-tips.md) — compact rows, select mode, and small time-savers.
13. [The command line and AI agents](docs/tutorial/13-command-line-and-agents.md) — running scripts from a terminal, and letting Claude run the ones you choose.
14. [RYOS Agent](docs/tutorial/14-ryos-agent.md) — RYOS without the window: add your scripts, choose what Claude may run, connect it.
15. [Updating and rolling back](docs/tutorial/15-updating.md) — Restart to update, Help → Roll back, `ryos-cli update`, and what to do when an update fails.
