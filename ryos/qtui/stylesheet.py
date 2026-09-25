"""Turn a RYOS palette into a Qt stylesheet.

This is the Qt half of what `ryos/ui/theme.py` does by hand. The Tk layer
propagates the ``C`` dict to every widget at construction, so re-theming means
walking and rebuilding the whole tree; Qt reads one stylesheet, so a theme
change is a single `setStyleSheet` call.

The generator is a **pure function of the palette** — no Qt import, no widget,
no display — so it is unit-testable exactly like `themes.build_palette()`,
which is what produces its input. Importing this module does not require
PySide6 to be installed.

Object names used by the app are addressed as ``#objectName``; everything else
is styled by Qt class. Keep selectors in the same order as the palette groups
they draw from, so a missing key is easy to spot.
"""

from __future__ import annotations

from pathlib import Path

from ..themes import (INK_LIGHT_POLE, REFERENCE, _readable_on, contrast_ratio,
                      ink_on)


#: Text needs 4.5:1 against its fill (WCAG AA); a glyph or a large
#: selected-tab label needs 3:1.
TEXT_MIN, GLYPH_MIN = 4.5, 3.0


def _legible(fg: str, *fills: str, floor: float = TEXT_MIN) -> str:
    """The theme's own colour when it reads on every fill, else the better of
    black and white. Most themes keep their colours; a few needed rescuing."""
    if all(contrast_ratio(fg, f) >= floor for f in fills):
        return fg
    return ink_on(*fills)


def drawn_colors(c: dict) -> dict:
    """Text colours the stylesheet draws where the palette's own key does not
    always read. Measured across the shipped themes: white on Nord's pale
    accent was 2.0:1, and tooltips drew the dark body text on a dark tooltip
    in every light theme (about 1.2:1)."""
    # Idle and hover are judged apart: on a mid-tone accent (Ocean Depths'
    # teal) neither black nor white clears 4.5:1 on both at once, but one of
    # them always does on each.
    return {
        "primary_fg": _legible(c["btn_fg"], c["accent"]),
        "primary_hover_fg": _legible(c["btn_fg"], c["accent2"]),
        "neutral_fg": _legible(c["btn_neutral_fg"], c["btn_neutral_bg"]),
        "neutral_hover_fg": _legible(c["btn_neutral_fg"], c["btn_neutral_hover"]),
        "tooltip_fg": _legible(c["name_fg"], c["tooltip_bg"]),
        "status_fg": _legible(c["path_fg"], c["status_bg"]),
        "tab_selected_fg": _legible(c["accent"], c["card_bg"], floor=GLYPH_MIN),
        # Gold stays gold, shaded until it reads on the wash.
        "star": _readable_on(c.get("bolt", "#FFD23F"), (c["accent_wash"],)),
    }


#: (colour from drawn_colors, the fills it sits on, minimum) -- for the tests.
DRAWN_PAIRS = (
    ("primary_fg", ("accent",), TEXT_MIN),
    ("primary_hover_fg", ("accent2",), TEXT_MIN),
    ("neutral_fg", ("btn_neutral_bg",), TEXT_MIN),
    ("neutral_hover_fg", ("btn_neutral_hover",), TEXT_MIN),
    ("tooltip_fg", ("tooltip_bg",), TEXT_MIN),
    ("status_fg", ("status_bg",), TEXT_MIN),
    ("tab_selected_fg", ("card_bg",), GLYPH_MIN),
    ("star", ("accent_wash",), GLYPH_MIN),
)


def icon_path(name: str) -> str:
    """Where an image the stylesheet draws lives, as Qt's url() wants it.

    Beside this module, from source and in the build alike: setup_cxfreeze.py
    copies the folder to the same place, as it does the theme presets.
    """
    return (Path(__file__).resolve().parent / "icons" / name).as_posix()

# Every palette key this module reads. Checked against the palette up front so
# a missing one is a clear error here rather than a literal "None" appearing in
# the generated CSS and silently rendering as a broken colour.
REQUIRED_KEYS = (
    "bg", "card_bg", "card_hover", "border", "header_bg", "status_bg",
    "accent", "accent2", "accent_wash",
    "name_fg", "path_fg", "tab_fg",
    "btn_fg", "btn_neutral_bg", "btn_neutral_hover", "btn_neutral_fg",
    "btn_dark_bg", "btn_dark_hover",
    "btn_run_bg", "btn_run_hover", "btn_run_fg",
    "btn_stop_idle", "btn_stop_idle_hover", "btn_stop_idle_fg",
    "btn_disabled_bg", "btn_disabled_fg",
    "tab_inactive_bg", "tab_inactive_hover",
    "out_bg", "out_stdout", "out_stderr", "out_tabbar",
    "tooltip_bg", "tooltip_border",
    "error", "ok", "running",
    "menu_bg", "fg_on_dark",
    "warn_bg", "warn_border", "warn_fg",
)


