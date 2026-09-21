# ScriptCard

One script in the list: a 5px `accent` rail, the name and path, and the controls
that act on it. `ryos/ui/cards.py`.

Left to right the card is a rail, a body on `card_bg`, and a gutter painted
`border` whose buttons are separated by the border showing through a 1px gap —
the divider is the background, not a drawn line.

The body is two rows. **Row one** is the type badge, any state badges
(`⏱ TEMP PARAM`, `🕒 SCHEDULED`), then the name in `title` inside a
`ScrollingLabel`. **Row two** is the path in `meta`, then the last-run
timestamp, then the `StatusBadge`.

Row two packs right to left. The path is the only element that can be
arbitrarily long, so it is packed last and takes what is left; packed in reading
order it consumed the row and squeezed the status badge to a pixel. Keep that
order when you add to this row.

## Consumer supplies

The record (id, name, path, params, interpreter, last run and status, group,
favourite flag, label colour), a `ScriptDB`, a runner, and callbacks for
refresh, reorder and favourite. Also `group_base_dir`, against which the path is
shown relative when it sits underneath.

## Rules

- Padding comes from `card_padding()` and `row_metrics()`, never a literal —
  six density combinations depend on it.
- The name is `highlight_fg(label_color)` when a label colour is set, else
  `name_fg`. Resolve it against `card_bg` **and** `card_hover`.
- In compact mode rows two and three are gone. Anything that must survive
  compaction belongs on the button strip, which is present at every size.
- The rail is `accent`. `pipe_accent` on this card would read as a pipeline.
