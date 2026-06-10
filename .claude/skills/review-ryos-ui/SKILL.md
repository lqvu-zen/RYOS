---
name: review-ryos-ui
description: Review and improve the RYOS desktop app's UI and UX. Use this whenever the user wants a design/usability review of RYOS, mentions the app "looks off," wants feedback on layout, spacing, colors, contrast, visual hierarchy, affordances, empty states, or accessibility — or asks to polish, clean up, modernize, or improve the look and feel of any RYOS screen (script cards, pipeline cards, tabs, dialogs, the output panel, the Quick Run bar, status bar, headers). Trigger even when the user doesn't say the words "UI" or "UX" but is clearly asking whether a screen is good, what to fix, or to make it nicer. Produces a prioritized findings report and then concrete edits to ryos/ui/*. Do NOT use it to add a feature or change behavior (use add-ryos-feature), to fix a functional bug or crash (use fix-ryos-bug), or to just launch the app (use run-ryos).
---

# Reviewing & improving RYOS UI/UX

RYOS is a Tkinter desktop app for running user scripts. Its entire interface lives in `ryos/ui/`. A good review of this app combines two things that neither alone gives you: **what the app actually looks like when running** (screenshots) and **why it looks that way** (the source). You will gather both, judge against the heuristics below, then propose fixes that respect the app's existing design language instead of importing generic web-design advice that doesn't fit a native desktop tool.

## Where the UI lives

| Concern | File |
|---|---|
| Main window, header, tabs, group sections, running rows, layout | `ryos/ui/app.py` |
| Script cards & pipeline cards (the main content) | `ryos/ui/cards.py` |
| All dialogs (add/edit script, settings, group base dir, etc.) | `ryos/ui/dialogs.py` |
| Pipeline editor | `ryos/ui/pipeline.py` |
| **Color palette + button factory + window snap** | `ryos/ui/theme.py` |
| Tooltip, scrolling label | `ryos/ui/widgets.py` |

**`theme.py` is the design-token source of truth.** Every colour in the app comes from the `C` dict there. Before recommending any colour change, read `theme.py` and refer to tokens by name (e.g. `C["accent"]`, `C["btn_run_bg"]`). Never hard-code a hex value into a widget when a token exists or should exist — if a new colour is genuinely needed, add it to `C` so the palette stays the single source of truth. The same goes for fonts: the app uses `("Segoe UI", ...)` throughout, so keep typography consistent with that.

## The review workflow

### 1. See the app running

You cannot review look-and-feel from source alone — spacing, contrast, alignment, and crowding only reveal themselves on screen. Use the **`run-ryos` skill** (`.claude/skills/run-ryos/`), which launches the app and captures screenshots via its driver. From the project root:

```
uv run --with pillow python .claude/skills/run-ryos/driver.py <scenario>
```

Screenshots land in `.claude/skills/run-ryos/screenshots/`. Read them with the `Read` tool. Existing scenarios: `smoke`, `quick-run-bar`, `run-first`, `autocomplete`, `adhoc-run`, `close-all-verify`, `debug-run-py`, `running-row-check`.

Capture whatever states are relevant to the review's scope. If the user points at a specific screen (e.g. "the settings dialog" or "pipeline cards"), prioritise that. If the review is general, cover the main states: **idle window**, a **running** script, the **output panel**, and at least one **dialog**. If no existing scenario reaches the state you need, add one — copy the pattern of an existing `_scenario(app)` function in `driver.py` (schedule actions with `app.after(...)`, screenshot with `_shot(app, name)`), and add a branch in `main()`. The driver has direct access to the live app (`app._cards`, `app.db`, `card._run()`, etc.; see the run-ryos SKILL.md for the full list).

If the app genuinely can't be launched in the current environment (no display), say so plainly and fall back to a source-only review — but flag that visual issues (crowding, contrast, alignment) are harder to catch that way, and review the screenshots already sitting in the `run-ryos/screenshots/` folder if any are recent.

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

Save the report to the outputs folder (or the project root if the user prefers) as a markdown file.

### 5. Propose the edits

After the report, turn the High and Medium findings into concrete code changes. Prefer **small, surgical diffs** that respect the existing patterns:

- Route colours through `theme.py` tokens. If a fix needs a new colour, add it to `C` with a comment, then reference it.
- Keep the `_flat_button` factory and `Segoe UI` typography — extend them rather than introducing parallel styles.
- Preserve behaviour: the worker-thread/queue output model, `after()` scheduling, and `pack(after=banner)` ordering are load-bearing (see `CLAUDE.md`). A visual change must not break threading or layout ordering.
- Show the edits as a clear before/after, grouped by file. Don't bundle unrelated refactors into a UI pass.

After editing, **re-run the relevant `run-ryos` scenario and screenshot again** to verify the change actually looks better and didn't break the layout. Reading the new screenshot is the verification step — don't claim an improvement you haven't looked at.

## Tone

Be a candid, constructive design reviewer. The goal is a better app, so don't pad findings with false praise, but do note what already works well — consistency and clear patterns are worth preserving, and the user needs to know what *not* to touch. Explain the reasoning behind each recommendation so the user can make their own call rather than following orders blindly.
