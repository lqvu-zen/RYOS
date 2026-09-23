"""Real-Qt checks for the PySide6 front-end being built alongside the Tk one.

The Tk equivalent is `tests/gui_smoke.py`. This one is separate because
PySide6 is an optional dependency: the app, the unit suite and CI all run
without Qt installed, so this exits 0 with a notice when it is missing rather
than failing.

Run it with:

    uv run --no-project --with PySide6 python tests/qt_smoke.py

Unlike the Tk harness, Qt gives real event synthesis (QTest) and real
rendering, so checks here can assert on what is actually painted.
"""

import sys
from pathlib import Path

# The card glyphs (▶ ↻ ★ ⚙) do not survive a cp1252 console, and a check that
# passes should not die printing its own result.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PySide6.QtWidgets import (QApplication, QLabel, QPlainTextEdit,
                                   QPushButton, QVBoxLayout, QWidget)
except ImportError:
    print("PySide6 not installed — skipping the Qt smoke checks.")
    print("  uv run --no-project --with PySide6 python tests/qt_smoke.py")
    raise SystemExit(0)

from ryos.qtui.stylesheet import (MissingPaletteKeys, missing_keys,  # noqa: E402
                                  stylesheet)
from ryos.themes import (SEEDS, build_palette,  # noqa: E402
                         contrast_ratio, load_presets)

PROBLEMS: list[str] = []


def _all_seeds() -> dict:
    """Every theme the project ships: built-ins, presets and the gallery."""
    import json
    seeds = dict(SEEDS)
    for pid, _label, seed in load_presets():
        seeds[pid] = seed
    gallery = Path(__file__).resolve().parents[1] / "theme-gallery"
    for fp in sorted(gallery.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data.get("seed"), dict):
            seeds.setdefault(fp.stem, data["seed"])
    return seeds


def check_every_theme_generates(seeds):
    """Each shipped theme must satisfy the stylesheet's required keys."""
    for name, seed in sorted(seeds.items()):
        gaps = missing_keys(build_palette(seed))
        if gaps:
            PROBLEMS.append(f"{name}: palette missing {gaps}")
    print(f"  [ok] generate: {len(seeds)} themes, none missing keys")


def check_a_short_palette_is_refused():
    """A gap must raise, not emit CSS with holes in it.

    An unstyled widget inherits Qt's default theme, which on a dark palette
    means dark-on-dark -- easy to miss in a screenshot, unusable in practice.
    """
    try:
        stylesheet({"bg": "#000000"})
    except MissingPaletteKeys:
        print("  [ok] short-palette: refused, as it should be")
        return
    PROBLEMS.append("a palette missing almost every key still produced CSS")


def check_stylesheet_reaches_real_widgets(app, seeds):
    """Apply each theme and read back what the widgets are actually painted.

    Asserts on `bg`, which differs on every shipped theme, and additionally
    requires that the themes do not all paint the same colour. An earlier
    version asserted only on `btn_run_bg` and `out_bg` -- which turn out to be
    identical across all 13 themes, being reference defaults rather than
    seed-derived -- so it would have passed a stylesheet that ignored the
    palette entirely.
    """
    host = QWidget()
    col = QVBoxLayout(host)
    card = QLabel("card")
    card.setObjectName("cardName")
    col.addWidget(card)
    out = QPlainTextEdit()
    out.setObjectName("output")
    col.addWidget(out)
    host.show()

    seen = set()
    for name, seed in sorted(seeds.items()):
        pal = build_palette(seed)
        app.setStyleSheet(stylesheet(pal))
        app.processEvents()
        got = host.palette().window().color().name().lower()
        want = pal["bg"].lower()
        seen.add(got)
        if got != want:
            PROBLEMS.append(f"{name}: window painted {got}, palette says {want}")
        got_out = out.palette().base().color().name().lower()
        if got_out != pal["out_bg"].lower():
            PROBLEMS.append(
                f"{name}: output painted {got_out}, palette says {pal['out_bg']}")
    if len(seen) < 2:
        PROBLEMS.append(
            f"every theme painted the same background ({seen}) — the "
            f"stylesheet is probably ignoring the palette")
    print(f"  [ok] applied: {len(seeds)} themes, {len(seen)} distinct backgrounds")
    host.hide()


def check_disabled_button_differs(app, seeds):
    """The disabled state must be visibly different, on every theme.

    This is issue #7's rule, carried across to Qt: a disabled control that
    looks enabled is the bug, so assert the difference rather than trusting
    the stylesheet to have said it.

    The difference may land in either channel, and which one is theme-dependent.
    On light themes the neutral button already sits nearly flush with the card,
    so there is no room for a flatter slab and the dimmed label carries the
    state -- the same limitation recorded for the Tk build in issue #7. So the
    check requires a visible difference in background *or* text, and reports
    which, rather than demanding one specific channel move.
    """
    host = QWidget()
    col = QVBoxLayout(host)
    on = QPushButton("Go")
    off = QPushButton("Go")
    off.setEnabled(False)
    col.addWidget(on)
    col.addWidget(off)
    host.show()
    by_channel: dict = {}
    for name, seed in sorted(seeds.items()):
        pal = build_palette(seed)
        app.setStyleSheet(stylesheet(pal))
        app.processEvents()
        bg_on = on.palette().button().color().name().lower()
        bg_off = off.palette().button().color().name().lower()
        fg_on = on.palette().buttonText().color().name().lower()
        fg_off = off.palette().buttonText().color().name().lower()
        bg_delta = contrast_ratio(bg_on, bg_off)
        fg_delta = contrast_ratio(fg_on, fg_off)
        carriers = []
        if bg_delta >= 1.05:
            carriers.append("slab")
        if fg_delta >= 1.15:
            carriers.append("label")
        if not carriers:
            PROBLEMS.append(
                f"{name}: disabled is indistinguishable from enabled "
                f"(slab {bg_delta:.2f}:1, label {fg_delta:.2f}:1)")
        by_channel[name] = ("+".join(carriers) or "NOTHING", bg_delta, fg_delta)
    widest = max(len(n) for n in by_channel)
    for name, (carrier, bg_d, fg_d) in sorted(by_channel.items()):
        print(f"       {name:<{widest}}  {carrier:<11} "
              f"slab {bg_d:.2f}:1  label {fg_d:.2f}:1")
    print(f"  [ok] disabled: distinguishable on all {len(seeds)} themes")
    host.hide()


