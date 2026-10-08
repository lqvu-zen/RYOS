# RYOS v2.3.0 — Release Plan (MCP in the build, RYOS Agent)

_Created 2026-10-08 at v2.2.0 · replaces the first draft (`RELEASE_2.3.0_PLAN.md`), which was written against the Tk-era layout (`ryos/ui/dialogs.py`, tkinter) and planned some work that is already done. Follows [`agent-support.md`](agent-support.md), which shipped in 2.2.0._

## Where we are

2.2.0 shipped the command line (`ryos-cli list | run | pipeline`, `ryos-cli.exe` in the Windows build) and the MCP server (`ryos mcp`). The MCP server runs only from source (`uv run --extra mcp ryos mcp`, plan decision D12), so a Windows user has to get the portable zip and install `uv` just to connect Claude. Adding scripts, presets and agent access still needs the window.

## Goals

1. **MCP inside the Windows build.** Connecting Claude is one config line pointing at `ryos-cli.exe mcp`: no `uv`, no second download.
2. **RYOS Agent.** A download for people who want Claude to run an allow-list of their scripts and have no use for the window: everything — adding scripts, presets, agent access, history — from `ryos-cli`.
3. **A clear set of downloads**, each telling you which file is yours when it says there is an update.

## Downloads

| Artifact | Contents | For |
| --- | --- | --- |
| `RYOS-windows.zip` | `RYOS.exe` + `ryos-cli.exe`, MCP built in | Most users |
| `RYOS-agent.zip` | `ryos-cli.exe` only, MCP built in, **no Qt** | People who only want Claude to run their scripts |
| `RYOS-portable.zip` | Source; MCP stays the optional extra | Run from source, developers |

No `RYOS-windows-noagent.zip` (decision A1). One portable zip: with or without AI it would be the same files, since the SDK is fetched only by `--extra mcp`.

## What the first draft got wrong (and why it changes the steps)

| Draft | Actual state |
| --- | --- |
| Step 3: "MCP not available" without a traceback | Done in 2.2.0 (`mcpserver.serve`): one line, different in the build. Only the exit code changes (1 → 125). |
| Step 4: move validation out of `ryos/ui/dialogs.py` | Done long ago: the checks are toolkit-free in `ryos/scriptform.py` (`validate`, `resolve_path`, `shows_relative`, `relative_field`, `browse_refusal`, `name_from_path`). The CLI calls them. **Dropped.** |
| Step 5: keep the CLI free of tkinter | There is no tkinter in RYOS. The CLI path already never imports Qt (`tests/test_cli.py` runs the real entry point and checks). What matters is **packaging**: the build takes the whole `ryos` package, `qtui` with it, which drags in PySide6 — the agent build must leave both out. **Folded into step 10.** |
| Step 6: record a schema version | Recorded since v1 (`PRAGMA user_version`, now 9). Migrations only add, so an older build runs on a newer database today (2.1.2 on v9). A blanket "newer → refuse" would break that. **Redesigned (A3, step 4).** |
| Step 9: the update check picks the matching asset | The check downloads nothing; it opens the release page. Nothing can "update into another variant". **Shrinks to naming the right zip (step 8).** |
| Ground rules: `ui/*`, `_refresh_cards()`, a `PRAGMA` guard | Stale. The rules are `CLAUDE.md`'s. |

## Decisions (defaults — change any of them before the step that uses it)

