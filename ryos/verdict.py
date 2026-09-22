"""One shape for "can this proceed, and if not what do I tell the user".

Three places had grown their own copy of this — the launch preflight, the
script form, and the theme editor — each a small dataclass with a title, a
message and a severity. They are the same idea, and three copies is how the
wording and the severity conventions drift apart.

Kept toolkit-free deliberately: a verdict says *what* to tell someone, never
how to draw it. Each front-end maps `severity` onto its own dialog.
"""

from __future__ import annotations

from dataclasses import dataclass

OK = "ok"            # go ahead
REFUSE = "refuse"    # cannot proceed; say why
CONFIRM = "confirm"  # probably wrong; ask first

# Severities, in the order a UI usually escalates them.
INFO = "info"        # a limit worth knowing about, not a mistake
WARNING = "warning"  # something not filled in yet
ERROR = "error"      # something actually wrong with what was entered


@dataclass(frozen=True)
class Verdict:
    """The answer, and the words for it."""

    kind: str
    title: str = ""
    message: str = ""
    severity: str = ERROR

    @property
    def ok(self) -> bool:
        return self.kind == OK

    @property
    def needs_confirmation(self) -> bool:
        return self.kind == CONFIRM


#: The common case, hoisted so callers do not allocate one per check.
PROCEED = Verdict(OK)


def refuse(title: str, message: str, severity: str = ERROR) -> Verdict:
    return Verdict(REFUSE, title, message, severity)


def confirm(title: str, message: str) -> Verdict:
    return Verdict(CONFIRM, title, message)
