"""Managing scripts without the window: what `ryos-cli add`, `edit`,
`remove`, `expose` and `preset` do, toolkit-free.

The script dialog's own rules decide: `scriptform.validate` and
`scriptform.name_from_path`, the interpreter left blank for detection at run
time, groups created on first use. On top of them, what a command line needs
and a dialog does not:

* **A name is unique in its group** (`add`, `edit`). The database allows a
  second "backup" in Tools, which could then be named only by its #id.
* **A question becomes a refusal** unless the caller says yes: `validate`
  asks about a missing file or a path outside the group's base folder, and
  a command line has no one to ask. `confirmed=True` is `--yes`.

Everything that refuses raises `ManageError`, in words for the person at
the terminal. Whether to let agents run something (`set_exposed`) is
decided here; whether the caller may decide it -- a terminal, or --yes -- is
the command line's (docs/archive/release-2.3.0.md, A2).

The window uses this module too, for the actions that cover several items at
once: a group tab's "Make all in this group available to agents…" and select
mode's agent buttons share ``group_members`` / ``targets_of``,
``plan_exposure`` and the wording with ``ryos-cli expose --group``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import scriptform
from .db import ScriptDB
from .headless import PIPELINE, SCRIPT, Target


class ManageError(Exception):
    """A change refused, in words for the person at the terminal."""


def _names_in(db: ScriptDB, group: str, *, but: int | None = None) -> set[str]:
    return {row[1] for row in db.list_all()
            if (row[8] or "") == group and row[0] != but}


def _check_name(db: ScriptDB, name: str, group: str, *, but: int | None = None) -> None:
    if not name.strip():
        raise ManageError("A script needs a name.")
    if name in _names_in(db, group, but=but):
        where = f"group {group!r}" if group else "Ungrouped"
        raise ManageError(f"{where} already has a script named {name!r}. "
                          "Give it another --name.")


def _check_form(*, name: str, path: str, group: str, base: str, confirmed: bool) -> None:
    verdict = scriptform.validate(name=name, path=path, interpreter="", base_dir=base,
                                  group_name=group, path_exists=os.path.exists(path))
    if verdict.kind == scriptform.REFUSE:
        raise ManageError(f"{verdict.title}: {verdict.message}".replace("\n", " "))
    if verdict.needs_confirmation and not confirmed:
        question = verdict.message.replace("\n", " ").rsplit("?", 1)[0]
        raise ManageError(f"{question}? Add --yes to do it anyway.")


def _work_dir(work_dir: str | None) -> str:
    if not work_dir:
        return ""
    folder = os.path.abspath(work_dir)
    if not os.path.isdir(folder):
        raise ManageError(f"No folder {folder}: give --workdir an existing folder.")
    return folder


def add_script(db: ScriptDB, file: str, *, name: str | None = None, group: str = "",
               work_dir: str | None = None, params: str = "", expose: bool = False,
               confirmed: bool = False) -> Target:
    """Add a script, as the dialog would. Its interpreter is detected when it
    runs. ``expose`` lets agents run it -- the caller has already made sure a
    person asked for that."""
    path = os.path.abspath(file)
    name = (name if name is not None else scriptform.name_from_path(path)).strip()
    group = group.strip()
    base = db.get_group_base_dir(group) if group else ""
    _check_name(db, name, group)
    _check_form(name=name, path=path, group=group, base=base, confirmed=confirmed)
    folder = _work_dir(work_dir)
    if group and group not in db.list_groups():
        db.create_group(group)
    sid = db.add(name, path, params.strip(), "", group, env_vars=None, work_dir=folder)
    if expose:
        db.set_agent_exposed(SCRIPT, sid, True)
    return Target(SCRIPT, sid, name, group)


def edit_script(db: ScriptDB, target: Target, *, name: str | None = None,
                group: str | None = None, work_dir: str | None = None,
                params: str | None = None, confirmed: bool = False) -> Target:
    """Change what was given and leave the rest -- environment, presets,
    launcher flag and agents' access untouched."""
    rec = db.get(target.item_id)
    if not rec:
        raise ManageError(f"{target.ref!r} is gone.")
    _id, old_name, path, old_params, interp, old_group, _tmp, _env, old_wd = rec[:9]
    name = old_name if name is None else name.strip()
    group = (old_group or "") if group is None else group.strip()
    if (name, group) != (old_name, old_group or ""):
        _check_name(db, name, group, but=target.item_id)
    if group != (old_group or ""):
        _check_form(name=name, path=path, group=group,
                    base=db.get_group_base_dir(group), confirmed=confirmed)
        if group and group not in db.list_groups():
            db.create_group(group)
    folder = (old_wd or "") if work_dir is None else _work_dir(work_dir)
    db.update(target.item_id, name, path,
              old_params if params is None else params.strip(), interp or "", group,
              work_dir=folder)
    return Target(SCRIPT, target.item_id, name, group)


