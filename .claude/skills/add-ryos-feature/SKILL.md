---
name: add-ryos-feature
description: 'Add or improve a feature in the RYOS desktop app the right way — end to end, following the project''s own conventions. Use this whenever the user wants to build a NEW capability OR enhance an existing one: a new setting, button, dialog, or DB column; a change to how scripts run, pipelines, the output panel, the Quick Run bar, notifications, or startup — and also when an existing feature needs a UX improvement, better edge-case handling, performance work, or a small refactor. Trigger even when the user just describes the behavior they want ("remember the last window size", "auto-clear output between runs", "make switching groups less janky") without saying "feature" or "implement". It carries RYOS''s architecture rules, the design→implement→test→review→commit workflow with per-phase model assignments, and the exact verification commands. Do NOT use it to fix a reproducible bug or crash (use fix-ryos-bug), for pure UI/UX design review (use review-ryos-ui), or to just run the app (use run-ryos).'
---

# Adding or improving a feature in RYOS

RYOS ("Run Your Own Scripts") is a Qt (PySide6) desktop app. All code lives in the `ryos/` package; the entry point is `ryos.__main__:main`, exposed as the `ryos` console-script in `pyproject.toml`. There is no shim file.

The point of this skill is that adding or improving a feature here is not just "write the code." A change that ignores the app's threading model, its settings/DB migration patterns, or its dependency direction will look correct and still break the running app or corrupt an existing user's database. So the workflow below front-loads understanding and ends with real verification — the app actually launching and the tests actually passing — before anything is committed.

Work through the phases in order. Don't skip the test/review phase to save time; a feature that isn't verified isn't done.

**You are the orchestrator.** You own the conversation with the user, the delegation below, the verification of everything you delegate, and the commit decision. You do **not** design the feature, write the implementation, run the tests, or review the final diff yourself — each of those goes to a fresh subagent with a pinned model, because an independent agent has no anchoring from this conversation and catches assumptions you've already absorbed. Design and review go to **Opus**; implement/test/fix goes to **Sonnet** (a different agent from you). Your own job is steps 1–2 (gather context), then spawning, verifying, and committing. This separation is the whole point — keep it even for small features.

## Recommended model per phase

Each phase has a default model chosen to match its demand — peak reasoning where correctness is decided, a fast strong coder for the implementation loop, and the orchestrator's own model for conversation and mechanics.

| Phase | Runs as | Default model | Why this model |
|---|---|---|---|
| 1. Understand | orchestrator | Sonnet 4.6 | Owns the conversation; needs sound judgment, not peak reasoning. |
| 2. Locate code | subagent | **Haiku 4.5** | Cheap, fast broad search; returns the code excerpts the orchestrator needs to brief design. |
| 3. Design | subagent | **Opus 4.8** | Hardest reasoning — architecture fit, edge cases, smallest correct change. |
| 4. Implement / test / fix | subagent | **Sonnet 4.6** | Excellent coder; fast and economical across the many tool calls in the fix loop. |
| 4b. Verify | orchestrator | Sonnet 4.6 | Re-runs tests and walks the checklist; the real correctness gate is the step-5 Opus review. |
| 5. Review | subagent | **Opus 4.8** | Catches subtle correctness and architecture-rule bugs the implementer can miss. |
| 6. Commit & push | orchestrator | Sonnet 4.6 | Mechanical. |
| 7. Report | orchestrator | Sonnet 4.6 | Light summarization. |

The delegated phases are pinned in their `Agent(... model: ...)` calls below (`haiku` for search, `opus` for design, `sonnet` for implementation, `opus` for review) — those are enforced. The orchestrator phases (1, 4b, 6, 7) all run on whatever model is driving this session; the skill can't switch that per phase, so **run it from a Sonnet session** for the intended balance. Opus as orchestrator works too but is slower and costlier for no gain on the mechanical phases.

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

### 1. Understand the request

Read what the user asked for and restate it to yourself in one sentence: what should the user be able to do after this ships that they can't do now? If a real ambiguity blocks the design (e.g. "remember settings" — which settings? per-script or global?), ask **one** focused question before writing code. Don't ask about things you can reasonably default.

This skill covers both **new capabilities** and **improvements to existing ones** — a UX rough edge, a missing edge case, performance, a small refactor. For an improvement, also pin down what's wrong with the current behavior and what "good" looks like as a concrete, observable outcome. If instead the user is reporting something genuinely **broken** — a crash, a freeze, wrong output they can reproduce — that's a bug: use `fix-ryos-bug`, which insists on a failing regression test first.

