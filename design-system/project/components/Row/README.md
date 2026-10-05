# Row

One script or pipeline in a section. `ryos/qtui/cards.py`; what it shows is
`ryos/cardstyle.py`.

## Anatomy

A 3px `rail` down the left edge (`accent` for a script, `pipe_accent` for a
pipeline). Line one: the KindTag, the name in `title` (scrolling when cut
short), the OutcomeWord. Line two: the path relative to the group's folder --
or a pipeline's steps (`Backup photos → Clean temp`) -- and the preset Run will
pass, in mono `tab_selected_fg`. Then three 32px quiet cells -- edit,
run-with, star -- and Run.

## States

- *At rest* -- only Run, and a favourite's gold star (`star`).
- *Under the pointer* -- `card_hover`, and the quiet cells appear in space kept
  for them, so nothing moves.
- *Failed* -- Run becomes Retry; the word says `● Failed`.
- *Running / Retrying / Stopped* -- said by the word; Stopped is muted and
  keeps Run.
- *Chosen* (maximised) -- `accent_wash`; the detail pane shows it.
- *Keyboard* -- the wash and a 2px `focus_edge` outline, only when the
  keyboard put it there (a click focuses a row too, and leaves no mark).

## Compact

One line: star, name, then the kind and the outcome as columns, then Run
(26px). An empty outcome column is part of the row, not a box.

## Keyboard

The row is one Tab stop; its buttons are not. Arrows, Home/End and Page
Up/Down move between rows; Enter runs, F2 edits, the Menu key opens the row's
menu, Space ticks it in select mode.

## Rules

- Padding comes from `cardstyle.card_padding()`, never a literal.
- Run sits at the same x on every row, script or pipeline.
- Every hover-only button is also in the row's right-click menu.
