---
name: add-ryos-feature
description: 'Add or improve a feature in the RYOS desktop app the right way — end to end, following the project''s own conventions. Use this whenever the user wants to build a NEW capability OR enhance an existing one: a new setting, button, dialog, or DB column; a change to how scripts run, pipelines, the output panel, the Quick Run bar, notifications, or startup — and also when an existing feature needs a UX improvement, better edge-case handling, performance work, or a small refactor. Trigger even when the user just describes the behavior they want ("remember the last window size", "auto-clear output between runs", "make switching groups less janky") without saying "feature" or "implement". It carries RYOS''s architecture rules, the design→implement→test→review→commit workflow with per-phase model assignments, and the exact verification commands. Do NOT use it to fix a reproducible bug or crash (use fix-ryos-bug), for pure UI/UX design review (use review-ryos-ui), or to just run the app (use run-ryos).'
---

# Adding or improving a feature in RYOS

RYOS ("Run Your Own Scripts") is a Tkinter desktop app. All code lives in the `ryos/` package; the entry point is `ryos.__main__:main`, exposed as the `ryos` console-script in `pyproject.toml`. There is no shim file.

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
| Windows "run at login" registry | `ryos/startup.py` |
| Toast notifications + GitHub update check | `ryos/notifications.py` |
| `ScriptDB` — all SQLite logic, schema, migrations | `ryos/db.py` |
| `detect_interpreter`, `build_command` | `ryos/interpreter.py` |
| Color palette `C`, flat-button factory, window snap | `ryos/ui/theme.py` |
| `ScrollingLabel`, tooltip | `ryos/ui/widgets.py` |
| Script / preset / param / advanced-options dialogs | `ryos/ui/dialogs.py` |
| `PipelineEditorDialog` | `ryos/ui/pipeline.py` |
| `ScriptCard`, `PipelineCard` | `ryos/ui/cards.py` |
| `RYOSApp` main window + run engine | `ryos/ui/app.py` |
| `__version__` | `ryos/__init__.py` |

## Architecture rules that always apply

These are the invariants that make RYOS work. Most "looked fine, broke in practice" bugs come from violating one of them, so internalize the *why*, not just the rule. **This is the canonical list** — when a brief below says to include the architecture rules, paste this whole section in verbatim rather than summarizing it; a partial list is how a rule quietly gets dropped.

- **Tkinter only.** The UI is built from `tk.Frame`, `tk.Label`, `tk.Button`, etc. Don't pull in ttk themes, Qt, or web tech.

- **Worker threads never touch widgets directly.** Script execution runs on a `threading.Thread`. Tkinter is not thread-safe, so a worker that writes to a `Text` widget or flips a label from its own thread will eventually crash or corrupt the display. Workers communicate with the UI in exactly two ways: by putting items on `self.output_queue` (drained on the main thread by a recurring `self.after(80, self._drain_output_queue)`), or by scheduling a callback with `self.after(0, callback)`. Any new background work must follow the same path. This is the single most important rule.

- **Don't rebuild all the cards on run/stop.** When a script starts or stops, flip the running state of *that one card* in place. Calling the full `_refresh_cards()` on every start/stop tears down and recreates every widget, which is slow, loses scroll position, and drops in-flight state. Before writing this part, Grep `ryos/ui/cards.py` and `ryos/ui/app.py` for how the running state is currently toggled (look for the running-state handling on the card and the running rows in `app.py`) and reuse that mechanism rather than inventing a new one or reaching for `_refresh_cards`.

- **Settings go through `_SETTINGS_DEFAULTS`.** A new user-facing toggle is added as a key in `_SETTINGS_DEFAULTS` in `ryos/settings.py` (so it has a default and old settings files still load via `{**_SETTINGS_DEFAULTS, **stored}`), persisted through `_load_settings()` / `_save_settings()`, and exposed in the Advanced Options dialog in `ryos/ui/dialogs.py` if the user should be able to change it.

- **Database changes are additive and migration-safe.** New columns/tables go in `ScriptDB._init_db()` in `ryos/db.py`. SQLite has **no** `ADD COLUMN IF NOT EXISTS`, so follow the pattern already in the file: read the existing columns with `PRAGMA table_info(<table>)`, then guard each migration — `if "<col>" not in cols: conn.execute("ALTER TABLE <table> ADD COLUMN <col> <type> DEFAULT <value>")`. New tables use `CREATE TABLE IF NOT EXISTS`. This is what keeps an existing user's `scripts.db` from breaking on upgrade. Add new query/mutation logic as methods on `ScriptDB`, not raw SQL scattered in the UI.

- **Dependency direction is one-way: `ui/*` → top-level modules.** The UI imports from `ryos.db`, `ryos.settings`, `ryos.interpreter`, etc. The reverse must never happen — `ryos/db.py`, `ryos/settings.py`, and friends must not import anything from `ryos.ui.*`. Crossing this line creates import cycles and couples the data layer to the widgets.

