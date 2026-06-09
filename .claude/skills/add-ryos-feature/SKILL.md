---
name: add-ryos-feature
description: 'Add a new feature to the RYOS desktop app the right way — end to end, following the project''s own conventions. Use this whenever the user asks to add, build, implement, or wire up any new capability in RYOS: a new setting or toggle, a new button or menu item, a new dialog, a new column or table in the script database, a change to how scripts run, pipeline behavior, the output panel, the Quick Run bar, notifications, startup behavior, or anything that means editing files under `ryos/`. Trigger even when the user just describes the behavior they want ("I want RYOS to remember the last window size", "can it auto-clear output between runs", "add a dark mode toggle") without saying the words "feature" or "implement". This skill carries RYOS''s architecture rules, the design→implement→test→review→commit workflow, and the exact verification commands, so you don''t reinvent them each time. Do NOT use it for pure UI/UX design reviews (use review-ryos-ui) or for just running the app (use run-ryos).'
---

# Adding a feature to RYOS

RYOS ("Run Your Own Scripts") is a Tkinter desktop app. All code lives in the `ryos/` package; the entry point is `ryos.__main__:main`, exposed as the `ryos` console-script in `pyproject.toml`. There is no shim file.

The point of this skill is that adding a feature here is not just "write the code." A change that ignores the app's threading model, its settings/DB migration patterns, or its dependency direction will look correct and still break the running app or corrupt an existing user's database. So the workflow below front-loads understanding and ends with real verification — the app actually launching and the tests actually passing — before anything is committed.

Work through the phases in order. Don't skip the test/review phase to save time; a feature that isn't verified isn't done.

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

These are the invariants that make RYOS work. Most "looked fine, broke in practice" bugs come from violating one of them, so internalize the *why*, not just the rule.

- **Tkinter only.** The UI is built from `tk.Frame`, `tk.Label`, `tk.Button`, etc. Don't pull in ttk themes, Qt, or web tech.

- **Worker threads never touch widgets directly.** Script execution runs on a `threading.Thread`. Tkinter is not thread-safe, so a worker that writes to a `Text` widget or flips a label from its own thread will eventually crash or corrupt the display. Workers communicate with the UI in exactly two ways: by putting items on `self.output_queue` (drained on the main thread by a recurring `self.after(80, self._drain_output_queue)`), or by scheduling a callback with `self.after(0, callback)`. Any new background work must follow the same path. This is the single most important rule.

- **Don't rebuild all the cards on run/stop.** When a script starts or stops, flip the running state of *that one card* in place. Calling the full `_refresh_cards()` on every start/stop tears down and recreates every widget, which is slow, loses scroll position, and drops in-flight state. Before writing this part, Grep `ryos/ui/cards.py` and `ryos/ui/app.py` for how the running state is currently toggled (look for the running-state handling on the card and the running rows in `app.py`) and reuse that mechanism rather than inventing a new one or reaching for `_refresh_cards`.

- **Settings go through `_SETTINGS_DEFAULTS`.** A new user-facing toggle is added as a key in `_SETTINGS_DEFAULTS` in `ryos/settings.py` (so it has a default and old settings files still load via `{**_SETTINGS_DEFAULTS, **stored}`), persisted through `_load_settings()` / `_save_settings()`, and exposed in the Advanced Options dialog in `ryos/ui/dialogs.py` if the user should be able to change it.

- **Database changes are additive and migration-safe.** New columns/tables go in `ScriptDB._init_db()` in `ryos/db.py`. SQLite has **no** `ADD COLUMN IF NOT EXISTS`, so follow the pattern already in the file: read the existing columns with `PRAGMA table_info(<table>)`, then guard each migration — `if "<col>" not in cols: conn.execute("ALTER TABLE <table> ADD COLUMN <col> <type> DEFAULT <value>")`. New tables use `CREATE TABLE IF NOT EXISTS`. This is what keeps an existing user's `scripts.db` from breaking on upgrade. Add new query/mutation logic as methods on `ScriptDB`, not raw SQL scattered in the UI.

- **Dependency direction is one-way: `ui/*` → top-level modules.** The UI imports from `ryos.db`, `ryos.settings`, `ryos.interpreter`, etc. The reverse must never happen — `ryos/db.py`, `ryos/settings.py`, and friends must not import anything from `ryos.ui.*`. Crossing this line creates import cycles and couples the data layer to the widgets.

- **Route colors and buttons through `theme.py`.** Every color comes from the `C` dict in `ryos/ui/theme.py`; buttons come from its flat-button factory. If a feature needs a new color, add it to `C` rather than hard-coding a hex value at the widget.

- **Comments explain WHY, not WHAT.** The codebase is sparing with comments. Add one only when the reason for a line is non-obvious; don't narrate what the code plainly does.

- **Bump `__version__`.** It lives in `ryos/__init__.py` (currently a `-dev` string). Bump the patch number for fixes and small features, the minor for a notable new capability.

## The workflow

### 1. Understand the request

