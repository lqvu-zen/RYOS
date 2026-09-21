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
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "project"
sys.path.insert(0, str(ROOT))

# HIGHLIGHT_SEEDS and HIGHLIGHT_MIN_RATIO are pure data, but they live in
# ryos/ui/theme.py, which imports tkinter. Reading them by mocking tkinter --
# the same trick tests/test_ryos.py uses -- keeps this script runnable on a
# headless CI runner AND keeps the values single-sourced, which is the whole
# point: a seed changed in the app must show up as a design-system diff.
sys.modules.setdefault("tkinter", mock.MagicMock())
sys.modules.setdefault("tkinter.ttk", mock.MagicMock())
sys.modules.setdefault("tkinter.font", mock.MagicMock())

from ryos.interpreter import _script_tag  # noqa: E402
from ryos.themes import (  # noqa: E402
    _rel_luminance, _shade, build_palette, contrast_ratio,
)
from ryos.ui.theme import HIGHLIGHT_MIN_RATIO, HIGHLIGHT_SEEDS  # noqa: E402

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
    ("bg", "Window ground behind the tab bar, card list and search bar. Seed colour."),
    ("card_bg", "ScriptCard and PipelineCard surface, and the active GroupTab's face. Carries name_fg and path_fg. Seed colour (`surface`)."),
    ("card_hover", "Card surface under the pointer. Derived: surface shaded -3% on a light theme, +10% on a dark one. highlight_fg() checks label colours against this as well as card_bg."),
    ("status_bg", "StatusBar strip along the window's bottom edge. Derived: bg shaded -5% light / +5% dark."),
    ("header_bg", "AppHeader band behind the bolt mark and the create buttons. Carries fg_on_dark. Seed colour."),
    ("border", "1px hairline on every card, the gutter behind a card's icon buttons and their 1px separators, the PanedWindow sash, and the scrollbar thumb. Seed colour."),
    ("accent", "Brand hue: the ScriptCard's 5px left rail, the active GroupTab's label and 3px indicator, the Combobox focus ring, and the + Script / + Group / + Pipeline buttons. Seed colour."),
    ("accent2", "Pressed and hover state for every accent-filled button. Derived: accent shaded -15%."),
    ("accent_wash", "Tinted fill behind a selected Combobox row, an active tab's hover, and a favourited card's star button. Derived: accent shaded +86% light / -55% dark."),
    ("bolt", "The lightning mark in the header and the Quick Run bar's toggle, and the current match in output search. Fixed across every theme -- it is the identity, not a themed surface."),
    ("bolt_hover", "Quick Run toggle under the pointer."),
    ("name_fg", "Primary text: card names, dialog body copy, entry text. Reads on bg, card_bg and card_hover."),
    ("path_fg", "Secondary text: script paths, last-run timestamps, the search glyph, the Combobox arrow. Reads on bg and card_bg."),
    ("fg_on_dark", "Text and glyphs on header_bg, accent, pipe_accent, menu_bg and tooltip_bg."),
    ("fg_on_dark_2", "Muted text on the output panel's header and tab bar."),
    ("tab_fg", "Label on an inactive GroupTab. Reads on tab_inactive_bg."),
    ("btn_fg", "Label on every filled FlatButton (run, create, modify). Reads on btn_run_bg, btn_create_bg and error."),
    ("btn_run_bg", "Run button fill on cards and the Run Selected action."),
    ("btn_run_hover", "Run button under the pointer. Derived from btn_run_bg when a theme overrides it."),
    ("btn_mod_bg", "Modify / edit button fill. Tracks accent."),
    ("btn_mod_hover", "Modify button under the pointer. Tracks accent2."),
    ("btn_create_bg", "Header create buttons (+ Script, + Group, + Pipeline). Tracks accent."),
    ("btn_create_hover", "Header create buttons under the pointer. Tracks accent2."),
    ("btn_neutral_bg", "Unfilled icon buttons in a card's right-hand gutter: reorder, history, star. Derived: surface shaded -6% light / +8% dark."),
    ("btn_neutral_hover", "Neutral icon button under the pointer. Derived: surface shaded -12% light / +14% dark."),
    ("btn_neutral_fg", "Glyph on a neutral icon button. Tracks text_muted."),
    ("btn_stop_idle", "Stop button fill while nothing is running. Fixed across themes -- the stop control reads the same everywhere."),
    ("btn_stop_idle_fg", "Stop glyph while disabled."),
    ("btn_stop_idle_active_fg", "Stop glyph while disabled and moused over."),
    ("btn_stop_idle_hover", "Disabled stop button under the pointer."),
    ("btn_stop_active", "Stop button fill while a job is running, and the pressed state of the retry Run button."),
    ("btn_stop_active_hover", "Armed stop button under the pointer."),
    ("btn_disabled_bg", "Slab of a control that is born disabled and never flips -- the palette default. A control that toggles calls disabled_pair() with its own colours instead. Derived: btn_neutral_bg mixed 45% toward card_bg, or shaded away from it where there is nowhere to mix toward."),
    ("btn_disabled_fg", "Label on a disabled control. Derived: btn_neutral_fg mixed toward its own slab in 24 steps until it drops to 2.6:1 -- dim enough to read as disabled, not so dim it vanishes."),
    ("btn_dark_bg", "The header's options (gear) button."),
    ("btn_dark_hover", "Options button under the pointer; also the StatusBar's text colour."),
    ("tab_inactive_bg", "Inactive GroupTab face and its 3px indicator. Derived: bg shaded -5% light / +6% dark."),
    ("tab_inactive_hover", "Inactive GroupTab under the pointer. Derived: bg shaded -10% light / +11% dark."),
    ("ok", "Success badge fill on a card that last ran clean."),
    ("running", "Fill for a card's in-flight run row."),
    ("error", "Failure badge fill, and the Run button's retry state after a failed run."),
    ("warn_bg", "SelectBar banner ground while multi-select is on."),
    ("warn_border", "SelectBar hairline, and the Select All button's hover fill."),
    ("warn_fg", "SelectBar text. Reads on warn_bg."),
    ("pipe_accent", "PipelineCard's 5px left rail and the SCHEDULED badge, separating a pipeline from a script at a glance."),
    ("pipe_accent2", "Pipeline hover and step connectors. Derived: pipe_accent shaded +12% when a theme overrides it."),
    ("out_bg", "Output panel ground. Fixed across themes by default: the terminal keeps a console's look whatever the chrome does."),
    ("out_header", "Output panel header strip and the Find bar."),
    ("out_tabbar", "Output panel per-job tab strip."),
    ("out_stdout", "stdout text in the output panel, set in the mono family."),
    ("out_stderr", "stderr text in the output panel."),
    ("out_status", "Runner status lines (started, exit code) in the output panel."),
    ("out_success", "Clean-exit line in the output panel."),
    ("menu_bg", "Right-click and options menu ground. Carries fg_on_dark; highlight swatches are re-shaded against this, not against card_bg."),
    ("menu_danger", "Destructive menu entries (Delete)."),
    ("tooltip_bg", "Tooltip ground. Carries fg_on_dark."),
    ("tooltip_border", "Tooltip 1px hairline."),
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

