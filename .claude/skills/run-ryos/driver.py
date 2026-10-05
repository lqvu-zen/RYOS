"""Screenshot driver for RYOS (Qt): build the real window on sample data and
capture screens as PNGs, without showing anything on any monitor.

    uv run python .claude/skills/run-ryos/driver.py [scenario ...] [--theme ID]

Scenarios: main, compact, output, quick-run, dialogs, themes, all (default:
main). Screenshots land in .claude/skills/run-ryos/screenshots/.

Everything runs on a throwaway data folder (APPDATA is pointed there before
ryos is imported), loaded with the repo's own samples/ through the app's
import. Windows are rendered with Qt's WA_DontShowOnScreen: fully laid out
and painted, never shown -- so nothing lands on the screen someone is using.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "screenshots"
sys.path.insert(0, str(ROOT))

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ryos-driver-")
os.environ["RYOS_NO_REGISTRY"] = "1"
os.environ["RYOS_ALLOW_MULTIPLE"] = "1"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)
HIDDEN = Qt.WidgetAttribute.WA_DontShowOnScreen


def pump(seconds: float = 0.2) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.01)


def shot(widget, name: str) -> Path:
    """Save what ``widget`` paints, at the screen's pixel ratio."""
    OUT.mkdir(parents=True, exist_ok=True)
    pump(0.3)
    path = OUT / f"{name}.png"
    widget.grab().save(str(path))
    print("saved", path.relative_to(ROOT))
    return path


def load_samples() -> None:
    """Import samples/ into the throwaway database, as a user would."""
    subprocess.run([sys.executable, str(ROOT / "samples" / "make_import.py")],
                   check=True, capture_output=True)
    from ryos.db import ScriptDB
    ScriptDB().import_from_file(str(ROOT / "samples" / "ryos-samples.json"))


def window(theme: str, **overrides):
    """The real start-up (qtui.main.build), rendered off screen."""
    from ryos.qtui.main import build
    from ryos.settings import _load_settings
    settings = _load_settings()
    settings.update(auto_check_update=False, theme=theme, window_width=560,
                    window_height=780, last_group="Samples",
                    remember_last_group=True, **overrides)
    app, win = build(settings=settings, show=False)
    win.setAttribute(HIDDEN)
    win.resize(560, 780)
    win.show()
    win.show_group("Samples")
    pump(0.5)
    return win


