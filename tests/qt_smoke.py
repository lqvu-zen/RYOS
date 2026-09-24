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
    """Add a script from the shell, edit it back, delete it -- on a real database.

    Starts with no groups, so Add Script has to ask for one first, as Tk does.
    Every field is read back from the database, and reopening checks the load
    path. The verdicts are `scriptform.validate`, shared with Tk.
    """
    import json
    import sys as _sys
    import tempfile

    from ryos import scriptform
    from ryos.db import ScriptDB
    from ryos.qtui.scriptdialog import ScriptDialog
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    tmp = Path(tempfile.mkdtemp())
    base = tmp / "base"
    (base / "sub").mkdir(parents=True)
    tool = base / "sub" / "tool.py"
    tool.write_text("print(1)\n", encoding="utf-8")
    outside = tmp / "outside.py"
    outside.write_text("print(2)\n", encoding="utf-8")
    db = ScriptDB(tmp / "scripts.db")

    win = MainWindow(REFERENCE["dark"], settings={"quick_run_enabled": False})
    win.load_from_db(db)
    opened: list = []
    win.run_dialog = opened.append
    win.ask_text = lambda title, prompt, initial: "First"

    def settle():
        for _ in range(3):
            app.processEvents()

    # -- no groups yet: Add Script asks for one, then opens in it --------------------
    win.add_script_button.click()
    settle()
    if db.list_groups() != ["First"] or len(opened) != 1:
        PROBLEMS.append(f"Add Script with no groups: groups {db.list_groups()}, "
                        f"{len(opened)} dialog(s)")
    elif opened[0].e_group.currentText() != "First":
        PROBLEMS.append("the new script did not default to the group on screen")
    db.create_group("Based", base_dir=str(base))

    # -- fill in every field ------------------------------------------------------------
    dlg = ScriptDialog(db=db, default_group="Based")
    warned: list = []
    dlg.warn = lambda title, text: warned.append(title)
    dlg.ask_yes_no = lambda title, text: True
    if not dlg.rel_row.isVisibleTo(dlg) or dlg.abs_row.isVisibleTo(dlg):
        PROBLEMS.append("a group with a base folder did not show the relative box")
    dlg.ask_file = lambda start: str(outside)
    dlg.browse()
    if warned != ["Path outside group directory"] or dlg.e_relpath.text():
        PROBLEMS.append("browsing outside the base folder was not refused")
    dlg.ask_file = lambda start: str(tool)
    dlg.browse()
    if dlg.e_relpath.text() != str(Path("sub") / "tool.py") or dlg.e_name.text() != "tool":
        PROBLEMS.append(f"browse under the base gave {dlg.e_relpath.text()!r}, "
                        f"name {dlg.e_name.text()!r}")
    dlg.e_params.setText("--fast")
    dlg.add_preset()
    dlg.add_preset()                                       # the same one again
    dlg.e_params.setText("--slow")
    dlg.add_preset()
    if dlg.preset_params() != ["--fast", "--slow"]:
        PROBLEMS.append(f"presets {dlg.preset_params()}")
    dlg.presets.setCurrentRow(0)
    dlg.use_preset()
    if dlg.e_params.text() != "--fast":
        PROBLEMS.append("Use did not copy the preset into Parameters")
    dlg.e_interp.setCurrentText(_sys.executable)
    dlg.temp_param.setChecked(True)
    dlg.launcher.setChecked(True)
    dlg.ask_dir = lambda start: str(tmp)
    dlg.browse_workdir()
    dlg.t_env.setPlainText("A=1\n# a comment\nB=x=y\n")
    if not dlg.save():
        PROBLEMS.append(f"a complete form did not save: {warned}")
    sid = dlg.script_id
    rec = db.get(sid)
    if rec is None:
        PROBLEMS.append("nothing was stored")
        return
    if (rec[1], rec[2], rec[3], rec[5], rec[6]) != (
            "tool", str(tool), "--fast", "Based", 1):
        PROBLEMS.append(f"stored {rec[:7]}")
    if json.loads(rec[7]) != {"A": "1", "B": "x=y"} or rec[8] != str(tmp):
        PROBLEMS.append(f"env/work dir stored as {rec[7]!r}, {rec[8]!r}")
    if not db.is_detached(sid):
        PROBLEMS.append("the launcher box was not stored")
    if [p[2] for p in db.list_param_presets(sid)] != ["--fast", "--slow"]:
        PROBLEMS.append("presets were not stored")

    # -- the card's gear reopens it with everything loaded ----------------------------
    win.reload()
    settle()
    opened.clear()
    card = next(c for c in win.card_lists["Based"].cards
                if c.drag_payload.item_id == sid)
    card.edit_button.click()
    if len(opened) != 1 or opened[0].script_id != sid:
        PROBLEMS.append("the script card's gear did not open its dialog")
        return
    dlg = opened[0]
    if dlg.form() != scriptform.load_form(db, sid):
        PROBLEMS.append(f"reopening lost something: {dlg.form()} vs "
                        f"{scriptform.load_form(db, sid)}")
    if dlg.e_relpath.text() != str(Path("sub") / "tool.py") or dlg.delete_button is None:
        PROBLEMS.append("editing showed the wrong path, or no Delete")

    # Moving to a group without a folder shows the full path, not the relative one.
    dlg.e_group.setCurrentText("First")
    if dlg.e_path.text() != str(tool) or not dlg.abs_row.isVisibleTo(dlg):
        PROBLEMS.append(f"switching group showed {dlg.e_path.text()!r}")
    dlg.e_group.setCurrentText("Based")

    # Presets change nothing until Save -- unlike Tk, Cancel means cancel.
    dlg.e_params.setText("--extra")
    dlg.add_preset()
    dlg.reject()
    if [p[2] for p in db.list_param_presets(sid)] != ["--fast", "--slow"] \
            or db.get(sid)[3] != "--fast":
        PROBLEMS.append("Cancel still wrote the new preset or parameters")

    # Clearing the environment really clears it (save_form passes "", which
    # means "clear"; None would mean "leave it alone" and keep A and B).
    dlg = ScriptDialog(db=db, script_id=sid)
    dlg.t_env.setPlainText("")
    dlg.save()
    if db.get(sid)[7] or scriptform.load_form(db, sid).env_text:
        PROBLEMS.append(f"clearing the environment left {db.get(sid)[7]!r}")

    # -- verdicts: refuse, and ask about a missing file ---------------------------------
    dlg = ScriptDialog(db=db, default_group="First", path_exists=lambda p: False)
    warned.clear()
    dlg.warn = lambda title, text: warned.append(title)
    asked: list = []
    dlg.ask_yes_no = lambda title, text: asked.append(title) or False
    if dlg.save() or warned != ["Missing Info"]:
        PROBLEMS.append("an empty form was not refused")
    dlg.e_name.setText("ghost")
    dlg.e_path.setText(str(tmp / "ghost.py"))
    before = len(db.list_all())
    if dlg.save() or asked != ["Warning"] or len(db.list_all()) != before:
        PROBLEMS.append("declining 'file not found' still saved")

    # -- load order: a based group listed first must not swallow the path ----------
    # The group box selects its first entry before the form loads. That is safe
    # only while the box is filled before its change signal is connected; if
    # that order flips, a based first group would put the dialog in relative
    # mode and the stored absolute path would be lost.
    plain = db.add("plain", str(outside), "", _sys.executable, "First")
    db.reorder_groups(["Based", "First"])
    dlg = ScriptDialog(db=db, script_id=plain)
    if dlg.current_path() != str(outside) or dlg.e_path.text() != str(outside):
        PROBLEMS.append(f"loading a script lost its path: {dlg.current_path()!r}")

    # -- delete asks first ------------------------------------------------------------
    dlg = ScriptDialog(db=db, script_id=sid)
    dlg.ask_yes_no = lambda title, text: False
    dlg.delete()
    if db.get(sid) is None:
        PROBLEMS.append("declining Delete still deleted")
    dlg.ask_yes_no = lambda title, text: True
    dlg.delete()
    if db.get(sid) is not None:
        PROBLEMS.append("confirming Delete did not delete")

    print("  [ok] script dialog: first group, relative path under a base, "
          "browse refusal, presets, launcher/work dir/env stored, gear reloads, "
          "Cancel writes nothing, verdicts, delete")
    win.deleteLater()


