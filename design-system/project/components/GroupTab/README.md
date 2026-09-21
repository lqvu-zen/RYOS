# GroupTab

One tab per script group, plus a pinned **All** tab on the right.
`_add_tab_btn()` and `_apply_tab_style()` in `ryos/ui/app.py`.

Each tab is three nested frames: a wrapper painted the border colour with 1px
inset (that inset *is* the border), an inner frame carrying the fill, and inside
it the label plus a 3px indicator strip.

| | Active | Inactive |
|---|---|---|
| fill | `card_bg` | `tab_inactive_bg` |
| label | `accent`, `control-strong` | `tab_fg`, `control` |
| indicator | `accent` | `tab_inactive_bg` (invisible) |
| hover | `accent_wash` | `tab_inactive_hover` |
| wrapper | `card_bg` (border disappears) | `border` |

The active tab takes the **card** surface, not the window ground, so the tab and
the cards below it read as one plane while inactive tabs sit back on `bg`. Its
wrapper matches its fill, which dissolves the border — the tab joins the content.

## Rules

- `_add_tab_btn()` and `_apply_tab_style()` must stay in step; the second
  restyles in place on a group switch rather than rebuilding, and both encode
  the table above. Change one, change the other.
- Tabs are `space-3` apart with `pady=(3, 0)` — flush to the content below.
- Right-click opens the group menu. The All tab has no group, and no menu.