def remove_script(db: ScriptDB, target: Target) -> None:
    """Delete a script, with its presets, schedule and pipeline steps (as the
    window's Delete does); its run history stays."""
    if not db.get(target.item_id):
        raise ManageError(f"{target.ref!r} is gone.")
    db.delete(target.item_id)


def pipelines_using(db: ScriptDB, target: Target) -> list[str]:
    """The pipelines a script's removal takes a step out of: said before."""
    return db.pipelines_using([target.item_id]) if target.kind == SCRIPT else []


def set_exposed(db: ScriptDB, target: Target, on: bool) -> bool:
    """Let agents run a script or pipeline, or stop. True when it changed."""
    was = db.is_agent_exposed(target.kind, target.item_id)
    db.set_agent_exposed(target.kind, target.item_id, on)
    return was != on


# -- letting agents run several things at once -------------------------------
#
# A group is only a way to pick items: ticking "Available to agents" on what is
# in it *now*. Nothing is stored about the group, so nothing becomes available
# later by being moved into it.

EXPOSE_TITLE = "Available to agents"


@dataclass(frozen=True)
class Exposure:
    """What turning agents' access on (or off) for some items would do."""

    on: bool
    change: tuple[Target, ...]
    unchanged: tuple[Target, ...]


def require_group(db: ScriptDB, group: str) -> str:
    """``group`` itself when it exists (an exact match; Ungrouped is not a group
    here), otherwise a refusal naming the ones that do."""
    groups = db.list_groups()
    if group in groups:
        return group
    if not groups:
        raise ManageError(f"No group named {group!r}: there are no groups yet.")
    raise ManageError(f"No group named {group!r}. The groups are: {', '.join(groups)}.")


def group_members(db: ScriptDB, group: str) -> list[Target]:
    """The group's scripts, then its pipelines, as they are now."""
    require_group(db, group)
    members = [Target(SCRIPT, row[0], row[1], group)
               for row in db.list_all() if (row[8] or "") == group]
    members += [Target(PIPELINE, pid, name, group)
                for pid, name, *_ in db.list_pipelines(group)]
    return members


def targets_of(db: ScriptDB, items) -> list[Target]:
    """(kind, id) pairs -- what select mode has ticked -- as targets. Items
    that are gone are skipped and repeats dropped."""
    found: list[Target] = []
    seen: set[tuple[str, int]] = set()
    for kind, item_id in items:
        if (kind, item_id) in seen:
            continue
        seen.add((kind, item_id))
        if kind == PIPELINE:
            ident = db.pipeline_identity(item_id)
            if ident:
                found.append(Target(PIPELINE, item_id, ident[0], ident[1]))
        else:
            rec = db.get(item_id)
            if rec:
                found.append(Target(SCRIPT, item_id, rec[1], rec[5] or ""))
    return found


