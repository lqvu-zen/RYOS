"""The right-click menus on cards and group tabs, as data.

Both UIs draw these menus; neither decides what is in them. Each entry is a
`MenuItem` carrying an action key, so the Tk and Qt builders only map keys to
handlers, and a test can read a menu without a display.

The database side of the actions that need no dialog -- favourite, colour,
move, clone, delete -- lives here too, for the same reason: the Tk cards and
the Qt shell call one implementation. Anything that must ask first (a delete
confirmation, a new group name) gets its wording from here and its dialog
from the toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- action keys -------------------------------------------------------------
FAVORITE = "favorite"
HIGHLIGHT = "highlight"          # the submenu; entries are "highlight:<key>"
MOVE_TOP = "move_top"
MOVE_UP = "move_up"
MOVE_DOWN = "move_down"
EDIT = "edit"
SCHEDULE = "schedule"
HISTORY = "history"
CLONE = "clone"
DELETE = "delete"

RENAME_GROUP = "rename_group"
CLONE_GROUP = "clone_group"
BASE_DIR = "base_dir"
EXPORT_GROUP = "export_group"
DELETE_GROUP = "delete_group"

SCRIPT = "script"
PIPELINE = "pipeline"

#: Highlight colours offered, in menu order. The seeds and the contrast
#: adjustment stay in the theme code; this is only what the menu lists.
HIGHLIGHTS: dict[str, str] = {
    "red": "Red", "orange": "Orange", "yellow": "Yellow", "green": "Green",
    "teal": "Teal", "blue": "Blue", "purple": "Purple",
}
_HIGHLIGHT_PREFIX = HIGHLIGHT + ":"


@dataclass(frozen=True)
class MenuItem:
    """One entry. ``key`` is None for a separator."""

    key: str | None
    label: str = ""
    danger: bool = False
    enabled: bool = True
    children: tuple = field(default_factory=tuple)   # a submenu when non-empty
    highlight: str | None = None     # the colour an entry previews, if any


SEPARATOR = MenuItem(None)


def highlight_key(color: str | None) -> str:
    """The action key for picking ``color`` (None clears it)."""
    return _HIGHLIGHT_PREFIX + (color or "")


def picked_highlight(key: str) -> tuple[bool, str | None]:
    """(is a highlight pick, the colour or None). Unknown colours clear."""
    if not key.startswith(_HIGHLIGHT_PREFIX):
        return False, None
    color = key[len(_HIGHLIGHT_PREFIX):]
    return True, (color if color in HIGHLIGHTS else None)


def _highlight_menu(current: str | None) -> MenuItem:
    current = current if current in HIGHLIGHTS else None

    def mark(color):
        return "●  " if current == color else "○  "

    entries = [MenuItem(highlight_key(None), f"{mark(None)}None"), SEPARATOR]
    entries += [MenuItem(highlight_key(c), f"{mark(c)}{label}", highlight=c)
                for c, label in HIGHLIGHTS.items()]
    return MenuItem(HIGHLIGHT, "🎨  Highlight", children=tuple(entries))


def _favorite_item(favorite: bool) -> MenuItem:
    return MenuItem(FAVORITE, "☆ Remove from Favorites" if favorite
                    else "★ Add to Favorites")


def script_menu(*, favorite: bool, color: str | None,
                can_move_up: bool, can_move_down: bool) -> list[MenuItem]:
    """The script card's menu. Moves are disabled at the ends of the list."""
    return [
        _favorite_item(favorite),
        _highlight_menu(color),
        SEPARATOR,
        MenuItem(MOVE_TOP, "⤒  Move to Top", enabled=can_move_up),
        MenuItem(MOVE_UP, "▲  Move Up", enabled=can_move_up),
        MenuItem(MOVE_DOWN, "▼  Move Down", enabled=can_move_down),
        SEPARATOR,
        MenuItem(SCHEDULE, "🕒  Schedule…"),
        MenuItem(HISTORY, "🕘  Run History…"),
        MenuItem(CLONE, "⧉  Clone"),
        SEPARATOR,
        MenuItem(DELETE, "🗑  Delete", danger=True),
    ]


