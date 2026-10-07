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
RUN_WITH = "run_with"
SCHEDULE = "schedule"
HISTORY = "history"
CLONE = "clone"
COPY = "copy"
COPY_TO = "copy_to"              # the submenu; entries are "copy_to:<group>"
DELETE = "delete"

RENAME_GROUP = "rename_group"
PASTE = "paste"
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
_COPY_TO_PREFIX = COPY_TO + ":"


@dataclass(frozen=True)
class MenuItem:
    """One entry. ``key`` is None for a separator."""

    key: str | None
    label: str = ""
    danger: bool = False
    enabled: bool = True
    children: tuple = field(default_factory=tuple)   # a submenu when non-empty
    highlight: str | None = None     # the colour an entry previews, if any
    icon: str | None = None          # a shape from qtui/icons.py, drawn by the menu


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
    return MenuItem(HIGHLIGHT, "Highlight", children=tuple(entries), icon="palette")


def _favorite_item(favorite: bool) -> MenuItem:
    return MenuItem(FAVORITE, "Remove from favorites" if favorite
                    else "Add to favorites",
                    icon="star" if favorite else "star-filled")


def copy_to_key(group: str) -> str:
    """The action key for copying into ``group``."""
    return _COPY_TO_PREFIX + group


def picked_copy_target(key: str) -> str | None:
    """The group a "Copy to" entry names, or None for any other key."""
    return key[len(_COPY_TO_PREFIX):] if key.startswith(_COPY_TO_PREFIX) else None


def copy_targets(groups, own_group: str) -> list[str]:
    """The groups "Copy to" offers: every group but the item's own, where
    Clone already does the job."""
    return [g for g in groups if g and g != own_group]


def _copy_items(targets) -> list[MenuItem]:
    """Copy, for Paste in any group (Ctrl+C on the row), and Copy to, for
    one step into another group. Copy to is greyed with nowhere to go."""
    children = tuple(MenuItem(copy_to_key(g), g) for g in targets)
    return [MenuItem(COPY, "Copy\tCtrl+C", icon="copy"),
            MenuItem(COPY_TO, "Copy to", enabled=bool(children), children=children,
                     icon="arrow-right")]


def paste_label(name: str | None) -> str:
    """The group menu's Paste: what it will paste, or that nothing is copied."""
    return f'Paste "{name}"\tCtrl+V' if name else "Paste\tCtrl+V"


#: Opens the item's dialog. First on both menus: a row shows its pencil only
#: under the pointer, so the menu is the way in that is always there.
EDIT_ITEM = MenuItem(EDIT, "Edit…", icon="edit")


def script_menu(*, favorite: bool, color: str | None,
                can_move_up: bool, can_move_down: bool,
                copy_targets=()) -> list[MenuItem]:
    """The script card's menu. Moves are disabled at the ends of the list.

    Edit and Run with parameters come first: the row keeps their buttons for
    the pointer, so without these a keyboard -- or anyone who never hovers
    the right spot -- had no way to either.
    """
    return [
        EDIT_ITEM,
        MenuItem(RUN_WITH, "Run with parameters…", icon="run-with"),
        SEPARATOR,
        _favorite_item(favorite),
        _highlight_menu(color),
        SEPARATOR,
        MenuItem(MOVE_TOP, "Move to top", enabled=can_move_up, icon="arrow-top"),
        MenuItem(MOVE_UP, "Move up", enabled=can_move_up, icon="arrow-up"),
        MenuItem(MOVE_DOWN, "Move down", enabled=can_move_down, icon="arrow-down"),
        SEPARATOR,
        MenuItem(SCHEDULE, "Schedule…", icon="clock"),
        MenuItem(HISTORY, "Run history…", icon="history"),
        MenuItem(CLONE, "Clone", icon="copy"),
        *_copy_items(copy_targets),
        SEPARATOR,
        MenuItem(DELETE, "Delete", danger=True, icon="trash"),
    ]


def pipeline_menu(*, favorite: bool, color: str | None,
                  copy_targets=()) -> list[MenuItem]:
    return [
        EDIT_ITEM,
        SEPARATOR,
        _favorite_item(favorite),
        _highlight_menu(color),
        SEPARATOR,
        MenuItem(SCHEDULE, "Schedule…", icon="clock"),
        MenuItem(HISTORY, "Run history…", icon="history"),
        MenuItem(CLONE, "Clone", icon="copy"),
        *_copy_items(copy_targets),
        SEPARATOR,
        MenuItem(DELETE, "Delete", danger=True, icon="trash"),
    ]


