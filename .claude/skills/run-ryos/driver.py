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


def _card_size_verify(app: RYOSApp):
    """Cycle through all card size + compact combinations, screenshot each, then show the Advanced Options dialog (Appearance tab)."""
    from ryos.ui import cards as _cards_mod

    combos = [
        ("normal", "small",  False),
        ("normal", "medium", False),
        ("normal", "large",  False),
        ("compact", "small",  True),
        ("compact", "medium", True),
        ("compact", "large",  True),
    ]
    idx = [0]

    def _next():
        if idx[0] >= len(combos):
            _open_dialog()
            return
        mode_label, size, compact = combos[idx[0]]
        print(f"card-size-verify: {mode_label} + {size}")
        app._settings["compact_mode"] = compact
        app._settings["card_size"] = size
        _cards_mod.set_compact_mode(compact)
        _cards_mod.set_card_size(size)
        app._rebuild_ui()
        app.after(400, lambda: _screenshot_and_advance(mode_label, size))

    def _screenshot_and_advance(mode_label, size):
        _shot(app, f"cs_{mode_label}_{size}")
        idx[0] += 1
        app.after(200, _next)

    def _open_dialog():
        print("card-size-verify: opening Advanced Options dialog")
        app._settings["compact_mode"] = False
        app._settings["card_size"] = "medium"
        _cards_mod.set_compact_mode(False)
        _cards_mod.set_card_size("medium")
        app._rebuild_ui()
        app.after(400, _do_dialog)

    def _do_dialog():
        app._open_advanced_options()
        app.after(600, _screenshot_dialog)

    def _screenshot_dialog():
        from PIL import ImageGrab
        # find the Advanced Options toplevel and screenshot it directly
        dlg = None
        for w in app.winfo_children():
            try:
                if hasattr(w, 'title') and w.title() == "Advanced Options":
                    dlg = w
                    break
            except Exception:
                pass
        if dlg:
            dlg.lift()
            dlg.update_idletasks()
            dlg.update()
            x, y = dlg.winfo_rootx(), dlg.winfo_rooty()
            w2, h2 = dlg.winfo_width(), dlg.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x + w2, y + h2))
            path = SHOTS_DIR / "cs_advanced_options_dialog.png"
            img.save(str(path))
            print(f"  screenshot -> {path.name}")
            dlg.destroy()
        else:
            print("  Advanced Options dialog not found")
        app.after(300, app.destroy)

    app.after(900, _next)


def _advanced_options_tabs(app: RYOSApp):
    """Open Advanced Options and screenshot every tab in sequence."""
    from PIL import ImageGrab

    TAB_NAMES = ["appearance", "startup", "output", "quick_run", "logging"]

    def _get_dlg():
        for w in app.winfo_children():
            try:
                if hasattr(w, "title") and w.title() == "Advanced Options":
                    return w
            except Exception:
                pass
        return None

    def _shot_dlg(dlg, name):
        dlg.attributes("-topmost", True)
        dlg.lift()
        dlg.focus_force()
        dlg.update_idletasks()
        dlg.update()
        dlg.attributes("-topmost", False)
        x, y = dlg.winfo_rootx(), dlg.winfo_rooty()
        w2, h2 = dlg.winfo_width(), dlg.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + w2, y + h2))
        path = SHOTS_DIR / f"adv_{name}.png"
        img.save(str(path))
        print(f"  screenshot -> {path.name}")

    def _do():
        print("advanced-options-tabs: opening dialog")
        app._open_advanced_options()
        app.after(700, lambda: _cycle(0))

    def _cycle(idx):
        if idx >= len(TAB_NAMES):
            dlg = _get_dlg()
            if dlg:
                dlg.destroy()
            app.after(300, app.destroy)
            return
        dlg = _get_dlg()
        if not dlg:
            print("  dialog not found, quitting")
            app.after(300, app.destroy)
            return
        try:
            nb = dlg._nb
            nb.select(idx)
            dlg.update_idletasks()
            dlg.update()
        except Exception as e:
            print(f"  could not select tab {idx}: {e}")
        app.after(300, lambda: _screenshot_and_next(idx))

    def _screenshot_and_next(idx):
        dlg = _get_dlg()
        if dlg:
            _shot_dlg(dlg, TAB_NAMES[idx])
        app.after(150, lambda: _cycle(idx + 1))

    app.after(900, _do)