def idle(win, timeout: float = 20.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end and len(win._bridge.registry):
        pump(0.1)


def card(win, name: str):
    return next(c for c in win.card_lists["Samples"].cards
                if getattr(c, "_name", None) == name)


def script_id(name: str) -> int:
    from ryos.db import ScriptDB
    return next(r[0] for r in ScriptDB().list_all() if r[1] == name)


# -- scenarios -----------------------------------------------------------------------

def scenario_main(theme: str) -> None:
    win = window(theme)
    shot(win, f"main_{theme}")
    win.bridge.stop()


def scenario_compact(theme: str) -> None:
    win = window(theme, compact_mode=True)
    shot(win, f"compact_{theme}")
    win.bridge.stop()


def scenario_output(theme: str) -> None:
    """A success and a failure: Run turns to Retry, output shows both."""
    win = window(theme)
    card(win, "Say hello").run_button.click()
    card(win, "Always fails").run_button.click()
    idle(win)
    win.set_output_expanded(True)
    shot(win, f"output_{theme}")
    win.bridge.stop()


def scenario_workspace(theme: str) -> None:
    """The maximised layout: the list, and a chosen pipeline and script.

    Off screen there is no window manager to maximise it, so it is sized as a
    maximised window would be and the layout switched on directly.
    """
    # A schedule, so the Activity bar has something coming up.
    import json
    from datetime import datetime, timedelta
    from ryos.db import ScriptDB
    db = ScriptDB()
    morning = next(r[0] for r in db.list_pipelines("Samples") if r[1] == "Morning report")
    if not db.list_schedules(pipeline_id=morning):
        db.add_schedule("pipeline", pipeline_id=morning, spec_type="daily",
                        spec=json.dumps({"at": "08:00"}), enabled=True,
                        next_run_at=(datetime.now() + timedelta(days=1)).replace(
                            hour=8, minute=0, second=0, microsecond=0).isoformat())
    win = window(theme)
    win.resize(1280, 760)
    win.set_workspace(True)
    pump(0.3)
    card(win, "Resilient").run_button.click()
    idle(win)
    card(win, "Resilient").activated.emit()
    win.detail.show_tab("Overview")
    shot(win, f"workspace_pipeline_{theme}")
    win.detail.show_tab("Output")
    shot(win, f"workspace_output_{theme}")
    win.detail.show_tab("History")
    shot(win, f"workspace_history_{theme}")
    win.detail.show_tab("Overview")
    card(win, "Say hello").activated.emit()
    shot(win, f"workspace_script_{theme}")
    # Something running: its row and Stop in the Activity bar, the rail's count.
    card(win, "Count a minute").run_button.click()
    pump(1.5)
    shot(win, f"workspace_running_{theme}")
    for job in list(win.bridge.registry.all()):
        win._stop_job(job)
    idle(win)
    win.bridge.stop()


def scenario_quick_run(theme: str) -> None:
    win = window(theme)
    bar = win.quick_run_bars.get("Samples")
    if bar is None:
        print("no Quick Run bar (the group has no base folder?)")
        return
    bar.open()
    bar.entry.setText("hel")
    pump(1.0)                                    # the index builds, suggestions show
    shot(win, f"quick_run_{theme}")
    win.bridge.stop()


def scenario_dialogs(theme: str) -> None:
    """Each dialog as the window opens it, captured instead of run."""
    win = window(theme)
    captured: list[str] = []

    def capture(dlg, name=None):
        dlg.setAttribute(HIDDEN)
        dlg.show()
        shot(dlg, f"dialog_{name or type(dlg).__name__}_{theme}")
        captured.append(type(dlg).__name__)
        dlg.reject()
    win.run_dialog = capture

    hello = script_id("Say hello")
    win.edit_script(hello)
    from ryos.db import ScriptDB
    pid = next(p[0] for p in ScriptDB().list_pipelines("Samples") if p[1] == "Resilient")
    win.on_card_menu("pipeline", pid, "edit")
    win.on_card_menu("script", hello, "schedule")
    card(win, "Say hello").run_button.click()
    idle(win)
    win.on_card_menu("script", hello, "history")
    win.open_options()
    win.open_appearance()
    win.new_group()
    print("dialogs:", ", ".join(captured))
    win.bridge.stop()


def scenario_themes(_theme: str) -> None:
    """Every theme's main window on one contact sheet (thumbnails)."""
    from ryos.themes import load_user_themes, theme_choices
    customs = load_user_themes(ROOT / "theme-gallery")
    thumbs = []
    for theme_id, label in theme_choices(customs):
        win = window(theme_id, themes_dir=str(ROOT / "theme-gallery"))
        img = win.grab().toImage().scaledToWidth(
            280, Qt.TransformationMode.SmoothTransformation)
        thumbs.append((label, img))
        win.bridge.stop()
        win.close()
    per_row, w = 5, 280
    h = max(i.height() for _l, i in thumbs) + 20
    rows = (len(thumbs) + per_row - 1) // per_row
    sheet = QImage(w * per_row, h * rows, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#808080"))
    p = QPainter(sheet)
    p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    for k, (label, img) in enumerate(thumbs):
        x, y = (k % per_row) * w, (k // per_row) * h
        p.drawText(x + 4, y + 14, label)
        p.drawImage(x, y + 20, img)
    p.end()
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.save(str(OUT / "themes.png"))
    print("saved", (OUT / "themes.png").relative_to(ROOT))


SCENARIOS = {"main": scenario_main, "compact": scenario_compact,
             "output": scenario_output, "workspace": scenario_workspace,
             "quick-run": scenario_quick_run,
             "dialogs": scenario_dialogs, "themes": scenario_themes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", nargs="*", default=["main"],
                        help=f"{', '.join(SCENARIOS)}, or all")
    parser.add_argument("--theme", default="dark", help="theme id (default: dark)")
    args = parser.parse_args()
    names = list(SCENARIOS) if "all" in args.scenario else args.scenario
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        parser.error(f"unknown scenario(s): {unknown}")
    load_samples()
    for name in names:
        SCENARIOS[name](args.theme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
