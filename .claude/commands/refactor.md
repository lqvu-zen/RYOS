---
model: claude-sonnet-4-6
---

Refactor the RYOS repository from a single monolithic file into a scalable, modular package. The goal is to make each concern (UI components, data layer, business logic, theme) independently editable without touching unrelated code.

The orchestrator running this skill is Sonnet 4.6. Design (Step 2) and review (Step 4) are delegated to fresh Opus 4.7 agents; the migration + tests + smoke-test (Step 3) is delegated to a Sonnet 4.6 agent. The orchestrator handles user conversation, delegation, verification of each step, and the commit decision — it does NOT design, implement, or review inline.

## Context

- **Current state**: all ~3600 lines live in `script_runner.py`
- **Entry points to preserve**: `uv run ryos`, `run.bat`, `RYOS.exe` (PyInstaller)
- **Test suite**: `tests/test_ryos.py` — must stay green throughout
- **Build**: `RYOS.spec` + `uv run --with pyinstaller pyinstaller RYOS.spec`

## Target package layout

```
ryos/
  __init__.py          # exposes __version__
  __main__.py          # entry point: instantiates and runs RYOSApp
  db.py                # ScriptDB class — all SQLite logic
  interpreter.py       # detect_interpreter(), build_command()
  settings.py          # _SETTINGS_DEFAULTS, _load_settings(), _save_settings(), paths (_BASE, _APPDATA)
  notifications.py     # _show_notification(), _fetch_latest_release(), _parse_version()
  ui/
    __init__.py
    theme.py           # C colour dict, font constants, _apply_snap_corner()
    app.py             # RYOSApp(tk.Tk) — main window, menu bar, output panel
    cards.py           # ScriptCard, GroupHeaderCard
    dialogs.py         # ScriptDialog, _PresetEntryDialog, AdvancedOptionsDialog
    pipeline.py        # PipelineEditorDialog, PipelineListDialog
    output_tabs.py     # OutputTabBar, output tab management
script_runner.py       # thin shim: `from ryos.__main__ import main; main()`
```

## Steps

### 1. Read and map the current file

Scan `script_runner.py` to locate the line ranges of each major section:
```bash
cd D:/Projects/RYOS && grep -n "^class \|^def \|^# ---" script_runner.py | head -80
```

Build a mental map before touching anything.

### 2. Design the package with Opus 4.7

The package design is owned by Opus 4.7. Always spawn a fresh Opus 4.7 agent to do the design pass; the orchestrator (Sonnet 4.6) does not design inline.

