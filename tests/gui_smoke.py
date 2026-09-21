#!/usr/bin/env python3
"""Real-Tk GUI smoke test for RYOS — runs under Xvfb in CI.

Unlike ``tests/test_ryos.py`` (which mocks tkinter), this builds the REAL
``RYOSApp`` on a real Tk display and drives scripts through the full job
lifecycle that the mocked suite cannot reach:

    _run_script -> JobController.new_job -> on_started (tab + ticker)
                -> _launch (worker thread) -> runner.run_subprocess
                -> _drain_output_queue -> JobController.pump
                -> handle_step_done -> _finish_job

It exercises two paths — a script that runs to completion, and a long-running
script that is stopped mid-run — and exits non-zero on any failure so CI catches
regressions in the widget + controller integration. The scripts it runs are
generated inline, so it depends on no fixture files.

Run locally:  xvfb-run -a python tests/gui_smoke.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ryos.ui.app as appmod  # noqa: E402
from ryos.ui.app import RYOSApp  # noqa: E402

TIMEOUT = 30.0  # generous; the quick job finishes well under a second


def pump_until(app, predicate, timeout=TIMEOUT):
    """Drive the Tk event loop (incl. the after-scheduled drain) until predicate."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.update_idletasks()
        app.update()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _write_script(body: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
    tmp.write(body)
    tmp.close()
    return tmp.name


def _last_run_status(app, script_id):
    with app.db._connect() as conn:
        row = conn.execute(
            "SELECT last_run_status FROM scripts WHERE id=?", (script_id,)
        ).fetchone()
    return row[0] if row else None


def check_run_to_completion(app):
    """A trivial script should run, complete, persist 'ok', and unregister."""
    path = _write_script("print('hello from gui smoke')\n")
    sid = app.db.add("smoke-ok", path, "", sys.executable)
    try:
        app._run_script(sid, "smoke-ok", path, "", sys.executable)
        assert len(app._jobreg) == 1, "job was not registered on launch"
        finished = pump_until(app, lambda: len(app._jobreg) == 0)
        assert finished, "job did not finish within timeout"
        status = _last_run_status(app, sid)
        assert status == "ok", f"expected last_run_status 'ok', got {status!r}"
        print("  [ok] run-to-completion: job finished and status persisted")
    finally:
        app.db.delete(sid)
        os.unlink(path)


def check_stop_running_job(app):
    """A long-running script should be stoppable, and stopping unregisters it."""
    path = _write_script(
        "import time, sys\n"
        "for i in range(600):\n"
        "    print(i, flush=True)\n"
        "    time.sleep(0.5)\n"
    )
    sid = app.db.add("smoke-stop", path, "", sys.executable)
    try:
        app._run_script(sid, "smoke-stop", path, "", sys.executable)
        assert len(app._jobreg) == 1, "slow job was not registered"
        # Let the worker actually spawn the process before stopping.
        pump_until(app, lambda: app._jobreg.all()[0].current_process is not None, timeout=10)
        job = app._jobreg.all()[0]
        app._stop_job(job)
        stopped = pump_until(app, lambda: len(app._jobreg) == 0)
        assert stopped, "stopped job did not unregister"
        assert job.stopped is True, "job.stopped flag was not set"
        print("  [ok] stop-running-job: job stopped and unregistered")
    finally:
        app.db.delete(sid)
        os.unlink(path)


def check_card_rendering(app):
    """Seed a favorite, a plain script, and a pipeline, then re-render the list.

    Exercises the extracted section builders (banner / running / favorites /
    pipelines / scripts) on a real Tk surface -- the headless unit suite can't
    reach these widget paths."""
    paths = [_write_script("print('a')\n"), _write_script("print('b')\n")]
    s1 = app.db.add("smoke-fav", paths[0], "", sys.executable)
    s2 = app.db.add("smoke-plain", paths[1], "", sys.executable)
    app.db.set_favorite_script(s1, True)
    pid = app.db.create_pipeline("smoke-pipe", "")
    try:
        app._active_group = None  # "All" view renders ungrouped scripts
        app._refresh_cards()
        app.update_idletasks()
        app.update()
        names = [getattr(c, "_name", "") for c in app._cards]
        assert "smoke-fav" in names and "smoke-plain" in names, \
            f"cards not rendered: {names}"
        print("  [ok] card-rendering: section builders ran, scripts rendered")
    finally:
        app.db.delete(s1)
        app.db.delete(s2)
        app.db.delete_pipeline(pid)
        for fp in paths:
            os.unlink(fp)
        app._refresh_cards()


def check_card_button_alignment(app):
    """Script and pipeline cards must present the same button columns.

    A script card has a fourth button (▶+ Run with parameter) that pipelines
    have no equivalent for, so without a spacer only the Run column lines up
    in a mixed list (issue #3). Measured in pixels, because the spacer has to
    be the same widget class to come out the same width — a Label sized to the
    same character width lands 4px narrower.
    """
    import tkinter as tk

    path = _write_script("print('align')\n")
    sid = app.db.add("smoke-align", path, "", sys.executable, "smoke-align-grp")
    pid = app.db.create_pipeline("smoke-align-pipe", "smoke-align-grp")

    def cells(card):
        strip = [w for w in card.winfo_children()
                 if isinstance(w, tk.Frame)
                 and any(isinstance(c, tk.Button) for c in w.winfo_children())]
        assert strip, "button strip not found"
        return [(w.winfo_rootx(), w.winfo_width())
                for w in strip[0].winfo_children() if w.winfo_width() > 1]

    try:
        app._active_group = "smoke-align-grp"
        app._refresh_cards()
        app.update_idletasks()
        app.update()
        card = next(c for c in app._cards
                    if getattr(c, "_name", "") == "smoke-align")
        pipe = next(c for c in app._pipeline_cards
                    if getattr(c, "_name", "") == "smoke-align-pipe")
        sc, pc = cells(card), cells(pipe)
        assert len(sc) == len(pc), f"columns differ: {len(sc)} vs {len(pc)}"
        for i, (a, b) in enumerate(zip(sc, pc)):
            assert abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1, (
                f"column {i} misaligned: script {a} vs pipeline {b}")
        print(f"  [ok] card-buttons: {len(sc)} columns aligned across card types")
    finally:
        app.db.delete_pipeline(pid)
        app.db.delete(sid)
        app.db.delete_group("smoke-align-grp")
        os.unlink(path)
        app._active_group = None
        app._refresh_cards()



def check_spacer_does_not_look_like_a_button(app):
    """The pipeline card's alignment spacer must read as a gap, not a control.

    Issue #3 added a blank disabled button so both card types have four
    columns. Issue #7 was that it was painted btn_neutral_bg like a real
    button, which sits ~1.03:1 against the strip -- so it looked like a button
    whose icon had failed to load. Blank and disabled was not enough; the
    colour is what carried the wrong signal.

    Checked on real widgets because this is about what is painted, which the
    mocked suite cannot see.
    """
    import tkinter as tk

    from ryos.ui.theme import C

    path = _write_script("print('spacer')\n")
    sid = app.db.add("smoke-spacer", path, "", sys.executable, "smoke-spacer-grp")
    pid = app.db.create_pipeline("smoke-spacer-pipe", "smoke-spacer-grp")

    def buttons(card):
        strip = [w for w in card.winfo_children()
                 if isinstance(w, tk.Frame)
                 and any(isinstance(c, tk.Button) for c in w.winfo_children())]
        assert strip, "button strip not found"
        return [w for w in strip[0].winfo_children() if isinstance(w, tk.Button)]

    try:
        app._active_group = "smoke-spacer-grp"
        app._refresh_cards()
        app.update_idletasks()
        app.update()
        card = next(c for c in app._cards
                    if getattr(c, "_name", "") == "smoke-spacer")
        pipe = next(c for c in app._pipeline_cards
                    if getattr(c, "_name", "") == "smoke-spacer-pipe")
        real = buttons(card)[2]          # the script card's ▶+ button
        spacer = buttons(pipe)[2]        # the pipeline card's spacer

        spacer_bg = str(spacer.cget("bg"))
        real_bg = str(real.cget("bg"))
        assert spacer_bg == C["border"], (
            f"spacer is {spacer_bg}, expected the strip colour {C['border']}")
        assert spacer_bg != real_bg, (
            f"spacer still painted like a real button ({spacer_bg})")
        assert str(spacer.cget("state")) == "disabled", "spacer is clickable"
        # issue #3 must stay fixed
        assert spacer.winfo_width() == real.winfo_width(), (
            f"spacer width {spacer.winfo_width()} != button "
            f"{real.winfo_width()} — issue #3 regressed")
        print(f"  [ok] spacer-reads-as-gap: {spacer_bg} matches the strip, "
              f"width {spacer.winfo_width()} still matches the button")
    finally:
        app.db.delete_pipeline(pid)
        app.db.delete(sid)
        app.db.delete_group("smoke-spacer-grp")
        os.unlink(path)
        app._active_group = None
        app._refresh_cards()


def check_card_run(app):
    """Run a script the way a user does: through the card's own Run button.

    check_run_to_completion calls app._run_script directly, which skips
    ScriptCard._run -- and that is where the record returned by db.get() is
    unpacked. Widening db.get() has broken that unpack twice now (temp_param,
    then env_vars/work_dir) without any test noticing, because the headless
    suite mocks Tk and the other smoke checks bypass the card.
    """
    path = _write_script("print('card run')\n")
    sid = app.db.add("smoke-card-run", path, "", sys.executable)
    try:
        app._active_group = None
        app._refresh_cards()
        app.update_idletasks()
        card = next((c for c in app._cards if getattr(c, "_name", "") == "smoke-card-run"), None)
        assert card is not None, "card was not rendered"
        card._run()
        assert len(app._jobreg) == 1, "card Run did not register a job"
        finished = pump_until(app, lambda: len(app._jobreg) == 0)
        assert finished, "card-launched job did not finish within timeout"
        status = _last_run_status(app, sid)
        assert status == "ok", f"expected last_run_status 'ok', got {status!r}"
        print("  [ok] card-run: ScriptCard._run launched and completed")
    finally:
        app.db.delete(sid)
        os.unlink(path)
        app._refresh_cards()


def check_failed_run_button_becomes_retry(app):
    """After a failure the Run button turns into Retry (issue #4).

    Checked in both card modes and against the real button, because the first
    version of this hung the retry off the status badge -- which compact cards
    don't render at all, and which a long path squeezed to 1px in normal mode.
    The button strip is present at every card size, which is why it is the
    right home for the action.

    invoke() rather than a synthetic click: widgets here are laid out but never
    displayed (winfo_ismapped is 0 with correct geometry), so a generated
    <Button-1> is swallowed and the check would pass vacuously.
    """
    import tkinter as tk

    from ryos.ui import cards as cards_mod
    from ryos.ui.theme import C

    def run_button(card):
        strip = [w for w in card.winfo_children()
                 if isinstance(w, tk.Frame)
                 and any(isinstance(c, tk.Button) for c in w.winfo_children())][0]
        return list(strip.winfo_children())[-1]

    path = _write_script("import sys; sys.exit(1)\n")
    sid = app.db.add("smoke-retry", path, "", sys.executable)
    original_compact = cards_mod._COMPACT
    try:
        app._active_group = None
        app._refresh_cards()
        app.update_idletasks()
        app.update()
        card = next(c for c in app._cards
                    if getattr(c, "_name", "") == "smoke-retry")
        assert str(run_button(card).cget("text")) == "▶",             "a script that has never run should show Run, not Retry"

        app._run_script(sid, "smoke-retry", path, "", sys.executable)
        assert pump_until(app, lambda: len(app._jobreg) == 0), "first run did not finish"
        assert _last_run_status(app, sid) == "error", "script did not fail as set up"

        for compact in (False, True):
            cards_mod.set_compact_mode(compact)
            app._refresh_cards()
            app.update_idletasks()
            app.update()
            card = next(c for c in app._cards
                        if getattr(c, "_name", "") == "smoke-retry")
            btn = run_button(card)
            assert str(btn.cget("text")) == "↻", (
                f"compact={compact}: Run button did not become Retry "
                f"(reads {str(btn.cget('text'))!r})")
            assert str(btn.cget("bg")) == C["error"], (
                f"compact={compact}: retry button is not marked as a failure")
            assert btn.winfo_width() >= 10 and btn.winfo_height() >= 10, (
                f"compact={compact}: retry button collapsed to "
                f"{btn.winfo_width()}x{btn.winfo_height()}")

            btn.invoke()
            assert len(app._jobreg) == 1, (
                f"compact={compact}: the retry button did not re-run it")
            assert pump_until(app, lambda: len(app._jobreg) == 0), "retry did not finish"
        print("  [ok] retry-button: Run becomes Retry after a failure, both modes")
    finally:
        cards_mod.set_compact_mode(original_compact)
        app.db.clear_runs(script_id=sid)
        app.db.delete(sid)
        os.unlink(path)
        app._refresh_cards()


def check_run_history(app):
    """A completed run must leave a history row carrying its real exit code."""
    path = _write_script("import sys; print('bye'); sys.exit(5)\n")
    sid = app.db.add("smoke-history", path, "", sys.executable)
    try:
        app._run_script(sid, "smoke-history", path, "", sys.executable)
        assert pump_until(app, lambda: len(app._jobreg) == 0), "job did not finish"
        rows = app.db.list_runs(script_id=sid)
        assert len(rows) == 1, f"expected one history row, got {len(rows)}"
        assert rows[0][7] == "error", f"expected status 'error', got {rows[0][7]!r}"
        assert rows[0][8] == 5, f"expected exit code 5, got {rows[0][8]!r}"
        print("  [ok] run-history: row recorded with real exit code")
    finally:
        app.db.clear_runs(script_id=sid)
        app.db.delete(sid)
        os.unlink(path)


def check_run_selected(app):
    """Select mode runs every ticked script, and refuses past the job limit once.

    Capacity is resolved before launching, so the over-limit case must report
    a single count rather than popping one rejection per script -- which is
    what would happen if each launch checked for itself.
    """
    import unittest.mock as mock

    paths = [_write_script(f"print('bulk {i}')\n") for i in range(3)]
    ids = [app.db.add(f"smoke-bulk-{i}", p, "", sys.executable)
           for i, p in enumerate(paths)]
    original_cap = app._settings.get("max_parallel_jobs")
    try:
        app._active_group = None
        app._refresh_cards()
        app.update_idletasks()
        cards = [c for c in app._cards
                 if getattr(c, "_name", "").startswith("smoke-bulk-")]
        assert len(cards) == 3, f"expected 3 cards, got {len(cards)}"

        # Nothing ticked -> an explanation, not a silent no-op.
        with mock.patch.object(appmod.messagebox, "showinfo") as info:
            app._run_selected()
        assert info.called, "running with nothing selected said nothing"
        assert len(app._jobreg) == 0

        # All three fit under the normal cap.
        app._settings["max_parallel_jobs"] = 10
        for c in cards:
            c.selected.set(True)
        with mock.patch.object(appmod.messagebox, "showinfo") as info:
            app._run_selected()
        assert len(app._jobreg) == 3, f"expected 3 jobs, got {len(app._jobreg)}"
        assert not info.called, "reported a limit that was not reached"
        assert pump_until(app, lambda: len(app._jobreg) == 0), "bulk jobs did not finish"

        # Tighten the cap: only some can start, and it says so exactly once.
        app._settings["max_parallel_jobs"] = 2
        for c in cards:
            c.selected.set(True)
        with mock.patch.object(appmod.messagebox, "showinfo") as info:
            app._run_selected()
        assert len(app._jobreg) == 2, f"expected 2 jobs, got {len(app._jobreg)}"
        assert info.call_count == 1, \
            f"expected one limit message, got {info.call_count}"
        assert "1" in " ".join(str(a) for a in info.call_args[0]), \
            f"message didn't name the skipped count: {info.call_args}"
        assert all(c.selected.get() for c in cards), \
            "selection was cleared, so the skipped scripts can't be retried"
        assert pump_until(app, lambda: len(app._jobreg) == 0), "jobs did not finish"
        print("  [ok] run-selected: bulk launch, and one message past the limit")
    finally:
        if original_cap is not None:
            app._settings["max_parallel_jobs"] = original_cap
        for sid in ids:
            app.db.clear_runs(script_id=sid)
            app.db.delete(sid)
        for fp in paths:
            os.unlink(fp)
        app._refresh_cards()


def check_output_search_and_filter(app):
    """Find highlights matches, and Errors only hides everything else.

    The filter works by eliding tags rather than rebuilding the buffer, so this
    also checks the underlying text is left intact — a filter that destroyed
    output would be far worse than no filter.
    """
    key = "all"
    app._activate_tab(key)
    app._clear_log()
    app._append_output("building widget alpha\n", tab_key=key)
    app._append_output("ERROR: widget exploded\n", tag="stderr", tab_key=key)
    app._append_output("building widget beta\n", tab_key=key)
    app.update_idletasks()
    text = app._output_tabs[key]["text"]

    def tagged(tag):
        r = text.tag_ranges(tag)
        return [text.get(r[i], r[i + 1]) for i in range(0, len(r), 2)]

    try:
        app._out_find_var.set("widget")
        app.update_idletasks()
        assert len(tagged("search")) == 3, tagged("search")
        assert app._out_match_var.get() == "0/3", app._out_match_var.get()
        app._step_output_match(True)
        assert app._out_match_var.get() == "1/3"
        app._out_find_var.set("")
        app.update_idletasks()
        assert tagged("search") == [], "highlights survived clearing the query"

        app._out_errors_var.set(True)
        app._apply_output_filter()
        app.update_idletasks()
        assert str(text.tag_cget("stdout", "elide")) in ("1", "true"), \
            "errors-only did not elide plain output"
        assert str(text.tag_cget("stderr", "elide")) not in ("1", "true"), \
            "errors-only elided the errors themselves"
        assert "building widget alpha" in text.get("1.0", "end"), \
            "filtering destroyed the buffer"
        app._out_errors_var.set(False)
        app._apply_output_filter()
        app.update_idletasks()
        assert str(text.tag_cget("stdout", "elide")) in ("0", "false", ""), \
            "plain output stayed hidden after turning the filter off"
        print("  [ok] output-search: find highlights, errors-only elides, buffer intact")
    finally:
        app._out_find_var.set("")
        app._out_errors_var.set(False)
        app._apply_output_filter()
        app._clear_log()


def check_pipeline_editor_lists_steps(app):
    """Opening the pipeline editor must actually show the steps.

    Regression guard for issue #2. list_pipeline_steps has grown twice
    (trigger_mode, then env_vars/work_dir) and the editor unpacked its rows
    into a fixed number of names, so _reload_steps raised and the list came up
    empty -- the steps looked like they had been deleted. Nothing caught it:
    the headless suite mocks Tk, so this dialog never runs there.
    """
    from ryos.ui.pipeline import PipelineEditorDialog

    paths = [_write_script("print('one')\n"), _write_script("print('two')\n")]
    a = app.db.add("smoke-step-a", paths[0], "", sys.executable, "smoke-pipe-grp")
    b = app.db.add("smoke-step-b", paths[1], "", sys.executable, "smoke-pipe-grp")
    pid = app.db.create_pipeline("smoke-editor", "smoke-pipe-grp")
    app.db.add_pipeline_step(pid, a)
    app.db.add_pipeline_step(pid, b)
    # An override and a concurrent step, so the label-building branches run too.
    steps = app.db.list_pipeline_steps(pid)
    app.db.update_pipeline_step_params(steps[1][0], "--ci")
    app.db.set_step_trigger_mode(steps[1][0], "with")

    dlg = None
    try:
        dlg = PipelineEditorDialog(app, app.db, pid, "smoke-editor",
                                   "smoke-pipe-grp", lambda: None)
        app.update_idletasks()
        rows = list(dlg._listbox.get(0, "end"))
        assert len(rows) == 2, f"editor showed {len(rows)} steps, expected 2: {rows}"
        assert "smoke-step-a" in rows[0], rows
        assert "smoke-step-b" in rows[1], rows
        assert "--ci" in rows[1], f"param override not shown: {rows[1]!r}"
        assert rows[1].startswith("∥"), f"concurrent marker missing: {rows[1]!r}"
        # Selecting a row reads the same tuple a second way.
        dlg._listbox.selection_clear(0, "end")
        dlg._listbox.selection_set(1)
        dlg._on_step_select()
        app.update_idletasks()
        assert str(dlg._on_failure_combo.cget("state")) == "readonly", \
            "policy controls stayed disabled with a step selected"

        # Set a non-default policy through the real handler and check it shows.
        dlg._on_failure_var.set(dlg._FAIL_LABELS["continue"])
        dlg._retries_var.set("2")
        dlg._on_policy_change()
        app.update_idletasks()
        stored = app.db.list_pipeline_steps(pid)[1]
        assert stored[10] == "continue" and stored[11] == 2, stored[10:]
        marked = dlg._listbox.get(1)
        assert "!" in marked and "↻2" in marked, f"policy marks missing: {marked!r}"

        # Removing the selection must leave the controls disabled, not stale.
        dlg._listbox.selection_clear(0, "end")
        dlg._listbox.selection_set(0)
        dlg._on_step_select()
        dlg._remove_selected()
        app.update_idletasks()
        assert str(dlg._on_failure_combo.cget("state")) == "disabled", \
            "policy controls stayed enabled after Remove"
        print("  [ok] pipeline-editor: steps, override, marker and policy controls")
    finally:
        if dlg is not None:
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()
        app.db.delete_pipeline(pid)
        app.db.delete(a)
        app.db.delete(b)
        app.db.delete_group("smoke-pipe-grp")
        for fp in paths:
            os.unlink(fp)
        app._refresh_cards()


def check_schedule_fires(app):
    """A due schedule launches its script, and the run is tagged as scheduled.

    Drives the real tick against a schedule whose next_run_at is already in the
    past -- the same path a run missed while RYOS was closed takes on startup.
    """
    import json
    from datetime import datetime, timedelta

    path = _write_script("print('scheduled')\n")
    sid = app.db.add("smoke-sched", path, "", sys.executable)
    sched = app.db.add_schedule(
        "script", script_id=sid, spec_type="interval",
        spec=json.dumps({"minutes": 60}), enabled=True,
        next_run_at=datetime.now() - timedelta(minutes=5))
    try:
        app._run_due_schedules()
        assert len(app._jobreg) == 1, "due schedule did not launch anything"
        assert pump_until(app, lambda: len(app._jobreg) == 0), "scheduled job did not finish"

        rows = app.db.list_runs(script_id=sid)
        assert len(rows) == 1, f"expected one history row, got {len(rows)}"
        assert rows[0][10] == "schedule", \
            f"run should be tagged 'schedule', got {rows[0][10]!r}"

        row = app.db.get_schedule(script_id=sid)
        assert row[8] is not None, "next_run_at was not advanced"
        assert datetime.fromisoformat(row[8]) > datetime.now(), \
            "next_run_at must be in the future after firing"
        assert not app.db.due_schedules(datetime.now()), "schedule is still due"

        # A second sweep must not re-run it.
        app._run_due_schedules()
        assert len(app._jobreg) == 0, "schedule fired twice for one due time"
        print("  [ok] schedule-fires: launched, tagged, and advanced")
    finally:
        app.db.delete_schedule(sched)
        app.db.clear_runs(script_id=sid)
        app.db.delete(sid)
        os.unlink(path)


def check_schedule_skips_while_running(app):
    """A schedule must not stack a second run on top of one still going."""
    import json
    from datetime import datetime, timedelta

    path = _write_script(
        "import time\n"
        "for i in range(600):\n"
        "    print(i, flush=True)\n"
        "    time.sleep(0.5)\n"
    )
    sid = app.db.add("smoke-sched-overlap", path, "", sys.executable)
    sched = app.db.add_schedule(
        "script", script_id=sid, spec_type="interval",
        spec=json.dumps({"minutes": 1}), enabled=True,
        next_run_at=datetime.now() - timedelta(minutes=5))
    job = None
    try:
        app._run_due_schedules()
        assert len(app._jobreg) == 1, "first scheduled run did not start"
        job = app._jobreg.all()[0]
        pump_until(app, lambda: job.current_process is not None, timeout=10)
        # Force it due again while the first run is still going.
        app.db.mark_schedule_fired(sched, datetime.now() - timedelta(minutes=1))
        app._run_due_schedules()
        assert len(app._jobreg) == 1, "schedule stacked a second run on a running job"
        print("  [ok] schedule-overlap: second run skipped while the first is going")
    finally:
        if job is not None:
            app._stop_job(job)
            pump_until(app, lambda: len(app._jobreg) == 0)
        app.db.delete_schedule(sched)
        app.db.clear_runs(script_id=sid)
        app.db.delete(sid)
        os.unlink(path)


def check_favorites_reorder(app):
    """Move Up on a favorite reorders the shared script order.

    Regression guard: the Favorites move actions were wired to no-ops, so
    reorder silently did nothing there."""
    pa = _write_script("print('fa')\n")
    pb = _write_script("print('fb')\n")
    a = app.db.add("fav-A", pa, "", sys.executable)
    b = app.db.add("fav-B", pb, "", sys.executable)   # b gets the higher order_index
    app.db.set_favorite_script(a, True)
    app.db.set_favorite_script(b, True)
    try:
        app._active_group = None
        app._refresh_cards()
        app.update_idletasks()
        app.update()
        by_id = {}
        for content in app._fav_contents:
            for w in content.winfo_children():
                sid = getattr(w, "script_id", None)
                if sid in (a, b):
                    by_id[sid] = w
        assert a in by_id and b in by_id, f"favorite cards not found: {list(by_id)}"
        order = [r[0] for r in app.db.list_all()]
        assert order.index(a) < order.index(b), "precondition: A should precede B"
        by_id[b]._on_move_up()   # would be a no-op before the fix
        app.update_idletasks()
        app.update()
        order2 = [r[0] for r in app.db.list_all()]
        assert order2.index(b) < order2.index(a), "favorite Move Up did not reorder"
        print("  [ok] favorites-reorder: Move Up swapped the order")
    finally:
        app.db.delete(a)
        app.db.delete(b)
        os.unlink(pa)
        os.unlink(pb)
        app._refresh_cards()


def check_favorites_drag_reorder(app):
    """A favorites drag-drop release reorders within the group's shared order.

    Regression guard: favorite cards were never drag-bound, so drag reorder in
    Favorites did nothing. Simulates the drop directly (motion is hard to fake)."""
    import tkinter as tk
    pa = _write_script("print('da')\n")
    pb = _write_script("print('db')\n")
    a = app.db.add("fdrag-A", pa, "", sys.executable)
    b = app.db.add("fdrag-B", pb, "", sys.executable)
    app.db.set_favorite_script(a, True)
    app.db.set_favorite_script(b, True)
    ghost = None
    try:
        app._active_group = None
        app._refresh_cards()
        app.update_idletasks()
        app.update()
        fav = {c.script_id: c for c in app._fav_cards if c.script_id in (a, b)}
        assert a in fav and b in fav, f"favorite cards not drag-bound: {list(fav)}"
        order = [r[0] for r in app.db.list_all()]
        assert order.index(a) < order.index(b), "precondition: A before B"
        # Simulate dropping B before A (not over a tab).
        ghost = tk.Toplevel(app)
        app._drag_card = fav[b]
        app._drag_ghost = ghost           # truthy so release acts
        app._drag_target_group = None
        app._drag_insert_before = a
        app._card_drag_release(None)
        app.update_idletasks()
        app.update()
        order2 = [r[0] for r in app.db.list_all()]
        assert order2.index(b) < order2.index(a), "favorites drag did not reorder"
        print("  [ok] favorites-drag: drop reordered within favorites")
    finally:
        app.db.delete(a)
        app.db.delete(b)
        os.unlink(pa)
        os.unlink(pb)
        app._refresh_cards()


def check_launcher_auto_release(app):
    """A launcher (detached) script is auto-released from Running, leaving its
    process alive. Regression guard for the launcher run path."""
    slow = _write_script("import time\nfor _ in range(600):\n    time.sleep(0.5)\n")
    sid = app.db.add("smoke-launcher", slow, "", sys.executable, detached=1)
    app._settings["launcher_release_seconds"] = 0
    job = None
    try:
        assert app.db.is_detached(sid)
        app._run_script(sid, "smoke-launcher", slow, "", sys.executable)
        assert len(app._jobreg) == 1, "launcher job not registered on launch"
        job = app._jobreg.all()[0]
        released = pump_until(app, lambda: len(app._jobreg) == 0, timeout=10)
        assert released, "launcher was not auto-released from Running"
        print("  [ok] launcher-auto-release: detached script left no running job")
    finally:
        if job is not None and job.current_process is not None:
            try:
                job.current_process.terminate()
            except OSError:
                pass
        app.db.delete(sid)
        os.unlink(slow)
        app._refresh_cards()


def main():
    print("RYOS GUI smoke starting...")
    app = RYOSApp()
    app._settings["auto_check_update"] = False  # avoid network in CI
    try:
        pump_until(app, lambda: False, timeout=0.5)  # let the UI settle
        check_card_rendering(app)
        check_card_button_alignment(app)
        check_spacer_does_not_look_like_a_button(app)
        check_card_run(app)
        check_failed_run_button_becomes_retry(app)
        check_run_history(app)
        check_output_search_and_filter(app)
        check_run_selected(app)
        check_pipeline_editor_lists_steps(app)
        check_schedule_fires(app)
        check_schedule_skips_while_running(app)
        check_favorites_reorder(app)
        check_favorites_drag_reorder(app)
        check_launcher_auto_release(app)
        check_run_to_completion(app)
        check_stop_running_job(app)
    finally:
        try:
            app.destroy()
        except Exception:
            pass
    print("RYOS GUI smoke PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
