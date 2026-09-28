---
name: review-ryos-ui
description: Review and improve the RYOS desktop app's UI and UX. Use this whenever the user wants a design/usability review of RYOS, mentions the app "looks off," wants feedback on layout, spacing, colors, contrast, visual hierarchy, affordances, empty states, or accessibility — or asks to polish, clean up, modernize, or improve the look and feel of any RYOS screen (script cards, pipeline cards, tabs, dialogs, the output panel, the Quick Run bar, status bar, headers). Trigger even when the user doesn't say the words "UI" or "UX" but is clearly asking whether a screen is good, what to fix, or to make it nicer. Produces a prioritized findings report and then concrete edits to ryos/qtui/* (and the rule modules they draw). Do NOT use it to add a feature or change behavior (use add-ryos-feature), to fix a functional bug or crash (use fix-ryos-bug), or to just launch the app (use run-ryos).
---

# Reviewing & improving RYOS UI/UX

RYOS is a Qt (PySide6) desktop app for running user scripts. Its interface lives in `ryos/qtui/`, drawing rules kept in top-level modules (`cardstyle.py`, `cardmenu.py`, `sections.py`, ...). A good review of this app combines two things that neither alone gives you: **what the app actually looks like when running** (screenshots) and **why it looks that way** (the source). You will gather both, judge against the heuristics below, then propose fixes that respect the app's existing design language instead of importing generic web-design advice that doesn't fit a native desktop tool.

## Where the UI lives

| Concern | File |
|---|---|
| Main window, menus, tabs, search, select mode, output panel, layout | `ryos/qtui/shell.py` |
| Group sections, All tab | `ryos/qtui/sections.py` (rules: `ryos/sections.py`) |
| Script cards & pipeline cards (the main content) | `ryos/qtui/cards.py` (rules: `ryos/cardstyle.py`) |
| Script dialog | `ryos/qtui/scriptdialog.py` |
| Options (generated), small dialogs | `ryos/qtui/dialogs.py`, `ryos/qtui/smalldialogs.py` |
| Pipeline editor | `ryos/qtui/pipeline.py` |
| Appearance, theme editor | `ryos/qtui/appearance.py`, `ryos/qtui/theme_editor.py` |
| Running list, Quick Run bar, tray | `ryos/qtui/running.py`, `ryos/qtui/quickrun.py`, `ryos/qtui/tray.py` |
| **Stylesheet (every colour, font and spacing rule)** | `ryos/qtui/stylesheet.py` |
| Palettes, themes, contrast helpers | `ryos/themes.py` |

**The palette is the design-token source of truth**, and `stylesheet.py` is where it becomes Qt styling. Before recommending any colour change, refer to palette keys by name (e.g. `c['accent']`, `c['btn_run_bg']`). Never hard-code a hex value when a key exists or should exist. Text colours go through `drawn_colors()` so they stay legible on their fill in every theme — `TestQtStylesheet` checks every drawn pair across all shipped themes, so a change that fails it is a real contrast problem. Typography is Segoe UI, set once in the stylesheet. The design system (`design-system/project/`) documents tokens and intent; its component notes predate the Qt interface and are due for revision.

## The review workflow

### 1. See the app running

You cannot review look-and-feel from source alone — spacing, contrast, alignment, and crowding only reveal themselves on screen. Use the **`run-ryos` skill** (`.claude/skills/run-ryos/`), which launches the app and captures screenshots via its driver. From the project root:

```
uv run python .claude/skills/run-ryos/driver.py <scenario ...> [--theme ID]
```

Screenshots land in `.claude/skills/run-ryos/screenshots/`. Read them with the `Read` tool. Scenarios: `main`, `compact`, `output`, `quick-run`, `dialogs`, `themes` (all themes on one sheet), `all`. Nothing is shown on any monitor — windows render off screen — and the data is a throwaway copy of the repo's `samples/`.

Capture whatever states are relevant to the review's scope. If the user points at a specific screen (e.g. "the settings dialog" or "pipeline cards"), prioritise that. If the review is general, cover the main states: **idle window**, a **finished and a failed run** with the **output panel**, **compact mode**, the **dialogs**, and more than one **theme** (a light and a dark one at least). If no scenario reaches the state you need, add one — see the run-ryos SKILL.md for the pattern and the window's hooks.

### 2. Read the relevant source

For each screen under review, read the file(s) that build it. You're looking for the *structural causes* of what you see: padding/`pady`/`padx` values, `pack`/`grid` choices, font sizes, colour tokens, hover bindings, disabled states, hardcoded widths. A finding is only actionable if you can point to the line that produces it.

### 3. Judge against the heuristics

Read `references/ui-ux-heuristics.md` and evaluate each screen against it. The heuristics are tuned to RYOS — a single-window, keyboard-and-mouse, local desktop tool — not a mobile app or a website. Don't apply web conventions (hamburger menus, infinite scroll, mobile breakpoints) that don't belong here.

### 4. Write the report

Use the template in `assets/report-template.md`. The core of a useful report is **prioritised, located, justified** findings:

- **Severity** — `High` (hurts usability or looks broken), `Medium` (noticeable friction or inconsistency), `Low` (polish).
- **Location** — the screen and the exact `file:line` (or token name) responsible.
- **What & why** — what's wrong and *why it matters to the user*, not just "this violates a rule."
- **Recommendation** — a concrete, RYOS-appropriate fix.

Order findings by severity. Lead with a 2–3 sentence summary of the overall impression so the user gets the gist before the details. Reference screenshots by filename so the user can look at exactly what you saw.

Save the report to `.claude/discarded/` as a markdown file (e.g. `ui-review-YYYY-MM-DD.md`). This folder is gitignored — review files are working documents, not project artefacts.

### 5. Propose the edits

After the report, turn the High and Medium findings into concrete code changes. Prefer **small, surgical diffs** that respect the existing patterns:

- Route colours through palette keys in `stylesheet.py` (text colours through `drawn_colors()`). If a fix needs a new colour, add a palette key in `themes.py` so every theme defines it, then reference it.
- Style by object name in the stylesheet (`QPushButton#primary`, `QFrame#card`) rather than per-widget `setStyleSheet`, except where a card's colour depends on its own state (the Run button).
- Put a rule that decides *what* shows (a label, a badge, a count) in the rule module (`cardstyle.py`, `sections.py`, ...) with a unit test, and let the Qt code draw it.
- Preserve behaviour: the worker-thread/queue output model is load-bearing (see `CLAUDE.md`). A visual change must not touch a widget from a worker thread.
- Show the edits as a clear before/after, grouped by file. Don't bundle unrelated refactors into a UI pass.
- Run `tests/qt_smoke.py` after a change: several checks there are about looks (long text fits at 540 px, ticks are drawn, gaps read as gaps).

After editing, **re-run the relevant `run-ryos` scenario and screenshot again** to verify the change actually looks better and didn't break the layout. Reading the new screenshot is the verification step — don't claim an improvement you haven't looked at.

## Tone

Be a candid, constructive design reviewer. The goal is a better app, so don't pad findings with false praise, but do note what already works well — consistency and clear patterns are worth preserving, and the user needs to know what *not* to touch. Explain the reasoning behind each recommendation so the user can make their own call rather than following orders blindly.
