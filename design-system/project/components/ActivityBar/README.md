# ActivityBar

What is running, what runs next and what ran last, down the right edge of the
maximised window. `ryos/qtui/activity.py`; what it lists and how it says it is
`ryos/activity.py`.

## Anatomy

`ACTIVITY`, then three boxes (`card_bg`, `border`, `radius-card`):

- **Running now** -- the window's running list, lent here: each job on its
  running wash (`running_wash`, or `pipe_wash` for a pipeline) with its elapsed
  time and a Stop icon.
- **Up next** -- the next scheduled runs, soonest first, with a clock:
  `Tomorrow 08:00 · Daily at 08:00`.
- **Recent** -- the last runs, a pipeline standing for its steps, with how
  they went in words: `OK · 03:00 · 9.4s`, `Failed · 02:10 · exit code 1`,
  `Stopped · Yesterday 18:02 · 1m 05s`.

## Rules

- A line under Up next or Recent is a button that shows its item: Recent on its
  History tab.
- Each box says what would be there when empty: `Nothing running.`,
  `Nothing scheduled.`, `No runs yet.`
- Shown or hidden from the rail, and remembered.
