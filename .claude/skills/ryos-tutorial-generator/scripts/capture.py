"""Capture every tutorial screenshot off screen, in the order the guide reads.

    uv run python .claude/skills/ryos-tutorial-generator/scripts/capture.py [--out DIR]

Builds the real window through the run-ryos driver: a throwaway data folder
loaded with the repo's samples/, Light theme, rendered with
WA_DontShowOnScreen -- nothing appears on any monitor, the user's own data is
never read, and every image holds RYOS and nothing else by construction.
Images land in docs/tutorial/images/ (or --out), named NN-step.png to sort in
reading order. Re-run it after a UI change; the pages link to these names.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "run-ryos"))
import driver  # noqa: E402  -- points APPDATA at a throwaway folder on import

from PySide6.QtCore import QPoint, QRect  # noqa: E402

OUT = ROOT / "docs" / "tutorial" / "images"
saved: list[str] = []


def save(widget, name: str, rect: QRect | None = None) -> None:
    """Grab ``widget`` (or part of it) into OUT/name.png."""
    driver.pump(0.3)
    OUT.mkdir(parents=True, exist_ok=True)
    pix = widget.grab(rect) if rect is not None else widget.grab()
    pix.save(str(OUT / f"{name}.png"))
    saved.append(name)
    print("saved", name)


def popup_capture(name: str):
    """A stand-in for win.popup that renders the menu off screen and saves it."""
    def run(menu, _pos):
        menu.setAttribute(driver.HIDDEN)
        menu.show()
        menu.adjustSize()
        save(menu, name)
        menu.close()
    return run


def dialog_capture(name: str, fill=None):
    """A stand-in for win.run_dialog: optionally fill, render, save, cancel."""
    def run(dlg):
        dlg.setAttribute(driver.HIDDEN)
        dlg.show()
        if fill is not None:
            fill(dlg)
        save(dlg, name)
        dlg.reject()
    return run


def top(win, height: int) -> QRect:
    return QRect(0, 0, win.width(), height)


def main() -> int:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    OUT = parser.parse_args().out
    driver.load_samples()
    from ryos.db import ScriptDB
    db = ScriptDB()
    db.create_group("Tools")

    win = driver.window("light", compact_mode=False,
                        themes_dir=str(ROOT / "theme-gallery"))
    win.reload()
    win.show_group("Samples")
    driver.pump(0.5)

    # -- 01 the main window ------------------------------------------------------------
    save(win, "01-main-window")
    hello = driver.card(win, "Say hello")
    flaky = driver.card(win, "Flaky")
    flaky.set_hovered(True)
    panel = flaky.parentWidget()
    rows = [c for c in panel.findChildren(type(flaky)) if c.isVisible()]
    bottom = max(c.geometry().bottom() for c in rows[:3]) + 1
    save(panel, "01-rows-hover", QRect(0, 0, panel.width(), bottom))
    flaky.set_hovered(False)
    win.popup = popup_capture("01-row-menu")
    win._show_card_menu("script", driver.script_id("Say hello"), QPoint(0, 0),
                        "scripts")

    # -- 02 adding a script --------------------------------------------------------------
    def fill_new(dlg):
        dlg.e_name.setText("Backup notes")
        (dlg.e_relpath if dlg.rel_row.isVisibleTo(dlg) else dlg.e_path).setText("backup.py")
        dlg.e_params.setText("--full")
    win.run_dialog = dialog_capture("02-add-script-dialog", fill_new)
    win.add_script()

    # -- 03 running and the output panel -------------------------------------------------
    driver.card(win, "Count a minute").run_button.click()
    driver.pump(1.5)
    save(win, "03-running")          # the Running list sits above the Output bar
    for job in list(win._bridge.registry.all()):
        win._stop_job(job)
    driver.idle(win)
    driver.card(win, "Say hello").run_button.click()
    driver.card(win, "Always fails").run_button.click()
    driver.idle(win)
    win.set_output_expanded(True)
    save(win, "03-output")
    win.set_output_expanded(False)
    driver.pump(0.3)
    save(win, "03-outcomes")

    # -- 04 groups ------------------------------------------------------------------------
    save(win, "04-group-pills", top(win, 150))
    win.popup = popup_capture("04-group-menu")
    win._show_group_menu("Samples", QPoint(0, 0))
    win.run_dialog = dialog_capture("04-new-group-dialog")
    win.new_group()

    # -- 05 parameters and presets --------------------------------------------------------
    hello = driver.card(win, "Say hello")

    def open_menu(menu, _pos):
        popup_capture("05-preset-menu")(menu, _pos)
    hello.menu_runner = open_menu
    hello.params_pick.click()
    win.run_dialog = dialog_capture("05-script-presets")
    win.edit_script(driver.script_id("Say hello"))
    win.run_dialog = dialog_capture("05-ask-each-run",
                                    lambda d: d.e_params.setText("--name Friday"))
    driver.card(win, "Ask each run").run_button.click()

    # -- 06 pipelines -----------------------------------------------------------------------
    pid = next(p[0] for p in db.list_pipelines("Samples") if p[1] == "Resilient")
    win.run_dialog = dialog_capture("06-pipeline-editor")
    win.on_card_menu("pipeline", pid, "edit")
    win.clear_output()
    driver.card(win, "Morning report").run_button.click()
    driver.idle(win)
    win.set_output_expanded(True)
    save(win, "06-pipeline-output")
    win.set_output_expanded(False)

    # -- 07 schedules and history ------------------------------------------------------------
    sid = driver.script_id("Say hello")
    win.run_dialog = dialog_capture("07-schedule")
    win.on_card_menu("script", sid, "schedule")
    win.run_dialog = dialog_capture("07-history")
    win.on_card_menu("script", sid, "history")

    # -- 08 quick run --------------------------------------------------------------------------
    bar = win.quick_run_bars.get("Samples")
    if bar is not None:
        bar.open()
        bar.entry.setText("hel")
        driver.pump(1.0)
        save(win, "08-quick-run", top(win, 260))
        bar.close_bar()

    # -- 09 the maximised layout -----------------------------------------------------------------
    win.resize(1280, 760)
    win.set_workspace(True)
    driver.pump(0.3)
    driver.card(win, "Say hello").activated.emit()
    save(win, "09-maximised-script")
    driver.card(win, "Resilient").activated.emit()
    save(win, "09-maximised-pipeline")
    win.set_workspace(False)
    win.resize(560, 780)
    driver.pump(0.3)

    # -- 10 import and export ----------------------------------------------------------------------
    file_menu = win.menu_bar.actions()[0].menu()
    popup_capture("10-file-menu")(file_menu, None)

    # -- 11 settings ----------------------------------------------------------------------------------
    from PySide6.QtWidgets import QTabWidget

    def options(dlg):
        tabs = dlg.findChild(QTabWidget)
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            # Tab text escapes "&" as "&&" so Qt shows it.
            slug = (tabs.tabText(i).replace("&&", "&").lower()
                    .replace(" & ", "-").replace(" ", "-"))
            save(dlg, f"11-options-{slug}")
    win.run_dialog = lambda dlg: (dlg.setAttribute(driver.HIDDEN), dlg.show(),
                                  options(dlg), dlg.reject())
    win.open_options()
    win.run_dialog = dialog_capture("11-appearance")
    win.open_appearance()
    win.popup = popup_capture("11-options-menu")
    options_menu = win.menu_bar.actions()[1].menu()
    popup_capture("11-options-menu")(options_menu, None)

    # -- 12 tips -----------------------------------------------------------------------------------------
    win.set_select_mode(True)
    for c in win.selectable_cards()[:2]:
        c.checkbox.setChecked(True)
    save(win, "12-select-mode")
    win.set_select_mode(False)
    win.bridge.stop()
    win.close()

    compact = driver.window("light", compact_mode=True)
    save(compact, "12-compact")
    compact.bridge.stop()
    compact.close()
    dark = driver.window("dark", compact_mode=False)
    save(dark, "12-dark")
    dark.bridge.stop()
    print(f"{len(saved)} images in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
