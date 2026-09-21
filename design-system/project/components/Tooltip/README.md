# Tooltip

A delayed label that follows the pointer. `Tooltip` in `ryos/ui/widgets.py`.

An override-redirect `Toplevel` on `tooltip_bg` with a `tooltip_border`
hairline, `fg_on_dark` text in `meta`, `space-6` × `space-3`. It appears
500ms after `<Enter>` and leaves on `<Leave>` or any button press.

Placement goes through `place_near()` (`ryos/ui/placement.py`), which offsets
from the pointer and keeps the tip on the **pointer's own monitor** — clamping
to the primary display is how tooltips end up on the wrong screen in a
multi-monitor setup.

Copy is a fragment, no period, and earns its place by saying something the glyph
does not: "Last run failed — click to run it again", not "Run".

## HoverPreview

Its richer sibling in the same module: a 1000ms dwell, and a caller-supplied
`builder(inner)` fills a `card_bg` panel inside a 1px `border` frame instead of
a string. It exists for compact cards, where the path and status rows are gone.

Its leave-detection is containment-aware. `<Leave>` fires on the parent every
time the pointer crosses into a child, so an immediate hide would flicker on a
multi-label card; instead it waits 120ms and walks up from the widget under the
pointer to check whether it is still inside the anchor.

It binds `<Button-1>`, `<Button-2>` and `<Button-3>` as well as `<ButtonPress>`:
those are more specific in Tk's dispatch, so a widget with its own click handler
would never reach the generic binding and the preview would survive the click.

## Rules

- Every bare-glyph control gets one. That is most of the app's buttons.
- 500ms for a tooltip, 1000ms for a preview. Don't tune per call site.
- Both bind `<Destroy>` and cancel their pending `after` job — a tooltip
  outliving its widget raises `TclError` on the next tick.