def check_pipeline_editor(app):
    """Every editor control, against a real database.

    Each control writes as it changes, as in the Tk editor, so every check
    reads the result back from the database rather than from the widget.
    """
    import sys as _sys
    import tempfile

    from ryos import pipelinesteps
    from ryos.db import (FAIL_CONTINUE, TRIGGER_AFTER, TRIGGER_WITH,
                         WHEN_ON_FAILURE, ScriptDB)
    from ryos.qtui.pipeline import PipelineEditorDialog

    tmp = Path(tempfile.mkdtemp())
    db = ScriptDB(tmp / "editor.db")
    db.create_group("G")
    a = db.add("first", str(tmp / "a.py"), "", _sys.executable, "G")
    b = db.add("second", str(tmp / "b.py"), "", _sys.executable, "G")
    c = db.add("build", str(tmp / "one" / "build.py"), "", _sys.executable, "G")
    d = db.add("build", str(tmp / "two" / "make.py"), "", _sys.executable, "G")
    db.add("elsewhere", str(tmp / "x.py"), "", _sys.executable, "H")
    db.replace_param_presets(b, [("fast", "--fast"), ("slow", "--slow")])
    pid = db.create_pipeline("P", "G")
    for sid in (a, b, c):
        db.add_pipeline_step(pid, sid)

    saved: list = []
    dlg = PipelineEditorDialog(db=db, pipeline_id=pid, name="P", group="G",
                               on_save=lambda: saved.append(True))
    warned: list = []
    dlg.warn = lambda title, text: warned.append(title)
    app.processEvents()

    def steps():
        return db.list_pipeline_steps(pid)

    def shown():
        return [dlg.list.item(i).text() for i in range(dlg.list.count())]

    # -- what it shows -----------------------------------------------------------
    if shown() != pipelinesteps.step_labels(steps()):
        PROBLEMS.append("the editor list does not match step_labels()")
    adds = [dlg.add_combo.itemText(i) for i in range(dlg.add_combo.count())]
    if "elsewhere" in adds or not any("(build.py)" in x for x in adds) \
            or not any("(make.py)" in x for x in adds):
        PROBLEMS.append(f"Add Step offered {adds}")
    dlg.list.setCurrentRow(-1)
    app.processEvents()
    if any(w.isEnabled() for w in (dlg.up_button, dlg.down_button,
                                   dlg.remove_button, dlg.on_failure)):
        PROBLEMS.append("step controls are live with nothing selected")
    dlg.list.setCurrentRow(0)
    if dlg.up_button.isEnabled() or dlg.trigger_button.isEnabled():
        PROBLEMS.append("step 1 can move up, or run with a previous step")

    # -- moves and the trigger toggle --------------------------------------------
    dlg.down_button.click()
    if [s[1] for s in steps()] != [b, a, c] or dlg.selected_index() != 1:
        PROBLEMS.append(f"Down stored {[s[1] for s in steps()]}")
    dlg.trigger_button.click()
    if steps()[1][7] != TRIGGER_WITH or not shown()[1].startswith("∥"):
        PROBLEMS.append("With Prev was not stored, or not shown")
    if dlg.trigger_button.text() != "→ After Prev":
        PROBLEMS.append(f"the toggle then read {dlg.trigger_button.text()!r}")
    dlg.trigger_button.click()
    if steps()[1][7] != TRIGGER_AFTER:
        PROBLEMS.append("toggling back did not store 'after'")

    # -- policy: the combos load the step and write it back ------------------------
    dlg.on_failure.setCurrentText(pipelinesteps.FAIL_LABELS[FAIL_CONTINUE])
    dlg.retries.setCurrentText("3")
    dlg.run_when.setCurrentText(pipelinesteps.WHEN_LABELS[WHEN_ON_FAILURE])
    if pipelinesteps.policy_of(steps()[1]) != (FAIL_CONTINUE, 3, WHEN_ON_FAILURE):
        PROBLEMS.append(f"policy stored {pipelinesteps.policy_of(steps()[1])}")
    if "!" not in shown()[1] or "↻3" not in shown()[1]:
        PROBLEMS.append(f"the row lost its marks: {shown()[1]!r}")
    dlg.list.setCurrentRow(0)
    if dlg.retries.currentText() != "0":
        PROBLEMS.append("selecting another step kept the last step's retries")
    dlg.list.setCurrentRow(1)
    if dlg.retries.currentText() != "3":
        PROBLEMS.append("reselecting a step did not show its stored retries")

    # -- per-step preset: offered only where the script has presets -----------------
    dlg.list.setCurrentRow(0)                        # "second", which has presets
    choices = [dlg.preset.itemText(i) for i in range(dlg.preset.count())]
    if choices != [pipelinesteps.DEFAULT_PRESET, "--fast", "--slow"]:
        PROBLEMS.append(f"preset choices {choices}")
    dlg.preset.setCurrentText("--slow")
    if steps()[0][6] != "--slow" or "[--slow]" not in shown()[0]:
        PROBLEMS.append("choosing a step preset was not stored, or not shown")
    dlg.preset.setCurrentText(pipelinesteps.DEFAULT_PRESET)
    if steps()[0][6] is not None:
        PROBLEMS.append("choosing the script default did not clear the override")
    dlg.list.setCurrentRow(2)                        # "build", no presets
    if dlg.preset.isEnabled():
        PROBLEMS.append("the preset box is live for a script without presets")

    # -- add and remove --------------------------------------------------------------
    dlg.add_combo.setCurrentText(next(x for x in adds if "(make.py)" in x))
    dlg.add_button.click()
    if [s[1] for s in steps()][-1] != d or dlg.selected_index() != 3:
        PROBLEMS.append("Add did not append the chosen script and select it")
    dlg.remove_button.click()
    if [s[1] for s in steps()] != [b, a, c]:
        PROBLEMS.append(f"Remove left {[s[1] for s in steps()]}")

    # -- save only renames; an empty name is refused ------------------------------
    dlg.name_edit.setText("   ")
    if dlg.save() or warned != [pipelinesteps.NAME_REQUIRED[0]]:
        PROBLEMS.append("an empty pipeline name was accepted")
    dlg.name_edit.setText(" Renamed ")
    dlg.save()
    if db.list_pipelines("G")[0][1] != "Renamed" or saved != [True]:
        PROBLEMS.append("Save did not rename, or did not report back")

    print("  [ok] pipeline editor: labels, Add Step choices, move, with-prev, "
          "policy combos, step presets, add/remove and rename, all stored")
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




