# RYOS v2.4.0 (working name): self-update, smarter runs, agents and pipelines, automation

_Created 2026-10-14 by the planner from `docs/plans/release-2.4.0-brief.md` (the secretary, 2026-10-13, from Vũ's decisions), after v2.3.1 shipped. Approved by Vũ 2026-10-14 ("all good": every planner recommendation accepted). This is the only plan after 2.3.1. The version number is Vũ's: "2.4.0" is a working name. Each code step goes through the `ryos-*` agent team via its skill, in a fresh conversation._

## Goals

1. Fix what the behaviour map found first: **OP-15** ("Clear output between runs" does nothing), **GR-33** (a scheduled outside run gets the note) and **SM-16** (starring or maximising leaves select mode).
2. **A. Self-update.** Staged and still zip-based: download, verify the hash and an Ed25519 signature, ask, swap folders, keep one `.previous` for rollback. The install path never changes. `release_check.py` covers it over each of the four downloads.
3. Close the behaviour map's **untested backlog**, so B, C and D are built with every surface guarded.
4. **B. Smarter runs:** failure patterns, time left, stats.
5. **C. Agents and pipelines:** agents read history and past output, and see a long run's progress (#32). The window shows runs started by the CLI or agents. Pipeline parameters, and values passed between steps.
6. **D. Automation:** secrets in Windows Credential Manager, then file triggers.
7. Ship **2.4** through the test phase: `release_check.py` hard gate, RC pre-release, `ryos-tester`, Vũ's checklist with no minimum time, then promote the same commit.

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
| P6 | Testing self-update without the private key in a session | In the RC flow Vũ signs **before** `release_check`. While step 11 is built, a test public key goes into `_build_info.py` only through an explicit build option; `build_release.py` and the release review refuse any zip that doesn't carry Vũ's key. The installed side is made to think it's older through a test-only override | A runtime switch that adds trusted keys would be a hole |
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

**Needs:** 1–11

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

**Needs:** —
**Escalation:** DB and threading: Opus at medium.

### 17 — B1: failure patterns: editor, highlights, CLI
_Brief, part B1._ The script dialog edits the rules and the common-set tick box. The output panel highlights error and warning lines in every theme. `ryos-cli edit <script> --fail-on REGEX` (and removal) for RYOS Agent users. A bad regex is refused in words.
**Touches:** PR-05/PR-08 (the script dialog), OP-09, OP-10, ST-06, CLI-10, RC-24 and GR-18 (clone and copy carry the rules), IE-02 (export round-trip).
**Done when:**
- the dialog round-trips the rules (`qt_smoke::check_script_dialog`);
- highlights are legible in every shipped theme (`TestQtStylesheet`);
- clone, copy and export keep the rules;
- `test_cli` covers `--fail-on`.

**Needs:** 16

### 18 — B2: time left
_Brief, part B2; P11._ A toolkit-free estimate from history: median of the last 10 successful runs, shown from 3, with "taking longer than usual" past it. Surfaces: the Running list and status bar, the detail pane, the Activity bar, the tray tooltip, MCP `get_run`.
**Touches:** OP-01, TW-23, TW-03, RC-12 (rows unchanged), MCP-04.
**Done when:**
- unit tests show it appears after enough runs and not before, stays sensible past the median, and ignores failed and stopped runs;
- it is drawn in normal, compact and maximised, and in the tray tooltip;
- new OP and TW entries are added.

**Needs:** —

### 19 — B3: stats
_Brief, part B3; P12._ A toolkit-free module over existing history: success rate, duration trend, and the pipeline step that fails most. Shown in the History dialog's summary (HI-03), the detail pane, and `ryos-cli history <item> --stats`.
**Touches:** HI-03, HI-08, HI-09, TW-22.
**Done when:**
- the numbers match a hand count on fixture history (unit test);
- shown in normal, compact and maximised;
- `test_cli` covers `--stats`;
- HI entries are added.

**Needs:** —

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

**Needs:** 20
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

**Needs:** —
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

**Needs:** 25
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

**Needs:** 27

### 29 — The 2.4 release test phase
_Standing rule: every release goes through the test phase._ New `release_check.py` cases on each built download:
- B1, a rule fails a run through `ryos-cli`;
- C1, `list_runs` and past output over plain JSON-RPC for `windows-ai` and `agent`;
- the CLI-run listing in `windows`;
- D1, a masked secret through the CLI, in a namespaced target that is removed afterwards;
- `session_smoke` with a trigger in both layouts.

The `ryos-tester` brief covers the update flow. Vũ's checklist adds:
- a real update from GitHub, RC to RC, through the pre-release channel;
- a rollback;
- the swap with Defender's real-time protection on;
- the update while Claude holds `ryos-cli mcp` open;
- "why did last night's run fail?" from Claude Desktop;
- the secret in the Windows Credential Manager UI, gone after delete;
- a slow copy from USB or a network share into a watched folder.

**Done when:** `release_check.py` passes on a fresh build of all four zips and fails on a planted fault for each new case, and the checklist is in the Status table.
**Needs:** 11, 13–28

### 30 — Release 2.4
**Needs:** 29, green CI.
`/release-ryos`, and **Vũ names the version**. The order: build, Vũ signs, `release_check`, an RC pre-release, `ryos-tester` PASS, Vũ's checklist ticked, then promote the same commit with the release review printing `READY TO PUBLISH`. The release notes say 2.3.x users update by hand once, and name #32.
**Done when:**
- the release is published with the four zips, `SHA256SUMS.txt` and `SHA256SUMS.txt.sig`;
- #32 is closed with a link;
- the new schema's fixture is added (`make_fixtures.py`, `release-ryos` B7);
- `dist/` is cleared;
- `release-2.4.0.md` and `release-2.4.0-brief.md` are moved to `docs/archive/` with their links fixed.

## Order

1. **Fixes** 1, 2, 3 (small, independent).
2. **Part A**, the riskiest and the one that changes the release process:
   1. 4 and 6 can run in parallel;
   2. then 5, 7, 8, 9, 10, 11;
   3. then **12**, the early candidate, so A gets real use for the rest of 2.4.
3. **Backlog** 13, 14, 15, before B and C touch rows, the pane and the Running list. Step 13 may run beside part A in its own worktree.
4. **B and C in parallel worktrees:**
   - B: 16 → 17, 18, 19;
   - C: 20 → 21 → 22, and 23 → 24.

   Steps with migrations (16, 20, 23, 24) take their `_MIGRATIONS` number when they merge (P22).
5. **Part D:** 25 → 26 → 27 → 28 (secrets before triggers).
6. **Release:** 29, the test phase, then 30.

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
| 4 A1 Find and download | — |
| 5 A1 Background download and setting | — |
| 6 A2 Signature check and signing tool | — |
| 7 Vũ makes the signing key | — |
| 8 A2 Signing in the release process | — |
| 9 A3 Apply and roll back | — |
| 10 A3/A4 Restart to update, edge cases | — |
| 11 A Self-update in release_check, docs | — |
| 12 Early candidate after part A | — |
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
