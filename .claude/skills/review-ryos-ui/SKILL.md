---
name: review-ryos-ui
description: Review and improve the RYOS desktop app's UI and UX. Use this whenever the user wants a design/usability review of RYOS, mentions the app "looks off," wants feedback on layout, spacing, colors, contrast, visual hierarchy, affordances, empty states, wording, keyboard use or accessibility — or asks to polish, clean up, modernize, or improve the look and feel of any RYOS screen (rows, pipeline rows, favourites, group pills, dialogs, the output panel, the maximised detail pane, the Quick Run bar, headers). Also use it for an accessibility audit (WCAG, keyboard, focus order, screen-reader names), a UX-copy pass (button labels, error messages, empty states, confirmations), an interaction review (hover/disabled/busy states, preventing mistakes on destructive actions) or a design critique of RYOS screenshots. Trigger even when the user doesn't say "UI" or "UX" but is clearly asking whether a screen is good, what to fix, or to make it nicer. Produces a measured audit, a prioritised findings report across five lenses, and concrete edits to ryos/qtui/* and the rule modules they draw. Do NOT use it to add a feature or change behavior (use add-ryos-feature), to fix a functional bug or crash (use fix-ryos-bug), or to just launch the app (use run-ryos).
---

# Reviewing & improving RYOS UI/UX

RYOS is a Qt (PySide6) desktop app for running one's own scripts. Its
interface lives in `ryos/qtui/`, drawing rules kept in top-level modules
(`cardstyle.py`, `cardmenu.py`, `sections.py`, `detail.py`, ...). A good review
combines three things none gives alone: **what the app looks like running**
(screenshots), **what can be measured** (the audit), and **why it is that way**
(the source). Judge them through five lenses, then fix what matters in the
app's own design language -- not generic web advice.

## Where the UI lives

| Concern | File |
| --- | --- |
| Main window, header, menus, pills, search, select mode, output panel, maximised layout | `ryos/qtui/shell.py` |
| Maximised detail pane | `ryos/qtui/detail.py` (rules: `ryos/detail.py`) |
| Sections, favourites strip, All tab | `ryos/qtui/sections.py`, `ryos/qtui/dragdrop.py` (rules: `ryos/sections.py`) |
| Rows (script and pipeline cards), chips | `ryos/qtui/cards.py` (rules: `ryos/cardstyle.py`) |
| Script dialog | `ryos/qtui/scriptdialog.py` |
| Options (generated), small dialogs | `ryos/qtui/dialogs.py`, `ryos/qtui/smalldialogs.py` |
| Pipeline editor | `ryos/qtui/pipeline.py` |
| Appearance, theme editor | `ryos/qtui/appearance.py`, `ryos/qtui/theme_editor.py` |
| Running list, Quick Run bar, tray | `ryos/qtui/running.py`, `ryos/qtui/quickrun.py`, `ryos/qtui/tray.py` |
| **Stylesheet (every colour, font and spacing rule)** | `ryos/qtui/stylesheet.py` |
| Palettes, themes, contrast helpers | `ryos/themes.py` |

**The palette is the design-token source of truth**, and `stylesheet.py` is
where it becomes Qt styling. Refer to palette keys by name (`c['accent']`,
`c['btn_run_bg']`); never hard-code a hex. Text colours go through
`drawn_colors()` so they stay legible in every theme -- `DRAWN_PAIRS` is
checked across all shipped themes by the unit suite.

## The five lenses

Each lens has a reference file. They are adapted from general design skills
(named in each file) and rewritten for a Qt desktop tool, so this skill works
without those plugins installed.

| Lens | Tag | Reference | Asks |
| --- | --- | --- | --- |
| Critique | `[critique]` | `references/critique.md` | Where does the eye land? Can people do the main tasks in few steps? |
| Accessibility | `[a11y]` | `references/accessibility.md` | WCAG 2.2 AA in Qt terms: contrast, keyboard, focus, names, targets, colour alone |
| Copy | `[copy]` | `references/copy.md` | Do buttons, messages, empty states and confirmations say the right thing? |
| Interaction | `[interaction]` | `references/interaction.md` | Are all states there (hover, disabled, busy, failed)? Are mistakes prevented? |
| Design system | `[system]` | `references/design-system.md` | Tokens, type scale, component states, drift |

`references/ui-ux-heuristics.md` describes RYOS's own design language and
what not to break. Read it first on every review; it is what makes a finding
fit this app.

**Scope.** A general review runs all five. When the user asks for one thing
("check accessibility", "review the wording", "is the delete flow safe?"),
run that lens -- plus the audit, which is cheap -- and say which you ran.

## The workflow

### 1. See the app running

Use the **run-ryos** skill's driver (renders off screen; nothing appears on
any monitor; throwaway copy of `samples/`):

```
uv run python .claude/skills/run-ryos/driver.py <scenario ...> [--theme ID]
```

Scenarios: `main`, `compact`, `output`, `workspace` (maximised), `quick-run`,
`dialogs`, `themes` (every theme on one sheet), `all`. Screenshots land in
`.claude/skills/run-ryos/screenshots/`; read them with `Read`. For a general
review capture at least `main`, `output`, `compact`, `workspace` and `dialogs`
in a light and a dark theme. If no scenario reaches a state you need (hover,
running, select mode, an error), add one -- see the run-ryos SKILL.md.

### 2. Measure

```
uv run python .claude/skills/review-ryos-ui/scripts/audit.py [--theme light dark]
```

It walks every screen and dialog and writes
`.claude/discarded/ui-audit-<date>.md`: targets under 24 px, buttons with no
accessible name, inputs with no linked label, keyboard reach, hover-only
controls, clipped text, default buttons, tab order, key contrast pairs in every
theme, hard-coded colours, font sizes, and deuteranopia simulations of the
main screens (`*_deutan.png`). Treat each line as a lead: confirm it in a
screenshot or the source before it becomes a finding, and say why when you
decide one is fine for RYOS.

### 3. Read the relevant source

For each screen, read the files that build it. A finding is actionable only
when you can point at the line, rule or palette key that produces it.

### 4. Judge through the lenses

Read `references/ui-ux-heuristics.md`, then each lens file in scope, and go
through the screenshots, the audit and the source with each. Start with the
critique's two-second look, before the details colour your eye.

**Deeper dives (optional).** If the plugin skills are installed and the user
wants more on one angle, you may also invoke `design:design-critique`,
`design:accessibility-review`, `design:ux-copy` or `design:design-system` on
the screenshots. Translate their output into RYOS terms (palette keys, Qt
calls, rule modules) before it goes in the report -- their templates assume
Figma and the web.

### 5. Write the report

Use `assets/report-template.md`. The core is **prioritised, located,
justified** findings, each tagged with its lens:

- **Severity** -- `High` (blocks someone or looks broken), `Medium`
  (noticeable friction or inconsistency), `Low` (polish).
- **Location** -- screen and `file:line`, palette key or rule module.
- **What & why** -- why it matters to the person using the app.
- **Recommendation** -- a concrete, RYOS-appropriate fix.
- **Evidence** -- the screenshot, the audit line or the measured ratio.

Lead with a 2–3 sentence summary and the first-look table; fill the audit's
"Before" column. Include the copy table when the copy lens ran, and a "what
already works" list. Save to `.claude/discarded/ui-review-YYYY-MM-DD.md`
(gitignored: working documents, not project artefacts).

### 6. Make the edits

Turn the High and Medium findings into small, surgical changes that respect
the existing patterns:

- Colours through palette keys in `stylesheet.py` (text through
  `drawn_colors()`, with a `DRAWN_PAIRS` entry). A new colour role is a new
  palette key in `themes.py`, so every theme defines it.
- Style by object name in the stylesheet (`QPushButton#primary`,
  `QFrame#card`), not per-widget `setStyleSheet` -- except where a widget's
  colour depends on its own state (Run/Retry).
- Accessible names with `setAccessibleName`; labels linked with `setBuddy`;
  tab order with `setTabOrder`.
- Wording and "what shows" rules in the rule module, with its unit test
  updated; the Qt code only draws.
- Preserve behaviour: the worker-thread/queue output model is load-bearing
  (see `CLAUDE.md`). The detail pane acts through the chosen row's buttons.
- Show edits as before/after grouped by file; no unrelated refactors.

### 7. Verify

Re-run the scenarios and the audit, **read the new screenshots**, and fill the
report's "After" column -- don't claim an improvement you haven't looked at or
measured. Then run the gate: `uv run --no-project --with pytest pytest -q`,
`tests/qt_smoke.py` (offscreen: `QT_QPA_PLATFORM=offscreen`), `uvx ruff check .`.
Several `qt_smoke` checks are about looks (text fits at 540 px, Run doesn't
move on hover, chips are round, ticks are drawn).

## Tone

A candid, constructive design reviewer. Don't pad findings with praise, but
name what works -- consistency is worth preserving and the user needs to know
what not to touch. Explain the reasoning behind each recommendation so the
user can make their own call.
