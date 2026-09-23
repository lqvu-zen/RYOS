"""What submitting the Quick Run bar does to the database.

Typing a path into the bar either reuses the script already registered for it
in that group, or registers a new one, and then runs it. The Tk bar did this
inline in `_quick_run_submit` between a message box and a card refresh; both
bars now call `ensure_script` and handle only the display around it
(docs/plans/qt-migration.md).

UI-free. Needs the database, which is why it is not in the pure `quickrun`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .interpreter import detect_interpreter


@dataclass(frozen=True)
class EnsuredScript:
    """The script a Quick Run submission resolved to, ready to launch.

    ``created`` and ``changed`` tell the caller whether the card list needs
    refreshing: a brand-new script has no card yet, and a changed one shows
    stale parameters.
    """

    script_id: int
    name: str
    params: str
    interpreter: str
    created: bool
    changed: bool


def find_script(db, abs_path: str, group: str):
    """The record already registered for this path in this group, or None.

    Matched by path *and* group: the same file in two groups is two scripts,
    each with its own parameters and history.
    """
    target = Path(abs_path)
    group = group or ""
    for rec in db.list_all():
        if Path(rec[2]) == target and (rec[8] or "") == group:
            return rec
    return None


def ensure_script(db, abs_path: str, group: str, typed_params: str,
                  params_explicit: bool) -> EnsuredScript:
    """Reuse or register the script for ``abs_path``, and decide its parameters.

    For an existing script, parameters typed in the bar win over the saved
    ones, and are remembered as a preset so they can be picked again later --
    once, not every time the same thing is typed. Parameters that were not
    typed leave the saved ones alone: running "build.py" must not wipe
    "build.py --release" that was saved last week.
    """
    group = group or ""
    rec = find_script(db, abs_path, group)
    if rec is not None:
        script_id, name = rec[0], rec[1]
        saved_params, interpreter = rec[3] or "", rec[4] or ""
        if not params_explicit:
            return EnsuredScript(script_id, name, saved_params, interpreter,
                                 created=False, changed=False)
        presets = db.list_param_presets(script_id)
        if typed_params not in {p[2] for p in presets}:
            db.replace_param_presets(
                script_id,
                [(p[1], p[2]) for p in presets] + [(typed_params, typed_params)])
        changed = typed_params != saved_params
        if changed:
            db.update(script_id, name, abs_path, typed_params, interpreter, group)
        return EnsuredScript(script_id, name, typed_params, interpreter,
                             created=False, changed=True)

    interpreter = detect_interpreter(abs_path)
    name = Path(abs_path).stem
    script_id = db.add(name=name, path=abs_path, params=typed_params,
                       interpreter=interpreter, group_name=group)
    if typed_params:
        db.replace_param_presets(script_id, [(typed_params, typed_params)])
    return EnsuredScript(script_id, name, typed_params, interpreter,
                         created=True, changed=True)


# --- from typed text to a file ------------------------------------------------

#: What a submission turned into.
NOTHING = "nothing"   # nothing typed, or only whitespace: do nothing, say nothing
ERROR = "error"       # nothing matched (or the path escaped the folder): say why
CHOOSE = "choose"     # several files match: ask which
RUN = "run"           # exactly one file


@dataclass(frozen=True)
class SubmitPlan:
    """How to proceed with what was typed into the bar."""

    kind: str
    params: str = ""
    params_explicit: bool = False
    abs_path: str = ""
    candidates: tuple = ()
    error: str = ""


def plan_submit(raw: str, base_dir: str) -> SubmitPlan:
    """Parse and resolve what was typed, before anything is written or run.

    Pure apart from the filesystem lookup inside `quickrun.resolve`, and the
    same for both bars -- the Tk bar did this inline between message boxes.
    """
    from .quickrun import parse_input, resolve

    text = (raw or "").strip()
    if not text:
        return SubmitPlan(NOTHING)
    query, params, explicit = parse_input(text)
    if not query:
        return SubmitPlan(NOTHING)
    abs_path, candidates, err = resolve(base_dir, query)
    if err:
        return SubmitPlan(ERROR, params, explicit, error=err)
    if candidates:
        return SubmitPlan(CHOOSE, params, explicit,
                          candidates=tuple(candidates))
    return SubmitPlan(RUN, params, explicit, abs_path=abs_path or "")


def chosen_path(base_dir: str, rel: str) -> str:
    """The absolute path for a candidate picked from the "which one?" list."""
    return str(Path(base_dir) / rel)
