"""Pure helpers for the Quick Run file index and suggestion ranking.

Extracted from ryos.ui.app so the matching/ranking logic can be unit-tested
without constructing the Tkinter application. The "index" passed to
rank_suggestions is a list of entries in the shape produced by build_entry():

    (rel_str, name_lower, stem_lower, rel_lower)

Keeping this here makes the index format single-sourced and the ranking
algorithm — the part most likely to harbour subtle ordering bugs — directly
testable.
"""
from pathlib import Path

# An index entry: (relative path, filename lower, stem lower, relative path lower).
Entry = tuple[str, str, str, str]


def build_entry(rel_str: str, filename: str) -> Entry:
    """Build an index entry for a file from its relative path and filename.

    Pre-lowercasing the comparison fields keeps the hot ranking loop cheap.
    """
    return (rel_str, filename.lower(), Path(filename).stem.lower(), rel_str.lower())


def rank_suggestions(index: list[Entry], query: str, max_n: int) -> list[str]:
    """Return up to max_n relative paths from index that match query, best first.

    Matches are ranked by tier (lower is better):

        0  filename stem equals the query exactly
        1  stem starts with the query
        2  filename starts with the query
        3  filename contains the query
        4  the relative path contains the query

    Within a tier, shorter stems rank first, then alphabetical relative path.
    Non-matching entries are dropped. Comparison is case-insensitive.
    """
    q = query.lower()
    results: list[tuple[int, int, str]] = []
    for rel, name_lower, stem_lower, rel_lower in index:
        if stem_lower == q:
            tier = 0
        elif stem_lower.startswith(q):
            tier = 1
        elif name_lower.startswith(q):
            tier = 2
        elif name_lower.find(q) != -1:
            tier = 3
        elif rel_lower.find(q) != -1:
            tier = 4
        else:
            continue
        results.append((tier, len(stem_lower), rel))
    results.sort(key=lambda x: (x[0], x[1], x[2]))
    return [r[2] for r in results[:max_n]]