def check_scrolling_label(app):
    """The Qt marquee must run the same arithmetic as the Tk one.

    Both drive `ryos.marquee`, so this checks the wiring rather than the
    maths: a long label scrolls, a short one does not, hovering pauses it, and
    a full pass returns to the start.
    """
    from ryos import marquee
    from ryos.qtui.widgets import ScrollingLabel

    lab = ScrollingLabel("a very long piece of text that will not fit at all")
    lab.resize(80, 22)
    lab.show()
    app.processEvents()

    if not marquee.needs_scroll(lab._text_width, lab.width()):
        PROBLEMS.append("the long label did not consider itself scrollable")
    if not lab._timer.isActive():
        PROBLEMS.append("a scrollable label did not start its timer")

    # Drive a whole pass and confirm it returns to the start exactly once.
    wraps = 0
    for _ in range(marquee.pass_steps(lab._text_width) + 2):
        before = lab._offset
        lab._tick()
        if lab._offset == 0 and before != 0:
            wraps += 1
    if wraps != 1:
        PROBLEMS.append(f"a single pass wrapped {wraps} times, expected 1")

    # Hovering pauses and resets.
    lab._pause()
    if lab._timer.isActive() or lab._offset != 0:
        PROBLEMS.append("hovering did not pause and reset the marquee")

    short = ScrollingLabel("ok")
    short.resize(400, 22)
    short.show()
    app.processEvents()
    if marquee.needs_scroll(short._text_width, short.width()):
        PROBLEMS.append("a label that fits was treated as scrollable")
    if short._timer.isActive():
        PROBLEMS.append("a label that fits started scrolling")

    print("  [ok] marquee: scrolls when it must, rests when it fits, wraps once")
    lab.hide()
    short.hide()


def check_tooltip_is_native(app):
    """Tooltips should be one Qt call, not a reimplementation."""
    from ryos.qtui.widgets import set_tooltip
    w = QLabel("x")
    set_tooltip(w, "hello")
    if w.toolTip() != "hello":
        PROBLEMS.append(f"tooltip did not attach: {w.toolTip()!r}")
    else:
        print("  [ok] tooltip: native, no popup machinery")




def check_cards(app):
    """The Qt cards must hold the rules the Tk cards were fixed into.

    Three shipped issues live here, and porting is exactly when they get
    silently undone:

      #3  script and pipeline cards must present the same button columns, at
          the same widths, or a mixed list is ragged.
      #7  the pipeline card's fourth cell must read as a gap, not as a button
          whose icon failed to load.
      #4  the Run button becomes Retry after a failure.
    """
    from ryos import cardstyle
    from ryos.qtui.cards import BUTTON_WIDTH, PipelineCard, ScriptCard
    from ryos.themes import REFERENCE

    pal = REFERENCE["dark"]
    app.setStyleSheet(stylesheet(pal))

    for compact in (False, True):
        for size in cardstyle.SIZES:
            sc = ScriptCard(script_id=1, name="script.py", path="C:/x/script.py",
                            palette=pal, compact=compact, size=size)
            pc = PipelineCard(pipeline_id=1, name="pipe", step_count=3,
                              palette=pal, compact=compact, size=size)
            for c in (sc, pc):
                c.resize(520, 60)
                c.show()
            app.processEvents()
            tag = f"compact={compact} size={size}"

            # #3: four cells each, same widths.
            s_cells = [sc.fav_button, sc.edit_button, sc.param_button, sc.run_button]
            p_cells = [pc.fav_button, pc.edit_button, pc.spacer, pc.run_button]
            if len(s_cells) != len(p_cells):
                PROBLEMS.append(f"{tag}: card types have different column counts")
            for i, (a, b) in enumerate(zip(s_cells, p_cells)):
                if a.width() != b.width():
                    PROBLEMS.append(
                        f"{tag}: column {i} widths differ — "
                        f"script {a.width()} vs pipeline {b.width()} (#3)")
                if a.width() != BUTTON_WIDTH:
                    PROBLEMS.append(
                        f"{tag}: column {i} is {a.width()}px, not {BUTTON_WIDTH}")

            # #7: the spacer must not be painted like a button.
            spacer_bg = pc.spacer.palette().window().color().name().lower()
            button_bg = pc.edit_button.palette().button().color().name().lower()
            if spacer_bg == button_bg:
                PROBLEMS.append(
                    f"{tag}: the spacer is painted like a button ({spacer_bg}) (#7)")

            # padding follows the shared table
            want = cardstyle.card_padding(compact, size)
            m = sc._row.contentsMargins()
            if (m.left(), m.top()) != want:
                PROBLEMS.append(
                    f"{tag}: padding {(m.left(), m.top())} != {want}")
            for c in (sc, pc):
                c.hide()
                c.deleteLater()

    # #4: Run becomes Retry after a failure, on both card types.
    seen = {}
    for status, want_state in ((None, cardstyle.RUN), ("ok", cardstyle.RUN),
                               ("error", cardstyle.RETRY)):
        sc = ScriptCard(script_id=1, name="s", path="x.py", palette=pal,
                        last_status=status)
        pc = PipelineCard(pipeline_id=1, name="p", step_count=1, palette=pal,
                          last_status=status)
        for kind, card in (("script", sc), ("pipeline", pc)):
            got = card.run_button.property("runState")
            seen[f"{kind}-{status}"] = card.run_button.text()
            if got != want_state:
                PROBLEMS.append(
                    f"{kind} with last_status={status!r}: run button is "
                    f"{got!r}, expected {want_state!r} (#4)")
            card.deleteLater()
    print(f"  [ok] cards: 4 columns aligned, spacer reads as a gap, "
          f"run/retry {seen['script-error']}/{seen['script-ok']}")




