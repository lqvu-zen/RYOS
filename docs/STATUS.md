# RYOS: project status

Kept by the secretary (`/ryos-secretary` in Claude Code, or a claude.ai session attached to the RYOS project). **This file is the master;** the claude.ai project copy was retired on 2026-10-19. Coding sessions **read** it but don't edit it: plan progress goes in each plan's own Status table. Last updated 2026-10-19 23:40 (UTC+7).

## Roles

- **Vũ ("Zenitus", maintainer):** decides, merges, picks version numbers, uses each release candidate, runs the manual checks, reviews the behaviour map.
- **Planner:** an Opus session in Claude Code at high effort, for planning only, e.g. turning `docs/plans/release-2.4.0-brief.md` into a plan.
- **Coding sessions:** Claude Code in VS Code running `add-ryos-feature` / `fix-ryos-bug` / `release-ryos` with the `ryos-*` agents (locator, designer, implementer, reviewer, and `ryos-tester` from 2.3.1 step 15).
- **Secretary:** keeps this status, the decision log and the open items; checks GitHub issues and the repo; writes plan steps when Vũ decides something. Never writes code; commits only its own doc files and never pushes.

## Working practices

- **Coding sessions:** one fresh conversation per plan step (`Ctrl+Shift+Esc`, *Open in New Tab*), on **Sonnet 5.5, Medium**; **High** for the release test phase and the release. Planning sessions run on **Opus 5.5, High**. The agents' models come from `.claude/agents/`, whatever the main thread uses. The prompt to continue, which names no plan file:
  > Read docs/STATUS.md to find the current plan, then continue with its next open step in Order that is not already in progress. Claim it first, and update the Status table when it's done.

  A second tab beside another uses the "second tab" prompt in `docs/PROMPTS.md`, which names its step.
- **The secretary:** run `/ryos-secretary` at the start of each working day, so this file catches up with the plans' Status tables and the git log (decided 2026-10-19). Start a fresh secretary conversation when the current one gets long, or after a release.
- **Paste-ready prompts** for every kind of session are in `docs/PROMPTS.md`.
- **Secretary edits to repo files** (`docs/plans/*.md`, `docs/STATUS.md`) may arrive uncommitted. Coding sessions commit them with their next change and never revert them. One edit was reverted on 10-13; step 31 makes that a `deny` rule.

## Releases: only two plans

| Release | What | Plan |
|---|---|---|
| **2.3.1** (✅ published 2026-10-14) | #26, #27, #29, #30, #31 fixes; behaviour map; publisher details; expose a group; Suggest a feature; release test phase | `docs/archive/release-2.3.1.md` |
| **2.4** (in progress, 15 of 38 steps done) | Fixes OP-15, GR-33, SM-16 · **A** self-update · backlog · **B** failure patterns, time left, stats · **C** agents read history and logs, more pipeline logic · **D** secrets, file triggers · steps 31–36: how the team works | `docs/plans/release-2.4.0.md` (steps 1–30 approved 2026-10-14; 31–36 added 2026-10-19) |

## Where we are (2026-10-19 23:40)

- **v2.3.1** is the latest release (2026-10-14). No 2.4 candidate yet.
- **`main` = `origin/main` at `afa32f5`** (2026-10-19 21:33). Since `2088a68`:
  - `7a125c9` the 2.4 plan written and approved;
  - `685d5aa` **OP-15:** "Clear output between runs" now empties the All tab (step 1);
  - `2e9867c` **GR-33:** a scheduled outside run no longer gets the outside note (step 2);
  - `2a9c973` **SM-16:** select mode and its ticks survive a reload (step 3);
  - `5c76e95`, `0ed73f1` test commands in `.claude/settings.json`; the no-comments code style in `CLAUDE.md`;
  - `e17f452`, `ebd986d`, `fee8d0c` the 2.3.1 plan archived; `release-ryos` archives a finished plan;
  - `754568b` find and download this download's update (step 4);
  - `984e300` download in the background, `version --check` (step 5);
  - `8cbebd7` Ed25519 signature check, `ryos-cli verify`, the signing tool (step 6);
  - `9620466` **Vũ made the release key** (step 7);
  - `e853e87` the release key embedded, signing in the release process, `release_check` signature case (step 8);
  - `a6deea9` apply and roll back an update (step 9);
  - `ef7600d` Restart to update, roll back, edge cases, `ryos-cli update` (step 10).