### 2. Locate the code (delegate broad search to a Haiku agent)

You need the current shape of the code to brief the design agent — but sweeping the package for the right functions is cheap, mechanical work. Hand it to a fast Haiku agent and keep your own context clean.

```
Agent({ description: "Locate code for <feature>", subagent_type: "general-purpose", model: "haiku", prompt: <brief> })
```

The brief gives the feature in one line plus the **Where things live** table, and asks the agent to:

- identify the file(s) and function(s) the change will touch;
- return the relevant code **excerpts verbatim** — the functions to be modified plus their direct callers/callees, each with a `file:line` reference — so they can be pasted straight into the design brief;
- report whether some or all of the capability **already exists** (a helper, a DB field, a settings key) that should be surfaced or extended rather than rebuilt. RYOS has more behind the scenes than the UI exposes — a request like "add a Copy button" may just need wiring to an existing `_copy_log` method, and catching that here avoids a redundant implementation.

End the brief with: *"Do not propose a design or edit anything — only locate and quote the relevant code."*

For a trivially small, obvious change you can skip the subagent and run one targeted Grep yourself:

```
Grep pattern="<relevant keyword>" path="ryos" output_mode="content" -n=true
```

Either way, you finish step 2 holding the code excerpts (and any "already exists" finding) that the design agent needs.

### 3. Design with a fresh Opus agent (always, before any code edits)

You do not design inline. Spawn a fresh Opus agent to produce the plan — even for a small feature — so the design is free of context bias from the feature-request conversation.

```
Agent({ description: "Design <feature>", subagent_type: "general-purpose", model: "opus", prompt: <self-contained brief> })
```

The brief must be self-contained — the design agent can't see this conversation. Paste in, verbatim: the user's request (one paragraph); the **Where things live** table and the entire **Architecture rules that always apply** section from this skill; the Grep/Read output from step 2 showing the current shape of the code (and anything you found in step 2 that already exists); and this instruction: *"Design the smallest correct implementation. Do NOT write code — produce only a plan with the sections below. If something is ambiguous, list it as a question for the user instead of guessing."*

The plan must answer: which **files** are edited (by path); which **functions/classes** are added or modified (one line of purpose each); any **schema/settings change** with its exact `_MIGRATIONS` entry (re-checking `PRAGMA table_info`) or new `_SETTINGS_DEFAULTS` key and `settings_schema` field; **UI placement** and behavior while a script runs; **thread-safety touch points** (anywhere a worker reaches the UI — only via the output queue or a `MainThreadInvoker`); the **regression surface** — which existing behaviors sit next to the change and must not break (run/stop, groups, output panel, drag-drop, pipeline editor, or specific tests); and **open questions**, if any. For an *improvement*, the plan also names the **root cause** of the current limitation, so the change targets the cause rather than the symptom.

A good plan is concrete and small. Example, for *"confirm before stopping a running script"*:

> - **Files:** `ryos/settings.py`, `ryos/settings_schema.py`, `ryos/qtui/shell.py`, `tests/test_ryos.py`
> - **Changes:** add `"confirm_stop": True` to `_SETTINGS_DEFAULTS`; add a BOOL `Field` for it in `settings_schema.py` (the Options dialog is generated from it); guard `_stop_job` in `qtui/shell.py` with `self.ask_yes_no` when the setting is on; unit-test the new field's coercion.
> - **Settings change:** new key `confirm_stop` (bool, default `True`). No DB change.
> - **UI placement:** checkbox in the Options dialog; the confirm prompt fires from the existing Stop control; no change to running-card behavior.
> - **Thread-safety:** none — the stop path is on the main thread.
> - **Risks:** don't double-prompt when stopping many scripts at once; default-on shouldn't surprise on first upgrade.

Present the plan to the user and proceed once they're on board (a "go ahead" with no comment counts as approval). Use a task list so each concrete change is visible during implementation.

### 4. Implement, test, and fix with a Sonnet agent

You do not write the implementation, run the tests, or launch the app yourself. Spawn a Sonnet agent (separate from you) to execute the approved plan, run the suite, smoke-test, and fix failures end-to-end. Offloading the whole implement–test–fix loop keeps your context clean for verification and the final review.

