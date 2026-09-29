# Lens 2: accessibility (WCAG 2.2 AA, for a Qt desktop app)

Adapted from the `design:accessibility-review` skill and the accessibility
section of `qt-development-skills:qt-ui-design`. Web-only criteria (ARIA,
alt text on images, landmarks) are swapped for their Qt equivalents.

Start from the audit (`scripts/audit.py`): it measures most of this. Then
check by hand what it can't.

## What the audit measures

| Criterion | Check | In Qt |
| --- | --- | --- |
| 1.4.3 Contrast (text) | ≥ 4.5:1, large text ≥ 3:1 | Key pairs in every theme; `drawn_colors()` and `DRAWN_PAIRS` are the fix points |
| 1.4.11 Non-text contrast | ≥ 3:1 for control edges and states | `control_edge` (the floor is 1.6 by design -- say so if you keep it) |
| 2.5.8 Target size | ≥ 24×24 px, or spaced so a 24 px circle doesn't overlap | Labelled check boxes are exempt (the label is part of the target) |
| 4.1.2 Name, role, value | Every control has a name | A glyph button (▶ ✎ ☆ + ⋯) is read as its glyph; set `setAccessibleName("Run")`. A tooltip is only the description |
| 1.3.1 / 3.3.2 Labels | Inputs are linked to their label | `QLabel.setBuddy(field)`, a `QFormLayout` row, or `setAccessibleName` |
| 2.1.1 Keyboard | Every control is reachable | Nothing interactive with `Qt.NoFocus` |
| 2.4.3 Focus order | Tab follows the reading order | `QWidget.setTabOrder` where the layout order is wrong |
| 1.4.1 Use of colour | State not by colour alone | The `*_deutan.png` simulations: OK vs Failed, Run vs Retry, pipeline vs script must still differ |

## What to check by hand

- **Keyboard only.** From the main window with no mouse: can you reach the
  filter, the group pills, a row's Run, the output? Enter submits a dialog,
  Esc closes it, Space toggles. Arrow keys move between pills.
- **Hover-only actions.** Every button a row shows only under the pointer
  (Edit, Run with…, ☆) must also be in the row's right-click menu or
  reachable by keyboard. List any that aren't.
- **Visible focus.** Tab through a dialog and the main window: is the focused
  control obvious in both a light and a dark theme? The stylesheet sets
  `:focus` only on inputs; check buttons and pills.
- **Text size.** The stylesheet sets the base font in points (`10pt`), which
  overrides the Windows text-size setting. Note what a person who has "Make
  text bigger" turned on actually gets, and whether the layout survives a
  larger base (the rows elide and scroll; dialogs may clip).
- **Motion.** Anything that moves (the scrolling name label) should be
  optional or brief.
- **Screen reader.** Without testing on NVDA or Narrator, you can still read
  the accessible names the audit reports and say what would be announced.

## Output for this lens

Findings tagged `[a11y]` with the criterion number ("2.5.8 Target size").
Severity: a control that can't be used at all by keyboard or has no name is
High; a small target or a weak contrast in one theme is Medium; polish is Low.
Add the contrast table from the audit when any pair fails.