def check_drag_and_drop(app):
    """Reorder by dropping in the list, move by dropping on a tab.

    Drops are real QDropEvents delivered to the real widgets, against a real
    database, so what is checked is the whole path from event to stored order.
    Starting a drag is checked with QDrag.exec swapped for a recorder, since
    the real one blocks until a physical mouse button is released.
    """
    import tempfile

    from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import (QDragEnterEvent, QDragMoveEvent, QDropEvent,
                               QMouseEvent)

    from ryos.db import ScriptDB
    from ryos.qtui.dragdrop import MIME, CardPayload
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    tmp = Path(tempfile.mkdtemp())
    inside = tmp / "base"
    inside.mkdir()
    db = ScriptDB(tmp / "dnd.db")
    db.create_group("G", base_dir=str(inside))
    db.create_group("H", base_dir=str(tmp / "elsewhere"))
    ids = [db.add(n, str(inside / f"{n}.py"), "", "", "G")
           for n in ("a", "b", "c")]
    loose = db.add("loose", str(tmp / "loose.py"), "", "", "")
    p1 = db.create_pipeline("p1", "G")
    p2 = db.create_pipeline("p2", "G")

    win = MainWindow(REFERENCE["dark"], settings={"quick_run_enabled": False})
    win.resize(700, 600)
    win.show()
    win.load_from_db(db)
    app.processEvents()

    def order(group):
        return [r[0] for r in db.list_all() if (r[8] or "") == group]

    def drag_to(widget, pos, raw):
        """Enter, move, drop -- Qt refuses a drop that no enter accepted."""
        mime = QMimeData()
        mime.setData(MIME, raw)
        args = (Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)
        app.sendEvent(widget, QDragEnterEvent(pos, *args))
        app.sendEvent(widget, QDragMoveEvent(pos, *args))
        app.sendEvent(widget, QDropEvent(QPointF(pos), *args))
        app.processEvents()      # the reload is deferred to the next turn
        app.processEvents()

    def drop_on(widget, pos, payload):
        drag_to(widget, pos, payload.encode())

    # Tabs are keyed by group, so "Ungrouped" maps back to "".
    keys = [win.group_tab_bar.tabData(i) for i in range(win.group_tabs.count())]
    labels = [win.group_tabs.tabText(i) for i in range(win.group_tabs.count())]
    if keys != ["G", "H", ""] or labels[-1] != "Ungrouped":
        PROBLEMS.append(f"tabs were {list(zip(labels, keys))}")

    # -- reorder: drop "c" above "a" -----------------------------------------
    win.show_group("G")
    app.processEvents()
    lst = win.card_lists["G"].section("scripts")
    card_a = next(c for c in lst.cards if c.drag_payload.item_id == ids[0])
    above_a = QPoint(10, card_a.geometry().y() + 2)
    drop_on(lst, above_a, CardPayload("script", ids[2], "G"))
    if order("G") != [ids[2], ids[0], ids[1]]:
        PROBLEMS.append(f"dropping c above a gave order {order('G')}")
    if win.current_group() != "G":
        PROBLEMS.append("reloading after a drop switched away from the group")

    # Pipelines reorder among pipelines, not against scripts.
    lst = win.card_lists["G"].section("pipelines")
    card_p1 = next(c for c in lst.cards if c.drag_payload.kind == "pipeline"
                   and c.drag_payload.item_id == p1)
    drop_on(lst, QPoint(10, card_p1.geometry().y() + 2),
            CardPayload("pipeline", p2, "G"))
    if [p[0] for p in db.list_pipelines("G")] != [p2, p1]:
        PROBLEMS.append("pipelines did not reorder among themselves")

    # A card from another group is refused by this list.
    before = order("G")
    drop_on(win.card_lists["G"].section("scripts"), QPoint(10, 5),
            CardPayload("script", loose, ""))
    if order("G") != before or order("") != [loose]:
        PROBLEMS.append("a drop from another group was accepted by the list")

    # -- move: drop "b" on tab H, whose folder does not hold it ----------------
    bar = win.group_tab_bar
    h_index = keys.index("H")
    drop_on(bar, bar.tabRect(h_index).center(), CardPayload("script", ids[1], "G"))
    if ids[1] not in order("H"):
        PROBLEMS.append("dropping on tab H did not move the script there")
    if "outside" not in win.statusBar().currentMessage():
        PROBLEMS.append("moving a script outside the new group's folder did "
                        f"not warn: {win.statusBar().currentMessage()!r}")

    # Dropping on its own tab changes nothing.
    before_g = order("G")
    g_index = [win.group_tab_bar.tabData(i)
               for i in range(win.group_tabs.count())].index("G")
    drop_on(win.group_tab_bar, win.group_tab_bar.tabRect(g_index).center(),
            CardPayload("script", ids[0], "G"))
    if order("G") != before_g:
        PROBLEMS.append("dropping a card on its own tab changed the order")

    # Dropping on "Ungrouped" moves to "", not to a group named "Ungrouped".
    u_index = [win.group_tab_bar.tabData(i)
               for i in range(win.group_tabs.count())].index("")
    drop_on(win.group_tab_bar, win.group_tab_bar.tabRect(u_index).center(),
            CardPayload("script", ids[0], "G"))
    if ids[0] not in order("") or "Ungrouped" in db.list_groups():
        PROBLEMS.append("dropping on 'Ungrouped' did not ungroup the script")

    # A payload that is not ours is ignored everywhere.
    snapshot = {g: order(g) for g in ("G", "H", "")}
    drag_to(bar, bar.tabRect(h_index).center(), b"not json")
    if {g: order(g) for g in ("G", "H", "")} != snapshot:
        PROBLEMS.append("a malformed drag payload changed something")

    # -- starting a drag: the threshold decides, the payload travels ------------
    win.show_group("H")
    app.processEvents()
    card = win.card_lists["H"].cards[0]
    started: list = []
    card.drag_runner = lambda drag: started.append(
        CardPayload.decode(drag.mimeData().data(MIME).data()))

    def mouse(kind, pos, buttons):
        ev = QMouseEvent(kind, QPointF(pos), QPointF(card.mapToGlobal(pos)),
                         Qt.MouseButton.LeftButton, buttons,
                         Qt.KeyboardModifier.NoModifier)
        app.sendEvent(card, ev)

    press = QPoint(20, 10)
    mouse(QEvent.Type.MouseButtonPress, press, Qt.MouseButton.LeftButton)
    mouse(QEvent.Type.MouseMove, press + QPoint(3, 2), Qt.MouseButton.LeftButton)
    if started:
        PROBLEMS.append("a 3-pixel twitch started a drag")
    mouse(QEvent.Type.MouseMove, press + QPoint(0, 12), Qt.MouseButton.LeftButton)
    if len(started) != 1 or started[0] != card.drag_payload:
        PROBLEMS.append(f"a real drag did not start with the card's payload: "
                        f"{started}")
    mouse(QEvent.Type.MouseButtonRelease, press, Qt.MouseButton.NoButton)

    print("  [ok] drag and drop: reorder (scripts and pipelines apart), move "
          "to tab with folder warning, own tab no-op, Ungrouped maps to '', "
          "threshold respected")
    win.hide()
    win.deleteLater()




def check_schedules(app):
    """The bridge's own timer fires due schedules, by the policy Tk uses.

    Nothing here calls the sweep by hand for the first run: the bridge is
    started and the check waits for its timer, so a sweep that is never
    armed fails here rather than in a user's overnight job.
    """
    import json
    import sys as _sys
    import tempfile
    import time as _time
    from datetime import datetime, timedelta

    from ryos import schedule_runner
    from ryos.db import ScriptDB
    from ryos.qtui.jobs import JobBridge

    tmp = Path(tempfile.mkdtemp())
    quick = tmp / "quick.py"
    quick.write_text("print('scheduled')\n", encoding="utf-8")
    slow = tmp / "slow.py"
    slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    db = ScriptDB(tmp / "sched.db")
    db.create_group("G")
    sid = db.add("quick", str(quick), "", _sys.executable, "G")
    past = datetime.now() - timedelta(minutes=5)
    every_hour = json.dumps({"minutes": 60})
    db.add_schedule("script", script_id=sid, spec_type="interval",
                            spec=every_hour, enabled=True, next_run_at=past)

    bridge = JobBridge(db, {"max_parallel_jobs": 4})
    statuses: list = []
    bridge.status.connect(statuses.append)

    def pump_until(predicate, timeout=25.0):
        end = _time.time() + timeout
        while _time.time() < end and not predicate():
            app.processEvents()
            _time.sleep(0.02)
        return predicate()

    # -- the timer, not the test, fires it ---------------------------------
    bridge.start()
    runs = lambda: db.list_runs(script_id=sid)  # noqa: E731
    if not pump_until(lambda: runs() and runs()[0][6] is not None,
                      timeout=schedule_runner.FIRST_TICK_MS / 1000 + 20):
        PROBLEMS.append("the bridge's schedule timer never fired a due run")
    else:
        if runs()[0][10] != "schedule":
            PROBLEMS.append(f"scheduled run tagged {runs()[0][10]!r}")
        row = db.get_schedule(script_id=sid)
        if not row[8] or datetime.fromisoformat(row[8]) <= datetime.now():
            PROBLEMS.append("next_run_at was not advanced past now")
    if bridge.run_due_schedules() != 0:
        PROBLEMS.append("a schedule fired twice for one due time")

    # -- an ungrouped pipeline is found, not disabled as missing -------------
    pid = db.create_pipeline("loose", "")
    db.add_pipeline_step(pid, sid)
    db.add_schedule("pipeline", pipeline_id=pid, spec_type="interval",
                             spec=every_hour, enabled=True, next_run_at=past)
    if bridge.run_due_schedules() != 1:
        PROBLEMS.append("a due ungrouped pipeline did not start")
    if not db.get_schedule(pipeline_id=pid)[6]:
        PROBLEMS.append("an ungrouped pipeline's schedule was disabled")
    if not pump_until(lambda: len(bridge.registry) == 0):
        PROBLEMS.append("finished jobs were never unregistered, so they "
                        "count toward the cap and block their schedules")

    # -- overlap: never stack a second run on one still going ----------------
    slow_id = db.add("slow", str(slow), "", _sys.executable, "G")
    db.add_schedule("script", script_id=slow_id, spec_type="interval",
                    spec=json.dumps({"minutes": 1}), enabled=True,
                    next_run_at=past)
    first = bridge.run_due_schedules()
    slow_sched = db.get_schedule(script_id=slow_id)[0]
    db.mark_schedule_fired(slow_sched, past)
    second = bridge.run_due_schedules()
    if first != 1 or second != 0 or len(bridge.registry) != 1:
        PROBLEMS.append("a schedule stacked a second run on a running one")

    # -- a target that has gone disables its schedule ---------------------------
    gone = db.add("gone", str(quick), "", _sys.executable, "G")
    db.add_schedule("script", script_id=gone, spec_type="interval",
                    spec=every_hour, enabled=True, next_run_at=past)
    db.delete(gone)
    bridge.run_due_schedules()
    rows = [r for r in db.list_schedules() if r[2] == gone]
    if rows and rows[0][6]:
        PROBLEMS.append("a schedule for a deleted script stayed enabled")

    # -- a refusal reports to the status line, keeps the schedule ---------------
    broken = db.add("broken", str(tmp / "nope.py"), "", _sys.executable, "G")
    db.add_schedule("script", script_id=broken, spec_type="interval",
                    spec=every_hour, enabled=True, next_run_at=past)
    bridge.run_due_schedules()
    if not any("Scheduled run refused" in s for s in statuses):
        PROBLEMS.append(f"a refused scheduled run said nothing: {statuses}")
    if not db.get_schedule(script_id=broken)[6]:
        PROBLEMS.append("a refused run disabled its schedule")

    bridge.stop()             # terminates the slow run
    print("  [ok] schedules: timer fires and tags, advances, no double fire, "
          "ungrouped pipeline found, no overlap, missing target disabled, "
          "refusal reported")




