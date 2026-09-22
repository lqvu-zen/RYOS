"""UI-independent grouping: bucketing for the 'All' view, and group CRUD rules.

The CRUD helpers here answer the questions ``RYOSApp`` used to answer inline
between dialog calls -- what to call a clone, and which tab to select once the
one you were on has been renamed or deleted. Keeping them here makes them
testable and means they survive the Qt migration
(docs/plans/qt-migration.md).
"""

from __future__ import annotations

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
