---
model: claude-opus-4-7
---

Refactor the RYOS repository from a single monolithic file into a scalable, modular package. The goal is to make each concern (UI components, data layer, business logic, theme) independently editable without touching unrelated code.

## Context

- **Current state**: all ~3600 lines live in `script_runner.py`
- **Entry points to preserve**: `uv run script_runner.py`, `run.bat`, `RYOS.exe` (PyInstaller)
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

### 2. Confirm the plan with the user

Present the proposed module layout (adjusted if needed after step 1) and ask for a go-ahead before writing any files.

### 3. Scaffold the package

Create empty files with only `# placeholder` so Python can resolve imports immediately:
```bash
mkdir -p D:/Projects/RYOS/ryos/ui
```
Create `ryos/__init__.py`, `ryos/ui/__init__.py`, and all module stubs.

### 4. Migrate in dependency order

Move code module by module, bottom-up. After each module, run a quick import check:
```bash
cd D:/Projects/RYOS && uv run python -c "from ryos.<module> import <KeyClass>"
```

**Order:**
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

### 5. Update script_runner.py to a shim

Replace the entire body of `script_runner.py` with:
```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["tkinterdnd2"]
# ///
from ryos.__main__ import main
if __name__ == "__main__":
    main()
```

The PEP 723 metadata block must stay here so `uv run script_runner.py` still provisions deps.

### 6. Update RYOS.spec

The PyInstaller spec's `Analysis` entrypoint should still point to `script_runner.py` (the shim). Verify `hiddenimports` includes any dynamically imported modules.

### 7. Run the test suite

```bash
cd D:/Projects/RYOS && uv run python -m unittest discover -s tests -v 2>&1
```

Fix import paths in `tests/test_ryos.py` (e.g. `from ryos.db import ScriptDB`). Do not change test logic.

### 8. Launch and smoke-test

```bash
cd D:/Projects/RYOS && uv run script_runner.py 2>&1
```

Verify:
- App opens, all script cards load
- Run / Stop a script, output appears
- Open Edit Script dialog, add a preset
- Open Pipeline editor, set a per-step preset
- Drag-and-drop a script file onto the window

### 9. Commit

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

### 10. Report

Tell the user:
- The new module layout with one-line purpose for each file
- Which file to edit for common tasks (e.g. "to change a button colour → `ryos/ui/theme.py`")
- Any follow-up suggestions (e.g. adding type hints, moving constants to a config file)
