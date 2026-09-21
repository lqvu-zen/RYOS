# StatusBadge

The last-run chip on row two of a card. `_status_badge()` in `ryos/ui/cards.py`.

`badge` type on a filled ground, `space-5` × `space-1`, two states and no third:
`✓ OK` on `ok`, `✕ Failed` on `error`. A card that has never run returns `None`
and the row simply doesn't include it — there is no "never run" chip, because
the absence of a timestamp already says so.

**It reports; it does not act.** The retry lives on the Run button, which is
present at every card size. Adding a click handler here would duplicate a
control the user already has.

Both states carry a glyph as well as a colour, which is what makes them
survivable: `fg_on_dark` on `ok` measures 2.10:1 and `btn_fg` on `error`
measures 3.63:1 on the dark themes. See `accessibility.md`.

## Rules

- Return `None` for an unknown status. A value left by a future palette must
  never render as an invisible or garbage chip.
- Pack it before the path on its row — the path expands and will otherwise
  squeeze it to a pixel.
- Never put a badge on `card_bg` unfilled; a badge is always a filled ground.
