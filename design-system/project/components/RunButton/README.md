# RunButton

The Run control, and the system's model for recovery. `run_button_style()` in
`ryos/ui/cards.py`.

It has two states and returns `(text, bg, hover, tooltip)` for whichever
applies:

| Last run | Glyph | Fill | Tooltip |
|---|---|---|---|
| anything but a failure | `▶` | `btn_run_bg` / `btn_run_hover` | Run |
| `error` | `↻` | `error` / `btn_stop_active` | Last run failed — click to run it again |

**After a failure the Run button becomes the retry.** It is the same action, so
it needs no second control — and unlike a status badge, the button strip is
present in every card mode and at every size, so the recovery survives compact
mode where the badge row does not.

`↻` rather than `✕`: in the red fill a cross reads as stop.

## Rules

- Call `run_button_style()`; never assemble the pair inline. It is pure and
  unit-tested, and both call sites must agree.
- Don't add a retry affordance elsewhere. The `✕ Failed` badge reports only.
- Red here means *this failed, press to try again* — not *destructive*.
  Destructive actions use `menu_danger` in a menu, or a dark red fill.
