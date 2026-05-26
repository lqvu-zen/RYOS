---
model: claude-opus-4-7
---

Add a new feature to RYOS. Follow these steps every time.

The orchestrator running this skill is Opus 4.7. It owns the design, the user conversation, the verification of every delegated step, and the commit decision. It does NOT write the implementation code itself.

## Architecture reminder

Code now lives in the `ryos/` package, not the old `script_runner.py` monolith. `script_runner.py` is just a PEP 723 shim that calls `ryos.__main__.main`.

| Concern                                  | Module                                       |
| ---------------------------------------- | -------------------------------------------- |
| Paths, `_SETTINGS_DEFAULTS`, load/save   | `ryos/settings.py`                           |
| Windows "run at login" registry          | `ryos/startup.py`                            |
| Toast + GitHub update check              | `ryos/notifications.py`                      |
| `ScriptDB` (all SQLite logic)            | `ryos/db.py`                                 |
| `detect_interpreter`, `build_command`    | `ryos/interpreter.py`                        |
| Colours, flat buttons, snap corner       | `ryos/ui/theme.py`                           |
| `ScrollingLabel`                         | `ryos/ui/widgets.py`                         |
| Script/preset/param/advanced dialogs     | `ryos/ui/dialogs.py`                         |
| `PipelineEditorDialog`                   | `ryos/ui/pipeline.py`                        |
| `ScriptCard`, `PipelineCard`             | `ryos/ui/cards.py`                           |
| `RYOSApp` main window + run engine       | `ryos/ui/app.py`                             |
| `__version__`                            | `ryos/__init__.py`                           |

Rules that still apply everywhere:

- **UI toolkit**: Tkinter — `tk.Frame`, `tk.Label`, `tk.Button`, etc.
- **No UI rebuild on run/stop**: use `card.set_running(True/False)` instead of `_refresh_cards()` when a script starts or stops.
- **Thread safety**: worker threads must only touch the UI via `self.after(0, callback)` or by putting items on `self.output_queue`.
- **Settings**: add new toggles to `_SETTINGS_DEFAULTS` in `ryos/settings.py` and save/load through `_load_settings()` / `_save_settings()`. Expose user-facing toggles in `AdvancedOptionsDialog` (`ryos/ui/dialogs.py`).
- **Database**: use `ScriptDB` methods in `ryos/db.py`; add new columns/tables in `_init_db()` with `ALTER TABLE … ADD COLUMN IF NOT EXISTS` so existing databases are not broken.
- **Dependency direction**: `ui/*` → top-level modules → never the other way. Don't import from `ryos.ui.*` inside `ryos/db.py`, `ryos/settings.py`, etc.
- **Version**: bump `__version__` in `ryos/__init__.py` (patch for fixes/small features, minor for notable new features).

## Steps

### 1. Understand the feature
Read the user's request carefully. If anything is ambiguous, ask one focused clarifying question before writing any code.

### 2. Locate relevant code
Use Grep to find the area to change inside `ryos/`:
```
Grep pattern="<relevant keyword>" path="ryos" output_mode="content" -n=true
```
Read the relevant sections with the Read tool before planning.

### 3. Design and plan with Opus 4.7 (ALWAYS — before any code edits)

The design is owned by Opus 4.7. For non-trivial features, spawn a fresh Opus 4.7 agent to do a deep design pass; for small features the orchestrator (also Opus 4.7) can produce the plan inline. Either way, the deliverable is the same plan format below.

When in doubt, delegate. Spawning a fresh agent gives an independent design free of context bias from the feature request conversation.

