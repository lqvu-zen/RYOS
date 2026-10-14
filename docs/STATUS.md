# RYOS: project status

Kept by the secretary (a claude.ai session attached to the RYOS project). Mirrored here as `docs/STATUS.md`, so every session can read it; the claude.ai project copy is the master. Coding sessions **read** it but don't edit it: plan progress goes in each plan's own Status table. Last updated 2026-10-14 20:50 (UTC+7).

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
| **2.3.1** (✅ published 2026-10-14) | #26, #27, #29, #30, #31 fixes; behaviour map; publisher details; expose a group; Suggest a feature; release test phase | `docs/plans/release-2.3.1.md` |
| **2.4** | **A** self-update · **B** failure patterns, time left, stats · **C** agents read history and logs, more pipeline logic · **D** secrets, file triggers | `docs/plans/release-2.4.0.md` (30 steps, approved 2026-10-14; from `release-2.4.0-brief.md`) |

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
- **Update 2026-10-14 (later):** **`v2.3.1` is published** (GitHub "Latest", 2026-10-14 12:48 UTC, from `57364b2`); #26, #27, #29, #30, #31 are closed. `main` is at `2088a68` (docs only since).
- **Next:** 2.4 step 1 (fix OP-15), in a fresh coding session. `docs/plans/release-2.4.0.md` is written and approved; steps 1–3 are fixes, 4–12 part A with an early candidate, then backlog, B/C, D, release.

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
| 6 | Release 2.3.1 via the RC flow | ✅ rc1 `4000e6d`; `v2.3.1` published from `57364b2` |

## Secretary skill and planner agent

In place since `2e15204`: `.claude/skills/ryos-secretary/SKILL.md` (`/ryos-secretary`) and `.claude/agents/ryos-planner.md`. `docs/STATUS.md` in the repo is now the master.

## Found by the behaviour map (planned)

- **OP-15:** the setting "Clear output between runs" does nothing → 2.4 step 1.
- **GR-33:** a scheduled run outside its group's base folder adds the outside-folder note → 2.4 step 2.
- **SM-16:** starring, or maximising with full rows, leaves select mode → 2.4 step 3.

## Open GitHub issues (checked 2026-10-14 19:45)

| # | Title | Where |
|---|---|---|
| 32 | Suggestion: check a run's status from MCP (a long pipeline looked hung to Claude); owner adds "anything to show in the RYOS app?" | 2.4 steps 20 (keep run output), 21 (agents read history, progress) and 22 (CLI and agent runs show in the window) |

Issues 29, 30 and 31 closed 2026-10-14 with v2.3.1.

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
