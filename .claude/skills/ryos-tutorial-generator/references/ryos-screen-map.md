# RYOS screen map

Every screen the guide covers, how `scripts/capture.py` reaches it, and the image it
saves. **The live screen wins**: when this file and a screenshot disagree, the screenshot
is right -- update this file.

## Sample data

The driver imports `samples/ryos-samples.json` into a throwaway database: the **Samples**
group (base folder: the repo's `samples/`) with *Say hello* (a favourite, presets
`--name RYOS`, `--loud`, `--loud --name Team`), *Always fails*, *Flaky*, *Count a minute*,
*Lots of output*, *Ask each run* (asks each run), *Write a report*, *Cleanup*,
*List folder* (batch), *System info* (PowerShell); pipelines *Morning report*,
*Resilient* (step policies) and *Side by side*. `capture.py` adds an empty **Tools** group
so the pills show more than one.

## Screens

| Image | Screen | Reached by |
| --- | --- | --- |
| `01-main-window` | Whole window, Samples | `driver.window("light")` |
| `01-rows-hover` | Three script rows, one hovered | `card.set_hovered(True)`; grab of the panel |
| `01-row-menu` | A script's right-click menu | `win.popup` hook + `_show_card_menu` |
| `02-add-script-dialog` | Script dialog, filled | `win.run_dialog` hook + `add_script()` |
| `03-running` | Running list with Stop | Run *Count a minute*, grab, stop it |
| `03-outcomes` | ● OK and ● Failed / ↻ | Run *Say hello* and *Always fails* |
| `03-output` | Output panel open | `set_output_expanded(True)` |
| `04-group-pills` | The pill row | top 150 px of the window |
| `04-group-menu` | A pill's right-click menu | `win.popup` + `_show_group_menu` |
| `04-new-group-dialog` | New group | `new_group()` |
| `05-preset-menu` | The row's preset chip menu | `card.menu_runner` + `params_pick.click()` |
| `05-script-presets` | Script dialog with presets | `edit_script(Say hello)` |
| `05-ask-each-run` | The ask-each-run prompt | Run *Ask each run* |
| `06-pipeline-editor` | Pipeline editor | `on_card_menu("pipeline", Resilient, "edit")` |
| `06-pipeline-output` | A pipeline's output | Run *Morning report* |
| `07-schedule` | Schedule dialog | card menu → schedule |
| `07-history` | Run history | card menu → history |
| `08-quick-run` | Quick Run box with a suggestion | `quick_run_bars["Samples"].open()`, type "hel" |
| `09-maximised-script` / `-pipeline` | Maximised layout | `resize(1280, 760)`, `set_workspace(True)`, `activated.emit()` |
| `10-file-menu` | File menu | `menu_bar.actions()[0].menu()` |
| `11-options-menu` | Options menu | `menu_bar.actions()[1].menu()` |
| `11-options-<tab>` | Each Options tab | `open_options()`, every tab of its `QTabWidget` |
| `11-appearance` | Appearance | `open_appearance()` (themes folder set to `theme-gallery/`, not the temp path) |
| `12-select-mode` | Select mode, two ticked | `set_select_mode(True)` |
| `12-compact` | Compact rows | `driver.window("light", compact_mode=True)` |
| `12-dark` | Dark theme | `driver.window("dark")` |

## Things that are easy to get wrong

- The **Running** list sits just above the Output bar, not at the top.
- Dropping files **adds them directly**; it does not open the script dialog.
- Import asks with **Merge** (default), **Replace** and **Cancel** buttons.
- Tab labels escape `&` as `&&` (`Startup && Window`): unescape before using one as a name.
- The throwaway data folder's path contains the user's name; keep it out of shots
  (the Appearance dialog's themes folder is pointed at `theme-gallery/` for that reason).