| # | Question | Default | Why |
| --- | --- | --- | --- |
| A1 | Ship a "no agent" Windows zip? | **No** | "Available to agents" is off by default; a fourth zip doubles the build and test matrix. Add it later if someone asks. |
| A2 | Can an agent manage the allow-list? | **Not over MCP**: no tool adds, edits, exposes or changes a preset. **`ryos-cli expose … on` and `add --expose` need an interactive terminal, or `--yes`.** | Claude Code has a shell, so MCP being read-only does not stop it typing `ryos-cli expose X on`. The terminal check stops it in passing, not a determined agent — and an agent with a shell can run the script directly anyway. The docs say plainly that the allow-list protects MCP-only clients (Claude Desktop), and is a convenience, not a boundary, for agents with a shell. |
| A3 | An older build meets a newer database | A **"compatible from"** number, stored beside `user_version`, raised only by a migration older builds cannot live with. A build refuses to open a database whose number is past what it knows, with "created by a newer RYOS; please update". Additive migrations leave it alone. | Keeps today's working downgrades; protects against the one that would corrupt. It cannot protect 2.2.0 and earlier, which shipped without it — docs say "from 2.3.0 on". |
| A4 | Exposure default | Off everywhere; `add` exposes only with `--expose` | As in 2.2.0. |
| A5 | Shared data | Every download uses `%APPDATA%\RYOS` | The agent package and the full app see the same scripts, presets, history and exposure. |
| A6 | Pipeline authoring from the CLI | Not in 2.3.0 | Pipelines are made in the window and run from anywhere. |
| A7 | Script names | `add` and `edit` refuse a name its group already has | Names are not unique in the database; a second "backup" in a group could be named only by `#id`. |
| A8 | The CLI and `validate`'s questions | A **confirm** verdict (missing file, outside the base folder) refuses with 125 unless `--yes` | A command line cannot ask; refusing is the safe default. |

## Rules for every step

`CLAUDE.md`'s, in particular: top-level modules never import `ryos.qtui`/PySide6; worker threads never touch widgets; schema changes are a `_MIGRATIONS` entry; accessor rows are not widened; cards update in place on run/stop. Each step is one reviewable commit with the unit suite, ruff, mypy, `qt_smoke.py` and `session_smoke.py` green, and the launch smoke on a build when the build changes. `__version__` changes only at release, and the maintainer names it.

## Steps

### 1 — Decisions
A1–A8 above. **Done:** defaults taken (2026-10-08).

### 2 — MCP inside the frozen `ryos-cli.exe` *(riskiest — start first)*
Include `mcp` and its dependencies in the cx_Freeze build of `ryos-cli.exe` (both downloads). The SDK and its 25 dependencies are 28.5 MB installed, `pywin32` alone 14.5 MB — find out what can be left out. Expect missing-module trouble from `pydantic_core`, `anyio` backends and lazy imports. Record the size of the full build before and after (2.2.0: 65 MB).
**Done when** `ryos-cli.exe mcp` lists, runs, polls and stops under a real MCP client against the built exe (an extension of `tests/test_mcpserver.py` pointed at it), and Claude Code and Claude Desktop connect to it with no Python or `uv` on `PATH`. If Windows Sandbox is available, also on a fresh Windows.

### 3 — Exit code for "MCP not available"
`ryos mcp` without the SDK exits with 125 (RYOS refused), as the CLI's other refusals do. A unit test.

### 4 — The "compatible from" guard (A3)
A `meta`-style record of the compatibility number; `ScriptDB` refuses to open a database past what it knows, with a clear message the window, the CLI and the MCP server each show their own way. No migration in 2.3.0 raises it. Tests: an older number opens, an equal one opens, a newer one refuses and leaves the file untouched.

