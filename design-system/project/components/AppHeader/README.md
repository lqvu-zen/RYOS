# AppHeader

The bar across the top of the window: the drawn bolt and RYOS, the File /
Options / Help menus, and the buttons that make things. `ryos/qtui/shell.py`
`_build_header`, styled as `QFrame#appHeader`.

## Anatomy

`bolt` icon (role `bolt`), the wordmark in `brand`, the menus, a stretch, then
**+ Pipeline** and **+ Group** outlined in `header_edge` and **+ Script**
filled with `accent` -- the window's one primary button.

## Rules

- Places to go are menus; things to make are buttons. Nothing else goes here.
- Words and menus use `header_fg`, never `fg_on_dark` directly: a few themes
  have a pale `header_bg`.
- The outline is the only thing that says + Pipeline and + Group are buttons,
  so `header_edge` is held to 3:1.
- Hover lifts the header toward its ink (14%); a focused button gets a
  `header_fg` edge.
