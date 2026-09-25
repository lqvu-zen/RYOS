"""The remaining Qt dialogs: groups, parameters, the tray prompt, history, schedules.

Each mirrors its Tk counterpart in `ui/dialogs.py` and keeps the same result
contract, so the shell can swap one for the other without changing a caller:

* ``result is None`` means cancelled.
* Anything else is the answer — a name and folder, a path (``""`` meaning
  "clear it"), a parameter string, or an outcome word.

The decisions live in toolkit-free modules shared with the Tk dialogs —
`grouping.validate_group_name`, `scriptform.param_options`, `history`, and
`scheduleform` — so none of these widgets decides anything on its own.

Every dialog exposes the method its OK button calls (``accept_form()`` and
friends), so tests can drive the real validation path without ``exec()``,
which would block waiting for a click.
"""

from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import history, scheduleform, scriptform
from ..grouping import validate_group_name
from ..scheduling import DAILY, INTERVAL, WEEKLY, next_occurrence, normalize_spec

# Outcomes of the close-to-tray prompt, matching the Tk dialog's strings.
TRAY = "tray"
QUIT = "quit"
CANCEL = "cancel"


def _warn(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def _ok_cancel(parent: QDialog, on_ok: Callable[[], None]) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(on_ok)
    buttons.rejected.connect(parent.reject)
    return buttons


# --- groups -------------------------------------------------------------------

class NewGroupDialog(QDialog):
    """Name a new group, optionally with a base folder.

    ``result`` is ``(name, base_dir)`` on OK. Validation is
    `grouping.validate_group_name`, shared with the rename and clone paths.
    """

    def __init__(self, parent: QWidget | None = None, *, existing=()):
        super().__init__(parent)
        self.setWindowTitle("New Group")
        self.result: tuple[str, str] | None = None
        self._existing = list(existing)

        form = QFormLayout(self)
        self.e_name = QLineEdit()
        self.e_dir = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.e_dir, 1)
        row.addWidget(browse)
        form.addRow(QLabel("Name"), self.e_name)
        form.addRow(QLabel("Base folder (optional)"), row)
        form.addRow(_ok_cancel(self, self.accept_form))

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Base folder",
                                                  self.e_dir.text())
        if chosen:
            self.e_dir.setText(chosen)

    def problem(self) -> str | None:
        """Why the name cannot be used, or None."""
        return validate_group_name(self.e_name.text(), self._existing)

    def accept_form(self) -> bool:
        issue = self.problem()
        if issue:
            _warn(self, "New Group", issue)
            return False
        self.result = (self.e_name.text().strip(), self.e_dir.text().strip())
        self.accept()
        return True


class GroupBaseDirDialog(QDialog):
    """Set, change or clear a group's base folder.

    ``result`` is the new path, ``""`` to clear it, or None when cancelled --
    the same three-way contract as the Tk dialog, which is why "Clear" is its
    own button rather than an empty field: an empty field and a cancelled
    dialog must not be confused.
    """

    def __init__(self, parent: QWidget | None = None, *, group_name: str,
                 current_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Base folder — {group_name}")
        self.result: str | None = None

        col = QVBoxLayout(self)
        col.addWidget(QLabel(
            "Scripts under this folder are stored relative to it, so the "
            "group can move with them."))
        row = QHBoxLayout()
        self.e_dir = QLineEdit(current_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.e_dir, 1)
        row.addWidget(browse)
        col.addLayout(row)

        buttons = _ok_cancel(self, self.accept_form)
        clear = buttons.addButton("Clear",
                                  QDialogButtonBox.ButtonRole.ResetRole)
        clear.clicked.connect(self.clear)
        col.addWidget(buttons)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Base folder",
                                                  self.e_dir.text())
        if chosen:
            self.e_dir.setText(chosen)

    def clear(self) -> None:
        self.result = ""
        self.accept()

    def accept_form(self) -> bool:
        self.result = self.e_dir.text().strip()
        self.accept()
        return True


# --- parameters ---------------------------------------------------------------

