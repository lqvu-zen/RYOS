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

LABELS = {RUNNING: "Running", FAVORITES: "★  Favorites",
          PIPELINES: "Pipelines", SCRIPTS: "Scripts"}

EMPTY = {RUNNING: "No script is currently running.",
         FAVORITES: "No favorites yet — click ☆ on a script or pipeline.",
         PIPELINES: "No pipelines yet.",
         SCRIPTS: "No scripts yet."}


def header_text(section: str, collapsed: bool) -> str:
    """The header as drawn: an arrow for the state, then the label in capitals."""
    return f"{'▶' if collapsed else '▼'}  {LABELS[section].upper()}"


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

NO_BASE_DIR = "No base directory — click to set"


def banner_text(base_dir: str) -> str:
    """The banner at the top of a group: its base folder, or how to set one."""
    return f"📁  {base_dir or NO_BASE_DIR}"