def check_context_menus(app):
    """Right-click a card and a tab, then pick entries from the real menus.

    The menu comes from a real QContextMenuEvent and each entry is picked by
    triggering its QAction, so the path from click to database is the one a
    user takes. Only the prompts are answered by the test.
    """
    import sys as _sys
    import tempfile

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    from ryos import cardmenu
    from ryos.db import ScriptDB
    from ryos.qtui.menus import actions_by_key
    from ryos.qtui.pipeline import PipelineEditorDialog
    from ryos.qtui.shell import MainWindow
    from ryos.qtui.smalldialogs import (GroupBaseDirDialog, RunHistoryDialog,
                                        ScheduleDialog)
    from ryos.themes import REFERENCE, readable_highlight

    tmp = Path(tempfile.mkdtemp())
    base = tmp / "base"
    base.mkdir()
    db = ScriptDB(tmp / "menus.db")
    db.create_group("G", base_dir=str(base))
    db.create_group("H")
    a = db.add("a", str(base / "a.py"), "", _sys.executable, "G",
               detached=1, env_vars="K=V", work_dir=str(tmp))
    b = db.add("b", str(base / "b.py"), "", _sys.executable, "G")
    c = db.add("c", str(base / "c.py"), "", _sys.executable, "G")
    pid = db.create_pipeline("p", "G")
    db.add_pipeline_step(pid, a)

    palette = REFERENCE["dark"]
    win = MainWindow(palette, settings={"quick_run_enabled": False})
    win.resize(700, 600)
    win.show()
    win.load_from_db(db)
    app.processEvents()

    shown: list = []
    win.popup = lambda menu, pos: shown.append(menu)
    asked: list = []
    answers = {"yes": True, "text": None}
    win.ask_yes_no = lambda title, q: asked.append(title) or answers["yes"]
    win.ask_text = lambda title, prompt, initial: answers["text"]
    warned: list = []
    win.warn = lambda title, msg: warned.append((title, msg))
    dialogs: list = []
    win.run_dialog = lambda dlg: dialogs.append(dlg)

    def settle():
        for _ in range(3):
            app.processEvents()

    def card_for(kind, item_id):
        for group_page in win.card_lists.values():
            for card in group_page.cards:
                if (card.drag_payload.kind, card.drag_payload.item_id) == (kind, item_id):
                    return card
        raise AssertionError(f"no card for {kind} {item_id}")

    def right_click(widget, pos):
        shown.clear()
        app.sendEvent(widget, QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, pos, widget.mapToGlobal(pos)))
        return actions_by_key(shown[-1]) if shown else {}

    def pick(kind, item_id, key):
        acts = right_click(card_for(kind, item_id), QPoint(30, 10))
        if key not in acts:
            PROBLEMS.append(f"{kind} menu had no {key!r}: {sorted(acts)}")
            return
        acts[key].trigger()
        settle()

    def order():
        return [r[0] for r in db.list_all() if r[8] == "G"]

    # -- what the menus contain ------------------------------------------------
    acts = right_click(card_for("script", a), QPoint(30, 10))
    if not acts:
        PROBLEMS.append("right-clicking a card opened no menu")
    else:
        if acts[cardmenu.MOVE_UP].isEnabled() or acts[cardmenu.MOVE_TOP].isEnabled():
            PROBLEMS.append("the first card offered Move Up / Move to Top")
        if not acts[cardmenu.MOVE_DOWN].isEnabled():
            PROBLEMS.append("the first card could not Move Down")
        swatches = [k for k, act in acts.items()
                    if k.startswith("highlight:") and not act.icon().isNull()]
        if len(swatches) != len(cardmenu.HIGHLIGHTS):
            PROBLEMS.append(f"highlight entries with swatches: {swatches}")
    acts = right_click(card_for("script", c), QPoint(30, 10))
    if acts and acts[cardmenu.MOVE_DOWN].isEnabled():
        PROBLEMS.append("the last card offered Move Down")
    acts = right_click(card_for("pipeline", pid), QPoint(30, 10))
    if cardmenu.EDIT not in acts or cardmenu.MOVE_UP in acts:
        PROBLEMS.append(f"the pipeline menu was wrong: {sorted(acts)}")

    # -- card actions ------------------------------------------------------------
    pick("script", a, cardmenu.MOVE_DOWN)
    if order() != [b, a, c]:
        PROBLEMS.append(f"Move Down gave {order()}")
    pick("script", c, cardmenu.MOVE_TOP)
    if order()[0] != c:
        PROBLEMS.append(f"Move to Top gave {order()}")

    pick("script", b, cardmenu.FAVORITE)
    if not next(r for r in db.list_all() if r[0] == b)[10]:
        PROBLEMS.append("Add to Favorites did not store the favourite")
    card_for("script", b).fav_button.click()      # the star button too
    settle()
    if next(r for r in db.list_all() if r[0] == b)[10]:
        PROBLEMS.append("the star button did not remove the favourite")

    pick("script", b, cardmenu.highlight_key("red"))
    want = readable_highlight("red", palette["card_bg"], palette["card_hover"])
    if want not in card_for("script", b).name_label.styleSheet():
        PROBLEMS.append("a red highlight did not colour the card's name")
    acts = right_click(card_for("script", b), QPoint(30, 10))
    if not acts[cardmenu.highlight_key("red")].text().startswith("●"):
        PROBLEMS.append("the menu did not mark the current highlight")

    before = len(db.list_all())
    pick("script", a, cardmenu.CLONE)
    copy = max(r[0] for r in db.list_all())
    rec = db.get(copy)
    if len(db.list_all()) != before + 1 or rec[1] != "a (copy)":
        PROBLEMS.append("Clone did not add 'a (copy)'")
    elif not db.is_detached(copy) or rec[7] != "K=V" or rec[8] != str(tmp):
        PROBLEMS.append("Clone lost detached / env vars / working folder")

    answers["yes"] = False
    pick("script", copy, cardmenu.DELETE)
    if db.get(copy) is None or asked[-1:] != ["Delete"]:
        PROBLEMS.append("declining the delete prompt still deleted")
    answers["yes"] = True
    pick("script", copy, cardmenu.DELETE)
    if db.get(copy) is not None:
        PROBLEMS.append("confirming the delete prompt did not delete")

    dialogs.clear()
    pick("script", a, cardmenu.SCHEDULE)
    pick("pipeline", pid, cardmenu.HISTORY)
    pick("pipeline", pid, cardmenu.EDIT)
    kinds = [type(d) for d in dialogs]
    if kinds != [ScheduleDialog, RunHistoryDialog, PipelineEditorDialog]:
        PROBLEMS.append(f"dialogs opened from the menu: {kinds}")
    dialogs.clear()
    card_for("pipeline", pid).edit_button.click()        # the ⚙ button
    settle()
    if [type(d) for d in dialogs] != [PipelineEditorDialog]:
        PROBLEMS.append("the pipeline card's ⚙ did not open the editor")

    # -- the group-tab menu ----------------------------------------------------------
    bar = win.group_tab_bar
    keys = [bar.tabData(i) for i in range(bar.count())]

    def tab_click(group):
        return right_click(bar, bar.tabRect(keys.index(group)).center())

    db.add("loose", str(tmp / "loose.py"), "", _sys.executable, "")
    win.reload()
    settle()
    keys = [bar.tabData(i) for i in range(bar.count())]
    tab_click("")
    if shown:
        PROBLEMS.append("the Ungrouped tab offered a group menu")

    answers["text"] = "H"                     # clashes with another group
    tab_click("G")[cardmenu.RENAME_GROUP].trigger()
    settle()
    if "G" not in db.list_groups() or not warned:
        PROBLEMS.append("renaming onto an existing group was not refused")

    answers["text"] = "G2"
    win.show_group("G")
    tab_click("G")[cardmenu.RENAME_GROUP].trigger()
    settle()
    keys = [bar.tabData(i) for i in range(bar.count())]
    if "G2" not in db.list_groups() or win.current_group() != "G2":
        PROBLEMS.append("rename did not rename, or lost the selected group")

    answers["text"] = None                    # accept nothing: cancelled
    tab_click("G2")[cardmenu.CLONE_GROUP].trigger()
    settle()
    if len(db.list_groups()) != 2:
        PROBLEMS.append("cancelling Clone Group still cloned")
    answers["text"] = "G2 (copy)"
    keys = [bar.tabData(i) for i in range(bar.count())]
    tab_click("G2")[cardmenu.CLONE_GROUP].trigger()
    settle()
    if "G2 (copy)" not in db.list_groups() or win.current_group() != "G2 (copy)":
        PROBLEMS.append("Clone Group did not clone and show the copy")

    moved = tmp / "moved"
    moved.mkdir()

    def answer_base_dir(dlg):
        dialogs.append(dlg)
        if isinstance(dlg, GroupBaseDirDialog):
            dlg.e_dir.setText(str(moved))
            dlg.accept_form()
    win.run_dialog = answer_base_dir
    asked.clear()
    keys = [bar.tabData(i) for i in range(bar.count())]
    tab_click("G2")[cardmenu.BASE_DIR].trigger()
    settle()
    if db.get_group_base_dir("G2") != str(moved) or asked != ["Re-map paths"]:
        PROBLEMS.append(f"moving the base folder: stored "
                        f"{db.get_group_base_dir('G2')!r}, asked {asked}")
    if "remapped" not in win.statusBar().currentMessage():
        PROBLEMS.append("the base folder change reported nothing")

    out = tmp / "export.json"
    win.ask_save_path = lambda title, initial: str(out)
    keys = [bar.tabData(i) for i in range(bar.count())]
    tab_click("G2")[cardmenu.EXPORT_GROUP].trigger()
    settle()
    if not out.exists() or "Exported" not in win.statusBar().currentMessage():
        PROBLEMS.append("Export group wrote nothing")

    keys = [bar.tabData(i) for i in range(bar.count())]
    tab_click("G2 (copy)")[cardmenu.DELETE_GROUP].trigger()
    settle()
    if "G2 (copy)" in db.list_groups():
        PROBLEMS.append("Delete Group did not delete")
    if win.current_group() not in db.list_groups() + [""]:
        PROBLEMS.append(f"after deleting, showing {win.current_group()!r}")

    print("  [ok] context menus: right-click opens the shared menus, moves "
          "disabled at the ends, swatches, favourite/highlight/move/clone/"
          "delete, dialogs, and the tab menu's rename/clone/base dir/export/"
          "delete with their prompts")
    win.hide()
    win.deleteLater()




