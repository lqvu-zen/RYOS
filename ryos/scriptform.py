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

import json
import os
from dataclasses import dataclass, field

from .interpreter import format_env_text, parse_env_text
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


# --- the rest of the form: wording, small rules, load and save ------------------
# Both dialogs draw these fields; what they offer, how a stored script loads
# into them and how they are written back are decided here, once.

INTERPRETER_CHOICES = ("cmd /c", "powershell -File", "pwsh -File", "python",
                       "node", "bash")
INTERPRETER_HINT = "Leave blank for auto-detection, or pick a preset"
TEMP_PARAM_LABEL = "Ask for a temporary parameter on each run (not saved)"
LAUNCHER_LABEL = "Launcher — opens an app/project; don't keep in Running"
ENV_HINT = "One KEY=value per line; blank to inherit only the system environment"
DELETE_PROMPT = ("Delete", "Delete this script?")
FIRST_GROUP_PROMPT = ("Create a Group First",
                      "You have no groups yet.\nEnter a group name to continue:")


def relative_under_base(path: str, base: str) -> str | None:
    """``path`` relative to ``base`` if it is strictly inside it, else None."""
    if not path or not base:
        return None
    norm_path = os.path.normcase(os.path.normpath(path))
    norm_base = os.path.normcase(os.path.normpath(base))
    if norm_path == norm_base or not norm_path.startswith(norm_base + os.sep):
        return None
    return os.path.normpath(path)[len(os.path.normpath(base)):].lstrip(os.sep)


def relative_field(path: str, base_dir: str) -> str:
    """What the relative box shows for ``path`` under ``base_dir``.

    A path outside the base shows just its file name -- a starting point to
    correct, rather than a path that would silently escape the folder.
    """
    rel = relative_under_base(path, base_dir)
    if rel is not None:
        return rel
    return os.path.basename(path) if path else ""


def browse_refusal(path: str, base_dir: str) -> "Check | None":
    """Why a browsed-to file cannot be used for a group with a base folder."""
    if base_dir and not _is_inside(path, base_dir):
        return Check(REFUSE, "Path outside group directory",
                     f"The selected file\n{path}\nis outside the base "
                     f"directory:\n{base_dir}")
    return None


def name_from_path(path: str) -> str:
    """The name suggested for a browsed-to file: its stem."""
    return os.path.splitext(os.path.basename(path))[0] if path else ""


def with_preset(presets: list, params: str) -> "list | None":
    """``presets`` plus one for ``params``, or None when there is nothing new."""
    params = params.strip()
    if not params or any(p[1] == params for p in presets):
        return None
    return [*presets, (params, params)]


@dataclass
class ScriptForm:
    """Everything the add/edit dialog edits, as plain values."""

    name: str = ""
    path: str = ""
    params: str = ""
    interpreter: str = ""
    group: str = ""
    temp_param: bool = False
    detached: bool = False
    work_dir: str = ""
    env_text: str = ""
    presets: list = field(default_factory=list)     # [(label, params)]


def load_form(db, script_id: "int | None", default_group: str = "") -> ScriptForm:
    """The form for an existing script, or a blank one in ``default_group``."""
    if not script_id:
        return ScriptForm(group=default_group)
    rec = db.get(script_id)
    if not rec:
        return ScriptForm(group=default_group)
    _id, name, path, params, interp, grp, temp_param, env_vars, work_dir = rec[:9]
    return ScriptForm(
        name=name or "", path=path or "", params=params or "",
        interpreter=interp or "", group=grp or "",
        temp_param=bool(temp_param), detached=bool(db.is_detached(script_id)),
        work_dir=work_dir or "", env_text=format_env_text(env_vars),
        presets=[(label, p) for _pid, label, p in db.list_param_presets(script_id)])


def save_form(db, script_id: "int | None", form: ScriptForm) -> int:
    """Write ``form``; returns the script's id (new when it was an add).

    Environment is stored as JSON, and as "" rather than None on update:
    None means "leave untouched", which would make clearing it impossible.
    """
    pairs = parse_env_text(form.env_text)
    env_vars = json.dumps(pairs) if pairs else ""
    args = (form.name.strip(), form.path.strip(), form.params.strip(),
            form.interpreter.strip(), form.group.strip(),
            int(form.temp_param), int(form.detached))
    if script_id:
        db.update(script_id, *args, env_vars=env_vars,
                  work_dir=form.work_dir.strip())
    else:
        script_id = db.add(*args, env_vars=env_vars or None,
                           work_dir=form.work_dir.strip())
    db.replace_param_presets(script_id, [(label, p) for label, p in form.presets])
    return script_id


# --- running a script with parameters -----------------------------------------------
# The card's preset drop-down, the ask-each-run prompt, and ▶+ "run with
# parameter". Shared by the Tk and Qt cards.

NO_PARAMS_LABEL = "(no parameters)"


def card_param_choices(params: str, presets) -> tuple[list, str] | None:
    """(entries, selected) for a card's preset drop-down, or None for no drop-down.

    Offered only when the script has presets. "(no parameters)" always comes
    first, so a script can be run bare whatever its presets say. The script's
    saved parameters are selected when they are one of the entries.
    """
    if not presets:
        return None
    entries = [NO_PARAMS_LABEL] + [p[2] for p in presets if p[2] != ""]
    return entries, (params if params and params in entries else NO_PARAMS_LABEL)


def params_from_choice(choice: str) -> str:
    return "" if choice == NO_PARAMS_LABEL else choice


def with_temp_param(params: str, extra: str) -> str:
    """The parameters for one run with a temporary addition."""
    return f"{params} {extra.strip()}".strip() if extra and extra.strip() else params


def temp_param_title(name: str) -> str:
    return f"Run with temp param — {name}"


RUN_WITH_PARAMS_TITLE = "Run with Parameters"


def remember_run_params(db, script_id: int, chosen: str) -> None:
    """▶+ keeps what it ran with: the script's parameters become ``chosen``,
    and ``chosen`` joins its presets if it is new."""
    rec = db.get(script_id)
    if not rec:
        return
    _id, name, path, _params, interp, group = rec[:6]
    existing = db.list_param_presets(script_id)
    if not any(p[2] == chosen for p in existing):
        db.replace_param_presets(script_id, [(p[1], p[2]) for p in existing]
                                 + [(chosen, chosen)])
    db.update(script_id, name, path, chosen, interp, group)

TEMP_PARAM_HINT = "Used for this run only — not saved. Appended to saved params."


def saved_params_line(params: str) -> str | None:
    """The temp-param prompt's reminder of what is already passed, if anything."""
    return f"Saved params: {params}" if params else None
