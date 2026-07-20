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


def main():
    print("RYOS GUI smoke starting...")
    app = RYOSApp()
    app._settings["auto_check_update"] = False  # avoid network in CI
    try:
        pump_until(app, lambda: False, timeout=0.5)  # let the UI settle
        check_card_rendering(app)
        check_favorites_reorder(app)
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
