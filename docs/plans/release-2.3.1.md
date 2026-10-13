# RYOS v2.3.1 — Plan for the week of 2026-10-12 (fixes after 2.3.0)

_Created 2026-10-12 by the secretary session from Vũ's agreed weekly plan. v2.3.0 shipped on 2026-10-09 (tag `v2.3.0`, `90157a2`). This plan is the planner's to refine. Each code step goes through the `ryos-*` agent team via its skill._

## Goals

1. Fix the two bugs reported against 2.2.0/2.3.0: **#26** (a pipeline gets stuck after a failing step) and **#27** (selecting several scripts or pipelines is broken).
2. Close the loose ends 2.3.0 left in its plan and docs.
3. Let users see who made RYOS and check that a download is the real one. RYOS isn't code-signed, so SmartScreen keeps saying "Unknown publisher".
4. Make a whole group available to agents in one go, and pick up new scripts and pipelines by running it again.
5. Fix what Vũ reported on 2026-10-13 while using 2.3.0: #29 (a freeze, and the log is hard to find) and #30 (Quick Run no longer adds a new script).
6. Stop "working on A breaks B" (user feedback, 2026-10-13): a behaviour map that every change is checked against.
7. A real test phase before every release: a release candidate Vũ uses for a few days, one release-check script as a hard gate, and a tester agent.
8. Ship **2.3.1**, the first release through the release-review gate and the new test phase.

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
| 13 Behaviour map, wired into the workflow | coding session + Vũ reviews | the agent team; Vũ reviews the map |
| 14 "Suggest a feature" next to "Report a bug" | coding session | `/add-ryos-feature` |
| 15 The release test phase (RC, release check, tester agent) | coding session; Vũ uses the RC | `/add-ryos-feature` for the script; agent file and skill edits by hand |
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
- `docs/archive/release-2.3.0.md`, Status: step 12 is "done; Claude Desktop and Claude Code connection to the exe tried by the maintainer on 2026-10-09 (passed)". Step 13 records what was actually run before the release, and "not run" for anything that wasn't.
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