def _favorites(app: RYOSApp):
    """Mark the first script as a favorite, refresh, screenshot the Favorites section."""
    def _do():
        print("favorites: marking first script as favorite")
        all_scripts = app.db.list_all()
        if not all_scripts:
            print("  no scripts in DB, quitting")
            app.after(300, app.destroy)
            return
        first_id = all_scripts[0][0]
        first_name = all_scripts[0][1]
        print(f"  favoriting script id={first_id} name={first_name!r}")
        app.db.set_favorite_script(first_id, True)
        app._refresh_cards()
        app.after(500, _screenshot)

    def _screenshot():
        print("favorites: taking screenshot")
        _shot(app, "favorites_section")
        app.after(300, app.destroy)

    app.after(900, _do)


def _search_bar(app: RYOSApp):
    """Screenshot the search bar: idle, filtered (one group matches), cleared."""
    def _idle():
        print("search-bar: idle state")
        _shot(app, "search_01_idle")
        app.after(300, _type_query)

    def _type_query():
        print("search-bar: typing 'inf' to filter")
        app._search_ph[0] = False
        from ryos.ui.theme import C as _C
        app._search_entry.config(fg=_C["name_fg"])
        app._search_var.set("inf")
        app.update_idletasks()
        app.update()
        app.after(400, _filtered)

    def _filtered():
        print("search-bar: filtered state")
        _shot(app, "search_02_filtered")
        app.after(300, _clear)

    def _clear():
        print("search-bar: clearing search")
        app._clear_search()
        app.update_idletasks()
        app.update()
        app.after(300, _done)

    def _done():
        print("search-bar: after clear")
        _shot(app, "search_03_cleared")
        app.after(300, app.destroy)

    app.after(900, _idle)


def _search_hint(app: RYOSApp):
    """Switch to Group2, type a query that matches Group1 scripts but not Group2,
    screenshot the 'found in other groups' hint callout."""
    def _do():
        groups = app.db.list_groups()
        if len(groups) < 2:
            print("search-hint: need at least 2 groups, quitting")
            app.after(300, app.destroy)
            return
        # Switch to the second group so the query has no local match
        target_group = groups[1]
        print(f"search-hint: switching to group {target_group!r}")
        app._switch_group(target_group)
        app.update_idletasks()
        app.update()
        app.after(400, _type_query)

    def _type_query():
        print("search-hint: typing 'inf' (matches Group1, not current group)")
        app._search_ph[0] = False
        from ryos.ui.theme import C as _C
        app._search_entry.config(fg=_C["name_fg"])
        app._search_var.set("inf")
        app.update_idletasks()
        app.update()
        app.after(400, _screenshot)

    def _screenshot():
        print("search-hint: screenshotting hint callout")
        _shot(app, "search_hint_callout")
        app.after(300, app.destroy)

    app.after(900, _do)


