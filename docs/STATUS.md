# RYOS: project status

Kept by the secretary (a claude.ai session attached to the RYOS project). Mirrored here as `docs/STATUS.md`, so every session can read it; the claude.ai project copy is the master. Coding sessions **read** it but don't edit it: plan progress goes in each plan's own Status table. Last updated 2026-10-13 21:30 (UTC+7).

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

## Where we are (21:20)

- **v2.3.0** is the latest release (2026-10-09).
- **`main` = `origin/main` at `9c66086`** (20:50). Since `f5bf71b`:
  - `1b6a100` **#29a fixed:** heavy output no longer freezes the window;
  - `d7ca83a`, `df179db` **docs cleanup:** superseded docs removed, finished plans moved to `docs/archive/`, links fixed;
  - `649dfa3` **#30 fixed:** a Quick Run of a new file shows its row again. The refresh had been lost in the Qt port of 2.0.0;
  - `9c66086` **behaviour map** `docs/BEHAVIOUR.md` (266 entries, 16 areas), wired into the skills, agents and `CLAUDE.md`; `session_smoke` now runs both layouts.
- **Uncommitted, being worked on:** most likely step 10 (log location) and step 14 (Suggest a feature). `bugreport.py`, `settings.py`, `cli.py` and the tests are modified.

## v2.3.1, in working order

| Step | What | State |
|---|---|---|
| 1–5 | Vũ on 2.3.0; #26; #27; loose ends | ✅ |
| 9 | #29a freeze | ✅ `1b6a100` |
| 11 | #30 Quick Run | ✅ `649dfa3` |
| 13 | Behaviour map | ✅ committed `9c66086`. **Waiting on Vũ's review of `docs/BEHAVIOUR.md`.** It found **two new bugs**, see below. |
| 10 | #29b log easy to find | in progress? |
| 14 | Suggest a feature… | in progress? |
| 7 | Publisher details, build commit in `--version`, "Check your download" | — |
| 8 | Expose a group | — |
| 12 | #31 newest log tab first | — |
| 15 | Release test phase (`release_check.py` gate, RC pre-release, `ryos-tester`, manual checklist, escape rule) | — |
| 6 | Release 2.3.1 via the RC flow | needs 7–15 |

## Secretary skill and planner agent (drafted 2026-10-13 21:30)

Staged in `docs/plans/secretary/` (uncommitted). A coding session copies them into place by following its `APPLY.md`, after the current step:
- `.claude/skills/ryos-secretary/SKILL.md`: this role, run as `/ryos-secretary` in its own Claude Code tab (Sonnet 5.5, Medium);
- `.claude/agents/ryos-planner.md`: a read-only Opus planner at high effort, called by the skill for heavy planning.

Once it works, `docs/STATUS.md` in the repo is the only master and the claude.ai project copy is deleted.

## Found by the behaviour map (not yet planned)

- **OP-15:** the setting "Clear output between runs" does nothing.
- **GR-33:** a scheduled run of a script outside its group's base folder adds the outside-folder note.

**Vũ to decide:** fix both in 2.3.1 (suggested, as small `/fix-ryos-bug` steps), or move them to 2.4.

## Open GitHub issues (checked 2026-10-13 19:30)

| # | Title | Where |
|---|---|---|
| 29 | I can't find the app log to report bug (and the freeze) | 2.3.1 steps 9 ✅ and 10 |
| 30 | Quick run function didn't auto add new script | 2.3.1 step 11 ✅ (close on release) |
| 31 | Suggestion: reverse the order for the logs' tabs | 2.3.1 step 12 |

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

- 2026-10-13 21:21: **The secretary and planner become repo assets:** the `ryos-secretary` skill (talks to Vũ, keeps STATUS and the plans, commits only its own doc files, never pushes or writes code) and the `ryos-planner` agent (read-only, Opus at high effort, returns drafts and open questions).
- 2026-10-13 21:15: **STATUS is mirrored into the repo as `docs/STATUS.md`** (the repo is public). The claude.ai project copy stays the master.
- 2026-10-13 21:06: **Coding sessions run on Sonnet 5.5 at Medium,** with High for steps 15 and 6, and Opus 5.5 at High for planning. One fresh conversation per plan step.
- 2026-10-13 20:04: **Docs cleanup:** superseded docs removed, finished plans archived, links fixed (done: `d7ca83a`, `df179db`).
- 2026-10-13 19:48: **A release test phase, from 2.3.1 on (step 15).**
  - `release_check.py` is a hard gate.
  - Releases go out first as `vX.Y.Z-rcN` pre-releases. `ryos-tester` drives the built app, and Vũ uses the RC for at least a day. Then the same commit is promoted.
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
