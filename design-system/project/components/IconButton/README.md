# IconButton

The app's one drawn icon set and the quiet buttons made from it.
`ryos/qtui/icons.py`: `SHAPES`, `IconButton`, `IconLabel`.

## The set

Line icons on a 24-unit grid with a 2-unit stroke and round ends, outline
except where filling means something: play, stop, the brand bolt and a
favourite's star. Each is tinted by a colour role (`muted`, `text`, `link`,
`star`, `pipe`, `danger`…) and re-tinted on a theme change. Usually 16px.

## Quiet buttons

A row's cells, the detail pane's star and ⋯, a tab's close: `muted_fg` at
rest, darker under the pointer, on `accent_wash` when focused, never a box of
their own. Each has an accessible name (`set_tooltip`).

## Rules

- Never a font glyph or an emoji as an icon -- they come in two fonts and the
  colour-emoji font's own colours. `check_one_icon_set` in `tests/qt_smoke.py`
  fails on one. Kept as typography on purpose: the `+` of + Script, the ●
  outcome dots, the ▾/▸ fold arrows.
