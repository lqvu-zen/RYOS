"""Rules for the custom theme editor, independent of any toolkit.

The editor edits a *seed* — a mode plus seven required colours, with optional
advanced overrides — and `themes.build_palette()` expands it. The colour maths
and `validate_seed` already live in `themes.py`; what lived only inside the Tk
dialog was the naming rule, and which colour an advanced row should show when
nothing has been overridden.
"""

from __future__ import annotations

from . import verdict
from .themes import (BUILTIN_THEMES, SEEDS, THEME_LABELS, build_palette,
                     delete_user_theme, is_hex_color, load_user_themes,
                     save_user_theme, validate_seed)

#: Human labels for each required seed colour, in the order the editor shows
#: them. Shared so the two editors present the same vocabulary.
COLOR_LABELS: dict[str, str] = {
    "bg": "Background",
    "surface": "Cards & dialogs",
    "border": "Borders & dividers",
    "header_bg": "Header bar",
    "accent": "Accent",
    "text": "Primary text",
    "text_muted": "Secondary text",
}


def effective_color(seed: dict, key: str) -> str:
    """What an advanced row should show: the override, or the derived colour.

    An advanced key is optional. With nothing set, the row still shows a
    colour — the one `build_palette` would derive — so the editor never
    displays an empty swatch for a colour the app will nonetheless paint.
    """
    value = seed.get(key)
    if is_hex_color(value):
        # is_hex_color already proved this is a "#rrggbb" string; say so, since
        # a bool-returning guard does not narrow the type on its own.
        return str(value)
    return build_palette(seed)[key]


def is_overridden(seed: dict, key: str) -> bool:
    """Whether an advanced key carries an explicit value rather than a derived one."""
    return is_hex_color(seed.get(key))


def validate(name: str, seed: dict, taken=()) -> verdict.Verdict:
    """Whether this theme can be saved under this name.

    Names are compared case-insensitively: two themes differing only in case
    would be indistinguishable in the picker and would collide on disk on
    Windows.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return verdict.refuse("Theme editor", "Give the theme a name.",
                              verdict.WARNING)
    if cleaned.lower() in {str(t).lower() for t in taken}:
        return verdict.refuse(
            "Theme editor", f"A theme named “{cleaned}” already exists.")
    problems = validate_seed(seed)
    if problems:
        return verdict.refuse(
            "Theme editor", "Fix these first:\n• " + "\n• ".join(problems))
    return verdict.PROCEED


# --- the Appearance tab: which theme, which accent, custom-theme files ----------
# Shared by the Tk options dialog and the Qt appearance dialog. ``customs`` is
# the custom-theme table (name -> seed) as `themes.load_user_themes` returns it.

def is_custom(theme: str, customs) -> bool:
    return theme in (customs or {})


def current_seed(theme: str, customs) -> dict:
    """The seed to start the editor from: the selected theme's own."""
    customs = customs or {}
    if theme in customs:
        return dict(customs[theme])
    return dict(SEEDS.get(theme, SEEDS["light"]))


def accent_shown(theme: str, accent: str | None, customs) -> str:
    """The accent swatch: the override if set, else the theme's own accent."""
    if accent:
        return accent
    customs = customs or {}
    if theme in customs:
        return customs[theme]["accent"]
    return BUILTIN_THEMES.get(theme, BUILTIN_THEMES["light"])["accent"]


def taken_names(customs, exclude: str | None = None) -> set:
    """Names a new or renamed theme may not use: built-in labels and other customs."""
    names = set(THEME_LABELS.values()) | set(customs or {})
    if exclude:
        names.discard(exclude)
    return names


def unique_theme_name(base: str, taken) -> str:
    """``base``, or ``base (2)`` upward, avoiding ``taken`` case-insensitively."""
    base = (base or "").strip() or "Imported theme"
    lowered = {str(n).lower() for n in taken}
    if base.lower() not in lowered:
        return base
    i = 2
    while f"{base} ({i})".lower() in lowered:
        i += 1
    return f"{base} ({i})"


def save_theme(directory, name: str, seed: dict,
               replacing: str | None = None) -> dict:
    """Write a custom theme (renaming ``replacing`` away); returns the reloaded table."""
    if replacing and replacing != name:
        delete_user_theme(directory, replacing)
    save_user_theme(directory, name, seed)
    return load_user_themes(directory)


def delete_theme(directory, name: str) -> dict:
    """Remove a custom theme; returns the reloaded table."""
    delete_user_theme(directory, name)
    return load_user_themes(directory)


def delete_prompt(name: str) -> tuple[str, str]:
    return "Delete theme", f"Delete the “{name}” theme?"