- **Route colors and buttons through `theme.py`.** Every color comes from the `C` dict in `ryos/ui/theme.py`; buttons come from its flat-button factory. If a feature needs a new color, add it to `C` rather than hard-coding a hex value at the widget.

- **Comments explain WHY, not WHAT.** The codebase is sparing with comments. Add one only when the reason for a line is non-obvious; don't narrate what the code plainly does.

- **Don't touch `__version__`.** Leave `ryos/__init__.py` alone — the version is bumped only when cutting a release (see the `release-ryos` skill), never per feature, and carries no `-dev` suffix.

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

The plan must answer: which **files** are edited (by path); which **functions/classes** are added or modified (one line of purpose each); any **schema/settings change** with its exact migration guard (`PRAGMA table_info` check + `ALTER TABLE`) or new `_SETTINGS_DEFAULTS` key; **UI placement** and behavior while a script runs; **thread-safety touch points** (anywhere a worker reaches the UI via `self.after`/`output_queue`); the **regression surface** — which existing behaviors sit next to the change and must not break (run/stop, groups, output panel, drag-drop, pipeline editor, or specific tests); and **open questions**, if any. For an *improvement*, the plan also names the **root cause** of the current limitation, so the change targets the cause rather than the symptom.

A good plan is concrete and small. Example, for *"confirm before stopping a running script"*:

> - **Files:** `ryos/settings.py`, `ryos/ui/dialogs.py`, `ryos/ui/app.py`, `ryos/__init__.py`
> - **Changes:** add `"confirm_stop": True` to `_SETTINGS_DEFAULTS`; add a checkbox in `AdvancedOptionsDialog._build` and persist it in `_save`; guard the existing stop handler in `app.py` with a `messagebox.askyesno` when the setting is on.
> - **Settings change:** new key `confirm_stop` (bool, default `True`). No DB change.
> - **UI placement:** checkbox in the Advanced Options dialog; the confirm prompt fires from the existing Stop control; no change to running-card behavior.
> - **Thread-safety:** none — the stop path is on the main thread.
> - **Risks:** don't double-prompt when stopping many scripts at once; default-on shouldn't surprise on first upgrade.

Present the plan to the user and proceed once they're on board (a "go ahead" with no comment counts as approval). Use a task list so each concrete change is visible during implementation.

### 4. Implement, test, and fix with a Sonnet agent

You do not write the implementation, run the tests, or launch the app yourself. Spawn a Sonnet agent (separate from you) to execute the approved plan, run the suite, smoke-test, and fix failures end-to-end. Offloading the whole implement–test–fix loop keeps your context clean for verification and the final review.

```
Agent({ description: "Implement <feature>", subagent_type: "general-purpose", model: "sonnet", prompt: <self-contained brief> })
```

The brief must include, verbatim: the **full approved plan** from step 3; the entire **Architecture rules that always apply** section (paste it — don't summarize; the full list is the contract); and the verification + acceptance criteria:

- `cd D:/Projects/RYOS && uv run python -m unittest discover -s tests -v` — all tests pass.
- `cd D:/Projects/RYOS && uv run ryos` — the app launches, the feature works end-to-end, and run/stop, groups, the output panel, drag-drop, and the pipeline editor do not regress. **If the environment has no display and the GUI can't launch, don't silently skip this** — say so, lean harder on the unit tests, and use the `run-ryos` skill's screenshot driver to verify the UI states where possible.

Add this instruction: *"Read only the files in the plan plus the direct callers/callees you need; use targeted Grep and narrow Reads — don't scan the repo. Edit only inside `ryos/` (a focused new test in `tests/test_ryos.py` is allowed when the feature adds testable non-UI logic). Don't touch `pyproject.toml`, `build*.bat`, or `uv.lock`. Implement the plan, then run the unit tests and the smoke check; if anything fails, read the traceback, fix, and re-run until both are clean. Do not commit or push. Report the files changed, the final test result, and a one-line smoke-test note."*

When the agent returns, **verify before moving on** — this is the gate, not a formality. Run `git diff` and `cd D:/Projects/RYOS && uv run python -m unittest discover -s tests -v` yourself (cheap insurance against a green run that wasn't), then walk this checklist against the diff:

- [ ] Changes match the approved plan; nothing extra crept in.
- [ ] No worker thread touches a widget except via `self.after` / `self.output_queue`.
- [ ] No new `import ryos.ui.*` inside `ryos/db.py`, `ryos/settings.py`, or other top-level modules.
- [ ] Any new DB column/table is `PRAGMA`-guarded (or `CREATE TABLE IF NOT EXISTS`) — no bare or `IF NOT EXISTS`-style `ALTER`.
- [ ] Run/stop flips the affected card in place — no `_refresh_cards()` on start/stop.
- [ ] New colors live in `theme.py` `C`; edits stay within `ryos/` (plus an allowed focused test).

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
