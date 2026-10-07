"""A script that lives outside its group's base folder — toolkit-free.

The base folder is what a card's path is shown relative to and what Quick Run
searches. A script (or the working folder it runs in) that is somewhere else
is usually a slip, so the window says so: a badge, a detail row and a note at
the top of the run. This is the only place containment is decided; it looks at
the strings only and never touches the disk.
"""

from __future__ import annotations

from .quickrun import _is_inside

FILE = "file"
WORKING_FOLDER = "working folder"


def outside_parts(path: str, work_dir: str, base: str) -> tuple[str, ...]:
    """Which of ``("file", "working folder")`` lie outside ``base``.

    Nothing is outside when the group has no base folder. An empty path is not
    checked, and a working folder only when it is set: blank means "run where
    the script is", which `interpreter.build_run_spec` also treats as unset.
    A relative working folder counts as outside: it is resolved against
    RYOS's own folder, not the base.
    """
    if not base:
        return ()
    parts = []
    if path and not _is_inside(path, base):
        parts.append(FILE)
    wd = (work_dir or "").strip()
    if wd and not _is_inside(wd, base):
        parts.append(WORKING_FOLDER)
    return tuple(parts)


def badge_tooltip(parts: tuple[str, ...], base: str) -> str:
    what = ("Script file and working folder are" if len(parts) > 1
            else "Working folder is" if parts == (WORKING_FOLDER,)
            else "Script file is")
    return f"{what} outside the group's base folder:\n{base}"


def pipeline_badge_tooltip(step_numbers: tuple[int, ...], base: str) -> str:
    if len(step_numbers) == 1:
        lead = f"Step {step_numbers[0]} runs a script"
    else:
        lead = f"Steps {', '.join(str(n) for n in step_numbers)} run scripts"
    return f"{lead} outside the group's base folder:\n{base}"


def run_note(parts: tuple[str, ...], path: str, work_dir: str, base: str) -> str:
    """The one line put at the top of a run, or "" when nothing is outside."""
    if not parts:
        return ""
    shown = []
    if FILE in parts:
        shown.append(f"file: {path}")
    if WORKING_FOLDER in parts:
        shown.append(f"working folder: {(work_dir or '').strip()}")
    return (f"Note: runs outside the group's base folder {base} "
            f"({'; '.join(shown)})\n")


def facts_value(parts: tuple[str, ...]) -> str:
    if len(parts) > 1:
        return "File, working folder"
    return "Working folder" if parts == (WORKING_FOLDER,) else "File"


def step_label(step_numbers: tuple[int, ...]) -> str:
    """'Step 2' / 'Steps 2, 4' — the detail row's value."""
    word = "Step" if len(step_numbers) == 1 else "Steps"
    return f"{word} {', '.join(str(n) for n in step_numbers)}"


# --- the warning before a run ----------------------------------------------------------
# Asked before a run started from the window, never for a scheduled, command
# line or agent run: nobody is there to answer. The note in the output stays
# either way.

#: The setting that turns the warning off (Options, or the box in the warning).
SETTING = "warn_outside_base"
WARN_TITLE = "Run outside the base folder?"
RUN_ANYWAY = "Run anyway"
DONT_WARN = "Don't warn me about this again"


def script_outside(db, script_id: int) -> tuple[tuple[str, ...], str, str, str]:
    """(parts, path, work_dir, base) for a stored script; parts is () when
    nothing is outside, or the script is gone."""
    rec = db.get(script_id)
    if not rec:
        return (), "", "", ""
    path, group, work_dir = rec[2] or "", rec[5] or "", rec[8] or ""
    base = db.get_group_base_dir(group)
    return outside_parts(path, work_dir, base), path, work_dir, base


def pipeline_outside(db, pipeline_id: int, group: str) -> tuple[tuple[int, ...], str]:
    """(step numbers outside, base) for a pipeline in ``group``."""
    base = db.get_group_base_dir(group)
    steps = tuple(i for i, row in enumerate(db.list_pipeline_steps(pipeline_id), 1)
                  if outside_parts(row[3], row[9] if len(row) > 9 else "", base))
    return steps, base


def should_warn(settings: dict, outside) -> bool:
    return bool(outside) and bool(settings.get(SETTING, True))


def warning_text(name: str, parts: tuple[str, ...], path: str, work_dir: str,
                 base: str) -> str:
    shown = []
    if FILE in parts:
        shown.append(f"File: {path}")
    if WORKING_FOLDER in parts:
        shown.append(f"Working folder: {(work_dir or '').strip()}")
    return (f"\u201c{name}\u201d runs outside its group's base folder:\n{base}\n\n"
            + "\n".join(shown)
            + "\n\nThat's usually a slip — a script copied or moved from "
              "another project. Run it anyway?")


def pipeline_warning_text(name: str, steps: tuple[int, ...], base: str) -> str:
    which = (f"Step {steps[0]} runs a script" if len(steps) == 1
             else f"Steps {', '.join(str(n) for n in steps)} run scripts")
    return (f"In \u201c{name}\u201d, {which} outside the group's base folder:\n"
            f"{base}\n\nRun the pipeline anyway?")


def after_warning(settings: dict, run: bool, dont_warn: bool) -> tuple[bool, bool]:
    """(run it, save settings) for an answer to the warning.

    Updates ``settings`` in place. "Don't warn me again" counts only with
    Run anyway: Cancel -- or closing the box any other way -- changes nothing.
    """
    if not run:
        return False, False
    if dont_warn:
        settings[SETTING] = False
        return True, True
    return True, False
