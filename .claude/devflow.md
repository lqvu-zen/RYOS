# RYOS: devflow profile

The devflow skills and agents read this file for everything specific to this project. Keep the headings exactly as they are: briefs paste these sections by name. Write each section as rules and facts, not history.

## Project

- **What it is:** RYOS ("Run Your Own Scripts") is a Windows desktop app that manages and runs a user's scripts and pipelines: cards grouped in tabs, a run history, schedules, a command line (`ryos-cli`) and an MCP server for AI agents. It ships as GitHub releases of four zips (`RYOS-windows`, `RYOS-windows-ai`, `RYOS-agent`, `RYOS-portable`) that update themselves from signed releases.
- **Repo:** lqvu-zen/RYOS (main branch: `main`)
- **Maintainer:** Vũ (lqvu-zen), time zone UTC+7 (inferred, please check). They decide, name versions, sign releases, use each release candidate and run the manual checks.
- **Languages and stack:** Python >= 3.10 (frozen builds use 3.14), PySide6 (Qt), SQLite, cx_Freeze, uv

## Where things live

| Concern | File |
|---|---|
| Entry point | `ryos/__main__.py` (`main`), Qt app `ryos/qtui/main.py` |
| Data / storage | `ryos/db.py` (`ScriptDB`), `ryos/settings.py` |
| Settings / config | `ryos/settings.py` |
| UI | `ryos/qtui/*` |
| Rules and data, no Qt | top-level `ryos/*.py` (see `docs/ARCHITECTURE.md`) |
| Command line | `ryos/cli.py`, `ryos/manage.py`, `ryos/headless.py` |
| MCP server | `ryos/mcpserver.py`, rules in `ryos/agenttools.py` |
| Run engine | `ryos/runner.py`, `ryos/jobs.py`, `ryos/jobhost.py`, `ryos/job_controller.py` |
| Updates | `ryos/updates.py`, `ryos/selfupdate.py`, `ryos/swap.py`, `ryos/signature.py`, `ryos/ed25519.py` |
| Build variants | `ryos/buildinfo.py`, `setup_cxfreeze.py`, `build_release.py` |
| Tests | `tests/` (unit: `test_*.py`; smokes: `qt_smoke.py`, `launch_smoke.py`, `session_smoke.py`, `real_data_smoke.py`; gate: `release_check.py`) |
| Behaviour map | `docs/BEHAVIOUR.md` |
| Version | `ryos/__init__.py` (`__version__`), `setup_cxfreeze.py` (`version=`) |

## Architecture rules

- **One-way imports.** `ryos/qtui/*` may import top-level modules; top-level modules never import it (the one exception is `__main__`, inside `main()`). That keeps the core unit-testable without Qt or a display.
- **Real effects are passed in.** The window saves settings, reconfigures the log, shows toasts, checks for updates, writes run-at-login and quits only through arguments that do nothing by default; `ryos/qtui/main.py` is the one place that passes the real ones. That lets tests build windows freely.
- **Thread-safe output.** A worker thread puts lines into a `Queue`; `JobHost.pump()` drains it on the UI thread every 80 ms. Never touch a widget from the worker.
- **Schema changes go through `_MIGRATIONS`.** `_ensure_baseline()` in `db.py` is frozen. New columns and tables go in `_MIGRATIONS` keyed by the `PRAGMA user_version` they upgrade to, each re-checking `PRAGMA table_info` so it is safe to run twice. A release that brings a new schema adds a fixture with `tests/fixtures/db/make_fixtures.py vX.Y.Z`.
- **Widening an accessor row is a breaking change.** `db.get()` and `list_pipeline_steps()` are unpacked by name in the UI; slice to a fixed width at the call site (`rec[:7]`, `row[:8]`). `TestRowWidthsArePinned` pins the widths.
- **Process handles live in `Job.processes`** (`step_token -> Popen`); `Stop` walks `job.active_processes()`. Don't use `Job.current_process` in anything pipeline-aware.
- **Parameters parse with** `shlex.split(params, posix=not sys.platform.startswith("win"))`.
- **Variant IDs and zip names are fixed** once released (`ryos/buildinfo.py`): each build's update notice names its own zip. The `windows` variant has no MCP server.
- **Don't touch the version.** `__version__` changes only in a `Release candidate X.Y.Z-rcN` or `Release X.Y.Z` commit made by the `release` skill, never per change, never `-dev`. The maintainer chooses the number.
- **No code comments** in new or changed code (`CLAUDE.md`, Code Style). Names, structure and tests carry the intent; why-it-exists notes belong in `docs/` and the commit message. CI fails any new comment line under `ryos/`.
- **Every escaped bug adds its check.** One line in `docs/BEHAVIOUR.md` § Escapes: "#NN (vX.Y.Z): should have been caught by <check>; added <test / map entry / release_check case>".

