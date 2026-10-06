# Accessibility

Contrast is enforced in code here, not left to reviewers. A handful of
mechanisms do the work, the unit suite checks them in every shipped theme, and
one short list records where the palettes themselves still miss.

`python design-system/build.py --audit` prints the live table this page
summarises, so the numbers below can be re-checked at any commit.

## The mechanisms

**`contrast_ratio(c1, c2)`** — WCAG 2 relative luminance, in
`ryos/themes.py`. Pure and unit-tested; use it rather than eyeballing.

**`drawn_colors(palette)`** — the main one, in `ryos/qtui/stylesheet.py`.
Nearly every text and edge colour the interface paints is not a palette key
but a colour derived from one until it reads on what it sits on: paths and
hints (`muted_fg`) on a row, a hovered row, the window and the chosen row's
wash; words on the accent (`primary_fg`); the header's words (`header_fg`);
pills, badges, tooltips, the status bar, the running list, the focus outline.
Three helpers do it:

- `_readable_on(colour, surfaces)` shades a colour in 8% steps until it clears
  4.5:1 on **every** surface given — so it stays itself, only darker or lighter;
- `_legible(fg, *fills)` keeps the theme's colour when it reads, else takes the
  better of black and white;
- `_edge(colour, *surfaces, floor)` does the same for lines and outlines, at the
  floor a boundary needs (3:1 for an outline that is the only thing saying
  "button", 1.6:1 for a field's edge).

`DRAWN_PAIRS` lists each drawn colour with the fills it sits on and its floor,
and the unit suite checks every pair in every shipped theme. The design
system carries the results as tokens (`muted_fg`, `primary_fg`, `focus_edge`…),
and a preview that writes text should use those, not the raw key.

**Painted inks** — a row's coloured words go through the same shading
(`cards._ink`: `_readable_on(colour, (card_bg, card_hover))`): the outcome
words, the kind tags, the highlight colours. A fixed tag fill or highlight seed
is never painted as it is; the `ink-*`, `tag-*-ink` and `highlight-*-ink`
tokens are what actually reaches the screen.

**`readable_highlight(key, *surfaces)`** — a user can tint a row's name one of
seven colours. The seven are *seeds*: one set serves every theme, because each
is shaded against the surfaces it lands on (`card_bg` and `card_hover` on a
row, the window in the detail pane). Don't hand-tune a highlight per theme —
pass the surfaces it will actually land on.

**`disabled_pair(bg, fg, surface)`** — the same idea aimed the other way. A
disabled control is deflated 45% toward its surface and its words mixed toward
that slab until they drop to `DISABLED_TARGET`, 2.6:1: clearly dimmed, still
readable. WCAG exempts disabled controls from the text minimum.

**`ink_on(*fills)`** — the better of pure white and pure black. For a single
fill the worst case is 4.58:1, so one fill always clears 4.5:1. It gives
`btn_run_fg` (judged on Run **and** its hover — two fills can pull toward
opposite poles, so that one is best-effort, 5.4–10.0:1 in every shipped
theme), `error_fg`, and the rail badge's `badge_fg`.

**`contrast_warnings(seed)`** — soft warnings in the theme editor when a
seed's `text` falls under 4.5:1 on `bg` or `surface`. Non-fatal by design: a
user's theme is theirs.

## Which floor applies

WCAG 2 asks 4.5:1 of body text, and 3:1 of large text (24px, or bold from
about 18.7px) and of the marks and boundaries that carry meaning. The only
large text in RYOS is the detail pane's 21px bold name; it is held to 4.5:1
anyway, like everything else. The 3:1 rows are marks: a row's 3px rail, the
icons on Run and Retry, the focus outline, the outlined header buttons.

## Where the shipped palettes miss

Nowhere: every audited pair clears its floor in every theme.

The last three were the gallery themes' own colours, now tuned:

- **Solarized Dark**'s `text` was `#93a1a1` (Solarized's base1): 4.86:1 on a
  row, but 3.63:1 under the pointer and 4.19:1 on the chosen row's wash. It is
  now `#aab4b4` — the same hue, lightened just to the floor (4.57:1 hovered).
- **Nord** had no pipeline colour of its own, so it took Dark's `#7c6bdd`, 2.40:1
  on Nord's pale surface. It now carries Nord's own aurora purple, `#b48ead`
  (3.55:1), as its `pipe_accent`.

Fixed earlier: a menu's highlighted entry drew
`fg_on_dark` on `accent` (2.00:1 on Nord, under 4.5:1 in five themes); it now
draws `primary_fg`. The filled SCHEDULED badge, the gutter glyphs and the
create buttons it listed no longer exist.

Everything else clears its floor in every theme: names on the window and rows,
the select bar (7.0–8.4:1), the whole output panel (6.0–11.3:1), menus
(13.8:1), and every drawn colour by construction.

## Keyboard, focus and targets

- Every control is reachable by Tab. A row is **one** stop — its buttons are
  reached through it: arrows move between rows, Enter runs, F2 edits, the Menu
  key opens its menu, Space ticks it in select mode.
- Focus always shows: a 1px `accent` edge on neutral buttons and fields, the
  wash on quiet buttons, a 2px ring on Run, and on a row the wash plus a 2px
  `focus_edge` outline — only when the keyboard put it there.
- Every clickable thing is at least `target-min`, 24px.
- Every icon-only button has an accessible name; a row's name says its last
  outcome ("Deploy site, last run failed") and its description says its keys.

`.claude/skills/review-ryos-ui/scripts/audit.py` measures all of it.

## If you add a theme

Run the seed through `validate_seed()` and `contrast_warnings()`, then
`python design-system/build.py --audit`. Check `name_fg` against `card_hover`
and `accent_wash` as well as `card_bg` — the derived hover is where
light-on-dark themes fail first.

## Colour is never the only signal

Every state carries a word or a shape beside its colour: `● OK`, `● Failed`,
`● Stopped`; Run's play icon versus Retry's arrow; an outline star versus a
filled one; `PYTHON`, `PIPELINE`, `SCHEDULED` as words. Where only a dot fits
(a favourite chip) the words are in its tooltip and accessible name. Keep that
rule when you add a state — the seven highlights are decorative precisely
because nothing depends on telling them apart.
