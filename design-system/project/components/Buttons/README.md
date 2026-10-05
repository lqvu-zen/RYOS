# Buttons

`QPushButton` in its roles, all from `ryos/qtui/stylesheet.py`.

| Role | Look | Where |
| --- | --- | --- |
| Primary | `accent` fill, `primary_fg` words | + Script, a dialog's default (Save) |
| Neutral | `btn_neutral_bg`, 1px `control_edge`, `radius-control` | Cancel, Select all, Clear history… |
| Link | words in `tab_selected_fg`, the wash under the pointer | Schedule…, Run with…, Edit |
| Stop | `btn_stop_active`, `stop_fg` -- only while something runs | the running list |
| Disabled | `btn_disabled_bg` / `btn_disabled_fg` | Run selected with nothing ticked |

## Rules

- One filled button per area. A second beside the first is a design bug.
- A button that opens a dialog ends in an ellipsis.
- Confirmations name the choice -- **Clear history** / **Keep**, **Merge** /
  **Replace** -- never Yes / No; the safe one is the default.
- A neutral button's edge is what makes it a button in Light, where its fill
  is 1.01:1 to the window.
