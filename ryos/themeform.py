"""Rules for the custom theme editor, independent of any toolkit.

The editor edits a *seed* — a mode plus seven required colours, with optional
advanced overrides — and `themes.build_palette()` expands it. The colour maths
and `validate_seed` already live in `themes.py`; what lived only inside the Tk
dialog was the naming rule, and which colour an advanced row should show when
nothing has been overridden.
"""

from __future__ import annotations

from . import verdict
from .themes import build_palette, is_hex_color, validate_seed

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
