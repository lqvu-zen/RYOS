"""UI-independent grouping of scripts for the 'All' view."""

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
