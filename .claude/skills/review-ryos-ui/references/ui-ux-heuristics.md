# RYOS: what good looks like here

The design language the app has settled on, and the rules that keep it
consistent. Judge a screen against this first: it is what makes a finding
RYOS-appropriate rather than generic. The lens files (`critique.md`,
`accessibility.md`, `copy.md`, `design-system.md`) go deeper on one angle each.

RYOS is a single-window, mouse-and-keyboard desktop tool for running one's own
scripts. People open it, find a script, press Run, watch the output, go back to
work. Most visits are seconds long. Everything below serves that loop.

## The design language

| Element | How it is drawn | Where |
| --- | --- | --- |
| Header bar | Theme's `header_bg`; bolt, name, the File/Options/Help menus, `+ Pipeline` `+ Group` (words) and `+ Script` (filled accent: the window's one primary button) | `shell.py` `_build_header`; `#appHeader` |
| Group tabs | Pills: chosen = `name_fg` filled with `pill_fg` ink; others muted words; a dashed round `+` between the groups and All | `GroupTabBar`; `QTabBar#groupTabBar` |
| Sections | One panel per section (`#sectionPanel`, `card_bg`, 1 px `border`, 4 px radius); rows split by hairlines; small ▾/▸ fold arrow and a capitalised label | `qtui/sections.py`, `ryos/sections.py` |
| Rows (cards) | 3 px left rail (`accent`, pipelines `pipe_accent`); line 1: kind word, name, outcome; line 2: path or steps, and the preset as a small chip. At rest only Run (and a favourite's gold star) show; ✎, run-with and ☆ appear under the pointer in space kept for them | `qtui/cards.py`, rules `cardstyle.py` |
| Compact rows | One line: star, name, kind, outcome, Run | same |
| Favourites | A wrapping strip of pills: name, outcome dot, small Run | `CardList(flow=True)`, `QFrame#card[chip="true"]` |
| Run | A green circle (`btn_run_bg`), ↻ on red (`error`) after a failure. The only filled thing on a row | `cardstyle.run_button()` |
| Words for state | Kind, badges and outcome are coloured words ("● OK", "● Failed"), never filled chips | `_tag`, `_status_chip` |
| Maximised | List on the left (compact rows), the chosen item on the right: name, Run/Retry, Run with…, Schedule…, Run history, preset chips, steps, facts, output | `qtui/detail.py`, rules `ryos/detail.py` |
| Output | Dark terminal (`out_*` keys) under the list, or under the detail when maximised; a small pill tab per run | `shell.py` `OutputPane` |

**Principles** (from `design-system/project/README.md`): flat, near-square,
hairlined; one filled action per area; colour from the palette only; words
before chips; quiet until needed.

## Heuristics

### 1. Hierarchy: one thing to press

- Each area has one filled, prominent control: + Script in the header, Run on
  a row, Run/Retry in the detail pane, Save (`QPushButton:default`) in a
  dialog. A second filled button competing with it is a finding.
- On a row the name dominates; kind, path and preset are supporting
  (`path_fg`, smaller). The outcome word may be coloured but not larger.
- The chosen group pill must be unmistakable from across the desk.

### 2. Quiet until needed

- Secondary actions wait for the pointer (rows) or live in the right-click
  menu. Adding an always-visible control to a row needs a reason.
- **But hover is an enhancement, never the only way in**: every hover-only
  action must also be in the right-click menu (`cardmenu.py`) or reachable by
  keyboard. The audit lists hover-only controls; check each has a twin.

### 3. Spacing and alignment

- Rows in a panel share one padding table (`cardstyle.CARD_PADDING`); Run
  sits at the same x on every row, script or pipeline (`qt_smoke` checks).
- Button columns line up across script and pipeline rows (the spacer cell).
- Dialog labels and fields align in columns; buttons sit bottom-right with
  the primary rightmost.

### 4. Colour and state

- Semantic colour is consistent: green = run/OK, red = failed/stop, accent =
  interactive, `pipe_accent` = pipeline, amber `warn_*` = select mode.
- Every colour comes from a palette key; text colours go through
  `drawn_colors()`/`_readable_on` so they read in every theme.
- Colour is never alone: OK/Failed carry a word, Retry a different glyph.
  A dot with no word (the favourite chip) needs a tooltip and a second cue.

### 5. Feedback

- A run must visibly start (Running list, the row's state, output) and end
  (outcome word, Retry, status bar). Silence is a bug.
- Destructive actions (delete, Delete All) confirm, name what goes, and use
  `menu_danger` in menus.

### 6. Empty and edge states

- Empty sections and groups say what goes there and how to add it
  (`sections.EMPTY`, `ALL_EMPTY`).
- Long names scroll (`ScrollingLabel`) or elide (`ElidedLabel`) -- nothing
  pushes Run off the edge at the 480 px minimum (`qt_smoke` checks 540).
- Many groups: the pill row scrolls; the + stays with the groups.

### 7. Layout

- Normal and compact fit 480 px wide. Maximised switches to list + detail.
- Dialogs are sized to their content and open over the window.

### 8. Keyboard and accessibility

- See `accessibility.md`. In short: everything reachable by Tab, Enter
  submits, Esc cancels, focus visible, targets at least 24 px, controls named.

### 9. Copy

- See `copy.md`. In short: verbs on buttons, sentence case, the same word for
  the same thing everywhere, errors that say what to do next.

## What's load-bearing -- don't break it

Per `CLAUDE.md`: output flows worker thread → `Queue` → a `QTimer` on the UI
thread; never touch a widget off-thread. Running processes live in
`Job.processes`, stopped through `job.active_processes()`. The window's real
effects (settings, toasts, update check, quitting) are injected -- a UI change
must not reach for them directly. The detail pane acts only through the chosen
row's own buttons; keep it that way so the two cannot drift.
