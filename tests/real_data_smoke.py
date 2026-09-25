#!/usr/bin/env python3
"""Open a COPY of the user's real RYOS data in the Qt app, and check all of it.

    uv run python tests/real_data_smoke.py            # offscreen: no window
    uv run python tests/real_data_smoke.py --visible  # window on a second screen
    uv run python tests/real_data_smoke.py --db PATH  # another database file, e.g.
                                                      # a backup or an older copy

``--db`` is how an upgrade is checked: an older database opens through the
same migrations a user's would, and the schema version before and after is
printed.

The fresh databases the other smokes build hold what the checks put there.
This one holds years of real use. It copies %APPDATA%/RYOS -- the database
through SQLite's backup API (consistent even if RYOS is running), settings,
themes -- into a throwaway folder, points APPDATA there, and builds the window
through the app's own start-up (`ryos.qtui.main.build`). Then:

* every group, script and pipeline in the database is on screen;
* every script opens in its dialog as stored, and saves back unchanged;
* every pipeline opens in the editor with all its steps;
* every schedule, and the theme and custom themes, load.

Only counts and ids are printed -- never names, paths or parameters. The
user's own folder is only read, and the run fails if anything in it changed.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROBLEMS: list = []
NOTES: list = []


def _snapshot(folder: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in folder.rglob("*") if p.is_file()} if folder.is_dir() else {}


def _copy_data(real: Path, into: Path, db_file: Path | None = None) -> None:
    into.mkdir(parents=True)
    src = db_file or real / "scripts.db"
    if src.exists():
        with sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True) as source, \
                sqlite3.connect(into / "scripts.db") as dest:
            source.backup(dest)
    for name in ("settings.json", "themes.json"):
        if (real / name).exists():
            shutil.copy2(real / name, into / name)
    if (real / "themes").is_dir():
        shutil.copytree(real / "themes", into / "themes")


def check_everything(app, win, db, settings) -> None:
    from ryos import scriptform
    from ryos.qtui.appearance import AppearanceDialog
    from ryos.qtui.pipeline import PipelineEditorDialog
    from ryos.qtui.scriptdialog import ScriptDialog
    from ryos.qtui.smalldialogs import RunHistoryDialog, ScheduleDialog
    from ryos.qtui.stylesheet import stylesheet
    from ryos.themes import palette_for

    groups = db.list_groups()
    scripts = db.list_all()
    pipelines = [p for g in [*groups, ""] for p in db.list_pipelines(g)]
    # Every pipeline row, whatever its group says -- so one filed under a group
    # that no longer exists still counts as "should be on screen".
    with sqlite3.connect(db.db_path) as conn:
        all_pipeline_ids = {r[0] for r in conn.execute("SELECT id FROM pipelines")}
    print(f"  data: {len(groups)} group(s), {len(scripts)} script(s), "
          f"{len(all_pipeline_ids)} pipeline(s), {len(db.list_schedules())} schedule(s)")

    # -- everything is on screen ------------------------------------------------------
    tabs = [k for k in win.group_tab_bar.tab_keys() if k is not None]
    if [t for t in tabs if t] != groups:
        PROBLEMS.append(f"group tabs {len(tabs)} do not match the {len(groups)} groups")
    shown_scripts = {c.drag_payload.item_id for page in win.card_lists.values()
                     for c in page.cards if c.drag_payload.kind == "script"}
    missing = sorted({r[0] for r in scripts} - shown_scripts)
    if missing:
        stray = sorted({(r[8] or "") for r in scripts if r[0] in missing})
        PROBLEMS.append(f"{len(missing)} script(s) not shown, ids {missing[:10]}; "
                        f"their group names are not groups ({len(stray)} name(s))")
    shown_pipes = {c.drag_payload.item_id for page in win.card_lists.values()
                   for c in page.cards if c.drag_payload.kind == "pipeline"}
    if all_pipeline_ids - shown_pipes:
        PROBLEMS.append(f"{len(all_pipeline_ids - shown_pipes)} pipeline(s) not shown, "
                        f"ids {sorted(all_pipeline_ids - shown_pipes)[:10]}")

    # -- every script opens as stored, and saves back unchanged ------------------------
    refused: list = []
    changed: list = []
    for rec in scripts:
        sid = rec[0]
        before = (db.get(sid), db.list_param_presets(sid), db.is_detached(sid))
        dlg = ScriptDialog(db=db, script_id=sid)
        if dlg.form() != scriptform.load_form(db, sid):
            PROBLEMS.append(f"script {sid} did not open as stored")
        warned: list = []
        dlg.warn = lambda title, text, w=warned: w.append(title)
        dlg.ask_yes_no = lambda title, text: True     # "file not found -- save anyway?"
        if not dlg.save():
            refused.append((sid, warned[-1] if warned else "?"))
        else:
            after = (db.get(sid), db.list_param_presets(sid), db.is_detached(sid))
            if after != before:
                fields = [i for i, (a, b) in enumerate(zip(after[0], before[0])) if a != b]
                changed.append((sid, fields, after[1] != before[1], after[2] != before[2]))
        dlg.deleteLater()
    if changed:
        PROBLEMS.append(f"{len(changed)} script(s) changed by an unchanged save "
                        f"(id, row fields, presets, launcher): {changed[:10]}")
    if refused:
        # Not necessarily a bug -- Tk's form refuses the same -- but worth knowing.
        NOTES.append(f"{len(refused)} script(s) the dialog would not save as they "
                     f"are (id, reason): {refused[:10]}")

    # -- every pipeline opens with its steps --------------------------------------------
    for pid, name, *_rest in pipelines:
        group = next((g for g in [*groups, ""]
                      if any(p[0] == pid for p in db.list_pipelines(g))), "")
        dlg = PipelineEditorDialog(db=db, pipeline_id=pid, name=name, group=group)
        if dlg.list.count() != len(db.list_pipeline_steps(pid)):
            PROBLEMS.append(f"pipeline {pid}: the editor showed {dlg.list.count()} "
                            f"of {len(db.list_pipeline_steps(pid))} steps")
        dlg.deleteLater()

    # -- schedules, history, themes -----------------------------------------------------
    for row in db.list_schedules():
        try:
            ScheduleDialog(db=db, script_id=row[2], pipeline_id=row[3]).deleteLater()
        except Exception as exc:                          # noqa: BLE001
            PROBLEMS.append(f"schedule {row[0]} did not open: {type(exc).__name__}")
    for rec in scripts[:50]:
        try:
            RunHistoryDialog(db=db, script_id=rec[0]).deleteLater()
        except Exception as exc:                          # noqa: BLE001
            PROBLEMS.append(f"run history of script {rec[0]} did not open: "
                            f"{type(exc).__name__}")
    customs = win.custom_themes()
    try:
        stylesheet(palette_for(settings.get("theme", "light"),
                               settings.get("accent_color"), customs))
        for name in customs:
            stylesheet(palette_for(name, None, customs))
        AppearanceDialog(settings=settings, customs=customs,
                         themes_dir=win.themes_dir()).deleteLater()
    except Exception as exc:                              # noqa: BLE001
        PROBLEMS.append(f"themes did not load: {type(exc).__name__}: {exc}")
    print(f"  checked: {len(scripts)} script dialog(s), {len(pipelines)} pipeline "
          f"editor(s), {len(db.list_schedules())} schedule(s), "
          f"{min(len(scripts), 50)} history view(s), {len(customs)} custom theme(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--visible", action="store_true",
                        help="show the window, on a second screen when there is one")
    parser.add_argument("--db", type=Path,
                        help="open a copy of this database file instead of the user's own")
    args = parser.parse_args()

    real = Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "RYOS"
    if not args.db and not (real / "scripts.db").exists():
        print(f"No RYOS data at {real}; nothing to check.")
        return 0
    before = _snapshot(real)
    extra_before = _snapshot(args.db.parent) if args.db else {}
    tmp = Path(tempfile.mkdtemp(prefix="ryos-realdata-"))
    _copy_data(real, tmp / "RYOS", args.db)
    copied = tmp / "RYOS" / "scripts.db"
    with sqlite3.connect(copied) as conn:
        version_before = conn.execute("PRAGMA user_version").fetchone()[0]
        steps_before = conn.execute("SELECT COUNT(*) FROM pipeline_steps").fetchone()[0]

    # Everything below reads and writes the copy: ryos works out its data
    # folder from APPDATA when it is first imported.
    os.environ["APPDATA"] = str(tmp)
    os.environ["RYOS_NO_REGISTRY"] = "1"
    if not args.visible:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    print(f"RYOS real-data smoke (a copy in {tmp}; "
          f"{'window on the smoke screen' if args.visible else 'no window'})")

    from ryos.settings import _load_settings
    settings = _load_settings()
    settings["auto_check_update"] = False
    settings["open_on_cursor_monitor"] = False
    if args.visible:
        sys.path.insert(0, str(ROOT / "tests"))
        from gui_smoke import smoke_screen
        area = smoke_screen()
        if area:
            settings["window_geometry"] = f"540x640+{area[0] + 40}+{area[1] + 40}"
            settings["snap_corner"] = "none"

    from ryos.db import ScriptDB
    from ryos.qtui.main import build
    app, win = build(settings=settings, show=args.visible)
    for _ in range(5):
        app.processEvents()
    with sqlite3.connect(copied) as conn:
        version_after = conn.execute("PRAGMA user_version").fetchone()[0]
        steps_after = conn.execute("SELECT COUNT(*) FROM pipeline_steps").fetchone()[0]
    print(f"  schema: v{version_before} -> v{version_after}; pipeline steps "
          f"{steps_before} -> {steps_after}")
    from ryos.db import SCHEMA_VERSION
    if version_after != SCHEMA_VERSION:
        PROBLEMS.append(f"the database was left at v{version_after}, not v{SCHEMA_VERSION}")
    check_everything(app, win, ScriptDB(), settings)
    win.bridge.stop()

    if _snapshot(real) != before:
        PROBLEMS.append("the real RYOS folder changed during the run")
    if args.db and _snapshot(args.db.parent) != extra_before:
        PROBLEMS.append("the folder of the --db file changed during the run")
    for note in NOTES:
        print(f"  NOTE: {note}")
    for problem in PROBLEMS:
        print(f"  PROBLEM: {problem}")
    print(f"\nRYOS real-data smoke {'FAILED' if PROBLEMS else 'PASSED'}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    raise SystemExit(main())
