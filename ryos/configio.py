"""Export, import and Delete All: the wording and decisions both UIs share.

The file work itself is `ScriptDB.export_to_file` / `import_from_file`; this
module is what the user is asked and told around it, so the Tk and Qt menus
say the same thing.
"""

from __future__ import annotations

from pathlib import Path

IMPORT_TITLE = "Import Config"
IMPORT_MODE = (
    "Import Mode",
    "How should existing data in the imported groups be handled?\n\n"
    "Yes = Replace (overwrite scripts/pipelines in the imported groups)\n"
    "No  = Merge (skip duplicates by path / name)")


def export_title(group: str | None) -> str:
    return f"Export Group: {group}" if group else "Export All Groups"


def export_filename(group: str | None) -> str:
    return f"ryos_{group}.json" if group else "ryos_all.json"


def export_status(scripts: int, pipelines: int, path: str) -> str:
    return (f"Exported {scripts} script(s), {pipelines} pipeline(s) "
            f"→ {Path(path).name}")


def import_status(added: int, skipped: int) -> str:
    return f"Import done — {added} script(s) added, {skipped} skipped."


def delete_all_prompt(total: int, pipelines: int = 0) -> "tuple[str, str] | None":
    """(title, question) for Delete All, or None when there is nothing to delete.

    ``total`` must be every script in the database, because that is what
    `ScriptDB.delete_all` removes -- not the cards on screen. Counting the
    visible ones understated the loss whenever a group was selected.
    """
    if total <= 0:
        return None
    noun = "script" if total == 1 else "scripts"
    question = f"Delete all {total} {noun} in every group? This cannot be undone."
    if pipelines > 0:
        # Pipelines are kept, but every step runs a script, so none survive.
        which = "pipeline" if pipelines == 1 else f"{pipelines} pipelines"
        question += f"\n\nYour {which} will be kept, with no steps left."
    return ("Delete All", question)


def delete_all_prompt_from(db) -> "tuple[str, str] | None":
    """`delete_all_prompt`, counted from the database: every script, and the
    pipelines that will lose their steps with them."""
    ids = [row[0] for row in db.list_all()]
    return delete_all_prompt(len(ids), len(db.pipelines_using(ids)))
