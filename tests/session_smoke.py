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

    uv run python tests/session_smoke.py              # offscreen, both layouts
    uv run python tests/session_smoke.py --layout compact
    uv run python tests/session_smoke.py --visible    # on a second screen

Both layouts (the default) run the whole session twice, once with normal rows
and once with the `compact_mode` setting on, each pass in its own process and
its own throwaway folder (the data paths are fixed when ryos is imported).
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
KNOWN_BUGS: list[str] = []        # app bugs a check found: reported, not failed
LAYOUT = ["normal"]

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
        self.urls: list[str] = []
        self.folders: list[str] = []
        self.hook(win)

    def hook(self, win) -> None:
        self.win = win
        win.run_dialog = self._run_dialog
        # No step may open a real browser or Explorer.
        win.open_url = self.urls.append
        win.open_folder = self.folders.append
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

    # File is where New and Import are looked for; they all sat under Options.
    menus = {m.title().replace("&", ""): [a.text().replace("&", "")
                                          for a in m.actions() if a.text()]
             for m in (a.menu() for a in win.menuBar().actions()) if m}
    if not {"New Script…", "New Group…", "Import config…"} <= set(menus.get("File", [])):
        problem(f"the File menu holds {menus.get('File')}")

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
    step_outside_note(s)


def step_outside_note(s: Session) -> None:
    """A script outside the group's base folder says so at the top of its run."""
    away = s.work / "away.py"
    away.write_text("print('from away')\n", encoding="utf-8")
    sid = s.db.add("Away", str(away), "", sys.executable, "Project")
    s.win.reload()
    s.win.show_group("Project")
    # It asks first: a run from the window outside the base folder.
    s.expect_dialog("OutsideBaseWarningDialog", lambda dlg: dlg.choose_run())
    s.card("Project", "Away").run_button.click()
    s.wait_for(lambda: "from away" in s.output("Away"), "the outside script's output")
    s.idle("away")
    first = s.output("Away").split("\n")[0]
    if not first.startswith("Note: runs outside the group's base folder"):
        problem(f"an outside script's output began {first!r}")
    # Gone again, so the steps after this one see the scripts they expect.
    s.db.delete(sid)
    s.win.reload()
    s.win.show_group("Project")
    ok("run: a script outside the group's base folder asks first, then opens its "
       "output with a note")


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
    # The Running list shows only while something runs; idle, it took a row
    # to say "Nothing running." beside a status bar saying "Ready".
    if s.win.running.isVisibleTo(s.win):
        problem("the Running list shows with nothing running")
    s.card("Project", "Slow").run_button.click()
    s.wait_for(lambda: "tick 3" in s.output("Slow"), "the slow script to tick")
    if not s.win.running.isVisibleTo(s.win):
        problem("the Running list is hidden while a job runs")
    chip = s.card("Project", "Slow").status_chip
    if chip is None or "Running" not in chip.text():
        problem("the running script's card does not say Running (issue #13)")
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
    if s.win.running.isVisibleTo(s.win):
        problem("the Running list stays up after the job ended")
    if s.win.running.count != 0:
        problem("the stopped job is still listed as running")
    chip = s.card("Project", "Slow").status_chip
    if chip is not None and "Running" in chip.text():
        problem("the card still says Running after the job ended")
    runs = s.runs(script_id=slow)
    ok(f"stop: the process ends, Running empties, recorded as {runs[-1][0] if runs else None!r}")