```
Agent({ description: "Implement <feature>", subagent_type: "general-purpose", model: "sonnet", prompt: <self-contained brief> })
```

The brief must include, verbatim: the **full approved plan** from step 3; the entire **Architecture rules that always apply** section (paste it — don't summarize; the full list is the contract); and the verification + acceptance criteria:

- `cd D:/Projects/RYOS && uv run --no-project --with pytest pytest -q` — the unit suite passes.
- `cd D:/Projects/RYOS && uvx ruff check . && uvx mypy --platform linux` — lint and types are clean.
- `cd D:/Projects/RYOS && uv run --no-project --with PySide6 python tests/qt_smoke.py` and `uv run python tests/session_smoke.py` — the real-widget checks and a whole session pass (both use a throwaway data folder; `QT_QPA_PLATFORM=offscreen` runs them without any window).
- The feature works end to end, and run/stop, groups, the output panel, drag-drop and the pipeline editor do not regress. Check what it looks like with the `run-ryos` driver's screenshots (off screen) — never by opening windows on the user's first screen. Add a check to `tests/qt_smoke.py` or `tests/session_smoke.py` when the feature is something those should keep catching.

Add this instruction: *"Read only the files in the plan plus the direct callers/callees you need; use targeted Grep and narrow Reads — don't scan the repo. Edit only inside `ryos/` (plus a focused new test in `tests/test_ryos.py` for testable non-UI logic, or a check in `tests/qt_smoke.py` / `tests/session_smoke.py`). Don't touch `pyproject.toml`, `build*.bat`, or `uv.lock`. Implement the plan, then run the unit tests and the smoke check; if anything fails, read the traceback, fix, and re-run until both are clean. Do not commit or push. Report the files changed, the final test result, and a one-line smoke-test note."*

When the agent returns, **verify before moving on** — this is the gate, not a formality. Run `git diff` and `cd D:/Projects/RYOS && uv run --no-project --with pytest pytest -q` yourself (cheap insurance against a green run that wasn't), then walk this checklist against the diff:

- [ ] Changes match the approved plan; nothing extra crept in.
- [ ] No worker thread touches a widget except via the output queue or a `MainThreadInvoker`.
- [ ] No PySide6 or `ryos.qtui` import inside a top-level module (only `__main__` may).
- [ ] Decision logic sits in a top-level module with a unit test; the Qt code only draws it.
- [ ] Any new DB column/table is a `_MIGRATIONS` entry that re-checks `PRAGMA table_info`.
- [ ] Run/stop updates cards in place — no full `reload()` on start/stop.
- [ ] New colours are palette keys used through the stylesheet; edits stay within `ryos/` (plus allowed tests).

If anything's off, fix it inline or send the Sonnet agent a follow-up via SendMessage. Mark each task complete only once verified.

### 5. Review with a fresh Opus agent (before commit)

Spawn an independent Opus agent to review the staged diff. A fresh agent has no bias from the planning step — it sees only the code and the brief.

```
Agent({ description: "Review <feature>", subagent_type: "general-purpose", model: "opus", prompt: <self-contained brief> })
```

The brief must include, verbatim: the original request (one paragraph); the approved plan from step 3; the full `git diff` of all modified files; the entire **Architecture rules that always apply** section; and this instruction: *"Review ONLY the diff and the files it modifies. If a change references a new external symbol you may open that file to confirm the API exists, but don't go hunting for unrelated issues. Look for correctness bugs, deviations from the plan, and architecture-rule violations in the changed code. Do NOT edit anything. Report findings as BLOCKERS, SUGGESTIONS, and OK. If there are no blockers, end with the line 'READY TO COMMIT'."*

If the reviewer reports BLOCKERS, fix them yourself or delegate back to the Sonnet agent via SendMessage, then re-review. Proceed only once the reviewer prints `READY TO COMMIT`.

### 6. Commit and push

Match the existing commit style (`git log --oneline -5`). Stage only the relevant files — never `scripts.db`, `dist/`, `build/`, `.env`, or `__pycache__`.

```bash
cd D:/Projects/RYOS && git add ryos/ <other touched files> && git commit -m "$(cat <<'EOF'
<short description of the feature>

<optional detail line>

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)" && git push
```

### 7. Report back

Tell the user, briefly: what was added and where it appears in the UI, which files under `ryos/` changed, the commit hash, and any known limitation or follow-up worth doing next.
