# SectionPanel

One of a group's three sections -- Favorites, Pipelines, Scripts -- as a
heading over one panel whose rows share it. `ryos/qtui/sections.py`; rules in
`ryos/sections.py`.

## Anatomy

- **Heading** -- a fold arrow (▾ open, ▸ folded) and the label in `caption`
  capitals, `muted_fg`, darkening to `name_fg` under the pointer. Folded, it
  carries a count: `SCRIPTS (4)`.
- **Panel** -- `card_bg`, a 1px `border`, `radius-card`. Rows inside are split
  by a hairline; the last has none.
- **Empty** -- a muted sentence that says what goes there and how to add it.

## Rules

- The search box, the pills and the panels line up on the list's 14px margin.
- Favorites is not a panel: its chips wrap on the window's ground
  (FavoriteChip).
