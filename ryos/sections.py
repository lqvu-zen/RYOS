"""The sections of a group's card list: Favorites, Pipelines, Scripts.

Which records go in which section, what each header and empty section says,
and which sections the user has collapsed -- shared by the Tk and Qt shells.
Pure: records in, lists out.

A favourite appears twice, in Favorites and in its own section, as it always
has in Tk; Favorites is a shortcut, not a move.
"""

from __future__ import annotations

RUNNING = "running"
FAVORITES = "favorites"
PIPELINES = "pipelines"
SCRIPTS = "scripts"

#: Card sections, top to bottom (Running sits above them and holds no cards).
ORDER = (FAVORITES, PIPELINES, SCRIPTS)

LABELS = {RUNNING: "Running", FAVORITES: "Favorites",
          PIPELINES: "Pipelines", SCRIPTS: "Scripts"}

EMPTY = {RUNNING: "No script is currently running.",
         # The star is a drawn icon that shows under the pointer, not a ☆
         # in the text: say where to find it.
         FAVORITES: "No favorites yet — point at a script or pipeline and "
                    "click its star.",
         PIPELINES: "No pipelines yet.",
         SCRIPTS: "No scripts yet."}


def no_match_text(query: str) -> str:
    """What a group says when a search leaves nothing in it. The count by the
    box ("0 of 14") was all there was: three headings over nothing."""
    return f"Nothing here matches “{query.strip()}”."


def header_text(section: str, collapsed: bool) -> str:
    """The header as drawn: a small arrow for the state, then the label in
    capitals. Small: it is a fold, not the thing the eye should land on."""
    return f"{COLLAPSED_MARK if collapsed else '▾'}  {LABELS[section].upper()}"


#: What starts a folded section's header.
COLLAPSED_MARK = "▸"


def split(records) -> dict:
    """Records by section. Each record is a dict with ``kind`` and ``favorite``.

    Favorites lists favourite pipelines first, then scripts -- the Tk order.
    Order within each section is the order given, which is the stored order.
    """
    pipelines = [r for r in records if r.get("kind") == "pipeline"]
    scripts = [r for r in records if r.get("kind") != "pipeline"]
    return {
        FAVORITES: ([r for r in pipelines if r.get("favorite")]
                    + [r for r in scripts if r.get("favorite")]),
        PIPELINES: pipelines,
        SCRIPTS: scripts,
    }


class CollapseState:
    """Which sections are collapsed, per group, for the session."""

    def __init__(self) -> None:
        self._collapsed: dict[str, dict[str, bool]] = {}

    def is_collapsed(self, group: str, section: str) -> bool:
        return self._collapsed.get(group, {}).get(section, False)

    def toggle(self, group: str, section: str) -> bool:
        """Flip one section; returns whether it is now collapsed."""
        now = not self.is_collapsed(group, section)
        self._collapsed.setdefault(group, {})[section] = now
        return now

    def forget(self, group: str) -> None:
        self._collapsed.pop(group, None)


# --- the All view: every group on one page -----------------------------------------

ALL_LABEL = "All"
OTHER_LABEL = "Other"
ADD_SCRIPT_LABEL = "+ Script"
ALL_EMPTY = f"No scripts yet.\nClick '{ADD_SCRIPT_LABEL}' to get started."


def all_view_groups(groups, has_ungrouped: bool) -> list[tuple[str, str | None]]:
    """(group key, header) for each block of the All view, top to bottom.

    Named groups in their stored order, each under its name in capitals;
    ungrouped items last, headed "Other" -- or with no header when there are
    no named groups, since "Other" than nothing reads oddly.
    """
    blocks: list[tuple[str, str | None]] = [(g, g.upper()) for g in groups]
    if has_ungrouped:
        blocks.append(("", OTHER_LABEL.upper() if groups else None))
    return blocks


# --- the group banner -------------------------------------------------------------

NO_BASE_DIR = "No base folder — click to set"


def banner_text(base_dir: str) -> str:
    """The banner at the top of a group: its base folder, or how to set one."""
    return base_dir or NO_BASE_DIR


# --- moving through the rows by keyboard ---------------------------------------------

#: What a row's keys do, for a screen reader and the tutorial.
ROW_KEYS_HINT = ("Enter runs it, F2 edits it, the Menu key shows everything "
                 "else; the arrow keys move between rows.")
#: How far Page Up / Page Down move.
PAGE_STEP = 5
#: The moves a key can make; the Qt code maps keys to these names.
STEPS = ("up", "down", "home", "end", "pageup", "pagedown")


def step_row(count: int, current: int | None, step: str) -> int | None:
    """Which row the focus goes to: the index in a list of ``count`` rows,
    or None when there are none. Moves stop at the ends rather than wrap,
    so holding a key can't send focus round and round the list."""
    if count <= 0:
        return None
    if current is None:
        return count - 1 if step in ("up", "end", "pageup") else 0
    target = {"up": current - 1, "down": current + 1, "home": 0,
              "end": count - 1, "pageup": current - PAGE_STEP,
              "pagedown": current + PAGE_STEP}[step]
    return max(0, min(count - 1, target))