def pipeline_menu(*, favorite: bool, color: str | None) -> list[MenuItem]:
    return [
        _favorite_item(favorite),
        _highlight_menu(color),
        SEPARATOR,
        MenuItem(EDIT, "⚙  Edit"),
        MenuItem(SCHEDULE, "🕒  Schedule…"),
        MenuItem(HISTORY, "🕘  Run History…"),
        MenuItem(CLONE, "⧉  Clone"),
        SEPARATOR,
        MenuItem(DELETE, "🗑  Delete", danger=True),
    ]


def group_menu() -> list[MenuItem]:
    return [
        MenuItem(RENAME_GROUP, "✏  Rename"),
        MenuItem(CLONE_GROUP, "📋  Clone Group"),
        MenuItem(BASE_DIR, "📁  Base directory…"),
        MenuItem(EXPORT_GROUP, "📤  Export group"),
        SEPARATOR,
        MenuItem(DELETE_GROUP, "🗑  Delete Group", danger=True),
    ]


def neighbours(ids: list, item_id) -> tuple:
    """(the id above, the id below) ``item_id`` in ``ids``; None at an end."""
    if item_id not in ids:
        return None, None
    i = ids.index(item_id)
    return (ids[i - 1] if i > 0 else None,
            ids[i + 1] if i < len(ids) - 1 else None)


# --- confirmations ------------------------------------------------------------

def delete_prompt(kind: str, name: str) -> tuple[str, str]:
    """(title, question) for deleting one card."""
    if kind == PIPELINE:
        return "Delete Pipeline", f"Delete pipeline '{name}'?"
    return "Delete", f"Delete '{name}'?"


def delete_group_prompt(name: str) -> tuple[str, str]:
    return ("Delete Group",
            f"Delete group '{name}'?\n\n"
            "Scripts in this group will be moved to ungrouped.")


# --- the database side ----------------------------------------------------------

def set_favorite(db, kind: str, item_id: int, favorite: bool) -> None:
    if kind == PIPELINE:
        db.set_favorite_pipeline(item_id, favorite)
    else:
        db.set_favorite_script(item_id, favorite)


def set_highlight(db, kind: str, item_id: int, color: str | None) -> None:
    if kind == PIPELINE:
        db.set_pipeline_color(item_id, color)
    else:
        db.set_script_color(item_id, color)


def move(db, key: str, item_id: int, *, up_id=None, down_id=None) -> bool:
    """Apply a move-menu key to a script. False when there is nowhere to go."""
    if key == MOVE_TOP and up_id is not None:
        db.move_to_top(item_id)
    elif key == MOVE_UP and up_id is not None:
        db.swap_order(item_id, up_id)
    elif key == MOVE_DOWN and down_id is not None:
        db.swap_order(item_id, down_id)
    else:
        return False
    return True


def clone(db, kind: str, item_id: int) -> int | None:
    """Copy one card next to the original. The new id, or None if it is gone.

    A script copy keeps everything that defines how it runs -- including
    ``detached``, ``env_vars`` and ``work_dir``, the same set `clone_group`
    keeps. A launcher cloned without ``detached`` would block its pipeline
    again, which is the behaviour issue #5 removed.
    """
    if kind == PIPELINE:
        return db.clone_pipeline(item_id)
    rec = db.get(item_id)
    if not rec:
        return None
    _id, name, path, params, interp, group, temp_param, env_vars, work_dir = rec[:9]
    return db.add(f"{name} (copy)", path, params, interp, group or "",
                  temp_param, int(db.is_detached(item_id)),
                  env_vars=env_vars, work_dir=work_dir or "")


def delete(db, kind: str, item_id: int) -> None:
    if kind == PIPELINE:
        db.delete_pipeline(item_id)
    else:
        db.delete(item_id)
