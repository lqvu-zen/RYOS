# FormControls

The ttk widgets used in dialogs, restyled to sit with the flat cards.
`_configure_ttk_styles()` in `ryos/ui/theme.py`.

ttk is switched to the **clam** theme first. On Windows the native renderer
swallows style overrides — a Combobox in particular ignores
`fieldbackground` entirely — so without `style.theme_use("clam")` half of this
does nothing. The call is wrapped in a `TclError` guard for platforms where clam
is absent.

**`Card.TCombobox`** — `card_bg` field, `name_fg` text, `accent_wash` selection,
`path_fg` arrow at `scrollbar-arrow` size, 1px border that turns `accent` on
focus. The focus ring is the only focus affordance in the app; keep it.

**`TScrollbar`** — thumb `border`, trough `bg`, no arrows drawn, going `path_fg`
when active. Slim and neutral on purpose: a scrollbar is not a control you aim
for in a list you scroll with the wheel.

**`Card.TNotebook`** — for Advanced Options. Borderless, tabs `space-12` ×
`space-6` in `body`, inactive on `bg` with `path_fg`, selected on `card_bg`
with `accent` — the same active-tab logic as `GroupTab`, so the two read as one
idea.

**Sash** — `gripcount=0`, 4px, painted `border`. The dotted grip marks clam
draws by default are the one clam detail the app removes.

## Rules

- Style through the named styles; don't configure a widget instance inline.
- A new ttk widget needs its style registered here, or it will render in clam's
  own grey on every theme.
- `_configure_ttk_styles()` runs at the end of `apply_theme()`. Anything read
  from `C` at import time will not re-theme.
