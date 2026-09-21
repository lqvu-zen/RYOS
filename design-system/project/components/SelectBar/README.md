# SelectBar

The banner shown while multi-select is on. `_build_select_bar()` in
`ryos/ui/app.py`.

`warn_bg` ground with a `warn_border` hairline and `warn_fg` text — the app's
only use of the warning family, and it is not a warning. It is a **mode
indicator**: checkboxes have appeared on every card and the next click means
something different. Amber because the state is temporary and the user must be
able to see, at a glance, that they are in it.

Left: the hint, in `body` — `Tick the checkboxes next to the scripts you want to
run or delete.` — replaced by a live count once anything is ticked. Right:
Select All flat on the banner (`warn_bg` fill, `warn_border` hover), then
`▶ Run Selected` on `btn_run_bg`, then `🗑 Delete Selected` on a fixed dark red
that is neither `error` nor `btn_stop_active`: destructive-and-bulk is its own
weight, and it must not read as the retry red.

`warn_fg` on `warn_bg` measures 7.0–8.4:1 across the themes — the most legible
pair in the system, which is appropriate for the one thing that says *you are in
a mode*.

## Rules

- Packed on demand, never hidden with a disabled state.
- The hint is the empty state. Swap its text for the count; don't add a second
  label.
- Destructive bulk actions get the dark red, not `error`.
