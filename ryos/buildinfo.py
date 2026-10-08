"""Which download this RYOS is: the Windows build, RYOS Agent, or the source.

A build writes ``ryos/_build_info.py`` (``VARIANT = "windows"`` or
``"agent"``) for the length of the build and removes it after
(``setup_cxfreeze.py``); without it, RYOS is running from source. The variant
shows in ``ryos-cli --version`` and the bug report's environment, and an
update notice names the zip that replaces *this* download -- never another.
"""

from __future__ import annotations

import importlib

WINDOWS = "windows"
AGENT = "agent"
PORTABLE = "portable"

#: The release asset each variant updates to.
DOWNLOADS = {WINDOWS: "RYOS-windows.zip", AGENT: "RYOS-agent.zip",
             PORTABLE: "RYOS-portable.zip"}
_WORDS = {WINDOWS: "Windows build", AGENT: "RYOS Agent", PORTABLE: "from source"}


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
    """'Windows build', 'RYOS Agent' or 'from source'."""
    return _WORDS[which or variant()]


def build_info_source(which: str) -> str:
    """The text of ``ryos/_build_info.py`` for a build of ``which``."""
    if which not in DOWNLOADS:
        raise ValueError(f"unknown build variant {which!r}")
    return ('"""Written by setup_cxfreeze.py for the length of a build; see '
            'ryos/buildinfo.py."""\n'
            f"VARIANT = {which!r}\n")
