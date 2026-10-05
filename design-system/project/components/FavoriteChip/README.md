# FavoriteChip

A starred script or pipeline in the Favorites strip: a pill of its own.
`ryos/qtui/cards.py` (`chip=True`), laid out by `FlowLayout`.

## Anatomy

The name (shortened with an ellipsis -- a chip is sized to its text), the
outcome as a dot alone, and a 24px Run. `card_bg`, a 1px `border`, half its
height in radius.

## Rules

- A dot alone is colour alone, so it carries the words: its tooltip and
  accessible name say `Last run: Failed`.
- Retry replaces Run after a failure, as on a row.
- Keyboard focus is a `focus_edge` border and the wash.
