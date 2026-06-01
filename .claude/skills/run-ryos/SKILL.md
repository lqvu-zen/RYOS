---
name: run-ryos
description: run RYOS, launch the desktop app, start, screenshot, build, test, smoke test, verify UI changes
---

RYOS is a Tkinter desktop GUI app (Python) that manages and runs user scripts. The driver at `.claude/skills/run-ryos/driver.py` imports `RYOSApp` directly, schedules actions via Tkinter's `after()` mechanism, and captures screenshots with Pillow — no subprocess management needed.

## Prerequisites

Pillow must be included at runtime. Pass `--with pillow` to `uv run`. No other install steps needed; `uv` handles the rest automatically.

## Build

No build step. `uv` provisions the environment on first run:

```
uv run ryos
```

## Run (agent path)

Always run from the project root (`D:\Projects\RYOS`):

```
uv run --with pillow python .claude/skills/run-ryos/driver.py [scenario]
```

Available scenarios:

| Scenario | What it does |
|---|---|
| `smoke` | Launch, take a screenshot of the initial window, quit |
| `quick-run-bar` | Launch, toggle the Quick Run inline bar, screenshot, quit |
| `run-first` | Launch, run the first script card, screenshot the output panel, quit |

Screenshots land in `.claude/skills/run-ryos/screenshots/`. Read them with the `Read` tool to verify UI state.

### Driving the app internals directly

The driver has direct access to the live `RYOSApp` instance. Useful internal APIs:

```python
app._cards                          # list[ScriptCard] — all script cards currently rendered
app._pipeline_cards                 # list[PipelineCard]
app._quick_run_bars                 # dict[group_name, {frame, entry, var, base_dir, banner}]
app._toggle_quick_run_bar(gname)    # toggle the Quick Run bar for a group
app.db                              # ScriptDB — read/write the script database
card._run()                         # trigger a script card's run (same as clicking the Run button)
```

To add a new scenario, add a `_my_scenario(app: RYOSApp)` function to `driver.py` that schedules actions with `app.after(delay_ms, callback)`, then add a branch in `main()`.

## Run (human path)

```
uv run ryos
```

Opens the RYOS window. Not useful for automated testing.

## Test suite

```
uv run python -m unittest discover -s tests -v
```

48 unit tests covering `ScriptDB`, `detect_interpreter`, and `build_command`. All tests mock out Tkinter and run without a display.

## Gotchas

- **Unicode in print() on Windows**: `print()` uses cp1252 by default in PowerShell. Avoid non-ASCII in driver output (→ breaks, use -> instead).
- **auto_check_update**: The driver disables this via `s._SETTINGS_DEFAULTS["auto_check_update"] = False` before creating `RYOSApp`. Without this, the app may open a browser on first launch when an update is available.
- **Pack order after `pack_forget()`**: Calling `frame.pack()` after `pack_forget()` appends to the end of the parent's pack list. The Quick Run bar avoids this by storing a `"banner"` reference and using `pack(after=banner)`.
- **Tkinter must run on the main thread**: The driver uses `app.after()` to schedule all actions from within the event loop. Never call Tkinter widget methods directly from a background thread.
- **`run-first` timing**: The 2500 ms wait after `card._run()` is enough for fast scripts. For slow scripts (e.g. `slow_counter.py`) the output panel will not be fully populated yet.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'PIL'` | Add `--with pillow` to the `uv run` command |
| `UnicodeEncodeError: 'charmap' codec can't encode character` | Non-ASCII character in a `print()` call in the driver; replace with ASCII equivalent |
| `AttributeError: 'ScriptCard' object has no attribute '_on_run'` | Use `card._run()` — the method is `_run`, not `_on_run` |
| Screenshot is blank / wrong region | The app may not have finished rendering; increase the `after()` delay before taking the screenshot |
| `no quick-run bars found` in `quick-run-bar` scenario | The active group has no base directory set; set one via the banner's 📁 click |
