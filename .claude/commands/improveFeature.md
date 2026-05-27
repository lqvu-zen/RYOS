---
model: claude-sonnet-4-6
---

Maintain or improve an existing RYOS feature. Follow these steps every time.

The orchestrator running this skill is Sonnet 4.6. It owns the user conversation, the delegation of analysis and review to Opus 4.7, the verification of every delegated step, and the commit decision. It does NOT analyse the code, write the implementation, run the tests, or review the diff itself — analysis and review go to fresh Opus 4.7 agents; implement/test/fix goes to a separate Sonnet 4.6 agent.

## Architecture reminder

Code lives in the `ryos/` package; entry point is `ryos.__main__:main` exposed via `pyproject.toml`.

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

Rules that apply everywhere:

- **UI toolkit**: Tkinter — `tk.Frame`, `tk.Label`, `tk.Button`, etc.
- **No UI rebuild on run/stop**: use `card.set_running(True/False)` instead of `_refresh_cards()` when a script starts or stops.
- **Thread safety**: worker threads must only touch the UI via `self.after(0, callback)` or by putting items on `self.output_queue`.
- **Settings**: add new toggles to `_SETTINGS_DEFAULTS` in `ryos/settings.py` and save/load through `_load_settings()` / `_save_settings()`. Expose user-facing toggles in `AdvancedOptionsDialog` (`ryos/ui/dialogs.py`).
- **Database**: use `ScriptDB` methods in `ryos/db.py`; add new columns/tables in `_init_db()` with `ALTER TABLE … ADD COLUMN IF NOT EXISTS` so existing databases are not broken.
- **Dependency direction**: `ui/*` → top-level modules — never the other way.
- **Version**: bump `__version__` in `ryos/__init__.py` (patch for fixes/small improvements, minor for notable enhancements).

## Steps

### 1. Understand the improvement request

Read the user's request carefully. Clarify:
- **Which specific feature** is being improved (ask if ambiguous).
- **What the undesired behaviour / limitation is** today — a bug, a UX issue, missing edge-case handling, performance, code quality?
- **What "good" looks like** — a concrete, observable outcome.

Ask one focused clarifying question before writing any code if anything is unclear.

### 2. Analyse the existing code

Use Grep to find the current implementation:

```
Grep pattern="<relevant keyword>" path="ryos" output_mode="content" -n=true
```

Read the relevant sections with the Read tool (narrow line ranges, not whole files). Gather enough context to describe:
- The current logic and its known edge cases.
- Any tests that exercise it (`tests/` directory).
- Any callers or callees that a change here will affect.

Do NOT open files unrelated to the feature being improved.

### 3. Analyse and plan with Opus 4.7 (ALWAYS — before any code edits)

The improvement plan is owned by Opus 4.7. Always spawn a fresh Opus 4.7 agent — even for small tweaks. A fresh agent sees only the code and the brief, which eliminates context bias from the conversation.

```
Agent({
  description: "Analyse and plan improvement: <feature name>",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The user's improvement request (one paragraph).
- The architecture table and rules from the top of this file (paste them in).
- The output of the Grep/Read calls from Step 2 that show the **current** implementation.
- Any existing tests from `tests/` that cover this feature.
- This instruction: *"Analyse the current implementation for the specific problem described. Then design the smallest correct change that fixes or improves it without breaking unrelated behaviour. Do NOT write code — produce only a plan with the sections listed below. If something is ambiguous, list it as a question for the user instead of guessing."*

The plan must answer:

- **Root cause** — what in the current code causes the problem / limitation.
- **Which file(s)** will be edited — list them by path (e.g. `ryos/ui/app.py`, `ryos/db.py`).
- **Which function(s) / class(es)** will be modified, with one-line description of each change.
- **Schema or settings changes** (if any) — new column, new `_SETTINGS_DEFAULTS` key, migration shape (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`).
- **Regression surface** — which existing behaviours are adjacent to the change and must not break: specific features (run/stop, groups, output panel, drag-drop, pipeline editor) or specific test cases.
- **Thread-safety touch points** — anywhere a worker thread needs to hit the UI (must go via `self.after` or `output_queue`).
- **Open questions** for the user, if any.

