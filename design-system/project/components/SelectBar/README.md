# SelectBar

Select mode's bar: tick rows, then run or delete them together.
`ryos/qtui/shell.py` `_build_select_bar`; wording in `ryos/selection.py`.

## Anatomy

A strip in the warn colours (`warn_bg`, `warn_border`, `warn_fg`) -- you are in
a mode. The words say what to do (`Tick the checkboxes next to the scripts you
want to run or delete.`), then how many are ticked (`2 of 6 selected`). Then
**Select All**, **Run selected** in Run's green with the play icon, and a
trash icon for **Delete selected**.

## Rules

- The warn colours mean a mode, and nothing else uses them.
- Each row shows a check box; Space ticks the row the keyboard is on.
- Delete selected confirms, naming how many go.
