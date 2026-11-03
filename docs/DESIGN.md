---
version: alpha
name: RYOS
description: A dense, quiet Windows desktop tool for running your own scripts; neutral surfaces, a muted blue accent, a green Run button (inferred, please check)
colors:
  primary: "#4a6fa5"
  secondary: "#3d5d8a"
  surface: "#ffffff"
  background: "#f0f2f5"
  on-surface: "#1a1a2e"
  muted: "#626975"
  border: "#dde2ea"
  header: "#1e2a3a"
  run: "#2ecc71"
  on-run: "#000000"
  stop-active: "#8b0000"
  error: "#c0392b"
  on-error: "#ffffff"
  favourite: "#FFD23F"
typography:
  body:
    fontFamily: Segoe UI
    fontSize: 10pt
    fontWeight: 400
  card-name:
    fontFamily: Segoe UI
    fontSize: 11pt
    fontWeight: 700
  card-path:
    fontFamily: Segoe UI
    fontSize: 9pt
    fontWeight: 400
  output:
    fontFamily: Consolas
    fontSize: 9pt
    fontWeight: 400
rounded:
  sm: 3px
  md: 4px
  pill: 16px
spacing:
  sm: 4px
  md: 8px
  lg: 12px
components:
  button-run:
    backgroundColor: "{colors.run}"
    textColor: "{colors.on-run}"
    rounded: "{rounded.pill}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
  button-primary-hover:
    backgroundColor: "{colors.secondary}"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
omitted:
  - section: Elevation & Depth
    reason: Cards are flat, separated by a 1 px border (inferred, please check)
---

# Design system: RYOS

Format: Google's DESIGN.md (`google-labs-code/design.md`, spec `alpha`). The front matter holds the tokens; the sections say how to use them. Values above are the Light theme's reference palette in `ryos/themes.py` (`_REFERENCE_FALLBACK["light"]`) and the sizes in `ryos/qtui/stylesheet.py`. Dark and the gallery themes derive from seeds (`build_palette`), so the live colours are whatever the chosen theme gives; the tokens here name the roles.

Token tiers: reference tokens hold raw values; semantic tokens say what a value is for; component tokens bind semantic tokens to a part. Components reference semantic tokens, never raw values.

## Overview

A tool people leave open all day to run their own scripts. Dense rows, muted neutrals, one accent for actions that change things, and a green Run button that is always the clearest control on a row. Every colour comes from the active theme's palette, never a literal in a widget (inferred, please check).

## Colors

`primary` and `secondary` (hover) mark edit, create and modify actions. `run` is only for running; `stop-active` only for a running stop. `error` is for failed runs and is paired with text. `favourite` is the star. Themes must keep text readable on each surface: `ryos/themes.py` has `contrast_ratio` (WCAG) for this.

## Typography

Segoe UI 10 pt for the interface; card names 11 pt bold (10 pt semi-bold on compact rows); paths and captions 9 pt. Output, logs and code use Consolas 9 pt.

## Layout

Rows are lists inside group tabs. Normal and compact rows keep the same cells at the same x positions (RC-04). The maximised layout puts the list on the left, a detail pane and rail on the right, and the Activity bar below. Compact controls have a 24 px minimum height.

## Elevation & Depth

None: cards are flat with a 1 px `border`; hover changes the background.

## Shapes

`sm` (3 px) on buttons, `md` (4 px) on cards and inputs, `pill` (16 px) on the Run button.

## Components

Run button, row (normal, compact, favourite chip), group tab, output panel, Quick Run bar, Activity bar, dialogs, tray menu. The `docs/BEHAVIOUR.md` § Rows and cards lists what each row shows and where.

## Do's and Don'ts

- Do take every colour from the theme palette so all gallery themes keep working.
- Do check a UI change on normal and compact rows, favourites, the All tab, the detail pane and select mode.
- Do pair colour with text or an icon for status.
- Don't hardcode a hex value in `ryos/qtui/*`.
- Don't move the Run button when hover controls appear (RC-03).
- Don't draw an empty outcome slot as an empty box (RC-05).

## Platforms

| Platform | Ships | Unit | Notes |
|---|---|---|---|
| web | no | | |
| desktop | yes | pt for text, px for geometry | Windows 11; Qt widgets via PySide6; multi-monitor |
| mobile | no | | |
| game | no | | |

## States

Rows and buttons cover default, hover, focus, disabled, running, succeeded, failed, selected (select mode), and dragging (reordering). Error is shown as a failed outcome with text, never as an empty row.

## Inputs

Mouse and keyboard, plus file drops. Targets at least 24 px high on compact rows. Keyboard focus must stay visible; the review-ryos-ui checks cover tab order and names.

## Motion

Almost none: hover and state changes are immediate. Output scrolls as lines arrive, drained every 80 ms. Nothing animates in a way that needs a reduced-motion switch (inferred, please check).
