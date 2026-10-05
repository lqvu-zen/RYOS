#!/usr/bin/env python3
"""Make a preview of every theme in this folder, and the GALLERY.md index,
so themes can be browsed and downloaded straight from GitHub.

    uv run python theme-gallery/make_previews.py

Outputs ``previews/<id>.png`` and ``GALLERY.md``.

Each preview is the real RYOS window, not a drawing of it: a small made-up
list (two pipelines, a few scripts, one run that passed and one that failed,
a favourite) in the theme, rendered off screen with the system's fonts. So a
preview always shows what the app looks like now -- drop a new theme JSON in
and re-run. Nothing touches your own RYOS: the data lives in a throwaway
folder, and no window, notification or registry write ever appears.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PREVIEWS = HERE / "previews"
#: The window's size in the preview: the app's own default width.
SIZE = (560, 600)

# Order: light/dark first (templates), then the rest by name.
_FIRST = ["light", "dark"]

# Before ryos is imported: its data folder is fixed at import.
_TMP = Path(tempfile.mkdtemp(prefix="ryos-gallery-"))
os.environ["APPDATA"] = str(_TMP)
os.environ["RYOS_NO_REGISTRY"] = "1"
os.environ["RYOS_NO_TOASTS"] = "1"
sys.path.insert(0, str(ROOT))


def _themes() -> list[tuple[str, str, dict]]:
    """(file stem, name, seed) for every theme JSON here, in gallery order."""
    found = []
    for fp in HERE.glob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data.get("seed"), dict):
            found.append((fp.stem, data.get("name") or fp.stem, data["seed"]))
    found.sort(key=lambda t: (_FIRST.index(t[0]) if t[0] in _FIRST else len(_FIRST),
                              t[1].lower()))
    return found


def _sample_db():
    """The made-up list every preview shows."""
    from ryos.db import ScriptDB
    # A made-up folder: shown on the group's line, never opened -- nothing
    # runs, and a row does not look for its file.
    folder = r"C:\Scripts"
    db = ScriptDB()
    db.create_group("Work", folder)
    ids = {}
    for name, file in (("Backup photos", "backup.py"), ("Deploy site", "deploy.ps1"),
                       ("Clean temp", "clean.bat"), ("Weekly report", "report.py")):
        ids[name] = db.add(name, folder + "\\" + file, "", "", "Work")
    night = db.create_pipeline("Nightly", "Work")
    for name in ("Backup photos", "Clean temp"):
        db.add_pipeline_step(night, ids[name])
    release = db.create_pipeline("Release", "Work")
    for name in ("Weekly report", "Deploy site"):
        db.add_pipeline_step(release, ids[name])
    start = datetime.now() - timedelta(minutes=5)
    for name, status, code in (("Backup photos", "ok", 0), ("Deploy site", "error", 1)):
        db.record_run("script", name=name, script_id=ids[name], started_at=start,
                      finished_at=start + timedelta(seconds=3), status=status,
                      exit_code=code)
        db.mark_run_status(ids[name], status)
    db.record_run("pipeline", name="Nightly", pipeline_id=night, started_at=start,
                  finished_at=start + timedelta(seconds=9), status="ok")
    db.set_favorite_script(ids["Weekly report"], True)
    return db


def _preview(app, db, theme_id: str, customs: dict, out: Path) -> None:
    from PySide6.QtCore import Qt
    from ryos.qtui.shell import MainWindow
    from ryos.themes import resolve_palette
    win = MainWindow(resolve_palette(theme_id, customs),
                     settings={"quick_run_enabled": False})
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    win.resize(*SIZE)
    win.load_from_db(db)
    win.show_group("Work")
    win.show()
    for _ in range(5):
        app.processEvents()
    win.grab().save(str(out))
    win.close()
    win.deleteLater()
    app.processEvents()


def main() -> None:
    from PySide6.QtWidgets import QApplication
    from ryos.themes import load_user_themes, theme_choices
    app = QApplication.instance() or QApplication([])
    themes = _themes()
    customs = load_user_themes(HERE)
    by_name = {name: tid for tid, name in theme_choices(customs)}
    db = _sample_db()
    PREVIEWS.mkdir(exist_ok=True)
    for old in PREVIEWS.glob("*.svg"):          # the drawn previews these replace
        old.unlink()
    made = []
    for stem, name, _seed in themes:
        # A built-in's file name is its id; a gallery theme loads under its name.
        theme_id = stem if stem in _FIRST else by_name.get(name)
        if theme_id is None:
            print(f"skipped {stem}: not loadable as a theme")
            continue
        _preview(app, db, theme_id, customs, PREVIEWS / f"{stem}.png")
        made.append((stem, name))

    lines = ["# Theme gallery — previews", "",
             "Each preview is the RYOS window itself in that theme. Pick one, download",
             "its `.json`, and in RYOS choose **Options → Appearance… → Import…**",
             "(maximised, **Appearance** is also on the rail down the left edge).", ""]
    for stem, name in made:
        lines += [f"## {name}", "",
                  f"![RYOS in the {name} theme](previews/{stem}.png)", "",
                  f"[⬇ Download {stem}.json]({stem}.json)", ""]
    (HERE / "GALLERY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Made {len(made)} previews and GALLERY.md")


if __name__ == "__main__":
    main()
