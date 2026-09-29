# Lens 5: interaction (states, feedback, preventing mistakes)

How the interface behaves between screenshots: what each control does under
the pointer, while busy, when it can't be used, and how the app keeps people
from losing work. Screenshots show one moment; this lens is about the
transitions, so read the code and drive the states with the run-ryos driver.

## Every control's states

For each kind of control, check the full set is defined and reads as one
family. Look in `ryos/qtui/stylesheet.py` for the rules and in the widget
code for anything set per widget.

| State | What good looks like here |
| --- | --- |
| Rest | Quiet: words or glyphs, one filled primary per area |
| Hover | A visible change (wash, ink), never a layout shift. Rows show their waiting buttons in space already kept |
| Pressed | Distinct from hover, briefly |
| Focus | Visible in light and dark themes (see `accessibility.md`) |
| Disabled | Looks unavailable (`btn_disabled_*`), and says why in a tooltip when it isn't obvious |
| Busy / running | Something moves or counts: the Running list, the row's state, output arriving. A control that would start the same thing again is disabled or turns into Stop |
| Done / failed | The row's outcome word, Retry in Run's place, the status bar; the output tab is one click away |
| Selected | The chosen pill, the chosen row (maximised), the output tab in front |

Missing states are findings. Drive them: `card(win, "Count a minute")
.run_button.click()` for running, "Always fails" for failed, `set_hovered(True)`
on a row for hover, `set_select_mode(True)` for select mode.

## Feedback timing

- Pressing Run changes something at once (within 400 ms), before the script
  prints: the Running list appears, the row shows it is busy.
- Long operations (building the Quick Run index, importing, a long pipeline)
  say they are working and, where they can, how far along.
- Nothing blocks the window while a script runs -- output is drained on a
  `QTimer`, never waited on.

## Preventing mistakes

- **Destructive actions confirm, and name what goes**: delete a script (and
  the pipelines that lose its step), delete a group, Delete All, delete the
  selected. The prompt's buttons name the action. Check `cardmenu.py`,
  `selection.py`, `configio.py`.
- **Undo where cheap**: a favourite toggled, a row moved, a preset chosen can
  simply be done again; a delete cannot -- so it confirms.
- **Dangerous things look dangerous**: `menu_danger` in menus; the Stop
  button only red while something is running.
- **Close and quit with work running**: `traypolicy.quit_prompt` asks before
  stopping live jobs. Check the wording names how many.
- **Double actions**: pressing Run twice quickly, or Run while the same
  script is running -- what happens, and is it what a person expects? The job
  cap refuses with a notice (`MainWindow._show_refusal`); check it says why.
- **Inputs that guard themselves**: the script dialog refuses a missing
  file, a schedule with no days; the message says what to fix and focus
  goes to the field.
- **Drag and drop**: the drop marker shows where a row will land; dropping
  on a pill moves the row to that group; a drop that can't happen shows
  nothing, not a wrong marker.

## Hover and discoverability

Rows keep Edit, Run with… and ☆ until the pointer comes. That is quieter, and
it hides them: check each is also in the right-click menu, that the menu is
discoverable (does anything hint at it?), and that the maximised pane shows
them all without hover.

## Output for this lens

Findings tagged `[interaction]`: the control, the state that is missing or
wrong, how to reproduce it (a driver call), and the fix. A destructive action
with no confirmation, or a state that leaves someone unsure whether anything
happened, is High.