class ParamPickerDialog(QDialog):
    """Pick which saved parameter set to run with.

    Options come from `scriptform.param_options`, so the list reads the same
    as the Tk picker, including showing a preset's parameters once when its
    label is just its parameters.
    """

    def __init__(self, parent: QWidget | None = None, *, script_name: str,
                 default_params: str, presets):
        super().__init__(parent)
        self.setWindowTitle(f"Run {script_name} with…")
        self.result: str | None = None
        self._options = scriptform.param_options(default_params, presets)

        col = QVBoxLayout(self)
        col.addWidget(QLabel("Select parameters"))
        self._group = QButtonGroup(self)
        self.radios: list[QRadioButton] = []
        for i, (_key, label, _params) in enumerate(self._options):
            radio = QRadioButton(label or "(none)")
            self._group.addButton(radio, i)
            self.radios.append(radio)
            col.addWidget(radio)
        if self.radios:
            self.radios[0].setChecked(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        run = buttons.addButton("Run", QDialogButtonBox.ButtonRole.AcceptRole)
        run.clicked.connect(self.accept_form)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    def select(self, index: int) -> None:
        self.radios[index].setChecked(True)

    def accept_form(self) -> bool:
        idx = self._group.checkedId()
        if idx < 0:
            return False
        self.result = self._options[idx][2]
        self.accept()
        return True


class PresetEntryDialog(QDialog):
    """Enter the parameters for a saved preset. They may not be empty."""

    def __init__(self, parent: QWidget | None = None, *, params: str = "",
                 title: str = "Preset"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.result: str | None = None
        form = QFormLayout(self)
        self.e_params = QLineEdit(params)
        form.addRow(QLabel("Parameters"), self.e_params)
        form.addRow(_ok_cancel(self, self.accept_form))

    def accept_form(self) -> bool:
        params = self.e_params.text().strip()
        if not params:
            # A preset with no parameters is just "Default" again.
            _warn(self, "Required", "Please enter parameters.")
            return False
        self.result = params
        self.accept()
        return True


class TempParamDialog(QDialog):
    """An extra parameter for one run, appended to the saved ones.

    ``result`` is what was typed (empty is allowed: run with the saved
    parameters alone), or None when cancelled. As in the Tk prompt, the saved
    parameters are shown, not put in the box: the answer is appended to them
    by `scriptform.with_temp_param`, so pre-filling them would pass them twice.
    """

    def __init__(self, parent: QWidget | None = None, *, saved_params: str = "",
                 title: str = "Temporary Parameter"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.result: str | None = None
        form = QFormLayout(self)
        saved = scriptform.saved_params_line(saved_params)
        if saved:
            self.saved_label = QLabel(saved)
            self.saved_label.setObjectName("cardPath")
            form.addRow(self.saved_label)
        self.e_params = QLineEdit()
        form.addRow(QLabel("Temp param:"), self.e_params)
        hint = QLabel(scriptform.TEMP_PARAM_HINT)
        hint.setObjectName("cardPath")
        form.addRow(hint)
        form.addRow(_ok_cancel(self, self.accept_form))

    def accept_form(self) -> bool:
        self.result = self.e_params.text().strip()
        self.accept()
        return True


# --- the tray prompt -----------------------------------------------------------

class CloseToTrayPromptDialog(QDialog):
    """Asked on close when the tray is available: minimise, quit, or stay.

    ``result`` is ``"tray"``, ``"quit"`` or ``"cancel"``, and ``dont_ask``
    carries the checkbox -- the same shape as the Tk dialog. Closing the
    window any other way is "cancel", never "quit": an accidental dismiss
    must not end the app and every running job with it.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Minimize to tray instead?")
        self.result = CANCEL
        self.dont_ask = False

        col = QVBoxLayout(self)
        body = QLabel("RYOS can keep running in the system tray instead of "
                      "closing, so scheduled runs and running jobs carry on.")
        body.setWordWrap(True)
        col.addWidget(body)
        self.remember = QCheckBox("Don't ask me again")
        col.addWidget(self.remember)

        row = QHBoxLayout()
        row.addStretch(1)
        self.quit_button = QPushButton("Quit")
        self.tray_button = QPushButton("Minimize to tray")
        self.tray_button.setObjectName("primary")
        self.tray_button.setDefault(True)
        row.addWidget(self.quit_button)
        row.addWidget(self.tray_button)
        col.addLayout(row)

        self.tray_button.clicked.connect(lambda: self.choose(TRAY))
        self.quit_button.clicked.connect(lambda: self.choose(QUIT))

    def choose(self, outcome: str) -> None:
        self.result = outcome
        self.dont_ask = self.remember.isChecked()
        self.accept()

    def reject(self) -> None:          # Esc, the close box, anything else
        self.result = CANCEL
        self.dont_ask = False
        super().reject()


# --- run history ---------------------------------------------------------------

class RunHistoryDialog(QDialog):
    """The recorded runs for one script or pipeline, newest first.

    Rows are formatted by `history.format_run_row` under `history.header_row`,
    the same fixed-width columns as the Tk dialog, in a monospaced box so they
    line up.
    """

    def __init__(self, parent: QWidget | None = None, *, db,
                 script_id: int | None = None, pipeline_id: int | None = None,
                 title: str = "", limit: int = 200):
        super().__init__(parent)
        self.setWindowTitle(f"Run history — {title}" if title else "Run history")
        self.db = db
        self._script_id = script_id
        self._pipeline_id = pipeline_id
        self._limit = limit

        col = QVBoxLayout(self)
        self.summary = QLabel("")
        self.summary.setObjectName("cardPath")
        col.addWidget(self.summary)
        self.table = QPlainTextEdit()
        self.table.setObjectName("output")
        self.table.setReadOnly(True)
        self.table.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        col.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.clear_button = buttons.addButton(
            "Clear history", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.clear_button.clicked.connect(self._confirm_clear)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self.resize(640, 420)
        self.reload()

    def rows(self) -> list:
        return list(self.db.list_runs(script_id=self._script_id,
                                      pipeline_id=self._pipeline_id,
                                      limit=self._limit))

    def reload(self) -> None:
        rows = self.rows()
        self.summary.setText(history.summarize(rows))
        lines = [history.header_row()] + [history.format_run_row(r) for r in rows]
        self.table.setPlainText("\n".join(lines) if rows else "No runs recorded yet.")
        self.clear_button.setEnabled(bool(rows))

    def _confirm_clear(self) -> None:
        answer = QMessageBox.question(
            self, "Clear history", "Delete every recorded run shown here?")
        if answer == QMessageBox.StandardButton.Yes:
            self.clear()

    def clear(self) -> int:
        """Delete this item's history. Never clears everyone's by accident."""
        if self._script_id is None and self._pipeline_id is None:
            return 0
        removed = self.db.clear_runs(script_id=self._script_id,
                                     pipeline_id=self._pipeline_id)
        self.reload()
        return removed


# --- schedules -----------------------------------------------------------------

class ScheduleDialog(QDialog):
    """Create, edit or remove the recurring schedule for one script or pipeline.

    Loads through `scheduleform.form_values`, builds its spec with
    `scheduleform.raw_spec`, and previews with `scheduleform.preview_lines` —
    the same functions the Tk dialog uses, so the next-runs list here is what
    will actually happen.
    """

    def __init__(self, parent: QWidget | None = None, *, db,
                 script_id: int | None = None, pipeline_id: int | None = None,
                 title: str = "", on_save: Callable[[], None] | None = None,
                 ask_login: Callable[[], bool] | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Schedule — {title}" if title else "Schedule")
        # The run-at-login question; injectable so saving an enabled schedule
        # can be tested without a modal box blocking the run.
        self._ask_login = ask_login
        self.db = db
        self._script_id = script_id
        self._pipeline_id = pipeline_id
        self._on_save = on_save
        self._existing = db.get_schedule(script_id=script_id,
                                         pipeline_id=pipeline_id)
        values = scheduleform.form_values(self._existing)

        col = QVBoxLayout(self)
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(values["enabled"])
        col.addWidget(self.enabled)

        self.mode = QComboBox()
        self.mode.addItem("Every N minutes", INTERVAL)
        self.mode.addItem("Every day at", DAILY)
        self.mode.addItem("On chosen days at", WEEKLY)
        self.mode.setCurrentIndex(self.mode.findData(values["mode"]))
        col.addWidget(self.mode)

        self.pages = QStackedWidget()
        # interval
        interval = QWidget()
        irow = QHBoxLayout(interval)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 7 * 24 * 60)
        self.minutes.setValue(_int_or(values["minutes"], 30))
        irow.addWidget(QLabel("Every"))
        irow.addWidget(self.minutes)
        irow.addWidget(QLabel("minutes"))
        irow.addStretch(1)
        self.pages.addWidget(interval)
        # daily and weekly share the time box, so it is built once
        timed = QWidget()
        tcol = QVBoxLayout(timed)
        trow = QHBoxLayout()
        self.at = QLineEdit(values["at"])
        self.at.setPlaceholderText("09:00")
        trow.addWidget(QLabel("At"))
        trow.addWidget(self.at)
        trow.addStretch(1)
        tcol.addLayout(trow)
        self.day_boxes: list[QCheckBox] = []
        drow = QHBoxLayout()
        for i, name in enumerate(scheduleform.DAY_NAMES):
            box = QCheckBox(name)
            box.setChecked(i in values["days"])
            self.day_boxes.append(box)
            drow.addWidget(box)
        self._days_row = QWidget()
        self._days_row.setLayout(drow)
        tcol.addWidget(self._days_row)
        self.pages.addWidget(timed)
        col.addWidget(self.pages)

        crow = QHBoxLayout()
        crow.addWidget(QLabel("If RYOS was closed when a run was due:"))
        self.catch_up = QComboBox()
        for key, label in scheduleform.CATCH_UP_LABELS.items():
            self.catch_up.addItem(label, key)
        self.catch_up.setCurrentIndex(self.catch_up.findData(values["catch_up"]))
        crow.addWidget(self.catch_up)
        col.addLayout(crow)

        col.addWidget(QLabel("Next runs"))
        self.preview = QLabel("")
        self.preview.setObjectName("cardPath")
        self.preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.remove_button = buttons.addButton(
            "Remove schedule", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.remove_button.setEnabled(self._existing is not None)
        self.remove_button.clicked.connect(self.remove)
        buttons.accepted.connect(self.accept_form)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

        for signal in (self.mode.currentIndexChanged, self.minutes.valueChanged,
                       self.at.textChanged):
            signal.connect(self.refresh)
        for box in self.day_boxes:
            box.toggled.connect(self.refresh)
        self.refresh()

    # -- the form ----------------------------------------------------------
    def current_mode(self) -> str:
        return self.mode.currentData()

    def current_spec(self):
        """(spec_type, normalised spec) for the form; spec is None if invalid."""
        mode = self.current_mode()
        raw = scheduleform.raw_spec(
            mode, minutes=str(self.minutes.value()), at=self.at.text(),
            days=[i for i, b in enumerate(self.day_boxes) if b.isChecked()])
        return mode, normalize_spec(mode, raw)

    def refresh(self, *_args) -> None:
        mode = self.current_mode()
        self.pages.setCurrentIndex(0 if mode == INTERVAL else 1)
        self._days_row.setVisible(mode == WEEKLY)
        spec_type, spec = self.current_spec()
        lines = scheduleform.preview_lines(spec_type, spec)
        self.preview.setText("\n".join(lines) if spec is not None
                             else "—  check the values above")

    # -- saving ------------------------------------------------------------
    def accept_form(self) -> bool:
        spec_type, spec = self.current_spec()
        check = scheduleform.check(spec)
        if not check.ok:
            _warn(self, check.title, check.message)
            return False
        kwargs = dict(spec_type=spec_type, spec=json.dumps(spec),
                      catch_up=self.catch_up.currentData(),
                      enabled=self.enabled.isChecked(),
                      next_run_at=next_occurrence(spec_type, spec,
                                                  _now()))
        if self._existing:
            self.db.update_schedule(self._existing[0], **kwargs)
        else:
            kind = "pipeline" if self._pipeline_id is not None else "script"
            self.db.add_schedule(kind, script_id=self._script_id,
                                 pipeline_id=self._pipeline_id, **kwargs)
        if kwargs["enabled"]:
            self.offer_run_at_login(ask=self._ask_login)
        if self._on_save is not None:
            self._on_save()
        self.accept()
        return True

    def offer_run_at_login(self, *, ask: Callable[[], bool] | None = None,
                           platform: str | None = None,
                           startup_enabled: bool | None = None,
                           enable: Callable[[bool], None] | None = None) -> bool:
        """Offer to start RYOS at login. True when it was switched on.

        Every side effect is injectable -- the question, the platform, the
        current registry state and the write -- so the rule can be exercised
        without a modal box or a Windows registry.
        """
        import sys as _sys

        from .. import startup
        plat = platform if platform is not None else _sys.platform
        if startup_enabled is None:
            try:
                startup_enabled = startup._startup_enabled()
            except OSError:
                startup_enabled = False
        if not scheduleform.should_offer_run_at_login(
                enabled=True, platform=plat, startup_enabled=startup_enabled):
            return False
        prompt = scheduleform.RUN_AT_LOGIN
        if ask is None:
            def ask() -> bool:
                return QMessageBox.question(
                    self, prompt.title, prompt.message
                ) == QMessageBox.StandardButton.Yes
        if not ask():
            return False
        try:
            (enable or startup._set_startup)(True)
        except OSError:
            _warn(self, "Could not change startup",
                  "RYOS could not update the startup setting.")
            return False
        return True

    def remove(self) -> None:
        if self._existing:
            self.db.delete_schedule(self._existing[0])
        if self._on_save is not None:
            self._on_save()
        self.accept()


def _int_or(value, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _now():
    from datetime import datetime
    return datetime.now()
