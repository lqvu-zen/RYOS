"""UI-independent search/filter logic.

Pure helpers extracted from ``RYOSApp`` so the matching rules can be
unit-tested without a display. The app renders widgets; this module makes the
decisions. Two domains live here: filtering the script list, and finding text
in an output tab.
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


# --- Output-panel search -----------------------------------------------------

def find_spans(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Case-insensitive, non-overlapping match spans as (start, end) offsets.

    Character offsets rather than line/column, because Tk accepts
    ``"1.0 + N chars"`` directly — so the caller needs no index arithmetic of
    its own, and this stays testable without a Text widget.

    A blank needle matches nothing: highlighting every character the moment
    someone focuses the box would be useless and slow.
    """
    if not needle or not haystack:
        return []
    hay, pin = haystack.lower(), needle.lower()
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        at = hay.find(pin, start)
        if at < 0:
            return spans
        spans.append((at, at + len(pin)))
        start = at + len(pin)      # non-overlapping: "aa" finds 2 in "aaaa"


def step_match(count: int, current: int | None, forward: bool = True) -> int | None:
    """Index of the next/previous match, wrapping at both ends.

    None when there is nothing to step through. With no current position,
    stepping forward lands on the first match and backward on the last, so the
    first Enter after typing goes somewhere sensible either way.
    """
    if count <= 0:
        return None
    if current is None:
        return 0 if forward else count - 1
    return (current + (1 if forward else -1)) % count
