# Rail

The column of places down the left edge of the maximised window.
`ryos/qtui/rail.py`; which places, in what order, is `ryos/detail.py` `RAIL`.

## Anatomy

A 56px column on `card_bg` with a hairline on its right. 40px icon buttons
(20px icons): **Library**, **Search**, **Activity** at the top; **Appearance…**
and **Options…** at the foot.

## States

- *Showing* -- the place or panel in view sits on `accent_wash`, its icon in
  `tab_selected_fg` (Library always; Activity while the bar is shown).
- *Badge* -- Activity carries a running count: `running` fill, `badge_fg`
  words, 16px tall, round. Its accessible name says "Activity, 2 running".
- Hover `tab_inactive_hover`; keyboard focus a 1px `accent` edge.

## Rules

- Places, not actions -- making things stays in the header.
- Only maximised. Restored, the rail goes and nothing replaces it.
