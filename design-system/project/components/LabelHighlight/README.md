# LabelHighlight

A name coloured to make one row stand out: right-click → Highlight.
`ryos/themes.py` `HIGHLIGHT_SEEDS`, `readable_highlight()`.

## Colours

Seven seeds -- red, orange, yellow, green, teal, blue, purple -- that are never
painted as they are: `readable_highlight()` shades a seed in 8% steps until it
clears 4.5:1 on `card_bg` and `card_hover`, so one palette stays legible on
every theme. The `highlight-*-ink` tokens are those results.

## Rules

- It colours the name only; the row's rail, kind and outcome are unchanged.
- In the detail pane the name is shaded against the window instead.