def check_options_form(app):
    """The options form is generated from the schema, and round-trips.

    The point of generating it is that no setting can be forgotten: every
    schema field must get a control, every control must read back, and the
    values must come out coerced -- through the same function the Tk dialog
    uses, so the two front-ends cannot disagree about what an empty box means.
    """
    from ryos import settings_schema
    from ryos.qtui.dialogs import OptionsDialog
    from ryos.settings import _SETTINGS_DEFAULTS

    dlg = OptionsDialog(dict(_SETTINGS_DEFAULTS))
    app.processEvents()

    # Every field has a control.
    missing = [f.key for f in settings_schema.FIELDS if f.key not in dlg._rows]
    if missing:
        PROBLEMS.append(f"options form has no control for: {missing}")

    # Every tab with fields is present.
    tab_names = {dlg.tabs.tabText(i) for i in range(dlg.tabs.count())}
    for tab in settings_schema.TABS:
        if settings_schema.fields_for(tab) and tab not in tab_names:
            PROBLEMS.append(f"options form is missing the {tab!r} tab")

    # Defaults round-trip unchanged: opening and saving must be a no-op.
    values = dlg.values()
    for key, want in _SETTINGS_DEFAULTS.items():
        if key not in dlg._rows:
            continue
        if values.get(key) != want:
            PROBLEMS.append(
                f"{key}: opening and saving changed {want!r} to "
                f"{values.get(key)!r}")

    # A spin box must not silently cap a large value at Qt's default of 99.
    row = dlg._rows["max_output_lines"]
    row.set_value(50_000)
    if dlg.values()["max_output_lines"] != 50_000:
        PROBLEMS.append(
            f"max_output_lines capped at {dlg.values()['max_output_lines']}")

    # Out-of-range input is clamped by the schema, not merely by the widget.
    for key, raw, want in (("max_output_lines", 5, 100),
                           ("max_parallel_jobs", -4, 0)):
        if settings_schema.coerce(key, raw) != want:
            PROBLEMS.append(f"{key}: {raw} did not coerce to {want}")

    # The list field survives the comma round trip.
    lst = dlg._rows["quick_run_index_extensions"]
    lst.set_value(".py, .js")
    got = dlg.values()["quick_run_index_extensions"]
    if got != [".py", ".js"]:
        PROBLEMS.append(f"extensions round-tripped as {got!r}")

    print(f"  [ok] options: {len(dlg._rows)} fields across "
          f"{dlg.tabs.count()} tabs, generated and round-tripping")
    dlg.deleteLater()


def check_script_dialog(app):
    """The Qt script dialog must reach the same verdicts as the Tk one."""
    from ryos import scriptform
    from ryos.qtui.dialogs import ScriptDialog

    cases = [
        ({"name": "", "path": "/x/a.py"}, scriptform.REFUSE, "no name"),
        ({"name": "x", "path": ""}, scriptform.REFUSE, "no path"),
        ({"name": "x", "path": "/x/a.py"}, scriptform.OK, "valid"),
        ({"name": "x", "path": "", "interpreter": "python"},
         scriptform.OK, "interpreter only"),
    ]
    for kwargs, want, label in cases:
        dlg = ScriptDialog(path_exists=lambda p: True, **kwargs)
        got = dlg.check().kind
        if got != want:
            PROBLEMS.append(
                f"script dialog ({label}): verdict {got!r}, expected {want!r}")
        dlg.deleteLater()

    # A missing file asks rather than refusing.
    dlg = ScriptDialog(name="x", path="/x/ghost.py",
                       path_exists=lambda p: False)
    if not dlg.check().needs_confirmation:
        PROBLEMS.append("a missing file did not raise a confirmation")
    dlg.deleteLater()
    print("  [ok] script dialog: same verdicts as the Tk form")




def check_pipeline_editor(app):
    """Rows, reordering and the controls that depend on the selection.

    The labels and the move rules are `ryos.pipelinesteps`, shared with the Tk
    editor, so this checks the wiring: that the list shows what the shared
    function says, that a move reorders and reports the new id order, and that
    the buttons disable where the move is impossible.
    """
    from ryos import pipelinesteps
    from ryos.db import FAIL_CONTINUE, FAIL_STOP, TRIGGER_AFTER, WHEN_ALWAYS
    from ryos.qtui.pipeline import PipelineEditorDialog

    def step(sid, name, **kw):
        return (sid, sid, name, "/x.py", "", "", kw.get("override"),
                kw.get("trigger", TRIGGER_AFTER), None, "",
                kw.get("on_failure", FAIL_STOP), kw.get("retries", 0),
                WHEN_ALWAYS, 0)

    steps = [step(10, "first"), step(20, "second", on_failure=FAIL_CONTINUE),
             step(30, "third", retries=2)]
    reordered = []
    dlg = PipelineEditorDialog(1, "P", steps,
                               on_reorder=lambda ids: reordered.append(ids))
    app.processEvents()

    # The list shows exactly what the shared labeller produced.
    shown = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    if shown != pipelinesteps.step_labels(steps):
        PROBLEMS.append("the editor list does not match step_labels()")
    if "!" not in shown[1]:
        PROBLEMS.append(f"a continue-on-failure step lost its mark: {shown[1]!r}")
    if "\u21bb2" not in shown[2]:
        PROBLEMS.append(f"a retrying step lost its mark: {shown[2]!r}")

    # Nothing selected: nothing can move.
    dlg.list.setCurrentRow(-1)
    app.processEvents()
    if dlg.up_button.isEnabled() or dlg.down_button.isEnabled():
        PROBLEMS.append("move buttons are live with nothing selected")

    # First row: cannot move up, and cannot run with a previous step.
    dlg.list.setCurrentRow(0)
    app.processEvents()
    if dlg.up_button.isEnabled():
        PROBLEMS.append("the first step can be moved up")
    if dlg.trigger_button.isEnabled():
        PROBLEMS.append("the first step offers 'with previous', which has no "
                        "step above it to run alongside")

    # Last row: cannot move down.
    dlg.list.setCurrentRow(len(steps) - 1)
    app.processEvents()
    if dlg.down_button.isEnabled():
        PROBLEMS.append("the last step can be moved down")

    # A real move reorders and reports the new id order.
    dlg.list.setCurrentRow(0)
    app.processEvents()
    dlg.move(+1)
    app.processEvents()
    if reordered != [[20, 10, 30]]:
        PROBLEMS.append(f"move reported {reordered}, expected [[20, 10, 30]]")
    now = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    if "second" not in now[0]:
        PROBLEMS.append(f"the list did not follow the move: {now[0]!r}")
    if dlg.list.currentRow() != 1:
        PROBLEMS.append("the moved step lost the selection")

    print(f"  [ok] pipeline editor: {len(steps)} rows, marks kept, "
          f"move reorders and keeps the selection")
    dlg.deleteLater()




