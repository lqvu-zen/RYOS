# KindTag

What a row is, in small coloured capitals before its name: `PYTHON`,
`POWERSHELL`, `BATCH`, `PIPELINE` (`PIPE` when compact). The same style for
badges: `ASKS EACH RUN`, `SCHEDULED`. `ryos/qtui/cards.py` `_tag`; colours from
`ryos/interpreter.py` `_script_tag()`.

## Colours

A language's colour is fixed across themes -- it is part of the label -- but
never painted as-is: the `tag-*-ink` tokens are each shaded to read on the row
in every theme. A pipeline's is `ink-pipe_accent`.

## Rules

- `caption` capitals, 0.4px tracking. Words, not filled chips.
- A new extension in `_script_tag()` needs an entry in `design-system/build.py`
  `TAG_ORDER`, or the build stops.