Present the plan to the user and wait for confirmation or adjustments. Use `TaskCreate` to record one task per concrete change so progress is visible during implementation. If the user says "go ahead" without comment, treat that as approval and proceed.

### 4. Implement, test, and fix (delegate to a Sonnet 4.6 agent)

You (the orchestrator) do NOT write the implementation code, run the tests, or launch the app yourself. Spawn a Sonnet 4.6 agent to execute the plan, run the test suite, smoke-test the feature, and fix any failures end-to-end.

```
Agent({
  description: "Implement improvement: <feature name>",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The full approved plan from Step 3 (root cause, files, functions, schema/settings changes).
- The architecture rules from the table above that apply (thread safety, `set_running`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, dependency direction, no comments unless WHY is non-obvious).
- The exact `__version__` bump expected — the agent bumps it as part of the same pass.
- The verification commands and acceptance criteria:
  - `uv run python -m unittest discover -s tests -v` — all unit tests must pass (including any tests that previously covered the feature being changed).
  - `uv run ryos` — the app must launch; the improved behaviour must be confirmed end-to-end; the features listed in the plan's **Regression surface** must not regress.
- This instruction: *"Read only the files listed in the plan plus any direct callers or callees you need to make the edit correctly. Use targeted Grep to locate symbols and Read narrow line ranges; do NOT scan the whole repo with `Glob "**"`, recursive directory listings, or open files you don't need. Edit only inside `ryos/`. Do not touch `pyproject.toml`, `build.bat`, or test files unless the plan explicitly calls for a test update. Implement the plan, bump `__version__`, then run the unit tests and the smoke checks. If anything fails, read the traceback, fix the code, and re-run — loop until tests and the app are both clean. Do not commit or push. Report back: the list of files you changed, the final test result, and a one-line note on the manual smoke-test outcome."*

When the agent returns, **verify before moving on**:
- Run `git diff` and confirm the actual changes match the plan; confirm `__version__` was bumped.
- Re-run `uv run python -m unittest discover -s tests -v` yourself — cheap defense against an agent claiming a green run that wasn't.
- Confirm the regression surface listed in the plan was not broken.
- If anything looks off, either fix it inline or send a follow-up via `SendMessage` to the same agent.

Mark each `TaskUpdate` as `completed` once verified.

### 5. Review with Opus 4.7 (before commit)

Spawn an independent Opus 4.7 agent to review the staged diff. A fresh agent has no context bias from the planning step — it sees only the code and the brief.

```
Agent({
  description: "Review improvement: <feature name>",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The original improvement request (one paragraph).
- The root cause and plan from Step 3.
- The regression surface that must not break.
- The output of `git diff` for all modified files (paste it in).
- The architecture rules the implementation must respect (thread safety via `self.after`/`output_queue`, `set_running` instead of `_refresh_cards`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, dependency direction `ui/*` → top-level, no comments unless WHY is non-obvious).
- This instruction: *"Review ONLY the diff and the files it modifies. Do not scan other files in the repo. If a change in the diff references an external symbol (e.g. a new import), you may open that referenced file to confirm the API exists — but do not go looking for unrelated issues outside the diff. Focus especially on: (1) does the change actually fix the described root cause? (2) does it touch the regression surface in a safe way? (3) does it introduce new edge cases? Report findings in three buckets: BLOCKERS (must fix before commit), SUGGESTIONS (nice-to-have), and OK (looks correct). If there are no blockers, end with the line 'READY TO COMMIT'."*

If the reviewer reports BLOCKERS, fix them yourself (or delegate back to the Sonnet 4.6 agent via `SendMessage`) and re-review. Only proceed once the reviewer prints `READY TO COMMIT`.

### 6. Commit and push

```
git add ryos/ <any other touched files> && git commit -m "$(cat <<'EOF'
<short description of the improvement>

<optional detail lines — root cause + fix approach if non-obvious>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)" && git push
```

### 7. Report

Tell the user:
- What changed and why (root cause → fix in plain language)
- Which files changed (paths inside `ryos/`)
- The new `__version__` value
- The commit hash
- Any known limitations, remaining edge cases, or follow-up suggestions