def check_select_mode(app):
    """Select mode: tick, select all, run past the cap, delete -- for real.

    Runs go through a real JobBridge, so "started 2 of 3" is counted from the
    registry, not from what the window thinks it asked for.
    """
    import sys as _sys
    import tempfile
    import time as _time

    from ryos import selection
    from ryos.db import ScriptDB
    from ryos.qtui.jobs import JobBridge
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    tmp = Path(tempfile.mkdtemp())
    db = ScriptDB(tmp / "select.db")
    db.create_group("G")
    db.create_group("H")
    ids = []
    for i in range(3):
        script = tmp / f"s{i}.py"
        script.write_text(f"print('selected {i}')\n", encoding="utf-8")
        ids.append(db.add(f"s{i}", str(script), "", _sys.executable, "G"))
    other = tmp / "other.py"
    other.write_text("print('other')\n", encoding="utf-8")
    db.add("other", str(other), "", _sys.executable, "H")
    pid = db.create_pipeline("p", "G")
    db.add_pipeline_step(pid, ids[0])

    settings = {"quick_run_enabled": False, "max_parallel_jobs": 2}
    win = MainWindow(REFERENCE["dark"], settings=settings)
    bridge = JobBridge(db, {"max_parallel_jobs": 2})
    win.attach_jobs(bridge)
    bridge.start()
    win.resize(700, 600)
    win.show()
    win.load_from_db(db)
    win.show_group("G")
    app.processEvents()

    told: list = []
    win.inform = lambda title, text: told.append(title)
    answers = {"yes": False}
    win.ask_yes_no = lambda title, q: answers["yes"]

    def pump_until(predicate, timeout=25.0):
        end = _time.time() + timeout
        while _time.time() < end and not predicate():
            app.processEvents()
            _time.sleep(0.02)
        return predicate()

    # -- entering ------------------------------------------------------------
    if win.select_bar.isVisible():
        PROBLEMS.append("the select bar showed before select mode")
    win.select_action.trigger()
    app.processEvents()
    cards = win.selectable_cards()
    if (not win.select_bar.isVisible()
            or win.select_action.text() != selection.LEAVE_LABEL):
        PROBLEMS.append("Options > Select scripts did not enter select mode")
    if len(cards) != 3 or not all(c.checkbox.isVisible() for c in cards):
        PROBLEMS.append(f"{len(cards)} selectable cards; pipelines are not "
                        "selectable and every script should show a box")
    if win.select_label.text() != selection.HINT:
        PROBLEMS.append("the bar did not start with the hint")

    # -- ticking -------------------------------------------------------------
    cards[0].checkbox.click()
    cards[1].checkbox.click()
    if win.select_label.text() != "2 of 3 selected":
        PROBLEMS.append(f"bar said {win.select_label.text()!r} for 2 of 3")
    win.select_all_button.click()
    if (len(win.selected_cards()) != 3
            or win.select_all_button.text() != "Deselect All"):
        PROBLEMS.append("Select All did not tick every script")
    win.select_all_button.click()
    if win.selected_cards():
        PROBLEMS.append("Deselect All left something ticked")

    # -- running -------------------------------------------------------------
    win.run_selected_button.click()
    if told != [selection.NOTHING_TO_RUN[0]] or len(bridge.registry):
        PROBLEMS.append("running nothing did not explain itself")
    told.clear()

    win.select_all_button.click()
    win.run_selected_button.click()
    if len(bridge.registry) != 2 or told != ["Job limit reached"]:
        PROBLEMS.append(f"past the cap: {len(bridge.registry)} started, "
                        f"told {told}")
    if len(win.selected_cards()) != 3:
        PROBLEMS.append("the selection was cleared, so skipped scripts "
                        "cannot be retried")
    if not pump_until(lambda: len(bridge.registry) == 0):
        PROBLEMS.append("the selected runs never finished")
    told.clear()
    # The window and the bridge each copy their settings; raise both caps.
    win._settings["max_parallel_jobs"] = bridge._settings["max_parallel_jobs"] = 10
    win.run_selected_button.click()
    if len(bridge.registry) != 3 or told:
        PROBLEMS.append("under the cap, not every selected script started")
    if win.statusBar().currentMessage() != "Started 3 scripts.":
        PROBLEMS.append(f"status after running: "
                        f"{win.statusBar().currentMessage()!r}")
    pump_until(lambda: len(bridge.registry) == 0)

    # -- a refused run says why, instead of doing nothing ---------------------
    warned: list = []
    win.warn = lambda title, text: warned.append(title)
    db.add("gone", str(tmp / "missing.py"), "", _sys.executable, "H")
    win.set_select_mode(False)
    win.reload()
    app.processEvents()
    gone = next(c for c in win.card_lists["H"].cards if c._name == "gone")
    gone.run_button.click()
    if not warned or len(bridge.registry):
        PROBLEMS.append("running a missing script was refused silently")
    win.set_select_mode(True)

    # -- the tab decides the scope --------------------------------------------
    win.show_group("H")
    app.processEvents()
    if win.select_label.text() != selection.HINT or len(win.selectable_cards()) != 2:
        PROBLEMS.append("switching tabs did not re-scope the selection")
    win.show_group("G")
    app.processEvents()

    # -- deleting ------------------------------------------------------------
    for c in win.selectable_cards():
        c.checkbox.setChecked(False)
    win.selectable_cards()[2].checkbox.click()
    answers["yes"] = False
    win.delete_selected_button.click()
    app.processEvents()
    if len([r for r in db.list_all() if r[8] == "G"]) != 3:
        PROBLEMS.append("declining Delete Selected still deleted")
    answers["yes"] = True
    win.delete_selected_button.click()
    for _ in range(3):
        app.processEvents()
    left = [r[0] for r in db.list_all() if r[8] == "G"]
    if left != ids[:2]:
        PROBLEMS.append(f"Delete Selected left {left}")
    if win.select_mode or win.select_bar.isVisible():
        PROBLEMS.append("select mode survived the reload after deleting")

    bridge.stop()
    print("  [ok] select mode: enters from Options, pipelines excluded, count "
          "and Select All, one notice past the cap with the selection kept, "
          "tab re-scopes, delete asks first")
    win.hide()
    win.deleteLater()