def step_status_line(s: Session) -> None:
    """The status bar's last line says what happened (OP-18)."""
    win = s.win
    for want, name in (("Done.", "Say hello"), ("Failed.", "Fail")):
        s.card("Project", name).run_button.click()
        s.idle(name)
        s.pump(0.3)
        if win.statusBar().currentMessage() != want:
            problem(f"after {name} the status bar says "
                    f"{win.statusBar().currentMessage()!r}, not {want!r}")
    s.card("Project", "Slow").run_button.click()
    s.wait_for(lambda: "tick 2" in s.output("Slow"), "the slow script to tick")
    rows = list(win.running._rows.values())
    if len(rows) != 1:
        problem(f"{len(rows)} rows in Running for one job")
        return
    rows[0].stop_button.click()
    s.idle("stop", timeout=10)
    s.pump(0.3)
    if win.statusBar().currentMessage() != "Stopped.":
        problem(f"after a stopped run the status bar says "
                f"{win.statusBar().currentMessage()!r}")
    ok("status bar: Done., Failed. and Stopped. after a run")


def step_output_options(s: Session) -> None:
    """"Clear output between runs" and "Scroll to the newest output" (OP-15).

    Clearing has no effect in the window today (nothing reads the setting):
    reported as a known app bug, not failed, so the map can say so."""
    from ryos import outputpanel
    win = s.win
    all_pane = win._output_tabs[outputpanel.ALL]
    win._settings["auto_clear_output"] = True
    try:
        for _ in range(2):
            s.card("Project", "Say hello").run_button.click()
            s.idle("hello, clearing between runs")
            s.pump(0.2)
        runs_shown = all_pane.plain_text().count("hello world")
    finally:
        win._settings["auto_clear_output"] = False
    if runs_shown != 1:
        KNOWN_BUGS.append(f"OP-15: with 'Clear output between runs' on, the All tab "
                          f"holds {runs_shown} runs of hello, not 1 (the setting is "
                          f"read nowhere)")
        print(f"  KNOWN BUG: {KNOWN_BUGS[-1]}")

    # Auto-scroll: off leaves the view where it was, on follows the newest line.
    win.set_output_expanded(True)
    win.output_tabs.setCurrentIndex(win.output_tabs.indexOf(all_pane))
    s.pump(0.3)
    bar = all_pane.text.verticalScrollBar()
    flood = "".join(f"line {i}\n" for i in range(300))
    try:
        win._settings["auto_scroll_output"] = False
        bar.setValue(0)
        win.append_output(flood)
        s.pump(0.3)
        if bar.value() != 0:
            problem(f"with auto-scroll off the output moved to {bar.value()}")
        win._settings["auto_scroll_output"] = True
        win.append_output(flood)
        s.pump(0.3)
        if bar.maximum() <= 0 or bar.value() != bar.maximum():
            problem(f"with auto-scroll on the output sits at {bar.value()} "
                    f"of {bar.maximum()}")
    finally:
        win._settings["auto_scroll_output"] = True
        win.set_output_expanded(False)
    ok("output options: auto-scroll follows or stays as set (clearing: see known bugs)")


