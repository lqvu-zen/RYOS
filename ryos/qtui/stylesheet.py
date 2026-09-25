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

from ..themes import REFERENCE

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
QLabel#cardName {{ color: {c['name_fg']}; font-weight: 600; }}
QLabel#cardPath {{ color: {c['path_fg']}; font-size: 9pt; }}

/* --- buttons -------------------------------------------------------- */
QPushButton {{
    background: {c['btn_neutral_bg']};
    color: {c['btn_neutral_fg']};
    border: none;
    border-radius: 3px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: {c['btn_neutral_hover']}; }}
QPushButton:disabled {{
    background: {c['btn_disabled_bg']};
    color: {c['btn_disabled_fg']};
}}
QPushButton#run {{ background: {c['btn_run_bg']}; color: {c['btn_run_fg']}; }}
QPushButton#run:hover {{ background: {c['btn_run_hover']}; }}
QPushButton#stop {{ background: {c['btn_stop_idle']}; color: {c['btn_stop_idle_fg']}; }}
QPushButton#stop:hover {{ background: {c['btn_stop_idle_hover']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['btn_fg']}; }}
QPushButton#primary:hover {{ background: {c['accent2']}; }}
QPushButton#dark {{ background: {c['btn_dark_bg']}; color: {c['btn_fg']}; }}
QPushButton#dark:hover {{ background: {c['btn_dark_hover']}; }}

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
    color: {c['accent']};
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

/* --- chrome --------------------------------------------------------- */
QHeaderView::section {{ background: {c['header_bg']}; color: {c['name_fg']}; border: none; padding: 4px; }}
QStatusBar {{ background: {c['status_bg']}; color: {c['path_fg']}; }}
QToolTip {{
    background: {c['tooltip_bg']};
    color: {c['name_fg']};
    border: 1px solid {c['tooltip_border']};
    padding: 4px;
}}
QScrollBar:vertical {{ background: {c['bg']}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 6px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['accent_wash']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

/* --- update banner ------------------------------------------------- */
QFrame#updateBanner {{
    background: {c['accent_wash']};
    border: 1px solid {c['accent']};
}}
QFrame#updateBanner QLabel {{ background: transparent; color: {c['name_fg']}; }}

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
