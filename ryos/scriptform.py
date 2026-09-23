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
from .quickrun import _is_inside

from . import verdict
from .verdict import CONFIRM, OK, REFUSE

#: Re-exported so callers can compare `check.kind` without importing two
#: modules. Named in __all__ because they are otherwise unused here, and a
#: lint pass would remove them.
__all__ = ["CONFIRM", "Check", "DEFAULT_OPTION", "OK", "REFUSE",
           "param_options", "resolve_path", "validate"]

#: The verdict shape is shared with the theme editor and the launch preflight
#: (ryos/verdict.py). Kept under the name this module already used, so its
#: callers and tests read unchanged.
Check = verdict.Verdict


_OK = verdict.PROCEED


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
        return verdict.refuse("Missing Info", "Name is required.",
                              verdict.WARNING)
    if not path and not interpreter:
        # An interpreter with no path is legitimate -- "python -c" style
        # entries, and launchers that are nothing but a command.
        return verdict.refuse(
            "Missing Info", "Path is required when no interpreter is set.",
            verdict.WARNING)
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


#: The picker key for "use the script's own parameters".
DEFAULT_OPTION = "__default__"


def param_options(default_params: str, presets) -> list[tuple[str, str, str]]:
    """What the parameter picker offers: ``(key, label, params)`` per row.

    The script's own parameters come first under "Default", then each saved
    preset. A preset whose label is just its parameters shows the parameters
    once rather than twice -- "--fast" labelled "--fast" is one idea, not two.
    """
    options = [(DEFAULT_OPTION, "Default", default_params)]
    for pid, label, params in presets:
        options.append((str(pid), label, params))
    return [(key, params if label == params else label, params)
            for key, label, params in options]
