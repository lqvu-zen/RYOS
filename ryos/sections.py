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
