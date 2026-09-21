# Accessibility

Contrast is enforced in code here, not left to reviewers. Three mechanisms do
the work, and one list records where the shipped palettes still miss.

`python design-system/build.py --audit` prints the live table this page
summarises, so the numbers below can be re-checked at any commit.

## The mechanisms

**`contrast_ratio(c1, c2)`** — WCAG 2 relative luminance, in
`ryos/themes.py`. Pure and unit-tested; use it rather than eyeballing.

**`highlight_fg(key, *surfaces)`** — the interesting one. A user can tint a
card's name one of seven colours. Those seven are *seeds*, not final colours:
`_readable_on()` shades the seed in 8% steps — lighter on a dark surface,
darker on a light one — until it clears 4.5:1 on **every** surface it will be
drawn against, which for a card means `card_bg` *and* `card_hover`, so the name
stays legible while the pointer is over it. The loop is capped at 30 steps and
returns its last value regardless, so a pathological theme degrades instead of
failing. Results are cached on `(seed, surfaces)`, and because the surfaces are
part of the key, a theme switch never serves a stale colour.

The consequence for anyone extending this system: **one set of seven seeds
serves all thirteen themes.** Don't hand-tune a highlight per theme — pass the
surfaces it will actually land on. The right-click menu does exactly this,
resolving its swatches against `menu_bg` rather than `card_bg`.

**`contrast_warnings(seed)`** — soft warnings in the theme editor when a seed's
`text` falls under 4.5:1 on `bg` or `surface`, or `text_muted` under 3:1 on
`bg`. Non-fatal by design: a user's theme is theirs.

## Which floor applies

WCAG 2 asks 4.5:1 of body text, and 3:1 of text at 24px+ (or bold 19px+) and of
non-text marks that carry meaning. **Nothing in RYOS is large text** — the
biggest type in the app is the 19px wordmark, which is under the bold-19px
threshold. So every text pair below is judged at 4.5:1, and the only 3:1 rows
are marks: the 5px card rail and the 3px tab indicator, which clear it on all
eight themes (3.42:1 at worst, on Ocean Depths).

## Where the shipped palettes miss

Eight distinct pairs, 35 cells across the eight themes. These are the source's
real values and they stay exact — the note is the deliverable, not a re-tint.

| Pair | Worst | Fails on | What to do |
|---|---|---|---|
| `btn_fg` on `btn_run_bg` | **2.10:1** | all 8 | Worst in the system: white on `#2ecc71`, under even the 3:1 mark floor. It is the `▶` on every Run button and the `▶ Run Selected` label. A darker green, or `name_fg` on the green, fixes it without touching the brand. |
| `fg_on_dark` on `ok` | **2.10:1** | all 8 | The same green under the `✓ OK` badge. The `✓` carries the meaning independently of the word, which is the only reason this is survivable. |
| `fg_on_dark` on `accent` | **2.00:1** (Nord) | dark, nord, solarized-dark, ocean-depths, high-contrast | These themes lighten the accent for a dark ground and then keep white on it. They want *dark* text on the accent — an `on-accent` token is the correct fix, rather than darkening the accent itself. |
| `fg_on_dark` on `pipe_accent` | **4.20:1** | dark, nord, solarized-dark, ocean-depths, high-contrast | The `🕒 SCHEDULED` badge. A near miss, and the same shape of problem as `on-accent`. The 5px pipeline rail that shares this colour is a mark, and clears 3:1 comfortably. |
| `btn_fg` on `error` | **3.63:1** | the 5 dark themes | The `✕ Failed` badge and the `↻` retry glyph. Passes 3:1 for the glyph, misses 4.5:1 for the 8pt bold word. |
| `btn_neutral_fg` on `btn_neutral_bg` | **3.26:1** (Solarized Dark) | nord, solarized-dark | Card gutter glyphs: reorder, history, star. Both values are *derived*, so the fix belongs in the `_shade` factors, not in either seed. |
| `name_fg` on `card_hover` | **3.63:1** (Solarized Dark) | solarized-dark | Card names under the pointer. Solarized's `text` is `#93a1a1`, already low on `card_bg` at 4.86:1; the +10% hover shade pushes it under. |
| `path_fg` on `card_bg` | **4.11:1** (Solarized Dark) | solarized-dark | Script paths and last-run timestamps. Solarized Dark is the one theme whose muted text misses; every other theme is 4.68:1 or better. |

Solarized Dark accounts for four of the eight on its own: its palette is built
for a terminal, where the whole point is low-contrast foreground text, and
porting it faithfully means porting that.

Everything else clears its floor in every theme, including all seven highlight
colours by construction, `warn_fg` on `warn_bg` (7.0–8.4:1), the whole output
panel (6.0–11.3:1), and `fg_on_dark` on `header_bg` (9.9–21:1).

## If you add a theme

Run the seed through `validate_seed()` and `contrast_warnings()` before
shipping it, then `python design-system/build.py --audit` to see it in the
table. Check `name_fg` against `card_hover` as well as `card_bg` — that derived
hover is where light-on-dark themes fail first.

## Colour is never the only signal

Every state in the system carries a glyph or a word alongside its colour: `✓ OK`
and `✕ Failed`, `▶` versus `↻`, `★` versus `☆`, the SCHEDULED and TEMP PARAM
badges, the `Python`/`Shell`/`PowerShell` type badges. Keep that rule when you
add a state — the seven card highlights are decorative precisely because
nothing depends on telling them apart.
