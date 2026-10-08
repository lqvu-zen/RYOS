---
name: fix-ryos-bug
description: 'Diagnose and fix a bug in the RYOS desktop app the right way — reproduce it, prove it with a failing test, fix the root cause, and verify nothing regressed. Use this whenever the user reports that RYOS misbehaves: a crash, traceback, freeze or hang, a script that won''t stop, output that doesn''t appear or floods, a setting that doesn''t stick, a card stuck in the running state, a broken scripts.db migration, drag-drop or pipeline glitches, or "X used to work and now doesn''t." Trigger even when the user just describes broken behavior ("the window goes white when a script prints a lot", "stop does nothing", "it forgets my last group") without using the word "bug" or pasting an error. This skill carries RYOS''s architecture rules, a reproduce→diagnose→fix→verify→review→commit workflow, per-phase model assignments, and the exact verification commands. Do NOT use it to ADD new capabilities (use add-ryos-feature), for pure UI/UX design feedback (use review-ryos-ui), or for just launching the app (use run-ryos).'
---

# Fixing a bug in RYOS

RYOS ("Run Your Own Scripts") is a Qt (PySide6) desktop app. All code lives in the `ryos/` package; the entry point is `ryos.__main__:main`, exposed as the `ryos` console-script in `pyproject.toml`.

The trap with bug-fixing here is fixing the *symptom* instead of the *cause*, or "fixing" something you never actually reproduced. Most RYOS bugs trace back to one of a few structural causes — a worker thread touching a widget directly, a migration that isn't guarded, a card refreshed the wrong way, a setting that never round-trips. So this workflow insists on two things before any code changes: reproduce the bug, and capture it in a **failing test** (where the logic is testable) so the fix is provable and can't silently regress later.

Work through the phases in order. A "fix" you didn't reproduce and can't demonstrate passing is not a fix.

**You are the orchestrator.** You own the conversation, the delegation below, the verification of everything you delegate, and the commit decision. You do **not** diagnose the root cause, write the fix, run the tests, or review the final diff yourself — each goes to a fresh subagent from `.claude/agents/` (diagnosis to `ryos-designer` in bug mode, the fix to `ryos-implementer`, review to `ryos-reviewer`), because an independent agent has no anchoring from this conversation and catches assumptions you've already absorbed. Your own job is steps 1–2 (reproduce, gather context), then spawning, verifying, and committing. Keep the separation even for a one-line fix.

## Who does each phase

| Phase | Runs as | Model (set in the agent file) | Why |
|---|---|---|---|
| 1. Reproduce & scope | orchestrator (you) | session model: run from Sonnet | Owns the conversation; pins down the repro and expected vs. actual. |
| 2. Locate code | `ryos-locator` | Haiku | Cheap, fast search; returns the suspect code excerpts for diagnosis. |
| 3. Diagnose + failing test | `ryos-designer` (bug mode) | Opus, high effort | Hardest reasoning: root-cause analysis and the minimal correct fix plan. |
| 4. Fix / verify | `ryos-implementer` | Sonnet (Opus, medium effort, when escalated) | Strong coder; fast and economical across the fix-and-re-run loop. |
| 4b. Verify | orchestrator (you) | session model | Re-runs tests and walks the checklist; the real gate is the step-5 review. |
| 5. Review | `ryos-reviewer` | Opus, high effort | Confirms the fix addresses the cause, not the symptom, with no new regressions. |
| 6. Commit & push | orchestrator (you) | session model | Mechanical. |
| 7. Report | orchestrator (you) | session model | Light summarization. |

Each role is defined once, in `.claude/agents/`: `ryos-locator`, `ryos-designer`, `ryos-implementer` and `ryos-reviewer`. Each file's frontmatter sets that role's model and effort, so **change a model there, not in this skill**, and don't pass `model` or `effort` in the calls below except to escalate. The orchestrator phases (1, 4b, 6, 7) run on whatever model drives this session, which the skill can't switch per phase, so **run it from a Sonnet session**. Opus as orchestrator works too, but it is slower and costlier for no gain on the mechanical phases.

**Escalate the implementer** to Opus at medium effort when a mistake is expensive or the fix loop will be deep. That covers database schema, migrations or the schema-version guard; packaging and freezing (`setup_cxfreeze.py`, cx_Freeze missing modules); and threading or the output queue:

```
Agent({ description: "...", subagent_type: "ryos-implementer", model: "opus", effort: "medium", prompt: <brief> })
```

