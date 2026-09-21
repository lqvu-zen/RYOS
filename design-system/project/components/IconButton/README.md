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
- Flip a button's state with `set_button_enabled()`, never a bare
  `config(state=...)`. Tk dims only the label, and on a custom palette it dims
  it to a Windows system colour unrelated to the theme; the helper swaps the
  slab too, which is what makes the state legible. It also gives the button the
  `arrow` cursor.
- Tk keeps delivering `<Enter>` to a disabled widget, so the hover bindings
  check state before swapping. Skip that check and a dead button lights up
  under the pointer and looks clickable.
- A blank spacer cell is painted `border`, the strip's own colour — not
  `btn_neutral_bg`, which sits 1.03:1 against the strip and reads as a button
  whose icon failed to load rather than as empty space.
- Every icon button takes a `Tooltip`. A bare glyph without one is a bug.
