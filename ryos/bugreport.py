"""Report a bug: a new GitHub issue, opened in the browser already filled in
with what the maintainer needs to reproduce it.

Nothing is sent from here. The person sees the issue on GitHub, writes what
happened, and submits it themselves -- so no log, path or setting leaves the
machine unless they choose to add it. The log is pointed to, not attached:
it can hold script paths and output.
"""

from __future__ import annotations

from urllib.parse import urlencode

from . import buildinfo

NEW_ISSUE = "https://github.com/lqvu-zen/RYOS/issues/new"

MENU_LABEL = "Report a bug…"
TOOLTIP = "Report a bug — opens a new issue on GitHub, filled in with your versions"
OPENED = "Opened a bug report in your browser — nothing is sent until you submit it."
OPEN_LOG_LABEL = "Open &log folder"
OPEN_LOG_BUTTON = "Open log folder"
DIALOG_TITLE = "Report a bug"

#: Where the log is, as anyone's machine spells it (no user name in it).
LOG_HINT = r"%APPDATA%\RYOS\logs\ryos.log"

#: Browsers and GitHub cope with long links, but not endlessly; the body
#: here is a few hundred characters, and this keeps it so.
MAX_URL = 6000


def log_note(*, logging_on: bool) -> str:
    """What the bug-report dialog says about the log. Either way it keeps the
    warning: the log can hold script paths and output."""
    if logging_on:
        return ("If the log would help, attach ryos.log from this folder (drag "
                "it into the issue). Have a look first: it can contain your "
                "script paths and output.")
    return ("RYOS isn't writing a log at the moment. To record one, turn on "
            "Options… → Logging → Write a log file, then make the bug happen "
            "again. An older log may still be in the folder: have a look "
            "first, it can contain your script paths and output.")


def open_failed(path: str) -> str:
    return f"Couldn't open the log folder: {path}"


def log_lines(log_dir: str, *, which: str, window: bool, cli: bool,
              mcp: bool) -> list[str]:
    """The log folder, then one line per log this download writes and who
    writes it. The flags say what the caller wants listed; the download
    decides what exists at all: RYOS Agent has no window, and a Windows build
    without AI agents has no MCP server."""
    rows = []
    if window and which != buildinfo.AGENT:
        rows.append(("ryos.log", "the window"))
    if cli:
        rows.append(("ryos-cli.log", "the command line"))
    if mcp and buildinfo.agents_offered(which):
        rows.append(("ryos-mcp.log", "AI agents (ryos-cli mcp)"))
    width = max((len(name) for name, _ in rows), default=0)
    return [f"Logs: {log_dir}",
            *[f"  {name.ljust(width)}  {who}" for name, who in rows]]


def environment(version: str, *, frozen: bool, os_name: str, python: str,
                qt: str, theme: str, layout: str,
                build: str | None = None) -> list[tuple[str, str]]:
    """The facts a bug report needs, as (label, value) pairs. ``build`` is
    which download and a build's commit (buildinfo.describe_build); without
    it, frozen or not says."""
    which = build or ("Windows build" if frozen else "from source")
    return [
        ("RYOS", f"{version} ({which})"),
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
        "_If it helps, attach the log (in RYOS: Help → Open log folder), "
        f"`{LOG_HINT}` — have a look first: it can contain your script paths "
        "and output._",
    ]
    return "\n".join(lines)


def new_issue_url(*, label: str, body: str, title: str = "") -> str:
    """A link that opens a new, filled-in issue. Shared by the bug report and
    the suggestion, so both drop the body the same way when it is too long:
    the label (and title) still arrive, the link never breaks."""
    fields = {"labels": label, **({"title": title} if title else {})}
    url = f"{NEW_ISSUE}?" + urlencode({**fields, "body": body})
    if len(url) > MAX_URL:
        url = f"{NEW_ISSUE}?" + urlencode(fields)
    return url


def issue_url(env: list[tuple[str, str]]) -> str:
    """The link that opens a new, filled-in bug issue."""
    return new_issue_url(label="bug", body=issue_body(env))
