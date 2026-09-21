# Theming

A RYOS theme is not a palette. It is a **seed**: a `mode` plus seven colours,
which `build_palette()` in `ryos/themes.py` expands into all 55 keys. Users
write seeds by hand in `themes.json`, drop them in a themes folder, or build
them in the in-app editor — so the seven seed colours are the only surface a
non-programmer ever touches, and everything else has to fall out of them.

## The seven

| Seed key | Becomes | Notes |
|---|---|---|
| `mode` | which reference palette to start from | `light` or `dark`; decides the sign of every derivation |
| `bg` | `bg` | and, shaded, `status_bg`, `tab_inactive_bg`, `tab_inactive_hover` |
| `surface` | `card_bg` | and, shaded, `card_hover`, `btn_neutral_bg`, `btn_neutral_hover` |
| `border` | `border` | used flat, never derived from |
| `accent` | `accent` | and `accent2`, `accent_wash`, `btn_mod_*`, `btn_create_*` |
| `text` | `name_fg`, `tab_fg` | |
| `text_muted` | `path_fg`, `btn_neutral_fg` | |
| `header_bg` | `header_bg` | used flat |

Everything a seed does not mention — the badge colours, the output panel, menus,
tooltips, the gold bolt — comes from the mode's reference palette. That is
deliberate: a user picking seven colours should not be able to make a failure
badge unreadable or lose the identity.

## Deriving

`_shade(colour, factor)` is the only interpolation in the system. A negative
factor multiplies each channel toward black; a positive one moves it toward
white by that fraction of the remaining distance. The factors are fixed per key
and flip with the mode:

```
card_hover          surface  -3%  light   /  +10%  dark
status_bg           bg       -5%          /   +5%
btn_neutral_bg      surface  -6%          /   +8%
btn_neutral_hover   surface -12%          /  +14%
tab_inactive_bg     bg       -5%          /   +6%
tab_inactive_hover  bg      -10%          /  +11%
accent2             accent  -15%          /  -15%
accent_wash         accent  +86%          /  -55%
```

If you add a token that needs a hover or pressed twin, derive it here rather
than asking the user for another colour.

## Advanced overrides

A seed may additionally pin any of twelve keys — `btn_run_bg`, `error`,
`out_bg`, `out_stdout`, `out_stderr`, `out_status`, `accent2`,
`btn_neutral_bg`, `tab_inactive_bg`, `pipe_accent`, `bolt`, `warn_bg` — and
`build_palette()` refreshes that key's companions from the override so the
result stays coherent: pin `btn_run_bg` and its hover is re-derived, pin
`pipe_accent` and `pipe_accent2` follows.

## Adding a token

Because every palette starts from the mode's reference, a new key added to
`_REFERENCE_FALLBACK` is immediately present in every built-in, preset, custom
and imported theme — no theme file needs editing and no lookup can `KeyError`.
Add the key with sensible light and dark defaults, and only make it
seed-derived if a user would genuinely expect it to follow their accent.

## The thirteen shipped palettes

Light and Dark carry hand-tuned reference palettes and are used verbatim; the
other eleven are seeds in `theme-gallery/` that `build_palette()` expands.

The published design system carries **eight** of them — the artifact format caps
a system at eight colour themes. The remaining five are listed here in full, and
expand identically: drop a seed into `theme-gallery/`, add it to the `THEMES`
list at the top of `design-system/build.py`, and rebuild.

| Theme | Mode | bg | surface | border | accent | text | text_muted | header_bg | In tokens.json |
|---|---|---|---|---|---|---|---|---|---|
| Light | light | `#f0f2f5` | `#ffffff` | `#dde2ea` | `#4a6fa5` | `#1a1a2e` | `#626975` | `#1e2a3a` | yes |
| Dark | dark | `#14181f` | `#1d232d` | `#2c3440` | `#5b8bd0` | `#e8ebf0` | `#9aa3b2` | `#0f141b` | yes |
| Forest Canopy | light | `#faf9f6` | `#ffffff` | `#e3e1d8` | `#3a6b38` | `#26301f` | `#566049` | `#2d4a2b` | yes |
| Golden Hour | light | `#efe3d2` | `#f8f1e6` | `#ddcbb1` | `#b3545a` | `#4a403a` | `#6e6056` | `#4a403a` | seed only |
| High Contrast | dark | `#000000` | `#121212` | `#5a5a5a` | `#4aa3ff` | `#ffffff` | `#d0d0d0` | `#000000` | yes |
| Midnight Galaxy | dark | `#2b1e3e` | `#382a4f` | `#473a5f` | `#9a82d8` | `#e6e6fa` | `#bcaed8` | `#1f1530` | seed only |
| Nord | dark | `#2e3440` | `#3b4252` | `#434c5e` | `#88c0d0` | `#eceff4` | `#aab1c0` | `#272c36` | yes |
| Ocean Depths | dark | `#1a2332` | `#243047` | `#33415c` | `#2c8f8f` | `#f1faee` | `#a8dadc` | `#121a26` | yes |
| Sepia | light | `#f4ecd8` | `#fbf5e6` | `#e3d9bf` | `#9a5b2e` | `#4b3a2a` | `#6f5b45` | `#3a2c1d` | yes |
| Solarized Dark | dark | `#002b36` | `#073642` | `#0f4a59` | `#268bd2` | `#93a1a1` | `#839496` | `#001f27` | yes |
| Solarized Light | light | `#eee8d5` | `#fdf6e3` | `#ddd6c1` | `#1f7ac0` | `#4d646b` | `#5d7077` | `#073642` | seed only |
| Sunset Boulevard | dark | `#264653` | `#2f5563` | `#3c6675` | `#e76f51` | `#f6ede2` | `#e9c46a` | `#1c333d` | seed only |
| Tech Innovation | dark | `#1e1e1e` | `#2a2a2a` | `#3a3a3a` | `#0a84ff` | `#ffffff` | `#b0b0b0` | `#141414` | seed only |

Swapping which eight ship is a one-line change to that `THEMES` list, with one
constraint: **Light must stay first.** A token missing a theme's value inherits
the first theme's, and Light is the app's default.
