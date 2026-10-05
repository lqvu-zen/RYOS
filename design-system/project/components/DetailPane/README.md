# DetailPane

The chosen item in full, beside the list when the window is maximised.
`ryos/qtui/detail.py`; what it says is `ryos/detail.py`.

## Anatomy

- **Head** -- a 3px rail, the KindTag, the name in `display`, and under it the
  subtitle (`2 steps · last run today 03:00, OK`); the star, **Edit** and ⋯ on
  the right.
- **Actions** -- Run (or Retry), 38px tall and round-ended, then the links
  **Run with…** (scripts) and **Schedule…**.
- **Tabs** -- PillTabs: **Overview · Output · History**.
- **Overview** -- a script's PresetPills, or a pipeline's StepCards; a few
  facts; and the **last-run box**: how it went, when, how long, the exit code
  of a failure, with **Open output** while that run's output tab is still open,
  **History** otherwise.
- **Output** -- the window's output panel, lent while maximised.
- **History** -- the item's runs, newest first, with Clear history….

## Rules

- Every button acts through the chosen row's own (Run presses its Run), so the
  two cannot drift.
- The last run is said once in the head and once in the box, in the same day
  words ("Today 03:00", "Fri 18:30").
- Running the item you are looking at switches to Output; a schedule firing
  for something else does not move the pane.
