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
    app.update_idletasks()
    app.update()
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


def main():
    import ryos.settings as _s
    _s._SETTINGS_DEFAULTS["auto_check_update"] = False

    scenario = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    app = RYOSApp()

    if scenario == "smoke":
        _smoke(app)
    elif scenario == "quick-run-bar":
        _quick_run_bar(app)
    elif scenario == "run-first":
        _run_first(app)
    else:
        print(f"unknown scenario: {scenario!r}. Use: smoke | quick-run-bar | run-first")
        app.after(0, app.destroy)

    app.mainloop()
    print("done.")


if __name__ == "__main__":
    main()
