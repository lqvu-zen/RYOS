# StepCard

One step of a pipeline, in its Overview. `ryos/qtui/detail.py`
`_step_card`; what it says is `ryos/detail.py` `step_cards()`.

## Anatomy

196 × 118, `card_bg`, a 1px `border`, `radius-card`. `STEP n` in `caption`,
the script's name in `title`, its file in `muted_fg`, its last outcome as an
OutcomeWord, and on a line of its own anything set differently from the
default: its own parameters, `keeps going`, `3 retries`, `only if something
has failed`, `launcher`.

## Rules

- Cards wrap. An arrow leads into each step after the first; a `+` into one
  that starts with the step before. The mark travels with its card, so a
  wrapped line starts `→ step` and never ends in an arrow to nothing.
- Only deviations are noted -- an ordinary step's card has no note line.
- The outcome is live: a step that is running says so.
