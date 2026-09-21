# StatusBar

A single label across the bottom of the window. `_build_status_bar()` in
`ryos/ui/app.py`.

`status_bg` ground (derived: `bg` shaded ±5%), text in `btn_dark_hover`,
`meta` type, `space-10` × `space-4`, left-aligned, driven by one
`StringVar`.

It is the app's only ambient channel. Messages are complete sentences ending in
a period — `Ready.`, `Running nightly-backup…`, `3 scripts selected.` — and it
resets to `Ready.` when nothing is happening. Errors that need an answer go to a
dialog; errors that merely happened go here and to the output panel.

## Rules

- One line, never wrapped, never two.
- No colour. The bar doesn't turn red on failure; the card and the output panel
  carry that.
- Never a progress bar. Long work reports through the output panel, which is
  already open while a job runs.
