# OutputPanel

The console under the card list, in the bottom half of a vertical
`PanedWindow`. `_build_output_panel()` and the drain loop in `ryos/ui/app.py`.

It keeps **its own dark world on every theme.** `out_bg` is `#1e1e1e` under
Light, Sepia and Forest Canopy alike, with `out_header` and `out_tabbar` above
it and `fg_on_dark_2` on the chrome. A theme may override the five `out_*` keys
in its seed's advanced section, but the default is deliberate: this is a
terminal, and a terminal that changes colour with the app's chrome stops reading
as one.

Body type is `terminal` (Consolas 10), and the four line colours are the only
semantics: `out_stdout` for program output, `out_stderr` for its error stream,
`out_status` for the runner's own lines (started, exit code), `out_success` for a
clean exit. All four clear 6.0:1 on `out_bg`.

A tab per job on `out_tabbar`, plus a pinned **All** tab that interleaves
everything. Find is inline in the header, mono-set, with the current match
highlighted in `bolt` on `out_bg`.

## How text gets here

Never directly. The worker thread puts lines on a `queue.Queue`; the main loop
drains it on a recurring `after(80, …)` timer and writes to the `Text` widget.
Writing to the widget from the worker will eventually corrupt Tk's state.

## Rules

- Tag every line with one of the four `out_*` colours. Untagged text inherits
  `out_stdout` and a status line becomes indistinguishable from program output.
- The panel collapses to its header, never to nothing — the toggle must stay
  reachable.
- Don't tint it to match the chrome.
