# PresetPill

A script's saved parameters in its Overview: pick one, or run with it now.
`ryos/qtui/detail.py` `_fill_chips`.

## Anatomy

A pill (32px, `control_edge`, `card_bg`): the parameters in mono, and a 24px
play button of its own. The chosen one -- what Run passes -- is on
`accent_wash` with an `accent` edge and its words in `tab_selected_fg`.

## Rules

- Clicking the words chooses the preset for Run; the play button runs with it
  straight away (choose, then Run -- through the row).
- Pills wrap; `(no parameters)` is always the first.
