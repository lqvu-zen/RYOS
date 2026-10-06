# RunButton

The one filled thing on a row: a green circle that runs, which becomes Retry
after a failure. `ryos/cardstyle.py` `run_button()`; drawn in
`ryos/qtui/cards.py`.

## Sizes

32px on a row, 26px compact, 24px on a favourite chip. In the detail pane it
grows words: a 38px round-ended **Run** / **Retry**.

## States

- *Run* -- `btn_run_bg`, the play icon in `btn_run_fg`; `btn_run_hover`.
- *Retry* -- after a failure, the same button on `error` with the retry icon:
  the recovery is on the control that fixes it, not a second one. Its tooltip
  says why: `Last run failed — click to run it again`.
- *Stopped* -- not a failure: it stays Run.
- *Stop* -- while the item's OWN run is going: `btn_stop_active` with the
  stop icon in its ink (`Running — click to stop it`). Pressed again, Run only
  started a second copy. A script running only as a pipeline's step keeps
  Run -- stopping it there would stop the pipeline (`jobs.own_runs`).
- *Focus* -- a 2px `name_fg` ring outside it.