def check_shell(app):
    """The window: output routing, the buffer cap, search, and re-theming.

    Routing and trimming are `ryos.outputpanel`, shared with the Tk shell, so
    this checks the wiring — and the one thing the Tk shell cannot do at all:
    re-theme without rebuilding its widget tree.
    """
    from ryos import outputpanel
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE, SEEDS, build_palette

    win = MainWindow(REFERENCE["dark"],
                     settings={"max_output_lines": 10,
                               "auto_scroll_output": True})
    win.resize(700, 560)
    win.show()
    app.processEvents()

    # Cards render into a group tab and search narrows them.
    win.set_cards("G", [
        {"id": 1, "name": "alpha.py", "path": "/x/alpha.py"},
        {"id": 2, "name": "beta.py", "path": "/x/beta.py"},
        {"id": 3, "kind": "pipeline", "name": "nightly", "steps": 2},
    ])
    app.processEvents()
    if win.group_tabs.count() != 1:
        PROBLEMS.append(f"expected one group tab, got {win.group_tabs.count()}")

    win.search_box.setText("alpha")
    app.processEvents()
    visible = [c for c in win._cards if c.isVisible()]
    if len(visible) != 1:
        PROBLEMS.append(f"search for 'alpha' left {len(visible)} cards visible")
    if "1 of 3" not in win.search_hint.text():
        PROBLEMS.append(f"search hint reads {win.search_hint.text()!r}")

    win.search_box.setText("")
    app.processEvents()
    if len([c for c in win._cards if c.isVisible()]) != 3:
        PROBLEMS.append("clearing the search did not restore every card")

    # A job's output reaches its own tab and the mirror, exactly once each.
    win.add_output_tab("job:1", "alpha")
    win.append_output("hello from the job", tab_key="job:1")
    app.processEvents()
    own = win._output_tabs["job:1"].text.toPlainText()
    mirror = win._output_tabs[outputpanel.ALL].text.toPlainText()
    if "hello from the job" not in own:
        PROBLEMS.append("output did not reach the job's own tab")
    if mirror.count("hello from the job") != 1:
        PROBLEMS.append(
            f"the mirror tab has the line {mirror.count('hello from the job')} "
            f"times, expected once")

    # A job whose own tab was closed still reaches the mirror. Closing the
    # tab of a *running* job must not silently discard the rest of its
    # output -- the mirror is the whole point of having an "all" tab. This
    # matches the Tk shell; an earlier version of this check asserted the
    # opposite and was wrong.
    win.append_output("still running", tab_key="job:gone")
    app.processEvents()
    if "still running" not in win._output_tabs[outputpanel.ALL].text.toPlainText():
        PROBLEMS.append("a closed job tab's output vanished instead of "
                        "falling back to the mirror")

    # The buffer cap holds.
    for i in range(40):
        win.append_output(f"line {i}", tab_key="job:1")
    app.processEvents()
    lines = win._output_tabs["job:1"].text.blockCount()
    if lines > 12:      # cap of 10, plus Qt's trailing block slack
        PROBLEMS.append(f"buffer grew to {lines} lines against a cap of 10")

    # The mirror tab cannot be closed; a job tab can.
    before = win.output_tabs.count()
    win._close_output_tab(0)            # index 0 is "all"
    if win.output_tabs.count() != before:
        PROBLEMS.append("the mirror output tab was closeable")
    win._close_output_tab(1)
    if "job:1" in win._output_tabs:
        PROBLEMS.append("closing a job tab left it registered")

    # Re-theming is one call, and actually repaints.
    before_bg = win.palette().window().color().name().lower()
    light = build_palette(SEEDS["light"])
    win.apply_palette(light)
    app.processEvents()
    after_bg = win.palette().window().color().name().lower()
    if after_bg == before_bg:
        PROBLEMS.append("apply_palette did not change the window colour")
    if after_bg != light["bg"].lower():
        PROBLEMS.append(f"re-themed to {after_bg}, expected {light['bg']}")

    print("  [ok] shell: cards + search, output routed once to each tab, "
          "cap held, re-themed without a rebuild")
    win.hide()
    win.deleteLater()