## Verify

Run from the repo root. All must pass before a change is reviewed.

```bash
QT_QPA_PLATFORM=offscreen uv run --no-project --with pytest --with PySide6 --with "mcp>=2.3,<3" pytest -q
uvx ruff check .
uvx mypy
QT_QPA_PLATFORM=offscreen uv run --no-project --with PySide6 python tests/qt_smoke.py
```

Also, for changes that reach start-up, runs or the window (not re-run now): `uv run python tests/launch_smoke.py` and `QT_QPA_PLATFORM=offscreen uv run python tests/session_smoke.py`. For changes to the data layer, `uv run python tests/real_data_smoke.py` (copies the real data; counts only).

## Edit bounds

- **The implementer may edit:** `ryos/`, `tests/`, `docs/BEHAVIOUR.md`, `docs/ARCHITECTURE.md`.
- **Only when the plan names them:** `pyproject.toml`, `uv.lock`, `setup_cxfreeze.py`, `build_release.py`, `tests/release_check.py`, `tests/fixtures/db/`, `.github/workflows/`, `tools/`, `.claude/`.
- **Never staged:** `dist/`, `build/`, `.claude/worktrees/`, `.claude/discarded/`, `.claude/settings.local.json`, `__pycache__`, local databases, anything named `*.pem`, `*.key`, `*.p8`.

## Escalate

The implementer runs on Opus at medium effort for: database schema, migrations and the schema-version guard; packaging and freezing (`setup_cxfreeze.py`, cx_Freeze missing modules, `build_release.py`); the self-update swap and signature code; threading and the output queue.

## See it working

- Run on throwaway data: point `APPDATA` and `LOCALAPPDATA` at a scratch folder in the same command (Bash: `APPDATA="$S/a" LOCALAPPDATA="$S/l" uv run ryos ...`; PowerShell: `$env:APPDATA = '...'; $env:LOCALAPPDATA = '...'; ...`).
- Screenshots: `uv run python .claude/skills/run-ryos/driver.py` renders the real window off screen (`WA_DontShowOnScreen`) on a throwaway folder with the repo's `samples/`, and saves PNGs under `.claude/skills/run-ryos/screenshots/`. Smokes take `--visible` to show a window on the second screen only.
- `RYOS_NO_TOASTS=1` and `RYOS_NO_REGISTRY=1` (set by `.claude/settings.json`) turn off Windows toasts and run-at-login writes. Use `QT_QPA_PLATFORM=offscreen` otherwise.
- Never against the real data in `%APPDATA%\RYOS` or `%LOCALAPPDATA%\RYOS`. Never open a window on the maintainer's first screen.

## Design system

- **File:** `docs/DESIGN.md`, in Google's DESIGN.md format (tokens in the front matter, then the sections, then Platforms, States, Inputs and Motion).
- **Platforms the project ships to:** desktop (Windows; Qt/PySide6 widgets).
- **UI surfaces:** the window (normal and compact rows, favourite chips, the All tab, the maximised detail pane, select mode), dialogs, the tray and notifications: `ryos/qtui/*`, with colours from `ryos/themes.py` and `ryos/qtui/stylesheet.py`.

## Release

