"""Report a bug: a new GitHub issue, opened in the browser already filled in
with what the maintainer needs to reproduce it.

Nothing is sent from here. The person sees the issue on GitHub, writes what
happened, and submits it themselves -- so no log, path or setting leaves the
machine unless they choose to add it. The log is pointed to, not attached:
it can hold script paths and output.
"""

from __future__ import annotations

from urllib.parse import urlencode

NEW_ISSUE = "https://github.com/lqvu-zen/RYOS/issues/new"

MENU_LABEL = "Report a bug…"
TOOLTIP = "Report a bug — opens a new issue on GitHub, filled in with your versions"
OPENED = "Opened a bug report in your browser — nothing is sent until you submit it."

#: Where the log is, as anyone's machine spells it (no user name in it).
LOG_HINT = r"%APPDATA%\RYOS\logs\ryos.log"

#: Browsers and GitHub cope with long links, but not endlessly; the body
#: here is a few hundred characters, and this keeps it so.
MAX_URL = 6000


def environment(version: str, *, frozen: bool, os_name: str, python: str,
                qt: str, theme: str, layout: str) -> list[tuple[str, str]]:
    """The facts a bug report needs, as (label, value) pairs."""
    return [
        ("RYOS", f"{version} ({'Windows build' if frozen else 'from source'})"),
        ("OS", os_name),
        ("Python", python),
        ("Qt", qt),
        ("Theme", theme or "light"),
        ("Layout", layout),
    ]


def issue_body(env: list[tuple[str, str]]) -> str:
    """The issue's text: three headings to fill in, then the environment."""
    lines = [
        "**What happened?**", "", "",
        "**What did you expect to happen?**", "", "",
        "**Steps to reproduce**", "1. ", "",
        "---",
        "**Environment**",
        *[f"- {label}: {value}" for label, value in env],
        "",
        f"_If it helps, attach the log, `{LOG_HINT}` — have a look first: it can "
        "contain your script paths and output._",
    ]
    return "\n".join(lines)


def issue_url(env: list[tuple[str, str]]) -> str:
    """The link that opens a new, filled-in issue."""
    url = f"{NEW_ISSUE}?" + urlencode({"labels": "bug", "body": issue_body(env)})
    if len(url) > MAX_URL:          # never, with today's body -- but never broken
        url = f"{NEW_ISSUE}?labels=bug"
    return url
