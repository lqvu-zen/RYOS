Add a new feature to RYOS (`script_runner.py`). Follow these steps every time.

## Architecture reminder

- **Single file**: all code lives in `D:/Projects/RYOS/script_runner.py`
- **UI toolkit**: Tkinter — use `tk.Frame`, `tk.Label`, `tk.Button`, etc.
- **No UI rebuild on run/stop**: use `card.set_running(True/False)` instead of `_refresh_cards()` when a script starts or stops.
- **Thread safety**: worker threads must only touch the UI via `self.after(0, callback)` or by putting items on `self.output_queue`.
- **Settings**: add new toggles to `_SETTINGS_DEFAULTS` and save/load through `_load_settings()` / `_save_settings()`. Expose user-facing toggles in `AdvancedOptionsDialog`.
- **Database**: use `ScriptDB` methods; add new columns/tables in `_init_db()` with `ALTER TABLE … ADD COLUMN IF NOT EXISTS` so existing databases are not broken.
- **Version**: bump `__version__` (patch for fixes/small features, minor for notable new features) in `script_runner.py` line ~41.

## Steps

### 1. Understand the feature
Read the user's request carefully. If anything is ambiguous, ask one focused clarifying question before writing any code.

### 2. Locate relevant code
Search for the area of the codebase to change:
```bash
cd D:/Projects/RYOS && grep -n "<relevant keyword>" script_runner.py 2>&1 | head -40
```
Read the relevant sections with the Read tool before editing.

### 3. Implement
- Edit `script_runner.py` only — do not create new files unless the user asks.
- Keep changes minimal: implement exactly what was requested, nothing more.
- Do not add comments unless the reason behind the code is non-obvious.
- If the feature has a user-facing toggle, add it to `_SETTINGS_DEFAULTS` and `AdvancedOptionsDialog`.
- If the feature touches card running state, use `set_running()` — never call `_refresh_cards()` from run/stop paths.

### 4. Bump the version
```bash
cd D:/Projects/RYOS && grep -n "__version__" script_runner.py 2>&1
```
Update `__version__` to the next appropriate value (patch = `x.y.Z+1`, minor = `x.Y+1.0`).

### 5. Commit and push
```bash
cd D:/Projects/RYOS && git add script_runner.py && git commit -m "$(cat <<'EOF'
<short description of the feature>

<optional detail lines>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)" && git push 2>&1
```

### 6. Report
Tell the user:
- What was added and where it lives in the UI
- The new `__version__` value
- The commit hash
- Any known limitations or follow-up suggestions