```
Agent({
  description: "Design ryos/ package layout",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The current state of `script_runner.py` (paste the section map from Step 1).
- The target layout sketch from the "Target package layout" section above (as a starting point — the agent may adjust it).
- The constraint that no behaviour may change: `tests/test_ryos.py` must stay green, `uv run script_runner.py` and `RYOS.exe` must keep working.
- This instruction: *"Produce a final module layout, the dependency order modules must be migrated in, and the rationale for any deviation from the starting sketch. Do NOT write code or move anything yet. Flag any ambiguity as a question for the user instead of guessing."*

The deliverable from this step is:

- **Final directory tree** (one-line purpose per file).
- **Dependency order** for migration (bottom-up — no module may depend on one migrated later).
- **Shim contract** — what `script_runner.py` will look like after the refactor.
- **`RYOS.spec` changes** — entrypoint and `hiddenimports`.
- **Open questions** for the user, if any.

Present the design to the user and wait for confirmation or adjustments before moving on.

### 3. Delegate the migration, tests, and smoke-test to a Sonnet 4.6 agent

You (the orchestrator, Opus) do NOT write the migration code, run the tests, or launch the app yourself. Spawn a Sonnet 4.6 agent (the `"sonnet"` model alias resolves to Claude Sonnet 4.6) to do the mechanical splitting AND run the unit tests AND smoke-test the app — fixing any failures end-to-end. Opus context is preserved for the independent review step that follows.

Invocation:

```
Agent({
  description: "Migrate script_runner.py into ryos/ package",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The approved module layout from Step 2 (the full directory tree).
- The dependency order below — the agent MUST migrate in this order and run an import-check after each module:
  1. `ryos/settings.py` — paths, defaults, load/save (no internal deps)
  2. `ryos/db.py` — ScriptDB (depends on settings for paths)
  3. `ryos/interpreter.py` — detect_interpreter, build_command (no internal deps)
  4. `ryos/notifications.py` — update check, system tray notifications
  5. `ryos/ui/theme.py` — C dict, snap helpers (no internal deps)
  6. `ryos/ui/output_tabs.py` — OutputTabBar widget
  7. `ryos/ui/cards.py` — ScriptCard, GroupHeaderCard
  8. `ryos/ui/dialogs.py` — ScriptDialog, _PresetEntryDialog, AdvancedOptionsDialog
  9. `ryos/ui/pipeline.py` — PipelineEditorDialog, PipelineListDialog
  10. `ryos/ui/app.py` — RYOSApp (depends on all of the above)
  11. `ryos/__main__.py` — `def main(): app = RYOSApp(); app.mainloop()`
- Import check after each module: `uv run python -c "from ryos.<module> import <KeyClass>"`.
- The shim contents for `script_runner.py` (must keep the PEP 723 metadata block):
  ```python
  # /// script
  # requires-python = ">=3.10"
  # dependencies = ["tkinterdnd2"]
  # ///
  from ryos.__main__ import main
  if __name__ == "__main__":
      main()
  ```
- Update `RYOS.spec` so the `Analysis` entrypoint stays at `script_runner.py` and add the `ryos.*` submodules to `hiddenimports`.
- The verification commands and acceptance criteria:
  - `uv run python -m unittest discover -s tests -v` — all tests must pass. Fix any broken import paths in `tests/test_ryos.py` (e.g. `from ryos.db import ScriptDB`); do not change test logic.
  - `uv run ryos` — launch the app and verify: app opens with all script cards loaded; Run / Stop a script and see output appear; open Edit Script dialog and add a preset; open Pipeline editor and set a per-step preset; drag-and-drop a script file onto the window.
- This instruction: *"Read only the files you need to migrate or that the migration directly touches (the source module being split, plus any test file that imports from it). Use targeted Grep to locate symbols; do NOT scan the whole repo with `Glob "**"` or recursive directory listings unless you genuinely need a project-wide view. Run the unit tests and the smoke checks after the migration. If anything fails, read the traceback, fix the code (or fix broken test imports), and re-run — loop until tests and the app are both clean. Do not commit or push. Report back the final list of files you created or modified, plus any deviations from the planned layout, and the final test/smoke result."*

When the agent returns, **verify before moving on**:
- Run `Glob "ryos/**/*.py"` and `git status` to confirm the structure matches the planned layout.
- Re-run `uv run python -m unittest discover -s tests -v` yourself — cheap defense against an agent claiming a green run that wasn't.
- If anything looks off, either fix it inline or send a follow-up via `SendMessage` to the same agent.

### 4. Review with Opus 4.7 (before commit)

Spawn an independent Opus 4.7 agent to review the refactor. The orchestrator is also Opus 4.7, but a fresh agent has no context bias from planning or delegation — it sees only the code and the brief.

```
Agent({
  description: "Review ryos/ refactor",
  subagent_type: "general-purpose",
  model: "opus",
  prompt: <self-contained brief — see below>
})
```

The prompt must include, verbatim:

- The original goal: "Split the monolithic `script_runner.py` into a `ryos/` package without changing behaviour."
- The approved module layout (the directory tree from Step 2).
- A list of every file the Sonnet agent created or modified (paste the `git status` output).
- The output of `git diff --stat` and selected `git diff` excerpts for the most behaviour-sensitive files (`ryos/db.py`, `ryos/ui/app.py`, `script_runner.py`, `RYOS.spec`).
- The rules the refactor must respect: no behaviour change, `script_runner.py` must remain a PEP 723 shim, dependency direction `ui/*` → top-level (never the reverse), `RYOS.spec` entrypoint stays at `script_runner.py` with `ryos.*` in `hiddenimports`.
- This instruction: *"Review ONLY the diff and the files it modifies. Do not scan other files in the repo. If a change in the diff references an external symbol (e.g. an import), you may open that referenced file to confirm the API exists — but do not go looking for unrelated issues outside the diff. Look for behaviour-changing edits, circular imports, missing `ryos.*` entries in `hiddenimports`, and any module landing in the wrong file. Do NOT edit any files. Report findings in three buckets: BLOCKERS, SUGGESTIONS, OK. End with the line 'READY TO COMMIT' if there are no blockers."*

If the reviewer reports BLOCKERS, fix them (or send a follow-up to the Sonnet agent via `SendMessage`) and re-review. Only proceed once the reviewer prints `READY TO COMMIT`.

### 5. Commit

```bash
cd D:/Projects/RYOS && git add -A && git commit -m "$(cat <<'EOF'
Refactor into ryos package — separate UI, DB, settings, interpreter

script_runner.py is now a thin uv shim. All logic lives under ryos/:
  db.py, interpreter.py, settings.py, notifications.py,
  ui/theme.py, ui/cards.py, ui/dialogs.py, ui/pipeline.py,
  ui/output_tabs.py, ui/app.py

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)" && git push 2>&1
```

### 6. Report

Tell the user:
- The new module layout with one-line purpose for each file
- Which file to edit for common tasks (e.g. "to change a button colour → `ryos/ui/theme.py`")
- Any follow-up suggestions (e.g. adding type hints, moving constants to a config file)
