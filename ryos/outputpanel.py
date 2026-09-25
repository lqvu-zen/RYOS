"""Where a line of output goes, and when the buffer is trimmed.

`ui/app.py` decided both inline while writing into a Tk Text widget. The rules
are the same whichever widget holds the text, so they live here and both
front-ends route through them (docs/plans/qt-migration.md).

Pure: takes keys and counts, returns keys and counts.
"""

from __future__ import annotations

#: The tab that mirrors every job's output.
ALL = "all"


def target_tabs(tab_key: str | None, active_tab_key: str | None,
                open_tabs) -> list[str]:
    """Which tabs a line of output should be written to.

    A line tagged with a ``tab_key`` belongs to a specific job, so it goes to
    that job's tab wherever the user happens to be looking — and to "all",
    which mirrors everything. Untagged text belongs to whatever is in front,
    and is dropped if that tab has gone away.

    Returns keys in write order, never containing duplicates: a job whose tab
    *is* "all" must not have its output written twice.
    """
    open_tabs = set(open_tabs)
    if tab_key is not None:
        keys = [tab_key] if tab_key in open_tabs else []
        if ALL in open_tabs and tab_key != ALL:
            keys.append(ALL)
        return keys
    if not active_tab_key or active_tab_key not in open_tabs:
        return []
    keys = [active_tab_key]
    if active_tab_key != ALL and ALL in open_tabs:
        keys.append(ALL)
    return keys


def overflow_lines(line_count: int, max_lines: int) -> int:
    """How many lines to drop from the top to get back under the cap.

    Zero when the buffer is within the cap, so a caller can skip the delete
    entirely. A non-positive cap means "no limit" rather than "keep nothing",
    which is the reading that does not silently erase a user's output.
    """
    if max_lines <= 0 or line_count <= max_lines:
        return 0
    return line_count - max_lines


def section_is_visible(*, query_active: bool, has_cards: bool,
                       any_match: bool) -> bool:
    """Whether a card section's header should show.

    A section with no real cards always shows — it is holding an empty-state
    placeholder, and hiding the header would leave the placeholder floating
    with nothing to explain it. Otherwise a section only hides while a search
    is narrowing the list and nothing in it matched.
    """
    if not has_cards:
        return True
    if not query_active:
        return True
    return any_match


# --- the output header and tabs: wording and small rules, shared -----------------

SHOW_OUTPUT = "▲  Show Output"
HIDE_OUTPUT = "▼  Hide Output"
CLEAR = "🗑 Clear"
CLOSE_ALL = "✕ Close All"
FIND = "Find"
ERRORS_ONLY = "Errors only"
TAB_COPY = "⎘  Copy"
TAB_SAVE = "💾  Save"
TAB_CLOSE = "✕  Close"
SAVE_TITLE = "Save output"
NOTHING_TO_SAVE = "Nothing to save."
COPIED = "Log copied to clipboard."

#: Line tags that stay visible under "Errors only". Everything else -- plain
#: output, status lines, the green success line -- is hidden, not removed.
ERROR_TAGS = frozenset({"stderr"})


def saved_status(path: str) -> str:
    return f"Saved to {path}"


def shown_when_filtered(tag: str | None, errors_only: bool) -> bool:
    return not errors_only or (tag or "stdout") in ERROR_TAGS


def match_label(query: str, count: int, current: int | None) -> str:
    """The find box's count: blank, "no matches", or "2/5"."""
    if not query:
        return ""
    if not count:
        return "no matches"
    return f"{(current + 1) if current is not None else 0}/{count}"


def tab_menu(key: str) -> list[str | None]:
    """The output tab's right-click menu; None is a separator. The All tab
    cannot be closed."""
    items: list[str | None] = [TAB_COPY, TAB_SAVE]
    if key != ALL:
        items += [None, TAB_CLOSE]
    return items


def closable(keys, running) -> list:
    """The tabs Close All closes: every one but All and those still running."""
    running = set(running)
    return [k for k in keys if k != ALL and k not in running]