**If the `ryos-*` agent types aren't listed**, for example because the session started before `.claude/agents/` existed, fall back to `subagent_type: "general-purpose"`. Pin the same model (`haiku`, `opus`, `sonnet`, `opus`), pass `effort: "high"` for the designer and reviewer, and paste that role's instructions from `.claude/agents/<name>.md` at the top of the brief.

**When the work is a step from a release plan** (`docs/plans/*.md`), paste that step's **Needs / Work / Done when** verbatim into the design, implement and review briefs. The reviewer checks every "Done when" item, and the step isn't finished until each one is met or marked "needs a human" (a clean-machine test, a real Claude Desktop connection). Report the "needs a human" items to the user.

## Where things live

| Concern | File |
|---|---|
| Paths, `_SETTINGS_DEFAULTS`, `_load_settings` / `_save_settings` | `ryos/settings.py` |
| What each setting is (the Options dialog is generated from it) | `ryos/settings_schema.py` |
| Windows "run at login" registry | `ryos/startup.py` |
| Toast notifications + GitHub update check | `ryos/notifications.py` |
| `ScriptDB` — all SQLite logic, schema, `_MIGRATIONS` | `ryos/db.py` |
| `detect_interpreter`, `build_command` | `ryos/interpreter.py` |
| Running jobs, pipelines, the output queue | `ryos/runner.py`, `ryos/jobs.py`, `ryos/job_controller.py` |
| Rules the window draws: card content, menus, sections, the script form, pipeline steps, output routing | `ryos/cardstyle.py`, `cardmenu.py`, `sections.py`, `scriptform.py`, `pipelinesteps.py`, `outputpanel.py` |
| Palettes, themes, contrast helpers | `ryos/themes.py` |
| Start-up: builds the window and passes it the real effects | `ryos/qtui/main.py` |
| `MainWindow` — tabs, search, menus, output panel, placement, tray | `ryos/qtui/shell.py` |
| `ScriptCard`, `PipelineCard` | `ryos/qtui/cards.py` |
| Script dialog / pipeline editor / Options / small dialogs | `ryos/qtui/scriptdialog.py`, `pipeline.py`, `dialogs.py`, `smalldialogs.py` |
| `JobBridge` (runs jobs, drains the queue on a `QTimer`) / Running list | `ryos/qtui/jobs.py`, `ryos/qtui/running.py` |
| Stylesheet — every colour, font and spacing rule | `ryos/qtui/stylesheet.py` |
| `__version__` | `ryos/__init__.py` |

## Architecture rules that always apply

These are the invariants that make RYOS work. Most "looked fine, broke in practice" bugs come from violating one of them, so internalize the *why*, not just the rule. **This is the canonical list** — when a brief below says to include the architecture rules, paste this whole section in verbatim rather than summarizing it; a partial list is how a rule quietly gets dropped.

- **Qt (PySide6) is the only toolkit.** The interface lives in `ryos/qtui/`. Don't pull in another toolkit or web tech.

