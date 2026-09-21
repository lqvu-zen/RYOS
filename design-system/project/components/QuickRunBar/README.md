# QuickRunBar

A per-group command line: type a script name and its parameters, press Enter,
and it runs. `_build_quick_run_bar()` in `ryos/ui/app.py`.

Collapsed by default behind a `⚡` button in the group banner — the **only**
control besides the header mark painted `bolt`, with `fg=name_fg` because white
on gold is unreadable. Gold here means *this is the fast path*, which is why it
is spent on exactly these two things.

Expanded, the bar is a frame on `bg` with a `hairline` border, holding the same
`SearchField` treatment: `card_bg`, `relief="flat"`, `bd=4`, `control` type,
with the placeholder `script name [params...]` in `path_fg`.

One bar per group, packed after that group's banner, and each keeps its own
entry and key bindings — `self._quick_run_buttons[gname]` and `_bars[gname]`.

## Rules

- The bar frame must be a sibling of the banner, not a child, or
  `pack(after=banner)` cannot place it.
- `bolt` on the toggle, `name_fg` on the glyph. Never `btn_fg`.
- Escape collapses the bar; Enter runs and leaves it open for the next command.
- It is a shortcut, never the only route — everything it does is also a card.
