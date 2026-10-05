# OutcomeWord

How a run went, as a coloured word: `● OK`, `● Failed`, `● Stopped`, and while
it lasts `● Running` / `● Retrying`. `ryos/cardstyle.py` `status_badge()`.

## Colours

Each is its palette colour shaded to read on the row (`cards._ink`): the
`ink-ok`, `ink-error`, `ink-path_fg` (Stopped, muted), `ink-running` and
`ink-warn_fg` tokens. 9pt semibold.

## Rules

- A word, never colour alone and never a filled chip.
- Stopped is the user's doing, not a failure: muted, and Run stays Run.
- Where only a dot fits (a favourite chip) the words go in its tooltip and
  accessible name.