```
Agent({
  description: "Design <feature name>",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The user's feature request (one paragraph).
- The architecture table and rules from the top of this file (paste them in).
- The output of any Grep/Read calls from Step 2 that show the current shape of the code being changed.
- This instruction: *"Design the smallest correct implementation. Do NOT write code — produce only a plan with the sections listed below. If something is ambiguous, list it as a question for the user instead of guessing."*

The plan must answer:

- **Which file(s)** will be edited — list them by path (e.g. `ryos/ui/app.py`, `ryos/db.py`).
- **Which function(s) / class(es)** will be added or modified, with one-line purpose for each.
- **Schema or settings changes** — any new column, new key in `_SETTINGS_DEFAULTS`, new method on `ScriptDB` (include the migration shape: `ALTER TABLE … ADD COLUMN IF NOT EXISTS`).
- **UI placement** — where in the window the new control appears, what triggers it, and how it behaves while a script is running.
- **Thread-safety touch points** — anywhere a worker thread needs to hit the UI (must go via `self.after` or `output_queue`).
- **Risks / regressions** to watch for during the test step.
- **Open questions** for the user, if any.

Present the plan to the user and wait for confirmation or adjustments. Use `TaskCreate` to record one task per concrete change so progress is visible during the implementation step. If the user says "go ahead" without comment, treat that as approval and proceed.

### 4. Implement (delegate to a Sonnet agent)

You (the orchestrator) do NOT write the implementation code yourself. Spawn a Sonnet agent via the `Agent` tool and hand it the approved plan to execute. This keeps the main context free for planning, review, and follow-ups.

Invocation:

```
Agent({
  description: "Implement <feature name>",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The full approved plan from Step 3 (files, functions, schema/settings changes, UI placement).
- The architecture rules from the table above that apply (thread safety, `set_running`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, dependency direction, no comments unless WHY is non-obvious).
- The exact `__version__` bump expected (so the agent can do it in the same pass).
- This instruction: *"Edit only inside `ryos/` and `ryos/__init__.py`. Do not touch `script_runner.py`, `RYOS.spec`, or any test file. Do not commit or push. Report back the list of files you changed."*

When the agent returns, **verify the changes yourself** before moving on: read each modified file's diff with `git diff` and confirm the agent did what the plan said. If it deviated, either accept the deviation or send a follow-up message via `SendMessage` to correct it. Mark each `TaskUpdate` as `completed` once verified.

### 5. Test and fix

Run the unit tests first:
```
uv run python -m unittest discover -s tests -v
```

Then launch the app and exercise the new feature end-to-end:
```
uv run script_runner.py
```
- Walk through the happy path: does the feature work as requested?
- Check for regressions: do existing features (run/stop, groups, output panel, drag-drop, pipeline editor) still work?
- If the app crashes or prints tracebacks, read the error, fix the code, and re-test.
- Repeat until tests and the app both run clean.

### 6. Bump the version
Edit `ryos/__init__.py` and bump `__version__` to the next appropriate value (patch = `x.y.Z+1`, minor = `x.Y+1.0`).

### 7. Review with Opus 4.7 (before commit)

Spawn an independent Opus 4.7 agent to review the staged diff. The orchestrator is also Opus 4.7, but a fresh agent has no context bias from the planning step — it sees only the code and the brief.

```
Agent({
  description: "Review <feature> implementation",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The original feature request (one paragraph).
- The full approved plan from Step 3.
- The output of `git diff` for all modified files (paste it in).
- The architecture rules the implementation must respect (thread safety via `self.after`/`output_queue`, `set_running` instead of `_refresh_cards`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, dependency direction `ui/*` → top-level, no comments unless WHY is non-obvious).
- This instruction: *"Review the diff for correctness bugs, deviations from the plan, and architecture-rule violations. Do NOT edit any files. Report findings in three buckets: BLOCKERS (must fix before commit), SUGGESTIONS (nice-to-have), and OK (looks correct). If there are no blockers, end with the line 'READY TO COMMIT'."*

If the reviewer reports BLOCKERS, fix them yourself (or delegate back to the Sonnet agent via `SendMessage`) and re-review. Only proceed once the reviewer prints `READY TO COMMIT`.

### 8. Commit and push
```
git add ryos/ <any other touched files> && git commit -m "$(cat <<'EOF'
<short description of the feature>

<optional detail lines>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)" && git push
```

### 9. Report
Tell the user:
- What was added and where it lives in the UI
- Which files changed (paths inside `ryos/`)
- The new `__version__` value
- The commit hash
- Any known limitations or follow-up suggestions