### 13 — The behaviour map: stop "working on A breaks B"
_Added 2026-10-13 from user feedback: "Are you creating a design document? I keep seeing situations where working on A ends up breaking B."_ The history agrees:
- compact mode broke three times (#28, the outside-folder tag on compact rows, the empty box beside Run);
- select mode missed pipelines (#27);
- Quick Run lost "add as a new script" (#30);
- a copied script lost its star, highlight and presets;
- `CLAUDE.md` records widened rows breaking call sites three times.

`docs/ARCHITECTURE.md`, `docs/adr/` and `CLAUDE.md` say how the code is built. Nothing says **what must keep working, and everywhere it shows up**. Most behaviours appear in several places: normal rows, compact rows, favourite chips, the detail pane, select mode, scripts and pipelines, window and CLI. A change reaches one place, and the others break unseen.

**Work:**
1. **Write `docs/BEHAVIOUR.md`**, grouped by area (rows and cards, favourites, groups, select mode, Quick Run, pipelines, output panel, history, schedules, tray and window, CLI, MCP, import and export, settings and themes). Each entry has:
   - the behaviour in one line, as the user sees it;
   - **every surface** it appears on;
   - the test that guards it (file and test name), or **untested**.

   Build it from the code, the tests, the tutorial and closed issues. Start with the areas behind the regressions above. Vũ reviews the map before it's final.
2. **Wire it into the workflow** (`add-ryos-feature`, `fix-ryos-bug`, and the `ryos-designer` and `ryos-reviewer` agents):
   - the locator returns the map entries for the area;
   - the designer's plan lists every surface the change touches, from the map;
   - the reviewer checks each of those surfaces, not only the one in the task;
   - every bug fix adds or updates its entry, with its regression test;
   - a new feature adds its entry.
3. **Smoke both layouts.** `tests/session_smoke.py` today runs the normal layout only. Run it, or at least its rows, favourites and select-mode parts, in the **compact** layout too.
4. **Turn the untested entries into a backlog:** a short list at the end of the map. The most-used ones get checks in `session_smoke.py` now, as part of this step; the rest are listed for 2.4.

**Order:** do this right after the two bug fixes (steps 9 and 11) and before steps 7, 8, 10 and 12, so those features are built with the map. Steps 9 and 11 add their entries once it exists.
**Done when:**
- `docs/BEHAVIOUR.md` exists, covers every area above, and has been reviewed by Vũ;
- the skills and agent files use it as described;
- `session_smoke.py` passes in both layouts;
- each regression listed above has its entry and a test.

### 14 — "Suggest a feature…" next to "Report a bug…"
_Added 2026-10-13 by Vũ._ Users already send suggestions as plain issues (#31 starts with "Suggestion:"). Give them a button that does it properly, the same way *Report a bug…* works (`ryos/bugreport.py`):
- **Where:** right next to *Report a bug…*, everywhere that one appears (menu and button), with the same look. Placement follows the behaviour map (step 13).
- **What it does:** opens a **new GitHub issue in the browser, already filled in.** Nothing is sent from RYOS; the person reads it, writes, and submits it themselves, exactly like the bug report.
  - **Title:** `Suggestion: ` followed by an empty space to type into.
  - **Label:** `enhancement` (it already exists in the repo).
  - **Body:**
    - *What would you like RYOS to do?*
    - *What are you trying to get done, and how do you do it today?*
    - *Anything else* (screenshots, examples).
    - A short footer with the RYOS version and download only, e.g. `2.3.1 (Windows build with AI agents)`. No log hint, no OS details, no paths.
- **Wording:** menu label `Suggest a feature…`; tooltip "Suggest a feature — opens a new issue on GitHub, nothing is sent until you submit it"; and after opening, "Opened a suggestion in your browser — nothing is sent until you submit it."
- **Code:** the rules (label, title, body, URL) go in a toolkit-free module next to `bugreport.py`, sharing its URL builder and `MAX_URL` limit, with unit tests. The window only draws the button. Present in every Windows download, including the no-AI build.
- Add its entry to `docs/BEHAVIOUR.md` (both layouts, every place the bug-report button appears).

**Done when** unit tests cover the URL (title, label, body, version footer, length limit), the button shows next to *Report a bug…* in both the normal and compact layouts (checked in `session_smoke.py`), and clicking it opens a correctly filled issue page.

### 15 — A real test phase before every release
_Added 2026-10-13 by Vũ._ Before this step, every change ran unit, lint, types, `qt_smoke`, `session_smoke` and an Opus diff review, and `release-ryos` built, smoke-tested, zip-checked and release-reviewed. What leaked:
- **Nobody used the build before it shipped.** 2.3.0 was built and published in about an hour; #29 and #30 were found days later in normal use.
- **The real release check was optional.** 2.3.0's step 13 was a plan item, and parts of it weren't run.
- **Nobody tested the built app like a user**, around the changes.
- **Coverage was uneven:** smokes in one layout, and upgrade checks depending on whatever old database is on Vũ's PC.

**Work:**
1. **`tests/release_check.py`**, one script over all four zips in `dist/`, with throwaway data and nothing opening on the first screen. It covers:
   - `launch_smoke` for each download;
   - the CLI commands, including the management ones;
   - MCP over plain JSON-RPC (list, run, poll, stop) for the MCP builds, and the 125 refusal for `windows`;
   - `session_smoke` in **both** layouts;
   - **an upgrade from a fixture database of each past version.** Commit sanitised copies under `tests/fixtures/db/`, e.g. `v2.0.db` … `v2.3.db`, with no real paths;
   - a mixed install in both orders (agent then full app, and the reverse: same scripts, history and exposure);
   - the A3 "compatible from" guard.

   It prints a pass/fail report and exits non-zero on any failure.
2. **A release-candidate flow in `release-ryos`:**
   1. build;
   2. run `release_check.py` (**hard gate**);
   3. publish **`v<X.Y.Z>-rc<N>` as a GitHub pre-release.** The update check reads `/releases/latest`, which skips pre-releases, so users aren't notified;
   4. run the tester agent (item 3) on the RC zips;
   5. Vũ uses the RC on his real data, for at least one day;
   6. any fix means a new RC from step 1;
   7. once Vũ says so, **promote the same commit**: rebuild from the RC's commit with the final version, run `release_check.py` again, run the release review, then publish.
   - **Version handling:** `_parse_version` in `ryos/notifications.py` reads `2.3.1-rc1` as `2.3.1`, so an RC build would not see the final as newer. Make the comparison treat a pre-release as older than its final (with a unit test), or document that RC users swap the zip by hand. The first is preferred.
   - `__version__` for an RC is `X.Y.Z-rcN`. Update the "no `-dev` suffix" rule in `CLAUDE.md` to allow `-rcN` on RC builds only.
3. **The `ryos-tester` agent** (`.claude/agents/ryos-tester.md`; Sonnet, medium effort; tools Read, Grep, Glob, Bash). It gets the behaviour map (step 13), `git log <last-tag>..HEAD`, and the RC zips. For each change, it drives the **built** app off screen with the `run-ryos` driver, in both layouts and for each relevant download, and works through the user flows around the change, every surface the map lists, not just the changed line. It never edits code. It reports `PASS` / `FAIL` per flow, with screenshots for failures and exact steps to reproduce. Any `FAIL` blocks promotion.
4. **Vũ's manual checklist.** The release review lists only what no agent can check, e.g. the Claude Desktop and Claude Code connection, real data looking right, and the SmartScreen flow on a fresh download. It goes in the release's plan Status for Vũ to tick during the RC days.
5. **The escape rule**, in `CLAUDE.md` and the behaviour map: every bug found after a release gets one line, "should have been caught by …", and that check is added (test, map entry, or `release_check.py` case).

**Done when:**
- `release_check.py` passes on a fresh build of all four zips, and fails on a planted fault (e.g. a zip with MCP in `windows`, or a broken fixture upgrade);
- `release-ryos` describes and enforces the RC flow;
- the pre-release version comparison is fixed and tested;
- `ryos-tester` exists and has run once on a test RC;
- the escape rule is written down.

### 6 — Release 2.3.1
**Needs** steps 3, 4, 5 and 7–15, plus green CI.
Run `/release-ryos` with the new flow from step 15. Vũ names the version (suggested: 2.3.1, a patch release for fixes). The steps:
1. `release_check.py` must pass;
2. publish `v2.3.1-rc1` as a pre-release;
3. `ryos-tester` reports no `FAIL`;
4. Vũ uses the RC for at least a day and ticks his manual checklist;
5. promote the same commit to `v2.3.1`, where the release-review gate must print `READY TO PUBLISH` before anything is pushed. Release notes name #26, #27, #29, #30 and #31.
**Done when** v2.3.1 is published with the four zips and `SHA256SUMS.txt`, and #26, #27, #29, #30 and #31 are closed with a link to the release.

## Order

Steps 3, 4 and 5 are done. Order: the bug fixes 9 and 11 first (Vũ hits them every day), then 13 (the behaviour map), then 10 and 14 (both next to *Report a bug…*), 7, 8 and 12, which are built with the map. Then 15 (the test phase), and finally step 6, the release, through that phase.

## Status

| Step | State |
| --- | --- |
| 1 Vũ on 2.3.0 | done: issues #29 and #30 were reported from 2.3.0 (Windows build with AI agents) |
| 2 #27 repro | not needed: #27 was diagnosed and fixed without it |
| 3 Fix #26 | done, `4e37723` (a step that leaves a process running no longer stalls its pipeline) |
| 4 Fix #27 | done, `257aa00` (select mode ticks pipelines too; clicking a row ticks it) |
| 5 Loose ends | done, `5d100ad` (CLI on throwaway data, per shell; the 2.3.0 plan records what was run) |
| 7 Publisher details and download check | done: Company and Copyright on both exes (`setup(author=)`, `Executable(copyright=)`), the build's short commit (`-dirty` when tracked files changed) in `ryos/_build_info.py` and shown in `--version` and the bug report; "Check your download" in README, TUTORIAL and the release notes template; both lineup checks in `release-ryos` and `ryos-reviewer`; BEHAVIOUR CLI-13, TW-18, TW-27. Checked on a built `agent` `ryos-cli.exe` (Get-Item VersionInfo, `--version`, launch smoke); `windows` and `windows-ai` not built. Needs a human: Explorer Properties → Details. The "`--version` names the commit the tag points at" check cannot pass until step 15 commits the version bump before the build |
| 8 Expose a group | — |
| 9 Fix #29a freeze | done: the window drains run output in 50 ms slices and joins a run's lines (a chatty pipeline held it for 70 s in one turn); `qt_smoke` heavy-output check |
| 10 #29b log easy to find | done: Help → Open log folder; Report a bug opens the issue, then a dialog with the log's path, an Open log folder button and the look-first warning; `ryos-cli version` prints the log folder and files; tutorial 12 "If something goes wrong". Needs a human: Explorer really opens on a built exe |
| 11 Fix #30 Quick Run | done: the Qt port (2.0.0) dropped Tk's refresh after Quick Run registered a script; restored as `quickrun_actions.needs_refresh`, smoke-checked in compact, normal and maximised |
| 12 #31 newest log tab first | — |
| 13 Behaviour map | **waiting on Vũ's review of `docs/BEHAVIOUR.md`**. Written (266 entries, 16 areas); wired into both skills, the four agents and `CLAUDE.md`; `session_smoke` runs normal and compact (`--layout`, default both); 7 backlog entries now checked. Found two bugs: OP-15 "Clear output between runs" does nothing, GR-33 a scheduled outside run adds the note |
| 14 Suggest a feature | done: `ryos/suggestion.py` (shared `bugreport.new_issue_url`); lightbulb button left of the bug button and Help → Suggest a feature… above Report a bug…; BEHAVIOUR TW-15/TW-26; checked in `session_smoke` (both layouts) and `qt_smoke`. Needs a human: open the real GitHub page once (the `enhancement` label applies only if the person may label issues) |
| 15 Release test phase | — |
| 6 Release 2.3.1 | — |
