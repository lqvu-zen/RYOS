#!/usr/bin/env python3
"""RYOS GUI driver — runs RYOS programmatically, captures screenshots.

Usage (always from project root):
    uv run --with pillow python .claude/skills/run-ryos/driver.py [scenario]

Scenarios:
    smoke           (default) launch, screenshot, quit
    quick-run-bar   launch, toggle the quick-run bar, screenshot, quit
    run-first       launch, run the first script card, screenshot output, quit
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from ryos.ui.app import RYOSApp  # noqa: E402

SHOTS_DIR = Path(__file__).parent / "screenshots"
SHOTS_DIR.mkdir(exist_ok=True)


def _shot(app: RYOSApp, name: str) -> Path:
    from PIL import ImageGrab
    app.lift()
    app.attributes("-topmost", True)
    app.focus_force()
    app.update_idletasks()
    app.update()
    app.attributes("-topmost", False)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    path = SHOTS_DIR / f"{name}.png"
    img.save(str(path))
    print(f"  screenshot -> {path.name}")
    return path


def _smoke(app: RYOSApp):
    def _do():
        print("smoke: launch screenshot")
        _shot(app, "01_launch")
        app.after(300, app.destroy)
    app.after(900, _do)


def _quick_run_bar(app: RYOSApp):
    def _do():
        print("quick-run-bar: initial screenshot")
        _shot(app, "01_launch")
        groups = list(app._quick_run_bars.keys())
        if not groups:
            print("  no quick-run bars found (need a group with a base directory)")
            app.after(300, app.destroy)
            return
        gname = groups[0]
        print(f"  toggling quick-run bar for group: {gname!r}")
        app._toggle_quick_run_bar(gname)
        app.after(400, _after_toggle)

    def _after_toggle():
        print("quick-run-bar: bar open screenshot")
        _shot(app, "02_bar_open")
        app.after(300, app.destroy)

    app.after(900, _do)


def _run_first(app: RYOSApp):
    def _do():
        print("run-first: initial screenshot")
        _shot(app, "01_launch")
        cards = app._cards
        if not cards:
            print("  no script cards found — quitting")
            app.after(300, app.destroy)
            return
        first = cards[0]
        print(f"  running card: {first._name!r}")
        first._run()
        app.after(2500, _after_run)

    def _after_run():
        print("run-first: post-run screenshot")
        _shot(app, "02_after_run")
        app.after(300, app.destroy)

    app.after(900, _do)


def _quick_run_autocomplete(app: RYOSApp):
    """Open Quick Run bar, type a character, wait for suggestion dropdown, screenshot."""
    def _do():
        print("autocomplete: initial screenshot")
        _shot(app, "01_launch")
        groups = list(app._quick_run_bars.keys())
        if not groups:
            print("  no quick-run bars found (need a group with a base directory)")
            app.after(300, app.destroy)
            return
        gname = groups[0]
        bar = app._quick_run_bars[gname]
        base_dir = bar["base_dir"]
        print(f"  group: {gname!r}, base_dir: {base_dir!r}")
        app._toggle_quick_run_bar(gname)
        app.after(400, lambda: _type_char(gname))

    def _type_char(gname):
        bar = app._quick_run_bars.get(gname)
        if not bar:
            print("  bar disappeared, quitting")
            app.after(300, app.destroy)
            return
        print("  bar open, simulating keypress 'p'")
        _shot(app, "02_bar_open")
        entry = bar["entry"]
        bar["var"].set("p")
        entry.config(fg=app._settings.get("name_fg", "#e8e8e8"))
        bar["is_placeholder"][0] = False
        entry.event_generate("<KeyRelease>", keysym="p")
        app.after(600, lambda: _check_suggestions(gname))

    def _check_suggestions(gname):
        bar = app._quick_run_bars.get(gname)
        _shot(app, "03_after_keypress")
        if bar:
            win = bar.get("suggest_win")
            lb = bar.get("suggest_lb")
            if win and win.winfo_exists() and lb:
                items = [lb.get(i) for i in range(lb.size())]
                print(f"  suggestion popup is OPEN with {lb.size()} item(s): {items[:5]}")
            else:
                cached = app._quick_run_index_cache.get(bar["base_dir"])
                if cached is None:
                    print("  index not yet ready (still building in background)")
                else:
                    print(f"  index ready ({len(cached[1])} files), but no suggestions for 'p'")
        app.after(300, app.destroy)

    app.after(900, _do)


def _adhoc_run(app: RYOSApp):
    """Quick Run a script NOT already in the DB; verify no new card appears."""
    import os

    TARGET_GROUP = "TestScripts"
    TARGET_SCRIPT = "uv_hello.py"

    def _do():
        cards_before = len(app._cards)
        print(f"adhoc-run: cards before = {cards_before}")
        _shot(app, "01_before_run")

        bar = app._quick_run_bars.get(TARGET_GROUP)
        if not bar:
            print(f"  no quick-run bar for group {TARGET_GROUP!r} -- quitting")
            app.after(300, app.destroy)
            return

        base_dir = bar["base_dir"]
        script_path = os.path.join(base_dir, TARGET_SCRIPT)
        if not os.path.exists(script_path):
            print(f"  target script not found: {script_path} -- quitting")
            app.after(300, app.destroy)
            return

        print(f"  submitting quick-run for: {TARGET_SCRIPT}")
        bar["var"].set(TARGET_SCRIPT)
        bar["is_placeholder"][0] = False
        app._quick_run_submit(TARGET_GROUP)
        app.after(3000, lambda: _after_run(cards_before))

    def _after_run(cards_before):
        cards_after = len(app._cards)
        print(f"adhoc-run: cards after  = {cards_after}")
        _shot(app, "02_after_run")
        if cards_after == cards_before:
            print("PASS: no new card appeared in the UI")
        else:
            print(f"FAIL: card count changed {cards_before} -> {cards_after} (unexpected card added)")
        app.after(400, app.destroy)

    app.after(900, _do)


def _close_all_verify(app: RYOSApp):
    """Verify the Close All button is visible in the output header and functional."""
    def _do():
        print("close-all-verify: screenshot output header")
        app.lift()
        app.focus_force()
        app.update_idletasks()
        app.update()
        # Screenshot just the output header region
        hdr = app.out_panel
        x, y = hdr.winfo_rootx(), hdr.winfo_rooty()
        w, h = hdr.winfo_width(), hdr.winfo_reqheight()
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(x, y, x + w, y + max(h, 30)))
        path = SHOTS_DIR / "close_all_header.png"
        img.save(str(path))
        print(f"  screenshot -> {path.name}")
        # Check button exists by finding it in out_panel children
        btns = [w for w in app.out_panel.winfo_children()[0].winfo_children()
                if hasattr(w, 'cget') and 'Close All' in str(w.cget('text') if hasattr(w, 'cget') else '')]
        if btns:
            print(f"PASS: found 'Close All' button in output header")
        else:
            print("FAIL: 'Close All' button not found in output header")
        app.after(300, app.destroy)
    app.after(900, _do)


def _debug_run_py(app: RYOSApp):
    """Find a .py card, print the command that would be built, run it, screenshot."""
    import sys as _sys
    from ryos.interpreter import detect_interpreter, build_command, _find_python, resolve_interpreter

    def _do():
        print(f"debug-run-py: sys.executable = {_sys.executable}")
        print(f"debug-run-py: frozen         = {getattr(_sys, 'frozen', False)}")
        print(f"debug-run-py: _find_python() = {_find_python()}")
        _shot(app, "01_launch")

        py_cards = [c for c in app._cards if c._name.lower().endswith(".py")
                    or any(str(app.db.get(c.script_id)[2]).endswith(".py") for _ in [1])]
        # simpler: find any card whose stored path ends in .py
        py_cards = []
        for c in app._cards:
            rec = app.db.get(c.script_id)
            if rec and str(rec[2]).endswith(".py"):
                py_cards.append((c, rec))

        if not py_cards:
            print("  no .py cards found")
            app.after(300, app.destroy)
            return

        card, rec = py_cards[0]
        _, name, path, params, interp, _grp = rec
        final_interp = resolve_interpreter(path, interp)
        cmd = build_command(path, params, final_interp)
        print(f"  card name : {name}")
        print(f"  path      : {path}")
        print(f"  stored interp : {interp!r}")
        print(f"  resolved interp: {final_interp!r}")
        print(f"  full cmd  : {cmd}")
        print(f"  running...")
        card._run()
        app.after(3000, _after_run)

    def _after_run():
        print("debug-run-py: post-run screenshot")
        _shot(app, "02_after_run")
        app.after(500, app.destroy)

    app.after(1000, _do)


def _running_row_check(app: RYOSApp):
    """Run a pipeline (if any) and a script, screenshot the Running section to verify
    stop button and timestamp are visible in both cases."""
    from PIL import ImageGrab

    def _do():
        print("running-row-check: initial screenshot")
        _shot(app, "01_launch")

        # --- Try to run a pipeline ---
        pipeline_cards = app._pipeline_cards
        if pipeline_cards:
            pc = pipeline_cards[0]
            print(f"  found pipeline card: pid={pc.pipeline_id}")
            app._run_pipeline(pc.pipeline_id, pc._name)
            app.after(800, _after_pipeline)
        else:
            print("  no pipeline cards found, skipping pipeline test")
            app.after(0, _run_script)

    def _after_pipeline():
        print("running-row-check: pipeline running screenshot")
        _shot(app, "02_pipeline_running")
        # Stop it so it does not block script run
        for job in list(app._jobs.values()):
            if job.kind == "pipeline":
                app._stop_job(job)
                break
        app.after(400, _run_script)

    def _run_script():
        cards = app._cards
        if not cards:
            print("  no script cards, skipping script test")
            app.after(300, app.destroy)
            return
        card = cards[0]
        print(f"  running script card: {card._name!r}")
        card._run()
        app.after(1200, _after_script)

    def _after_script():
        print("running-row-check: script running screenshot")
        _shot(app, "03_script_running")
        app.after(400, app.destroy)

    app.after(1000, _do)


def _compact_running(app: RYOSApp):
    """Enable compact mode, run a pipeline (if any) and a script, screenshot each state."""
    from PIL import ImageGrab

    def _do():
        print("compact-running: idle compact screenshot")
        _shot(app, "cr_01_idle_compact")

        pipeline_cards = app._pipeline_cards
        if pipeline_cards:
            pc = pipeline_cards[0]
            print(f"  starting pipeline: {pc._name!r}")
            app._run_pipeline(pc.pipeline_id, pc._name)
            app.after(1000, _after_pipeline)
        else:
            print("  no pipeline cards, skipping to script")
            app.after(0, _run_script)

    def _after_pipeline():
        print("compact-running: pipeline running screenshot")
        _shot(app, "cr_02_pipeline_running")
        for job in list(app._jobs.values()):
            if job.kind == "pipeline":
                app._stop_job(job)
                break
        app.after(600, _run_script)

    def _run_script():
        cards = app._cards
        if not cards:
            print("  no script cards, quitting")
            app.after(300, app.destroy)
            return
        card = cards[0]
        print(f"  running script: {card._name!r}")
        card._run()
        app.after(1400, _after_script)

    def _after_script():
        print("compact-running: script running screenshot")
        _shot(app, "cr_03_script_running")
        # also screenshot with both a pipeline and script if possible
        pipeline_cards = app._pipeline_cards
        if pipeline_cards:
            pc = pipeline_cards[0]
            app._run_pipeline(pc.pipeline_id, pc._name)
            app.after(1000, _both_running)
        else:
            app.after(400, app.destroy)

    def _both_running():
        print("compact-running: both running screenshot")
        _shot(app, "cr_04_both_running")
        app.after(400, app.destroy)

    app.after(1000, _do)


def main():
    import ryos.settings as _s
    _s._SETTINGS_DEFAULTS["auto_check_update"] = False

    scenario = sys.argv[1] if len(sys.argv) > 1 else "smoke"

    if scenario == "compact-running":
        _s._SETTINGS_DEFAULTS["compact_mode"] = True

    app = RYOSApp()

    if scenario == "smoke":
        _smoke(app)
    elif scenario == "quick-run-bar":
        _quick_run_bar(app)
    elif scenario == "run-first":
        _run_first(app)
    elif scenario == "autocomplete":
        _quick_run_autocomplete(app)
    elif scenario == "adhoc-run":
        _adhoc_run(app)
    elif scenario == "close-all-verify":
        _close_all_verify(app)
    elif scenario == "debug-run-py":
        _debug_run_py(app)
    elif scenario == "running-row-check":
        _running_row_check(app)
    elif scenario == "compact-running":
        _compact_running(app)
    else:
        print(f"unknown scenario: {scenario!r}. Use: smoke | quick-run-bar | run-first | autocomplete | adhoc-run | close-all-verify | debug-run-py | running-row-check | compact-running")
        app.after(0, app.destroy)

    app.mainloop()
    print("done.")


if __name__ == "__main__":
    main()
