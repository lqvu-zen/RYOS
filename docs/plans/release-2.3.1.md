# RYOS v2.3.1 — Plan for the week of 2026-10-12 (fixes after 2.3.0)

_Created 2026-10-12 by the secretary session from Vũ's agreed weekly plan. v2.3.0 shipped on 2026-10-09 (tag `v2.3.0`, `90157a2`). This plan is the planner's to refine. Each code step goes through the `ryos-*` agent team via its skill._

## Goals

1. Fix the two bugs reported against 2.2.0/2.3.0: **#26** (a pipeline gets stuck after a failing step) and **#27** (selecting several scripts or pipelines is broken).
2. Close the loose ends 2.3.0 left in its plan and docs.
3. Ship **2.3.1**, the first release through the release-review gate.

## Who does what

| Step | Who | How |
|---|---|---|
| 1 Use 2.3.0 day to day | Vũ | Download `RYOS-windows-ai.zip` from the v2.3.0 release and use it on the real data |
| 2 Write up #27 | Vũ | Steps, expected, actual, which build, a screenshot |
| 3 Fix #26 | coding session | `/fix-ryos-bug` |
| 4 Fix #27 | coding session | `/fix-ryos-bug`, after step 2 |
| 5 Plan and docs loose ends | coding session | one small commit, no skill needed |
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

### 6 — Release 2.3.1
**Needs** steps 3, 4 and 5, plus green CI.
Run `/release-ryos`. Vũ names the version (suggested: 2.3.1, a patch release for fixes). The release-review gate must print `READY TO PUBLISH` before anything is pushed. Release notes name #26 and #27.
**Done when** v2.3.1 is published with the four zips and `SHA256SUMS.txt`, and #26 and #27 are closed with a link to the release.

## Order

```
Step 1 (Vũ) ─────────────────────────────── any time this week
Step 2 (Vũ) ──► Step 4 ──┐
Step 3 ──────────────────┼──► Step 6
Step 5 ──────────────────┘
```

Steps 3 and 5 can start now. Step 4 waits for step 2.

## Status

| Step | State |
| --- | --- |
| 1 Vũ on 2.3.0 | — |
| 2 #27 repro | — |
| 3 Fix #26 | — |
| 4 Fix #27 | waiting on 2 |
| 5 Loose ends | — |
| 6 Release 2.3.1 | — |