### 5 — CLI management commands
```text
ryos-cli add <file> [--name N] [--group G] [--workdir DIR] [--params="..."] [--expose] [--yes]
ryos-cli edit <script> [--name N] [--group G] [--workdir DIR] [--params="..."] [--yes]
ryos-cli remove <script> [--yes]
ryos-cli expose <script-or-pipeline> on|off [--yes]
ryos-cli preset add <script> <label> --params="..."
ryos-cli preset remove <script> <label>
ryos-cli history [<script-or-pipeline>] [--limit N] [--json]
```
- Built on `ScriptDB` and `scriptform` (`validate`, `resolve_path`, `name_from_path`), and `interpreter` detection — the dialog's own rules, so a script added here behaves as one added in the window.
- Naming as in 2.2.0 (`name`, `group/name`, `#id`; ambiguous refused with candidates). A7: duplicate names in a group refused. A8: confirm verdicts refuse unless `--yes`.
- A2: `expose … on` and `add --expose` refuse without an interactive terminal unless `--yes`. `remove` asks unless `--yes`.
- Refusals exit 125.
- A running window shows the changes: a new single-instance verb that makes the window rebuild its rows (today's `RELOAD` only updates last-run status in place).
- Tests for every command, the ambiguous-name, bad-path, duplicate-name, no-terminal and `--yes` cases, and qt_smoke for the window rebuilding on the new verb.
**Done when** a script can be added, given presets, exposed, run, seen in history and removed without opening the window.

### 6 — History says who started a run
`runs.trigger_source` has been recorded since 2.2.0 (`manual`, `schedule`, `pipeline`, `cli`, `agent`) but nothing shows it. `ryos-cli history` shows it, and so does the window's Run history (wording in `ryos/history.py`). Page 14 promises it.

### 7 — Build variant
`ryos/_build_info.py`, written at build time: `VARIANT = "windows" | "agent" | "portable"` (portable is the default when the file is absent). Shown in Help → About, `ryos-cli --version` and the bug report's environment.

### 8 — Updates name the right download
The update banner (window) and a new `ryos-cli version --check` (no window to show a banner) say which zip is yours: "RYOS 2.3.1 is out — download RYOS-agent.zip". Toolkit-free wording in `notifications.py`; the check stays read-only and never downloads.

### 9 — Exit-code and help polish
`ryos-cli` with no command prints help (as now) and lists the new commands; `--help` per command; the Windows build's `ryos-cli.exe` help mentions `mcp`.

### 10 — The agent build target
A build target producing `RYOS-agent.zip`: `ryos-cli.exe` only, variant `agent`, **without `ryos.qtui` and PySide6** (the draft's step 5), MCP included. Record its size against the full build. The launch smoke learns `--agent`: CLI checks only, and that no Qt DLL is in the folder.

### 11 — Build matrix
One command builds every download with consistent names, plus `SHA256SUMS.txt`. The release skill and its zip checks learn the agent zip.

### 12 — Docs
- Page 13: "Connect Claude" for the exe (`ryos-cli.exe mcp`, no `uv`), from source as the alternative; the management commands; A2 stated plainly.
- Page 14, RYOS Agent: from the draft beside this plan ([`release-2.3.0-page14-draft.md`](release-2.3.0-page14-draft.md)); linked from the contents and page 13. Every command on it run for real before it ships.
- README and release notes: a "Which download?" table.

### 13 — Release check
For each download: upgrade over v2.2.0 data (a copy; `real_data_smoke.py --db` on a backup); window builds through the launch smoke on the second screen; the CLI and management commands; MCP builds with Claude Code and Claude Desktop (list, run, poll, stop); a mixed install both ways (agent first, then the full app, and the reverse — same scripts and history); the A3 guard against a database marked newer. Then the `release-ryos` skill, with the version the maintainer names.

## Order

```
Step 2 (MCP in the build) ────────────────┐
Step 5 (CLI management) ──► Step 6 ───────┼──► Step 10 (agent build) ──► Step 11 ──► Step 12 ──► Step 13
Steps 3, 4 (small, any time)              │
Step 7 (variant) ──► Step 8 (updates) ────┘
```

Steps 2 and 5 are the big pieces and run side by side; 3, 4 and 7 are small and fit anywhere. Step 10 needs 2 and 7.

## Status

| Step | State |
| --- | --- |
| 1 Decisions | defaults taken |
| 2 MCP in the build | done (full build 65 → 93 MB; `cryptography` is imported at start, so it stays) |
| 3 Exit code | done |
| 4 Compatible-from guard | — |
| 5 CLI management | done |
| 6 History source | — |
| 7 Build variant | — |
| 8 Update names the zip | — |
| 9 Help polish | — |
| 10 Agent build | — |
| 11 Build matrix | — |
| 12 Docs | — |
| 13 Release check | — |