- **Repo:** `lqvu-zen/RYOS`.
- **Version files:** `ryos/__init__.py` (`__version__ = "X.Y.Z-rcN"`); `setup_cxfreeze.py` (`version=`, numbers only: `X.Y.Z`).
- **Build:** `uv run --python 3.14 --extra mcp --with cx_Freeze python build_release.py`; it ends with `build_release done`.
- **Gate:** `uv run --python 3.14 python tests/release_check.py` on throwaway data; it ends with `RELEASE CHECK PASSED`.
- **Stamp:** `dist/release_check.passed`, written by **Gate** and read by the guard.
  - Format: a JSON object with `head` (the full SHA of HEAD), `sha256sums` (the SHA-256 hex of `dist/SHA256SUMS.txt`) and `passed` (the case count, above 0). Extra fields are allowed and ignored.
  - **Gate** writes it only when every case passes and neither HEAD nor the bound file changed during the run. It deletes any old stamp when a run starts, and **Build** deletes it too.
  - With a stamp configured the guard refuses `gh release create`, `upload`, a publishing `edit` and `gh api` writes to releases unless the stamp names the current HEAD and the bound file's current hash.
- **Sign:** the maintainer runs `uv run --with cryptography python tools/sign_release.py sign <key file> --sums dist/SHA256SUMS.txt` after every build; Claude never signs, reads, or looks for the key. Every rebuild changes `SHA256SUMS.txt`, so it is signed again.
- **Artifacts:** `dist/RYOS-windows.zip`, `dist/RYOS-windows-ai.zip`, `dist/RYOS-agent.zip`, `dist/RYOS-portable.zip`, `dist/SHA256SUMS.txt`, `dist/SHA256SUMS.txt.sig`.
- **Notes:** every release's notes carry "Which download?" and "Check your download" (the hash matches `SHA256SUMS.txt`, and `ryos-cli verify <zip>`), and say what changed for someone using the app.
- **After:** clear `dist/`; add a fixture under `tests/fixtures/db/` when the schema changed.

### Lineup

| Artifact | Must contain | Must not contain |
|---|---|---|
| `RYOS-windows.zip` | `RYOS.exe`, `ryos-cli.exe`, no MCP server | the MCP SDK, caches, `__pycache__`, local databases |
| `RYOS-windows-ai.zip` | the above plus the MCP server inside `ryos-cli.exe` | caches, `__pycache__`, local databases |
| `RYOS-agent.zip` | `ryos-cli.exe` with MCP | Qt, a window, `RYOS.exe` |
| `RYOS-portable.zip` | exactly the tracked source, runs with uv via `run.bat` | `__pycache__`, `_build_info.py`, untracked files |

(Taken from the existing `release-ryos` skill's lineup; the full table there is the source until that skill is retired.)

### Checklist

- [ ] Claude Desktop connects to the `windows-ai` build's `ryos-cli.exe mcp` and runs an exposed script.
- [ ] Claude Code connects to the `agent` build and runs an exposed script.
- [ ] `uv run python tests/real_data_smoke.py` on the real data (and `--db <backup>` on an older backup): no count dropped.
- [ ] The real data looks right after the upgrade (scripts, groups, pipelines, schedules, history).
- [ ] A fresh download from the candidate's release page installs and starts; SmartScreen's flow; the hash matches `SHA256SUMS.txt`.
- [ ] Properties -> Details on `RYOS.exe` and `ryos-cli.exe` shows the publisher.

## Try it

- **Unpack:** each zip into a new folder in the scratchpad; run only the program itself from inside it.
- **Drive:** `uv run python tests/launch_smoke.py --exe <RYOS.exe>` (and `--cli-only` for the agent build); `ryos-cli.exe` `--version`, `list`, `run`, `add`, `expose`, `verify`; `ryos-cli.exe mcp` over plain JSON-RPC (initialize, tools, `list_scripts`, run, poll, stop); the off-screen driver `.claude/skills/run-ryos/driver.py` for the window.
- **Throwaway data:** `APPDATA` and `LOCALAPPDATA` point at a scratch folder in the same command, with `RYOS_NO_TOASTS=1` and `RYOS_NO_REGISTRY=1`.
- **Never:** launch a window on the main screen; sign anything; touch `%APPDATA%\RYOS`; run anything from inside an unpacked folder except the program itself.

## Standing rules

- Few release plans: the current one and the next at most.
- The version number is the maintainer's: always ask, even if one was proposed earlier.
- Every release goes through a release candidate; between a candidate and its promotion only `docs/`-only commits land on `main`.
- Every escaped bug adds its check.
- Push to `origin/main` after each gated commit; never force-push, and never create tags or releases without the maintainer.
- Clear `dist/` after every release.
- A session that breaks a process rule adds the rule or hook case that would have stopped it (`docs/BEHAVIOUR.md` § Harness escapes).
