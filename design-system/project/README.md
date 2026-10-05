RYOS is a Windows desktop launcher for your own scripts: a list of rows, each
one a script or a pipeline you can run, with the output of every run in a
terminal panel underneath. This is its interface language, extracted from
`ryos/themes.py`, `ryos/qtui/*` and `ryos/interpreter.py`.

The whole system is built to be re-skinned. A theme is **seven colours and a
mode**, and `build_palette()` expands that seed into the 55-key palette every
widget reads. Design to the token names below and your work themes itself.

## Principles

**Flat, near-square, hairlined -- except what you choose.** Nothing casts a
shadow. Structure is square or nearly so: a section is one panel
(`radius-card`, 4px) whose rows share it, split by a `hairline`; fields and
dialog buttons are `radius-control` (3px). The things you pick or press on
their own -- group pills, output tab pills, favourite chips, preset chips,
and Run -- are pills (`radius-pill`, half their height).

**One filled thing per area.** + Script in the header, Run on a row, Run or
Retry in the detail pane, the default button in a dialog. Everything else is
quiet: words or icons, boxed only under the pointer. A second filled button
beside the first is a design bug.

**Quiet until needed.** A row shows its name, its kind, how its last run went
and Run. Edit, run-with-parameters and the star appear under the pointer, in
space kept for them so nothing moves -- and every one of them is also in the
row's right-click menu, which is the keyboard's way in.

**Colour carries meaning, never decoration.** `accent` means *script* and
*interactive*, `pipe_accent` means *pipeline*, `bolt` means *the app itself*,
green means *run* or *OK*, `error` means *the last run failed*, `warn_bg`
means *you are in a mode*. If a surface does not mean one of those things,
paint it `bg`, `card_bg` or `border`. And colour is never alone: an outcome
is a word ("● OK", "● Failed"), Retry is a different icon.

**Failure is shown on the control that fixes it.** After a failed run the Run
button *becomes* the retry: same action, `error` fill, a circular arrow. The
"● Failed" word only reports. Don't add a second control for a recovery the
user already has.

**Density is a setting, not a style.** Rows come in three sizes and a compact
form (`cardstyle.CARD_PADDING`). Never hard-code a row's padding.

**Maximised, the window spreads out.** A rail of places down the left edge;
the list goes compact beside the chosen item, whose Overview, Output and
History are tabs; an Activity bar down the right says what is running, what
runs next and what ran last. The same rows, the same Run -- the pane acts
through the chosen row's own buttons, so the two cannot drift.

## Colour

Take the ground from `bg`, surfaces from `card_bg`, and every line from
`border`. Primary text is `name_fg`. Secondary text -- paths, hints, captions
-- is `path_fg`, drawn through `drawn_colors()["muted_fg"]`, which shades it
just enough to read 4.5:1 on a row, a hovered row, the window and the chosen
row's wash. Every text colour goes through `drawn_colors()`; the unit suite
checks each pair in every shipped theme (`DRAWN_PAIRS`). The tokens carry the
results -- the drawn colours by name (`muted_fg`, `primary_fg`, `focus_edge`…)
and the inks a row paints its coloured words in (`ink-ok`, `tag-python-ink`,
`highlight-red-ink`…) -- so a design never has to guess what reaches the
screen.

`bolt` (`#ffd23f`) is the one colour that does not theme. It is the mark in
the header, and a favourite's star is shaded from it. Spend it on nothing else.

The output panel keeps its own dark world — `out_bg`, `out_stdout`,
`out_stderr`, `out_status` — on light themes too, because it is a console.
Don't tint it to match the chrome.

Never invent a shade. If you need a step between two colours, derive it the way
the engine does: `_shade(colour, ±factor)` — negative darkens, positive lightens
toward white. The eight derived tokens (`card_hover`, `status_bg`, `accent2`,
`accent_wash`, `btn_neutral_bg`, `btn_neutral_hover`, `tab_inactive_bg`,
`tab_inactive_hover`) all come from one of the seven seeds this way, and their
factors are in each token's usage note.

## Type

Two families, both asked of the OS: `sans` (Segoe UI) for the interface, `mono`
(Consolas) for the output panel and parameters shown as values. No webfonts.

Six sizes and no others: `display` (16pt, the detail pane's name), `brand`
(13pt, the wordmark), `title` (11pt bold, a row's name), `body` (10pt, the
base), `secondary` (9pt, paths and outcome words), `caption` (8pt bold
capitals: section headings, a row's kind, badges). Half-point steps read as
mistakes; don't add them.

A row's name that outgrows its width scrolls rather than truncating
(`ScrollingLabel`): it waits, creeps, and pauses under the pointer. A favourite
chip, sized to its name, shortens with an ellipsis instead.

## Spacing and layout

The list's side margin is `space-14`: the search box, the pills and the
panels line up on it. A row's padding comes from `card_padding()`; its buttons
sit `space-6` apart in `button-cell` columns, so script and pipeline rows line
up and Run is at the same x on every row.

Row anatomy, left to right: the `rail` (3px, `accent` or `pipe_accent`), then
two lines -- the kind in `caption`, the name in `title`, the outcome word; the
path or the steps, and the preset Run will pass -- then the quiet buttons, the
star, and Run. A compact row is one line: star, name, kind, outcome, Run.

## Iconography

One drawn set, `ryos/qtui/icons.py`: line icons on a 24-unit grid, 2-unit
stroke, round caps and joins (after the Lucide set), outline by default and
filled only where filling means something -- play and stop, the brand bolt, a
favourite's star. Each is tinted by a colour role from the palette and
re-tinted on a theme change. Icons usually draw at `icon` (16px).

Never use a font glyph or an emoji as an icon: they come in two fonts and the
colour-emoji font's own colours, whatever the theme. `check_one_icon_set` in
`tests/qt_smoke.py` fails on one in any button or menu text. Kept as
typography, on purpose: the `+` of "+ Script", the ● outcome dots, the ▾/▸
fold arrows, and ∥ for a pipeline step that starts with the one above.

The application mark is a gold bolt on a dark rounded square, in
`assets/AppIcon/`.

## Writing

Sentence case everywhere, including buttons and menus. Buttons name their
action -- `+ Script`, `Run selected`, `Create group`, and **Run** on a prompt
that runs. A button that opens a dialog ends in an ellipsis (`Schedule…`).
Confirmations name the thing and the consequence, and their buttons name the
choice (`Clear history` / `Keep`, `Merge` / `Replace`), never Yes / No. The
status bar reports briefly (`Ready`, `Failed.`). Tooltips are a fragment and
explain the *why* when the icon already says the what: "Last run failed —
click to run it again". One word per thing: *base folder*, *parameters*,
*favorites*.

## Accessibility

The system enforces contrast in code rather than by convention, and it does not
paint a text colour it has not checked. `contrast_ratio()` in `ryos/themes.py`
is the WCAG 2 formula; `drawn_colors()` shades each text colour until it
reads; `readable_highlight()` shades a row's highlight colour in 8% steps until
it clears 4.5:1 on both `card_bg` and `card_hover`; and the theme editor warns
on a seed whose `text` misses 4.5:1 on `bg` or `surface`.

Every clickable thing is at least `target-min` (24px); every icon button has an
accessible name; every field is linked to its label; Tab reaches every control
and shows where it is. `.claude/skills/review-ryos-ui/scripts/audit.py`
measures all of it.

A few raw palette pairs in the shipped themes miss the floor before
`drawn_colors()` adjusts them. They are listed, with what the app draws
instead, in `accessibility.md` — they are the source's values and they stay
exact.
