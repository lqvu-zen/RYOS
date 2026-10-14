# RYOS 2.4 — Brief for the planner

_Written 2026-10-13 by the secretary session from Vũ's decisions. The planner turns this into **one** plan, `docs/plans/release-2.4.0.md`; Vũ wants as few release plans as possible. 2.4 starts **after 2.3.1 ships** (`docs/archive/release-2.3.1.md`)._

## What 2.4 is

Everything after 2.3.1 goes into one release, in four parts:

- **A. Self-update** (staged, still zip-based).
- **B. Smarter runs:** failure patterns, time left, stats.
- **C. Agents and pipelines:** agents read history and logs; more pipeline logic.
- **D. Automation:** secrets, file triggers.

**Order:** A first, because it changes the release process and is the riskiest. Every later 2.4 dev build can then be updated through it, which tests it for real. B and C are independent of each other and can run in parallel worktrees. In D, secrets come before triggers. The planner may reorder within these rules.

**Not in 2.4:**
- phone notifications and running RYOS from the phone (dropped);
- the `adb` "device plugged in" trigger (dropped with the phone items);
- a license and Windows code signing (parked).

---

## Part A — Self-update

Vũ chose a full self-update over a one-click download that leaves the swap to the user, and over moving to an installer framework. RYOS already has most of the pieces, and changing how RYOS is distributed isn't worth it.

### What already exists
- **The update check.** `ryos/notifications.py` compares `__version__` with the latest GitHub tag (`_fetch_latest_release` → `(tag, html_url)`, then `update_status`). Today it only opens the release page. `banner_text` and `version_check_text` name the zip.
- **The variants.** `ryos/buildinfo.py` has `variant()`, `DOWNLOADS` and `BUILD_FOLDERS`. The names and IDs are frozen since 2.3.0: `windows`, `windows-ai`, `agent`, `portable`.
- **The checksums.** `build_release.py` writes `SHA256SUMS.txt` for every release.
- **The shared data folder.** `%APPDATA%\RYOS` is used by every download. The A3 "compatible from" guard lets an older build open data a newer one upgraded, unless a migration raised the number.
- **`ryos-cli version --check`**, for RYOS Agent.

