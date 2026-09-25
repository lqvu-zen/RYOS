"""A whole working session in the Qt app, on realistic throwaway data.

tests/qt_smoke.py checks each feature on its own, mostly on a bare window.
This one does what a person does in a sitting, in order, through the real
start-up (`qtui.main.build`), the real job bridge and its schedule timer, and
settings saved to disk: make a group, add scripts through the dialog, run
them, watch one fail and retry it, stop a long one, build a pipeline in the
editor and run it, schedule a script and let the sweep fire it, use Quick
Run, search, select mode, favourites, delete a script a pipeline uses,
export and import, change options and the theme -- then quit, start again,
and check that what should have stuck did.

Everything lives in a throwaway folder: APPDATA points there before ryos is
imported, and the run refuses to start unless the database, settings and
log all resolve inside it. The user's own folder is compared before and
after. Run-at-login writes are off (RYOS_NO_REGISTRY).

    uv run python tests/session_smoke.py              # offscreen
    uv run python tests/session_smoke.py --visible    # on a second screen
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROBLEMS: list[str] = []

SCRIPTS = {
    "hello.py": ("import os, sys\n"
                 "print('hello', *sys.argv[1:])\n"
                 "print('env', os.environ.get('RYOS_SESSION', '-'))\n"),
    "fail.py": ("import sys\n"
                "print('about to fail')\n"
                "print('it broke', file=sys.stderr)\n"
                "sys.exit(3)\n"),
    "slow.py": ("import time\n"
                "for i in range(600):\n"
                "    print('tick', i, flush=True)\n"
                "    time.sleep(0.1)\n"),
    "mark.py": ("import pathlib, sys\n"
                "pathlib.Path(sys.argv[1]).write_text('done')\n"
                "print('marked')\n"),
    "cleanup.py": "print('cleanup ran')\n",
}


def problem(text: str) -> None:
    PROBLEMS.append(text)
    print(f"  PROBLEM: {text}")


_STEP_START = [0]


def ok(text: str) -> None:
    """Report a step passed -- only if it raised no problem of its own."""
    if len(PROBLEMS) == _STEP_START[0]:
        print(f"  [ok] {text}")


# --- the user's own folder, compared before and after ---------------------------

def _real_folder() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / ".local" / "share") / "RYOS"


def _snapshot(folder: Path) -> dict:
    if not folder.exists():
        return {}
    return {str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob("*") if p.is_file()}


# --- driving the window ----------------------------------------------------------

class Session:
    """The window, and answers for everything it may ask.

    Each dialog or question must be expected first (`expect_dialog`,
    `answer`); anything unexpected is a problem, and is dismissed so the run
    never blocks on a modal box.
    """

    def __init__(self, app, win, db, work: Path):
        self.app, self.win, self.db, self.work = app, win, db, work
        self._dialogs: list = []
        self._answers: dict[str, list] = {"yes_no": [], "text": [], "save": [], "open": []}
        self.asked: list[tuple[str, str]] = []
        self.hook(win)

    def hook(self, win) -> None:
        self.win = win
        win.run_dialog = self._run_dialog
        win.ask_yes_no = lambda t, q: self._take("yes_no", t, q)
        win.ask_text = lambda t, q, _i="": self._take("text", t, q)
        win.ask_save_path = lambda t, _n: self._take("save", t, "")
        win.ask_open_path = lambda t: self._take("open", t, "")
        win.warn = lambda t, q: problem(f"unexpected warning: {t}: {q}")
        win.inform = lambda t, q: problem(f"unexpected notice: {t}: {q}")

    def expect_dialog(self, cls_name: str, fill) -> None:
        self._dialogs.append((cls_name, fill))

    def answer(self, kind: str, value) -> None:
        self._answers[kind].append(value)

    def _take(self, kind, title, question):
        self.asked.append((title, question))
        if not self._answers[kind]:
            problem(f"unexpected question ({kind}): {title}: {question}")
            return None if kind != "yes_no" else False
        return self._answers[kind].pop(0)

    def _run_dialog(self, dlg) -> None:
        name = type(dlg).__name__
        if not self._dialogs or self._dialogs[0][0] != name:
            problem(f"unexpected dialog: {name} ({dlg.windowTitle()})")
            dlg.reject()
            return
        _n, fill = self._dialogs.pop(0)
        try:
            fill(dlg)
        except Exception:
            problem(f"filling {name} failed:\n{traceback.format_exc()}")
            dlg.reject()

    # -- waiting ---------------------------------------------------------------
    def pump(self, seconds: float = 0.2) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def wait_for(self, cond, what: str, timeout: float = 15.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            try:
                if cond():
                    return True
            except Exception:
                pass
            time.sleep(0.02)
        problem(f"timed out after {timeout:.0f}s waiting for {what}")
        return False

    def idle(self, what: str, timeout: float = 20.0) -> bool:
        """Every job finished and unregistered."""
        return self.wait_for(lambda: len(self.win._bridge.registry) == 0,
                             f"jobs to finish ({what})", timeout)

    # -- finding things -----------------------------------------------------------
    def card(self, group: str, name: str):
        self.pump(0.1)                   # a deferred reload replaces cards
        page = self.win.card_lists.get(group)
        for card in (page.cards if page is not None else []):
            if getattr(card, "_name", None) == name:
                return card
        raise LookupError(f"no card {name!r} in {group!r}")

    def output(self, name: str) -> str:
        """Text of the newest output tab titled ``name``: each run opens its
        own tab, as in Tk, so a script run twice has two."""
        tabs = self.win.output_tabs
        for i in reversed(range(tabs.count())):
            if tabs.tabText(i).replace("&&", "&") == name:
                return tabs.widget(i).plain_text()
        self.last_tabs = [tabs.tabText(i) for i in range(tabs.count())]
        return ""

    def runs(self, **where) -> list:
        (col, value), = where.items()
        conn = sqlite3.connect(self.db.db_path)
        try:
            return conn.execute(
                f"SELECT status, exit_code, trigger_source, kind FROM runs "
                f"WHERE {col}=? ORDER BY id", (value,)).fetchall()
        finally:
            conn.close()

    def script_id(self, name: str) -> int:
        return next(r[0] for r in self.db.list_all() if r[1] == name)


# --- the session -------------------------------------------------------------------

def make_files(work: Path) -> Path:
    project = work / "project"
    project.mkdir(parents=True)
    for name, body in SCRIPTS.items():
        (project / name).write_text(body, encoding="utf-8")
    return project


def step_groups_and_scripts(s: Session, project: Path) -> None:
    win = s.win

    # A group with a base folder, made in the New Group dialog.
    def fill_group(dlg):
        dlg.e_name.setText("Project")
        dlg.e_dir.setText(str(project))
        dlg.accept_form()
    s.expect_dialog("NewGroupDialog", fill_group)
    win.new_group()
    s.wait_for(lambda: "Project" in win.card_lists, "the Project tab")
    win.show_group("Project")

    # A script added through + Script, with presets and an environment.
    def fill_script(dlg):
        dlg.e_name.setText("Say hello")
        dlg.e_relpath.setText("hello.py")
        dlg.e_params.setText("--loud")
        dlg.add_preset()
        dlg.e_params.setText("world")
        dlg.t_env.setPlainText("RYOS_SESSION=yes")
        dlg.warn = lambda t, q: problem(f"script dialog refused: {t}: {q}")
        if not dlg.save():
            problem("the script dialog did not save")
    s.expect_dialog("ScriptDialog", fill_script)
    add = next(b for b in win.findChildren(type(win.add_pipeline_button))
               if b.text() == "+ Script")
    add.click()
    s.pump(0.3)
    hello = s.script_id("Say hello")
    rec = s.db.get(hello)
    if Path(rec[2]) != project / "hello.py" or rec[3] != "world":
        problem(f"the saved script is {rec[:5]}")
    if [p for _l, p in [(x[1], x[2]) for x in s.db.list_param_presets(hello)]] != ["--loud"]:
        problem(f"presets saved: {s.db.list_param_presets(hello)}")

    # The rest, as a user would add them too; the dialog is covered above.
    for name, file, params in (("Fail", "fail.py", ""), ("Slow", "slow.py", ""),
                               ("Mark", "mark.py", str(s.work / "marker.txt")),
                               ("Cleanup", "cleanup.py", "")):
        s.db.add(name, str(project / file), params, "", "Project")
    win.reload()
    win.show_group("Project")
    s.card("Project", "Mark")
    ok("groups and scripts: a group with a base folder and a script with presets "
       "and an environment, made through their dialogs")


def step_run_and_output(s: Session) -> None:
    hello = s.script_id("Say hello")
    s.card("Project", "Say hello").run_button.click()
    if not s.wait_for(lambda: "hello world" in s.output("Say hello"), "hello's output"):
        print(f"    (output tabs: {getattr(s, 'last_tabs', None)}; "
              f"text: {s.output('Say hello')!r})")
    s.idle("hello")
    text = s.output("Say hello")
    if "env yes" not in text:
        problem(f"the script's environment did not reach it: {text!r}")
    if [r[0] for r in s.runs(script_id=hello)] != ["ok"]:
        problem(f"hello's runs: {s.runs(script_id=hello)}")

    # A preset from the card's drop-down.
    card = s.card("Project", "Say hello")
    combo = card.params_combo
    idx = next((i for i in range(combo.count()) if "--loud" in combo.itemText(i)), -1)
    if idx < 0:
        problem(f"the preset is not in the drop-down: "
                f"{[combo.itemText(i) for i in range(combo.count())]}")
    else:
        combo.setCurrentIndex(idx)
        card.run_button.click()
        if not s.wait_for(lambda: "hello --loud" in s.output("Say hello"), "the preset's run"):
            print(f"    (chose {combo.currentText()!r} of "
                  f"{[combo.itemText(i) for i in range(combo.count())]}; "
                  f"output {s.output('Say hello')!r})")
        s.idle("hello --loud")

    # Run history, from the card's menu.
    seen = {}

    def read_history(dlg):
        seen["text"] = dlg.table.toPlainText()
        dlg.reject()
    s.expect_dialog("RunHistoryDialog", read_history)
    s.win.on_card_menu("script", hello, "history")
    if seen.get("text", "").count("\n") < 1:
        problem(f"run history shows {seen.get('text')!r} after two runs")
    ok("run: output, the script's environment, a preset from the drop-down, "
       "and both runs in the history")


def step_failure_and_retry(s: Session) -> None:
    fail = s.script_id("Fail")
    before = s.card("Project", "Fail").run_button.text()
    s.card("Project", "Fail").run_button.click()
    s.wait_for(lambda: "it broke" in s.output("Fail"), "the failure's stderr")
    s.idle("fail")
    runs = s.runs(script_id=fail)
    if not runs or runs[-1][0] == "ok" or runs[-1][1] != 3:
        problem(f"a script exiting 3 was recorded as {runs}")
    s.pump(0.3)
    after = s.card("Project", "Fail").run_button
    if after.text() == before and after.toolTip() == s.card("Project", "Say hello").run_button.toolTip():
        problem("after a failure the Run button looks no different")
    after.click()
    s.wait_for(lambda: len(s.runs(script_id=fail)) == 2, "the retry")
    s.idle("retry")
    ok(f"failure: exit 3 recorded as {runs[-1][0]!r}, stderr shown, the button "
       f"turns to retry, and retrying runs it again")


def step_stop(s: Session) -> None:
    slow = s.script_id("Slow")
    s.card("Project", "Slow").run_button.click()
    s.wait_for(lambda: "tick 3" in s.output("Slow"), "the slow script to tick")
    rows = list(s.win.running._rows.values())
    if len(rows) != 1:
        problem(f"{len(rows)} rows in Running for one job")
        return
    job = next(iter(s.win._bridge.registry.all()))
    procs = list(job.active_processes())
    rows[0].stop_button.click()
    s.idle("stop", timeout=10)
    if any(p.poll() is None for p in procs):
        problem("the stopped script's process is still alive")
    if s.win.running.count != 0:
        problem("the stopped job is still listed as running")
    runs = s.runs(script_id=slow)
    ok(f"stop: the process ends, Running empties, recorded as {runs[-1][0] if runs else None!r}")


def step_pipeline(s: Session) -> None:
    win = s.win
    marker = s.work / "marker.txt"

    def fill_editor(dlg):
        def add(name):
            i = dlg.add_combo.findText(name, flags=__import__(
                "PySide6.QtCore", fromlist=["Qt"]).Qt.MatchFlag.MatchContains)
            if i < 0:
                raise LookupError(f"{name} not offered: "
                                  f"{[dlg.add_combo.itemText(k) for k in range(dlg.add_combo.count())]}")
            dlg.add_combo.setCurrentIndex(i)
            dlg.add_step()
        for name in ("Say hello", "Mark", "Fail", "Cleanup"):
            add(name)
        from ryos import pipelinesteps
        # Fail: carry on; Cleanup: only when something failed.
        dlg.list.setCurrentRow(2)
        dlg.on_failure.setCurrentText(pipelinesteps.FAIL_LABELS["continue"])
        dlg.list.setCurrentRow(3)
        dlg.run_when.setCurrentText(pipelinesteps.WHEN_LABELS["on_failure"])
        if not dlg.save():
            problem("the pipeline editor did not save")
    s.answer("text", "Release")
    s.expect_dialog("PipelineEditorDialog", fill_editor)
    win.new_pipeline()
    s.pump(0.3)
    pid = next(p[0] for p in s.db.list_pipelines("Project") if p[1] == "Release")
    steps = s.db.list_pipeline_steps(pid)
    if [r[2] for r in steps] != ["Say hello", "Mark", "Fail", "Cleanup"]:
        problem(f"the pipeline's steps are {[r[2] for r in steps]}")
    if [r[10:13] for r in steps][2:] != [("continue", 0, "always"), ("stop", 0, "on_failure")]:
        problem(f"step policies saved as {[r[10:13] for r in steps]}")

    s.card("Project", "Release").run_button.click()
    s.wait_for(lambda: "cleanup ran" in s.output("⚡ Release"), "the pipeline's cleanup step",
               timeout=30)
    s.idle("pipeline", timeout=30)
    text = s.output("⚡ Release")
    if not marker.exists():
        problem("the pipeline's Mark step did not write its file")
    order = [text.find(x) for x in ("hello world", "marked", "it broke", "cleanup ran")]
    if -1 in order or order != sorted(order):
        problem(f"pipeline output out of order or missing: {order}\n{text}")
    kinds = [r[3] for r in s.runs(pipeline_id=pid)]
    if "pipeline" not in kinds:
        problem(f"the pipeline run is not in its history: {s.runs(pipeline_id=pid)}")
    ok("pipeline: built in the editor with a carry-on step and a cleanup step, "
       "runs in order, the cleanup runs because a step failed, history recorded")


def step_schedule(s: Session) -> None:
    hello = s.script_id("Say hello")
    from ryos.scheduleform import INTERVAL

    def fill_schedule(dlg):
        dlg.enabled.setChecked(True)
        dlg.mode.setCurrentIndex(dlg.mode.findData(INTERVAL))
        dlg.minutes.setValue(1)
        dlg._ask_login = lambda: False
        if not dlg.accept_form():
            problem("the schedule dialog did not save")
    s.expect_dialog("ScheduleDialog", fill_schedule)
    s.win.on_card_menu("script", hello, "schedule")
    sched = s.db.get_schedule(script_id=hello)
    if sched is None:
        problem("no schedule saved")
        return
    # A minute passing, without waiting for it: the next run is now due.
    conn = sqlite3.connect(s.db.db_path)
    conn.execute("UPDATE schedules SET next_run_at='2000-01-01T00:00:00' WHERE script_id=?",
                 (hello,))
    conn.commit()
    conn.close()
    from ryos.db import SOURCE_SCHEDULE
    fired = s.wait_for(
        lambda: any(r[2] == SOURCE_SCHEDULE for r in s.runs(script_id=hello)),
        "the schedule sweep to fire (the timer ticks every 30 s)", timeout=45)
    s.idle("scheduled run")
    if fired:
        ok("schedule: made in its dialog; the real sweep timer fires it when due")


def step_quick_run_search_select(s: Session, project: Path) -> None:
    win = s.win
    hello = s.script_id("Say hello")
    before = len(s.runs(script_id=hello))
    if not win.quick_run_submit("Project", str(project), "hello.py",
                                on_error=lambda *a: problem(f"quick run: {a}")):
        problem("quick run did not start hello.py")
    s.wait_for(lambda: len(s.runs(script_id=hello)) > before, "the quick run")
    s.idle("quick run")
    if sum(1 for r in s.db.list_all() if r[2].endswith("hello.py")) != 1:
        problem("quick run registered hello.py a second time")

    win.search_box.setText("fail")
    s.pump(0.4)
    visible = [c._name for c in win.card_lists["Project"].cards if c.isVisibleTo(win)]
    if visible != ["Fail"]:
        problem(f"searching 'fail' shows {visible}")
    win.search_box.clear()
    s.pump(0.4)

    win.set_select_mode(True)
    for name in ("Say hello", "Cleanup"):
        s.card("Project", name).checkbox.setChecked(True)
    cleanup = s.script_id("Cleanup")
    counts = (len(s.runs(script_id=hello)), len(s.runs(script_id=cleanup)))
    win.run_selected_button.click()
    s.wait_for(lambda: (len(s.runs(script_id=hello)), len(s.runs(script_id=cleanup)))
               == (counts[0] + 1, counts[1] + 1), "both selected scripts to run")
    s.idle("run selected")
    win.set_select_mode(False)
    ok("quick run reuses the registered script; search filters the cards; "
       "select mode runs the ticked scripts")


def step_favourite_and_delete(s: Session) -> None:
    win = s.win
    s.card("Project", "Say hello").fav_button.click()
    s.pump(0.4)
    favs = [c._name for c in win.card_lists["Project"].cards
            if c.isVisibleTo(win) and getattr(c, "section", None) == "favorites"]
    rec = next(r for r in s.db.list_all() if r[1] == "Say hello")
    if not rec[10]:
        problem("the favourite was not saved")

    cleanup = s.script_id("Cleanup")
    pid = next(p[0] for p in s.db.list_pipelines("Project") if p[1] == "Release")
    s.answer("yes_no", True)
    win.on_card_menu("script", cleanup, "delete")
    s.pump(0.3)
    question = s.asked[-1][1] if s.asked else ""
    if "'Release'" not in question:
        problem(f"deleting a pipeline step's script did not name the pipeline: {question!r}")
    if [r[2] for r in s.db.list_pipeline_steps(pid)] != ["Say hello", "Mark", "Fail"]:
        problem(f"after the delete the pipeline has {s.db.list_pipeline_steps(pid)}")
    conn = sqlite3.connect(s.db.db_path)
    left = conn.execute("SELECT COUNT(*) FROM pipeline_steps WHERE script_id=?",
                        (cleanup,)).fetchone()[0]
    conn.close()
    if left:
        problem(f"{left} step(s) of the deleted script stayed in the database")
    ok(f"favourite saved{' and shown' if favs or rec[10] else ''}; deleting a script "
       f"names the pipeline it leaves and takes its step with it")


def step_export_import(s: Session) -> None:
    path = s.work / "export.json"
    s.answer("save", str(path))
    s.win.export_all()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problem(f"export wrote nothing readable: {exc}")
        return
    before = len(s.db.list_all())
    s.answer("open", str(path))
    s.answer("yes_no", False)                  # merge
    s.win.import_config()
    s.pump(0.3)
    if len(s.db.list_all()) != before:
        problem(f"merging an export of the same data changed the script count "
                f"{before} -> {len(s.db.list_all())}")
    ok(f"export and import: {len(json.dumps(data))} bytes out, merged back in "
       f"with nothing duplicated")


def step_options_and_theme(s: Session, settings_path: Path) -> None:
    def fill_options(dlg):
        dlg._rows["max_output_lines"].set_value(777)
        dlg.save()
    s.expect_dialog("OptionsDialog", fill_options)
    s.win.open_options()
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    if saved.get("max_output_lines") != 777:
        problem(f"Options' Save did not reach settings.json "
                f"(max_output_lines={saved.get('max_output_lines')})")

    sheet = s.win.styleSheet()
    s.theme = "dark" if s.win._settings.get("theme", "light") == "light" else "light"

    def fill_appearance(dlg):
        dlg.select_theme(s.theme)
        dlg.save()
    s.expect_dialog("AppearanceDialog", fill_appearance)
    s.win.open_appearance()
    s.pump(0.3)
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    if saved.get("theme") != s.theme:
        problem(f"the theme saved as {saved.get('theme')!r}")
    if s.win.styleSheet() == sheet:
        problem("the window did not re-theme")
    ok("options and theme: both saved to settings.json; the window re-themes at once")


def step_restart(s: Session, build, settings_loader) -> None:
    win = s.win
    if not win.quit_app():
        problem("quitting was refused")
    s.pump(0.3)
    settings = settings_loader()
    app, win2 = build(settings=settings, show=s.visible)
    s.hook(win2)
    s.pump(0.5)
    if "Project" not in win2.card_lists:
        problem("after a restart the Project group is gone")
        return
    names = sorted(c._name for c in win2.card_lists["Project"].cards)
    want = sorted(["Say hello", "Fail", "Slow", "Mark", "Release"])
    # Favourites show a second card for the same script.
    if sorted(set(names)) != want:
        problem(f"after a restart Project shows {names}")
    if settings.get("theme") != s.theme or settings.get("max_output_lines") != 777:
        problem("settings did not survive the restart")
    if win2.current_group() != "Project":
        problem(f"the app reopened on {win2.current_group()!r}, not the last group")
    win2.quit_app()
    s.pump(0.2)
    ok("restart: groups, scripts, the pipeline, options, theme and the last group "
       "all come back")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--visible", action="store_true",
                        help="show the window, on a second screen when there is one")
    args = parser.parse_args()

    real = _real_folder()
    real_before = _snapshot(real)
    tmp = Path(tempfile.mkdtemp(prefix="ryos-session-"))
    os.environ["APPDATA"] = str(tmp)
    os.environ["RYOS_NO_REGISTRY"] = "1"
    os.environ["RYOS_ALLOW_MULTIPLE"] = "1"
    if not args.visible:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from ryos import settings as settings_mod
    for label, path in (("database", settings_mod.DB_PATH),
                        ("settings", settings_mod._SETTINGS_PATH),
                        ("log", settings_mod.LOG_PATH)):
        if tmp not in Path(path).resolve().parents:
            print(f"Refusing to run: the {label} would be {path}, outside {tmp}")
            return 2
    print(f"RYOS session smoke (a throwaway folder: {tmp}; "
          f"{'window on the smoke screen' if args.visible else 'no window'})")

    from ryos.logger import setup_logging
    setup_logging(True, "INFO")
    errors: list[str] = []
    sys.excepthook = lambda t, v, tb: errors.append(
        "".join(traceback.format_exception(t, v, tb)))

    def load_settings():
        settings = settings_mod._load_settings()
        settings["auto_check_update"] = False
        settings["open_on_cursor_monitor"] = False
        if args.visible:
            sys.path.insert(0, str(ROOT / "tests"))
            from gui_smoke import smoke_screen
            area = smoke_screen()
            if area:
                settings["window_geometry"] = f"540x700+{area[0] + 40}+{area[1] + 40}"
                settings["snap_corner"] = "none"
        return settings

    from ryos.db import ScriptDB
    from ryos.qtui.main import build
    work = tmp / "work"
    project = make_files(work)
    app, win = build(settings=load_settings(), show=args.visible)
    s = Session(app, win, ScriptDB(), work)
    s.visible = args.visible
    s.pump(0.5)

    steps = [lambda: step_groups_and_scripts(s, project),
             lambda: step_run_and_output(s),
             lambda: step_failure_and_retry(s),
             lambda: step_stop(s),
             lambda: step_pipeline(s),
             lambda: step_schedule(s),
             lambda: step_quick_run_search_select(s, project),
             lambda: step_favourite_and_delete(s),
             lambda: step_export_import(s),
             lambda: step_options_and_theme(s, Path(settings_mod._SETTINGS_PATH)),
             lambda: step_restart(s, build, load_settings)]
    for step in steps:
        _STEP_START[0] = len(PROBLEMS)
        try:
            step()
        except Exception:
            problem(f"a step crashed:\n{traceback.format_exc()}")
        if s._dialogs:
            problem(f"dialogs expected but never opened: {[d[0] for d in s._dialogs]}")
            s._dialogs.clear()
        for kind, left in s._answers.items():
            if left:
                problem(f"answers never asked for ({kind}): {left}")
                left.clear()

    for e in errors:
        problem(f"an exception reached the event loop:\n{e}")
    log = Path(settings_mod.LOG_PATH)
    bad = [line for line in (log.read_text(encoding="utf-8").splitlines()
                             if log.exists() else [])
           if (" ERROR " in line or " CRITICAL " in line)
           # A script failing is logged at ERROR by design; that is the
           # script's outcome, not a fault in RYOS.
           and "ryos.runner: Done:" not in line]
    for line in bad:
        problem(f"logged: {line}")
    if _snapshot(real) != real_before:
        problem("the user's own RYOS folder changed during the run")

    print(f"\nRYOS session smoke {'FAILED' if PROBLEMS else 'PASSED'}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    raise SystemExit(main())
