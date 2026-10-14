# RYOS: project status

Kept by the secretary (a claude.ai session attached to the RYOS project). Mirrored here as `docs/STATUS.md`, so every session can read it; the claude.ai project copy is the master. Coding sessions **read** it but don't edit it: plan progress goes in each plan's own Status table. Last updated 2026-10-14 19:45 (UTC+7).

## Roles

- **Vũ ("Zenitus", maintainer):** decides, merges, picks version numbers, uses each release candidate, runs the manual checks, reviews the behaviour map.
- **Planner:** an Opus session in Claude Code at high effort, for planning only, e.g. turning `docs/plans/release-2.4.0-brief.md` into a plan.
- **Coding sessions:** Claude Code in VS Code running `add-ryos-feature` / `fix-ryos-bug` / `release-ryos` with the `ryos-*` agents (locator, designer, implementer, reviewer, and `ryos-tester` from 2.3.1 step 15).
- **Secretary:** keeps this status, the decision log and the open items; checks GitHub issues and the repo; writes plan steps when Vũ decides something. Doesn't write code or commit.

## Working practices

- **Coding sessions:** one fresh conversation per plan step (`Ctrl+Shift+Esc`, *Open in New Tab*), on **Sonnet 5.5, Medium**. Use **High** for step 15 (the release test phase) and step 6 (the release). Planning sessions run on **Opus 5.5, High**. The agents' models come from `.claude/agents/`, whatever the main thread uses. The prompt to continue:
  > Read docs/plans/release-2.3.1.md and continue with the next open step in its Order. Update the Status table when it's done.
- **The secretary:** start a fresh secretary conversation when the current one gets long, or after a release. The opening message:
  > You're my RYOS project secretary (not planner, no code). Read claude/STATUS.md and the other project docs, check GitHub (lqvu-zen/RYOS) and my PC (D:\Projects\RYOS) for anything newer, then tell me where we are.
- **Secretary edits to repo files** (`docs/plans/*.md`, `docs/STATUS.md`) arrive uncommitted. Coding sessions commit them with their next change and never revert them. One edit was reverted on 10-13.

## Releases: only two plans

| Release | What | Plan |
|---|---|---|
| **2.3.1** (in progress) | #26, #27, #29, #30, #31 fixes; behaviour map; publisher details; expose a group; Suggest a feature; release test phase | `docs/plans/release-2.3.1.md` (steps 1–15 committed) |
| **2.4** | **A** self-update · **B** failure patterns, time left, stats · **C** agents read history and logs, more pipeline logic · **D** secrets, file triggers | `docs/plans/release-2.4.0-brief.md`. The planner turns it into `release-2.4.0.md` after 2.3.1 ships. |

## Where we are (2026-10-14 19:45)

