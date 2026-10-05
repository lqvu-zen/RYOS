# QuickRunBar

Run any file under a group's folder without adding it: type part of a name,
pick, Run. `ryos/qtui/quickrun.py`; the index in `ryos/quickrun_index.py`.

## Anatomy

Opened from **⚡ Quick Run** (a link on the group's folder line): a field, a
filled **Run** -- the one primary of its area -- and a close icon; the matches
listed under it with their folders muted.

## Rules

- It searches the group's base folder; a group without one has no Quick Run.
- Enter runs the highlighted match (or what was typed); Esc closes the
  list of matches first, then the bar.