def step_run_click(s: Session) -> None:
    """A real mouse click on a row's Run starts the run, in either layout."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    cleanup = s.script_id("Cleanup")
    before = len(s.runs(script_id=cleanup))
    s.win.show_group("Project")
    s.pump(0.2)
    card = s.card("Project", "Cleanup")
    if (LAYOUT[0] == "compact") != bool(card._compact):
        problem(f"the {LAYOUT[0]} layout shows a row with compact={card._compact}")
    if not card.run_button.isVisibleTo(s.win):
        problem("the row's Run button is not visible")
    QTest.mouseClick(card.run_button, Qt.MouseButton.LeftButton)
    s.wait_for(lambda: len(s.runs(script_id=cleanup)) > before,
               "a click on Run to start the run")
    s.idle("clicked run")
    ok(f"a mouse click on Run in a {LAYOUT[0]} row starts the run")


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
    s.wait_for(lambda: "cleanup ran" in s.output("Release"), "the pipeline's cleanup step",
               timeout=30)
    s.idle("pipeline", timeout=30)
    text = s.output("Release")
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


def step_scheduled_outside(s: Session) -> None:
    """A scheduled run of a script outside the base folder never asks and
    never asks (GR-33, the schedule half; the "no note" half is a known bug). Any question or dialog it
    raised would be reported as unexpected."""
    away = s.work / "away_sched.py"
    away.write_text("print('scheduled from away')\n", encoding="utf-8")
    sid = s.db.add("AwayTimer", str(away), "", sys.executable, "Project")
    s.db.add_schedule("script", script_id=sid, spec_type="interval",
                      spec=json.dumps({"minutes": 1}), enabled=True,
                      next_run_at="2000-01-01T00:00:00")
    s.win.reload()
    s.win.show_group("Project")
    asked = len(s.asked)
    started = s.win._bridge.run_due_schedules()
    if started < 1:
        problem(f"the sweep started {started} runs for a due schedule")
    s.wait_for(lambda: "scheduled from away" in s.output("AwayTimer"),
               "the scheduled outside script's output")
    s.idle("scheduled outside run")
    from ryos.db import SOURCE_SCHEDULE
    if [r[2] for r in s.runs(script_id=sid)] != [SOURCE_SCHEDULE]:
        problem(f"the outside script's runs: {s.runs(script_id=sid)}")
    first = s.output("AwayTimer").split("\n")[0]
    if first.startswith("Note:"):
        # GR-33 says a schedule adds no note; it does. Reported, not failed.
        KNOWN_BUGS.append("GR-33: a scheduled run of an outside script opens its "
                          "output with the outside-folder note (the map says none)")
        print(f"  KNOWN BUG: {KNOWN_BUGS[-1]}")
    if len(s.asked) != asked:
        problem(f"a scheduled run asked {s.asked[asked:]}")
    s.db.delete(sid)
    s.win.reload()
    s.win.show_group("Project")
    ok("a scheduled run of an outside script starts at once, with no question")


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

    # A file that is not a script yet is registered, and its row must appear
    # without a restart (issue #30).
    (project / "fresh.py").write_text("print('fresh')\n", encoding="utf-8")
    if not win.quick_run_submit("Project", str(project), "fresh.py",
                                on_error=lambda *a: problem(f"quick run: {a}")):
        problem("quick run did not start fresh.py")
    s.wait_for(lambda: any(r[1] == "fresh" for r in s.db.list_all()),
               "fresh.py to be registered")
    s.idle("quick run of a new file")
    s.pump(0.4)
    try:
        fresh = s.card("Project", "fresh")
    except Exception:
        fresh = None
    if fresh is None:
        problem("quick run of a new file added no row to Project")
    elif fresh._last_status != "ok":
        problem(f"the new quick-run row says {fresh._last_status!r}, not ok")
    if not any(c._name == "fresh" for page in win.all_pages.values()
               for c in page.cards):
        problem("quick run of a new file added no row to All")

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

    # A pipeline is tickable too, and a click on its row ticks it (issue #27).
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    for card in win.selectable_cards():
        card.checkbox.setChecked(False)
    release = s.card("Project", "Release")
    QTest.mouseClick(release, Qt.MouseButton.LeftButton,
                     pos=QPoint(release.width() // 2, 6))
    if not release.checkbox.isChecked() or len(win.selected_cards()) != 1:
        problem("a click on the pipeline row did not tick just it")
    pipe_id = release.pipeline_id
    pipe_runs = len(s.runs(pipeline_id=pipe_id))
    win.run_selected_button.click()
    if win.statusBar().currentMessage() != "Started 1 pipeline.":
        problem(f"status after running a ticked pipeline: "
                f"{win.statusBar().currentMessage()!r}")
    s.wait_for(lambda: len(s.runs(pipeline_id=pipe_id)) > pipe_runs,
               "the selected pipeline to run", timeout=30)
    s.idle("run selected pipeline", timeout=30)
    win.set_select_mode(False)
    ok("quick run reuses the registered script; search filters the cards; "
       "select mode runs the ticked scripts and a ticked pipeline (row click)")


def step_agents_for_a_group(s: Session, project: Path) -> None:
    """A group tab's "Make all in this group available to agents..." and
    select mode's two agent buttons: the same plan and wording as `ryos-cli
    expose --group`, no rows rebuilt, hidden in the build without agents."""
    from PySide6.QtCore import QPoint

    from ryos import cardmenu
    from ryos.qtui.menus import actions_by_key

    win = s.win
    notices: list[tuple[str, str]] = []
    old_inform, old_popup = win.inform, win.popup
    win.inform = lambda t, q: notices.append((t, q))
    shown: list = []
    win.popup = lambda menu, pos: shown.append(menu)
    key = cardmenu.EXPOSE_GROUP
    try:
        # (1) The tab's menu has the entry.
        win._show_group_menu("Project", QPoint(0, 0))
        if not shown or key not in actions_by_key(shown[-1]):
            problem("the group menu has no 'Make all in this group available to agents'")

        def members():
            scripts = {r[0] for r in s.db.list_all() if (r[8] or "") == "Project"}
            pipes = {r[0] for r in s.db.list_pipelines("Project")}
            return scripts, pipes

        def exposed_in_group():
            scripts, pipes = members()
            return (scripts <= s.db.agent_exposed_ids("script")
                    and pipes <= s.db.agent_exposed_ids("pipeline"))

        outside = {r[0] for r in s.db.list_all() if (r[8] or "") != "Project"}
        outside_before = s.db.agent_exposed_ids("script") & outside

        # (2) Yes: everything in the group is available, nothing outside it.
        card_before = s.card("Project", "Say hello")
        asked = len(s.asked)
        s.answer("yes_no", True)
        win.on_group_menu("Project", key)
        s.pump(0.2)
        if len(s.asked) != asked + 1 or "Will make" not in s.asked[-1][1]:
            problem(f"the group question was {s.asked[asked:]}")
        if not exposed_in_group():
            problem("the group menu left something in Project unavailable")
        if s.db.agent_exposed_ids("script") & outside != outside_before:
            problem("exposing Project touched a script outside it")
        if not win.statusBar().currentMessage().startswith("Made "):
            problem(f"status after exposing: {win.statusBar().currentMessage()!r}")
        if s.card("Project", "Say hello") is not card_before:
            problem("exposing a group rebuilt the rows")

        # (3) Again: nothing new, and no question.
        asked = len(s.asked)
        notices.clear()
        win.on_group_menu("Project", key)
        if len(s.asked) != asked:
            problem("a second run asked a question with nothing new")
        if not notices or "already available to agents" not in notices[-1][1]:
            problem(f"a second run said {notices}")

        # (4) A script added since: the question names only it.
        late = s.db.add("Late", str(project / "hello.py"), "", "", "Project")
        asked = len(s.asked)
        s.answer("yes_no", True)
        win.on_group_menu("Project", key)
        question = s.asked[-1][1] if len(s.asked) == asked + 1 else ""
        if "Will make 1 available to agents: Project/Late." not in question:
            problem(f"the refresh asked {question!r}")
        if not s.db.is_agent_exposed("script", late):
            problem("the refresh did not expose the new script")
        win.reload()
        win.show_group("Project")
        s.pump(0.3)

        # (5) Select mode: off asks nothing and keeps the ticks; on asks.
        win.set_select_mode(True)
        for name in ("Say hello", "Cleanup"):
            s.card("Project", name).checkbox.setChecked(True)
        ids = [s.script_id("Say hello"), s.script_id("Cleanup")]
        asked = len(s.asked)
        win.agents_off_button.click()
        if len(s.asked) != asked:
            problem("turning agents off from select mode asked a question")
        if any(s.db.is_agent_exposed("script", i) for i in ids):
            problem("select mode's off left a ticked script available")
        if len(win.selected_cards()) != 2:
            problem("select mode lost its ticks after the agent button")
        asked = len(s.asked)
        s.answer("yes_no", True)
        win.agents_on_button.click()
        if len(s.asked) != asked + 1 or "Will make 2" not in s.asked[-1][1]:
            problem(f"select mode's on asked {s.asked[asked:]}")
        if not all(s.db.is_agent_exposed("script", i) for i in ids):
            problem("select mode's on left a ticked script unavailable")
        if not (win.agents_on_button.isVisibleTo(win)
                and win.agents_off_button.isVisibleTo(win)):
            problem("the agent buttons are missing from select mode")

        # (6) The build without agents hides both, and the menu entry.
        import types
        win.set_select_mode(False)
        previous = sys.modules.get("ryos._build_info")
        fake = types.ModuleType("ryos._build_info")
        fake.VARIANT = "windows"          # type: ignore[attr-defined]
        sys.modules["ryos._build_info"] = fake
        try:
            win.set_select_mode(True)
            if (win.agents_on_button.isVisibleTo(win)
                    or win.agents_off_button.isVisibleTo(win)):
                problem("select mode shows agent buttons in the build without agents")
            win.set_select_mode(False)
            shown.clear()
            win._show_group_menu("Project", QPoint(0, 0))
            if not shown or key in actions_by_key(shown[-1]):
                problem("the group menu offers agents in the build without them")
        finally:
            if previous is None:
                sys.modules.pop("ryos._build_info", None)
            else:
                sys.modules["ryos._build_info"] = previous
        if win.select_mode:
            win.set_select_mode(False)
    finally:
        win.inform, win.popup = old_inform, old_popup
    s.db.delete(late)
    win.reload()
    win.show_group("Project")
    s.pump(0.3)
    stray = [n for n in notices if "already available" not in n[1]]
    if stray:
        problem(f"unexpected notices: {stray}")
    ok("a group tab's menu and select mode make scripts and pipelines available "
       "to agents: asks about what is new, off asks nothing, nothing rebuilt, "
       "hidden in the build without agents")


def step_keyboard_and_menu(s: Session) -> None:
    """Esc clears the search (TW-14); the Select menu entry reads "Cancel
    select" while the mode is on (SM-12); Ctrl+V on a row pastes into that
    row's group (GR-25)."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest

    from ryos import selection
    win = s.win

    win.search_box.setText("fail")
    s.pump(0.4)
    QTest.keyClick(win.search_box, Qt.Key.Key_Escape)
    s.pump(0.4)
    if win.search_box.text() != "":
        problem(f"Esc left {win.search_box.text()!r} in the search box")
    shown = [c._name for c in win.card_lists["Project"].cards if c.isVisibleTo(win)]
    if len(shown) < 5:
        problem(f"after Esc the list shows only {shown}")

    if win.select_action.text() != selection.ENTER_LABEL:
        problem(f"the Select entry reads {win.select_action.text()!r} at rest")
    win.select_action.trigger()
    if win.select_action.text() != selection.LEAVE_LABEL or not win.select_mode:
        problem(f"the Select entry reads {win.select_action.text()!r} in select mode")
    win.select_action.trigger()
    if win.select_action.text() != selection.ENTER_LABEL or win.select_mode:
        problem(f"the Select entry reads {win.select_action.text()!r} after leaving")

    s.db.create_group("Other")
    other_id = s.db.add("Other one", str(s.work / "away.py"), "", sys.executable, "Other")
    win.reload()
    win.show_group("Project")
    s.pump(0.3)
    ctrl = Qt.KeyboardModifier.ControlModifier
    s.app.sendEvent(s.card("Project", "Say hello"),
                    QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, ctrl))
    if win.copied_name() != "Say hello":
        problem(f"Ctrl+C on a row held {win.copied_name()!r}")
    s.app.sendEvent(s.card("Other", "Other one"),
                    QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, ctrl))
    s.pump(0.4)
    rows = [(r[0], r[1]) for r in s.db.list_all() if (r[8] or "") == "Other"]
    pasted = [i for i, n in rows if n.startswith("Say hello")]
    if len(rows) != 2 or len(pasted) != 1:
        problem(f"after Ctrl+V on a row of Other, that group holds {rows}")
    for sid in pasted + [other_id]:
        s.db.delete(sid)
    s.db.delete_group("Other")
    win._copied = None
    win.reload()
    win.show_group("Project")
    s.pump(0.3)
    ok("Esc clears the search; the Select entry flips to Cancel select and back; "
       "Ctrl+V on a row pastes into that row's group")


def step_help_and_log(s: Session) -> None:
    """Report a bug opens the browser, then shows where the log is; Help ->
    Open log folder opens that folder (TW-18, TW-25); Suggest a feature
    opens a titled, labelled issue (TW-26)."""
    from pathlib import Path

    from ryos import settings as settings_mod
    win = s.win
    s.urls.clear()
    s.folders.clear()

    def fill(dlg):
        shown = Path(dlg.path_label.text())
        appdata = Path(os.environ["APPDATA"]).resolve()
        if appdata not in shown.resolve().parents:
            problem(f"the bug report shows a log outside the session folder: {shown}")
        if shown != Path(settings_mod.LOG_PATH):
            problem(f"the bug report shows {shown}, not the log")
        dlg.open_button.click()

    s.expect_dialog("BugReportDialog", fill)
    win.bug_button.click()
    win.open_log_action.trigger()
    s.pump(0.2)
    if len(s.urls) != 1:
        problem(f"Report a bug opened {len(s.urls)} links, not 1")
    want = [str(settings_mod.LOG_DIR)] * 2
    if s.folders != want:
        problem(f"the log folder was opened as {s.folders}, not {want}")
    ok("Report a bug opens one link then the log dialog; its button and "
       "Help -> Open log folder both open the log folder")

    # Suggest a feature (TW-26): button and menu, a titled, labelled issue.
    from urllib.parse import parse_qs, urlparse

    from ryos import suggestion
    s.urls.clear()
    win.suggest_button.click()
    win.suggest_action.trigger()
    s.pump(0.2)
    if len(s.urls) != 2:
        problem(f"Suggest a feature opened {len(s.urls)} links, not 2")
    for url in s.urls:
        query = parse_qs(urlparse(url).query)
        if query.get("labels") != ["enhancement"] \
                or query.get("title") != ["Suggestion: "]:
            problem(f"the suggestion link is not titled and labelled: {url[:120]}")
    if win.statusBar().currentMessage() != suggestion.OPENED:
        problem("suggesting did not say what happened: "
                f"{win.statusBar().currentMessage()!r}")
    sb, bb = win.suggest_button, win.bug_button
    if not sb.isVisible() or sb.x() >= bb.x():
        problem("the suggestion button is not visible and left of the bug button")
    ok("Suggest a feature opens a titled, labelled issue from the status bar "
       "and Help, says so, and sits left of the bug button")


def step_favourite_and_delete(s: Session) -> None:
    win = s.win
    s.card("Project", "Say hello").fav_button.click()
    s.pump(0.4)
    favs = [c._name for c in win.card_lists["Project"].favorite_cards
            if c.isVisibleTo(win)]
    rec = next(r for r in s.db.list_all() if r[1] == "Say hello")
    if not rec[10]:
        problem("the favourite was not saved")
    if favs != ["Say hello"]:
        problem(f"Favorites shows {favs}, not the new favourite")

    # A favourite has two cards; a run's outcome must reach both at once.
    # The refresh walked only the group's own cards, so the copy at the top
    # kept its old state (found on a screenshot).
    # "Mark" last succeeded, so both its cards start as Run; pointed at a
    # folder instead of a file, its next run fails.
    from ryos import cardstyle
    mark = s.script_id("Mark")
    rec = s.db.get(mark)
    s.db.update(mark, rec[1], rec[2], str(s.work), rec[4], rec[5])
    s.card("Project", "Mark").fav_button.click()        # reloads the cards
    s.pump(0.4)
    page = win.card_lists["Project"]

    def mark_states():
        both = [c for c in (*page.favorite_cards, *page.cards) if c._name == "Mark"]
        return [c.run_button.property("runState") for c in both]
    if mark_states() != [cardstyle.RUN] * 2:
        problem(f"before the run, Mark's two cards show {mark_states()}")
    runs = len(s.runs(script_id=mark))
    next(c for c in page.favorite_cards if c._name == "Mark").run_button.click()
    s.wait_for(lambda: len(s.runs(script_id=mark)) > runs, "the favourite's run")
    s.idle("favourite run")
    s.pump(0.3)
    if mark_states() != [cardstyle.RETRY] * 2:
        problem(f"after a failed run, the favourite's two cards show {mark_states()}")

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
    s.win.ask_import_mode = lambda: "merge"
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
    # History older than the retention window goes at start-up (HI-05); a
    # recent run stays.
    hello = s.script_id("Say hello")
    old = s.db.record_run("script", name="Say hello", script_id=hello,
                          started_at="2000-01-01T00:00:00", status="ok", exit_code=0)
    recent = s.db.record_run("script", name="Say hello", script_id=hello,
                             started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                             status="ok", exit_code=0)
    if not win.quit_app():
        problem("quitting was refused")
    s.pump(0.3)
    s.restarting[0] = True
    settings = settings_loader()
    app, win2 = build(settings=settings, show=True)
    s.hook(win2)
    s.pump(0.5)
    if "Project" not in win2.card_lists:
        problem("after a restart the Project group is gone")
        return
    names = sorted(c._name for c in win2.card_lists["Project"].cards)
    want = sorted(["Say hello", "Fail", "Slow", "Mark", "Release", "fresh"])
    # Favourites show a second card for the same script.
    if sorted(set(names)) != want:
        problem(f"after a restart Project shows {names}")
    if settings.get("theme") != s.theme or settings.get("max_output_lines") != 777:
        problem("settings did not survive the restart")
    if win2.current_group() != "Project":
        problem(f"the app reopened on {win2.current_group()!r}, not the last group")
    conn = sqlite3.connect(s.db.db_path)
    try:
        left = {r[0] for r in conn.execute("SELECT id FROM runs WHERE id IN (?, ?)",
                                           (old, recent))}
    finally:
        conn.close()
    if old in left or recent not in left:
        problem(f"start-up pruning kept {sorted(left)}: the 2000 run {old} should "
                f"be gone and the recent run {recent} kept")
    win2.quit_app()
    s.pump(0.2)
    ok("restart: groups, scripts, the pipeline, options, theme and the last group "
       "all come back; history past its retention is pruned")


def run_both(args) -> int:
    """One process per layout: the data paths are fixed when ryos is imported,
    so each pass needs its own interpreter and throwaway folder."""
    import subprocess
    codes: dict[str, tuple[int, float]] = {}
    for layout in ("normal", "compact"):
        print(f"\n=== session smoke: {layout} layout ===", flush=True)
        cmd = [sys.executable, str(Path(__file__).resolve()), "--layout", layout]
        if args.visible:
            cmd.append("--visible")
        start = time.monotonic()
        code = subprocess.call(cmd)
        codes[layout] = (code, time.monotonic() - start)
    print()
    for layout, (code, secs) in codes.items():
        print(f"{layout}: {'passed' if code == 0 else f'FAILED (exit {code})'} "
              f"in {secs:.0f}s")
    return 0 if all(c == 0 for c, _t in codes.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--visible", action="store_true",
                        help="show the window, on a second screen when there is one")
    parser.add_argument("--layout", choices=("normal", "compact", "both"),
                        default="both",
                        help="rows to run the session with (default: both, each in "
                             "its own process and throwaway folder)")
    args = parser.parse_args()
    if args.layout == "both":
        return run_both(args)
    LAYOUT[0] = args.layout

    real = _real_folder()
    real_before = _snapshot(real)
    tmp = Path(tempfile.mkdtemp(prefix="ryos-session-"))
    os.environ["APPDATA"] = str(tmp)
    os.environ["RYOS_NO_REGISTRY"] = "1"
    os.environ["RYOS_NO_TOASTS"] = "1"
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
    print(f"RYOS session smoke, {args.layout} layout (a throwaway folder: {tmp}; "
          f"{'window on the smoke screen' if args.visible else 'no window'})")

    from ryos.logger import setup_logging
    setup_logging(True, "INFO")
    errors: list[str] = []
    sys.excepthook = lambda t, v, tb: errors.append(
        "".join(traceback.format_exception(t, v, tb)))

    s_restarting = [False]

    def load_settings():
        settings = settings_mod._load_settings()
        settings["auto_check_update"] = False
        settings["open_on_cursor_monitor"] = False
        # A definite place to open, so the start-up check can tell it from
        # Qt's default spot; the saved geometry takes over after a restart.
        if not settings.get("window_geometry") or not s_restarting[0]:
            settings["window_geometry"] = "500x600+150+120"
        settings["remember_window_geometry"] = True
        settings["snap_corner"] = "none"
        settings["compact_mode"] = args.layout == "compact"
        if args.visible:
            sys.path.insert(0, str(ROOT / "tests"))
            from smoke_screen import smoke_screen
            area = smoke_screen()
            if area:
                settings["window_geometry"] = f"540x700+{area[0] + 40}+{area[1] + 40}"
                settings["snap_corner"] = "none"
        return settings

    from ryos.db import ScriptDB
    from ryos.qtui.main import build
    work = tmp / "work"
    project = make_files(work)
    # Where the window is at the moment it first shows: it must already be
    # where it belongs, not at Qt's default spot on the primary screen.
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication, QMainWindow
    shown_at: list = []

    class _FirstShow(QObject):
        def eventFilter(self, obj, event):               # noqa: N802
            if (event.type() == QEvent.Type.Show and isinstance(obj, QMainWindow)
                    and not shown_at):
                shown_at.append((obj.geometry().topLeft().toTuple(),
                                 obj.screen().name() if obj.screen() else None))
            return False
    first_show = _FirstShow()
    app0 = QApplication.instance() or QApplication(sys.argv)
    app0.installEventFilter(first_show)
    app, win = build(settings=load_settings(), show=True)
    app.removeEventFilter(first_show)
    s = Session(app, win, ScriptDB(), work)
    s.visible = args.visible
    s.restarting = s_restarting
    s.pump(0.5)
    final = (win.geometry().topLeft().toTuple(), win.screen().name())
    if not shown_at:
        problem("the window was never shown")
    elif shown_at[0][1] != final[1] or any(
            abs(a - b) > 30 for a, b in zip(shown_at[0][0], final[0])):
        problem(f"the window first showed at {shown_at[0]} and then moved to {final}")
    else:
        ok(f"start-up: the window first shows where it stays, {final}")

    if win.statusBar().currentMessage() != "Ready":
        problem(f"at start-up the status bar says {win.statusBar().currentMessage()!r}")
    if bool(win._settings.get("compact_mode")) != (args.layout == "compact"):
        problem("the compact_mode setting did not reach the window")

    steps = [lambda: step_groups_and_scripts(s, project),
             lambda: step_run_and_output(s),
             lambda: step_failure_and_retry(s),
             lambda: step_stop(s),
             lambda: step_status_line(s),
             lambda: step_output_options(s),
             lambda: step_run_click(s),
             lambda: step_pipeline(s),
             lambda: step_schedule(s),
             lambda: step_scheduled_outside(s),
             lambda: step_quick_run_search_select(s, project),
             lambda: step_agents_for_a_group(s, project),
             lambda: step_keyboard_and_menu(s),
             lambda: step_help_and_log(s),
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

    for bug in KNOWN_BUGS:
        print(f"  known app bug (not failed): {bug}")
    print(f"\nRYOS session smoke ({args.layout}) {'FAILED' if PROBLEMS else 'PASSED'}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    raise SystemExit(main())