- **v2.3.0** is still the latest published release. **`v2.3.1-rc1`** is a pre-release (2026-10-14 00:32, from `4000e6d`): `release_check` passed (22 cases), `ryos-tester` **PASS**, Vũ ticked the whole checklist.
- **`main` = `origin/main` at `ae8c470`.** Since `9c66086`:
  - `d4cdced` **#29b:** Help → Open log folder; Report a bug shows the log's path (step 10);
  - `2e15204`, `f9a96da` the secretary skill and planner agent are in the repo;
  - `e4ed9f3` **Suggest a feature…** next to Report a bug… (step 14);
  - `c080364` **publisher details** on both exes, the build's commit in `--version`, "Check your download" (step 7);
  - `0caecbb` Vũ approved the behaviour map (step 13);
  - `396931e` **expose a whole group** from the CLI, the group menu and select mode (step 8);
  - `df0d4ef` **#31:** a run's output tab opens right after All (step 12);
  - `49a3b64` **the release test phase:** `release_check.py`, the RC flow, `ryos-tester` (step 15);
  - `5dd72c5` fix: the select bar stays readable with the agent buttons (the tester's first FAIL);
  - `4000e6d` 2.3.1-rc1; `57364b2` **Release 2.3.1** (the version commit for promotion); `ae8c470` checklist ticked, 24 h waived.
- **Next:** the coding session publishes `v2.3.1` from `57364b2` (no `v2.3.1` tag or GitHub release yet). Then close #29, #30, #31.

## v2.3.1, in working order

| Step | What | State |
|---|---|---|
| 1–5 | Vũ on 2.3.0; #26; #27; loose ends | ✅ |
| 9 | #29a freeze | ✅ `1b6a100` |
| 11 | #30 Quick Run | ✅ `649dfa3` |
| 13 | Behaviour map | ✅ `9c66086`, approved `0caecbb` |
| 10 | #29b log easy to find | ✅ `d4cdced` |
| 14 | Suggest a feature… | ✅ `e4ed9f3` |
| 7 | Publisher details, build commit in `--version`, "Check your download" | ✅ `c080364` |
| 8 | Expose a group | ✅ `396931e` |
| 12 | #31 newest log tab first | ✅ `df0d4ef` |
| 15 | Release test phase | ✅ `49a3b64` (+ fix `5dd72c5`) |
| 6 | Release 2.3.1 via the RC flow | rc1 ✅ `4000e6d`; promotion commit `57364b2`, **publish pending** |

## Secretary skill and planner agent

In place since `2e15204`: `.claude/skills/ryos-secretary/SKILL.md` (`/ryos-secretary`) and `.claude/agents/ryos-planner.md`. `docs/STATUS.md` in the repo is now the master.

## Found by the behaviour map (not yet planned)

- **OP-15:** the setting "Clear output between runs" does nothing.
- **GR-33:** a scheduled run of a script outside its group's base folder adds the outside-folder note.

**Vũ to decide:** 2.3.1 has shipped its RC without them, so they go to 2.4 unless Vũ wants a 2.3.2.

## Open GitHub issues (checked 2026-10-14 19:45)

| # | Title | Where |
|---|---|---|
| 29 | I can't find the app log to report bug (and the freeze) | 2.3.1 steps 9 ✅ and 10 ✅ (close on release) |
| 30 | Quick run function didn't auto add new script | 2.3.1 step 11 ✅ (close on release) |
| 31 | Suggestion: reverse the order for the logs' tabs | 2.3.1 step 12 ✅ (close on release) |
| 32 | Suggestion: check a run's status from MCP (a long pipeline looked hung to Claude) | **New, not triaged.** Suggested: 2.4 part C (agents read history and logs) |

## User feedback

- 2026-10-13: "Are you creating a design document? I keep seeing situations where working on A ends up breaking B." The answer is the behaviour map (step 13 ✅), plus the tester agent and the release check (step 15).

## Next: v2.4

One release in four parts:

- **A, self-update**, first;
- **B and C** in parallel;
- **D**: secrets before triggers.

It ships through the new test phase, and self-update gets a `release_check.py` case over each of the four downloads. The behaviour map's untested backlog also feeds 2.4. Before part A2, Vũ needs an Ed25519 key pair; only he holds the private key, with a backup.

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

- 2026-10-14 19:45: **No minimum time on a release candidate.** The 24 h of use is dropped for every release, not only waived for 2.3.1: an RC is promoted once `release_check` passes, `ryos-tester` passes and Vũ has ticked his checklist. The RC pre-release, the tester and the checklist stay. `release-ryos`, `ryos-reviewer` and `ryos-secretary` still say 24 h and need a coding session to change them.
- 2026-10-13 21:21: **The secretary and planner become repo assets:** the `ryos-secretary` skill (talks to Vũ, keeps STATUS and the plans, commits only its own doc files, never pushes or writes code) and the `ryos-planner` agent (read-only, Opus at high effort, returns drafts and open questions).
- 2026-10-13 21:15: **STATUS is mirrored into the repo as `docs/STATUS.md`** (the repo is public). The claude.ai project copy stays the master.
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
