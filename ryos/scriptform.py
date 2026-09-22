"""Validation for the add/edit-script form, independent of any toolkit.

`ui/dialogs.ScriptDialog._save` decided these inline, between `messagebox`
calls, so none of them could be tested without a display — `dialogs.py` is
1,864 lines with no unit coverage at all (docs/tech-debt-2026-09-21.md item 5).
Both front-ends now ask this module and render the answer their own way.

Three outcomes rather than two, because one of the rules is a *question*: a
path that does not exist yet is often correct (a script about to be written,
a network share that is offline), so the form asks rather than refusing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .quickrun import _is_inside

OK = "ok"            # save it
REFUSE = "refuse"    # cannot be saved; say why
CONFIRM = "confirm"  # probably wrong; ask before saving


@dataclass(frozen=True)
class Check:
    """The verdict on a form, with the words to show for it.

    `severity` matters only for REFUSE: "warning" for a field the user has
    simply not filled in yet, "error" for something actually wrong with what
    they entered. The caller maps it onto its own dialog.
    """

    kind: str
    title: str = ""
    message: str = ""
    severity: str = "error"

    @property
    def ok(self) -> bool:
        return self.kind == OK

    @property
    def needs_confirmation(self) -> bool:
        return self.kind == CONFIRM


_OK = Check(OK)


def resolve_path(*, base_dir: str, relative: str, absolute: str,
                 use_relative: bool) -> str:
    """The path the form is really pointing at.

    When a group has a base directory the form offers a relative box instead
    of an absolute one; leading separators are stripped so "/sub/x.py" joins
    under the base rather than escaping to the filesystem root.
    """
    if use_relative and base_dir:
        rel = relative.strip().lstrip("/\\")
        return os.path.normpath(os.path.join(base_dir, rel)) if rel else ""
    return absolute.strip()


def validate(*, name: str, path: str, interpreter: str, base_dir: str = "",
             group_name: str = "", path_exists: bool = True) -> Check:
    """Whether this script can be saved.

    ``path_exists`` is passed in rather than looked up, so this stays pure and
    a test does not need to touch the filesystem.

    Order matters and is the order a user would expect: the fields they must
    fill first, then where the path points, then whether it is there yet.
    """
    name = name.strip()
    path = path.strip()
    interpreter = interpreter.strip()

    if not name:
        return Check(REFUSE, "Missing Info", "Name is required.",
                     severity="warning")
    if not path and not interpreter:
        # An interpreter with no path is legitimate -- "python -c" style
        # entries, and launchers that are nothing but a command.
        return Check(REFUSE, "Missing Info",
                     "Path is required when no interpreter is set.",
                     severity="warning")
    if path and base_dir and not _is_inside(path, base_dir):
        return Check(REFUSE, "Path outside group directory",
                     f"The path\n{path}\nis outside the base directory for "
                     f"group '{group_name}':\n{base_dir}")
    if path and not interpreter and not path_exists:
        # A question, not a refusal: the file may not be written yet, or may
        # live on a share that is currently offline.
        return Check(CONFIRM, "Warning",
                     f"File not found:\n{path}\n\nSave anyway?")
    return _OK