def check_group_management(app):
    """New group, drag a tab to reorder, export/import, Delete All -- for real.

    The tab reorder is a real press-move-release on the tab bar; the order
    checked is the one stored in the database.
    """
    import sys as _sys
    import tempfile

    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from ryos.db import ScriptDB
    from ryos.qtui.shell import MainWindow
    from ryos.qtui.smalldialogs import NewGroupDialog
    from ryos.themes import REFERENCE

    tmp = Path(tempfile.mkdtemp())
    db = ScriptDB(tmp / "groups.db")
    for g in ("A", "B", "C"):
        db.create_group(g)
    for i, g in enumerate(("A", "A", "B", "C")):
        db.add(f"s{i}", str(tmp / f"s{i}.py"), "", _sys.executable, g)
    db.add("loose", str(tmp / "loose.py"), "", _sys.executable, "")

    win = MainWindow(REFERENCE["dark"], settings={"quick_run_enabled": False})
    win.resize(800, 600)
    win.show()
    win.load_from_db(db)
    app.processEvents()

    asked: list = []
    answers = {"yes": False}
    win.ask_yes_no = lambda title, q: asked.append(q) or answers["yes"]
    warned: list = []
    win.warn = lambda title, msg: warned.append((title, msg))

    def settle():
        for _ in range(3):
            app.processEvents()

    bar = win.group_tab_bar

    # -- new group, from the + button -----------------------------------------
    def fill_new_group(dlg):
        if isinstance(dlg, NewGroupDialog):
            dlg.e_name.setText("  New  ")
            dlg.e_dir.setText(str(tmp))
            dlg.accept_form()
    win.run_dialog = fill_new_group
    win.new_group_button.click()
    settle()
    if db.list_groups()[-1:] != ["New"] or db.get_group_base_dir("New") != str(tmp):
        PROBLEMS.append(f"+ did not create 'New': {db.list_groups()}")
    if win.current_group() != "New":
        PROBLEMS.append("the new group was not brought to the front")

    # -- drag tab C in front of A, with the mouse --------------------------------
    def mouse(kind, pos, buttons):
        app.sendEvent(bar, QMouseEvent(
            kind, QPointF(pos), QPointF(bar.mapToGlobal(pos)),
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))

    keys = bar.tab_keys()
    start = bar.tabRect(keys.index("C")).center()
    end = bar.tabRect(keys.index("A")).center() - QPoint(8, 0)
    mouse(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    for step in range(1, 11):
        mouse(QEvent.Type.MouseMove, start + (end - start) * step / 10,
              Qt.MouseButton.LeftButton)
    mouse(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
    settle()
    if db.list_groups() != ["C", "A", "B", "New"]:
        PROBLEMS.append(f"dragging tab C to the front stored {db.list_groups()}")

    # Ungrouped cannot stay anywhere but last.
    bar.moveTab(bar.tab_keys().index(""), 0)
    mouse(QEvent.Type.MouseButtonRelease, QPoint(5, 5), Qt.MouseButton.NoButton)
    settle()
    if bar.tab_keys()[-1] != "" or db.list_groups() != ["C", "A", "B", "New"]:
        PROBLEMS.append(f"after moving Ungrouped: tabs {bar.tab_keys()}, "
                        f"stored {db.list_groups()}")

    # -- export all, then import into another window's database -------------------
    out = tmp / "all.json"
    win.ask_save_path = lambda title, initial: str(out)
    win.export_all()
    if not out.exists() or "all.json" not in win.statusBar().currentMessage():
        PROBLEMS.append("Export all groups wrote nothing, or did not say where")

    other_db = ScriptDB(tmp / "other.db")
    other = MainWindow(REFERENCE["dark"], settings={"quick_run_enabled": False})
    other.load_from_db(other_db)
    other.ask_open_path = lambda title: str(out)
    other.ask_yes_no = lambda title, q: False            # merge
    other.import_config()
    settle()
    if set(other_db.list_groups()) != {"A", "B", "C", "New"}:
        PROBLEMS.append(f"import brought in {other_db.list_groups()}")
    if len(other_db.list_all()) != 5 or "5 script(s) added" not in \
            other.statusBar().currentMessage():
        PROBLEMS.append(f"import: {len(other_db.list_all())} scripts, "
                        f"{other.statusBar().currentMessage()!r}")
    if set(other.card_lists) != {"A", "B", "C", "New", ""}:
        PROBLEMS.append("the imported groups did not appear as tabs")
    other.import_config()                                # again: all skipped
    settle()
    if len(other_db.list_all()) != 5:
        PROBLEMS.append("importing the same file twice duplicated scripts")
    other.deleteLater()

    # -- Delete All counts every script, not the tab on screen ---------------------
    win.show_group("B")                  # one card showing, five in the database
    asked.clear()
    answers["yes"] = False
    win.delete_all_action.trigger()
    settle()
    if not asked or "5 scripts" not in asked[0] or len(db.list_all()) != 5:
        PROBLEMS.append(f"Delete All asked {asked} with one card on screen")
    answers["yes"] = True
    win.delete_all_action.trigger()
    settle()
    if db.list_all():
        PROBLEMS.append("confirming Delete All left scripts behind")
    asked.clear()
    win.delete_all_action.trigger()
    if asked:
        PROBLEMS.append("Delete All asked with nothing to delete")

    print("  [ok] group management: + makes and shows a group, a mouse drag "
          "reorders tabs, Ungrouped stays last, export/import round-trips, "
          "Delete All names the real count")
    win.hide()
    win.deleteLater()




def check_tray_and_close(app):
    """Tray menu and tooltip, close/minimise to tray, a second launch, quit.

    The second launch is the real `single_instance` listener on a loopback
    socket, sent a real handshake -- not `acquire()`, which would touch the
    user's own lock file. Settings saving and application quit are stubbed:
    both default to doing nothing, so no smoke run can write real settings.
    """
    import secrets
    import socket
    import sys as _sys
    import tempfile
    import time as _time

    from PySide6.QtGui import QIcon, QPixmap

    from ryos import traypolicy
    from ryos.db import ScriptDB
    from ryos.qtui.jobs import JobBridge
    from ryos.qtui.shell import MainWindow
    from ryos.qtui.smalldialogs import CloseToTrayPromptDialog
    from ryos.qtui.tray import Tray
    from ryos.single_instance import SingleInstance
    from ryos.themes import REFERENCE

    def pump_until(predicate, timeout=15.0):
        end = _time.time() + timeout
        while _time.time() < end and not predicate():
            app.processEvents()
            _time.sleep(0.02)
        return predicate()

    pix = QPixmap(16, 16)
    pix.fill()
    tray = Tray(QIcon(pix), title="RYOS test")

    # -- the menu and tooltip follow the job snapshot --------------------------------
    picked: list = []
    tray.job_requested.connect(lambda jid: picked.append(("job", jid)))
    tray.show_requested.connect(lambda: picked.append(("show",)))
    tray.exit_requested.connect(lambda: picked.append(("exit",)))
    tray.set_jobs([(4, "alpha"), (9, "⚡ pipe — Step 2/3: b")])
    labels = [a.text() for a in tray.menu.actions() if not a.isSeparator()]
    if labels != ["alpha", "⚡ pipe — Step 2/3: b", "Show RYOS", "Exit"]:
        PROBLEMS.append(f"tray menu {labels}")
    if tray.tooltip != traypolicy.tray_title(["alpha", "⚡ pipe — Step 2/3: b"],
                                              "RYOS test"):
        PROBLEMS.append(f"tray tooltip {tray.tooltip!r}")
    by_key = {a.data(): a for a in tray.menu.actions()}
    for key in (traypolicy.job_key(9), traypolicy.SHOW, traypolicy.EXIT):
        by_key[key].trigger()
    if picked != [("job", 9), ("show",), ("exit",)]:
        PROBLEMS.append(f"tray actions emitted {picked}")
    tray.set_jobs([])
    if tray.tooltip != "RYOS test":
        PROBLEMS.append("the tooltip kept jobs that had finished")

    # -- a window with the tray, a bridge and a real instance listener ---------------
    tmp = Path(tempfile.mkdtemp())
    slow = tmp / "slow.py"
    slow.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    db = ScriptDB(tmp / "tray.db")
    db.create_group("G")
    db.add("slow", str(slow), "", _sys.executable, "G")

    saved: list = []
    quits: list = []
    settings = {"quick_run_enabled": False, "close_to_tray": False,
                "prompt_close_to_tray": True, "max_parallel_jobs": 4}
    win = MainWindow(REFERENCE["dark"], settings=settings,
                     save_settings=lambda s: saved.append(dict(s)))
    win.on_quit = lambda: quits.append(True)
    bridge = JobBridge(db, {"max_parallel_jobs": 4})
    win.attach_jobs(bridge)
    bridge.start()
    win.attach_tray(tray)
    win.tray_available = lambda: True       # offscreen CI has no tray
    win.load_from_db(db)
    win.show()
    app.processEvents()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(4)
    token = secrets.token_hex(8)
    lock = SingleInstance(sock=sock, token=token)
    win.attach_instance(lock, interval_ms=20)

    # A running job reaches the tray.
    win.card_lists["G"].cards[0].run_button.click()
    if not pump_until(lambda: "slow" in tray.tooltip):
        PROBLEMS.append(f"a running job never reached the tray: {tray.tooltip!r}")

    # -- close asks; each answer does what it says ------------------------------------
    answers = {"result": "cancel", "dont_ask": False}

    def answer(dlg):
        if isinstance(dlg, CloseToTrayPromptDialog):
            dlg.result, dlg.dont_ask = answers["result"], answers["dont_ask"]
    win.run_dialog = answer
    win.close()
    app.processEvents()
    if not win.isVisible() or quits or saved:
        PROBLEMS.append("Cancel on the close prompt did something")
    answers.update(result="tray", dont_ask=False)
    win.close()
    app.processEvents()
    if win.isVisible() or not win.hidden_to_tray or quits:
        PROBLEMS.append("choosing the tray did not hide the window")
    if not saved or not saved[-1].get("close_to_tray") \
            or saved[-1].get("prompt_close_to_tray"):
        PROBLEMS.append(f"choosing the tray was not remembered: {saved[-1:]}")
    if len(bridge.registry) != 1:
        PROBLEMS.append("hiding to the tray stopped the running job")

    # -- a second launch restores it, through the real listener -----------------------
    port = sock.getsockname()[1]
    with socket.create_connection(("127.0.0.1", port), timeout=2) as c:
        c.sendall(f"{token} RESTORE\n".encode())
        reply = c.recv(16)
    if reply != b"OK\n" or not pump_until(lambda: win.isVisible()):
        PROBLEMS.append(f"a second launch did not restore the window ({reply!r})")
    if win.hidden_to_tray:
        PROBLEMS.append("restored, but still marked hidden")

    # Remembered: closing now goes straight to the tray, no prompt.
    win.run_dialog = lambda dlg: PROBLEMS.append("prompted again after 'tray'")
    win.close()
    app.processEvents()
    if win.isVisible():
        PROBLEMS.append("close did not go straight to the tray")
    tray.show_requested.emit()
    app.processEvents()

    # -- minimising goes to the tray --------------------------------------------------
    win.showMinimized()
    if not pump_until(lambda: win.hidden_to_tray and not win.isVisible(), 5):
        PROBLEMS.append("minimising did not hide to the tray")
    if not bridge.registry.all():
        PROBLEMS.append("the running job was gone before the tray could "
                        "jump to it (did a close quit the app?)")
        win.deleteLater()
        return
    job = bridge.registry.all()[0]
    tray.job_requested.emit(job.job_id)
    app.processEvents()
    if not win.isVisible() or win.output_tabs.currentWidget() is not \
            win._output_tabs.get(job.tab_key):
        PROBLEMS.append("picking a job in the tray did not show its output")

    # -- quit with a job alive asks, and only then stops everything ---------------------
    asked: list = []
    win.ask_yes_no = lambda title, q: asked.append(title) or False
    tray.exit_requested.emit()
    app.processEvents()
    if asked != ["Still Running"] or quits or not job.active_processes():
        PROBLEMS.append(f"declining quit: asked {asked}, quit {quits}")
    win.ask_yes_no = lambda title, q: True
    tray.exit_requested.emit()
    app.processEvents()
    if quits != [True] or win.isVisible():
        PROBLEMS.append("confirming quit did not quit")
    if not job.stopped:
        PROBLEMS.append("quitting left the job running")
    if tray.icon.isVisible():
        PROBLEMS.append("quitting left the tray icon up")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            PROBLEMS.append("quitting did not release the instance listener")
    except OSError:
        pass

    print("  [ok] tray and close: menu/tooltip follow jobs, close prompt answers, "
          "remembered tray, second launch restores, minimise hides, job jump, "
          "quit asks then stops jobs, tray and listener")
    win.deleteLater()




def check_updates_and_notify(app):
    """The update banner and notices, and job-finished toasts.

    The fetch and the toast are injected: the real ones call GitHub and pop a
    Windows toast. What is checked is everything around them -- that the
    fetch runs off the UI thread, and what each result shows.
    """
    import sys as _sys
    import tempfile
    import threading
    import time as _time

    from ryos import __version__, notifications
    from ryos.db import ScriptDB
    from ryos.qtui.jobs import JobBridge
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    def pump_until(predicate, timeout=10.0):
        end = _time.time() + timeout
        while _time.time() < end and not predicate():
            app.processEvents()
            _time.sleep(0.02)
        return predicate()

    reply = {"value": ("v999.0.0", "https://example.invalid/r")}
    threads: list = []

    def fetch():
        threads.append(threading.current_thread() is threading.main_thread())
        return reply["value"]

    toasts: list = []
    settings = {"quick_run_enabled": False, "notify_on_complete": True}
    win = MainWindow(REFERENCE["dark"], settings=settings, fetch_release=fetch,
                     notifier=lambda title, body: toasts.append(title))
    told: list = []
    win.inform = lambda title, text: told.append(title)
    opened: list = []
    win.open_url = opened.append
    win.show()

    # -- a newer release: a banner, once, that opens the release page ---------------
    win.check_for_updates()
    if not pump_until(lambda: win.update_banner is not None):
        PROBLEMS.append("a newer release never showed the banner")
        return
    if threads != [False]:
        PROBLEMS.append("the update fetch ran on the UI thread")
    if win.update_label.text() != notifications.banner_text("v999.0.0", __version__):
        PROBLEMS.append(f"banner said {win.update_label.text()!r}")
    win.update_download.click()
    if opened != ["https://example.invalid/r"]:
        PROBLEMS.append(f"Download opened {opened}")
    banner = win.update_banner
    win.check_for_updates(manual=True)
    pump_until(lambda: len(threads) == 2)
    app.processEvents()
    if win.update_banner is not banner or told:
        PROBLEMS.append("a second check added a second banner, or a notice")
    win.dismiss_update_banner()
    app.processEvents()
    if win.update_banner is not None:
        PROBLEMS.append("✕ did not dismiss the banner")

    # -- manual checks say when there is nothing, automatic ones stay quiet ---------
    reply["value"] = (f"v{__version__}", "https://example.invalid/r")
    win.update_action.trigger()
    pump_until(lambda: told)
    if told != ["Up to date"] or win.update_banner is not None:
        PROBLEMS.append(f"current version, manual: told {told}")
    told.clear()
    reply["value"] = None
    win.check_for_updates(manual=True)
    pump_until(lambda: told)
    if told != [notifications.UNREACHABLE_NOTICE[0]]:
        PROBLEMS.append(f"unreachable, manual: told {told}")
    told.clear()
    before = len(threads)
    win.check_for_updates()
    pump_until(lambda: len(threads) > before)
    app.processEvents()
    if told:
        PROBLEMS.append("an automatic check that failed said something")

    # -- a finished job toasts, unless the setting is off ----------------------------
    tmp = Path(tempfile.mkdtemp())
    quick = tmp / "q.py"
    quick.write_text("print('done')\n", encoding="utf-8")
    db = ScriptDB(tmp / "notify.db")
    db.create_group("G")
    sid = db.add("q", str(quick), "", _sys.executable, "G")
    bridge = JobBridge(db, {"max_parallel_jobs": 4})
    win.attach_jobs(bridge)
    bridge.start()
    bridge.run_script(sid, "q", str(quick), "", _sys.executable)
    if not pump_until(lambda: toasts, 20):
        PROBLEMS.append("a finished job sent no notification")
    toasts.clear()
    win._settings["notify_on_complete"] = False
    bridge.run_script(sid, "q", str(quick), "", _sys.executable)
    pump_until(lambda: len(bridge.registry) == 0, 20)
    app.processEvents()
    if toasts:
        PROBLEMS.append("notify_on_complete off still sent a notification")
    bridge.stop()

    print("  [ok] updates and notify: fetch off the UI thread, one banner that "
          "opens the release, manual up-to-date / unreachable notices, quiet "
          "automatic failure, job toasts follow the setting")
    win.hide()
    win.deleteLater()




def check_window_placement(app):
    """Where the window opens, snaps, is remembered, and restores to.

    A made-up two-monitor desktop is injected, so the numbers are the same on
    any machine: A is (0, 0, 1000, 800), B is (1000, 0, 900, 800).
    """
    from PySide6.QtCore import Qt

    from ryos.qtui.dialogs import OptionsDialog
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    A, B = (0, 0, 1000, 800), (1000, 0, 900, 800)

    def area_at(x, y):
        return A if x < 1000 else B

    def window(settings, cursor=B, **kw):
        base = {"quick_run_enabled": False, "window_width": 540,
                "window_height": 640, "open_on_cursor_monitor": True,
                "remember_window_geometry": True}
        base.update(settings)
        saved: list = []
        win = MainWindow(REFERENCE["dark"], settings=base,
                         save_settings=lambda s: saved.append(dict(s)))
        win.cursor_area = lambda: cursor
        win.area_at = area_at
        win.show()
        app.processEvents()
        win.apply_placement(**kw)
        app.processEvents()
        return win, saved

    def at(win):
        return (win.x(), win.y(), win.width(), win.height())

    # Saved on A, cursor on B: same offset, moved to B.
    win, _ = window({"window_geometry": "540x640+100+50"})
    if at(win) != (1100, 50, 540, 640):
        PROBLEMS.append(f"saved geometry moved to the cursor monitor at {at(win)}")
    win.deleteLater()

    # A login launch restores exactly where it was, whatever the cursor.
    win, _ = window({"window_geometry": "540x640+100+50"}, launched_at_startup=True)
    if at(win) != (100, 50, 540, 640):
        PROBLEMS.append(f"a login launch opened at {at(win)}")
    win.deleteLater()

    # Nothing saved: centred on the cursor's monitor.
    win, _ = window({"remember_window_geometry": False,
                     "window_geometry": "540x640+100+50"})
    if at(win) != (1180, 80, 540, 640):
        PROBLEMS.append(f"centring on the cursor monitor gave {at(win)}")
    win.deleteLater()

    # Snap to a corner of the cursor's monitor, and always on top.
    win, saved = window({"snap_corner": "bottom-right", "always_on_top": True})
    if (win.x(), win.y()) != (1350, 150):
        PROBLEMS.append(f"bottom-right snap on B gave {(win.x(), win.y())}")
    if not win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint or not win.isVisible():
        PROBLEMS.append("always-on-top was not applied, or hid the window")
    win.deleteLater()

    # -- remembered on quit, even from the tray --------------------------------------
    win, saved = window({})
    win.move(200, 60)
    app.processEvents()
    win.hide_to_tray()
    win.quit_app()
    if not saved or saved[-1].get("window_geometry") != "540x640+200+60":
        PROBLEMS.append(f"quitting from the tray saved "
                        f"{saved[-1].get('window_geometry') if saved else None!r}")

    # -- a second launch restores onto the cursor's monitor ---------------------------
    win, _ = window({"window_geometry": "540x640+100+50"}, cursor=A)
    win.cursor_area = lambda: B
    win.hide_to_tray()
    win.restore_from_tray(follow_cursor=True)
    app.processEvents()
    if (win.x(), win.y()) != (1100, 50) or not win.isVisible():
        PROBLEMS.append(f"restoring to the cursor monitor gave {at(win)}")
    win.deleteLater()

    # -- Advanced options opens, and saving applies to the window ---------------------
    win, saved = window({})
    dialogs: list = []
    win.run_dialog = dialogs.append
    win.options_action.trigger()
    if len(dialogs) != 1 or not isinstance(dialogs[0], OptionsDialog):
        PROBLEMS.append("Options > Advanced options did not open the dialog")
    else:
        win.apply_settings({"window_width": 600, "always_on_top": True,
                            "snap_corner": "top-left"})
        app.processEvents()
        if win.width() != 600 or (win.x(), win.y()) != (1010, 10):
            PROBLEMS.append(f"applied options left the window at {at(win)}")
        if not win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            PROBLEMS.append("applied options did not set always-on-top")
        if not saved or saved[-1].get("window_width") != 600:
            PROBLEMS.append("applied options were not saved")
        # Compact cards take effect on the rebuilt card list.
        import tempfile
        from ryos.db import ScriptDB
        db = ScriptDB(Path(tempfile.mkdtemp()) / "opts.db")
        db.create_group("G")
        db.add("s", "/x/s.py", "", "", "G")
        win.load_from_db(db)
        path_shown = hasattr(win.card_lists["G"].cards[0], "path_label")
        win.apply_settings({"compact_mode": True})
        for _ in range(3):
            app.processEvents()
        if not path_shown or hasattr(win.card_lists["G"].cards[0], "path_label"):
            PROBLEMS.append("turning on compact cards did not rebuild them")
    win.deleteLater()

    print("  [ok] window placement: moved to the cursor monitor, login restores "
          "in place, centred, corner snap, on top, remembered from the tray, "
          "restore follows the cursor, options apply")




def check_sections_and_favorites(app):
    """Favorites / Pipelines / Scripts sections, on a real database.

    A favourite shows twice, as in Tk: in Favorites and in its own section.
    Moving or dropping a favourite in Favorites moves it among favourites.
    """
    import sys as _sys
    import tempfile

    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    from ryos import cardmenu, sections
    from ryos.db import ScriptDB
    from ryos.qtui.dragdrop import MIME, CardPayload
    from ryos.qtui.shell import MainWindow
    from ryos.themes import REFERENCE

    tmp = Path(tempfile.mkdtemp())
    db = ScriptDB(tmp / "fav.db")
    db.create_group("G")
    db.create_group("H")
    ids = {n: db.add(n, str(tmp / f"{n}.py"), "", _sys.executable, "G")
           for n in ("alpha", "bravo", "charlie", "delta")}
    db.set_favorite_script(ids["bravo"], True)
    db.set_favorite_script(ids["delta"], True)
    p1 = db.create_pipeline("pipe-one", "G")
    db.create_pipeline("pipe-two", "G")
    db.set_favorite_pipeline(p1, True)

    win = MainWindow(REFERENCE["dark"], settings={"quick_run_enabled": False})
    win.resize(700, 900)
    shown_menus: list = []
    win.popup = lambda menu, pos: shown_menus.append(menu)
    win.show()
    win.load_from_db(db)
    win.show_group("G")
    app.processEvents()

    def settle():
        for _ in range(3):
            app.processEvents()

    def names(key, group="G"):
        return [c._name for c in win.card_lists[group].section(key).cards]

    def order():
        return [r[1] for r in db.list_all() if r[8] == "G"]

    # -- what each section holds ----------------------------------------------------
    if names(sections.FAVORITES) != ["pipe-one", "bravo", "delta"]:
        PROBLEMS.append(f"Favorites held {names(sections.FAVORITES)}")
    if names(sections.PIPELINES) != ["pipe-one", "pipe-two"]:
        PROBLEMS.append(f"Pipelines held {names(sections.PIPELINES)}")
    if names(sections.SCRIPTS) != ["alpha", "bravo", "charlie", "delta"]:
        PROBLEMS.append(f"Scripts held {names(sections.SCRIPTS)}")
    page = win.card_lists["G"]
    headers = [page.sections[k].header.text() for k in sections.ORDER]
    if headers != [sections.header_text(k, False) for k in sections.ORDER]:
        PROBLEMS.append(f"section headers {headers}")
    empty_h = win.card_lists["H"].sections[sections.FAVORITES]
    if empty_h.empty.isHidden() or not empty_h.cards.isHidden():
        PROBLEMS.append("an empty section did not say so")

    # -- collapsing survives a reload, and is per group -------------------------------
    page.sections[sections.SCRIPTS].header.click()
    if not page.section(sections.SCRIPTS).isHidden():
        PROBLEMS.append("clicking the Scripts header did not collapse it")
    win.reload()
    settle()
    page = win.card_lists["G"]
    if not page.section(sections.SCRIPTS).isHidden() \
            or not page.sections[sections.SCRIPTS].header.text().startswith("▶"):
        PROBLEMS.append("a collapsed section opened again on reload")
    if win.card_lists["H"].sections[sections.SCRIPTS].empty.isHidden():
        PROBLEMS.append("collapsing in one group collapsed another")
    page.sections[sections.SCRIPTS].header.click()
    if page.section(sections.SCRIPTS).isHidden():
        PROBLEMS.append("clicking again did not expand it")

    # -- a move from the menu moves among the section it was shown in ----------------
    def menu_pick(section, name, key):
        card = next(c for c in win.card_lists["G"].section(section).cards
                    if c._name == name)
        shown_menus.clear()
        from PySide6.QtGui import QContextMenuEvent
        app.sendEvent(card, QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                              QPoint(20, 10),
                                              card.mapToGlobal(QPoint(20, 10))))
        from ryos.qtui.menus import actions_by_key
        acts = actions_by_key(shown_menus[-1])
        return acts, key

    acts, key = menu_pick(sections.FAVORITES, "bravo", cardmenu.MOVE_DOWN)
    if acts[cardmenu.MOVE_UP].isEnabled():
        PROBLEMS.append("the first favourite script offered Move Up")
    acts[key].trigger()
    settle()
    if order() != ["alpha", "delta", "charlie", "bravo"]:
        PROBLEMS.append(f"Move Down in Favorites gave {order()} "
                        "(it should swap with the next favourite)")
    acts, key = menu_pick(sections.SCRIPTS, "charlie", cardmenu.MOVE_UP)
    acts[key].trigger()
    settle()
    if order() != ["alpha", "charlie", "delta", "bravo"]:
        PROBLEMS.append(f"Move Up in Scripts gave {order()}")

    # -- dropping in Favorites reorders the shared script order ------------------------
    fav = win.card_lists["G"].section(sections.FAVORITES)
    target = next(c for c in fav.cards if c._name == "delta")
    mime = QMimeData()
    mime.setData(MIME, CardPayload("script", ids["bravo"], "G").encode())
    pos = QPoint(10, target.geometry().y() + 2)
    args = (Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
    app.sendEvent(fav, QDragEnterEvent(pos, *args))
    app.sendEvent(fav, QDragMoveEvent(pos, *args))
    app.sendEvent(fav, QDropEvent(QPointF(pos), *args))
    settle()
    if order().index("bravo") > order().index("delta"):
        PROBLEMS.append(f"dropping bravo above delta in Favorites gave {order()}")

    # -- the star takes it out of Favorites ---------------------------------------------
    star = next(c for c in win.card_lists["G"].section(sections.SCRIPTS).cards
                if c._name == "delta")
    star.fav_button.click()
    settle()
    if names(sections.FAVORITES) != ["pipe-one", "bravo"]:
        PROBLEMS.append(f"unstarring left Favorites as {names(sections.FAVORITES)}")

    # -- search counts items, and shows a favourite in both places ----------------------
    win.search_box.setText("bravo")
    app.processEvents()
    both = [c for c in win._cards if c._name == "bravo"]
    others = [c for c in win._cards if c._name != "bravo"]
    if win.search_hint.text() != "1 of 6" or len(both) != 2 \
            or any(c.isHidden() for c in both) or not all(c.isHidden() for c in others):
        PROBLEMS.append(f"search: hint {win.search_hint.text()!r}, "
                        f"{len(both)} bravo cards")
    win.search_box.clear()

    # -- select mode ticks the group's scripts, not the favourite copies ---------------
    win.set_select_mode(True)
    if len(win.selectable_cards()) != 4:
        PROBLEMS.append(f"select mode offered {len(win.selectable_cards())} cards")
    win.set_select_mode(False)

    print("  [ok] sections: Favorites / Pipelines / Scripts filled and ordered, "
          "empty text, collapse per group kept across reload, moves and drops "
          "among favourites, star, search counts items, select skips copies")
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
    check_drag_and_drop(app)
    check_schedules(app)
    check_context_menus(app)
    check_select_mode(app)
    check_group_management(app)
    check_tray_and_close(app)
    check_updates_and_notify(app)
    check_window_placement(app)
    check_sections_and_favorites(app)
    print()
    if PROBLEMS:
        for p in PROBLEMS:
            print("  PROBLEM:", p)
        return 1
    print("RYOS Qt smoke PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
