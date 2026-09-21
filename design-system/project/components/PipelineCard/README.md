# PipelineCard

A sequence of scripts run in order, shown as one card. `ryos/ui/cards.py`.

Structurally identical to `ScriptCard` — same rail, body, gutter — with one
change that carries all the meaning: the rail is `pipe_accent`, a violet that
sits nowhere else in the chrome. A user scanning the list separates pipelines
from scripts on that 5px strip alone, so it is the one thing you must not
restyle.

Where a script shows a type badge, a pipeline shows its step count and the
steps' own type badges. The name is a click target: it opens the step editor.

## Consumer supplies

`pipeline_id`, name, group, a `ScriptDB` (the card reads its own steps via
`list_pipeline_steps`), and `on_run` / `on_edit` / `on_refresh` callbacks.

## Rules

- `list_pipeline_steps()` rows are unpacked by name at the call site. Slice to a
  fixed width (`row[:8]`) — appending a column has silently broken this three
  times, and `TestRowWidthsArePinned` exists to catch it.
- Stopping a pipeline walks `job.active_processes()`, not `current_process`: a
  pipeline can have several steps in flight.
- `pipe_accent2` is for step connectors and hover, derived at +12%.
