RYOS is a Windows desktop launcher for your own scripts: a list of cards, each
one a script or a pipeline you can run, with the output of every run in a
terminal panel underneath. This is its interface language, extracted from
`ryos/themes.py`, `ryos/ui/*` and `ryos/interpreter.py`.

The whole system is built to be re-skinned. A theme is **seven colours and a
mode**, and `build_palette()` expands that seed into the 55-key palette every
widget reads. Design to the token names below and your work themes itself.

## Principles

**Flat, square, hairlined.** Nothing is rounded and nothing casts a shadow.
Separation comes from a `hairline` border, a fill change, or a coloured `rail`
down the left edge. `radius-none` is not a default you may override — it is the
system. A rounded card in RYOS reads as foreign.

**Colour carries meaning, never decoration.** `accent` means *script*,
`pipe_accent` means *pipeline*, `bolt` means *the app itself*, `error` means
*the last run failed*, `warn_bg` means *you are in a mode*. If a surface does
not mean one of those things, paint it `bg`, `card_bg` or `border`.

**Density is a setting, not a style.** Cards render at three sizes across
compact and roomy modes — six padding pairs in all (`_CARD_PADDING` in
`ryos/ui/cards.py`). Never hard-code a card's padding; read `card_padding()` and
`row_metrics()` so a new element compacts with everything else.

**A control that changes on hover says so by swapping its fill.** Every button
in the app binds `<Enter>` and `<Leave>` to swap `bg` for its `*_hover` twin.
There is no transition, no lift, no outline. Pair every fill token you use with
its hover token.

**Failure is shown on the control that fixes it.** After a failed run the Run
button *becomes* the retry: same action, `error` fill, `↻` instead of `▶`. The
`✕ Failed` badge only reports. Don't add a second control for a recovery the
user already has.

## Colour

Take the ground from `bg`, surfaces from `card_bg`, and every line from
`border`. Primary text is `name_fg`; anything secondary — paths, timestamps,
glyph hints — is `path_fg`. On `header_bg`, `accent`, `pipe_accent`, `menu_bg`
and `tooltip_bg`, text is `fg_on_dark`; never a literal white.

`bolt` (`#ffd23f`) is the one colour that does not theme. It is the lightning
mark and the Quick Run trigger, and it is the same gold on all thirteen
palettes. Spend it only on those two things.

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
(Consolas) for the output panel and any literal command. There are no webfonts
and no display face — the wordmark is `brand`, the same Segoe UI at 14pt bold.

Set card names in `title`, controls and tabs in `control`, forms and dialog copy
in `body`, button labels in `button`, and paths, timestamps and the status bar
in `meta`. Badges are `badge` — 8pt bold, always on a filled ground, never on
`card_bg`. `micro` (7pt) exists for the pipeline step editor and nothing else;
treat it as the floor.

A card name that outgrows its width scrolls rather than truncating
(`ScrollingLabel`): it waits 1.5s, creeps 1px per 25ms, and pauses on hover.
Clipping a name with an ellipsis is not the house behaviour.

## Spacing and layout

Use the eleven steps in `spacing` and nothing between them. The window's outer
margin is `space-18`; dialogs section at `space-16`; a card's body is
`space-12` horizontally with its vertical padding from `card_padding()`.

Card anatomy, left to right: a `rail` strip, then the body on `card_bg`, then a
right-hand gutter painted `border` with the icon buttons sitting on it separated
by `hairline` frames. The gutter is filled, not spaced — the border colour
showing through *is* the divider.

## Iconography

RYOS uses no icon font and ships no icon set. Every glyph in the interface is a
Unicode character set in `sans`: `⚡` (the mark), `▶` run, `↻` retry, `■` stop,
`★`/`☆` favourite, `🔍` search, `⚙` options, `🕒` scheduled, `⏱` temporary
parameter, `🗑` delete, `✓`/`✕` status, `▲`/`▼` reorder and panel toggle. Pick
from that set before adding anything; a new glyph must read at `control` size
(13px) in a 3-character-wide button.

The application mark is the only drawn artwork: a gold bolt on a dark rounded
square, in `assets/AppIcon/`.

## Writing

Sentence case everywhere, including buttons. Controls name their action —
`+ Script`, `Run Selected`, `Check for updates`. The status bar reports in
complete sentences ending in a period (`Ready.`). Tooltips are a fragment, no
period, and explain the *why* when the glyph already says the what:
"Last run failed — click to run it again".

## Accessibility

The system enforces contrast in code rather than by convention, and it does not
paint a label colour it has not checked. `contrast_ratio()` in `ryos/themes.py`
is the WCAG 2 formula; `highlight_fg()` shades a card label's seed in 8% steps
until it clears 4.5:1 against both `card_bg` and `card_hover`; and the theme
editor warns on a seed whose `text` misses 4.5:1 on `bg` or `surface`.

Six real pairs in the shipped palettes miss the floor. They are listed, with
what to do about them, in `accessibility.md` — they are the source's values and
they stay exact.
