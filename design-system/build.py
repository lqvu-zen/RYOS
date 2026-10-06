#!/usr/bin/env python3
"""Regenerate the RYOS design system's derived files from the live codebase.

The published design system (a Claude Design System artifact) is half authored
prose -- the brand book, the per-component guidelines, the previews -- and half
values that already exist in this repository: the theme palettes, the script-tag
fills, the highlight seeds, the app icon. This script regenerates that second
half so the two can never drift apart silently.

    python design-system/build.py            # rewrite the derived files
    python design-system/build.py --check    # exit 1 if they are out of date
    python design-system/build.py --audit    # print the WCAG contrast table

`--check` is what `TestDesignSystemTokensAreCurrent` in tests/test_ryos.py runs,
so CI fails the moment a palette changes without the design system being rebuilt.

What is GENERATED (never hand-edit; this script overwrites it):
    project/tokens.json
    project/assets/AppIcon/ryos-*.png   extracted from icon.ico
    project/assets/AppIcon/ryos-mark.svg

What is AUTHORED (this script never touches it):
    project/README.md, accessibility.md, themes.md
    project/components/**, project/assets/AppIcon/README.md

Publishing the result is a separate step -- see design-system/README.md.
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "project"
sys.path.insert(0, str(ROOT))

# Every value below is read from the app's own modules, so a seed changed in
# the app shows up as a design-system diff -- the whole point.
from ryos.interpreter import _script_tag  # noqa: E402
from ryos.qtui.stylesheet import drawn_colors  # noqa: E402  -- pure, no Qt
from ryos.themes import (  # noqa: E402
    HIGHLIGHT_MIN_RATIO, HIGHLIGHT_SEEDS, _readable_on, _rel_luminance, _shade,
    build_palette, contrast_ratio,
)

# --- which palettes ship -----------------------------------------------------
# The artifact format caps a system at EIGHT colour themes, and RYOS ships
# thirteen. These eight are the ones carried; the remaining five are documented
# as seeds in project/themes.md and expand identically through build_palette().
# Light must stay first: a token missing a theme's value inherits the first
# theme's, and Light is the app's default.
THEMES: list[tuple[str, str, str]] = [
    ("light",          "Light",          "ryos/presets/light.json"),
    ("dark",           "Dark",           "ryos/presets/dark.json"),
    ("nord",           "Nord",           "theme-gallery/nord.json"),
    ("solarized-dark", "Solarized Dark", "theme-gallery/solarized-dark.json"),
    ("ocean-depths",   "Ocean Depths",   "theme-gallery/ocean-depths.json"),
    ("sepia",          "Sepia",          "theme-gallery/sepia.json"),
    ("forest-canopy",  "Forest Canopy",  "theme-gallery/forest-canopy.json"),
    ("high-contrast",  "High Contrast",  "theme-gallery/high-contrast.json"),
]

# --- authored prose ----------------------------------------------------------
# The one hand-written part of tokens.json: what each palette key is for. Order
# is the order themes.py declares the keys in, and it is also the order the
# tokens appear in the published system.
USAGE: list[tuple[str, str]] = [
    ("bg", "The window's ground: behind the list, the pills, the dialogs, the Activity bar. Seed colour."),
    ("card_bg", "The surface of a section's panel and its rows, fields, step cards, the last-run box, the Activity bar's boxes and the rail. Seed colour (`surface`)."),
    ("card_hover", "A row (or chip, or Activity line) under the pointer. Derived: surface shaded -3% light / +10% dark. Highlights and coloured words are shaded to read on this as well as card_bg."),
    ("status_bg", "The status bar along the window's bottom edge. Derived: bg shaded -5% light / +5% dark."),
    ("header_bg", "The header bar behind the bolt, the menus and the make buttons. Seed colour. Its words are header_fg."),
    ("border", "Every 1px hairline: a panel's border and the line between its rows, field borders, the splitters, menu borders. Seed colour."),
    ("accent", "Brand hue: a script row's 3px rail, + Script and a dialog's default button, a focused field's border, a chosen preset's edge, a menu's highlighted entry. Seed colour."),
    ("accent2", "The accent under the pointer, and a focused primary's ring. Derived: accent shaded -15%."),
    ("accent_wash", "The chosen row (maximised), the row the keyboard is on, a quiet button's hover and focus, the rail's current place, the chosen preset. Derived: accent shaded +86% light / -55% dark."),
    ("bolt", "The brand bolt in the header and on Quick Run; a favourite's star is shaded from it. Fixed across themes -- the identity, not a surface."),
    ("bolt_hover", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("name_fg", "Primary text: names, field text, dialog words; also the chosen pill's fill. Reads on bg, card_bg, card_hover and accent_wash."),
    ("path_fg", "The theme's muted colour. Painted through muted_fg (paths, hints, captions) and, shaded, as the Stopped outcome word."),
    ("fg_on_dark", "Text on the menu ground and a menu's highlighted entry; the seed of header_fg and stop_fg."),
    ("fg_on_dark_2", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("tab_fg", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_fg", "The seed of primary_fg, the words on accent-filled buttons."),
    ("btn_run_bg", "Run's green circle, the detail pane's Run, Run selected."),
    ("btn_run_hover", "Run under the pointer. Derived from btn_run_bg when a theme overrides it."),
    ("btn_run_fg", "The play icon on Run's green. Derived: whichever of the light or dark pole measures better against btn_run_bg AND btn_run_hover."),
    ("btn_mod_bg", "Only the theme editor's preview swatch. Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_mod_hover", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_create_bg", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_create_hover", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_neutral_bg", "A neutral button's fill (Cancel, Select All, Open output). Derived: surface shaded -6% light / +8% dark."),
    ("btn_neutral_hover", "A neutral button under the pointer. Derived: surface shaded -12% light / +14% dark."),
    ("btn_neutral_fg", "The seed of neutral_fg, a neutral button's words. Tracks text_muted."),
    ("btn_stop_idle", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete. Stop only exists while something runs."),
    ("btn_stop_idle_fg", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_stop_idle_active_fg", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_stop_idle_hover", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_stop_active", "Stop's red fill in the running list and the Activity bar; Retry under the pointer."),
    ("btn_stop_active_hover", "Stop under the pointer."),
    ("btn_disabled_bg", "A disabled button's fill. Derived: btn_neutral_bg mixed 45% toward card_bg."),
    ("btn_disabled_fg", "A disabled control's words, and a disabled menu entry. Derived: dimmed to 2.6:1 -- reads as unavailable without vanishing."),
    ("btn_dark_bg", "A button role (`#dark`) no widget uses now. Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("btn_dark_hover", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("tab_inactive_bg", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete. (Its hover twin is drawn.)"),
    ("tab_inactive_hover", "An unchosen pill under the pointer, a rail button's hover, a preset's play button hover. Derived: bg shaded -10% light / +11% dark."),
    ("ok", "The ● OK word (shaded to read: ink-ok), a passed step's chip over the output."),
    ("ok_fg", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete. The OK word carries its own shaded ink instead of a filled chip."),
    ("running", "The ● Running word, the running list's strip and wash, the rail's running-count badge."),
    ("error", "The ● Failed word (ink-error), Retry's fill, a failed step's chip."),
    ("error_fg", "The retry icon on Retry's red."),
    ("warn_bg", "The select bar while select mode is on."),
    ("warn_border", "The select bar's hairline."),
    ("warn_fg", "The select bar's words, and the ● Retrying word (shaded: ink-warn_fg)."),
    ("pipe_accent", "A pipeline's 3px rail, the PIPELINE kind word and the SCHEDULED badge (shaded: ink-pipe_accent), the bolt on a pipeline's output tab, a running pipeline's wash."),
    ("pipe_accent2", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("out_bg", "The terminal's ground. Fixed across themes by default: a console's look whatever the chrome does."),
    ("out_header", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("out_tabbar", "Not painted by the Qt interface; kept so theme files and the theme editor stay complete."),
    ("out_stdout", "stdout in the terminal, in the mono family; a parallel step's chip words."),
    ("out_stderr", "stderr in the terminal."),
    ("out_status", "Step headers and runner status lines in the terminal."),
    ("out_success", "Exit lines and Pipeline complete in the terminal."),
    ("menu_bg", "The ground of every menu."),
    ("menu_danger", "Destructive menu entries (Delete) and their icons."),
    ("tooltip_bg", "A tooltip's ground. Its words are tooltip_fg."),
    ("tooltip_border", "A tooltip's 1px hairline."),
]

# Extensions whose badge colour is worth naming in a usage note, in the order
# _script_tag declares them. Anything _script_tag gains that is missing here is
# reported by --check rather than silently dropped.
TAG_ORDER = [
    (".py", "tag-python", "Python"),
    (".js", "tag-javascript", "JavaScript"),
    (".ts", "tag-typescript", "TypeScript"),
    (".rb", "tag-ruby", "Ruby"),
    (".pl", "tag-perl", "Perl"),
    (".php", "tag-php", "PHP"),
    (".sh", "tag-shell", "Shell"),
    (".ps1", "tag-powershell", "PowerShell"),
    (".bat", "tag-batch", "Batch and CMD"),
    (".exe", "tag-exe", "EXE"),
    (".sln", "tag-visual-studio", "Visual Studio solutions"),
    (".code-workspace", "tag-vscode", "VS Code workspaces"),
]

PT_TO_PX = 4 / 3  # Qt font sizes are points; the app is laid out for 96 dpi


def _style(name, pt, weight=400, italic=False, usage=""):
    d = {"name": name, "fontSize": f"{round(pt * PT_TO_PX)}px",
         "lineHeight": round(pt * PT_TO_PX * 1.35), "fontWeight": weight,
         "usage": usage}
    if italic:
        d["fontStyle"] = "italic"
    return d


# The colours the stylesheet actually paints text and edges in, where a
# palette key would not read on every theme: `drawn_colors()` shades each one
# until it clears its floor (`DRAWN_PAIRS`, checked by the unit suite). A
# preview that writes text should use these, not the raw palette key.
DRAWN_USAGE: list[tuple[str, str]] = [
    ("primary_fg", "Words on a filled primary button (+ Script, a dialog's default) -- btn_fg, or black/white where it would not read on accent."),
    ("primary_hover_fg", "The same words on the primary button's hover fill (accent2)."),
    ("neutral_fg", "Words on a neutral button (Cancel, Clear history...)."),
    ("neutral_hover_fg", "The same words on the neutral button's hover fill."),
    ("tooltip_fg", "A tooltip's text, on tooltip_bg."),
    ("status_fg", "The status bar's text, on status_bg."),
    ("stop_fg", "Stop's icon and word on its active red fill."),
    ("muted_fg", "Paths, hints, captions, notes: path_fg shaded just enough to read on a row, a hovered row, the window and the chosen row's wash -- kept muted, never black or white."),
    ("tab_selected_fg", "The accent as a word: links (Schedule..., Edit), a row's preset, the output header's words. Held to 3:1 on card_bg and the wash."),
    ("star", "A favourite's gold star, shaded from bolt until it shows on a row, hovered or chosen."),
    ("header_fg", "Words and menus on the header bar -- fg_on_dark, or dark ink on a pale header_bg."),
    ("running_ink", "The running list's heading, in the running green, readable on the window."),
    ("running_edge", "The edge of a running script's row in the running list."),
    ("pipe_edge", "The edge of a running pipeline's row in the running list."),
    ("running_wash", "A running script's row fill: the window mixed 16% toward running."),
    ("pipe_wash", "A running pipeline's row fill: the window mixed 16% toward pipe_accent."),
    ("running_name_fg", "A job's name on either running wash."),
    ("running_time_fg", "A job's elapsed time on either running wash."),
    ("step_fg", "A parallel step's chip over the output, in the terminal's own text colour."),
    ("step_fail_fg", "That chip once its step failed: error, readable on out_bg."),
    ("step_ok_fg", "That chip once its step passed: running green, readable on out_bg."),
    ("header_edge", "The outline of + Pipeline and + Group on the header: the only thing that says they are buttons, so held to 3:1."),
    ("pill_fg", "The chosen pill's words (group, output, detail and Options tabs): the window colour on a name_fg fill."),
    ("pill_idle_fg", "An unchosen pill's words, on the window and on its hover fill."),
    ("pill_edge", "An unchosen pill's 1px outline (group, detail, Options and output tabs): the only thing that says it is a button, so held to 3:1 on the window and the hover fill. The chosen pill's edge is its own fill."),
    ("control_edge", "The 1px outline of fields, neutral buttons, the group picker and preset pills -- in Light the fills alone are 1.01:1 to the window."),
    ("focus_edge", "The 2px outline round the row the keyboard is on (and a focused chip's edge): the accent, shaded to 3:1 against the row's wash and the rows around it."),
    ("badge_fg", "The running count on the rail's Activity button, on the running fill."),
]


def palettes() -> dict[str, dict]:
    """The eight shipped palettes, exactly as the app resolves them.

    Light and Dark carry hand-tuned reference palettes and are used verbatim;
    the rest are expanded from their 7-colour seed by build_palette().
    """
    out = {}
    for tid, _name, rel in THEMES:
        data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        if tid in ("light", "dark") and "palette" in data:
            out[tid] = dict(data["palette"])
        else:
            out[tid] = build_palette(data["seed"])
    return out


def resolve_highlight(seed: str, surfaces: tuple[str, ...]) -> tuple[str, int]:
    """Mirror of ui.theme._readable_on, returning the step count as well.

    Kept here rather than imported because the app's version is memoised behind
    the live palette; this one is explicit about which surfaces it ran against.
    """
    step = 0.08 if _rel_luminance(surfaces[0]) < 0.45 else -0.08
    cur = seed
    for i in range(30):
        if all(contrast_ratio(cur, s) >= HIGHLIGHT_MIN_RATIO for s in surfaces):
            return cur, i
        cur = _shade(cur, step)
    return cur, 30


def build_tokens() -> dict:
    pal = palettes()
    missing = set(pal["light"]) - {k for k, _ in USAGE}
    if missing:
        raise SystemExit(
            f"design-system/build.py: {len(missing)} palette key(s) have no usage "
            f"note: {', '.join(sorted(missing))}. Add them to USAGE.")
    stale = {k for k, _ in USAGE} - set(pal["light"])
    if stale:
        raise SystemExit(
            f"design-system/build.py: USAGE names key(s) the palette no longer "
            f"has: {', '.join(sorted(stale))}.")

    ids = [t for t, _, _ in THEMES]
    colors = [{"name": k, "value": {t: pal[t][k].lower() for t in ids}, "usage": u}
              for k, u in USAGE]

    drawn = {t: drawn_colors(pal[t]) for t in ids}
    noted = {k for k, _ in DRAWN_USAGE}
    if set(drawn["light"]) != noted:
        raise SystemExit(
            "design-system/build.py: drawn_colors() and DRAWN_USAGE disagree: "
            f"unnoted {sorted(set(drawn['light']) - noted)}, "
            f"gone {sorted(noted - set(drawn['light']))}.")
    colors += [{"name": k, "value": {t: drawn[t][k].lower() for t in ids},
                "usage": f"Drawn: {u}"} for k, u in DRAWN_USAGE]

    # What a row actually paints a coloured word in: the colour shaded until
    # it reads on the row and the hovered row (cards._ink). A fixed tag fill
    # or a highlight seed is never painted as-is, and in a dark theme the raw
    # value can all but vanish.
    def ink(theme: str, color: str) -> str:
        return _readable_on(color, (pal[theme]["card_bg"], pal[theme]["card_hover"])).lower()

    for key, what in (("ok", "the ● OK outcome word"), ("error", "the ● Failed outcome word"),
                      ("running", "the ● Running outcome word"),
                      ("path_fg", "the ● Stopped outcome word"),
                      ("warn_fg", "the ● Retrying outcome word"),
                      ("pipe_accent", "the PIPELINE / PIPE kind word and the SCHEDULED badge")):
        colors.append({"name": f"ink-{key}", "value": {t: ink(t, pal[t][key]) for t in ids},
                       "usage": f"Painted: {what} on a row -- {key} shaded to read on "
                                "card_bg and card_hover."})

    for key, seed in HIGHLIGHT_SEEDS.items():
        colors.append({
            "name": f"highlight-{key}", "value": seed.lower(),
            "usage": (f"Seed for the {key} card label. Never painted as-is: "
                      "highlight_fg() shades it in 8% steps away from card_bg and "
                      "card_hover until it clears 4.5:1 on both, so one set of seven "
                      "stays legible on every theme.")})

    for key, seed in HIGHLIGHT_SEEDS.items():
        colors.append({
            "name": f"highlight-{key}-ink", "value": {t: ink(t, seed) for t in ids},
            "usage": f"Painted: a {key}-highlighted row's name, the seed shaded to read."})

    known = {ext for ext, _, _ in TAG_ORDER}
    for ext, name, label in TAG_ORDER:
        _tag_label, fill = _script_tag(f"x{ext}")
        colors.append({
            "name": name, "value": fill.lower(),
            "usage": (f"The colour of {label}: fixed across themes -- it names the "
                      "language, so it is part of the label. Never painted as-is; "
                      f"see {name}-ink.")})
        colors.append({
            "name": f"{name}-ink", "value": {t: ink(t, fill) for t in ids},
            "usage": f"Painted: a {label} row's kind word, {name} shaded to read on the row."})
    _unknown_label, unknown_fill = _script_tag("x.nosuchext")
    colors.append({
        "name": "tag-unknown", "value": unknown_fill.lower(),
        "usage": ("The colour for any other extension, whose upper-cased extension "
                  "becomes the kind word. Fixed across themes; see tag-unknown-ink.")})
    colors.append({
        "name": "tag-unknown-ink", "value": {t: ink(t, unknown_fill) for t in ids},
        "usage": "Painted: that kind word, shaded to read on the row."})
    # .cmd shares .bat's fill by design; anything else new needs a usage note.
    src = inspect.getsource(_script_tag)
    for ext in re.findall(r'"(\.[a-z0-9-]+)":', src):
        if ext not in known and ext != ".cmd":
            raise SystemExit(
                f"design-system/build.py: _script_tag gained {ext!r} with no entry "
                "in TAG_ORDER. Add one (with a usage note).")

    return {
        "name": "RYOS",
        "version": 1,
        "color": {
            "themes": [{"id": t, "name": n} for t, n, _ in THEMES],
            "tokens": colors,
            "note": ("Eight of the thirteen palettes RYOS ships. Light and Dark are "
                     "hand-tuned and used verbatim; the other six are expanded from a "
                     "7-colour seed by build_palette() in ryos/themes.py, so their "
                     "derived values are exactly what the app paints."),
        },
        "type": {
            "note": ("Two OS families, no webfonts: RYOS is a Qt desktop app and asks "
                     "the platform for Segoe UI and Consolas by name. Six sizes, set "
                     "in points in ryos/qtui/stylesheet.py (10pt is the base every "
                     "widget inherits); px below are those points at 96 dpi."),
            "fonts": [],
            "families": {
                "sans": '"Segoe UI", "Selawik", system-ui, sans-serif',
                "mono": '"Consolas", "Cascadia Mono", ui-monospace, monospace',
            },
            "groups": [
                {"name": "Interface", "family": "sans", "styles": [
                    _style("display", 16, 700, usage="The chosen item's name in the maximised detail pane (16pt bold). The largest type in the app."),
                    _style("brand", 13, 700, usage="The header's RYOS wordmark, beside the drawn bolt (13pt bold)."),
                    _style("title", 11, 700, usage="A row's name (11pt bold; 10pt semibold on a compact row)."),
                    _style("body", 10, usage="The base: menus, fields, buttons, dialog labels, pills (10pt; pills and buttons semibold)."),
                    _style("secondary", 9, usage="A row's path and outcome word, facts in the detail pane, hints under fields, the status bar (9pt)."),
                    _style("caption", 8, 700, usage="Section headings, a row's kind (PYTHON, PIPELINE), badges, the detail pane's headings (8pt bold, capitals)."),
                ]},
                {"name": "Terminal", "family": "mono", "styles": [
                    _style("terminal", 10, usage="The output panel and run history (Consolas 10)."),
                    _style("terminal-small", 9, usage="Parameters shown as values: a row's preset chip, the detail pane's preset chips (Consolas 9)."),
                ]},
            ],
        },
        "spacing": {
            "note": ("Qt layout margins and stylesheet padding as the code sets them "
                     "(ryos/qtui/*, cardstyle.CARD_PADDING). Not a strict grid: these "
                     "are the steps in use, ordered by size."),
            "tokens": [
                {"name": "space-1", "value": "1px", "usage": "Gap between a row's name line and its path line."},
                {"name": "space-3", "value": "3px", "usage": "A favourite chip's vertical padding; an output tab pill's vertical padding."},
                {"name": "space-4", "value": "4px", "usage": "Gap between header buttons and between group pills."},
                {"name": "space-6", "value": "6px", "usage": "Gap between a row's buttons and between favourite chips; a menu item's vertical padding."},
                {"name": "space-8", "value": "8px", "usage": "Gap between a row's kind, name and outcome; between the search box and the pills."},
                {"name": "space-10", "value": "10px", "usage": "A row's vertical padding at medium size; the top of the list area."},
                {"name": "space-12", "value": "12px", "usage": "A row's horizontal padding at every size; a menu icon's inset; a chip's horizontal padding."},
                {"name": "space-14", "value": "14px", "usage": "The list's side margin -- the search box, pills and panels line up on it; a pill's horizontal padding."},
                {"name": "space-24", "value": "24px", "usage": "A menu item's gap on the right; the menu words start 36px in (the icon column)."},
                {"name": "space-26", "value": "26px", "usage": "The detail pane's side margin, maximised."},
            ],
        },
        "radius": {
            "note": ("RYOS is near-square, with one exception: things you choose or "
                     "press on their own are pills. No shadows; separation comes from a "
                     "hairline, a fill or the rail."),
            "tokens": [
                {"name": "radius-card", "value": "4px", "usage": "A section's panel (its rows share it), the update banner, the quiet buttons' hover box."},
                {"name": "radius-control", "value": "3px", "usage": "Text fields, drop-downs, spin boxes, dialog buttons."},
                {"name": "radius-pill", "value": "50%", "usage": "Half the height: group pills, output tab pills, favourite chips, preset chips -- and Run, a circle."},
                {"name": "radius-none", "value": "0", "usage": "The header bar, section headings, rows inside a panel, the output panel."},
                {"name": "radius-icon", "value": "24%", "usage": "The application icon's rounded rectangle only (make_icon.py). Not a UI value."},
            ],
        },
        "size": {
            "note": "Line weights and fixed sizes, in px.",
            "tokens": [
                {"name": "hairline", "value": "1px", "usage": "A panel's border and the line between its rows; field and tooltip borders; a neutral button's focus edge."},
                {"name": "rail", "value": "3px", "usage": "The strip down a row's left edge: accent on a script, pipe_accent on a pipeline."},
                {"name": "focus-ring", "value": "2px", "usage": "Keyboard focus on Run (in name_fg, on any fill). Quiet buttons show focus with the accent wash instead."},
                {"name": "target-min", "value": "24px", "usage": "The smallest thing you can click (WCAG 2.5.8): chip Run, preset chip, Quick Run, tab close."},
                {"name": "run", "value": "32px", "usage": "Run's diameter on a row; 26px on a compact row, 24px on a favourite chip."},
                {"name": "button-cell", "value": "32px", "usage": "The width of each of a row's quiet buttons, so script and pipeline rows line up."},
                {"name": "icon", "value": "16px", "usage": "The usual icon size; drawn on a 24-unit grid with a 2-unit stroke (ryos/qtui/icons.py)."},
            ],
        },
        "meta": _provenance(),
    }


def _provenance() -> dict:
    return {
        "source": "github",
        "repo": "lqvu-zen/ryos",
        "package": "ryos",
        "generator": "design-system/build.py",
        "paths": {
            "tokens": ["ryos/themes.py", "ryos/qtui/stylesheet.py", "ryos/interpreter.py",
                       "ryos/presets/*.json", "theme-gallery/*.json"],
            "fonts": [],
            "assets": ["icon.ico", "make_icon.py"],
            "docs": ["README.md", "CLAUDE.md", "docs/ARCHITECTURE.md", "theme-gallery/"],
        },
        "components": {
            "AppHeader": "ryos/qtui/shell.py", "Rail": "ryos/qtui/rail.py",
            "StatusBar": "ryos/qtui/shell.py", "SectionPanel": "ryos/qtui/sections.py",
            "Row": "ryos/qtui/cards.py", "FavoriteChip": "ryos/qtui/cards.py",
            "DetailPane": "ryos/qtui/detail.py", "StepCard": "ryos/qtui/detail.py",
            "ActivityBar": "ryos/qtui/activity.py", "Buttons": "ryos/qtui/stylesheet.py",
            "RunButton": "ryos/qtui/cards.py", "IconButton": "ryos/qtui/icons.py",
            "PresetPill": "ryos/qtui/detail.py", "PillTabs": "ryos/qtui/stylesheet.py",
            "SearchField": "ryos/qtui/shell.py", "FormControls": "ryos/qtui/stylesheet.py",
            "QuickRunBar": "ryos/qtui/quickrun.py", "SelectBar": "ryos/qtui/shell.py",
            "OutcomeWord": "ryos/cardstyle.py", "KindTag": "ryos/qtui/cards.py",
            "LabelHighlight": "ryos/themes.py", "Tooltip": "ryos/qtui/widgets.py",
            "OutputPanel": "ryos/qtui/shell.py",
        },

    }


# --- the app mark ------------------------------------------------------------

def icon_files() -> dict[str, bytes]:
    """The PNG entries inside icon.ico, plus an SVG at the generator's own
    coordinates. Only the four sizes the design system documents are kept."""
    raw = (ROOT / "icon.ico").read_bytes()
    _reserved, _typ, count = struct.unpack("<HHH", raw[:6])
    out: dict[str, bytes] = {}
    wanted = {16, 32, 64, 256}
    for i in range(count):
        off = 6 + 16 * i
        w, _h, _cc, _r, _pl, _bpp, size, offset = struct.unpack(
            "<BBBBHHII", raw[off:off + 16])
        width = w or 256
        blob = raw[offset:offset + size]
        if width in wanted and blob[:8] == b"\x89PNG\r\n\x1a\n":
            out[f"ryos-{width}.png"] = blob
    if set(out) != {f"ryos-{n}.png" for n in wanted}:
        raise SystemExit(
            "design-system/build.py: icon.ico no longer carries PNG entries at "
            f"{sorted(wanted)}; got {sorted(out)}.")

    # Same polygon make_icon.py draws, at s = 256.
    s = 256.0
    pts = [(0.62, 0.04), (0.22, 0.55), (0.46, 0.55),
           (0.38, 0.96), (0.78, 0.45), (0.54, 0.45)]
    poly = " ".join(f"{x * s:g},{y * s:g}" for x, y in pts)
    pad, r = 0.06 * s, 0.24 * s
    out["ryos-mark.svg"] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
        'width="256" height="256" role="img" aria-label="RYOS">\n'
        "  <title>RYOS</title>\n"
        f'  <rect x="{pad:g}" y="{pad:g}" width="{s - 2 * pad:g}" '
        f'height="{s - 2 * pad:g}" rx="{r:g}" ry="{r:g}" fill="#1e2a3a"/>\n'
        f'  <polygon points="{poly}" fill="#ffd23f"/>\n'
        "</svg>\n").encode("utf-8")
    return out


# --- WCAG audit --------------------------------------------------------------

# (fg, bg, floor, where it appears): the raw palette pairs the Qt interface
# paints as they are. Every other text colour goes through drawn_colors(),
# which shades it to its floor -- DRAWN_PAIRS in ryos/qtui/stylesheet.py, checked
# in every theme by the unit suite -- so it is not repeated here. WCAG 2 asks
# 4.5:1 of body text and 3:1 of the marks that carry meaning: the rails.
AUDIT_PAIRS: list[tuple[str, str, float, str]] = [
    ("name_fg", "bg", 4.5, "names and words on the window"),
    ("name_fg", "card_bg", 4.5, "a row's name"),
    ("name_fg", "card_hover", 4.5, "a row's name under the pointer"),
    ("name_fg", "accent_wash", 4.5, "the chosen row's name, maximised"),
    ("btn_run_fg", "btn_run_bg", 3.0, "the play icon on Run"),
    ("btn_run_fg", "btn_run_hover", 3.0, "the play icon on Run under the pointer"),
    ("error_fg", "error", 3.0, "the retry icon on Retry"),
    ("warn_fg", "warn_bg", 4.5, "the select bar's words"),
    ("fg_on_dark", "menu_bg", 4.5, "menu entries"),
    ("out_stdout", "out_bg", 4.5, "stdout"),
    ("out_stderr", "out_bg", 4.5, "stderr"),
    ("out_status", "out_bg", 4.5, "step headers and status lines"),
    ("out_success", "out_bg", 4.5, "exit lines"),
    ("accent", "card_bg", 3.0, "a script row's 3px rail"),
    ("pipe_accent", "card_bg", 3.0, "a pipeline row's 3px rail"),
]


def audit() -> list[tuple[str, str, str, float, float]]:
    """Every (theme, fg, bg, ratio, floor) under its floor, worst first."""
    pal = palettes()
    fails = []
    for tid, _name, _ in THEMES:
        for fg, bg, floor, _where in AUDIT_PAIRS:
            ratio = contrast_ratio(pal[tid][fg], pal[tid][bg])
            if ratio < floor:
                fails.append((tid, fg, bg, ratio, floor))
    return sorted(fails, key=lambda r: r[3] / r[4])


def print_audit() -> None:
    pal = palettes()
    ids = [t for t, _, _ in THEMES]
    head = f"{'pair':34}{'floor':>6}" + "".join(f"{t:>9.8}" for t in ids)
    print(head)
    print("-" * len(head))
    for fg, bg, floor, where in AUDIT_PAIRS:
        cells = ""
        for t in ids:
            ratio = contrast_ratio(pal[t][fg], pal[t][bg])
            cells += f"{ratio:8.2f}" + ("*" if ratio < floor else " ")
        print(f"{fg + ' / ' + bg:34}{floor:>6.1f}{cells}   {where}")

    fails = audit()
    pairs = {(f, b) for _t, f, b, _r, _fl in fails}
    print(f"\n* = under the row's floor. {len(fails)} failing cells across "
          f"{len(pairs)} distinct pairs; all are recorded in "
          "project/accessibility.md and kept exact.")
    print("\nhighlight_fg() resolution "
          "(all seven clear 4.5:1 on card_bg AND card_hover by construction):")
    for theme in ("light", "dark"):
        surfaces = (pal[theme]["card_bg"], pal[theme]["card_hover"])
        got = []
        for k, v in HIGHLIGHT_SEEDS.items():
            colour, steps = resolve_highlight(v, surfaces)
            got.append(f"{k}={colour}({steps})")
        print(f"  {theme:6} " + "  ".join(got))


# --- driver ------------------------------------------------------------------

# Generated files whose bytes git may rewrite on checkout. Compared with line
# endings normalised, because CI runs --check on Windows too and a CRLF
# checkout would otherwise report an up-to-date tree as stale. .gitattributes
# pins these to LF as well; this is the belt to that pair of braces, so the
# check is correct in any working tree however it was configured.
_TEXT_SUFFIXES = frozenset({".json", ".svg"})


def _unchanged(path: Path, blob: bytes) -> bool:
    current = path.read_bytes()
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return current.replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n")
    return current == blob


def generated_files() -> dict[str, bytes]:
    files = {"tokens.json":
             (json.dumps(build_tokens(), indent=1) + "\n").encode("utf-8")}
    for name, blob in icon_files().items():
        files[f"assets/AppIcon/{name}"] = blob
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a generated file is out of date")
    ap.add_argument("--audit", action="store_true",
                    help="print the WCAG contrast table and exit")
    args = ap.parse_args()

    if args.audit:
        print_audit()
        return 0

    files = generated_files()
    stale = []
    for rel, blob in files.items():
        path = OUT / rel
        if path.exists() and _unchanged(path, blob):
            continue
        stale.append(rel)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)

    if args.check:
        if stale:
            print("design system is out of date: "
                  + ", ".join(f"project/{s}" for s in sorted(stale)),
                  file=sys.stderr)
            print("run: python design-system/build.py", file=sys.stderr)
            return 1
        print(f"design system up to date ({len(files)} generated files)")
        return 0

    if stale:
        print("rewrote " + ", ".join(f"project/{s}" for s in sorted(stale)))
    else:
        print(f"design system already up to date ({len(files)} generated files)")
    fails = audit()
    if fails:
        pairs = {(f, b) for _t, f, b, _r, _fl in fails}
        print(f"note: {len(fails)} cells across {len(pairs)} colour pairs are "
              "under their contrast floor (--audit for the table; they are "
              "recorded in project/accessibility.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
