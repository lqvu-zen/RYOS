# SearchField

The filter above the tab bar, and the same treatment on every text input in the
app. `_build_cards_pane()` in `ryos/ui/app.py`.

A `🔍` glyph in `path_fg`, then a borderless `Entry` on `card_bg` with `bd=4`.
Tk's `bd` on a flat-relief entry becomes inner padding, which is how the field
gets its inset without a border: `relief="flat", bd=4`. The caret is `name_fg`.

**Placeholder text is real text.** There is no placeholder attribute in Tk, so
the field is seeded with its hint in `path_fg` and a flag tracks whether the
content is still the placeholder; the first keystroke clears it and switches the
colour to `name_fg`, and blurring an empty field puts it back. Filtering must
skip the placeholder value, or every card disappears on launch.

Filtering is live and matches names, paths and parameters
(`ryos/search.py`), and it hides whole group sections that have no match —
except a group with something running, which stays visible.

## Rules

- `card_bg` on a `bg` ground: the field is a surface, like a card.
- Placeholder in `path_fg`, entered text in `name_fg`. Never grey live text.
- Empty results show a message in `meta-italic`, never a blank pane.
