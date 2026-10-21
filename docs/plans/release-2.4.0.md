# RYOS v2.4.0 (working name): self-update, smarter runs, agents and pipelines, automation

_Created 2026-10-14 by the planner from `docs/plans/release-2.4.0-brief.md` (the secretary, 2026-10-13, from Vũ's decisions), after v2.3.1 shipped. Approved by Vũ 2026-10-14 ("all good": every planner recommendation accepted). Steps 31–36 added and step 29 amended 2026-10-19 from the improvement plan, approved by Vũ ("approve all the recommendations"). Step 37 added 2026-10-19 from Vũ's decision (red CI). Step 38 added 2026-10-19 from Vũ's decision (claim a step). This is the only plan after 2.3.1. The version number is Vũ's: "2.4.0" is a working name. Each code step goes through the `ryos-*` agent team via its skill, in a fresh conversation._

## Goals

1. Fix what the behaviour map found first: **OP-15** ("Clear output between runs" does nothing), **GR-33** (a scheduled outside run gets the note) and **SM-16** (starring or maximising leaves select mode).
2. **A. Self-update.** Staged and still zip-based: download, verify the hash and an Ed25519 signature, ask, swap folders, keep one `.previous` for rollback. The install path never changes. `release_check.py` covers it over each of the four downloads.
3. Close the behaviour map's **untested backlog**, so B, C and D are built with every surface guarded.
4. **B. Smarter runs:** failure patterns, time left, stats.
5. **C. Agents and pipelines:** agents read history and past output, and see a long run's progress (#32). The window shows runs started by the CLI or agents. Pipeline parameters, and values passed between steps.
6. **D. Automation:** secrets in Windows Credential Manager, then file triggers.
7. **Harden how the team works** (steps 31–36, 38, 40): enforce the safety rules in the harness, give the step loop a stop rule, make the plan an explicit graph, have each session claim its step, refuse a publish without a passing `release_check`, and check frozen builds and the window code in CI.
8. Ship **2.4** through the test phase: `release_check.py` hard gate, RC pre-release, `ryos-tester`, Vũ's checklist with no minimum time, then promote the same commit.

## Decisions

Fixed by Vũ (brief, 2026-10-13): **U1** no Windows code signing in 2.4 (leave room for a signing step); **U2** ask before applying ("Update ready — Restart to update", *Later*); **U3** an option turns automatic downloading off, the check stays; **U4** keep one old version (`.previous`); **U5** only Vũ holds the private key, with a backup, and a lost key means one manual update for everyone.

Accepted by Vũ 2026-10-14 (all planner recommendations, P1–P22):

| # | Question | Decision | Why |
|---|---|---|---|
| P1 | Ed25519 in the no-MCP `windows` build | A small pure-Python, verify-only Ed25519 in **every** download, tested against the RFC 8032 vectors. The designer confirms the Windows CNG point before ruling it out | `cryptography` comes only with the MCP SDK; CNG appears to have no Ed25519 signatures; one code path, adds kilobytes |
| P2 | Who signs, and what is signed | Vũ runs the signing tool himself; the session never sees the key. A new asset `SHA256SUMS.txt.sig` signs the SUMS **plus the version**. `SHA256SUMS.txt` stays byte-for-byte `sha256sum -c` compatible | Binding the version stops an old signed release being served as "latest". Zip names stay frozen |
| P3 | What runs the helper | The **new** build's `ryos-cli.exe apply-update`, from its verified, extracted copy in the updates folder. Rollback runs from a fresh copy of the installed build's folder. Never from a folder being swapped | A cx_Freeze exe can't start without its `lib/`; no toolchain for a tiny exe; one more unsigned binary for antivirus |
| P4 | Antivirus during the swap | No exclusions. Check the extracted tree against the zip's file list and sizes. Retry renames with backoff (~60 s). Keep a journal so a crash mid-swap is finished or undone at the next start. Any failure restores the old folder and the message names antivirus as a likely cause | Never leave half of each version |
| P5 | Where updates are staged | `%LOCALAPPDATA%\RYOS\updates\<version>\`, defined once in `settings.py`. Every harness redirects `LOCALAPPDATA` as it does `APPDATA` | Nothing redirects `LOCALAPPDATA` today |
| P6 | Testing self-update without the private key in a session | In the RC flow Vũ signs **before** `release_check`. While step 11 is built, **amended by Vũ 2026-10-19:** `release_check` copies each shipped build and swaps only `lib/ryos/_build_info.pyc` to carry the test key and a `TEST_UPDATES` mark (no build option, no extra builds); a marked build alone reads `RYOS_TEST_RELEASES_API`, only for `http://127.0.0.1`; the local source serves `v99.0.0`, so no version override. `build_release.py` and the release review refuse any zip that lacks Vũ's key or carries the mark | A runtime switch that adds trusted keys would be a hole |
| P7 | Pre-release channel | Options → "Offer release candidates (for testing)", off by default; reads `/releases` instead of `/releases/latest` | The only way rcN → rcN+1 goes through self-update for real on Vũ's PC |
| P8 | Early candidate after part A | Yes, step 12: a `-rc1` with A and the fixes, never promoted itself | Real use of the riskiest part for weeks |
| P9 | Failure patterns: where, and the common set | Per script. "Also use the common patterns (`error:`, `FAILED`, `Traceback`)" is a tick box, off by default | Existing scripts behave exactly as before |
| P10 | Where failure patterns and masking are matched | In the run's output reader thread (`runner.py`), before lines are logged or queued. The result travels on the done item or Job state; the window only draws | `runner.py` logs lines in the worker; a pump-side mask would leak to `ryos.log` |
| P11 | Time left | Median of the last 10 successful runs, shown from 3. Shown in the Running list, detail pane, Activity bar, tray tooltip and MCP `get_run`. Rows unchanged | Rows have no room (RC-14); agents need it for #32 |
| P12 | Where stats show | History dialog summary, detail pane, `ryos-cli history <item> --stats`. Not on rows | Reads existing history only |
| P13 | Keep each run's output | On by default for every run, capped per run (designer picks, ~10k lines), pruned with history retention (HI-05), Options switch. Secrets masked (step 25) | C1 can't answer "why did last night's run fail?" without it |
| P14 | #32 in the window | CLI and agent runs show while they run, in the Running list and Activity bar: who started them, step i/n, "quiet for 20 min", output viewable. Read-only (no Stop from the window) | The window hears of them only when they finish |
| P15 | C2's "on-failure step" | **Dropped: it exists** since v1.11.0 (`run_when='on_failure'`, PL-04, PL-06) | Don't rebuild a shipped feature |
| P16 | Pipeline parameters for unattended runs | Each parameter has a default. The window asks once (prefilled). The CLI takes `--param name=value`. Agents, schedules and triggers use the defaults; agents never pass free text | MCP-03 stays true |
| P17 | Passing a value between steps | A marked output line (designer picks the marker) becomes an environment variable for later steps. No text substitution into commands in 2.4 | Keeps step output out of command lines |
| P18 | Secrets: namespace, copies, export | Credential Manager target names namespaced by the data folder. A copy or clone refers to the same secret. Delete offers to remove only secrets nothing else uses. Exports carry variable **names**, never values. Set in the script dialog and `ryos-cli secret set` (hidden prompt), **never over MCP** | Credential Manager is per Windows user, not per data folder |
| P19 | File triggers: watcher and rules | A polling sweep in a toolkit-free module (like `schedule_runner.py`), driven by a timer in the window. "Settled" = size and mtime unchanged for 5 s. Rules: skip (default) or queue one. **"Run another" dropped** | It would be the first way to run one script twice at once (RC-10, SC-06) |
| P20 | What a trigger gives the script | `RYOS_TRIGGER_FILE` in the environment. Triggers are not exported (like schedules). A trigger never asks | Unattended, like a schedule |
| P21 | OP-15, GR-33, SM-16 | 2.4, steps 1–3 | A 2.3.2 costs a full test phase |
| P22 | Migration numbers with parallel worktrees | Numbered when the step merges. Every 2.4 migration is add-only, so `COMPATIBLE_FROM` stays 1 | `_MIGRATIONS` is one dict |

## Who does what

| Step | Who | How |
|---|---|---|
| 1 Fix OP-15 clear output between runs | coding session | `/fix-ryos-bug` |
| 2 Fix GR-33 scheduled outside run gets the note | coding session | `/fix-ryos-bug` |
| 3 Fix SM-16 starring or maximising leaves select mode | coding session | `/fix-ryos-bug` |
| 4 A1 Find and download the update | coding session (Opus, threading) | `/add-ryos-feature` |
| 5 A1 Background download and the setting | coding session | `/add-ryos-feature` |
| 6 A2 Signature check and signing tool | coding session (Opus) | `/add-ryos-feature` |
| 7 Vũ makes the signing key | Vũ | with step 6's tool, off the repo, with a backup |
| 8 A2 Signing in the release process | coding session (Opus) | `/add-ryos-feature`; skill and agent edits by hand |
| 9 A3 Apply and roll back: the helper | coding session (Opus) | `/add-ryos-feature` |
| 10 A3/A4 Restart to update, roll back, edge cases | coding session (Opus) | `/add-ryos-feature` |
| 11 A Self-update in release_check, and the docs | coding session (Opus, packaging) | `/add-ryos-feature` |
| 12 Early candidate after part A | coding session (High) + Vũ | `/release-ryos` part A only; Vũ names the version |
| 13 Backlog: checks without a window | coding session | `/add-ryos-feature` (tests and map); a failing check → `/fix-ryos-bug` |
| 14 Backlog: the pane, dialogs and menus | coding session | as 13 |
| 15 Backlog: every row surface | coding session | as 13 |
| 16 B1 Failure patterns: rules, outcome, history | coding session (Opus, DB) | `/add-ryos-feature` |
| 17 B1 Failure patterns: editor, highlights, CLI | coding session | `/add-ryos-feature` |
| 18 B2 Time left | coding session | `/add-ryos-feature` |
| 19 B3 Stats | coding session | `/add-ryos-feature` |
| 20 C1 Keep each run's output | coding session (Opus, DB) | `/add-ryos-feature` |
| 21 C1 + #32 Agents read history and logs, and see progress | coding session | `/add-ryos-feature` |
| 22 #32 CLI and agent runs show in the window | coding session (Opus, cross-process) | `/add-ryos-feature` |
| 23 C2 Pipeline parameters | coding session (Opus, DB) | `/add-ryos-feature` |
| 24 C2 Passing a value between steps | coding session (Opus, DB) | `/add-ryos-feature` |
| 25 D1 Secrets: store, inject, mask | coding session (Opus, security) | `/add-ryos-feature` |
| 26 D1 Secrets: dialog, CLI, delete, export | coding session (Opus, security) | `/add-ryos-feature` |
| 27 D2 File triggers: rules, storage, firing | coding session (Opus, DB + threading) | `/add-ryos-feature` |
| 28 D2 File triggers: dialog, badge, Up next | coding session | `/add-ryos-feature` |
| 29 The 2.4 release test phase | coding session (High) | `/add-ryos-feature` for `release_check.py`; tester and checklist by hand |
| 30 Release 2.4 | coding session (High) + Vũ | `/release-ryos`; Vũ names the version |
| 31 Harness: permissions, hooks and checks | coding session (Opus, security) + Vũ | `/add-ryos-feature`; Vũ approves the ask and deny lists |
| 32 Loop rules | coding session | `/add-ryos-feature`; skill and agent edits |
| 33 The plan as a graph | secretary + `ryos-planner` + Vũ | `/ryos-secretary`; docs only |
| 34 Frozen builds in CI | coding session (Opus, packaging) | `/add-ryos-feature` |
| 35 Tech-debt review of the Qt app | coding session (Opus, High) | the "Tech debt check-in" prompt; no code |
| 36 Type checks over the window, extract what you touch | the B, C and D coding sessions | inside their own steps |
| 37 Fix the qt-smoke crash on CI | coding session (Opus if the cause is in threads or Qt object lifetime) | `/fix-ryos-bug` |
| 38 Claim a step when you start | coding session | `/add-ryos-feature`; skill, hook and eval edits |
| 39 A Offer release candidates (P7) | coding session | `/add-ryos-feature` |
| 40 No publish without a passing release_check; a reproducible portable zip | coding session (Opus, packaging + harness) + Vũ | `/fix-ryos-bug`; Vũ approves the `guard.py` change |

Every session is Sonnet 5.5 Medium unless marked. "Opus" means the implementer is escalated to Opus at medium effort (A2, A3, D1, every DB migration, packaging, cross-process and threading work). Each step that adds a top-level module adds its row to `CLAUDE.md`'s Architecture table and `docs/ARCHITECTURE.md`.

## Steps

### 1 — Fix OP-15: "Clear output between runs" does nothing
_Found by the behaviour map (2.3.1 step 13); 2.4 by decision (P21)._ `auto_clear_output` is defined (`settings.py:64`, `settings_schema.py:131`) and read nowhere. Since #31 each run gets its own tab (OP-21), so "clear" needs a meaning. `session_smoke::step_output_options` already expects that, with the option on, the **All** tab holds only the newest run. The designer confirms that and says what happens to finished run tabs.
**Touches:** OP-15, OP-08, OP-12, OP-16 (the detail pane's Output tab), OP-21; surfaces W D.
**Done when:**
- `step_output_options` asserts the clearing instead of reporting a known bug, in both layouts;
- a unit test in `test_ryos::TestOutputRouting` covers the rule (option on and off, a run already going in another tab is not wiped);
- the maximised pane's Output tab behaves the same;
- OP-15 is updated, and § Escapes gets "OP-15 (v2.3.1): should have been caught by …; added …".

**Needs:** —

### 2 — Fix GR-33: a scheduled run of an outside script gets the outside note
_Found by the behaviour map._ The note is decided per controller, not per run: `JobController._base_notes` (`job_controller.py:216`, `:442`) is set once for the window (`qtui/jobs.py:62`), so a schedule launched through the window's host gets it. Make it depend on what started the run: window clicks note; schedule and startup runs (and step 27's triggers) don't.
**Touches:** GR-32, GR-33, GR-30, SC-05, SC-11, PL-05 (step notes); surfaces N C F D · Sc P, and the schedule path.
**Done when:**
- `session_smoke::step_scheduled_outside` asserts no note instead of a known bug, in both layouts;
- `test_ryos::TestBaseFolderNotes` covers schedule, startup and manual for a script and a pipeline step;
- a window-started outside run still notes (GR-32 green);
- GR-33 is updated, with its escape line.

**Needs:** —

### 3 — Fix SM-16: starring, or maximising with full rows, leaves select mode
_Backlog row marked "-> 2.4" (known since 2.3.0)._ The chain is `_set_favorite` → `_defer_reload` → `load_from_db` → `set_select_mode(False)`, and `set_workspace` reloads when rows are not compact. Keep the mode and the ticked (kind, id) across a reload. The exception is Delete selected, which still leaves the mode (SM-09).
**Touches:** SM-01–SM-10, SM-13, SM-16, FV-05, TW-20; surfaces S N C D · Sc P.
**Done when:**
- a `qt_smoke` check stars and unstars a ticked row, and maximises with full rows, and the mode and ticks survive, on N, C and D;
- Delete selected still leaves the mode;
- SM-16 is no longer "untested (known)", with an escape line "SM-16 (v2.3.0)".

**Needs:** —

### 4 — A1: find and download this download's update
_Brief, part A1._ Add a toolkit-free updates module that:
- picks this variant's asset (`buildinfo.DOWNLOADS`; `portable` never self-updates);
- downloads it and `SHA256SUMS.txt` into the updates folder (P5);
- resumes or restarts cleanly after an interruption;
- verifies the hash, and deletes a mismatch.

The network is passed in. Build on `notifications._fetch_latest_release`, but **don't widen its `(tag, url)` result**: it is unpacked at `notifications.py:101` and injected at `cli.py:503` and `qtui/main.py:118`. Add a fetch that also returns the assets. The pre-release channel (P7) is a parameter here.
**Touches:** TW-17, CLI-13; a new map area **17. Updates** (UP-01…).
**Done when:**
- tests against a local HTTP server on 127.0.0.1 (never GitHub) show the right asset for each of `windows`, `windows-ai` and `agent`, and none for `portable`;
- a wrong hash is rejected and the file deleted;
- a cut-off download resumes or restarts and ends verified;
- a missing asset or missing SUMS is refused with words;
- every test redirects `LOCALAPPDATA`;
- UP entries are added.

**Needs:** —
**Escalation:** background network work with files on disk: Opus at medium.

### 5 — A1: downloaded in the background, and the setting
_Brief, A1 and U3._ The window's update check (`MainWindow.check_for_updates`, off the UI thread through `MainThreadInvoker`, `qtui/shell.py:1737`) starts the download when the new setting allows it. `ryos-cli version --check` says whether an update is downloaded. The banner keeps its Download button until step 10 adds Restart.
**Touches:** TW-17, ST-01 (the new setting appears in the generated Options), ST-03, CLI-13, UP; surfaces W D, CLI.
**Done when:**
- with the setting off nothing downloads and the check still runs;
- the worker never touches a widget (`qt_smoke::check_updates_and_notify` extended, banner in normal, compact and maximised);
- the portable build shows today's notice;
- `test_cli::TestVersion` covers the new wording;
- UP and TW-17 are updated.

**Needs:** 4

### 6 — A2: the signature check and the signing tool
_Brief, part A2; P1, P2._ Add:
- a pure-Python, verify-only Ed25519 in a toolkit-free module, with the trusted public key **passed in**, so tests use a test key;
- the update's verification: SUMS signature, version bound in the signed message, then the zip's hash;
- `ryos-cli verify <zip>` for a zip downloaded by hand.

Add a signing tool under `tools/` (`new` / `sign`) that reads the private key from a path Vũ gives, never from the repo. Add a `.gitignore` guard.
**Touches:** UP, CLI-13, MCP-08 (the `windows` build still holds no MCP SDK and no `cryptography`: `build_release.problems_in` gains that check).
**Done when:**
- the RFC 8032 vectors pass;
- a tampered zip, a tampered SUMS, a missing signature, a wrong key and a signed **older** version are each refused with a clear message (unit tests, and `test_cli` for `verify`);
- UP entries are added.

**Needs:** —
**Escalation:** security: Opus at medium.

### 7 — Vũ makes the signing key
_Brief: needed before A2._ Vũ runs step 6's `new` on his own machine and keeps the private key off the repo and off CI, with a backup in a second place. He hands over only the public key.
**Done when:** the public key is in a message to the next session, and Vũ has read the key-lost note: a new key pair means one manual update for everyone.
**Needs:** 6

### 8 — A2: signing in the release process
_Brief, part A2._
- Embed Vũ's public key in the builds (`buildinfo` or `_build_info.py`, P6).
- `release-ryos` gets a **"Vũ signs"** step after the build and **before** `release_check` (P2, P6). Vũ runs the tool himself. `SHA256SUMS.txt.sig` joins both `gh release create` commands.
- `ryos-reviewer`'s lineup check verifies the signature with the build's own `ryos-cli verify`.
- "Check your download" (README, tutorial install page, the release-notes template) gains `ryos-cli verify`.
- The key-lost note goes in `docs/CONTRIBUTING.md` and `release-ryos`.

**Touches:** UP, CLI-13, TW-27 (lineup).
**Done when:**
- a `release_check::signature` case verifies all three frozen zips with each build's own `ryos-cli verify`, and fails on a planted wrong signature and on a zip carrying the test key;
- the skill and agent describe the step;
- the docs are updated.

**Needs:** 6, 7
**Escalation:** security and packaging: Opus at medium.

### 9 — A3: apply and roll back (the helper)
_Brief, part A3; P3, P4._ Add a toolkit-free swap plan with every file-system and process effect passed in. Wait for RYOS to exit, then extract beside the install, check the tree, rename to `<folder>.previous`, rename the new one into place, and restart. Keep a journal, so a crash at any step is finished or undone at the next start. Rollback swaps back. The hidden `ryos-cli apply-update` runs it (P3).
Traps:
- renaming the install folder needs write access to its **parent**;
- Windows refuses to rename a folder while a file inside it is open, so the helper never runs from either folder;
- the single-instance socket (TW-06) must be released before the restart.

**Touches:** UP, TW-06, TW-16 (the run-at-login path is unchanged), CLI-11 (no lock or registry from the CLI).
**Done when:**
- tests on real temporary folders show an update and a rollback, with the exe path unchanged;
- a failure injected at **each** step (extract, check, either rename, restart; a locked file; a missing extracted file) leaves a working RYOS, old or new, never half of each;
- a journal left by a crash is finished or undone;
- UP entries are added.

**Needs:** 4, 6
**Escalation:** file swap, process control: Opus at medium.

### 10 — A3/A4: Restart to update, roll back, and the edge cases
_Brief, A3 and A4; U2, U4._ In the window, the banner reads "Update ready — Restart to update" with *Later*, plus a Help entry to roll back. The command line gets `ryos-cli update` and `update --rollback`, which serves RYOS Agent. Edge cases, each in the toolkit-free rules:
- runs active or due → ask, or wait for the end;
- `ryos-cli.exe mcp` held open → say so, and offer to apply at the next start;
- `portable` → never; today's notice;
- the folder or its parent not writable → say so and open the release page;
- rollback across a raised `compatible_from` → warn, never silently.

**Touches:** TW-05 (quit with jobs), TW-15 (the Help menu list changes), TW-17, TW-19, CLI-13, CLI-14, MCP-07/08, UP; surfaces W D T CLI.
**Done when:**
- each edge case has a unit test;
- the banner states and the Help entry are checked by `qt_smoke` in normal, compact and maximised;
- `test_cli` covers `update` and `--rollback` refusals;
- TW-15 is updated, with UP entries for each case.

**Needs:** 5, 9
**Escalation:** Opus at medium.

### 11 — A: self-update in release_check, and the docs
_Brief: a release_check case over each of the four downloads._ Cases on throwaway data, served from a local signed source (P6):
- `windows`, `windows-ai` and `agent` each update and roll back, with the exe path unchanged, and scripts, history and agent exposure intact;
- `ryos-cli` and MCP still answer after the swap;
- a forced failure (a locked file) leaves the old build working;
- `portable` refuses and keeps the notice.

Docs: the tutorial gets "Updating and rolling back"; README; a release-notes line saying 2.3.x users need one manual update to reach 2.4.
**Touches:** UP, DB-07 (mixed installs), TW-19; `release_check` cases.
**Done when:**
- the cases pass on a fresh `build_release.py` build and fail on a planted fault (an unsigned zip; a helper that dies mid-swap);
- the docs are in.

**Needs:** 8, 10
**Escalation:** packaging: Opus at medium.

### 12 — Early candidate after part A (P8)
_Planner proposal, accepted by Vũ._ `/release-ryos` part A (A1–A8) only, for the commit after steps 1–11. Vũ names the version and installs it by hand (the last manual update). With "Offer release candidates" on (P7), every later candidate reaches him through self-update. It is never promoted itself; step 30 promotes the final candidate.
**Done when:**
- `release_check` passed, including step 11's cases;
- the RC is published as a pre-release, signed;
- `ryos-tester` PASS on the update flow;
- Vũ runs it.

**Needs:** 1–11, 37 (green CI), 38, 39
**Gate:** Vũ names the version, installs the candidate by hand and runs it.

### 13 — Backlog: checks without a window
_Behaviour map backlog._
- GR-24: Copy to leaves the schedule behind (`TestCopyBetweenGroups`).
- PL-16: a released launcher's output still reaches its tab (`follow_leftovers`).
- ST-13: the log options.
- TW-16: Start with Windows, through the injected startup object.
- CLI-05: Ctrl+C exits 130 (a real console interrupt on Windows).
- TW-27: the built exe's version resource, read by a `release_check` case.

**Done when:**
- each entry names its test and leaves the backlog table;
- a check that finds a bug is reported as a `/fix-ryos-bug`, not hidden.

**Needs:** —

### 14 — Backlog: the pane, dialogs and menus
_Behaviour map backlog._
- FV-13: the pane's star.
- SC-14: the pane's Schedule…
- RC-35: the pane's Edit, star, three dots and Schedule.
- QR-13: the bar's reaction to its options.
- IE-05: Replace through the window.
- TW-13: the hint's links.
- TW-15: the Options menu.
- OP-21 on D.
- OP-05 on N.

**Done when:**
- each has a `qt_smoke` or `session_smoke` check, in both layouts where it applies;
- the backlog rows are removed.

**Needs:** 3

### 15 — Backlog: every row surface
_Behaviour map, "guarded on some surfaces only"._
- Real clicks on Run and star on F and D (RC-03, RC-09, RC-10, FV-05).
- Select mode on C and D with a search active, and SM-14 on All and D (SM-13).
- The keyboard on C and D (RC-29).
- Menu actions on C, F and D (RC-20–25).
- Drag on C and D (GR-14, GR-15).
- GR-30 from a chip and from the pane.

**Done when:**
- `session_smoke` or `qt_smoke` covers each listed surface;
- the "Guarded on some surfaces only" table is empty or says why a row stays.

**Needs:** 3

### 16 — B1: failure patterns: rules, outcome, history
_Brief, part B1; P9, P10._ Per-script regex rules in a new table (`_MIGRATIONS`, add-only). Matching happens in the reader thread (`runner.py` `_forward_output`). Status there is decided by the return code alone (`runner.py:156`), and the done item's tuple shape is pinned by exact-equality tests (`runner.py:105–107`). A run failed by a rule records which rule and which line, in a new `runs` column read through a **new** accessor. `list_runs` is pinned at 11 (`TestRowWidthsArePinned`). A pipeline's step policy treats it as a failure, and MCP `get_run` reports the reason.
**Touches:** HI-01, HI-03, PL-04, PL-06, PL-18, MCP-04, CLI-04, DB-01, DB-02; surfaces N C F D CLI MCP · Sc P.
**Done when:**
- a script that exits 0 but prints a matching line is recorded as failed with the line shown, from the window, the CLI and MCP;
- a pipeline stops or continues by its policy;
- the migration upgrades every fixture (`TestFixtureUpgrades`) and changes no existing outcome;
- HI and PL entries are updated.

**Needs:** 14, 15 (rows, the pane or the Running list; added 2026-10-19)
**Escalation:** DB and threading: Opus at medium.

### 17 — B1: failure patterns: editor, highlights, CLI
_Brief, part B1._ The script dialog edits the rules and the common-set tick box. The output panel highlights error and warning lines in every theme. `ryos-cli edit <script> --fail-on REGEX` (and removal) for RYOS Agent users. A bad regex is refused in words.
**Touches:** PR-05/PR-08 (the script dialog), OP-09, OP-10, ST-06, CLI-10, RC-24 and GR-18 (clone and copy carry the rules), IE-02 (export round-trip).
**Done when:**
- the dialog round-trips the rules (`qt_smoke::check_script_dialog`);
- highlights are legible in every shipped theme (`TestQtStylesheet`);
- clone, copy and export keep the rules;
- `test_cli` covers `--fail-on`.

**Needs:** 16, 14, 15 (rows, the pane or the Running list; added 2026-10-19)

### 18 — B2: time left
_Brief, part B2; P11._ A toolkit-free estimate from history: median of the last 10 successful runs, shown from 3, with "taking longer than usual" past it. Surfaces: the Running list and status bar, the detail pane, the Activity bar, the tray tooltip, MCP `get_run`.
**Touches:** OP-01, TW-23, TW-03, RC-12 (rows unchanged), MCP-04.
**Done when:**
- unit tests show it appears after enough runs and not before, stays sensible past the median, and ignores failed and stopped runs;
- it is drawn in normal, compact and maximised, and in the tray tooltip;
- new OP and TW entries are added.

**Needs:** 14, 15 (rows, the pane or the Running list; added 2026-10-19)

### 19 — B3: stats
_Brief, part B3; P12._ A toolkit-free module over existing history: success rate, duration trend, and the pipeline step that fails most. Shown in the History dialog's summary (HI-03), the detail pane, and `ryos-cli history <item> --stats`.
**Touches:** HI-03, HI-08, HI-09, TW-22.
**Done when:**
- the numbers match a hand count on fixture history (unit test);
- shown in normal, compact and maximised;
- `test_cli` covers `--stats`;
- HI entries are added.

**Needs:** 14, 15 (rows, the pane or the Running list; added 2026-10-19)

### 20 — C1: keep each run's output
_Needed by C1 and #32; P13._ Every run's output is written to `%APPDATA%\RYOS\runs\` as it arrives, capped and pruned with history retention. A history row links to it by a key known **at start**: `runs` rows are written only at completion (`db.py:115`), so this goes through a migration and a new accessor. The window, CLI and MCP share the writer through `JobHost`. Off in Options stops writing.
**Touches:** HI-05, HI-06, HI-07 (a failing write never breaks the run), OP-06, CLI-15, ST-01, DB-01, DB-02.
**Done when:**
- a run from each source leaves its output on disk, up to the cap;
- pruning removes it with its row;
- a failing disk write doesn't break the run;
- the migration upgrades every fixture;
- HI entries are added.

**Needs:** —
**Escalation:** DB and threading: Opus at medium.

### 21 — C1 + #32: agents read history and logs, and see a run's progress
_Brief, part C1; issue #32 (a long pipeline looked hung to Claude)._ Read-only MCP tools:
- list past runs, filtered by script or pipeline, result and time;
- read a past run's output in pages, like `get_run`.

Both are limited to items **Available to agents**, and MCP still never changes the allow-list. For #32, `get_run` adds each step's state, the current step i/n and name, seconds since the last output, and the usual duration (step 18). Past runs use the history id. `get_run`'s `run_id` is the in-process job id, forgotten after `KEEP_RUNS` (`agenttools.py:38`, `:126`), so keep the two id spaces distinct and named. Update the pinned tool lists (`test_mcpserver.py:84`, `release_check.py:60`).
**Touches:** MCP-01, MCP-04, MCP-05, MCP-07 (no longer six tools), HI-02, PL-08.
**Done when:**
- `test_agenttools` and `test_mcpserver` show "why did last night's run of X fail?" answered from the stored output;
- a run of an unavailable item is refused as "not found";
- a pipeline in progress reports its steps and quiet time;
- the MCP entries are updated.

**Needs:** 20 (18 for the usual duration)

### 22 — #32: CLI and agent runs show in the window
_Issue #32, owner's comment "can we have anything to show in the RYOS app?"; P14._ Runs started by `ryos-cli` or an agent appear in the window's Running list and Activity bar while they run. Each shows CLI or Agent, step i/n, elapsed and "quiet for N min", and its output can be read from the store (step 20). Read-only. Today the window hears only at the end (`mcpserver.py:154`, `cli.py:467` send RELOAD). The designer picks how the window learns of a start (a new single-instance verb plus a live record), and a run whose process died must not show forever.
**Touches:** OP-01, TW-23, TW-03 (tray), RC-12, CLI-12, MCP-06; surfaces R D T W N C.
**Done when:**
- a `qt_smoke` check runs a real CLI script and an MCP-style run beside the window and sees them listed, with progress, in normal, compact and maximised;
- they leave the list when they end, or when their process dies;
- new OP and TW entries are added.

**Needs:** 20, 14, 15 (rows, the pane or the Running list; added 2026-10-19)
**Escalation:** cross-process and threading: Opus at medium.

### 23 — C2: pipeline parameters
_Brief, part C2; P16._ Named parameters with defaults on a pipeline (`_MIGRATIONS`, new accessor; `list_pipeline_steps` is pinned at 14). The editor declares them, the window asks once at start (prefilled), and the steps receive them. CLI: `pipeline --param name=value`. Agents, schedules and triggers use the defaults.
**Touches:** PL-01, PL-02, PL-05, PL-20, PL-24, CLI-08, MCP-03, IE-02, GR-19, RC-24 (clone and copy carry them), DB-01, DB-02.
**Done when:**
- unit tests cover the defaults and the once-only ask;
- `qt_smoke::check_pipeline_editor` covers the editor;
- `test_headless` and `test_cli` cover `--param`;
- an agent run uses the defaults;
- every existing pipeline runs exactly as before (fixture upgrade plus `TestJobController`);
- PL entries are added.

**Needs:** 14, 15 (rows, the pane or the Running list; added 2026-10-19)
**Escalation:** DB: Opus at medium.

### 24 — C2: passing a value between steps
_Brief, part C2; P17._ A marked line in a step's output sets a value, and later steps receive it as an environment variable. The editor shows which steps set and use what. Parallel steps (PL-03, PL-09) must have a defined order: the last one to finish wins, or the designer says otherwise.
**Touches:** PL-03, PL-05, PL-08, PL-09, PL-20, CLI-08, MCP-04.
**Done when:**
- a three-step pipeline passes a path from step 1 to step 3 in the window, the CLI and MCP;
- the marker line still shows in the output;
- an unset value is empty, not an error;
- PL entries are added.

**Needs:** 23
**Escalation:** if it adds a column: Opus at medium.

### 25 — D1: secrets: store, inject, mask
_Brief, part D1; P10, P18._ A toolkit-free module over Credential Manager (ctypes `CredRead/Write/Delete/EnumerateW`, passed in; no new dependency). Name it `credentials.py`, not `secrets.py`, to stay clear of the stdlib module. Target names are namespaced by the data folder. Script references go in a new table (`_MIGRATIONS`). Values reach the process environment at launch (`build_run_spec`). Printed values are masked in the reader thread **before** `runner.py` logs a line (`runner.py:167`, `:207`) and before the output store (step 20) and the queue.
**Touches:** PR-10, PL-20, OP-09, HI-01, ST-13, CLI-04, MCP-04, MCP-05, RC-26, DB-01.
**Done when:**
- a secret reaches a script from the window, the CLI and MCP;
- tests grep the parameters, `runs`, `ryos.log` (with "Log script output too" on), the output store, MCP output and the CLI output, and never find the value;
- tests use a fake store, or a namespaced throwaway target that they remove;
- SE entries are added in a new map area **18. Secrets**.

**Needs:** 20
**Escalation:** security: Opus at medium.

### 26 — D1: secrets: dialog, CLI, delete, export
_Brief, part D1; P18._
- The script dialog sets, replaces and removes a secret, and never shows a value back.
- Deleting a script offers to delete the secrets nothing else uses.
- Clone and copy refer to the same secret.
- An export carries names, never values; an import shows what is missing.
- `ryos-cli secret set|remove|list <script>`, with the value read at a hidden prompt, never as an argument.
- Never over MCP.

**Touches:** PR-05, PR-08, RC-24, RC-25, GR-05, GR-18, IE-02, IE-03, CLI-09, CLI-10, SE.
**Done when:**
- an export file is grepped and holds no value;
- the delete prompt is unit-tested and smoke-checked in both layouts;
- `test_cli` covers `secret`;
- the MCP tool list is unchanged.

**Needs:** 25, 14, 15 (rows, the pane or the Running list; added 2026-10-19)
**Escalation:** security: Opus at medium.

### 27 — D2: file triggers: rules, storage, firing
_Brief, part D2; P19, P20._ A toolkit-free rules module covers settling, a burst, and skip or queue-one, with the clock and the folder lister passed in. A sweep module copies `schedule_runner.run_due`'s shape (`schedule_runner.py:53`). A `triggers` table goes in `_MIGRATIONS`. Add a `SOURCE_TRIGGER` source and the word "Trigger" in `history.py`'s `_SOURCE_WORD`. Deletes cascade (`db._forget_scripts`). There is no outside note (step 2's rule) and no question. Triggers run only while the window or tray runs, with a timer in `qtui`.
**Touches:** HI-02, SC-06 (never stack), RC-26, SC-12, OP-02, GR-33, DB-01; a new map area **19. Triggers**.
**Done when:**
- unit tests show a dropped file fires once, a slow copy fires once at the end, and a burst follows the rule;
- triggers survive a restart (`session_smoke::step_restart`);
- a run is recorded as Trigger;
- the migration upgrades every fixture;
- TR entries are added.

**Needs:** 2, 25 (secrets before triggers)
**Escalation:** DB and threading: Opus at medium.

### 28 — D2: file triggers: dialog, badge, Up next
_Brief, part D2._ A dialog to add, edit and remove a trigger. Where it is reached is the designer's call: a new row-menu entry changes RC-20's pinned order (`TestCardMenu::test_script_menu_order`), so the schedule dialog is an alternative. A TRIGGER badge goes on full rows (RC-16), and the Activity bar says what is watched.
**Touches:** RC-16, RC-20, SC-10, SC-13, TW-23, GR-24 (a copy leaves its trigger), TR.
**Done when:**
- `qt_smoke` covers the dialog;
- the badge shows on full rows and not on compact rows;
- `session_smoke` drops a file and sees the run, in both layouts;
- RC and TR entries are updated.

**Needs:** 27, 14, 15 (rows, the pane or the Running list; added 2026-10-19)

### 29 — The 2.4 release test phase
_Standing rule: every release goes through the test phase._ New `release_check.py` cases on each built download:
- B1, a rule fails a run through `ryos-cli`;
- C1, `list_runs` and past output over plain JSON-RPC for `windows-ai` and `agent`;
- the CLI-run listing in `windows`;
- D1, a masked secret through the CLI, in a namespaced target that is removed afterwards;
- `session_smoke` with a trigger in both layouts.

The `ryos-tester` brief covers the update flow. Vũ's checklist adds:
- two real updates in a row from GitHub through the app, RC to RC (for example rc1 → rc2 → rc3), in the window build and with RYOS Agent's `ryos-cli update` (amended 2026-10-19: once 2.4 ships, a bug in its downloader or signature check can only be fixed by a manual update);
- a rollback;
- the swap with Defender's real-time protection on;
- the update while Claude holds `ryos-cli mcp` open;
- "why did last night's run fail?" from Claude Desktop;
- the secret in the Windows Credential Manager UI, gone after delete;
- a slow copy from USB or a network share into a watched folder.

**Done when:** `release_check.py` passes on a fresh build of all four zips and fails on a planted fault for each new case, and the checklist, including the two RC-to-RC updates, is in the Status table.
**Needs:** 11, 13–28, 37, 38, 39, 40
**Gate:** Vũ ticks the checklist.

### 30 — Release 2.4
**Needs:** 29, green CI.
**Gate:** Vũ names the version and confirms each "needs a human" item before publishing.
`/release-ryos`, and **Vũ names the version**. The order: build, Vũ signs, `release_check`, an RC pre-release, `ryos-tester` PASS, Vũ's checklist ticked, then promote the same commit with the release review printing `READY TO PUBLISH`. The release notes say 2.3.x users update by hand once, and name #32.
**Done when:**
- the release is published with the four zips, `SHA256SUMS.txt` and `SHA256SUMS.txt.sig`;
- #32 is closed with a link;
- the new schema's fixture is added (`make_fixtures.py`, `release-ryos` B7);
- `dist/` is cleared;
- `release-2.4.0.md` and `release-2.4.0-brief.md` are moved to `docs/archive/` with their links fixed.

### 31 — Harness: permissions, hooks and checks
_Added 2026-10-19 from Vũ's decision (the improvement plan, "Harness")._ The rules that protect a release, Vũ's data and the secretary's edits live only in skills and `CLAUDE.md`, and two have already been broken: a test wrote into the real `%APPDATA%\RYOS` on 10-09, and a secretary edit was reverted on 10-13. `.claude/settings.json` holds 162 allow rules, saved one click at a time: 23 point at scratch folders of finished sessions and 11 are one-off `sed -i` edits. It has no `ask` or `deny` rules, no `env` block and no hooks. Some allows are wider than the skills permit: `gh release *`, `uv run *`, `xargs -r git checkout --`, `Read(//c/Users/Admin/.claude/**)` (Claude's own sign-in files) and `Read(//c/Users/Admin/Downloads/**)`.

Fixed by Vũ:
- `ask` for `gh release create`, `edit` and `delete`, and for `git push --force`;
- `deny` for `git checkout --`, `git restore` and `git reset --hard` on `docs/STATUS.md` and `docs/plans/`, and for reading or writing the signing-key folder and `*.pem`, `*.key`, `*.p8` files;
- an `env` block for `PYTHONIOENCODING=utf-8`, `RYOS_NO_TOASTS=1` and `RYOS_NO_REGISTRY=1`;
- a `PreToolUse` hook that refuses a command writing into the real `%APPDATA%\RYOS`;
- a `SessionStart` hook that prints the branch, uncommitted files, CI on HEAD and the next open step of the current plan;
- two CI checks instead of hooks, because CI also sees commits made outside Claude: `__version__` changes only in a commit titled `Release candidate …` or `Release …`, and no new comment lines in changed code under `ryos/`.

The hooks run on Vũ's Windows setup; the designer picks their language (Python through `uv` is already everywhere).
**Files:** `.claude/settings.json`, `.claude/hooks/` (new), `.github/workflows/ci.yml`, `tools/` (the two checks), `docs/BEHAVIOUR.md` (§ Harness escapes), `CLAUDE.md` (one paragraph on the harness).
**Done when:**
- the allow list holds only stable patterns (tests, smokes, ruff, mypy, the `run-ryos` and audit drivers, `uv run python tests/*`), with no scratch paths, one-off edits, `.claude` reads beyond the skills folder, or Downloads read;
- every command `add-ryos-feature`, `fix-ryos-bug`, `run-ryos`, `review-ryos-ui`, `ryos-tutorial-generator` and the `ryos-*` agents run still runs without a prompt, and `release-ryos`'s `gh release` calls ask;
- the hook script is tested with a refused command (a write into the real data folder, a read of the key folder) and an allowed one (a throwaway `APPDATA`);
- each CI check fails a planted commit and passes a clean one;
- `docs/BEHAVIOUR.md` has a **Harness escapes** list with the 10-09 and 10-13 incidents, and the rule: a session that breaks a process rule adds the hook or deny rule that would have stopped it.

**Needs:** —
**Gate:** Vũ approves the final `ask` and `deny` lists before the commit; they change what every session may do.
**Escalation:** security: Opus at medium.

### 32 — Loop rules: a stop rule, CI in the loop, one continue prompt
_Added 2026-10-19 from Vũ's decision (the improvement plan, "Loops")._ The implementer fixes "until clean" with no limit, only `release-ryos` checks CI, and the continue prompt in `docs/STATUS.md` still names `release-2.3.1.md`. Only `add-ryos-feature` has behaviour evals.
**Files:** `.claude/skills/add-ryos-feature/SKILL.md`, `.claude/skills/fix-ryos-bug/SKILL.md`, `.claude/agents/ryos-implementer.md`, `.claude/skills/*/evals/`, `docs/PROMPTS.md`, `docs/MCP_CLEAN_TEST.md` (staged uncommitted by the secretary on 2026-10-19).
**Done when:**
- the implementer stops after two fix rounds following the first run and reports what is still red; a reviewer BLOCKERS verdict gets one more round, then the skill stops and reports to Vũ;
- both coding skills stop at a step's `**Gate:**` line and say what Vũ has to do;
- both coding skills check CI on HEAD before starting, and after pushing watch the run (`gh run watch --exit-status`); a red run makes the fix the next step;
- `docs/PROMPTS.md`'s continue prompt is the one below, and names no plan file;
- `docs/MCP_CLEAN_TEST.md` is committed as the manual check against real Claude Desktop and Claude Code (what `release_check`'s plain JSON-RPC can't show), brought up to date (its title and the `--version` line name the current release), and `docs/PROMPTS.md` points at it instead of the claude.ai project;
- `fix-ryos-bug` gains behaviour evals; `release-ryos` gains at least three (stops on a failed `release_check`, waits for the version number, waits for Vũ's signature); `ryos-secretary` gains at least two (never edits code, never pushes).

> Read docs/STATUS.md to find the current plan, then continue with its next open step in Order. Update the Status table when it's done.

**Needs:** 31 (the `SessionStart` hook and the `ask` rules).

### 33 — The plan as a graph: Files lines and the parallel lanes
_Added 2026-10-19 from Vũ's decision (the improvement plan, "Graphs")._ The secretary added the `**Gate:**` lines (12, 29, 30, 31), the 13–15 Needs on the steps that change rows, the pane or the Running list, and the merge rules ("Parallel lanes and merging", below). What remains needs the code: a `**Files:**` line for each open step, so the lanes' collisions are visible before B and C start. Known hot spots: `ryos/db.py` `_MIGRATIONS` (16, 20, 23, 24, 27), `ryos/qtui/shell.py` (3,475 lines at `ef7600d`), `docs/BEHAVIOUR.md` and this plan's Status table.
**Who:** the secretary with `ryos-planner`; docs only.
**Done when:**
- steps 11 and 13–30 each have a `**Files:**` line checked against the code;
- "Parallel lanes and merging" lists which B and C steps share files, and proposes which may run in parallel;
- Vũ decides parallel or in sequence, and the Order says which.

**Needs:** —
**Gate:** Vũ decides parallel or in sequence.

### 34 — Frozen builds in CI
_Added 2026-10-19 from Vũ's decision (the improvement plan, "Code and test health")._ The four downloads are built and checked only on Vũ's PC, by `release-ryos`. A Windows CI job that runs `build_release.py` and `release_check.py` finds packaging faults before a candidate. The signature case needs Vũ's key, so the designer proposes either a build carrying the test key (`tests/ed25519_signer.py`) or skipping that one case in CI with the reason printed. `release_check` on Vũ's PC stays the release gate.
**Files:** `.github/workflows/` (a new job or workflow), `tests/release_check.py` (a CI mode, if needed), `build_release.py` (only if the test-key build needs it).
**Done when:**
- a `workflow_dispatch` and nightly Windows job builds all four zips and runs `release_check.py`;
- the signature case is handled as the designer proposed, and the job says so;
- a planted packaging fault (a missing exe, or the MCP SDK in `RYOS-windows.zip`) fails the job;
- `session_smoke` also runs on `windows-latest`, or the step records why it can't headless there.

**Needs:** 11
**Escalation:** packaging: Opus at medium.

### 35 — A tech-debt review of the Qt app
_Added 2026-10-19 from Vũ's decision (the improvement plan, "Code and test health")._ `docs/tech-debt-2026-09-21.md` describes the Tk app at 1.11.2 (`app.py`, `dialogs.py`). Since the Qt port the biggest file is `ryos/qtui/shell.py` (3,475 lines at `ef7600d`); `ryos/` is 78 modules and 23,647 lines, and `mypy` covers 61% of them. Use the "Tech debt check-in" prompt in `docs/PROMPTS.md`. No code changes.
**Files:** `docs/tech-debt-2026-MM-DD.md` (new), `docs/tech-debt-2026-09-21.md` (marked superseded), links to it.
**Done when:**
- the new review uses the same scoring (priority = (Impact + Risk) × (6 − Effort));
- it names extraction candidates in the files steps 16–28 change;
- the old review is marked superseded and every link to it is fixed.

**Needs:** —

### 36 — Type checks over the window, and extract what you touch
_Added 2026-10-19 from Vũ's decision (the improvement plan, "Code and test health")._ A rolling step that rides along with B, C and D. The typecheck job leaves `ryos/qtui/` out because it doesn't install PySide6. No big refactor in 2.4: a step that changes `shell.py` moves the part it touches into its own module, where step 35 names it as a candidate.
**Files:** `.github/workflows/ci.yml` (typecheck job), `pyproject.toml` (`[tool.mypy] files`), `ryos/qtui/*`, the Architecture tables in `CLAUDE.md` and `docs/ARCHITECTURE.md`.
**Done when:**
- the typecheck job installs PySide6, and every `qtui` file a B, C or D step changed is in `[tool.mypy] files` and clean on Linux;
- `shell.py` is shorter at step 29 than its 3,475 lines at `ef7600d`;
- each new module has its Architecture rows.

**Needs:** 35

### 37 — Fix the qt-smoke crash on CI
_Added 2026-10-19 from Vũ's decision (red CI on `afa32f5`)._ CI's `qt-smoke (ubuntu, offscreen)` job (`uv run --no-project --with PySide6 python tests/qt_smoke.py`) ends with exit code 139, a segfault, in about half its runs since 2026-10-13: 10 of the last 20 runs on `main`, among them `754568b`, `a6deea9`, `e853e87`, `d900395` and `afa32f5`. It has also passed on the same code (`96405b6` passed, `afa32f5` failed with no change under `ryos/` or `tests/`). Every crash comes right after the last check prints (`check_ampersands_show`, `tests/qt_smoke.py:5964`), so it happens after all the checks have finished, between `main()`'s summary and process exit. "RYOS Qt smoke PASSED" never appears in those logs. The Windows test jobs and the unit tests pass. It is not yet known whether the cause is in the smoke's own teardown or in RYOS shutting down (window, `QTimer`, worker threads, `MainThreadInvoker`). If it's RYOS, a user on Linux could hit it at quit. Step 32 makes every coding session fix a red CI run first, so until this is fixed each session stops here.
**Files:** `tests/qt_smoke.py` (`main`, teardown), possibly `ryos/qtui/*` shutdown paths, `.github/workflows/ci.yml` only if the job needs a debug aid.
**Done when:**
- the cause is named, and a check that crashed before the fix passes after it (or the crash is reproduced locally with offscreen Qt on Linux or WSL and fixed);
- `qt-smoke (ubuntu, offscreen)` passes 10 runs in a row on the fix commit (re-runs or a repeat matrix), with "RYOS Qt smoke PASSED" in each log;
- if the cause is in RYOS, its `docs/BEHAVIOUR.md` row (quit/tray, TW-*) names the test; if it's in the harness, a line in BEHAVIOUR § Harness escapes. Either way, a line in § Escapes per the escape rule, since it reached `main`.

**Needs:** —

### 38 — Claim a step when you start
_Added 2026-10-19 from Vũ's decision ("other sessions should tell us which task is in progress")._ Since 2026-10-19 several tabs work at once (37 and 35 beside the secretary's 33). A coding session writes to the Status table only when it finishes, so nothing shows a step is taken, and two tabs given the continue prompt both pick the same step. `.claude/hooks/session_start.py` already prints "Also started" for rows whose state begins `started` or `in progress` (`started()`), but `next_open()` still counts those rows as open, so the "Next open step" it prints can be a step another tab holds.
**Files:** `.claude/skills/add-ryos-feature/SKILL.md`, `.claude/skills/fix-ryos-bug/SKILL.md`, `.claude/skills/release-ryos/SKILL.md`, `.claude/hooks/session_start.py` (`next_open`, `plan_lines`), `tests/test_harness.py` (`TestSessionStart`), `docs/PROMPTS.md`, `.claude/skills/*/evals/`.
**Done when:**
- the three coding skills, before any other work, set their step's Status row to `in progress (YYYY-MM-DD HH:MM)`, and commit and push that one line on its own, by path;
- the continue prompt's "next open step in Order" skips a step already in progress, and the session-start hook prints the steps in progress and a next step that isn't one of them (`TestSessionStart` cases: one claimed, all claimed, a `started` row);
- a session that stops without finishing (Still red, a `**Gate:**`, a second BLOCKERS) writes why in its row, so no claim goes stale;
- a tab given a named step that is already claimed says so and stops;
- each coding skill gains an eval for claiming, and `fix-ryos-bug` one for refusing a claimed step;
- `docs/PROMPTS.md` says how to start a second tab beside another.

**Needs:** 37 (green CI).

### 39 — A: Offer release candidates (P7)
_Added 2026-10-21 from Vũ's decision (P7 was in no step, and step 12 relies on it)._ Decision P7: Options → "Offer release candidates (for testing)", off by default, reads `/releases` instead of `/releases/latest`. It is the only way rcN → rcN+1 goes through self-update for real on Vũ's PC, which step 12 and step 29's two RC-to-RC updates count on. Step 4 built the channel as a parameter, `updates.fetch_release(prereleases=…)` (`ryos/updates.py:101`), but nothing sets it: there is no setting and no checkbox, so the window's check (`ryos/qtui/shell.py`, beside the `auto_download_update` read) and `ryos-cli version --check` / `update` always ask for `/releases/latest`. "Download updates in the background" lives on the Logging tab (`settings.py`, `settings_schema.py`). RYOS Agent has no Options dialog, so the designer decides how the command line follows the setting.
**Touches:** TW-17 ("a pre-release is never offered" holds with the option off), UP-01, UP-07, UP-08, CLI-13; surfaces W CLI.
**Files:** `ryos/settings.py`, `ryos/settings_schema.py`, `ryos/qtui/shell.py` (the update check), `ryos/cli.py` (`version --check`, `update`), possibly `ryos/updates.py` / `ryos/selfupdate.py`; `tests/test_updates.py`, `tests/test_cli.py`, `tests/test_ryos.py` (`TestSettingsSchema`), `tests/qt_smoke.py`.
**Done when:**
- the option is in Options, off by default, and with it off nothing changes (TW-17's tests still pass);
- with it on, the window and the command line offer a newer pre-release of this download, downloaded, signature-checked and applied exactly like a release, tested against a 127.0.0.1 server (rcN → rcN+1, rcN → its final, a final → the next rc1);
- a pre-release is never offered to a build with the option off, and a release is never replaced by an older pre-release;
- `qt_smoke` checks the checkbox; TW-17 and a new UP entry name the tests.

**Needs:** 11

### 40 — No publish without a passing release_check; a reproducible portable zip
_Added 2026-10-21 from Vũ's decision (the v2.4.0-rc1 harness escape, `baf0245`)._ v2.4.0-rc1 was published at 20:38 with no `release_check` run on record before it, and the step 12 row said "PASSED (29/0/0)" without one (corrected in `5f9f1a4`). The rule "release_check is a hard gate" lives only in the `release-ryos` skill; `gh release create` is an `ask` in `.claude/settings.json`, which stops nothing once Vũ is used to approving it. BEHAVIOUR § Harness escapes (2026-10-21) proposes: `release_check` writes a pass stamp (e.g. `dist/release_check.passed`) holding HEAD, the hash of `dist/SHA256SUMS.txt` and the case count, and `.claude/hooks/guard.py` refuses `gh release create vX.Y.Z[-rcN]` (and its wrapped forms) unless the stamp names the current HEAD and the current `SHA256SUMS.txt` hash. A failed run must leave no stamp.

The re-run at `6b9d12e` also failed `release_check::portable`: `build_release.zip_portable` zips `ryos/` from the working tree, which has mixed line endings (57 files CRLF, 29 LF; `core.autocrlf=true`, no `.gitattributes` rule for `ryos/`), so the zip doesn't byte-match a clean checkout, though every file is equal once CRLF is normalised. The same run needed Python 3.13: under 3.14 the three `self_update_*` cases fail. Which side changes (the zip, the check, `.gitattributes`) is the designer's call.
**Touches:** BEHAVIOUR § Harness escapes (the 2026-10-21 line: "proposed" becomes the check in place), § Escapes (the portable mismatch), `release-ryos` (where the stamp is made and checked).
**Files:** `tests/release_check.py`, `.claude/hooks/guard.py`, `tests/test_harness.py`, `build_release.py` (`zip_portable`), possibly `.gitattributes`, `.claude/skills/release-ryos/SKILL.md`, `docs/BEHAVIOUR.md`.
**Done when:**
- `test_harness` shows `gh release create` refused with no stamp, a stamp for another HEAD, a stamp for another `SHA256SUMS.txt`, and after a failed run; allowed with a matching stamp; the wrapped forms the guard already knows are covered too;
- `release_check` writes the stamp only when every case passes;
- `release_check::portable` passes on a fresh `build_release.py` build from this checkout and from a clean worktree, and `release_check` says which Python it needs (or refuses another) instead of failing the `self_update_*` cases;
- `release-ryos` names the stamp; BEHAVIOUR § Harness escapes and § Escapes say what was added.

**Needs:** 12 (rc1 published).
**Gate:** Vũ approves the `guard.py` change (`.claude/hooks/` edits are `ask`).

## Order

1. **Fixes** 1, 2, 3 (small, independent). Done.
   - **37** (the qt-smoke crash, added 2026-10-19) comes next (CI must be green before a candidate).
   - **38** (claim a step, added 2026-10-19) right after it (parallel tabs need it).
2. **Harness and loop rules, before step 11** (added 2026-10-19): 31, then 32. 33 runs alongside (docs only).
3. **Part A**, the riskiest and the one that changes the release process:
   1. 4 and 6 can run in parallel;
   2. then 5, 7, 8, 9, 10, 11;
   3. then **39** ("Offer release candidates", P7; added 2026-10-21; step 12 relies on it);
   4. then **12**, the early candidate, so A gets real use for the rest of 2.4.
   5. then **40** (added 2026-10-21), before any later candidate is published.
4. **Backlog** 13, 14, 15, before B and C touch rows, the pane and the Running list. Step 13 may run beside part A in its own worktree. 34 (frozen builds in CI, after 11) and 35 (the tech-debt review) run beside the backlog.
5. **B and C**, in parallel worktrees where step 33 shows their files don't overlap, otherwise in sequence:
   - B: 16 → 17, 18, 19;
   - C: 20 → 21 → 22, and 23 → 24.

   Steps with migrations (16, 20, 23, 24) take their `_MIGRATIONS` number when they merge (P22). Step 36 rides along with every B, C and D step that changes `ryos/qtui/`. Two lanes cross: 21 needs 18, and 25 needs 20.
6. **Part D:** 25 → 26 → 27 → 28 (secrets before triggers).
7. **Release:** 29, the test phase, then 30.

## Parallel lanes and merging

_Added 2026-10-19 from Vũ's decision (the improvement plan, "Graphs")._ Until now every commit went straight onto `main`, one after another. When two lanes run at once:

1. One worktree and branch per lane (`lane/b`, `lane/c`), each made from `main`.
2. A lane edits only its own rows of the Status table, and only its own new `docs/BEHAVIOUR.md` entries.
3. To merge, the lane rebases on `main` and takes the next `_MIGRATIONS` number (P22). It runs the full suite and `session_smoke`, pushes the branch and waits for green CI.
4. Vũ approves each merge. Merges are fast-forward only, one lane at a time.
5. After a merge, the other lane rebases before its next step.

Run at most two lanes, and only where step 33's Files lines don't overlap: one maintainer reviews every merge.

## Risks in the code the plan works around

- **The update fetch's result can't be widened.** `notifications.py:101` unpacks `(tag, url)`, and `cli.py:503` and `qtui/main.py:118` inject the fetch. Step 4 adds a separate fetch with the assets.
- **Nothing redirects `LOCALAPPDATA` today.** `settings.py:14` uses `APPDATA` only (P5).
- **A cx_Freeze exe needs its `lib/`** (`setup_cxfreeze.py:108–142`), so a lone temp copy can't run (P3). Renaming the install folder needs write access to its parent and fails while anything inside is open.
- **`SHA256SUMS.txt` carries no version** (`build_release.py:120–124`); the signature binds it (P2).
- **The worker thread logs output lines** when "Log script output too" is on (`runner.py:167`, `:207`). Masking (25) and failure patterns (16) happen in the reader, before those lines. Status comes from the return code only (`runner.py:156`); the done tuple's shape is pinned (`runner.py:105–107`).
- **The outside note is decided per controller, not per run** (`job_controller.py:216`, `:442`; `qtui/jobs.py:62`): the root of GR-33, and a trap for triggers.
- **`auto_clear_output` is read nowhere**; `session_smoke.py:437–458` expects the All tab to hold only the newest run.
- **Agent run ids are in-process** (`agenttools.py:38`, `:126`; `headless.py:219`); history rows are written only at completion (`db.py:115–116`), hence step 20.
- **Accessor rows are pinned** (`test_ryos.py:5026–5035`: `list_runs` 11, `list_pipeline_steps` 14). Steps 16, 20, 23, 24 add accessors, not columns to old rows.
- **The MCP tool list is pinned to six names** (`test_mcpserver.py:84`, `release_check.py:60`). Step 21 updates both and MCP-07.
- **The window learns of CLI and agent runs only when they end** (`mcpserver.py:154`, `cli.py:467`).
- **`_MIGRATIONS` is one dict** (`db.py:263`); `COMPATIBLE_FROM` (`db.py:281`) must stay 1.
- **The row menu's order is pinned** (RC-20, `TestCardMenu::test_script_menu_order`).
- **Credential Manager is per Windows user, not per data folder**; tests namespace their targets (P18).

## Status

| Step | State |
| --- | --- |
| 1 Fix OP-15 | done: All tab emptied when a run starts with the option on; finished and running run tabs kept; `test_ryos::TestOutputRouting` (clearing, option off, running tab kept), `session_smoke::step_output_options`, `qt_smoke::check_maximised_layout` |
| 2 Fix GR-33 | done: the outside note is decided by the run's trigger (`basefolder.notes_for`, only the window's manual runs note; script and pipeline-step paths); `test_ryos::TestBaseFolderNotes` (script and pipeline step by trigger, `test_only_a_window_run_notes`), `session_smoke::step_scheduled_outside` asserts no note |
| 3 Fix SM-16 | done: `load_from_db` keeps select mode and the ticked (kind, id) across a reload; Delete selected leaves the mode itself; `qt_smoke::check_select_mode` stars, unstars, maximises and restores with a tick |
| 4 A1 Find and download | done: `ryos/updates.py` (`fetch_release` with the pre-release channel, `pick_asset`, `download` with resume and SHA-256 check; `_fetch_latest_release` unchanged), `settings.updates_dir`; `tests/test_updates.py` against a 127.0.0.1 server; UP-01…UP-06. Not run against real GitHub. Left for step 5: test the cut-off with the real streaming opener, catch `OSError` from the hash check and rename, send `LOCALAPPDATA` to the harnesses |
| 5 A1 Background download and setting | done: the window fetches with `updates.fetch_release` and, on a newer release of its own zip with "Download updates in the background" on (`auto_download_update`, default on, Logging tab), downloads on a second worker through `MainThreadInvoker` (`updates.wants_download`, `check_of`, `downloaded`; `download()` now catches `OSError` from the hash check and rename); `ryos-cli version --check` says "Not downloaded yet." or "is downloaded and checked: <path>" (UP-08); portable keeps today's notice; every harness redirects `LOCALAPPDATA`; `test_updates::TestWhenToDownload`/`TestDownloaded`, `test_cli::TestVersion`, `qt_smoke::check_update_downloads_in_the_background` (normal, compact, maximised); UP-07, UP-08. Not run against real GitHub or a frozen build. P7 "Offer release candidates" not added: still to place before step 12 |
| 6 A2 Signature check and signing tool | done: `ryos/ed25519.py` (pure-Python verify-only Ed25519, RFC 8032 §5.1.7 cofactorless, about 2.5 ms a check) and `ryos/signature.py` (`SHA256SUMS.txt.sig` format; `check`: missing, malformed, different key, changed, another version, older than this RYOS); `updates.download` needs `buildinfo.release_key()` and checks SUMS + `.sig` in memory before staging either or fetching the zip; `downloaded` re-checks the staged signature; `updates.verify_zip` and `ryos-cli verify <zip>` (0, or 125 with words; no database or settings); `build_release.problems_in` refuses `lib/cryptography/` in `RYOS-windows.zip`; `tools/sign_release.py new / sign` (key outside the repository, passphrase-protected PKCS8 PEM, `uv run --with cryptography`); `.gitignore` guards `*.pem`, `*.key`, `*.p8`; `tests/ed25519_signer.py` signs with the RFC 8032 test keys; `test_updates::TestEd25519`/`TestReleaseSignature`/`TestVerifyZip`/`TestSigningTool` and the new `TestDownloading`/`TestDownloaded` cases, `test_cli::TestVerify`, `test_ryos::TestBuildInfo::test_release_key_comes_only_from_the_build`, `TestReleaseZipChecks::test_the_build_without_agents_carries_no_cryptography`; UP-09…UP-13, UP-03/05/08, CLI-13, MCP-08. Step 8 embeds the key (`RELEASE_KEY` in `_build_info.py`); until then every build says it "carries no release key" and downloads nothing. Not run against real GitHub or a frozen build; no real release key made |
| 7 Vũ makes the signing key | done 2026-10-15: key made with `tools/sign_release.py new`, kept outside the repo (`%USERPROFILE%\ryos-keys\ryos-release.pem`); public key `3448252042d2cd24b977ba0688acf6c3d4ca914aaf4f7df80cbac399008006a8` for step 8. Still for Vũ: a backup of the key file in a second place, and the passphrase in a password manager |
| 8 A2 Signing in the release process | done: the build embeds `buildinfo.RELEASE_PUBLIC_KEY` (`build_info_source(..., release_key)`, passed by `setup_cxfreeze.py`), so a build now downloads and verifies; `release_check::signature` (each frozen build's own `ryos-cli verify` accepts its zip with dist's `SHA256SUMS.txt.sig`; planted: signed with the test key, changed SUMS, both refused with 125); `release-ryos` A3b "Vũ signs" between build and check (and again in B3), `.sig` joins both `gh release create`, the lineup and notes template; `ryos-reviewer` item 5a; README, TUTORIAL "Check your download" gain `ryos-cli verify`; key-lost note in `docs/CONTRIBUTING.md` and `release-ryos`; UP-20. Not run: `release_check` needs a build and Vũ's signature, first at step 11/12 |
| 9 A3 Apply and roll back | done: `ryos/swap.py` (`apply_update`, `roll_back`, `recover`, `settle_at_start`, `rollback_available`, `stage_helper`, `stage_rollback_helper`, `helper_argv`; journal `swap.json`, `swap.lock`, `previous.json` in the updates folder), hidden `ryos-cli apply-update` (argv v1); `tests/test_swap.py` (update and rollback on real folders, a failure at each step, real locked files on Windows, a crash at every effect call recovered, unsafe zips) and `test_cli::TestApplyUpdate`, `TestTheRealEntryPoint`; UP-14…UP-19, CLI-11/TW-06/TW-16 notes. Rollback settles `.outgoing` into `.previous` after the restart, not before verify. `ryos/swap.py` is in `[tool.mypy] files`. Left for step 10: `previous.json` and the journal are one per updates folder, not per install (mixed installs share them); `--recover` ignores `--install`; `settle_at_start` is not wired and accepts an unverified build after an interrupted unswap; refuse an update already installed; compare with `realpath`. Not tried: a frozen build, real antivirus (step 11) |
| 10 A3/A4 Restart to update, edge cases | done: `ryos/selfupdate.py` (pure `decide`: from source, nothing, not writable, blocked, busy, due, go, with the window's and the CLI's words and the `compatible_from` rollback warning; `running_from` (Windows process list), `write_problem` (probe folder beside the install, probe file in it), `due_soon` (5 minutes), `Updater`/`real()`, `prepare`, `at_start` with `at-start.json`); window banner states Available / Ready ("Update ready — RYOS X (you have vY)", Restart to update, Later) / Staging / Waiting (Cancel) / At next start, Help → Roll back to RYOS X…, `quit_app` split into `_shut_down`, helper staged off the UI thread through `MainThreadInvoker`; `ryos-cli update [--rollback] [--yes]` (no lock, no Qt, no database; 0 started or up to date, 1 unreachable/download/prepare failed, 125 refused); `__main__` runs `at_start` after the instance lock and before Qt; swap: journal per install (`journal_dir_for`), `--from-compatible` kept in `previous.json`, `previous_build`, the start-up settle accepts a new build only when its files are the zip's, `recover` needs its journal folder (`--recover` uses the install's), apply-update refuses an update already installed, logs its result and starts RYOS again after a refusal (not while another swap runs); `db.read_compatible_from` (read only). Tests: `tests/test_selfupdate.py`, `test_swap::TestPerInstall`, `test_cli::TestUpdate`, `TestApplyUpdate` additions, `TestTheRealEntryPoint::test_update_…`, `test_ryos::TestCompatibleFrom::test_read_compatible_from_reads_without_writing`, `qt_smoke::check_restart_to_update` (normal, compact, maximised). Decisions applied: no "stop runs and restart" (wait or not now); a dismissed Available banner does not come back as Ready that session; Later in the at-next-start state keeps the request; RYOS Agent with its MCP server open is refused 125 with no at-start request; `--yes` accepts the rollback warning, printed to stderr; with background download off the banner stays Available. Not tried: a frozen build end to end, real antivirus, a real agent holding `ryos-cli.exe mcp` open (the probe is unit-tested on this process only). Deferred: no Repair button (9), `folders_for` stays on `abspath` (10), the last update's result is not in `version` (11); no on-demand download when background download is off (8). |
| 11 A Self-update in release_check, docs | done 2026-10-19: `release_check` cases `self_update_windows`/`_windows_ai`/`_agent` (update and roll back from a signed source on 127.0.0.1: exe path unchanged, data, pipeline and exposure intact, `ryos-cli`, MCP and the window answer; planted unsigned and other-key releases refused; helper killed mid-swap and a held file leave the old build whole), `self_update_newer_database`, `self_update_portable`, `shipped_builds_ignore_the_test_source`; P6 amended (pyc swap in a copy, see P6); `buildinfo.test_updates`/`test_releases_api`, `build_release.release_key_problems` (also in `zips` and the reviewer); `swap._save_json` retries a refused journal replace (found by the cases; `test_swap::TestJournal`); UP-28…UP-30; tutorial page 15, README, TUTORIAL, release-notes "Updating". Planted-fault runs were made before the `_save_json` fix. `signature` and `build_commit` fail until step 12 (no `.sig`, dirty tree). Not run: a real release, real Defender |
| 12 Early candidate after part A | v2.4.0-rc1 published 2026-10-21 20:38 (pre-release, 6b9d12e); release_check run at HEAD 053d8b9 after publishing: 28 passed, 1 failed, 0 skipped, the one failure `build_commit` only because HEAD is two docs-only commits past the build (the exes say 6b9d12e), every other case passed including `zips`, `signature` and the three `self_update_*` cases; no run before the 20:38 publish is on record, and the "29/0/0" first written here was never a recorded run. Re-run 2026-10-21 from a git worktree at 6b9d12e against the published `dist/` (its four zips' SHA-256 equal the release's): 28 passed, 1 failed, 0 skipped; `build_commit` passed (the exes say 6b9d12e), as did `zips`, `signature` and the three `self_update_*` cases; the one failure is `portable`, whose byte compare finds the zip's `ryos/` (built from the dev tree: 57 files CRLF, 29 LF) unlike any one checkout's line endings, while every file is equal once CRLF is normalised. The worktree needs `--python 3.13` (the builds' Python; 3.14 fails the three `self_update_*` cases) and a short path; tester TESTER: PASS on the update flow (no FAIL: `ryos-cli verify` with the real key on all three frozen zips and its refusals, `version --check`, `update` rc1 → rc2, `--rollback` and rc1 → final from a local signed source with the test key, "Offer release candidates" off and on, the window's Ready/Staging/Waiting/agent-blocking/not-writable/Roll back/Options flows in normal, compact and maximised from source; the built `RYOS.exe` window was only started, never driven through a real update). Waiting on Vũ's checklist (no minimum time): [ ] Claude Desktop connects to the windows-ai build's `ryos-cli.exe mcp` and runs an exposed script. [ ] Claude Code connects to the agent build and runs an exposed script. [ ] `uv run python tests/real_data_smoke.py` on real data (and `--db <backup>`): no count dropped. [ ] Real data looks right after the upgrade (scripts, groups, pipelines, schedules, history). [ ] Fresh download from the release page: SmartScreen flow and "Check your download" hash. [ ] Properties -> Details on `RYOS.exe` and `ryos-cli.exe` shows the publisher (TW-27). [ ] A real Restart to update through the window from a real newer release, and Help > Roll back after it. [ ] The rc channel against real GitHub with a newer rc present (today rc1 is newest: only "Up to date" seen). [ ] Maximised list in select mode at real DPI, with and without agents: sideways scrollbar and Run buttons under the vertical scrollbar (SM-15, RC-14). [ ] Antivirus during the helper swap; a real MCP server holding the install (UP-23). [ ] Portable `run.bat` / `install_uv.bat` with uv. |
| 13 Backlog: no window | — |
| 14 Backlog: pane, dialogs, menus | — |
| 15 Backlog: every row surface | — |
| 16 B1 Failure patterns: rules, outcome | — |
| 17 B1 Failure patterns: editor, highlights | — |
| 18 B2 Time left | — |
| 19 B3 Stats | — |
| 20 C1 Keep each run's output | — |
| 21 C1 + #32 Agents read history, progress | — |
| 22 #32 CLI and agent runs in the window | — |
| 23 C2 Pipeline parameters | — |
| 24 C2 Passing a value between steps | — |
| 25 D1 Secrets: store, inject, mask | — |
| 26 D1 Secrets: dialog, CLI, export | — |
| 27 D2 Triggers: rules, storage, firing | — |
| 28 D2 Triggers: dialog, badge | — |
| 29 2.4 release test phase | — |
| 30 Release 2.4 | — |
| 31 Harness: permissions, hooks, checks | done 2026-10-19: `.claude/settings.json` rewritten (89 stable allow rules, no scratch-session paths or one-off edits, `.claude` reads only `~/.claude/skills/**`, no Downloads; 26 `ask`: `gh release create/edit/delete/upload`, `gh api *releases*`, forced and mirror `git push`, edits to `.claude/settings.json` and `.claude/hooks/`; 27 `deny`: `git checkout`/`git restore` on `docs/STATUS.md` and `docs/plans`, `git reset --hard`, `xargs … git checkout/restore`, the key folder and `*.pem`/`*.key`/`*.p8`, `~/.claude/.credentials.json`; `env` block; `C:\Users\Admin\.claude` dropped from `additionalDirectories`); `.claude/hooks/guard.py` (PreToolUse on Bash, PowerShell and the file tools: refuses writes into the real `%APPDATA%\RYOS` / `%LOCALAPPDATA%\RYOS` in any spelling, alias, wrapper or after a `cd`, starting RYOS (`uv run`, `uvx`, `python -m`, the exes, `start`, `Invoke-Item`) without `APPDATA` pointed elsewhere in the same command, `set APPDATA=` outside `cmd /c`, the key folder or a `*.pem`/`*.key`/`*.p8` file argument (not attribute access such as `item.key`, not git or gh text), `tools/sign_release.py sign/new`, reverting secretary files (also after `cd docs`), and `git stash` / `git clean -f` / `git checkout -f` / `git switch -f` / whole-tree, glob or bare-name discards while they are dirty; asks for wrapped release and forced-push forms; a crash fails open with a message); `.claude/hooks/session_start.py` (branch, uncommitted, secretary edits, CI on HEAD, the plan's next open step); `tools/harness_checks.py version` / `comments` and CI's `harness` job; `tests/test_harness.py` (`TestGuardRefuses`/`Allows`/`Asks`/`SkillCommands`/`Main`, `TestSessionStart`, `TestVersionCheck`, `TestCommentCheck`); BEHAVIOUR § Harness escapes (10-09, 10-13, PR #14); CLAUDE.md § Harness. Both checks pass on `5c76e95..HEAD` and on the 2.3.1 release commits, and fail `92f9eac` (PR #14) and a `Revert "Release …"` that changes the version. Known gap: a scratch `.py` importing `ryos` without redirecting `APPDATA` is not visible on the command line. Needs a human: a session with only the project settings runs one command from each skill without a prompt; the `gh release create` ask seen at the next candidate; the live CI `harness` job green on push; confirm auto-memory still works without `C:\Users\Admin\.claude` in `additionalDirectories` |
| 32 Loop rules | done 2026-10-19: `ryos-implementer` has a stop rule (two fix rounds after the first run, then a "Still red" report, no workarounds; a reviewer's BLOCKERS are one more round counted on their own); `add-ryos-feature` and `fix-ryos-bug` gain "Before you start, and where you stop" (CI on HEAD checked first, a red run's fix comes next; stop at a `**Gate:**` line and say what Vũ does; the loop's stop rules), a second BLOCKERS verdict stops and reports to Vũ, and after `git push` they watch the run with `gh run watch <id> --exit-status`; `docs/PROMPTS.md`'s continue prompt is the one-line STATUS prompt and names no plan; `docs/MCP_CLEAN_TEST.md` committed (title and `--version` line updated to 2.3.1, framed as the manual check against real Claude Desktop and Claude Code) and `docs/PROMPTS.md` points at it; new evals: `fix-ryos-bug` 5, `release-ryos` 4 (failed `release_check`, waits for the version, waits for Vũ's signature, red CI), `ryos-secretary` 4 (no code, no push, no version pick, no claim without evidence). The evals are written, not run. Not changed: the stale Tk-era `add-ryos-feature` evals |
| 33 The plan as a graph | started 2026-10-19: Gate lines, 14–15 Needs and the merge rules added by the secretary; Files lines to do |
| 34 Frozen builds in CI | — |
| 35 Tech-debt review of the Qt app | done 2026-10-19: `docs/tech-debt-2026-10-19.md` (11 items scored by (Impact + Risk) × (6 − Effort), the old register's six items accounted for, top three, remediation by step). Top three: split `handle_step_done` (190 lines, was 156) before step 23; extract the card/group menu dispatch from `shell.py` at step 14 and put the `qtui` files steps 16–28 change into `mypy` at step 36; settle the jobs/Activity boundary at step 22's design. Extraction candidates named for steps 14, 15, 18, 22, 23, 24, 26, 28. `tech-debt-2026-09-21.md` marked superseded; links fixed in `README.md`, `docs/README.md`, `docs/PROMPTS.md`. Not changed: the docstring in `ryos/scriptform.py` that cites the old review (no code changes; the old file stays). No code, no tests run |
| 36 Type checks over the window | — |
| 37 Fix the qt-smoke crash on CI | done 2026-10-21: cause was the smoke leaving ~800 widgets and ~130 Python-owned objects alive (`deleteLater` never ran without an event loop), which PySide6 6.12.0 (unpinned in CI) crashed tearing down at exit after PASSED (exit 139); fixed in 895f077 (`close_down` in `tests/qt_smoke.py`, fails if any survive; the job gets faulthandler and unbuffered output); BEHAVIOUR rows added in the same commit. Evidence: CI run 39281059401 on 895f077, `qt-smoke (ubuntu, offscreen)` re-run to attempts 1-10, all 10 green with "RYOS Qt smoke PASSED" in each log (checked per attempt through the jobs API) |
| 38 Claim a step when you start | done 2026-10-19: the three coding skills (`add-ryos-feature`, `fix-ryos-bug`, `release-ryos`) start with "Claim your step before anything else" (a row `in progress` or `started` is held, stop; otherwise set `in progress (YYYY-MM-DD HH:MM)`, commit and push that line alone by path; a session that stops writes why in the row); `session_start.py` `next_open` skips claimed rows and `plan_lines` prints "In progress (claimed by another tab, don't take)" (`is_claimed`, `started` without `skip`); `tests/test_harness.py::TestSessionStart` (one claimed, a `started` row, every open step claimed); `docs/PROMPTS.md` continue prompt says "not already in progress" and has a second-tab prompt; evals: claim in all three skills, `fix-ryos-bug` refuses a claimed step (written, not run). Not changed: the continue prompt quoted in `docs/STATUS.md` (secretary file) |
| 39 A Offer release candidates (P7) | done 2026-10-21: Options > Logging "Offer release candidates (for testing)" (`offer_release_candidates`, off by default); the window and `ryos-cli version --check` / `update` pass it to `updates.fetch_release`; `version --check` no longer has its own fetch (`notifications._fetch_latest_release` deleted); UP-31 added, TW-17, UP-06, CLI-13 updated. Tests: `test_updates::TestReleaseCandidates`, `test_cli` apply and default-fetch cases, `qt_smoke` options row and rc block. Not run: a real rc to rc update from GitHub (steps 12, 29). |
| 40 No publish without a passing release_check | — |