def check_jobs_run(app):
    """Run a real script through the Qt bridge, to completion.

    This is the milestone the port exists for: the same JobController that
    drives the Tk app, driven from Qt. Everything here is real -- a real
    database, a real subprocess, the real queue -- so a passing check means
    the Qt side can run scripts, not that its wiring type-checks.
    """
    import sys as _sys
    import tempfile
    import time as _time

    from ryos.db import ScriptDB
    from ryos.qtui.jobs import JobBridge

    tmp = Path(tempfile.mkdtemp())
    script = tmp / "hello.py"
    script.write_text("print('from the qt bridge')\n", encoding="utf-8")
    failing = tmp / "boom.py"
    failing.write_text("import sys; sys.exit(3)\n", encoding="utf-8")

    db = ScriptDB(tmp / "qt.db")
    db.create_group("G")
    ok_id = db.add("hello", str(script), "", _sys.executable, "G")
    bad_id = db.add("boom", str(failing), "", _sys.executable, "G")

    bridge = JobBridge(db, {"max_parallel_jobs": 4})
    lines: list = []
    finished: list = []
    bridge.output.connect(lambda key, text, tag: lines.append(text))
    bridge.finished.connect(finished.append)
    bridge.start()

    def pump_until(predicate, timeout=25.0):
        end = _time.time() + timeout
        while _time.time() < end and not predicate():
            app.processEvents()
            _time.sleep(0.02)
        return predicate()

    # A successful run reaches completion and its output arrives.
    started = bridge.run_script(ok_id, "hello", str(script), "",
                                _sys.executable)
    if not started:
        PROBLEMS.append("the Qt bridge refused to start a valid script")
    if not pump_until(lambda: len(finished) >= 1):
        PROBLEMS.append("a script run never finished under the Qt bridge")
    body = "".join(lines)
    if "from the qt bridge" not in body:
        PROBLEMS.append(f"the script's output never arrived: {body[:120]!r}")

    # The run is recorded, with its real exit code.
    runs = db.list_runs(script_id=ok_id)
    if not runs:
        PROBLEMS.append("a completed run was not written to history")
    elif runs[0][7] != "ok":
        PROBLEMS.append(f"a successful run recorded status {runs[0][7]!r}")

    # A failing script is recorded as such, not merely as finished.
    finished.clear()
    bridge.run_script(bad_id, "boom", str(failing), "", _sys.executable)
    if not pump_until(lambda: len(finished) >= 1):
        PROBLEMS.append("a failing script never finished")
    bad_runs = db.list_runs(script_id=bad_id)
    if not bad_runs or bad_runs[0][7] != "error":
        PROBLEMS.append(
            f"a failing run recorded {bad_runs[0][7] if bad_runs else None!r}, "
            f"expected 'error'")

    # The cap is enforced through the same planner the Tk app uses.
    refusals: list = []
    bridge._settings["max_parallel_jobs"] = 0
    bridge.registry.add(__import__("ryos.jobs", fromlist=["Job"]).Job(
        99, "script", None, None, "busy", "job:99", "G"))
    bridge._settings["max_parallel_jobs"] = 1
    if bridge.run_script(ok_id, "hello", str(script), "", _sys.executable,
                         on_refusal=refusals.append):
        PROBLEMS.append("the Qt bridge ignored the parallel-job cap")
    if not refusals or refusals[0].title != "Too many jobs":
        PROBLEMS.append(f"cap refusal was {refusals!r}")

    bridge.stop()
    print("  [ok] jobs: ran a real script to completion, recorded ok and "
          "error, honoured the job cap")




def check_running_section(app):
    """A real run appears in the running list and leaves when it finishes.

    Driven through JobBridge rather than by constructing rows, because the
    thing worth checking is the wiring: started adds a row, finished removes
    it, and a job that is stopped still gets removed when it actually dies
    rather than when the button was pressed.
    """
    import sys as _sys
    import tempfile
    import time as _time

    from ryos.db import ScriptDB
    from ryos.qtui.jobs import JobBridge
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    tmp = Path(tempfile.mkdtemp())
    quick = tmp / "quick.py"
    quick.write_text("print('done')\n", encoding="utf-8")
    slow = tmp / "slow.py"
    slow.write_text("import time\nfor _ in range(200): time.sleep(0.1)\n",
                    encoding="utf-8")

    db = ScriptDB(tmp / "run.db")
    db.create_group("G")
    quick_id = db.add("quick", str(quick), "", _sys.executable, "G")
    slow_id = db.add("slow", str(slow), "", _sys.executable, "G")

    win = MainWindow(REFERENCE["dark"], settings={"max_parallel_jobs": 4})
    bridge = JobBridge(db, {"max_parallel_jobs": 4})
    win.attach_jobs(bridge)
    bridge.start()
    win.show()
    app.processEvents()

    def pump_until(predicate, timeout=25.0):
        end = _time.time() + timeout
        while _time.time() < end and not predicate():
            app.processEvents()
            _time.sleep(0.02)
        return predicate()

    if win.running.count != 0:
        PROBLEMS.append("the running section started with rows in it")

    # A run appears...
    bridge.run_script(quick_id, "quick", str(quick), "", _sys.executable)
    if not pump_until(lambda: win.running.count == 1):
        PROBLEMS.append("a started job never appeared in the running section")
    # ...and leaves when it finishes.
    if not pump_until(lambda: win.running.count == 0):
        PROBLEMS.append("a finished job kept its row")

    # Its output tab was opened for it.
    if len(win._output_tabs) < 2:
        PROBLEMS.append("a started job did not get its own output tab")

    # Stopping: the row goes when the job actually dies, not on the click.
    bridge.run_script(slow_id, "slow", str(slow), "", _sys.executable)
    if not pump_until(lambda: win.running.count == 1):
        PROBLEMS.append("the long-running job never appeared")
    else:
        row = next(iter(win.running._rows.values()))
        label_before = row.time_label.text()
        row.stop_button.click()
        if not pump_until(lambda: win.running.count == 0):
            PROBLEMS.append("stopping a job did not clear its row")
        if not label_before:
            PROBLEMS.append("the elapsed label was empty")

    bridge.stop()
    print("  [ok] running: a real job appears, ticks, and leaves on finish; "
          "stop clears it")
    win.hide()
    win.deleteLater()