- **Worker threads never touch widgets.** Script execution runs on a `threading.Thread`. Qt widgets belong to the UI thread; touching one from a worker crashes or corrupts the display, sometimes only later. Workers reach the UI in exactly two ways: by putting items on the job output queue (drained on the UI thread by `JobBridge`'s `QTimer`, through `JobController.pump()`), or by handing a callable to a `MainThreadInvoker` (see `qtui/quickrun.py`). `QTimer.singleShot` from a worker thread never fires — don't use it for the hop. This is the single most important rule.

- **Rules go in top-level modules, the window draws them.** What a card shows, what a menu offers, what a form accepts, how a pipeline proceeds — these live in toolkit-free modules (`cardstyle`, `cardmenu`, `scriptform`, `pipelinesteps`, `sections`, ...) with unit tests, and `ryos/qtui/*` only draws them. Put new decision logic there, not in a widget method.

- **Dependency direction is one-way: `qtui/*` → top-level modules.** `ryos/db.py`, `ryos/settings.py` and every other top-level module must never import PySide6 or `ryos.qtui`. That is what keeps the core testable without a display or Qt. The only exception is `ryos/__main__.py`.

- **Real effects are passed in.** The window saves settings, reconfigures the log, shows toasts, checks for updates, writes run-at-login and quits only through constructor arguments that do nothing by default, and asks the user only through attributes (`ask_yes_no`, `ask_text`, `warn`, `run_dialog`, ...). `ryos/qtui/main.py` passes the real ones. A new effect follows the same pattern, so tests can build windows without side effects.

- **Don't rebuild all the cards on run/stop.** A run's outcome reaches cards in place (`set_last_status` / `set_last_run`, driven by `_refresh_card_statuses` in `shell.py` — including the favourite copies). A full `reload()` tears down every card, loses scroll position and select-mode ticks. Reuse the in-place path.

- **Settings go through `_SETTINGS_DEFAULTS` and `settings_schema`.** A new user-facing setting is a key in `_SETTINGS_DEFAULTS` in `ryos/settings.py` (so old settings files still load via `{**_SETTINGS_DEFAULTS, **stored}`), and a `Field` in `ryos/settings_schema.py` if the user should change it — the Options dialog is generated from those fields, and `coerce()` turns what was typed into a usable value.

- **Database changes go through `_MIGRATIONS`.** `_ensure_baseline()` in `ryos/db.py` is frozen. A new column or table is a new entry in `_MIGRATIONS`, keyed by the `PRAGMA user_version` it upgrades to, and it re-checks `PRAGMA table_info` so it is safe to run twice (SQLite has no `ADD COLUMN IF NOT EXISTS`). Add query logic as `ScriptDB` methods, not raw SQL in the UI. Don't widen `db.get()` or `list_pipeline_steps()` rows — call sites slice them, and `TestRowWidthsArePinned` pins the widths.

- **Colours come from the palette.** Style through `ryos/qtui/stylesheet.py` by object name; text colours through `drawn_colors()` so they stay legible in every theme. A genuinely new colour is a palette key in `themes.py`, not a hex literal at a widget.

- **Never open windows on the user's first screen.** They work there. Screenshots use the `run-ryos` driver (renders off screen); the smokes' `--visible` uses the second screen.

- **Comments explain WHY, not WHAT.** The codebase is sparing with comments. Add one only when the reason for a line is non-obvious; don't narrate what the code plainly does.

- **Don't touch `__version__`.** Leave `ryos/__init__.py` alone — the version is bumped only when cutting a release (see the `release-ryos` skill), never per change, and carries no `-dev` suffix.

## The workflow

### 1. Reproduce and scope the bug

You can't fix what you can't see fail. Pin down, from the user, the exact steps, the expected behavior, and the actual behavior (and the full traceback if there is one — ask for it rather than guessing). Then reproduce it:

- If it's logic (a `ScriptDB` method, settings round-trip, interpreter/param parsing), reproduce with a quick `python3 -c ...` or by reading the failing path — the cheapest repro.
- If it's runtime/UI behavior (freeze, stuck card, output glitch), use the `run-ryos` skill to launch and drive the app and capture screenshots of the broken state. If there's no display, say so and reason from the code + traceback.

If you genuinely cannot reproduce it, say so and ask the user for more detail (OS, exact script, settings) instead of speculating a fix. State the confirmed repro in one sentence before moving on.

### 2. Locate the code (delegate broad search to a Haiku agent)

Hand the search for the suspect code to a fast Haiku agent and keep your own context clean.

```
Agent({ description: "Locate code for <bug>", subagent_type: "ryos-locator", prompt: <brief> })
```

The brief gives the bug and its repro in a line or two plus the **Where things live** table, and asks the agent to: find the file(s)/function(s) on the failing path; return the relevant code **excerpts verbatim** with `file:line` references (the suspect function plus its callers/callees) so they can be pasted into the diagnosis brief; and flag anything that looks like a violated architecture rule near the failure. End with: *"Do not propose a fix or edit anything — only locate and quote the relevant code."*

### 3. Diagnose the root cause and write a failing test (fresh Opus agent)

You do not diagnose inline. Spawn a fresh Opus agent to find the *root cause* (not the symptom) and produce the fix plan.

```
Agent({ description: "Diagnose <bug>", subagent_type: "ryos-designer", prompt: <self-contained brief> })
```

The brief is self-contained — paste, verbatim: the confirmed repro and expected/actual behavior; any traceback; the **Where things live** table and the entire **Architecture rules that always apply** section; the code excerpts from step 2; and this instruction: *"Find the ROOT CAUSE, not the symptom — explain why the bug happens, tracing it to a specific line or interaction. Then specify the smallest correct fix. Where the bug is in testable non-UI logic, write a unit test (in the `TestScriptDB*` style of tests/test_ryos.py) that FAILS on the current code and will PASS once fixed — this proves the bug and guards against regression. For a purely visual bug, describe the run-ryos check that demonstrates it instead. Do NOT write the fix; produce: root cause, the failing test (or visual check), the fix plan (files + functions + one-line purpose), and risks/regressions to watch. List any open questions instead of guessing."*

A good diagnosis is specific. Illustrative shape (not a real RYOS bug): *root cause — the stop handler calls `proc.terminate()` but never flips the card's running flag, so a card whose process exits between polls stays "running"; failing test — assert the card state resets after the done-event is drained; fix — set the state in the done branch of the queue drain; risk — make sure normal completion still clears it.*

Present the diagnosis and fix plan to the user; proceed once they're on board (a "go ahead" counts as approval). Use a task list for the concrete changes.

### 4. Fix and verify (Sonnet agent)

You do not write the fix or run the tests yourself. Spawn a Sonnet agent to apply the plan, make the failing test pass, and confirm nothing else broke.

```
Agent({ description: "Fix <bug>", subagent_type: "ryos-implementer", prompt: <self-contained brief> })
```

The brief includes, verbatim: the root cause and fix plan from step 3; the failing test to add (or the visual check); the entire **Architecture rules that always apply** section (paste it — the fix must not trade one violation for another); and the acceptance criteria:

- `cd D:/Projects/RYOS && uv run --no-project --with pytest pytest -q` — the new regression test passes and the whole suite is green.
- `cd D:/Projects/RYOS && uvx ruff check . && uvx mypy --platform linux` — lint and types are clean.
- `cd D:/Projects/RYOS && uv run --no-project --with PySide6 python tests/qt_smoke.py` and `uv run python tests/session_smoke.py` — the real-widget checks and a whole session pass (both use a throwaway data folder; `QT_QPA_PLATFORM=offscreen` runs them without any window).
- The original repro no longer reproduces, and run/stop, groups, output panel, drag-drop, and the pipeline editor still work. Reproduce through the window's hooks (the session smoke shows the pattern) or the `run-ryos` driver's screenshots — never by opening windows on the user's first screen. If the bug is something a smoke should keep catching, add the check there too.

Add: *"Read only the files in the plan plus direct callers/callees; don't scan the repo. Edit only inside `ryos/`, plus the regression test in tests/test_ryos.py. Don't touch pyproject.toml, build*.bat, or uv.lock. Apply the fix, add the failing test, then run the suite and the repro check; if anything fails, read the traceback, fix, and re-run until clean. Do not commit or push. Report files changed, the regression test going red→green, the final suite result, and a one-line repro-gone note."*

When the agent returns, **verify before moving on** — this is the gate. Run `git diff` and re-run the suite yourself, then check the diff:

- [ ] The regression test actually fails on the old code and passes on the fix (not a test written to trivially pass).
- [ ] The fix addresses the root cause from step 3, not just the surface symptom.
- [ ] No worker thread touches a widget except via the output queue or a `MainThreadInvoker`.
- [ ] No PySide6 or `ryos.qtui` import inside a top-level module; any DB change is a `_MIGRATIONS` entry.
- [ ] Run/stop still updates cards in place — no full `reload()` on start/stop.
- [ ] Edits stay within `ryos/` plus the one regression test.

Fix inline or send the Sonnet agent a follow-up via SendMessage if anything's off. Mark tasks complete only once verified.

### 5. Review before commit (fresh Opus agent)

Spawn an independent Opus agent to review the staged diff.

```
Agent({ description: "Review fix for <bug>", subagent_type: "ryos-reviewer", prompt: <self-contained brief> })
```

The brief includes, verbatim: the original bug + repro; the root cause and plan from step 3; the full `git diff`; the entire **Architecture rules that always apply** section; and: *"Review ONLY the diff and the files it modifies. Confirm the change fixes the stated root cause (not just the symptom), that the regression test genuinely covers the bug, and that no architecture rule is violated or new regression introduced. Do NOT edit anything. Report BLOCKERS, SUGGESTIONS, and OK. If there are no blockers, end with 'READY TO COMMIT'."*

If there are BLOCKERS, fix them or delegate back via SendMessage, then re-review. Proceed only on `READY TO COMMIT`.

### 6. Commit and push

Match the existing commit style (`git log --oneline -5`). Stage only the relevant files — never `scripts.db`, `dist/`, `build/`, `.env`, or `__pycache__`.

```bash
cd D:/Projects/RYOS && git add ryos/ tests/test_ryos.py && git commit -m "$(cat <<'EOF'
fix: <short description of the bug>

<root cause in a line; what changed>

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)" && git push
```

### 7. Report back

Tell the user, briefly: what was broken and the root cause, the fix and which files under `ryos/` changed, the regression test added, the commit hash, and anything to watch for.
