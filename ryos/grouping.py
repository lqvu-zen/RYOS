"""UI-independent grouping: bucketing for the 'All' view, and group CRUD rules.

The CRUD helpers here answer the questions ``RYOSApp`` used to answer inline
between dialog calls -- what to call a clone, and which tab to select once the
one you were on has been renamed or deleted. Keeping them here makes them
testable and means they survive the Qt migration
(docs/plans/qt-migration.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


def bucket_by_group(records: list, groups: list[str],
                    key: Callable[[object], str]) -> dict[str, list]:
    """Bucket records by group for display.

    Every name in ``groups`` gets a (possibly empty) bucket, the ungrouped key
    ``""`` is always present, and each record lands in ``key(record)``'s bucket
    (created on demand). Input order is preserved within each bucket.
    """
    buckets: dict[str, list] = {g: [] for g in groups}
    buckets.setdefault("", [])
    for rec in records:
        g = key(rec)
        buckets.setdefault(g, [])
        buckets[g].append(rec)
    return buckets


def unique_clone_name(source: str, existing) -> str:
    """A free name for a copy of ``source``.

    ``"X (copy)"`` first, then ``"X (copy 2)"`` upward. Numbering starts at 2
    because the unnumbered name is conceptually the first copy -- going
    straight to "(copy 1)" would leave no name for the plain case and read
    oddly next to it.
    """
    existing = set(existing)
    candidate = f"{source} (copy)"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{source} (copy {n})" in existing:
        n += 1
    return f"{source} (copy {n})"


def validate_group_name(name, existing) -> str | None:
    """The reason ``name`` cannot be used, or None if it can.

    Returns a message rather than raising, because every caller turns it
    straight into a dialog.
    """
    if name is None:
        return None                      # the user cancelled; not an error
    cleaned = name.strip()
    if not cleaned:
        return "A group needs a name."
    if cleaned in set(existing):
        return f"A group named '{cleaned}' already exists."
    return None


def rename_target(old: str, answer, existing) -> tuple:
    """(new name, problem) for renaming ``old`` to what the user typed.

    (None, None) means there is nothing to do: cancelled, blank, or the same
    name. A clash with another group is a problem to show -- the database
    enforces unique names, so letting it through would raise, not merge.
    """
    if answer is None or not answer.strip() or answer.strip() == old:
        return None, None
    problem = validate_group_name(answer, [g for g in existing if g != old])
    return (None, problem) if problem else (answer.strip(), None)


def group_order(tab_keys) -> list[str]:
    """The stored group order for tabs in ``tab_keys`` order.

    Drops the ungrouped key ``""``: it is not a stored group, and wherever
    its tab ended up after a drag, it goes back to the end on the next build.
    """
    return [k for k in tab_keys if k]


def active_after_rename(active: str | None, old: str, new: str) -> str | None:
    """Which group stays selected when ``old`` is renamed to ``new``."""
    return new if active == old else active


def active_after_delete(active: str | None, deleted: str,
                        remaining: list[str]) -> str | None:
    """Which group is selected once ``deleted`` is gone.

    Deleting the group you are looking at falls back to the first remaining
    one, or the All view when nothing is left -- never a name that no longer
    exists, which would render an empty tab.
    """
    if active != deleted:
        return active
    return remaining[0] if remaining else None


# --- changing a group's base directory -----------------------------------------
# The dialog returns the new folder, "" to clear it, or None when cancelled.
# What happens next -- and what the user is asked on the way -- is decided
# here, so the Tk and Qt flows cannot drift apart.

BASE_DIR_CLEAR = "clear"
BASE_DIR_SET = "set"


@dataclass(frozen=True)
class BaseDirChange:
    """What to do with a base-directory answer, and what to confirm first."""

    kind: str
    new_dir: str
    confirm: "tuple[str, str] | None"      # (title, question), or None


def base_dir_change(group: str, current: str,
                    answer: "str | None") -> "BaseDirChange | None":
    """The change a base-directory dialog answer asks for, or None for none.

    Clearing always confirms. Moving an existing folder confirms, because it
    rewrites stored script paths; setting a first folder does not.
    """
    if answer is None or answer == current:
        return None
    if not answer:
        return BaseDirChange(BASE_DIR_CLEAR, "", (
            "Clear base directory",
            f"Remove base directory restriction for '{group}'?\n\n"
            "Existing script paths will not be changed."))
    confirm = None
    if current:
        confirm = ("Re-map paths",
                   f"Re-map script paths from\n{current}\nto\n{answer}?\n\n"
                   "Paths already outside the old base will be left unchanged.")
    return BaseDirChange(BASE_DIR_SET, answer, confirm)


def apply_base_dir_change(db, group: str, change: BaseDirChange
                          ) -> "tuple[str, tuple[str, str] | None]":
    """Store ``change``. Returns (status line, warning (title, text) or None)."""
    if change.kind == BASE_DIR_CLEAR:
        db.set_group_base_dir(group, "")
        return f"Base directory cleared for '{group}'.", None
    remapped, untouched = db.set_group_base_dir(group, change.new_dir)
    warning = None
    if untouched:
        warning = ("Some paths not remapped",
                   f"{len(untouched)} script(s) have paths outside the old "
                   "base directory and were not remapped:\n"
                   + "\n".join(untouched[:10]))
    return (f"Base directory set for '{group}'. {remapped} path(s) remapped.",
            warning)


# --- which group is on screen at start, and remembering it -------------------------

def initial_group(settings: dict, groups) -> str | None:
    """The group to open on: the remembered one if it still exists, else the
    first group, else None -- the All view."""
    groups = list(groups)
    last = settings.get("last_group")
    if settings.get("remember_last_group", True) and last in groups:
        return last
    return groups[0] if groups else None


def remember_group(settings: dict, active: str | None) -> None:
    """Store the group on screen for next time, when the setting asks for it.

    The setting existed, and was read at start, but nothing ever wrote it --
    so it always fell back to the first group.
    """
    if settings.get("remember_last_group", True):
        settings["last_group"] = active
