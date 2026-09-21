# AppHeader

The band across the top of the window: the mark on the left, the create buttons
and the options gear on the right. `_build_header()` in `ryos/ui/app.py`.

`header_bg` ground, `space-18` horizontal and `space-14` vertical padding — the
value that sets the window's outer margin, so anything else flush to the window
edge should match it.

The mark is two labels, not an image: `⚡` in `bolt` and ` RYOS` in
`fg_on_dark`, both `brand` (14pt bold). It is the largest type in the app and
the only place `bolt` appears besides the Quick Run trigger. The drawn icon in
`assets/AppIcon/` is for the OS — taskbar, tray, installer — never the header.

The three create buttons all pass `width=6` so they align regardless of label
length, and the gear uses `btn_dark_bg` rather than the accent: it opens a menu
rather than creating anything, and shouldn't compete with the three that do.

## Rules

- Text on `header_bg` is `fg_on_dark`. Never a literal white.
- New header actions are `btn_create_bg` only if they create something.
  Everything else is `btn_dark_bg`.
- Every header button takes a `Tooltip` — the gear is a bare glyph.
