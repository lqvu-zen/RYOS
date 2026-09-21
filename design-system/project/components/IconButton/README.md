# IconButton

The square glyph buttons in a card's right-hand gutter: reorder, favourite,
edit, history, stop, run. The `_rbtn` factory inside `ScriptCard` and
`PipelineCard` in `ryos/ui/cards.py`.

Three characters wide, `control` type (10pt), full card height, no border. They
sit on a frame painted `border` with 1px frames between them, so the gutter's
background is what draws every divider.

Each button caches its own `_bg` and `_hbg` on the widget and restores from
those on `<Leave>` — so a button whose fill changes with state (run → retry,
stop idle → armed) must update both attributes, not just `config(bg=...)`, or
the next hover reverts it to the stale colour.

## Consumer supplies

`text, bg, hover_bg, command`, plus optional `tip`, `fg`, `active_fg`,
`disabled_fg` and `state`.

## Rules

- Default fill is `btn_neutral_bg` / `btn_neutral_hover` with `btn_neutral_fg`.
- A favourited star is `accent_wash`; an unfavourited one is neutral.
- A disabled button gets the `arrow` cursor and no hover bindings — the absence
  of the fill swap is how disabled reads.
- Every icon button takes a `Tooltip`. A bare glyph without one is a bug.
