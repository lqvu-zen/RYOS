# OutputPanel

Every run's output, in a terminal of its own. `ryos/qtui/shell.py`
`OutputPane` and `_build_output`; routing in `ryos/outputpanel.py`.

## Anatomy

A header (**Output**, Show/Hide output, Clear, Close all, in
`tab_selected_fg` words with icons), a find row (**Find**, matches, **Errors
only**), the run tabs as small pills, then the terminal: `out_bg`, Consolas,
`out_stdout`, `out_stderr` in red, `out_status` for step headers,
`out_success` for exit lines.

## Rules

- The terminal keeps its own dark world on light themes too; don't tint it to
  the chrome.
- Maximised, the panel lives in the detail pane's Output tab, always open --
  its title and hide toggle go.
- A pipeline's tab carries the bolt; a parallel step's lines carry a coloured
  prefix chip (`step_fg`, `step_ok_fg`, `step_fail_fg`).
