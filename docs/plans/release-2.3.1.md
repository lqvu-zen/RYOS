# RYOS v2.3.1 — Plan for the week of 2026-10-12 (fixes after 2.3.0)

_Created 2026-10-12 by the secretary session from Vũ's agreed weekly plan. v2.3.0 shipped on 2026-10-09 (tag `v2.3.0`, `90157a2`). This plan is the planner's to refine. Each code step goes through the `ryos-*` agent team via its skill._

## Goals

1. Fix the two bugs reported against 2.2.0/2.3.0: **#26** (a pipeline gets stuck after a failing step) and **#27** (selecting several scripts or pipelines is broken).
2. Close the loose ends 2.3.0 left in its plan and docs.
3. Let users see who made RYOS and check that a download is the real one. RYOS isn't code-signed, so SmartScreen keeps saying "Unknown publisher".
4. Make a whole group available to agents in one go, and pick up new scripts and pipelines by running it again.
5. Fix what Vũ reported on 2026-10-13 while using 2.3.0: #29 (a freeze, and the log is hard to find) and #30 (Quick Run no longer adds a new script).
6. Ship **2.3.1**, the first release through the release-review gate.

## Who does what

| Step | Who | How |
|---|---|---|
| 1 Use 2.3.0 day to day | Vũ | Download `RYOS-windows-ai.zip` from the v2.3.0 release and use it on the real data |
| 2 Write up #27 | Vũ | Steps, expected, actual, which build, a screenshot |
| 3 Fix #26 | coding session | `/fix-ryos-bug` |
| 4 Fix #27 | coding session | `/fix-ryos-bug`, after step 2 |
| 5 Plan and docs loose ends | coding session | one small commit, no skill needed |
| 7 Who made it, and checking a download | coding session | `/add-ryos-feature` |
| 8 Expose a group | coding session | `/add-ryos-feature` |
| 9 Fix #29a: freeze when opening a pipeline's detail in full screen | coding session | `/fix-ryos-bug` |
| 10 #29b: make the app log easy to find | coding session | `/add-ryos-feature` |
| 11 Fix #30: Quick Run no longer adds a new script | coding session | `/fix-ryos-bug` |
| 12 #31: newest log tab first | coding session | `/add-ryos-feature` |
| 6 Release 2.3.1 | coding session + Vũ | `/release-ryos`; Vũ names the version |

## Steps

### 1 — Vũ moves to 2.3.0
**Done when** Vũ's everyday RYOS reports 2.3.0 (`ryos-cli --version`: Windows build with AI agents) and has been used on the real data, which is already at schema v10, without anything odd. Anything odd becomes a new issue.

### 2 — #27 gets a repro
**Done when** issue #27 has steps to reproduce, the expected and actual behaviour, and the build it was seen on. Until then step 4 waits.

### 3 — Fix #26: the pipeline stuck after a failing step
Reported 2026-10-08 (before 2.3.0) with a `bakeDataWin` step whose `.bat` ends with:

```bat
echo error: %error_level% received when making data
pause
exit /B %error_level%
```

The output shows `Status code: '1'`, the error line and `Press any key to continue . . .`, and then the pipeline does not move on.