def group_menu(copied: str | None = None) -> list[MenuItem]:
    """The group tab's menu. ``copied`` names what Copy holds, if anything:
    Paste is there either way, greyed until something is copied."""
    return [
        MenuItem(RENAME_GROUP, "Rename…", icon="edit"),
        MenuItem(PASTE, paste_label(copied), enabled=bool(copied), icon="import"),
        MenuItem(CLONE_GROUP, "Clone group", icon="copy"),
        MenuItem(BASE_DIR, "Base folder…", icon="folder"),
        MenuItem(EXPORT_GROUP, "Export group…", icon="export"),
        SEPARATOR,
        MenuItem(DELETE_GROUP, "Delete group", danger=True, icon="trash"),
    ]


def neighbours(ids: list, item_id) -> tuple:
    """(the id above, the id below) ``item_id`` in ``ids``; None at an end."""
    if item_id not in ids:
        return None, None
    i = ids.index(item_id)
    return (ids[i - 1] if i > 0 else None,
            ids[i + 1] if i < len(ids) - 1 else None)


# --- confirmations ------------------------------------------------------------

def steps_note(pipelines, whose: str = "Its") -> str:
    """What deleting scripts does to the pipelines that run them ("" if none).

    Their steps go with them (`db._forget_scripts`), so say so and name the
    pipelines: a step vanishing unannounced reads as data loss.
    """
    names = list(pipelines)
    if not names:
        return ""
    shown = ", ".join(f"'{n}'" for n in names[:3])
    if len(names) > 3:
        shown += f" and {len(names) - 3} more"
    noun = "pipeline" if len(names) == 1 else "pipelines"
    return f"\n\n{whose} steps in {noun} {shown} will be removed too."


def delete_prompt(kind: str, name: str, used_in=()) -> tuple[str, str]:
    """(title, question) for deleting one card. ``used_in``: the pipelines
    with a step running this script (`ScriptDB.pipelines_using`)."""
    if kind == PIPELINE:
        return "Delete Pipeline", f"Delete pipeline '{name}'?"
    return "Delete", f"Delete '{name}'?" + steps_note(used_in)


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


def _copy_script(db, script_id: int, group: str) -> int | None:
    """One script into ``group``, with everything that defines how it runs and
    its presets. Its own name in another group; "(copy)" beside itself."""
    rec = db.get(script_id)
    if not rec:
        return None
    _id, name, path, params, interp, own_group, temp_param, env_vars, work_dir = rec[:9]
    new_id = db.add(name if (own_group or "") != group else f"{name} (copy)",
                    path, params, interp, group, temp_param,
                    int(db.is_detached(script_id)),
                    env_vars=env_vars, work_dir=work_dir or "")
    presets = [(label, p) for _pid, label, p in db.list_param_presets(script_id)]
    if presets:
        db.replace_param_presets(new_id, presets)
    return new_id


def _same_script_in(db, script_id: int, group: str) -> int | None:
    """A script already in ``group`` that runs the same file the same way."""
    rec = db.get(script_id)
    if not rec:
        return None
    path, params, interp = rec[2], rec[3], rec[4]
    for row in db.list_all():
        if ((row[8] or "") == group and row[2] == path and (row[3] or "") == (params or "")
                and (row[4] or "") == (interp or "")):
            return row[0]
    return None


def copy_to_group(db, kind: str, item_id: int, group: str) -> int | None:
    """Copy one script or pipeline into ``group``. The new id, or None if the
    item is gone.

    A pipeline brings the scripts its steps run: the pipeline editor offers
    only its own group's scripts, so a copy still pointing at another group's
    would not be editable there, and would break when those were deleted. A
    script the group already has -- same file, parameters and interpreter --
    is used rather than duplicated, and one script used by several steps is
    copied once.
    """
    if kind != PIPELINE:
        return _copy_script(db, item_id, group)
    ident = db.pipeline_identity(item_id)
    if ident is None:
        return None
    name, own_group = ident
    script_map: dict = {}
    for row in db.list_pipeline_steps(item_id):
        sid = row[1]
        if sid in script_map:
            continue
        found = _same_script_in(db, sid, group)
        new_sid = found if found is not None else _copy_script(db, sid, group)
        if new_sid is not None:
            script_map[sid] = new_sid
    return db.copy_pipeline_to_group(
        item_id, group, script_map,
        name if own_group != group else f"{name} (copy)")


def item_name(db, kind: str, item_id: int) -> str | None:
    """What Paste will say it is pasting; None once the item is gone."""
    if kind == PIPELINE:
        ident = db.pipeline_identity(item_id)
        return ident[0] if ident else None
    rec = db.get(item_id)
    return rec[1] if rec else None


def delete(db, kind: str, item_id: int) -> None:
    if kind == PIPELINE:
        db.delete_pipeline(item_id)
    else:
        db.delete(item_id)