def check_small_dialogs(app):
    """The seven remaining dialogs, success and refusal paths, on a real DB.

    Each keeps its Tk counterpart's result contract (None means cancelled),
    so the shell can swap one for the other. Driven through the methods their
    OK buttons call rather than exec(), which would block on a click; the
    message boxes are stubbed for the same reason, and counted, so a refusal
    that should warn is seen to warn.
    """
    import datetime as _dt
    import json as _json
    import tempfile

    from PySide6.QtWidgets import QMessageBox

    from ryos.db import RUN_SCRIPT, ScriptDB
    from ryos.qtui import smalldialogs as sd
    from ryos.scheduling import INTERVAL, WEEKLY

    warnings: list = []
    real_warning, real_question = QMessageBox.warning, QMessageBox.question
    QMessageBox.warning = staticmethod(
        lambda parent, title, text, *a, **k: warnings.append(title))
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        # -- NewGroupDialog --------------------------------------------------
        dlg = sd.NewGroupDialog(existing=["Build"])
        dlg.e_name.setText("   ")
        if dlg.accept_form() or not warnings:
            PROBLEMS.append("a blank group name was accepted without a warning")
        warnings.clear()
        dlg.e_name.setText("Build")
        if dlg.accept_form():
            PROBLEMS.append("a duplicate group name was accepted")
        dlg.e_name.setText("  Deploy  ")
        dlg.e_dir.setText(" C:/work ")
        if not dlg.accept_form() or dlg.result != ("Deploy", "C:/work"):
            PROBLEMS.append(f"new group result was {dlg.result!r}")
        dlg.deleteLater()

        # -- GroupBaseDirDialog: three distinct outcomes ------------------------
        dlg = sd.GroupBaseDirDialog(group_name="G", current_dir="C:/old")
        if dlg.result is not None:
            PROBLEMS.append("an untouched base-dir dialog was not 'cancelled'")
        dlg.e_dir.setText("C:/new")
        dlg.accept_form()
        if dlg.result != "C:/new":
            PROBLEMS.append(f"base dir set to {dlg.result!r}")
        dlg2 = sd.GroupBaseDirDialog(group_name="G", current_dir="C:/old")
        dlg2.clear()
        if dlg2.result != "":
            PROBLEMS.append("Clear did not produce the empty-string result")
        dlg.deleteLater()
        dlg2.deleteLater()

        # -- ParamPickerDialog ---------------------------------------------------
        dlg = sd.ParamPickerDialog(script_name="build", default_params="--all",
                                   presets=[(1, "Fast", "--fast"),
                                            (2, "--dry", "--dry")])
        labels = [r.text() for r in dlg.radios]
        if labels != ["Default", "Fast", "--dry"]:
            PROBLEMS.append(f"picker labels were {labels}")
        dlg.accept_form()
        if dlg.result != "--all":
            PROBLEMS.append(f"default choice gave {dlg.result!r}")
        dlg = sd.ParamPickerDialog(script_name="build", default_params="--all",
                                   presets=[(1, "Fast", "--fast")])
        dlg.select(1)
        dlg.accept_form()
        if dlg.result != "--fast":
            PROBLEMS.append(f"preset choice gave {dlg.result!r}")
        dlg.deleteLater()

        # -- PresetEntryDialog / TempParamDialog ---------------------------------
        dlg = sd.PresetEntryDialog(params="")
        warnings.clear()
        if dlg.accept_form() or not warnings:
            PROBLEMS.append("an empty preset was accepted without a warning")
        dlg.e_params.setText(" -v ")
        if not dlg.accept_form() or dlg.result != "-v":
            PROBLEMS.append(f"preset result {dlg.result!r}")
        tmp_dlg = sd.TempParamDialog(saved_params="--x")
        tmp_dlg.e_params.setText("")
        if not tmp_dlg.accept_form() or tmp_dlg.result != "":
            PROBLEMS.append("empty one-off parameters were refused; they mean "
                            "'none' and must be allowed")
        dlg.deleteLater()
        tmp_dlg.deleteLater()

        # -- CloseToTrayPromptDialog ----------------------------------------------
        dlg = sd.CloseToTrayPromptDialog()
        dlg.remember.setChecked(True)
        dlg.choose(sd.TRAY)
        if (dlg.result, dlg.dont_ask) != (sd.TRAY, True):
            PROBLEMS.append(f"tray choice gave {(dlg.result, dlg.dont_ask)}")
        dlg = sd.CloseToTrayPromptDialog()
        dlg.remember.setChecked(True)
        dlg.reject()
        if (dlg.result, dlg.dont_ask) != (sd.CANCEL, False):
            PROBLEMS.append("dismissing the tray prompt was not a plain cancel "
                            f"({dlg.result!r}, dont_ask={dlg.dont_ask})")
        dlg.deleteLater()

        # -- RunHistoryDialog on a real database ------------------------------------
        tmp = Path(tempfile.mkdtemp())
        db = ScriptDB(tmp / "dlg.db")
        db.create_group("G")
        a = db.add("a", "/a.py", "", "", "G")
        b = db.add("b", "/b.py", "", "", "G")
        now = _dt.datetime.now()
        for status in ("ok", "error", "ok"):
            db.record_run(RUN_SCRIPT, name="a", script_id=a, started_at=now,
                          finished_at=now, status=status, exit_code=0)
        db.record_run(RUN_SCRIPT, name="b", script_id=b, started_at=now,
                      finished_at=now, status="ok", exit_code=0)
        hist = sd.RunHistoryDialog(db=db, script_id=a, title="a")
        shown = hist.table.toPlainText().splitlines()
        if len(shown) != 4:                        # header + 3 rows
            PROBLEMS.append(f"history showed {len(shown)} lines, expected 4")
        if not hist.summary.text():
            PROBLEMS.append("history summary was empty")
        removed = hist.clear()
        if removed != 3 or db.list_runs(script_id=b) == []:
            PROBLEMS.append(f"clearing a's history removed {removed} rows "
                            f"or touched b's")
        if hist.clear_button.isEnabled():
            PROBLEMS.append("Clear stayed enabled with nothing left to clear")
        nobody = sd.RunHistoryDialog(db=db)
        if nobody.clear() != 0 or not db.list_runs(script_id=b):
            PROBLEMS.append("a history dialog for no item cleared everything")
        hist.deleteLater()
        nobody.deleteLater()

        # -- ScheduleDialog: create, reload, refuse, remove -------------------------
        asked: list = []
        sched = sd.ScheduleDialog(db=db, script_id=a, title="a",
                                  ask_login=lambda: asked.append(1) or False)
        if sched.current_mode() != INTERVAL or sched.minutes.value() != 30:
            PROBLEMS.append("a new schedule did not start at every 30 minutes")
        sched.mode.setCurrentIndex(sched.mode.findData(WEEKLY))
        sched.at.setText("07:45")
        for i, box in enumerate(sched.day_boxes):
            box.setChecked(i in (1, 4))
        sched.enabled.setChecked(True)
        sched.catch_up.setCurrentIndex(sched.catch_up.findData("skip"))
        if not sched.preview.text() or "check" in sched.preview.text():
            PROBLEMS.append(f"a valid spec showed no preview: "
                            f"{sched.preview.text()!r}")
        if not sched.accept_form():
            PROBLEMS.append("a valid weekly schedule was refused")
        row = db.get_schedule(script_id=a)
        if row is None:
            PROBLEMS.append("saving did not write a schedule")
        else:
            spec = _json.loads(row[5])
            if (row[4], spec.get("days"), spec.get("at"), row[7], bool(row[6])) \
                    != (WEEKLY, [1, 4], "07:45", "skip", True):
                PROBLEMS.append(f"saved schedule was {row!r}")
        # Reopening shows exactly what was saved.
        again = sd.ScheduleDialog(db=db, script_id=a, ask_login=lambda: False)
        got = (again.current_mode(), again.at.text(),
               [i for i, bx in enumerate(again.day_boxes) if bx.isChecked()],
               again.catch_up.currentData(), again.enabled.isChecked())
        if got != (WEEKLY, "07:45", [1, 4], "skip", True):
            PROBLEMS.append(f"reopened schedule loaded as {got}")
        # A weekly schedule with no days is refused.
        for bx in again.day_boxes:
            bx.setChecked(False)
        warnings.clear()
        if again.accept_form() or "Check the schedule" not in warnings:
            PROBLEMS.append("a weekly schedule with no days was not refused")
        again.remove()
        if db.get_schedule(script_id=a) is not None:
            PROBLEMS.append("Remove schedule left the schedule in place")
        sched.deleteLater()
        again.deleteLater()

        # -- the run-at-login offer rule ---------------------------------------------
        probe = sd.ScheduleDialog(db=db, script_id=b, ask_login=lambda: False)
        switched: list = []
        if probe.offer_run_at_login(ask=lambda: True, platform="linux",
                                    enable=switched.append):
            PROBLEMS.append("run-at-login was offered off Windows")
        if probe.offer_run_at_login(ask=lambda: True, platform="win32",
                                    startup_enabled=True,
                                    enable=switched.append):
            PROBLEMS.append("run-at-login was offered when already on")
        if not probe.offer_run_at_login(ask=lambda: True, platform="win32",
                                        startup_enabled=False,
                                        enable=switched.append) \
                or switched != [True]:
            PROBLEMS.append("accepting the offer did not switch startup on")
        if probe.offer_run_at_login(ask=lambda: False, platform="win32",
                                    startup_enabled=False,
                                    enable=switched.append) \
                or switched != [True]:
            PROBLEMS.append("declining the offer still switched startup on")
        probe.deleteLater()
    finally:
        QMessageBox.warning, QMessageBox.question = real_warning, real_question

    print("  [ok] small dialogs: 7 ported; groups, params, tray prompt, "
          "history and schedules on a real DB, refusals warn")




