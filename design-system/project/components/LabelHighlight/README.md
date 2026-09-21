# LabelHighlight

A user-set tint on a card's name, and the system's one piece of generative
colour. `HIGHLIGHT_SEEDS` and `highlight_fg()` in `ryos/ui/theme.py`.

Seven colours — red, orange, yellow, green, teal, blue, purple — chosen from a
right-click submenu. **The seven values are seeds, not paint.** `_readable_on()`
shades a seed in 8% steps, lighter on a dark surface and darker on a light one,
until it clears 4.5:1 against every surface it will be drawn on, and only then
does it become a colour.

For a card that means both `card_bg` and `card_hover`, so a highlighted name
stays readable while the pointer is over it. That is why one palette of seven
serves all thirteen themes instead of needing a hand-tuned set per theme.

```python
highlight_fg("teal")                    # against the live card surfaces
highlight_fg("teal", C["menu_bg"])      # the swatch in the dark popup menu
```

## Rules

- Pass the surfaces the text will actually land on. The right-click menu passes
  `menu_bg`; passing nothing defaults to the card pair.
- An unknown key returns `None`, and the caller falls back to `name_fg` — so a
  value left in the database by a future palette degrades instead of rendering
  as garbage.
- The loop is capped at 30 steps and returns its last value either way. Some
  themes (`sunset-boulevard`) need about 20; most converge in two or three.
- Results are cached on `(seed, surfaces)`. Because the surfaces are part of the
  key, a theme switch can never serve a stale colour — there is nothing to
  invalidate.
- Highlights are decorative. Nothing may depend on telling them apart.

## What the seven seeds resolve to

| Key | Seed | Light theme | Dark theme |
|---|---|---|---|
| red | `#e05252` | `#bd4545` (2 steps) | `#e67676` (3 steps) |
| orange | `#e08a3c` | `#9f602a` (4 steps) | `#e08a3c` (0 steps) |
| yellow | `#d4a72c` | `#8a6b1b` (5 steps) | `#d4a72c` (0 steps) |
| green | `#3fa45b` | `#2f7e45` (3 steps) | `#4eab68` (1 steps) |
| teal | `#2aa3a8` | `#1f7e81` (3 steps) | `#3baaae` (1 steps) |
| blue | `#4a90d9` | `#396fa8` (3 steps) | `#5898dc` (1 steps) |
| purple | `#a06ee0` | `#875cbd` (2 steps) | `#ae83e4` (2 steps) |

Orange and yellow need no shading at all on Dark — they already clear the
floor against `card_bg` and `card_hover`, so the loop exits on its first check.
