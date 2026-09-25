"""The Qt add/edit-script dialog.

Loads and saves through `scriptform.load_form` / `save_form` and validates
with `scriptform.validate` -- the same functions the Tk dialog uses -- so the
two cannot store a script differently. Everything toolkit-shaped is here: the
path row that switches to a relative box when the group has a base folder,
the preset list, and the prompts.

Every prompt goes through an attribute holding the real dialog (`warn`,
`ask_yes_no`, `ask_text`, `ask_file`, `ask_dir`), so a test can answer in its
place.

One Tk behaviour is deliberately not copied: adding a preset while editing
saves the presets, and overwrites the script's parameters, at once -- so
Cancel does not undo it. Here nothing is written until Save.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from .. import scriptform
from .widgets import button_row


class ScriptDialog(QDialog):
    """Add a script, or edit one and its presets."""

    def __init__(self, parent: QWidget | None = None, *, db,
                 script_id: int | None = None, default_group: str = "",
                 on_save: Callable[[], None] | None = None,
                 path_exists: Callable[[str], bool] | None = None):
        super().__init__(parent)
        self.db = db
        self.script_id = script_id
        self._on_save = on_save
        self._path_exists = path_exists or os.path.exists
        self._base_dirs = dict(db.list_groups_with_meta())
        self._base = ""
        self.setWindowTitle("Edit Script" if script_id else "Add Script")

        self.warn: Callable[[str, str], None] = \
            lambda title, text: QMessageBox.warning(self, title, text)
        self.ask_yes_no: Callable[[str, str], bool] = \
            lambda title, text: QMessageBox.question(self, title, text) == \
            QMessageBox.StandardButton.Yes
        self.ask_text: Callable[[str, str, str], str | None] = self._ask_text
        self.ask_file: Callable[[str], str | None] = self._ask_file
        self.ask_dir: Callable[[str], str | None] = self._ask_dir

        col = QVBoxLayout(self)
        form = QFormLayout()
        col.addLayout(form)

        self.e_name = QLineEdit()
        form.addRow(QLabel("Name:"), self.e_name)

        # Absolute path, for a group with no base folder...
        self.e_path = QLineEdit()
        self.abs_row = self._with_button(self.e_path, "Browse…", self.browse)
        form.addRow(QLabel("Path:"), self.abs_row)
        self._abs_label = form.labelForField(self.abs_row)
        # ...or the base folder and a path under it.
        self.base_label = QLabel("")
        self.base_label.setObjectName("cardPath")
        form.addRow(QLabel("Base dir:"), self.base_label)
        self._base_caption = form.labelForField(self.base_label)
        self.e_relpath = QLineEdit()
        self.rel_row = self._with_button(self.e_relpath, "Browse…", self.browse)
        form.addRow(QLabel("Path:"), self.rel_row)
        self._rel_label = form.labelForField(self.rel_row)

        self.e_params = QLineEdit()
        self.e_params.editingFinished.connect(self._name_from_params)
        self.e_params.returnPressed.connect(self.add_preset)
        form.addRow(QLabel("Parameters:"),
                    self._with_button(self.e_params, "+ Preset", self.add_preset))

        self.presets = QListWidget()
        self.presets.setMaximumHeight(90)
        self.presets.itemDoubleClicked.connect(lambda _item: self.use_preset())
        preset_buttons = QHBoxLayout()
        for label, slot in (("← Use", self.use_preset), ("Edit", self.edit_preset),
                            ("Remove", self.remove_preset)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            preset_buttons.addWidget(b)
        preset_buttons.addStretch(1)
        preset_box = QVBoxLayout()
        preset_box.addWidget(self.presets)
        preset_box.addLayout(preset_buttons)
        form.addRow(QLabel("Presets:"), preset_box)

        self.e_interp = QComboBox()
        self.e_interp.setEditable(True)
        self.e_interp.addItems(list(scriptform.INTERPRETER_CHOICES))
        form.addRow(QLabel("Interpreter:"), self.e_interp)
        hint = QLabel(scriptform.INTERPRETER_HINT)
        hint.setObjectName("cardPath")
        form.addRow(QLabel(""), hint)

        self.e_group = QComboBox()
        self.e_group.setEditable(True)
        # Filled before the signal is connected: selecting the first group must
        # not switch the path row before the stored path has been loaded.
        self.e_group.addItems(db.list_groups())
        self.e_group.currentTextChanged.connect(lambda _t: self.refresh_path_inputs())
        form.addRow(QLabel("Group:"), self.e_group)

        self.temp_param = QCheckBox(scriptform.TEMP_PARAM_LABEL)
        self.launcher = QCheckBox(scriptform.LAUNCHER_LABEL)
        form.addRow(QLabel(""), self.temp_param)
        form.addRow(QLabel(""), self.launcher)

        self.e_workdir = QLineEdit()
        form.addRow(QLabel("Working dir:"),
                    self._with_button(self.e_workdir, "Browse", self.browse_workdir))

        self.t_env = QPlainTextEdit()
        self.t_env.setObjectName("output")
        self.t_env.setMaximumHeight(90)
        form.addRow(QLabel("Environment:"), self.t_env)
        env_hint = QLabel(scriptform.ENV_HINT)
        env_hint.setObjectName("cardPath")
        form.addRow(QLabel(""), env_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.delete_button = None
        if script_id:
            self.delete_button = QPushButton("Delete")
            self.delete_button.clicked.connect(self.delete)
        col.addWidget(button_row(buttons, self.delete_button))

        self._load(scriptform.load_form(db, script_id, default_group))

    # -- building ------------------------------------------------------------
    @staticmethod
    def _with_button(edit: QLineEdit, text: str, slot) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(edit, 1)
        button = QPushButton(text)
        button.clicked.connect(slot)
        lay.addWidget(button)
        return row

    def _load(self, form: scriptform.ScriptForm) -> None:
        self.e_name.setText(form.name)
        self.e_path.setText(form.path)
        self.e_params.setText(form.params)
        self.e_interp.setCurrentText(form.interpreter)
        self.temp_param.setChecked(form.temp_param)
        self.launcher.setChecked(form.detached)
        self.e_workdir.setText(form.work_dir)
        self.t_env.setPlainText(form.env_text)
        self._presets = list(form.presets)
        self._fill_presets()
        # Setting the group last converts the path into its relative form.
        self.e_group.setCurrentText(form.group)
        self.refresh_path_inputs()

    # -- the path row --------------------------------------------------------------
    def current_path(self) -> str:
        return scriptform.resolve_path(
            base_dir=self._base, relative=self.e_relpath.text(),
            absolute=self.e_path.text(), use_relative=bool(self._base))

    def refresh_path_inputs(self) -> None:
        """Show the relative box when the group has a base folder, else the
        absolute one, carrying the path across either way."""
        path = self.current_path()
        base = self._base_dirs.get(self.e_group.currentText().strip(), "")
        if base:
            self.e_relpath.setText(scriptform.relative_field(path, base))
            self.e_path.clear()
        else:
            self.e_path.setText(path)
            self.e_relpath.clear()
        self._base = base
        self.base_label.setText(base)
        for w in (self.abs_row, self._abs_label):
            w.setVisible(not base)
        for w in (self.base_label, self._base_caption, self.rel_row, self._rel_label):
            w.setVisible(bool(base))

    def browse(self) -> None:
        path = self.ask_file(self._base)
        if not path:
            return
        if self._base:
            refusal = scriptform.browse_refusal(path, self._base)
            if refusal is not None:
                self.warn(refusal.title, refusal.message)
                return
            self.e_relpath.setText(scriptform.relative_under_base(path, self._base) or "")
        else:
            self.e_path.setText(path)
        if not self.e_name.text().strip():
            self.e_name.setText(scriptform.name_from_path(path))

    def browse_workdir(self) -> None:
        chosen = self.ask_dir(self.e_workdir.text().strip())
        if chosen:
            self.e_workdir.setText(os.path.normpath(chosen))

    def _name_from_params(self) -> None:
        if not self.e_name.text().strip() and self.e_params.text().strip():
            self.e_name.setText(self.e_params.text().strip())

    # -- presets (kept in the dialog until Save) ------------------------------------
    def _fill_presets(self) -> None:
        self.presets.clear()
        self.presets.addItems([label for label, _p in self._presets])

    def preset_params(self) -> list:
        return [p for _label, p in self._presets]

    def add_preset(self) -> None:
        grown = scriptform.with_preset(self._presets, self.e_params.text())
        if grown is not None:
            self._presets = grown
            self._fill_presets()

    def _selected_preset(self) -> int | None:
        row = self.presets.currentRow()
        return row if 0 <= row < len(self._presets) else None

    def use_preset(self) -> None:
        idx = self._selected_preset()
        if idx is not None:
            self.e_params.setText(self._presets[idx][1])

    def edit_preset(self) -> None:
        idx = self._selected_preset()
        if idx is None:
            return
        new = self.ask_text("Preset", "Parameters:", self._presets[idx][1])
        if new and new.strip():
            self._presets[idx] = (new.strip(), new.strip())
            self._fill_presets()
            self.presets.setCurrentRow(idx)

    def remove_preset(self) -> None:
        idx = self._selected_preset()
        if idx is not None:
            del self._presets[idx]
            self._fill_presets()

    # -- saving ----------------------------------------------------------------------
    def check(self) -> scriptform.Check:
        """The verdict on what is currently entered."""
        path = self.current_path()
        return scriptform.validate(
            name=self.e_name.text(), path=path,
            interpreter=self.e_interp.currentText(), base_dir=self._base,
            group_name=self.e_group.currentText().strip(),
            path_exists=bool(path) and self._path_exists(path))

    def form(self) -> scriptform.ScriptForm:
        return scriptform.ScriptForm(
            name=self.e_name.text(), path=self.current_path(),
            params=self.e_params.text(), interpreter=self.e_interp.currentText(),
            group=self.e_group.currentText(),
            temp_param=self.temp_param.isChecked(),
            detached=self.launcher.isChecked(), work_dir=self.e_workdir.text(),
            env_text=self.t_env.toPlainText(), presets=list(self._presets))

    def save(self) -> bool:
        verdict = self.check()
        if verdict.kind == scriptform.REFUSE:
            self.warn(verdict.title, verdict.message)
            return False
        if verdict.needs_confirmation and not self.ask_yes_no(verdict.title,
                                                              verdict.message):
            return False
        self.script_id = scriptform.save_form(self.db, self.script_id, self.form())
        if self._on_save is not None:
            self._on_save()
        self.accept()
        return True

    def delete(self) -> bool:
        if not self.script_id or not self.ask_yes_no(*scriptform.DELETE_PROMPT):
            return False
        self.db.delete(self.script_id)
        if self._on_save is not None:
            self._on_save()
        self.accept()
        return True

    # -- the real prompts -------------------------------------------------------------
    def _ask_text(self, title: str, prompt: str, initial: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, prompt, text=initial)
        return text if ok else None

    def _ask_file(self, start_dir: str) -> str | None:
        path, _filter = QFileDialog.getOpenFileName(self, "Select Script", start_dir)
        return path or None

    def _ask_dir(self, start_dir: str) -> str | None:
        return QFileDialog.getExistingDirectory(self, "Working directory",
                                                start_dir) or None