def check_quick_run(app):
    """The Qt Quick Run bar, end to end, with the real background index.

    The Tk harness could never check the index's worker-thread hand-off: its
    after(0, ...) raises when no mainloop is running, so check_quick_run_bar
    in gui_smoke.py primes the index by hand. Here the index is built on its
    real worker thread and the result has to arrive on the UI thread through
    MainThreadInvoker -- which is the part most likely to be silently broken,
    since the obvious QTimer.singleShot would simply never fire.
    """
    import tempfile
    import time as _time

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from ryos import quickrun as qr
    from ryos.db import ScriptDB
    from ryos.qtui.jobs import JobBridge
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    tmp = Path(tempfile.mkdtemp())
    for name in ("alpha_tool.py", "alpine.py", "beta_tool.py"):
        (tmp / name).write_text("print('qr ran')\n", encoding="utf-8")
    (tmp / "sub").mkdir()
    (tmp / "sub" / "alpha_tool.py").write_text("print(2)\n", encoding="utf-8")

    db = ScriptDB(tmp / "qr.db")
    db.create_group("G", base_dir=str(tmp))
    win = MainWindow(REFERENCE["dark"],
                     settings={"quick_run_enabled": True,
                               "quick_run_autocomplete": True,
                               "quick_run_max_suggestions": 10,
                               "quick_run_index_extensions": [],
                               "max_parallel_jobs": 4})
    bridge = JobBridge(db, {"max_parallel_jobs": 4})
    win.attach_jobs(bridge)
    bridge.start()
    win.set_cards("G", [], base_dir=str(tmp))
    win.show()
    app.processEvents()

    def pump_until(predicate, timeout=20.0):
        end = _time.time() + timeout
        while _time.time() < end and not predicate():
            app.processEvents()
            _time.sleep(0.02)
        return predicate()

    def key(k):
        app.sendEvent(bar.entry, QKeyEvent(QEvent.Type.KeyPress, k,
                                           Qt.KeyboardModifier.NoModifier))
        app.processEvents()

    bar = win.quick_run_bars.get("G")
    if bar is None:
        PROBLEMS.append("a group with a base folder got no Quick Run bar")
        return
    bar.open()

    # The real worker thread builds the index; its result must come back.
    if not pump_until(lambda: win._qr_index.cached(str(tmp)) is not None):
        PROBLEMS.append("the background index never reached the UI thread -- "
                        "the cross-thread hand-off is broken")
        return

    # Typing shows ranked suggestions, top one pre-selected.
    bar.entry.setText("alp")
    bar.refresh()
    shown = [bar.suggestions.item(i).text()
             for i in range(bar.suggestions.count())]
    if not shown or not any("alpha_tool" in s for s in shown):
        PROBLEMS.append(f"'alp' suggested {shown}")
    if bar.suggestions.currentRow() != 0:
        PROBLEMS.append("the best match was not pre-selected")

    # Typing parameters hides the list.
    bar.entry.setText("alpine.py --x")
    bar.refresh()
    if bar.suggestions_open:
        PROBLEMS.append("suggestions stayed open while typing parameters")

    # Down/Up clamp at the ends rather than wrapping.
    bar.entry.setText("alp")
    bar.refresh()
    last = bar.suggestions.count() - 1
    for _ in range(last + 3):
        key(Qt.Key.Key_Down)
    if bar.suggestions.currentRow() != last:
        PROBLEMS.append("Down wrapped past the last suggestion")
    for _ in range(last + 3):
        key(Qt.Key.Key_Up)
    if bar.suggestions.currentRow() != 0:
        PROBLEMS.append("Up wrapped past the first suggestion")

    # Tab completes and leaves room for parameters; focus stays in the box.
    key(Qt.Key.Key_Tab)
    if not bar.entry.text().endswith(" ") or bar.suggestions_open:
        PROBLEMS.append(f"Tab left {bar.entry.text()!r}, list open="
                        f"{bar.suggestions_open}")

    # Escape closes one layer per press: the list, then the bar.
    bar.entry.setText("alp")
    bar.refresh()
    key(Qt.Key.Key_Escape)
    if bar.suggestions_open or not bar.isVisible():
        PROBLEMS.append("first Escape did not close only the list")
    key(Qt.Key.Key_Escape)
    if bar.isVisible():
        PROBLEMS.append("second Escape did not close the bar")

    # The placeholder shown while indexing is never accepted.
    bar.open()
    bar.show_suggestions([qr.INDEXING])
    if bar.suggestions.currentRow() != -1:
        PROBLEMS.append("the 'indexing' placeholder was pre-selected")
    before = bar.entry.text()
    bar.accept_suggestion(qr.INDEXING, submit=True)
    if bar.entry.text() != before:
        PROBLEMS.append("the 'indexing' placeholder was accepted")

    # Several matches ask; declining runs nothing.
    finished: list = []
    bridge.finished.connect(finished.append)
    asked: list = []
    started = win.quick_run_submit("G", str(tmp), "alpha_tool",
                                   choose=lambda c: asked.append(c) or None)
    if not asked or started:
        PROBLEMS.append("an ambiguous name did not ask which, or ran anyway")

    # A miss says why and runs nothing.
    errors: list = []
    if win.quick_run_submit("G", str(tmp), "nothing_like_it",
                            on_error=errors.append) or not errors:
        PROBLEMS.append("an unknown script neither refused nor said why")

    # One match registers the script and runs it, with typed parameters.
    before = len(db.list_all())
    if not win.quick_run_submit("G", str(tmp), "beta_tool.py --fast"):
        PROBLEMS.append("a unique match did not start")
    elif not pump_until(lambda: len(finished) >= 1):
        PROBLEMS.append("the Quick Run job never finished")
    made = [r for r in db.list_all() if r[1] == "beta_tool"]
    if len(db.list_all()) != before + 1 or not made:
        PROBLEMS.append("submitting did not register the script")
    elif made[0][3] != "--fast":
        PROBLEMS.append(f"typed parameters were saved as {made[0][3]!r}")

    # Running it again reuses the record instead of adding a second.
    finished.clear()
    win.quick_run_submit("G", str(tmp), "beta_tool.py")
    pump_until(lambda: len(finished) >= 1)
    if len([r for r in db.list_all() if r[1] == "beta_tool"]) != 1:
        PROBLEMS.append("running the same script twice registered it twice")

    bridge.stop()
    print(f"  [ok] quick run: real index thread, {len(shown)} suggestions, "
          f"keys clamp, Esc one layer, ambiguity asks, reuse not duplicate")
    win.hide()
    win.deleteLater()


def main() -> int:
    print("RYOS Qt smoke starting...")
    app = QApplication(sys.argv)
    seeds = _all_seeds()
    check_every_theme_generates(seeds)
    check_a_short_palette_is_refused()
    check_stylesheet_reaches_real_widgets(app, seeds)
    check_disabled_button_differs(app, seeds)
    check_scrolling_label(app)
    check_tooltip_is_native(app)
    check_cards(app)
    check_options_form(app)
    check_script_dialog(app)
    check_pipeline_editor(app)
    check_shell(app)
    check_jobs_run(app)
    check_running_section(app)
    check_small_dialogs(app)
    check_quick_run(app)
    print()
    if PROBLEMS:
        for p in PROBLEMS:
            print("  PROBLEM:", p)
        return 1
    print("RYOS Qt smoke PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
