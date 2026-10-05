---
name: run-ryos
description: run RYOS, launch the desktop app, start, screenshot, build, test, smoke test, verify UI changes
---

RYOS is a Qt (PySide6) desktop app that manages and runs user scripts. The driver at `.claude/skills/run-ryos/driver.py` builds the real window through the app's own start-up (`ryos.qtui.main.build`) on a throwaway data folder loaded with the repo's `samples/`, and saves screenshots — **without showing anything on any monitor** (Qt's `WA_DontShowOnScreen` renders fully, off screen). The user works on the first screen; never put windows there.

## Run (agent path)

From the project root (`D:\Projects\RYOS`):

```
uv run python .claude/skills/run-ryos/driver.py [scenario ...] [--theme ID]
```

| Scenario | What it captures |
|---|---|
| `main` (default) | The window on the Samples group |
| `compact` | The same in compact card mode |
| `output` | After a successful and a failing run: output panel open, Retry state |
| `workspace` | The maximised layout (list + detail pane), on a pipeline and on a script |
| `quick-run` | The Quick Run bar open, with suggestions |
| `dialogs` | Script dialog, pipeline editor, schedule, run history, Options, Appearance, New Group |
| `themes` | Every theme's main window on one contact sheet (`themes.png`) |
| `all` | All of the above |

`--theme` takes a theme id (`light`, `dark`, or a gallery/preset id such as `nord`). Screenshots land in `.claude/skills/run-ryos/screenshots/` (gitignored); read them with the `Read` tool.

### Adding a scenario

Add a `scenario_<name>(theme)` function and register it in `SCENARIOS`. `window(theme, **settings)` returns a built, off-screen `MainWindow`; `shot(widget, name)` saves a PNG. The window's hooks make any state reachable without a person:

```python
win.run_dialog = lambda dlg: ...        # every dialog passes through here
win.ask_yes_no / ask_text / warn = ...  # every prompt, likewise
card(win, "Say hello").run_button.click()
win.on_card_menu("script", sid, "history")   # any card-menu action by key
win.set_output_expanded(True); win.quick_run_bars["Samples"].open()
idle(win)                               # wait for running jobs to finish
```

## Run (human path)

```
uv run ryos
```

## Tests

```
uv run --no-project --with pytest pytest -q                      # unit suite, no display
uv run --no-project --with PySide6 python tests/qt_smoke.py      # real widgets, feature by feature
uv run python tests/session_smoke.py                             # a whole working session
```

The smokes take `--visible` (where supported) to show windows on the **second** screen; `CLAUDE.md` lists them all.

## Gotchas

- **Console encoding**: card glyphs (▶ ↻ ★) do not survive a cp1252 console. Set `PYTHONIOENCODING=utf-8` if printing them.
- **Never block on a modal**: a dialog opened with `exec()` waits for a person. Route it through `win.run_dialog` (the driver captures and rejects it).
- **Jobs are real**: `run_button.click()` starts a real subprocess; call `idle(win)` before capturing the result, and `win.bridge.stop()` when done.
- **The real data is never touched**: `APPDATA` points at a temp folder before `ryos` is imported, registry writes are off (`RYOS_NO_REGISTRY=1`), and so are Windows notifications (`RYOS_NO_TOASTS=1`) -- jobs run here, and each finished one would otherwise pop a toast on the screen in use.
