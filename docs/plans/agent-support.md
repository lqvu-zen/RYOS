# RYOS — Agent Support Plan (CLI + MCP server)

_Created 2026-10-07 at v2.1.1 · replaces the first draft (`AGENT_SUPPORT_PLAN.md`), which was written against the Tk-era layout (`ryos/ui/`, PyInstaller) and planned work that has since been done._

## Goal

Let AI agents (Claude Code, Claude Desktop, Cowork) and plain automation (Task Scheduler, CI, git hooks) find, run and read the results of RYOS scripts and pipelines, through:

1. **A headless CLI** — `ryos list`, `ryos run`, `ryos pipeline`, with `--json` and meaningful exit codes.
2. **An MCP server** — `ryos mcp` over stdio, the same abilities as MCP tools.

Out of scope for now: an agent inside the RYOS window, agents creating or editing scripts, and live display of agent-started runs in the window (they reach History and the cards' last status; see step 5).

## Where the code already is

The draft's steps 1–3 (pull the run engine out of the UI, then move the UI onto it) are done:

| Piece | Module | Toolkit |
| --- | --- | --- |
| Subprocess worker, output-queue protocol, `terminate_tree` | `ryos/runner.py` | none |
| `Job`, `JobRegistry`, `own_runs`, capacity | `ryos/jobs.py` | none |
| Planning, pipeline sequencing, policies, retries, history rows | `ryos/job_controller.py` | none — callbacks injected |
| Run history (`runs` table, `trigger_source` column) | `ryos/db.py` | none |
| Launching, launcher release, run/pipeline entry points, schedule firing | `ryos/qtui/jobs.py` (`JobBridge`) | **Qt only for the timer and the signals** |

So the remaining engine work is to take the toolkit-free logic out of `JobBridge` (step 2), not to write a new runner. A second copy of it for the CLI is exactly the "two engines drift apart" risk the draft warned about.

## Decisions (defaults — change any of them before the step that depends on it)

| # | Question | Default | Why |
| --- | --- | --- | --- |
| D1 | How a script is named on the command line | `group/name`; a bare `name` when it is unique; `#id` always works | Names repeat across groups (Copy to makes that normal). An ambiguous name is an error that lists the candidates. |
| D2 | What agents may run | Only scripts and pipelines marked **Available to agents** (new flag, off for everything) | An MCP tool that runs scripts is code execution on this machine. |
| D3 | Does the flag gate the CLI too? | **No** — the CLI runs anything | Whoever has a terminal can already run the script directly; the flag guards the MCP door, which a prompt-injected agent can reach without a shell. |
| D4 | Parameters from an agent | A **preset by label**, or none. No free-text arguments over MCP in v1 | RYOS parameters are one free-text string plus named presets — there are no typed parameters to build a JSON schema from, and free text from an agent into a script that hands it to a shell is the main injection path. The CLI may pass `--params "…"`. |
| D5 | A pipeline's steps | An exposed pipeline runs all its steps, whatever their own flags | The steps are part of what was exposed. |
| D6 | The same item already running | Refused within one process; across processes (window + CLI) allowed in v1 | Cross-process detection needs a liveness check on `runs` rows; later, if it matters. |
| D7 | Launcher (detached) scripts | Released after `launcher_release_seconds`, as in the window; the CLI then returns ok | Same rule as the window. |
| D8 | Toasts | Off for CLI and MCP runs | Nobody is watching a toast for a run they started from a terminal or an agent. |
| D9 | Logging | A separate `ryos-cli.log` | Two processes must not both rotate `ryos.log`. |
| D10 | History | `trigger_source` = `cli` or `agent` | History already records every run; the column was made for this. |
| D11 | The window's cards after a CLI run | The CLI signals a running window to reload (new `RELOAD` verb on the single-instance socket) | Otherwise a card shows a stale last status until the next reload. |
| D12 | MCP in the Windows build | From source only in v1 (`uv run --extra mcp ryos mcp`); revisit at step 8 | Bundling the MCP SDK grows the download for a feature most users won't use. |
| D13 | Does Clone / Copy / import keep it? | Clone, Copy and Clone group keep it; **export leaves it out, so an import never grants it** | A copy within this database differs only in name, id and group. A file from elsewhere -- a colleague's group -- must not make scripts agent-runnable without its new owner deciding. |

## Rules for every step

- Follow `CLAUDE.md` and the `add-ryos-feature` workflow. In particular: top-level modules never import `ryos.qtui` or PySide6; worker threads never touch widgets; schema changes are a new `_MIGRATIONS` entry; `db.get()` and `list_pipeline_steps()` rows are not widened.
- **The CLI never imports Qt, never takes the single-instance lock, and never writes the run-at-login entry.** `__main__.main()` does all three today, so subcommands branch off before any of it.
- Each step is one reviewable commit, with the unit suite, ruff, mypy, `qt_smoke.py` and `session_smoke.py` green.
- `__version__` changes only at release (step 9); the maintainer names the version.

## Steps

### Step 1 — Decisions
Confirm or change D1–D12. **Done:** defaults taken (2026-10-07); revisit any one before the step that uses it.

### Step 2 — One toolkit-free job host
- **2a.** Move `JobBridge`'s toolkit-free logic into `ryos/jobhost.py`: the registry, queue and controller; `_launch` (worker thread, `mark_run`, launcher release); `run_script` / `run_pipeline`; the schedule sweep's launch. What it needs from a toolkit comes in as arguments — `call_later(seconds, fn)`, which must run `fn` on the pumping thread, and the controller's callbacks. `JobBridge` keeps the `QTimer`s and signals and delegates the rest. Pure refactor: the window behaves identically.
- **2b.** `ryos/headless.py`: a `HeadlessRunner` built on the host. One thread pumps and runs due `call_later` callbacks (no Qt, no extra threads touching the controller); it collects each run's output into a bounded ring buffer, finds scripts and pipelines by D1, stops runs, and waits with a timeout (`terminate_tree`). Toasts off (D8), `trigger_source` per D10.
- **Tests:** tiny scripts run through the headless runner — output, exit code, stop, timeout, a launcher released, a pipeline honouring a step's failure policy and retries, name resolution including the ambiguous case.
- **Done when:** tests green, `qt_smoke` and `session_smoke` unchanged.

### Step 3 — Exposure flag in the database
`_MIGRATIONS` v9: `agent_exposed INTEGER NOT NULL DEFAULT 0` on `scripts` and `pipelines`. `ScriptDB` methods to set it and to list exposed items (their own query; no row widening). Carried by Clone, Copy and Clone group; not exported, so never set by an import (D13). Test the upgrade with `tests/real_data_smoke.py --db` on an older backup.

### Step 4 — "Available to agents" in the window
A checkbox in the script dialog (rule in `scriptform.py`) and the pipeline editor; optionally a small badge on the card. **Done when** it survives a restart.

### Step 5 — CLI
`ryos list [--json]`, `ryos run <ref> [--preset P] [--params "…"] [--timeout S] [--json]`, `ryos pipeline <ref> [--timeout S] [--json]`. Streams output; `--json` prints one result (status, exit code, duration, output tail). Exit codes: the script's own for a run, and a reserved range for RYOS errors (not found, ambiguous, bad preset, timeout) so callers can tell them apart. Plain `ryos` still opens the window. After a run, `RELOAD` to a running window (D11).

### Step 6 — Console build
`setup_cxfreeze.py` gains a second `Executable`, `ryos-cli.exe`, with the console base (the window's exe uses `base="gui"`, which has no stdout). Checked by an extension of `tests/launch_smoke.py`.

### Step 7 — MCP server
`ryos mcp` over stdio with the official Python SDK (FastMCP), an optional extra `ryos[mcp]`. Tools: `list_scripts`, `list_pipelines` (exposed only; never `env_vars`), `run_script` / `run_pipeline` (return a `run_id` at once), `get_run(run_id, offset?)` with paged, capped output, `stop_run`. Script output is untrusted text: capped and paged, never interpreted. **Done when** Claude Code and Claude Desktop can list, run, poll and stop.

### Step 8 — Docs
README section, MCP config snippets for Claude Code and Claude Desktop, a tutorial page, `CLAUDE.md` and `docs/ARCHITECTURE.md` rows, D12 revisited.

### Step 9 — Release
Through the `release-ryos` skill, version named by the maintainer; an end-to-end run with a real agent first.

## Order

```
Step 2a ──► 2b ──► 5 ──► 6 ──┐
             │               ├──► 8 ──► 9
Step 3 ──► 4 └──► 7 ─────────┘
```

Steps 3–4 are independent of 2 and can go first or in between. 5 needs 2b; 7 needs 2b and 3. Don't release 5 or 7 before 2a is in — that is what keeps one engine.

## Status

| Step | State |
| --- | --- |
| 1 Decisions | defaults taken |
| 2a Job host | done (`42fb549`) |
| 2b Headless runner | done |
| 3 DB flag | done |
| 4 UI flag | done (card badge left for later) |
| 5 CLI | done |
| 6 Console build | — |
| 7 MCP | — |
| 8 Docs | — |
| 9 Release | — |
