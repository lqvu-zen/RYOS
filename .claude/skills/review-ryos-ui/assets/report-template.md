# RYOS UI/UX Review — <scope> (<date>)

## Summary

<2–3 sentences: overall impression, what works, the single most important thing to fix.>

**Screens reviewed:** <list> · **Themes:** <at least one light, one dark> ·
**Screenshots:** <filenames in run-ryos/screenshots/> · **Audit:** `.claude/discarded/ui-audit-<date>.md`

## First look

| Screen | Eye lands on | Should be | Purpose clear? |
| --- | --- | --- | --- |
| <screen> | <element> | <element> | <yes / no — why> |

## Audit at a glance

| Check | Before | After |
| --- | --- | --- |
| Targets under 24 px | <n> | <n> |
| Buttons with no name | <n> | <n> |
| Inputs with no linked label | <n> | <n> |
| Tab can't reach | <n> | <n> |
| Hover-only controls without another way in | <n> | <n> |
| Key colour pairs under minimum | <n> | <n> |
| Hard-coded colours / font sizes | <n> / <n> | <n> / <n> |

## Findings

Each finding carries its lens: `[critique]`, `[a11y]` (with the WCAG
criterion), `[copy]`, `[interaction]` or `[system]`.

### High

> Hurts usability, blocks someone, or looks broken.

#### H1. <short title> `[lens]`

- **Screen / location:** <screen> — `ryos/qtui/<file>.py:<line>` (or palette key `c['...']`, or rule module)
- **What & why:** <what's wrong and why it matters to the person using it>
- **Recommendation:** <concrete, RYOS-appropriate fix>
- **Evidence:** <screenshot filename, audit line, or measured ratio>

### Medium

> Noticeable friction or inconsistency.

#### M1. <short title> `[lens]`

- **Screen / location:** ...
- **What & why:** ...
- **Recommendation:** ...

### Low

> Polish.

#### L1. <short title> `[lens]`

- **Screen / location:** ...
- **What & why:** ...
- **Recommendation:** ...

## Copy changes

| Where | Now | Proposed | Why |
| --- | --- | --- | --- |
| `ryos/<module>.py` <NAME> | "<current>" | "<proposed>" | <reason> |

## What already works well

<Patterns worth preserving, named specifically, so the next pass doesn't undo them.>

## Proposed edits

<Per file, grouped. For each: the file, a before/after, and one line on the
expected effect. Verify by re-running the run-ryos scenario and the audit,
reading the new screenshots, and filling in the "After" column above.>