class MissingPaletteKeys(KeyError):
    """A palette did not carry everything the stylesheet needs."""


def missing_keys(palette: dict) -> list[str]:
    """Which required keys ``palette`` lacks, in REQUIRED_KEYS order."""
    return [k for k in REQUIRED_KEYS if k not in palette]


def stylesheet(palette: dict) -> str:
    """The full Qt stylesheet for ``palette``.

    Raises ``MissingPaletteKeys`` rather than emitting CSS with holes in it:
    an unstyled widget inherits whatever Qt's default theme does, which on a
    dark palette means black text on a dark background — legible enough in a
    screenshot to miss, and unreadable in use.
    """
    gaps = missing_keys(palette)
    if gaps:
        raise MissingPaletteKeys(
            f"palette is missing {len(gaps)} key(s) the stylesheet needs: "
            f"{', '.join(gaps)}")
    c = palette
    d = drawn_colors(c)
    tick = icon_path("check-light.svg" if ink_on(c["accent"]) == INK_LIGHT_POLE
                     else "check-dark.svg")
    return f"""
/* --- surfaces ------------------------------------------------------- */
QWidget {{
    background: {c['bg']};
    color: {c['name_fg']};
    font-family: "Segoe UI";
    font-size: 10pt;
}}
QMainWindow, QDialog {{ background: {c['bg']}; }}

/* --- cards ---------------------------------------------------------- */
QFrame#card {{
    background: {c['card_bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
}}
QFrame#card:hover {{ background: {c['card_hover']}; }}
/* The coloured edge Tk cards have: the accent for a script, the pipeline
   accent for a pipeline, so the two kinds tell apart at a glance. */
QFrame#card {{ border-left: 4px solid {c['accent']}; }}
QFrame#card[kind="pipeline"] {{ border-left: 4px solid {c.get('pipe_accent', c['accent'])}; }}
QLabel#cardName {{ color: {c['name_fg']}; font-weight: 600; }}
/* The name is a ScrollingLabel, not a QLabel: without this it was not bold. */
QWidget#cardName {{ font-weight: 600; }}
/* Text on a card sits on the card, not in a box of the window colour. */
QFrame#card QLabel, QFrame#card #cardName {{ background: transparent; }}
/* The empty column on a pipeline card is a gap in the card (#7). */
QWidget#cardSpacer {{ background: transparent; }}
QLabel#cardPath {{ color: {c['path_fg']}; font-size: 9pt; }}

/* --- buttons -------------------------------------------------------- */
QPushButton {{
    background: {c['btn_neutral_bg']};
    color: {d['neutral_fg']};
    border: none;
    border-radius: 3px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: {c['btn_neutral_hover']}; color: {d['neutral_hover_fg']}; }}
QPushButton:disabled {{
    background: {c['btn_disabled_bg']};
    color: {c['btn_disabled_fg']};
}}
QPushButton#run {{ background: {c['btn_run_bg']}; color: {c['btn_run_fg']}; }}
QPushButton#run:hover {{ background: {c['btn_run_hover']}; }}
QPushButton#stop {{ background: {c['btn_stop_idle']}; color: {c['btn_stop_idle_fg']}; }}
QPushButton#stop:hover {{ background: {c['btn_stop_idle_hover']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {d['primary_fg']}; }}
QPushButton#primary:hover {{ background: {c['accent2']}; color: {d['primary_hover_fg']}; }}
QPushButton#dark {{ background: {c['btn_dark_bg']}; color: {c['btn_fg']}; }}
QPushButton#dark:hover {{ background: {c['btn_dark_hover']}; }}
/* A card's button strip holds glyphs, not words (▶ ↻ ★ ⚙ ▸+): at the body
   size they drew a few pixels tall, and ↻ -- the retry -- was hard to make
   out. Tk draws them larger too. */
QFrame#card QPushButton {{ font-size: 13pt; padding: 2px 0; }}
/* A favourite's star is gold on the accent wash, as in Tk. */
QFrame#card QPushButton#favOn {{
    color: {d['star']}; background: {c['accent_wash']};
}}

/* --- group tabs ----------------------------------------------------- */
QTabWidget::pane {{ border: 1px solid {c['border']}; background: {c['card_bg']}; }}
QTabBar::tab {{
    background: {c['tab_inactive_bg']};
    color: {c['tab_fg']};
    padding: 6px 14px;
    border: none;
}}
QTabBar::tab:hover {{ background: {c['tab_inactive_hover']}; }}
QTabBar::tab:selected {{
    background: {c['card_bg']};
    color: {d['tab_selected_fg']};
    font-weight: 600;
    border-bottom: 2px solid {c['accent']};
}}

/* --- output panel --------------------------------------------------- */
QPlainTextEdit#output, QTextEdit#output {{
    background: {c['out_bg']};
    color: {c['out_stdout']};
    border: none;
    font-family: Consolas, "Courier New", monospace;
}}
QTabBar#outputTabs::tab {{ background: {c['out_tabbar']}; }}

/* --- inputs --------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {c['card_bg']};
    color: {c['name_fg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: {c['accent']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}
/* Lists (the script dialog's presets, the pipeline editor's steps) show
   their edge even when empty, so they read as a place to put things. */
QListView {{
    background: {c['card_bg']};
    color: {c['name_fg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
}}
/* A check box reads as a box whether ticked or not, on every theme. */
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {c['path_fg']};
    background: {c['card_bg']};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
/* Ticked: the accent, with a tick in whichever ink reads on it. A chosen
   radio button: a dot of the accent in the box's own colour. */
QCheckBox::indicator:checked {{
    background: {c['accent']}; border: 1px solid {c['accent']};
    image: url("{tick}");
}}
QRadioButton::indicator:checked {{
    border: 1px solid {c['accent']};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {c['accent']}, stop:0.55 {c['accent']},
        stop:0.62 {c['card_bg']}, stop:1 {c['card_bg']});
}}

/* --- chrome --------------------------------------------------------- */
QHeaderView::section {{ background: {c['header_bg']}; color: {c['name_fg']}; border: none; padding: 4px; }}
QStatusBar {{ background: {c['status_bg']}; color: {d['status_fg']}; }}
QToolTip {{
    background: {c['tooltip_bg']};
    color: {d['tooltip_fg']};
    border: 1px solid {c['tooltip_border']};
    padding: 4px;
}}
QScrollBar:vertical {{ background: {c['bg']}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 6px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['accent_wash']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
/* The track either side of the handle: left unstyled, Qt fills it with a
   dotted hatch. */
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* --- update banner ------------------------------------------------- */
QFrame#updateBanner {{
    background: {c['accent_wash']};
    border: 1px solid {c['accent']};
}}
QFrame#updateBanner QLabel {{ background: transparent; color: {c['name_fg']}; }}

/* --- hover preview and steps popup ------------------------------- */
QFrame#hoverPreview {{ background: {c['card_bg']}; border: 1px solid {c['border']}; }}

/* --- group banner -------------------------------------------------- */
QLabel#groupBanner, QLabel#groupBannerEmpty {{
    background: {c['card_bg']};
    border: 1px solid {c['border']};
    text-align: left;
    padding: 8px 10px;
}}
QLabel#groupBanner {{ color: {c['name_fg']}; }}
QLabel#groupBannerEmpty {{ color: {c['path_fg']}; }}
QLabel#groupBanner:hover, QLabel#groupBannerEmpty:hover {{
    background: {c['card_hover']};
}}

/* --- sections ------------------------------------------------------ */
QPushButton#sectionHeader {{
    background: transparent;
    color: {c['path_fg']};
    font-size: 8pt;
    font-weight: 700;
    text-align: left;
    padding: 6px 2px 2px 2px;
    border: none;
    border-bottom: 1px solid {c['border']};
    border-radius: 0;
}}
QPushButton#sectionHeader:hover {{ color: {c['name_fg']}; }}
QLabel#groupHeader {{ color: {c['path_fg']}; font-size: 8pt; font-weight: 700; padding: 14px 0 2px 0; }}

/* --- select mode --------------------------------------------------- */
QFrame#selectBar {{
    background: {c['warn_bg']};
    border: 1px solid {c['warn_border']};
}}
QFrame#selectBar QLabel {{ background: transparent; color: {c['warn_fg']}; }}

/* --- context menus ------------------------------------------------- */
QMenu {{
    background: {c['menu_bg']};
    color: {c['fg_on_dark']};
    border: 1px solid {c['border']};
    padding: 4px 0;
}}
QMenu::item {{ padding: 5px 22px 5px 12px; background: transparent; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['fg_on_dark']}; }}
QMenu::item:disabled {{ color: {c['btn_disabled_fg']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}

/* --- drag and drop ------------------------------------------------- */
QFrame#dropIndicator {{ background: {c['accent']}; border: none; }}

/* --- status colours ------------------------------------------------- */
QLabel#statusOk {{ color: {c['ok']}; }}
QLabel#statusError {{ color: {c['error']}; }}
QLabel#statusRunning {{ color: {c['running']}; }}
""".strip() + "\n"


def stylesheet_for(theme_name: str) -> str:
    """The stylesheet for one of the built-in reference palettes."""
    if theme_name not in REFERENCE:
        raise KeyError(f"unknown theme {theme_name!r}; "
                       f"have {sorted(REFERENCE)}")
    return stylesheet(REFERENCE[theme_name])