Read what the user asked for and restate it to yourself in one sentence: what should the user be able to do after this ships that they can't do now? If a real ambiguity blocks the design (e.g. "remember settings" — which settings? per-script or global?), ask **one** focused question before writing code. Don't ask about things you can reasonably default.

### 2. Locate the code

Find the area you'll change with targeted Grep inside `ryos/`, then Read the relevant sections — not the whole repo:

```
Grep pattern="<relevant keyword>" path="ryos" output_mode="content" -n=true
```

Read the few functions you'll touch plus their direct callers/callees. You need enough to make the edit correctly and to see which of the architecture rules above are in play (does this touch a worker thread? the DB? settings? card running-state?).

While you're in there, check whether some or all of what's being asked **already exists**. RYOS has more behind the scenes than the UI exposes — a copy-to-clipboard helper, a status setter, a DB field — and the right move is often to surface or extend an existing function rather than build a parallel one. A request like "add a Copy button" may turn out to be "wire a button to the `_copy_log` method that's already there." Finding that first saves a redundant implementation and keeps behavior consistent.

### 3. Design the smallest correct change

Before editing, write a short plan — a few sentences or bullets, not a formal document:

- **Files** you'll edit, by path.
- **Functions/classes** added or modified, one line of purpose each.
- **Schema or settings changes**, including the exact migration guard (`PRAGMA` check + `ALTER TABLE`) or the new `_SETTINGS_DEFAULTS` key.
- **UI placement** — where the control appears, what triggers it, and how it behaves while a script is running.
- **Thread-safety touch points** — anywhere a worker needs to reach the UI (must go via `self.after` or `output_queue`).
- **Risks/regressions** to check in the test phase (run/stop, groups, output panel, drag-drop, pipeline editor are the usual suspects).

Aim for the smallest change that fully satisfies the request and respects the rules. Resist scope creep and incidental refactors.

For a substantial or risky feature, it's worth getting independent eyes on the design before you build: if subagents are available, spawn a fresh agent to produce or sanity-check the plan — a fresh agent has no anchoring from the feature-request conversation and will catch assumptions you've absorbed. For small, obvious changes this is overkill; use judgment. Either way, show the plan to the user and proceed once they're on board (a "go ahead" with no comment counts as approval). Use a task list so the concrete changes are visible as you work.

### 4. Implement

Edit only inside `ryos/`. Don't touch `pyproject.toml`, the `build*.bat` files, or the test files unless the feature genuinely requires it (and if a test needs updating because behavior legitimately changed, that's fine — but never edit a test just to make a red run go green). Follow the plan; bump `__version__` in `ryos/__init__.py` as part of the same pass so it's never forgotten.

### 5. Test and smoke-check — this is not optional

Run the unit suite and fix anything red before moving on:

```bash
cd D:/Projects/RYOS && uv run python -m unittest discover -s tests -v
```

Then launch the app and confirm the feature works end-to-end *and* that nothing regressed:

```bash
cd D:/Projects/RYOS && uv run ryos
```

Exercise the new behavior, then poke the load-bearing existing features — start and stop a script, switch groups, open the output panel, drag-drop a file, open the pipeline editor. If the environment has no display and the app can't launch, say so plainly; lean harder on the unit tests and (if present) the `run-ryos` skill's screenshot driver, and flag that you couldn't do a live smoke test.

**Add a test when the feature adds testable non-UI logic.** This repo has a strong unit-test culture (see the `TestScriptDB*` classes in `tests/test_ryos.py`). If your feature adds a new `ScriptDB` method, a migration, or a settings-derived behavior, add a focused test for it in the matching style — this is the one sanctioned reason to edit `tests/test_ryos.py`. A pure-UI change (a new button, a dialog toggle) usually has nothing unit-testable and shouldn't force a test; verify those by reasoning about the widget code and, where possible, the `run-ryos` screenshot driver.

If a test or the app fails, read the traceback, fix the code, and re-run — loop until both are clean. A green claim you didn't actually verify is worse than no claim.

### 6. Review before commit

Run `git diff` and read your own change as if you were reviewing someone else's PR. Check it against the plan and against the architecture rules above: any worker thread reaching the UI without `self.after`/`output_queue`? any `ui/*` → top-level import you introduced backwards? a DB migration missing its `PRAGMA` guard? `_refresh_cards` called where an in-place card update belongs? `__version__` bumped?

For a non-trivial diff, a fresh-eyes pass pays off: if subagents are available, hand the diff to one for an independent review and fix any real issues it surfaces before committing. Don't gold-plate small changes.

### 7. Commit and push

Match the existing commit style (`git log --oneline -5` to see it). Stage only the relevant files — never `scripts.db`, `dist/`, `build/`, `.env`, or `__pycache__`.

```bash
cd D:/Projects/RYOS && git add ryos/ <other touched files> && git commit -m "$(cat <<'EOF'
<short description of the feature>

<optional detail line>

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)" && git push
```

### 8. Report back

Tell the user, briefly: what was added and where it appears in the UI, which files under `ryos/` changed, the new `__version__`, the commit hash, and any known limitation or follow-up worth doing next.
