# FormControls

Fields in dialogs: text, drop-downs, spin boxes, check boxes.
`ryos/qtui/stylesheet.py`; the dialogs in `scriptdialog.py`, `dialogs.py`,
`smalldialogs.py`.

## Anatomy

`card_bg`, a 1px `border` (`accent` when focused), `radius-control`, 4px 6px
padding. Drop-downs and spin boxes carry a thin drawn chevron, not Qt's boxed
arrows. A check box is a 16px rounded square, `accent` with the drawn tick
when on.

## Rules

- Every field has a label linked to it (`setBuddy` or a form row).
- A dialog's labels and fields align in two columns; its buttons sit
  bottom-right with the default rightmost.
- A dialog that refuses a value (a missing file, a schedule with no days)
  says what to fix.