PT_TO_PX = 4 / 3  # Tk sizes are points; the app is laid out for 96 dpi


def _style(name, pt, weight=400, italic=False, usage=""):
    d = {"name": name, "fontSize": f"{round(pt * PT_TO_PX)}px",
         "lineHeight": round(pt * PT_TO_PX * 1.35), "fontWeight": weight,
         "usage": usage}
    if italic:
        d["fontStyle"] = "italic"
    return d


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

    for key, seed in HIGHLIGHT_SEEDS.items():
        colors.append({
            "name": f"highlight-{key}", "value": seed.lower(),
            "usage": (f"Seed for the {key} card label. Never painted as-is: "
                      "highlight_fg() shades it in 8% steps away from card_bg and "
                      "card_hover until it clears 4.5:1 on both, so one set of seven "
                      "stays legible on every theme.")})

    known = {ext for ext, _, _ in TAG_ORDER}
    for ext, name, label in TAG_ORDER:
        _tag_label, fill = _script_tag(f"x{ext}")
        colors.append({
            "name": name, "value": fill.lower(),
            "usage": (f"ScriptTypeBadge fill for {label}. Fixed across themes -- the "
                      "badge names the language, so its colour is part of the label. "
                      "Carries fg_on_dark.")})
    _unknown_label, unknown_fill = _script_tag("x.nosuchext")
    colors.append({
        "name": "tag-unknown", "value": unknown_fill.lower(),
        "usage": ("ScriptTypeBadge fill for any other extension, whose upper-cased "
                  "extension becomes the label. Fixed across themes. Carries fg_on_dark.")})
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
            "note": ("Two OS families, no webfonts: RYOS is a Tk desktop app and asks "
                     "the platform for Segoe UI and Consolas by name. Sizes below are "
                     "the Tk point sizes converted at 96 dpi -- the usage note gives "
                     "the point size the code passes."),
            "fonts": [],
            "families": {
                "sans": '"Segoe UI", "Selawik", system-ui, sans-serif',
                "mono": '"Consolas", "Cascadia Mono", ui-monospace, monospace',
            },
            "groups": [
                {"name": "Interface", "family": "sans", "styles": [
                    _style("brand", 14, 700, usage="The header's RYOS wordmark and bolt (Segoe UI 14 bold). The only type this large in the app."),
                    _style("title", 11, 700, usage="Card names in ScrollingLabel, and dialog section headings (Segoe UI 11 bold)."),
                    _style("control", 10, usage="GroupTab labels, search and quick-run entries, card gutter glyphs, menu entries (Segoe UI 10)."),
                    _style("control-strong", 10, 700, usage="The active GroupTab's label (Segoe UI 10 bold)."),
                    _style("body", 9, usage="Dialog body copy, form labels, the SelectBar hint (Segoe UI 9). The app's workhorse size."),
                    _style("button", 9, 700, usage="Every FlatButton label (Segoe UI 9 bold)."),
                    _style("meta", 8, usage="Script paths, last-run timestamps, the StatusBar, tooltips (Segoe UI 8)."),
                    _style("badge", 8, 700, usage="StatusBadge and ScriptTypeBadge text (Segoe UI 8 bold). Always on a filled ground."),
                    _style("meta-italic", 8, italic=True, usage="Empty-state and placeholder notes in dialogs (Segoe UI 8 italic)."),
                    _style("micro", 7, usage="Densest annotations in the pipeline step editor (Segoe UI 7). Do not go smaller."),
                ]},
                {"name": "Terminal", "family": "mono", "styles": [
                    _style("terminal", 10, usage="Output panel body -- stdout, stderr and status lines (Consolas 10)."),
                    _style("terminal-compact", 9, usage="Output search field and the pipeline step command preview (Consolas 9)."),
                    _style("terminal-meta", 8, usage="The output search match counter (Consolas 8)."),
                ]},
            ],
        },
        "spacing": {
            "note": ("Tk padx/pady values as the code passes them. There is no 4px or "
                     "8px grid: these are the eleven steps actually in use, ordered by size."),
            "tokens": [
                {"name": "space-1", "value": "1px", "usage": "Tab wrapper inset that draws a tab's border, and the 1px frame around a HoverPreview."},
                {"name": "space-2", "value": "2px", "usage": "Gap under a card's name row; compact-card row padding."},
                {"name": "space-3", "value": "3px", "usage": "Gap between GroupTabs; tooltip vertical padding; small-card row padding."},
                {"name": "space-4", "value": "4px", "usage": "StatusBar vertical padding, card row padding at medium size, Entry border inset."},
                {"name": "space-5", "value": "5px", "usage": "Badge horizontal padding, FlatButton vertical padding."},
                {"name": "space-6", "value": "6px", "usage": "Gap between header buttons, tooltip horizontal padding, GroupTab vertical padding."},
                {"name": "space-8", "value": "8px", "usage": "Gap beside the options button; quick-run entry left inset."},
                {"name": "space-10", "value": "10px", "usage": "StatusBar horizontal padding; compact-card horizontal padding; output header inset."},
                {"name": "space-12", "value": "12px", "usage": "Card body horizontal padding at every size, FlatButton horizontal padding, search bar inset."},
                {"name": "space-14", "value": "14px", "usage": "GroupTab horizontal padding, SelectBar text inset, header vertical padding."},
                {"name": "space-16", "value": "16px", "usage": "Dialog section padding -- the most common value in the dialogs module."},
                {"name": "space-18", "value": "18px", "usage": "AppHeader horizontal padding, setting the window's outer margin."},
            ],
        },
        "radius": {
            "note": ("RYOS is square. Tk frames have no corner radius and the app never "
                     "fakes one; the single exception is the application icon, whose "
                     "rounded rectangle is drawn at 24% of its canvas."),
            "tokens": [
                {"name": "radius-none", "value": "0", "usage": "Every card, button, badge, tab, banner, tooltip and panel. Separation comes from a hairline and a fill, never a corner."},
                {"name": "radius-icon", "value": "24%", "usage": "The application icon's rounded rectangle only (make_icon.py). Not a UI value."},
            ],
        },
        "size": {
            "note": "Structural line weights and fixed widths, in px.",
            "tokens": [
                {"name": "hairline", "value": "1px", "usage": "Card border, tooltip border, SelectBar border, and the separators between a card's gutter buttons."},
                {"name": "rail", "value": "5px", "usage": "The coloured strip down a card's left edge: accent on a ScriptCard, pipe_accent on a PipelineCard."},
                {"name": "tab-indicator", "value": "3px", "usage": "The bar under a GroupTab -- accent when active, tab_inactive_bg when not."},
                {"name": "sash", "value": "4px", "usage": "The PanedWindow sash between the card list and the output panel, gripless."},
                {"name": "scrollbar-arrow", "value": "12px", "usage": "ttk scrollbar and Combobox arrow size."},
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
            "tokens": ["ryos/themes.py", "ryos/ui/theme.py", "ryos/interpreter.py",
                       "ryos/presets/*.json", "theme-gallery/*.json"],
            "fonts": [],
            "assets": ["icon.ico", "make_icon.py"],
            "docs": ["README.md", "CLAUDE.md", "docs/ARCHITECTURE.md", "theme-gallery/"],
        },
        "components": {
            "ScriptCard": "ryos/ui/cards.py", "PipelineCard": "ryos/ui/cards.py",
            "FlatButton": "ryos/ui/theme.py", "IconButton": "ryos/ui/cards.py",
            "RunButton": "ryos/ui/cards.py", "StatusBadge": "ryos/ui/cards.py",
            "ScriptTypeBadge": "ryos/interpreter.py", "LabelHighlight": "ryos/ui/theme.py",
            "Tooltip": "ryos/ui/widgets.py", "AppHeader": "ryos/ui/app.py",
            "GroupTab": "ryos/ui/app.py", "SelectBar": "ryos/ui/app.py",
            "StatusBar": "ryos/ui/app.py", "SearchField": "ryos/ui/app.py",
            "QuickRunBar": "ryos/ui/app.py", "FormControls": "ryos/ui/theme.py",
            "OutputPanel": "ryos/ui/app.py",
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

# (fg, bg, floor, where it appears). WCAG 2 asks 4.5:1 of body text and 3:1 of
# text at 24px+ / bold 19px+ and of non-text marks that carry meaning. Nothing
# in RYOS is large text -- the biggest is the 19px wordmark -- so the only 3:1
# rows here are marks: the card rail and the tab indicator.
AUDIT_PAIRS: list[tuple[str, str, float, str]] = [
    ("name_fg", "bg", 4.5, "card names on the window ground"),
    ("name_fg", "card_bg", 4.5, "card names"),
    ("name_fg", "card_hover", 4.5, "card names under the pointer"),
    ("path_fg", "bg", 4.5, "the search glyph and group counts"),
    ("path_fg", "card_bg", 4.5, "script paths and last-run timestamps"),
    ("tab_fg", "tab_inactive_bg", 4.5, "inactive GroupTab labels"),
    ("fg_on_dark", "header_bg", 4.5, "the wordmark and header text"),
    ("fg_on_dark", "accent", 4.5, "create-button labels"),
    ("fg_on_dark", "ok", 4.5, "the OK badge"),
    ("fg_on_dark", "pipe_accent", 4.5, "the SCHEDULED badge"),
    ("btn_fg", "btn_run_bg", 4.5, "the Run glyph and Run Selected"),
    ("btn_fg", "error", 4.5, "the Failed badge and the retry glyph"),
    ("btn_neutral_fg", "btn_neutral_bg", 4.5, "card gutter glyphs"),
    ("warn_fg", "warn_bg", 4.5, "the SelectBar hint"),
    ("out_stdout", "out_bg", 4.5, "stdout"),
    ("out_stderr", "out_bg", 4.5, "stderr"),
    ("out_status", "out_bg", 4.5, "runner status lines"),
    ("out_success", "out_bg", 4.5, "clean-exit lines"),
    ("accent", "card_bg", 3.0, "the 5px card rail and the 3px tab indicator"),
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
        current = path.read_bytes() if path.exists() else None
        if current == blob:
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