- `d900395` **self-update cases in `release_check`** over each frozen download; tutorial page 15 "Updating", README, release-notes line (step 11). It landed before 31 and 32, which the Order puts first. `signature` and `build_commit` fail until step 12 (no `.sig`, dirty tree).
- `96405b6` **the harness** (step 31): `ask` for release commands and forced pushes, `deny` for reverting STATUS/plans and for the key, `guard.py` and `session_start.py` hooks, `env` block, 89 stable allow rules, CI `harness` job (version bump, new comments). CI all green on `96405b6`, `harness` job included.
- `afa32f5` **loop rules** (step 32): the implementer stops after two fix rounds; skills check CI first and watch it after a push; one continue prompt; `docs/MCP_CLEAN_TEST.md` committed; new skill evals (written, not run).
- **CI is red on `afa32f5`: a recurring crash, not flaky noise.** `qt-smoke (ubuntu, offscreen)` exits 139 (segfault) right after its last check (`check_ampersands_show`, the last line before the summary), so at the end of the run or at exit. It has done this in 10 of the last ~20 runs since 2026-10-13 (`d900395`, `e853e87`, `a6deea9`, `754568b` among them), always at the same point; Windows and the unit tests pass. Under step 32's rule a coding session now fixes red CI first. Now **step 37** (Vũ, 22:05).
- **Gap before step 12:** the "Offer release candidates" option (P7) is in no step. `updates.fetch_release(prereleases=…)` exists (step 4), but there is no setting or checkbox; step 12 relies on it. **On hold (Vũ, 2026-10-19):** where to plan it waits; step 12 can't start without it.
- `de6108a` **tech-debt review of the Qt app** (step 35): `docs/tech-debt-2026-10-19.md`, 11 items; top three: split `handle_step_done` before step 23, extract the card/group menu dispatch from `shell.py` at step 14, settle the jobs/Activity boundary at step 22. The 09-21 review is marked superseded.
- `e39e71a` **claim a step when you start** (step 38): the coding skills mark their Status row `in progress` and push it first, and stop on a claimed step; the session-start hook skips claimed steps and lists them; a second-tab prompt in `docs/PROMPTS.md`. CI green on `e39e71a`, but qt-smoke still fails about half the time, so one green run doesn't prove 37 fixed.
- **In progress:** step 37 (the qt-smoke crash) in a coding tab, not yet claimed in its row; step 33 here: `ryos-planner`'s draft (Files lines, lanes cut by files, 8 questions) is back, Vũ answering.
- **Next:** 37, then 12 once P7 is placed.
- **Self-update is untested for real:** steps 4–10 each note "not run against real GitHub or a frozen build". Steps 11 and 12 are the first real tests.

## v2.4, by step