Facts for the diagnosis (not a conclusion):
- `ryos/runner.py` already runs every script with `stdin=subprocess.DEVNULL` (issue #12), so `pause` should print its prompt and return at once.
- The report is about a **pipeline**, so suspect the step-failure path in `ryos/job_controller.py` / `ryos/pipelinesteps.py` (step policies), not only the runner.
- Check which version and download it was seen on, and whether it reproduces on 2.3.0.

**Done when** a regression test reproduces the hang on the old code and passes on the fix. A pipeline whose step exits 1 after `pause` then finishes according to its step policy (stops, or continues), with the right status in Run history. `qt_smoke.py` and `session_smoke.py` stay green.

### 4 — Fix #27: selecting several scripts or pipelines
**Needs** step 2.
**Done when** the repro from #27 no longer reproduces, a regression test (or a `session_smoke.py` check for select mode) guards it, and select mode's run-selected and bar text still behave (`ryos/selection.py`).

### 5 — Loose ends from 2.3.0 (one commit)
- `docs/plans/release-2.3.0.md`, Status: step 12 is "done; Claude Desktop and Claude Code connection to the exe tried by the maintainer on 2026-10-09 (passed)". Step 13 records what was actually run before the release, and "not run" for anything that wasn't.
- `docs/tutorial/13-command-line-and-agents.md`, wherever an environment variable is set: `set VAR=...` works only in Command Prompt; in PowerShell it is `$env:VAR = "..."`. (During the 2.3.0 test a PowerShell `set APPDATA=...` silently wrote test scripts into the real data.)

**Done when** both are committed.

### 7 — Who made RYOS, and how to check a download
_Added 2026-10-13. Vũ decided: no license and no code signing for now (see `claude/STATUS.md` in the project), so SmartScreen keeps saying "Unknown publisher". This step gives users other ways to check._

- **Publisher details in both exes.** In `setup_cxfreeze.py`, fill the Windows version information of `RYOS.exe` and `ryos-cli.exe`:
  - Company: **Zenitus (Lê Quang Vũ)**
  - Copyright: **© 2026 Lê Quang Vũ (Zenitus)**
  - Keep the product name, description and version as they are.

  Check which cx_Freeze fields map to Company and Copyright (`Executable(copyright=...)`, setup metadata). Confirm that the Vietnamese characters display correctly in *Properties → Details*.
- **The build's commit.** Write the short Git commit into `ryos/_build_info.py` at build time, like `VARIANT`. Show it in `ryos-cli --version` and in the bug report's environment, e.g. `RYOS 2.3.1 (Windows build with AI agents, 1a2b3c4)`.
- **"Check your download" in the docs.** Add it to the README, the release-notes template in `release-ryos`, and the tutorial's install page:
  - download only from `https://github.com/lqvu-zen/RYOS/releases`;
  - `Get-FileHash .\RYOS-windows-ai.zip -Algorithm SHA256` must match the line in that release's `SHA256SUMS.txt`;
  - *Properties → Details* shows Zenitus (Lê Quang Vũ);
  - "Unknown publisher" from SmartScreen is expected, because RYOS isn't code-signed. Choose *More info → Run anyway* only for a download that passed the check.
- **Release review.** Add to the release-review lineup check: both exes carry the Company and Copyright above, and `--version` names the commit the tag points at.

**Done when** a built `RYOS.exe` and `ryos-cli.exe` show the publisher details in *Properties → Details*, `ryos-cli --version` shows the commit, the "Check your download" section is in all three places, and the release-review lineup check includes the two new items.

### 8 — Expose a group (and refresh it)
_Added 2026-10-13 by Vũ's decision. It is option 1: exposing a group ticks the existing per-item **Available to agents** boxes of what is in the group **now**. There's no group-level flag and no schema change, and nothing becomes available later by being moved into a group._

- **`ryos-cli expose --group <group> on`.** Covers the group's scripts **and** pipelines.
  - It lists only what it would change: "Will make 2 available to agents: Tools/backup, Tools/sync (pipeline). 5 already are."
  - It asks once, unless `--yes` is given. Like `expose … on` today, it needs an interactive terminal or `--yes` (2.3.0 decision A2).
  - It exits 0 when there's nothing new ("All 7 in Tools are already available to agents").
- **Refresh = run it again.** The command is idempotent: a second run picks up only the scripts and pipelines added to the group since, and asks about just those. No separate refresh command or state is needed.
- **`ryos-cli expose --group <group> off`.** Turns all of them off. No question, since it only takes access away.
- **`ryos-cli list --group <group>`** (new filter). Shows what is in the group and what isn't available yet, so Vũ can see what a refresh would add.
- **The window: the same action in two places.**
  - Select mode: "Make available to agents", or "Stop", for the selected items.
  - A group tab's right-click menu: "Make all in this group available to agents…", which lists the new ones and asks, exactly like the CLI.

  Hidden in the `windows` (no-MCP) build, like the checkbox.
- **MCP never does this** (A2: agents never change the allow-list).
- An unknown group is refused with exit 125 and a list of the existing groups. The empty-group case says so.

**Done when** the tests in `tests/test_cli.py` show:
- the first run exposes everything in the group;
- a second run after adding a script and a pipeline asks about, and exposes, only those two;
- `off` clears them all;
- an unknown group gives 125;
- refusal without a terminal or `--yes`.

The window actions are also in `tests/session_smoke.py`, and the no-MCP build hides them.

### 9 — Fix #29a: the app freezes on a pipeline's detail in full screen
_Added 2026-10-13 from issue #29 (Vũ, on 2.3.0 Windows build with AI agents)._ In full-screen (maximised) mode, clicking a pipeline to watch its detail makes the app stick. Suspects:
- the maximised list + detail layout (`ryos/detail.py`, `ryos/qtui/detail.py`);
- the pipeline's step chips and output routing;
- work done on the UI thread for a large output.

Reproduce first, with the `run-ryos` driver off screen and with a long-output pipeline as well as a short one. The fix must not break the 2.3.1 #26 fix (`4e37723`).
**Done when** a regression check reproduces the freeze on the old code (a `session_smoke.py` or `qt_smoke.py` check that opens a pipeline's detail while maximised), it passes on the fix, and opening the detail stays responsive while the pipeline is running and after it has finished.

### 10 — #29b: make the app log easy to find
_Added 2026-10-13 from issue #29:_ "I can't find the app log to report the bug." The bug-report template already names `%APPDATA%\RYOS\logs\ryos.log`, but nothing in the app leads there.
- Add **Help → Open log folder** (or wherever the planner fits it, next to *Report a bug*) and `ryos-cli` support for it, e.g. `ryos-cli version` printing the log path.
- In *Report a bug*, show the log's path with a button that opens the folder, and keep the "have a look first: it can contain your script paths and output" warning.

**Done when** the log folder opens from the window in two clicks or fewer, the CLI prints the path, and the tutorial's troubleshooting section says where the log is.

### 11 — Fix #30: Quick Run no longer adds a new script
_Added 2026-10-13 from issue #30 (Vũ, on 2.3.0 Windows build with AI agents, compact layout)._ After a Quick Run of a file that isn't a script yet, older versions added it as a new script; 2.3.0 doesn't. Find the version where it stopped (`git log` / bisect over `ryos/quickrun*.py` and `ryos/qtui/quickrun.py`, between the tags), and whether it was a deliberate change. If it was deliberate, bring it back as the documented behaviour, or as a setting if the change had a reason.
**Done when** a regression test in `tests/test_ryos.py` (Quick Run rules are toolkit-free in `ryos/quickrun*.py`) shows a Quick Run of a new file adds it as a script, as before, and the compact and normal layouts both show it.

### 12 — #31: the newest log tab sits right after "All"
_Added 2026-10-13 from issue #31 (Vũ's suggestion). It's small; if it turns out not to be, move it to 2.4 and say so in the Status table._ When a script or pipeline starts, its tab in the output panel goes **right after "All"** instead of at the end, so the run just started is always in view. The alternative in the issue was scrolling the tab bar to the end on each run. The rule (where a new tab goes) lives in the toolkit-free `ryos/outputpanel.py`, and the window only draws it. A re-run of a script that already has a tab moves that tab to the front, not a duplicate.
**Done when** a unit test covers the order (new tab, re-run, several runs at once, a pipeline's step tabs keep their order inside the pipeline), and the tab bar shows the newest run without scrolling in both the normal and compact layouts.

### 6 — Release 2.3.1
**Needs** steps 3, 4, 5 and 7–12, plus green CI.
Run `/release-ryos`. Vũ names the version (suggested: 2.3.1, a patch release for fixes). The release-review gate must print `READY TO PUBLISH` before anything is pushed. Release notes name #26, #27, #29, #30 and #31.
**Done when** v2.3.1 is published with the four zips and `SHA256SUMS.txt`, and #26, #27, #29, #30 and #31 are closed with a link to the release.

## Order

Steps 3, 4 and 5 are done. Steps 7–12 are independent of each other and can start now; do the bug fixes (9 and 11) first, since Vũ hits them every day. Step 6, the release, comes last.

## Status

| Step | State |
| --- | --- |
| 1 Vũ on 2.3.0 | done: issues #29 and #30 were reported from 2.3.0 (Windows build with AI agents) |
| 2 #27 repro | not needed: #27 was diagnosed and fixed without it |
| 3 Fix #26 | done, `4e37723` (a step that leaves a process running no longer stalls its pipeline) |
| 4 Fix #27 | done, `257aa00` (select mode ticks pipelines too; clicking a row ticks it) |
| 5 Loose ends | done, `5d100ad` (CLI on throwaway data, per shell; the 2.3.0 plan records what was run) |
| 7 Publisher details and download check | — |
| 8 Expose a group | — |
| 9 Fix #29a freeze | — |
| 10 #29b log easy to find | — |
| 11 Fix #30 Quick Run | — |
| 12 #31 newest log tab first | — |
| 6 Release 2.3.1 | — |
