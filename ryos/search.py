"""UI-independent search/filter logic for the script list.

Pure helpers extracted from ``RYOSApp`` so the matching rule and the
"found in other groups" hint decision can be unit-tested without a display.
The app renders widgets; this module makes the decisions.
"""

from __future__ import annotations

from dataclasses import dataclass


def normalize_query(raw: str, is_placeholder: bool) -> str:
    """Lowercased, stripped query. The placeholder text counts as no query."""
    if is_placeholder:
        return ""
    return raw.lower().strip()


def matches(name: str, query: str) -> bool:
    """True when there is no query, or the query is a substring of the name."""
    return not query or query in name.lower()


@dataclass(frozen=True)
class HintLink:
    """One clickable target group in the search hint."""

    label: str          # display text ("Other" for the unnamed group)
    target: str | None  # group to switch to (None is the unnamed/"Other" group)
    count: int


@dataclass(frozen=True)
class SearchHint:
    """The 'no local matches, found elsewhere' hint to render."""

    links: list[HintLink]


def compute_hint(
    query: str,
    active_group: str | None,
    counts: list[tuple[str, int]],
    dismissed: str | None = None,
) -> SearchHint | None:
    """Decide whether to show the 'found in other groups' hint.

    ``counts`` is ``[(group, match_count), ...]`` for the query. Returns a
    ``SearchHint`` with the other-group links, or ``None`` when no hint should
    show: no query, no active group, the query was dismissed, the active group
    already has a match, or no other group matches.
    """
    if not query or active_group is None:
        return None
    if query == dismissed:
        return None
    others = [(g, n) for g, n in counts if g != active_group]
    active_has_match = any(g == active_group for g, _ in counts)
    if active_has_match or not others:
        return None
    links = [
        HintLink(label=("Other" if g == "" else g),
                 target=(None if g == "" else g), count=n)
        for g, n in others
    ]
    return SearchHint(links=links)
