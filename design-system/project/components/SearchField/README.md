# SearchField

The box over the list that filters it as you type. `ryos/qtui/shell.py`;
matching in `ryos/search.py`.

## Anatomy

A `QLineEdit`: `card_bg`, a 1px `border` (`accent` when focused),
`radius-control`, the placeholder `Search scripts and pipelines...`.

## Behaviour

- RYOS starts here, so typing filters at once.
- ↓ goes into the list on the first row showing; Esc clears the box.
- Nothing matches: the list says `Nothing here matches “zzz”.`