| Steps | What | State |
|---|---|---|
| 1–3 | OP-15, GR-33, SM-16 | ✅ `685d5aa`, `2e9867c`, `2a9c973` |
| 4–10 | A: find, download, verify, apply, roll back, Restart to update | ✅ `754568b` … `ef7600d` |
| 11 | A in `release_check`, docs | ✅ `d900395` |
| 31 | Harness | ✅ `96405b6` |
| 32 | Loop rules | ✅ `afa32f5` |
| 37 | Fix the qt-smoke crash on CI | in progress (10-19) |
| 33 | The plan as a graph | in progress: planner's draft back; Vũ's questions open |
| 35 | Tech-debt review of the Qt app | ✅ `de6108a` |
| 38 | Claim a step when you start | ✅ `e39e71a` |
| 12 | The early candidate (Vũ's gate) | waits for P7 (on hold) |
| 13–15, 34 | Backlog; frozen builds in CI | — |
| 16–24, 36 | B and C (lanes decided at step 33); type checks alongside | — |
| 25–28 | D: secrets, then triggers | — |
| 29, 30 | Test phase (with two RC-to-RC updates); release | — |

## Vũ to do

- [ ] **Back up the release key** in a second place, and put its passphrase in a password manager (left over from step 7).
- [ ] Step 31 left checks for you: approve the `ask`/`deny` lists as committed in `96405b6`; confirm a fresh session runs one command from each skill without a prompt; confirm auto-memory still works now that `C:\Users\Admin\.claude` is out of `additionalDirectories`. (The `gh release create` ask is seen at the next candidate.)
- [ ] At step 33: decide whether B and C run in parallel.

## Secretary skill and planner agent

In place since `2e15204`: `.claude/skills/ryos-secretary/SKILL.md` (`/ryos-secretary`) and `.claude/agents/ryos-planner.md`. `docs/STATUS.md` in the repo is the master.

## Found by the behaviour map

- **OP-15:** "Clear output between runs" did nothing → fixed, 2.4 step 1 (`685d5aa`).
- **GR-33:** a scheduled run outside its group's base folder got the outside-folder note → fixed, 2.4 step 2 (`2e9867c`).
- **SM-16:** starring, or maximising with full rows, left select mode → fixed, 2.4 step 3 (`2a9c973`).

## Open GitHub issues (checked 2026-10-19 11:54)

| # | Title | Where |
|---|---|---|
| 32 | Suggestion: check a run's status from MCP (a long pipeline looked hung to Claude); owner adds "anything to show in the RYOS app?" | 2.4 steps 20 (keep run output), 21 (agents read history, progress) and 22 (CLI and agent runs show in the window) |

Issues 29, 30 and 31 closed 2026-10-14 with v2.3.1.

## User feedback

- 2026-10-13: "Are you creating a design document? I keep seeing situations where working on A ends up breaking B." The answer is the behaviour map (step 13 ✅), plus the tester agent and the release check (step 15).

## Improvement plan (2026-10-19)

Vũ asked whether "prompts → agents → loops → graphs → harness" applies to RYOS. The review found the code and checks strong, and the rules around the agents weak. It is written up as the Claude Doc "RYOS improvement plan" (https://claude.ai/code/artifact/5bd1159f-9295-46b4-914d-d637c521a40a), and every recommendation was approved. In short:

- **Harness (31):** `ask` for release commands, `deny` for reverting secretary edits and for the key, hooks guarding the real data folder, an `env` block, a pruned allow list, CI checks for `__version__` and new comments.
- **Loops (32):** two fix rounds then stop, CI checked before and after each step, one continue prompt, more skill evals.
- **Graphs (33):** Gate lines, Files lines, the 14–15 Needs, and merge rules for parallel lanes.
- **Code health (34–36):** frozen builds in CI, a tech-debt review of the Qt app, type checks over `qtui`; step 29 proves two RC-to-RC updates.

## Next: v2.4

Steps 31 and 32, then part A's last two steps (11, 12). The early candidate (12) is the last manual install; every later candidate reaches Vũ through self-update. Then the backlog, B and C, D, and the test phase.

## Parked and dropped

- **Parked: a license.** Revisit if someone wants to contribute or reuse the code, or for code signing.
- **Parked: Windows code signing.** Needs an OSI license first. The cheapest fit is then Certum Open Source in the cloud, about €49 a year.
- **Dropped:** phone notifications, running RYOS from the phone, the `adb` "device plugged in" trigger, and a group-level "always exposed" flag.

## v2.3.0 lineup (released, frozen)

| Artifact | Variant ID | Contents |
|---|---|---|
| `RYOS-windows.zip` | `windows` | `RYOS.exe` + `ryos-cli.exe`, **no** MCP |
| `RYOS-windows-ai.zip` | `windows-ai` | `RYOS.exe` + `ryos-cli.exe` with MCP |
| `RYOS-agent.zip` | `agent` | `ryos-cli.exe` with MCP only, no window |
| `RYOS-portable.zip` | `portable` | Source + `uv`; MCP stays an optional extra |

## Test log: MCP builds (2026-10-09, Vũ's PC)

All checks passed: `windows-ai` MCP with no Python or `uv` on `PATH`; Claude Desktop and Claude Code list, run, poll and stop; history shows agent runs; `windows` refuses MCP with 125. One incident: a PowerShell `set APPDATA=...` doesn't set the environment, so test scripts landed in the real data (they were removed), and the real data was upgraded to schema v10.

## Decision log

- 2026-10-19 23:00: **A coding session claims its step when it starts** (2.4 step 38, after 37, before 12): it marks the Status row `in progress` and pushes that alone; the continue prompt and the session-start hook skip claimed steps; a session that stops writes why. `/add-ryos-feature`.
- 2026-10-19 22:40: **Work runs in parallel where the files don't collide:** step 35 (docs only) starts now beside 37, earlier than the Order's "beside the backlog"; 33 continues in the secretary session. A tab working beside another names its step instead of using the continue prompt, and commits only its own files.
- 2026-10-19 22:05: **The CI qt-smoke crash becomes 2.4 step 37, done next,** before step 12, so CI is a trustworthy gate for the early candidate. `/fix-ryos-bug`.
- 2026-10-19 14:07: **The improvement plan is approved as drafted** (all recommendations):
  - steps 31–36 join the 2.4 plan; 31 and 32 come before step 11, 33 runs alongside;
  - release commands are `ask`, for every session;
  - B and C run in parallel only where step 33's Files lines don't overlap; Vũ decides at step 33;
  - steps that change rows, the pane or the Running list need 14 and 15 (16, 17, 18, 19, 22, 23, 26 and 28);
  - frozen-build CI: the step 34 designer proposes how to handle the signature case; `release_check` on Vũ's PC stays the gate;
  - STATUS stays current through a daily `/ryos-secretary` run; no scheduled task writes to the repo;
  - `MCP_CLEAN_TEST.md` moves into `docs/` as the manual check against real Claude clients (staged by the secretary, committed with step 32);
  - the product scope of 2.4 is unchanged;
  - the claude.ai project copies of STATUS and PROMPTS are deleted; `docs/STATUS.md` is the only master.
- 2026-10-14 21:45: **A finished plan and its brief are archived to `docs/archive/` once the release is published, not before.** The Status table is the live record until then; nothing is deleted. The `release-2.3.1.md` archive is a prompt for a coding session (the secretary doesn't move files outside `docs/plans/`); the 2.4 archive is now in step 30's "Done when".
- 2026-10-14 20:50: **The 2.4 plan is approved as drafted** (`docs/plans/release-2.4.0.md`, 30 steps). Vũ accepted every planner recommendation:
  - the C2 on-failure step is dropped, because it has existed since v1.11.0;
  - OP-15, GR-33 and SM-16 are 2.4 steps 1–3, not a 2.3.2;
  - #32 gets stored run output, richer `get_run`, and CLI and agent runs shown read-only in the window;
  - Ed25519 is pure Python in every download;
  - the helper is the new build's `ryos-cli.exe apply-update`;
  - Vũ signs each candidate himself, with an extra `SHA256SUMS.txt.sig` asset;
  - an "Offer release candidates" option, and an early candidate after part A;
  - file triggers drop "run another";
  - agents never pass free text to pipeline parameters;
  - exports carry secret names, never values.
- 2026-10-14 19:45: **No minimum time on a release candidate.** The 24 h of use is dropped for every release, not only waived for 2.3.1: an RC is promoted once `release_check` passes, `ryos-tester` passes and Vũ has ticked his checklist. The RC pre-release, the tester and the checklist stay. `release-ryos`, `ryos-reviewer` and `ryos-secretary` still say 24 h and need a coding session to change them.
- 2026-10-13 21:21: **The secretary and planner become repo assets:** the `ryos-secretary` skill (talks to Vũ, keeps STATUS and the plans, commits only its own doc files, never pushes or writes code) and the `ryos-planner` agent (read-only, Opus at high effort, returns drafts and open questions).
- 2026-10-13 21:15: **STATUS is mirrored into the repo as `docs/STATUS.md`** (the repo is public). The claude.ai project copy stays the master. *(Superseded: the repo copy became the master with `2e15204`, and the project copy was retired on 2026-10-19.)*
- 2026-10-13 21:06: **Coding sessions run on Sonnet 5.5 at Medium,** with High for steps 15 and 6, and Opus 5.5 at High for planning. One fresh conversation per plan step.
- 2026-10-13 20:04: **Docs cleanup:** superseded docs removed, finished plans archived, links fixed (done: `d7ca83a`, `df179db`).
- 2026-10-13 19:48: **A release test phase, from 2.3.1 on (step 15).**
  - `release_check.py` is a hard gate.
  - Releases go out first as `vX.Y.Z-rcN` pre-releases. `ryos-tester` drives the built app, and Vũ uses the RC for at least a day. Then the same commit is promoted. *(The one-day minimum was dropped on 2026-10-14, see above.)*
  - A pre-release compares as older than its final.
  - Every escaped bug adds its check.
- 2026-10-13 19:44: **"Suggest a feature…" next to "Report a bug…"** (step 14).
- 2026-10-13 19:43: **Behaviour map in 2.3.1 (step 13).**
- 2026-10-13 19:28–19:30: **All plans shipped to the team.** #29, #30 and #31 go into 2.3.1.
- 2026-10-13 16:42: **Expose a group = tick what's in the group now;** refresh = run the same command again. CLI and window only, never MCP.
- 2026-10-13 11:54: **All new features go into 2.4,** with self-update. **No more release plans** beyond 2.3.1 and 2.4.
- 2026-10-13 11:51: **Phone features dropped.**
- 2026-10-13 11:44: **Publisher details:** Company "Zenitus (Lê Quang Vũ)", Copyright "© 2026 Lê Quang Vũ (Zenitus)".
- 2026-10-13 11:40: **No license for now**, so **no code signing in 2.4**.
- 2026-10-13 10:32: **Keep v2.3.0 published.**
- 2026-10-13: **Self-update is staged and still zip-based.** It asks before applying, keeps one `.previous` folder for rollback, and the install path never changes.
- 2026-10-08: The four-zip lineup, the no-AI build, the release review gate, the agent team, the A3 "compatible from" guard, and a single portable zip.
