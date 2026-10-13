"""Which download this RYOS is: the Windows build (with or without AI
agents), RYOS Agent, or the source.

A build writes ``ryos/_build_info.py`` (``VARIANT = "windows"``,
``"windows-ai"`` or ``"agent"``) for the length of the build and removes it
after (``setup_cxfreeze.py``); without it, RYOS is running from source. The
variant shows in ``ryos-cli --version`` and the bug report's environment, an
update notice names the zip that replaces *this* download -- never another --
and it decides whether the MCP server and the "Available to agents" checkbox
are there.

The IDs are what each build's update notice names, so they cannot change once
a build carrying them is released (2.3.0 is the first).
"""

from __future__ import annotations

import importlib
import re

#: Shown in Properties -> Details of both exes (setup_cxfreeze.py). NFC
#: literals: the version resource is UTF-16, but a decomposed form would still
#: render differently in some tools.
COMPANY = "Zenitus (Lê Quang Vũ)"
COPYRIGHT = "© 2026 Lê Quang Vũ (Zenitus)"

_COMMIT = re.compile(r"[0-9a-f]{7,40}(-dirty)?")

WINDOWS = "windows"             # RYOS.exe + ryos-cli.exe, no MCP server
WINDOWS_AI = "windows-ai"       # RYOS.exe + ryos-cli.exe with the MCP server
AGENT = "agent"                 # ryos-cli.exe alone, with the MCP server, no Qt
PORTABLE = "portable"           # the source; MCP is the optional extra

#: The release asset each variant updates to.
DOWNLOADS = {WINDOWS: "RYOS-windows.zip", WINDOWS_AI: "RYOS-windows-ai.zip",
             AGENT: "RYOS-agent.zip", PORTABLE: "RYOS-portable.zip"}
_WORDS = {WINDOWS: "Windows build", WINDOWS_AI: "Windows build with AI agents",
          AGENT: "RYOS Agent", PORTABLE: "from source"}

#: Where setup_cxfreeze.py builds each frozen variant.
BUILD_FOLDERS = {WINDOWS: "dist/cxfreeze", WINDOWS_AI: "dist/cxfreeze-ai",
                 AGENT: "dist/cxfreeze-agent"}

#: The frozen variants that carry the MCP server (the SDK inside ryos-cli.exe).
_WITH_MCP = {WINDOWS_AI, AGENT}


def variant() -> str:
    """This RYOS's variant; ``portable`` (from source) without a build's file."""
    try:
        found = importlib.import_module("ryos._build_info").VARIANT
    except (ImportError, AttributeError):
        return PORTABLE
    return found if found in DOWNLOADS else PORTABLE


def download_name(which: str | None = None) -> str:
    return DOWNLOADS[which or variant()]


def describe(which: str | None = None) -> str:
    """'Windows build', 'Windows build with AI agents', 'RYOS Agent' or
    'from source'."""
    return _WORDS[which or variant()]


def bundles_mcp(which: str) -> bool:
    """Whether a frozen build of ``which`` carries the MCP SDK."""
    return which in _WITH_MCP


def agents_offered(which: str | None = None) -> bool:
    """Whether this RYOS offers AI agents at all: every download but the
    Windows build without them. From source the SDK is an optional extra, so
    the choice is offered there too. Where they are not offered, the
    "Available to agents" checkbox is hidden -- the flag itself stays, so
    moving between downloads never loses it."""
    return (which or variant()) != WINDOWS


def commit() -> str | None:
    """The commit this build was made from ('1a2b3c4', plus '-dirty' for a
    build of a tree with uncommitted changes); None from source or when the
    build file carries none."""
    if variant() == PORTABLE:
        return None
    try:
        found = importlib.import_module("ryos._build_info").COMMIT
    except (ImportError, AttributeError):
        return None
    if isinstance(found, str) and _COMMIT.fullmatch(found):
        return found
    return None


def describe_build(which: str | None = None) -> str:
    """``describe()`` plus the build's commit, for ``--version`` and the bug
    report ('Windows build with AI agents, 1a2b3c4'). From source, exactly
    'from source'."""
    words = describe(which)
    found = commit()
    return f"{words}, {found}" if found else words


def git_commit(root, run=None) -> str | None:
    """HEAD's short commit in ``root``, with '-dirty' when tracked files have
    changes. Build time only (``setup_cxfreeze.py``); None when git cannot
    say. ``run`` is ``subprocess.run`` unless a test passes another."""
    import subprocess
    run = run or subprocess.run
    try:
        head = run(["git", "rev-parse", "--short=7", "HEAD"], cwd=root,
                   capture_output=True, text=True, timeout=10,
                   encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    found = (head.stdout or "").strip()
    if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{7,40}", found):
        return None
    try:
        status = run(["git", "status", "--porcelain", "--untracked-files=no"],
                     cwd=root, capture_output=True, text=True, timeout=10,
                     encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return found
    if status.returncode == 0 and (status.stdout or "").strip():
        return found + "-dirty"
    return found


def build_info_source(which: str, commit: str | None = None) -> str:
    """The text of ``ryos/_build_info.py`` for a build of ``which``."""
    if which not in BUILD_FOLDERS:
        raise ValueError(f"unknown build variant {which!r}")
    text = ('"""Written by setup_cxfreeze.py for the length of a build; see '
            'ryos/buildinfo.py."""\n'
            f"VARIANT = {which!r}\n")
    if commit is not None:
        if not _COMMIT.fullmatch(commit):
            raise ValueError(f"not a commit: {commit!r}")
        text += f"COMMIT = {commit!r}\n"
    return text
