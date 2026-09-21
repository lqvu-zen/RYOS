# RunButton

The Run control, and the system's model for recovery. `run_button_style()` in
`ryos/ui/cards.py`.

It has two states and returns `(text, fg, active_fg, bg, hover, tooltip)` for
whichever applies:

| Last run | Glyph | Ink | Ink on hover | Fill | Hover | Tooltip |
|---|---|---|---|---|---|---|
| anything but a failure | `▶` | `btn_run_fg` | `ink_on(btn_run_hover)` | `btn_run_bg` | `btn_run_hover` | Run |
| `error` | `↻` | `error_fg` | `ink_on(btn_stop_active)` | `error` | `btn_stop_active` | Last run failed — click to run it again |

The ink is derived by `ink_on()` rather than fixed, because `btn_run_bg` is
user-overridable and a hardcoded ink would go unreadable against a pinned dark
run colour. See `accessibility.md`'s `ink_on` entry.

**The hovered ink is its own returned value, not the resting ink re-checked.**
The retry state rests on `error`, a mid red, and hovers to `btn_stop_active`, a
near-black one; no single ink clears both. Keeping `error_fg` through the swap
measures 2.64:1 on the dark themes against 7.96:1 for the derived one, so the
sixth element is load-bearing, not decoration.

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