def _hover_preview(app: RYOSApp):
    """Enable compact mode + hover_preview, force-show/hide the HoverPreview popups
    (script + pipeline) without relying on real OS mouse movement, verify the
    click-popup still works, then verify the setting/compact-mode gating.

    Popup content is verified by walking its widget tree and printing label
    text (not by screen-grabbing it): the popup's on-screen position tracks
    the real OS pointer, which in an automated/headless run can land anywhere
    on the physical desktop, so a pixel capture there risks landing on and
    exposing whatever unrelated window happens to be under the real cursor.
    """
    from ryos.ui import cards as _cards_mod
    from ryos.ui.widgets import HoverPreview as _RealHoverPreview

    captured = {"instances": []}

    class _TrackedHoverPreview(_RealHoverPreview):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured["instances"].append(self)

    _cards_mod.HoverPreview = _TrackedHoverPreview

    def _dump_popup_text(popup, name):
        lines = []

        def _walk(w):
            try:
                if hasattr(w, "cget") and str(w.cget("text")).strip():
                    lines.append(str(w.cget("text")).strip())
            except Exception:
                pass
            for ch in w.winfo_children():
                _walk(ch)

        _walk(popup)
        # PowerShell's console codepage (cp1252) can't encode the ✓/✕ glyphs
        # used in the preview, so print an ASCII-safe form.
        safe = [l.encode("ascii", "replace").decode("ascii") for l in lines]
        print(f"  [{name}] popup text content: {safe}")
        return lines

    def _do():
        print("hover-preview: enabling compact mode + hover_preview")
        app._settings["compact_mode"] = True
        app._settings["hover_preview"] = True
        _cards_mod.set_compact_mode(True)
        _cards_mod.set_hover_preview(True)
        app._rebuild_ui()
        app.after(400, _after_compact)

    def _after_compact():
        _shot(app, "hp_01_compact")
        print(f"  captured {len(captured['instances'])} HoverPreview instances in compact mode")
        if not captured["instances"]:
            print("FAIL: no HoverPreview instances created in compact mode")
            app.after(300, app.destroy)
            return
        hp = captured["instances"][0]
        print(f"  forcing _show() on instance 0 (card type: {type(hp._card).__name__})")
        hp._show()
        app.after(300, lambda: _show_screenshot(hp))

    def _show_screenshot(hp):
        popup_exists = bool(hp._popup) and hp._popup.winfo_exists()
        print(f"  popup exists after _show(): {popup_exists}")
        if popup_exists:
            text = _dump_popup_text(hp._popup, "script preview")
            expect = ["Path", "Working dir", "Interpreter", "Params"]
            missing = [e for e in expect if not any(e in t for t in text)]
            print(f"  {'PASS' if not missing else 'FAIL'}: expected labels present (missing: {missing})")
        print("  forcing _hide()")
        hp._hide()
        app.after(200, lambda: _hide_screenshot(hp))

    def _hide_screenshot(hp):
        popup_gone = hp._popup is None
        print(f"  {'PASS' if popup_gone else 'FAIL'}: popup gone after _hide(): {popup_gone}")
        _shot(app, "hp_03_after_hide")

        pipeline_hps = [h for h in captured["instances"]
                        if type(h._card).__name__ == "PipelineCard"]
        if pipeline_hps:
            app.after(200, lambda: _pipeline_preview(pipeline_hps[0]))
        else:
            print("  no PipelineCard HoverPreview captured (no pipeline cards in DB?)")
            app.after(200, _click_popup_check)

    def _pipeline_preview(phv):
        print("  forcing pipeline HoverPreview _show()")
        phv._show()
        app.after(300, lambda: _pipeline_screenshot(phv))

    def _pipeline_screenshot(phv):
        popup_exists = bool(phv._popup) and phv._popup.winfo_exists()
        print(f"  pipeline popup exists after _show(): {popup_exists}")
        if popup_exists:
            _dump_popup_text(phv._popup, "pipeline preview")
        phv._hide()
        app.after(200, _click_popup_check)

    def _click_popup_check():
        pipeline_cards = app._pipeline_cards
        if not pipeline_cards:
            print("  no pipeline cards, skipping click-popup check")
            app.after(200, _disable_setting)
            return
        pc = pipeline_cards[0]
        print(f"  clicking pipeline card name to open click-popup: {pc._name!r}")
        pc._show_steps_popup()
        app.after(300, lambda: _after_click_popup(pc))

    def _after_click_popup(pc):
        popup = getattr(pc, "_steps_popup", None)
        ok = bool(popup) and popup.winfo_exists()
        print(f"  {'PASS' if ok else 'FAIL'}: click-popup opened: {ok}")
        _shot(app, "hp_05_click_popup")
        if popup:
            try:
                popup.destroy()
            except Exception:
                pass
            pc._steps_popup = None
        app.after(200, _disable_setting)

    def _disable_setting():
        print("hover-preview: disabling hover_preview setting (compact stays on)")
        captured["instances"].clear()
        app._settings["hover_preview"] = False
        _cards_mod.set_hover_preview(False)
        app._rebuild_ui()
        app.after(400, _after_disable)

    def _after_disable():
        n = len(captured["instances"])
        print(f"  {'PASS' if n == 0 else 'FAIL'}: HoverPreview instances with setting off: {n}")
        app.after(200, _restore_noncompact)

    def _restore_noncompact():
        print("hover-preview: turning off compact mode (hover_preview back on)")
        captured["instances"].clear()
        app._settings["compact_mode"] = False
        app._settings["hover_preview"] = True
        _cards_mod.set_compact_mode(False)
        _cards_mod.set_hover_preview(True)
        app._rebuild_ui()
        app.after(400, _after_noncompact)

    def _after_noncompact():
        _shot(app, "hp_06_noncompact")
        n = len(captured["instances"])
        print(f"  {'PASS' if n == 0 else 'FAIL'}: HoverPreview instances in non-compact mode: {n}")
        app.after(300, app.destroy)

    app.after(900, _do)


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
    elif scenario == "card-size-verify":
        _card_size_verify(app)
    elif scenario == "advanced-options-tabs":
        _advanced_options_tabs(app)
    elif scenario == "favorites":
        _favorites(app)
    elif scenario == "search-bar":
        _search_bar(app)
    elif scenario == "search-hint":
        _search_hint(app)
    elif scenario == "hover-preview":
        _hover_preview(app)
    else:
        print(f"unknown scenario: {scenario!r}. Use: smoke | quick-run-bar | run-first | autocomplete | adhoc-run | close-all-verify | debug-run-py | running-row-check | compact-running | advanced-options-tabs")
        app.after(0, app.destroy)

    app.mainloop()
    print("done.")


if __name__ == "__main__":
    main()
