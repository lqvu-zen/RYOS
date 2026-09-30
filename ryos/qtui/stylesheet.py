"""Turn a RYOS palette into a Qt stylesheet.

Qt reads one stylesheet, so a theme change is a single `setStyleSheet`
call rather than a walk over every widget.

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

from ..themes import (INK_LIGHT_POLE, REFERENCE, _mix, _readable_on,
                      _rel_luminance, _shade, contrast_ratio, ink_on)


#: Text needs 4.5:1 against its fill (WCAG AA); a glyph or a large
#: selected-tab label needs 3:1. A control's edge only has to show.
TEXT_MIN, GLYPH_MIN, EDGE_MIN = 4.5, 3.0, 1.6


def _edge(start: str, *surfaces: str, floor: float = EDGE_MIN) -> str:
    """``start`` shaded away from ``surfaces`` until it shows on all of them."""
    step = -0.06 if _rel_luminance(surfaces[0]) > 0.45 else 0.06
    cur = start
    for _ in range(30):
        if all(contrast_ratio(cur, s) >= floor for s in surfaces):
            break
        cur = _shade(cur, step)
    return cur


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
        "stop_fg": _legible(c["fg_on_dark"], c["btn_stop_active"],
                            c["btn_stop_active_hover"]),
        # Paths, hints, captions: the theme's muted colour, shaded only as
        # far as it takes to read on a row, a hovered row and the window.
        # Kept as a shade rather than _legible's black or white, so it stays
        # muted; two Solarized themes were at 4.1 and 4.2 to 1.
        "muted_fg": _readable_on(c["path_fg"], (c["card_bg"], c["card_hover"], c["bg"])),
        "tab_selected_fg": _legible(c["accent"], c["card_bg"], floor=GLYPH_MIN),
        # Gold stays gold, shaded until it reads on a row, hovered or not.
        "star": _readable_on(c.get("bolt", "#FFD23F"),
                             (c["card_bg"], c["card_hover"], c["accent_wash"])),
        # The header bar is the theme's header colour, which is dark in most
        # themes and pale in a few; its words and menus follow it.
        "header_fg": _legible(c["fg_on_dark"], c["header_bg"]),
        # A group pill: the chosen one is the body text colour, filled, with
        # the window colour for ink; the others are muted words on the window.
        "pill_fg": _legible(c["bg"], c["name_fg"]),
        "pill_idle_fg": _legible(c["path_fg"], c["bg"], c["tab_inactive_hover"]),
        # A neutral button's outline. In Light its fill is 1.01:1 against the
        # window, so without an edge Save and Cancel read as plain text.
        "control_edge": _edge(c["border"], c["bg"], c["card_bg"]),
    }


#: (colour from drawn_colors, the fills it sits on, minimum) -- for the tests.
DRAWN_PAIRS = (
    ("primary_fg", ("accent",), TEXT_MIN),
    ("primary_hover_fg", ("accent2",), TEXT_MIN),
    ("neutral_fg", ("btn_neutral_bg",), TEXT_MIN),
    ("neutral_hover_fg", ("btn_neutral_hover",), TEXT_MIN),
    ("tooltip_fg", ("tooltip_bg",), TEXT_MIN),
    ("status_fg", ("status_bg",), TEXT_MIN),
    ("stop_fg", ("btn_stop_active", "btn_stop_active_hover"), TEXT_MIN),
    ("muted_fg", ("card_bg", "card_hover", "bg"), TEXT_MIN),
    ("tab_selected_fg", ("card_bg",), GLYPH_MIN),
    ("star", ("card_bg", "card_hover", "accent_wash"), GLYPH_MIN),
    ("header_fg", ("header_bg",), TEXT_MIN),
    ("pill_fg", ("name_fg",), TEXT_MIN),
    ("pill_idle_fg", ("bg", "tab_inactive_hover"), TEXT_MIN),
    ("control_edge", ("bg", "card_bg"), EDGE_MIN),
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
    "btn_stop_active", "btn_stop_active_hover",
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
    # Chevrons in the field's own ink: dark on a light field, light on dark.
    ink = "dark" if _rel_luminance(c["card_bg"]) > 0.45 else "light"
    chevron_down = icon_path(f"chevron-down-{ink}.svg")
    chevron_up = icon_path(f"chevron-up-{ink}.svg")
    # A header button under the pointer: the header lifted toward its ink.
    header_hover = _mix(c["header_bg"], d["header_fg"], 0.14)
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
/* A section is one panel, and each card a row of it: no box of its own,
   split from the next by a hairline. */
QWidget#sectionPanel {{
    background: {c['card_bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
}}
QFrame#card {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {c['border']};
    border-radius: 0;
}}
QFrame#card[last="true"] {{ border-bottom: none; }}
QFrame#card:hover {{ background: {c['card_hover']}; }}
/* The coloured edge Tk cards have: the accent for a script, the pipeline
   accent for a pipeline, so the two kinds tell apart at a glance. */
QFrame#card {{ border-left: 3px solid {c['accent']}; }}
QFrame#card[kind="pipeline"] {{ border-left: 3px solid {c.get('pipe_accent', c['accent'])}; }}
/* A favourite is a chip in the strip above the lists: a pill of its own,
   not a row of a panel. After the edge rules above, which it replaces. */
QWidget#sectionPanel[flow="true"] {{ background: transparent; border: none; }}
QFrame#card[chip="true"] {{
    background: {c['card_bg']};
    border: 1px solid {c['border']};
    /* Half its height: Run (24) + padding (6) + the edge (2). */
    border-radius: 16px;
}}
QFrame#card[chip="true"]:hover {{ background: {c['card_hover']}; }}
QLabel#cardName {{ color: {c['name_fg']}; font-weight: 600; }}
/* The name is a ScrollingLabel, not a QLabel: without this it was not bold. */
QWidget#cardName {{ font-weight: 700; font-size: 11pt; }}
QFrame#card[compact="true"] QWidget#cardName {{ font-weight: 600; font-size: 10pt; }}
/* Text on a card sits on the card, not in a box of the window colour. */
QFrame#card QLabel, QFrame#card #cardName {{ background: transparent; }}
/* The empty column on a pipeline card is a gap in the card (#7). */
QWidget#cardSpacer {{ background: transparent; }}
QLabel#cardPath {{ color: {d['muted_fg']}; font-size: 9pt; }}

/* --- buttons -------------------------------------------------------- */
QPushButton {{
    background: {c['btn_neutral_bg']};
    color: {d['neutral_fg']};
    border: 1px solid {d['control_edge']};
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
/* Stop is only on screen while something runs (the Running list), so it is
   always the live red: in the idle grey it read as a disabled button. */
QPushButton#stop {{ background: {c['btn_stop_active']}; color: {d['stop_fg']}; }}
QPushButton#stop:hover {{ background: {c['btn_stop_active_hover']}; color: {d['stop_fg']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {d['primary_fg']}; }}
QPushButton#primary:hover {{ background: {c['accent2']}; color: {d['primary_hover_fg']}; }}
QPushButton#dark {{ background: {c['btn_dark_bg']}; color: {c['btn_fg']}; }}
QPushButton#dark:hover {{ background: {c['btn_dark_hover']}; }}
/* A dialog's default button (Save, OK) is its primary action, as + Script is
   the window's; it follows focus between a dialog's buttons, as on Windows. */
QPushButton:default {{ background: {c['accent']}; color: {d['primary_fg']}; }}
QPushButton:default:hover {{ background: {c['accent2']}; color: {d['primary_hover_fg']}; }}
QPushButton:default:disabled {{
    background: {c['btn_disabled_bg']}; color: {c['btn_disabled_fg']};
}}
/* Filled buttons say what they are with the fill; the edge is for neutral ones. */
QPushButton#run, QPushButton#stop, QPushButton#primary, QPushButton#dark,
QPushButton:default {{ border: none; }}
/* A quiet button anywhere: an icon or a word, boxed only under the pointer
   (Quick Run's close, the update banner's dismiss). Icons come from the one
   drawn set in qtui/icons.py, tinted from the palette -- never a font glyph
   or an emoji, which each draw in their own style and colour. */
QPushButton#quiet {{
    background: transparent; border: none; color: {d['muted_fg']};
    border-radius: 4px; padding: 4px 8px; min-height: 24px;
}}
QPushButton#quiet:hover {{ background: {c['accent_wash']}; color: {c['name_fg']}; }}
/* Quiet: an icon in the muted ink, boxed only under the pointer, so Run --
   round and filled -- is the one thing on the row that looks pressable. */
QFrame#card QPushButton {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px 0;
    min-height: 28px;
}}
QFrame#card QPushButton:hover {{ background: {c['accent_wash']}; }}
QFrame#card QPushButton#run {{ padding: 0; }}
QFrame#card[compact="true"] QPushButton {{ min-height: 24px; }}
/* The preset Run will pass, on a row's second line: a word to click, not
   a drop-down box. */
QFrame#card QPushButton#paramPick {{
    background: transparent;
    color: {d['tab_selected_fg']};
    border: none;
    border-radius: 3px;
    /* A 24 px target, though it reads as a word (WCAG 2.5.8). */
    min-height: 24px;
    padding: 0 6px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 9pt;
}}
QFrame#card QPushButton#paramPick:hover {{ background: {c['accent_wash']}; }}

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
/* The group tabs are pills on the window, with no frame round the page:
   the section panels are the page. */
QTabWidget#groupTabs::pane {{ border: none; background: transparent; }}
QTabWidget#groupTabs::tab-bar {{ left: 0; }}
QTabBar#groupTabBar::tab {{
    background: transparent;
    color: {d['pill_idle_fg']};
    border: none;
    border-radius: 14px;
    padding: 5px 14px;
    margin: 0 4px 8px 0;
    font-weight: 600;
}}
QTabBar#groupTabBar::tab:hover {{ background: {c['tab_inactive_hover']}; }}
/* All comes last: the gap before it holds the + for a new group, which
   belongs with the groups. */
QTabBar#groupTabBar::tab:last {{ margin-left: 34px; }}
QTabBar#groupTabBar::tab:selected {{
    background: {c['name_fg']};
    color: {d['pill_fg']};
    font-weight: 700;
    border: none;
}}
QPushButton#newGroupPill {{
    background: transparent;
    color: {d['pill_idle_fg']};
    border: 1px dashed {d['control_edge']};
    border-radius: 13px;
    padding: 0;
    font-size: 13pt;
    min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
}}
QPushButton#newGroupPill:hover {{ background: {c['tab_inactive_hover']}; }}

/* --- output panel --------------------------------------------------- */
QPlainTextEdit#output, QTextEdit#output {{
    background: {c['out_bg']};
    color: {c['out_stdout']};
    border: none;
    font-family: Consolas, "Courier New", monospace;
}}
/* The output header's buttons are words, like the header bar's. */
QFrame#outputHeader QPushButton {{
    background: transparent;
    border: none;
    color: {d['tab_selected_fg']};
    font-weight: 600;
    padding: 3px 8px;
}}
QFrame#outputHeader QPushButton:hover {{ background: {c['accent_wash']}; }}
/* A tab per run, as small pills over the terminal. */
QTabWidget#outputTabs::pane {{ border: none; }}
QTabWidget#outputTabs QTabBar::tab {{
    background: transparent;
    color: {d['pill_idle_fg']};
    border: none;
    border-radius: 11px;
    padding: 3px 10px;
    margin: 4px 2px 6px 0;
    font-weight: 600;
}}
QTabWidget#outputTabs QTabBar::tab:hover {{ background: {c['tab_inactive_hover']}; }}
QTabWidget#outputTabs QTabBar::tab:selected {{
    background: {c['name_fg']};
    color: {d['pill_fg']};
    border: none;
}}
/* Typed into, so it looks like the other fields -- not like the terminal. */
QPlainTextEdit#envEdit {{
    background: {c['card_bg']};
    color: {c['name_fg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
    font-family: Consolas, "Courier New", monospace;
}}

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
/* The arrows: a thin chevron in the field, not Qt's own boxed button --
   drawn with a heavy dark bar in Light and white boxes in Dark, they read as
   a rendering fault among hairlined panels. */
QComboBox {{ padding-right: 22px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 22px; border: none; background: transparent;
}}
QComboBox::down-arrow {{ image: url("{chevron_down}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {c['card_bg']};
    color: {c['name_fg']};
    border: 1px solid {c['border']};
    selection-background-color: {c['accent_wash']};
    selection-color: {c['name_fg']};
}}
QAbstractSpinBox {{ padding-right: 20px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 20px; border: none; background: transparent;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: {c['accent_wash']};
}}
QAbstractSpinBox::up-arrow {{ image: url("{chevron_up}"); width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: url("{chevron_down}"); width: 10px; height: 10px; }}
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
/* Thin, and only the handle drawn: a place to grab, not a grey column. */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0; }}
QScrollBar::handle:vertical {{ background: {d['control_edge']}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['path_fg']}; }}
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

/* --- header bar ----------------------------------------------------- */
/* The theme's header colour, holding the menus and what makes things.
   Its buttons are words; + Script, the one filled, is the main action. */
QFrame#appHeader {{ background: {c['header_bg']}; border: none; }}
QFrame#appHeader QLabel {{ background: transparent; color: {d['header_fg']}; }}
QLabel#appTitle {{ font-size: 13pt; font-weight: 700; }}
QLabel#appBolt {{ color: {c.get('bolt', '#FFD23F')}; font-size: 13pt; }}
QFrame#appHeader QPushButton {{
    background: transparent;
    color: {d['header_fg']};
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    font-weight: 600;
}}
QFrame#appHeader QPushButton:hover {{ background: {header_hover}; }}
QFrame#appHeader QPushButton#primary {{ background: {c['accent']}; color: {d['primary_fg']}; }}
QFrame#appHeader QPushButton#primary:hover {{
    background: {c['accent2']}; color: {d['primary_hover_fg']};
}}
QMenuBar#appMenu {{ background: transparent; color: {d['header_fg']}; }}
QMenuBar#appMenu::item {{ background: transparent; padding: 4px 8px; border-radius: 4px; }}
QMenuBar#appMenu::item:selected, QMenuBar#appMenu::item:pressed {{
    background: {header_hover};
}}

/* --- group banner -------------------------------------------------- */
/* The group's folder: a line of muted text over the sections, which
   opens the folder dialog when clicked -- not a box of its own. */
QLabel#groupBanner, QLabel#groupBannerEmpty {{
    background: transparent;
    border: none;
    color: {d['muted_fg']};
    font-size: 9pt;
    padding: 2px 2px;
}}
QLabel#groupBanner:hover, QLabel#groupBannerEmpty:hover {{ color: {c['name_fg']}; }}
QPushButton#quickRunToggle {{
    background: transparent;
    border: none;
    color: {d['tab_selected_fg']};
    font-weight: 600;
    padding: 2px 6px;
    min-height: 24px;
}}
QPushButton#quickRunToggle:hover {{ background: {c['accent_wash']}; }}

/* --- sections ------------------------------------------------------ */
QPushButton#sectionHeader {{
    background: transparent;
    color: {d['muted_fg']};
    font-size: 8pt;
    font-weight: 700;
    text-align: left;
    padding: 10px 2px 4px 2px;
    border: none;
    border-radius: 0;
}}
QPushButton#sectionHeader:hover {{ color: {c['name_fg']}; }}
QLabel#groupHeader {{ color: {d['muted_fg']}; font-size: 8pt; font-weight: 700; padding: 14px 0 2px 0; }}

/* --- the maximised layout: the chosen row and the detail pane ------- */
QFrame#card[selected="true"] {{ background: {c['accent_wash']}; }}
QLabel#detailName, QWidget#detailName {{ font-size: 16pt; font-weight: 700; }}
QLabel#detailHeading {{
    color: {d['muted_fg']}; font-size: 8pt; font-weight: 700; letter-spacing: 0.8px;
}}
QPushButton#detailLink, QPushButton#detailStar {{
    background: transparent;
    border: none;
    border-radius: 4px;
    color: {d['tab_selected_fg']};
    font-weight: 600;
    padding: 7px 12px;
}}
QPushButton#detailLink:hover, QPushButton#detailStar:hover {{
    background: {c['accent_wash']};
}}
QPushButton#detailStar {{ color: {d['muted_fg']}; font-size: 13pt; padding: 2px 8px; }}
QPushButton#detailStar[on="true"] {{ color: {d['star']}; }}
QPushButton#paramChip {{
    background: transparent;
    color: {c['name_fg']};
    border: 1px solid {d['control_edge']};
    /* Qt draws no rounding at all past half the height: keep under it. */
    border-radius: 11px;
    min-height: 16px;
    padding: 3px 12px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 9pt;
}}
QPushButton#paramChip:hover {{ background: {c['card_hover']}; }}
QPushButton#paramChip:checked {{
    background: {c['accent_wash']};
    color: {d['tab_selected_fg']};
    border: 1px solid {c['accent']};
}}
QFrame#stepRow {{ background: transparent; border: none; border-bottom: 1px solid {c['border']}; }}
QFrame#stepRow[last="true"] {{ border-bottom: none; }}
QFrame#stepRow QLabel, QFrame#stepRow QWidget {{ background: transparent; }}
QLabel#factKey, QWidget#factKey {{ color: {d['muted_fg']}; font-size: 9pt; }}
QWidget#factValue {{ font-size: 10pt; }}
QSplitter#outerSplit::handle {{ background: {c['border']}; width: 1px; }}

/* --- keyboard focus ----------------------------------------------- */
/* Styling a button's border removes Qt's own focus frame, so Tab moved
   through dialogs with nothing showing where it was. Neutral buttons take an
   accent edge; quiet ones (rows, header, links) the wash their hover uses. */
QPushButton:focus {{ border: 1px solid {c['accent']}; }}
QPushButton#primary:focus, QPushButton:default:focus {{
    border: 1px solid {d['primary_fg']};
}}
QFrame#card QPushButton:focus, QPushButton#detailLink:focus,
QPushButton#detailStar:focus, QPushButton#quiet:focus,
QPushButton#quickRunToggle:focus, QFrame#outputHeader QPushButton:focus {{
    background: {c['accent_wash']}; border: none;
}}
QFrame#appHeader QPushButton:focus {{ background: {header_hover}; border: none; }}
QFrame#appHeader QPushButton#primary:focus {{
    background: {c['accent2']}; border: 1px solid {d['primary_fg']};
}}

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