### A1 — Download and verify
When an update exists, download the zip for **this** variant, plus `SHA256SUMS.txt`, into `%LOCALAPPDATA%\RYOS\updates\<version>\`, and verify the hash. The banner says "ready to install".
**Done when** a test against a fake release (a local folder or a local HTTP server, never real GitHub) shows: the right asset is chosen per variant, a wrong hash is rejected and the file deleted, and an interrupted download resumes or restarts cleanly.

### A2 — Signed updates
At release time, `SHA256SUMS.txt` is signed with an **Ed25519** private key that Vũ keeps off the repo and off CI. Each build carries the public key and **refuses** an update whose signature is missing or wrong. `release-ryos` gets a signing step, and the release-review gate checks the signature. Optionally, `ryos-cli verify <zip>` runs the same check on a zip downloaded by hand.
**Done when** a tampered zip, a tampered `SHA256SUMS.txt`, and a missing signature are each refused with a clear message, in tests and on a real build.

### A3 — Apply and roll back
A helper process that is **not** the running exe applies the update. One option is a temp copy of `ryos-cli.exe` running `apply-update`. The helper:
1. waits for RYOS to exit;
2. extracts the new zip beside the install folder;
3. renames the current folder to `<folder>.previous`;
4. renames the new folder into place;
5. restarts RYOS.

The **install path must stay the same**, because run-at-login (`ryos/startup.py`), shortcuts and Claude's MCP config all point at it. "Roll back" swaps the folders back.
**Done when** an update and a rollback both work on a real build in a throwaway folder, the exe path is unchanged afterwards, and a failure at any step leaves a working RYOS (old or new, never half of each).

### A4 — Edge cases
- **Scripts running or about to run:** don't apply while a run is active. Ask, or wait for the end of the run.
- **`ryos-cli.exe mcp` held open by Claude:** say so, and offer to apply at the next start.
- **RYOS Agent:** `ryos-cli update` and `ryos-cli update --rollback`.
- **Portable:** never self-updates; keep today's notice.
- **Install folder not writable:** say so and fall back to opening the release page.
- **Rollback across a raised "compatible from" number:** warn, and don't roll back silently.

**Done when** each case has a test or a documented manual check, and the docs explain updating and rolling back. Note for the release notes: 2.3.x users need one manual update to reach 2.4.

### Decisions for part A

| # | Question | Default |
|---|---|---|
| U1 | Windows code signing | **Not in 2.4** (decided 2026-10-13: no license for now, and the cheap or free options need one). SmartScreen warnings stay; leave room for a signing step later. |
| U2 | Apply automatically or ask? | **Ask:** "Update ready — Restart to update", with *Later* |
| U3 | Settings | An option to turn automatic downloading off. The check itself stays. |
| U4 | How many old versions to keep | One (`.previous`) |
| U5 | Key custody | Only Vũ holds the private key, with a backup. The plan needs a "key lost" note: a new key pair means one manual update for everyone. |

### Open questions for part A
- How to verify Ed25519 in the no-MCP `windows` build without adding weight: pure Python, or Windows CNG through `ctypes`.
- What runs the helper: a temp copy of `ryos-cli.exe`, or a tiny dedicated exe.
- Antivirus locking or quarantining files during the swap, made more likely by unsigned exes.

---

## Part B — Smarter runs

All three read what RYOS already records (output and Run history).

### B1 — Failure patterns
A per-script rule: "treat the run as failed if the output matches …". It catches tools that exit 0 after printing `error:`. Rules are regexes stored per script; an optional default set covers `error:`, `FAILED` and `Traceback`. The same rules highlight error and warning lines in the output panel. A run marked failed by a rule says which rule and which line, in History and for agents. The schema change is a new `_MIGRATIONS` entry; `db.get()` rows are not widened.
**Done when** a script that exits 0 but prints a matching line is recorded as failed with the matching line shown, a pipeline's step policy treats it as a failure, and the highlights work in every theme.

### B2 — Time left
A running job shows "usually 12 min, about 4 left". The estimate comes from the median of the last N successful runs, and appears only with enough history.
**Done when** the estimate appears after enough runs and not before, and stays sensible for a run that goes over (e.g. "taking longer than usual").

### B3 — Stats
Per script and pipeline: success rate, duration trend, and the pipeline step that fails most often. It reads existing history, with no new tracking.
**Done when** the numbers match a hand count on test data.

---

## Part C — Agents and pipelines

### C1 — Agents read history and logs
New **read-only** MCP tools: list past runs (filter by script, result and time), and read a past run's output in pages, like `get_run`. They are limited to scripts and pipelines marked **Available to agents**. MCP still never changes the allow-list (2.3.0 decision A2), and output stays text.
**Done when** "why did last night's run of X fail?" can be answered from the real log, and the tools refuse runs of scripts not available to agents. `tests/test_mcpserver.py` covers both.

### C2 — More pipeline logic
- An **on-failure step:** runs only if an earlier step failed, such as cleanup or a report script.
- **Passing a value between steps:** for example a build path printed by step 1 and used by step 3. The designer picks the mechanism, e.g. a marked output line or a file.
- **Pipeline-level parameters,** asked once at the start.

Pipelines are still authored in the window (A6). The schema changes go through `_MIGRATIONS`.
**Done when** each of the three has tests, the pipeline editor supports them, and existing pipelines behave exactly as before (the migration doesn't change them).

---

## Part D — Automation

### D1 — Secrets
Store tokens and passwords in Windows Credential Manager, and give them to scripts as environment variables. They never appear in parameters, exports, history, logs or MCP output: mask them if a script prints one.
**Done when** a secret reaches the script, never shows up in any of those places (including an export file), and deleting a script offers to delete its secrets.

### D2 — File triggers
Run a script or pipeline when a file appears in or changes inside a watched folder. It debounces, so a file still being copied doesn't fire it early. A rule covers what happens if the job is already running (skip, queue or run another). Triggered runs show in History as started by *Trigger*. "Run when RYOS starts" already exists (*Startup*). A trigger works only while RYOS is running (window or tray), as schedules do.
**Done when** dropping a file fires the job once, a slow copy fires once at the end, a burst of files follows the chosen rule, and triggers survive a restart.

---

## Rules (all parts)

Follow `CLAUDE.md`'s rules:
- decision logic goes in toolkit-free top-level modules with unit tests, and the window only draws it;
- real effects (network, file swap, restart, Credential Manager, file watching) are passed in;
- DB changes are `_MIGRATIONS` entries, and accessor rows are not widened;
- worker threads never touch widgets.

Use `add-ryos-feature` for each step. Escalate the implementer to Opus at medium effort for A2, A3, D1 and any DB migration.

**Release check:** the step-13-style check for 2.4 covers all four parts, and the self-update path over each of the four downloads.

## Version

2.4.0, after 2.3.1. Vũ names the number at release.
