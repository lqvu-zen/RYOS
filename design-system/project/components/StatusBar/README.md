# StatusBar

The strip along the bottom of the window. Qt's `QStatusBar`, styled with
`status_bg` and `status_fg`.

## Anatomy

On the left, what just happened, briefly: `Ready`, `Done.`, `Failed.`,
`Stopped.`, `Pipeline complete.`. Maximised, a summary on the right from
`ryos/activity.py` `summary()`: `1 running  ·  next: Morning report,
Tomorrow 08:00`.

At the very end, the **bug** icon: a quiet 24px button that opens a new GitHub
issue filled in with the versions, theme and layout (`ryos/bugreport.py`) --
nothing is sent until the person submits it. Also Help → Report a bug….

## Rules

- A report, not a log: one short line, replaced by the next.
- Text in `status_fg`, which is `path_fg` shaded to read on `status_bg`.
