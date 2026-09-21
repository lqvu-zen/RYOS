# FlatButton

The app's filled button. `_flat_button()` in `ryos/ui/theme.py`.

Borderless, square, `button` type (9pt bold), padded `space-12` × `space-5`,
`hand2` cursor, and a fill that swaps to its hover twin on `<Enter>`. There is
no transition and no pressed state beyond the hover fill — Tk's
`activebackground` covers the press.

It is built with a fixed character `width`, not a content width: the header's
three create buttons all pass `width=6` so they line up regardless of label.

## Consumer supplies

`parent, text, bg, hover_bg, command`, optionally `width` and `fg`.

## Variants — always pass a fill with its hover twin

| Role | `bg` / `hover_bg` |
|---|---|
| Create, modify, confirm | `btn_create_bg` / `btn_create_hover` (both track `accent`) |
| Run | `btn_run_bg` / `btn_run_hover`, with `fg=btn_run_fg` |
| Options, neutral dark | `btn_dark_bg` / `btn_dark_hover` |
| Quick Run | `bolt` / `bolt_hover`, with `fg=name_fg` |

Run and Quick Run both override `btn_fg`. Run's override is
`ink_on(btn_run_bg, btn_run_hover)` rather than a fixed colour, because
`btn_run_bg` is user-overridable — see `RunButton`.

## Rules

- Never a lone fill. A fill without a hover twin leaves the button dead under
  the pointer, and the hover swap is the app's only affordance.
- `bolt` needs `fg=name_fg`; white on gold is unreadable.
- Labels are sentence case and name the action.
