"""Suggest a feature: a new GitHub issue, opened in the browser with a few
questions to answer.

Like the bug report, nothing is sent from here. Unlike it, the issue carries
no environment: a wish needs no OS, paths or log, only which RYOS it is about.
"""

from __future__ import annotations

from . import bugreport

LABEL = "enhancement"
TITLE = "Suggestion: "

MENU_LABEL = "Suggest a feature…"
TOOLTIP = ("Suggest a feature — opens a new issue on GitHub, nothing is sent "
           "until you submit it")
OPENED = ("Opened a suggestion in your browser — nothing is sent until you "
          "submit it.")
ACCESSIBLE_NAME = "Suggest a feature"


def issue_body(version: str, build: str) -> str:
    """Three headings to fill in, then which RYOS this is (and nothing else)."""
    lines = [
        "**What would you like RYOS to do?**", "", "",
        "**What are you trying to get done, and how do you do it today?**",
        "", "",
        "**Anything else** (screenshots, examples)", "", "",
        "---",
        f"RYOS {version} ({build})",
    ]
    return "\n".join(lines)


def issue_url(version: str, build: str) -> str:
    """The link that opens a new, titled, labelled suggestion."""
    return bugreport.new_issue_url(
        label=LABEL, title=TITLE, body=issue_body(version, build))
