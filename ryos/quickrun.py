"""Pure helpers for the Quick Run feature: path containment, file-index entry
shape, suggestion ranking, and name resolution.

Extracted from ryos.ui.app so this logic can be unit-tested without building
the Tkinter application. None of it imports the UI layer. The "index" passed
to rank_suggestions is a list of entries in the shape produced by build_entry():

    (rel_str, name_lower, stem_lower, rel_lower)
"""
import os
import shlex
from pathlib import Path

# An index entry: (relative path, filename lower, stem lower, relative path lower).
Entry = tuple[str, str, str, str]

# Directories skipped when scanning a base directory for scripts.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}


def _is_inside(path: str, base: str) -> bool:
    """True if path is base itself or located somewhere inside it.

    Used as a directory-traversal guard so a user-typed path cannot escape the
    configured base directory.
    """
    if not path or not base:
        return False
    norm_path = os.path.normcase(os.path.normpath(path))
    norm_base = os.path.normcase(os.path.normpath(base))
    return norm_path == norm_base or norm_path.startswith(norm_base + os.sep)


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


def resolve(base_dir: str, query: str) -> tuple[str | None, list[str], str]:
    """Find a script under base_dir matching query (exact stem, case-insensitive).

    Returns exactly one of:
        (abs_path, [], "")          exactly one match
        (None, [rel, ...], "")      multiple matches (caller disambiguates)
        (None, [], error_message)   zero matches, a traversal attempt, or an error

    A query containing a path separator or a suffix is treated as a literal path
    and validated to stay inside base_dir; otherwise base_dir is searched
    recursively (skipping vendor/VCS directories) for a filename stem match.
    """
    query = query.strip()
    if not query:
        return None, [], "Please enter a script name."

    base = Path(base_dir)

    if os.sep in query or "/" in query or (Path(query).suffix and Path(query).suffix != query):
        candidate = (base / query).resolve()
        if not _is_inside(str(candidate), str(base.resolve())):
            return None, [], f"Path '{query}' is outside the base directory."
        if not candidate.exists():
            return None, [], f"File not found:\n{candidate}"
        return str(candidate), [], ""

    query_lower = query.lower()
    matches: list[Path] = []
    try:
        for p in base.rglob("*"):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.is_file() and p.stem.lower() == query_lower:
                matches.append(p)
    except PermissionError:
        pass

    if not matches:
        return None, [], f"No script found matching '{query}' in:\n{base_dir}"
    if len(matches) == 1:
        return str(matches[0]), [], ""
    base_resolved = base.resolve()
    rels = [str(m.resolve().relative_to(base_resolved)) for m in matches]
    return None, rels, ""


def parse_input(raw: str) -> tuple[str, str, bool]:
    """Split a Quick Run entry into (query, params, params_were_given).

    The first token is the script query; the remaining tokens (re-joined) are
    its parameters. Quoting is parsed with shlex using platform-appropriate
    rules, falling back to a plain whitespace split on unbalanced quotes.
    """
    raw = raw.strip()
    try:
        tokens = shlex.split(raw, posix=(os.name != "nt"))
    except ValueError:
        tokens = raw.split()
    query = tokens[0] if tokens else ""
    return query, " ".join(tokens[1:]), len(tokens) >= 2


def display_relpath(abs_path: str, base_dir: str) -> str:
    """Label for a resolved script: path relative to base_dir, else its name."""
    try:
        return str(Path(abs_path).resolve().relative_to(Path(base_dir).resolve()))
    except ValueError:
        return Path(abs_path).name