def plan_exposure(db: ScriptDB, targets, on: bool) -> Exposure:
    """Split ``targets`` into what would change and what is already so."""
    exposed = {SCRIPT: db.agent_exposed_ids(SCRIPT),
               PIPELINE: db.agent_exposed_ids(PIPELINE)}
    change: list[Target] = []
    unchanged: list[Target] = []
    for t in targets:
        was = t.item_id in exposed.get(t.kind, set())
        (unchanged if was == on else change).append(t)
    return Exposure(on, tuple(change), tuple(unchanged))


def apply_exposure(db: ScriptDB, plan: Exposure) -> int:
    """Carry the plan out. How many changed."""
    for t in plan.change:
        db.set_agent_exposed(t.kind, t.item_id, plan.on)
    return len(plan.change)


def named(targets) -> str:
    """'Tools/backup, Tools/sync (pipeline)'."""
    return ", ".join(t.ref + (" (pipeline)" if t.kind == PIPELINE else "")
                     for t in targets)


def _already(n: int, verb_one: str, verb_many: str) -> str:
    return f"{n} already {verb_one if n == 1 else verb_many}."


def exposure_question(plan: Exposure) -> str:
    """The one question before agents may run something: only what changes."""
    n = len(plan.change)
    text = f"Will make {n} available to agents: {named(plan.change)}."
    if plan.unchanged:
        text += " " + _already(len(plan.unchanged), "is", "are")
    return text + " Go ahead?"


def nothing_new(plan: Exposure, where: str | None) -> str:
    """Said when the plan changes nothing. ``where`` is the group, or None for
    select mode."""
    total = len(plan.unchanged)
    if plan.on:
        if total == 1:
            return f"{plan.unchanged[0].ref} is already available to agents."
        if where is None:
            return f"All {total} selected are already available to agents."
        return f"All {total} in {where} are already available to agents."
    if total == 1:
        return f"{plan.unchanged[0].ref} was not available to agents."
    if where is None:
        return "None of the selected were available to agents."
    return f"None in {where} was available to agents."


def exposure_done(plan: Exposure, where: str | None) -> str:
    """Said after the plan was applied."""
    n = len(plan.change)
    if plan.on:
        text = f"Made {n} available to agents: {named(plan.change)}."
        if plan.unchanged:
            text += " " + _already(len(plan.unchanged), "was", "were")
        return text
    place = f"in {where}" if where is not None else "selected"
    return (f"{n} {place} {'is' if n == 1 else 'are'} "
            "no longer available to agents.")


def empty_group(group: str) -> str:
    return f"{group} has no scripts or pipelines yet."


def add_preset(db: ScriptDB, target: Target, label: str, params: str) -> None:
    label = label.strip()
    if not label:
        raise ManageError("A preset needs a label.")
    presets = [(lbl, p) for _pid, lbl, p in db.list_param_presets(target.item_id)]
    if any(lbl == label for lbl, _p in presets):
        raise ManageError(f"{target.ref!r} already has a preset {label!r}: "
                          "remove it first to change it.")
    db.replace_param_presets(target.item_id, [*presets, (label, params.strip())])


def remove_preset(db: ScriptDB, target: Target, label: str) -> None:
    presets = [(lbl, p) for _pid, lbl, p in db.list_param_presets(target.item_id)]
    kept = [(lbl, p) for lbl, p in presets if lbl != label]
    if len(kept) == len(presets):
        have = ", ".join(repr(lbl) for lbl, _p in presets) or "none"
        raise ManageError(f"{target.ref!r} has no preset {label!r} (it has: {have}).")
    db.replace_param_presets(target.item_id, kept)


def history(db: ScriptDB, target: Target | None = None, limit: int = 20) -> list:
    """Run-history rows, newest first: everything, or one script's or
    pipeline's (a pipeline's whole runs and its steps)."""
    if target is None:
        return db.list_runs(limit=limit)
    if target.kind == PIPELINE:
        return db.list_runs(pipeline_id=target.item_id, limit=limit)
    return db.list_runs(script_id=target.item_id, limit=limit)
