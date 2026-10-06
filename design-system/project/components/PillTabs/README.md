# PillTabs

Every tab in RYOS is a pill: the group tabs, the detail pane's tabs, Options'
tabs and the output panel's run tabs. `ryos/qtui/stylesheet.py`.

## Anatomy

The chosen pill is filled with `name_fg` and its words in `pill_fg` (the
window's colour, bold); the others are `pill_idle_fg` words on the window in a
1px `pill_edge` outline -- the only thing that says they are buttons, so held
to 3:1 -- and `tab_inactive_hover` under the pointer. The chosen pill's border
is its own fill, so switching never shifts anything. 28px tall (24px over the
output), radius half the height.

## Variants

- **Groups** -- with a dashed round `+` for a new group just before **All**.
  Maximised, the pills give way to a group picker (a field with a chevron).
- **Detail pane** -- Overview · Output · History.
- **Output** -- a pill per run, closable with the close icon; a pipeline's
  carries the bolt in `pipe_accent`.

## Rules

- Qt draws no rounding past half a height: keep the radius at or under it.
- The chosen pill must be unmistakable from across the desk.
