"""Qt dialogs.

The options dialog is the reason this file is short. Its Tk counterpart is 761
lines: five hand-built tabs and a `_save` that reads each control back by name.
Here the form is **generated** from `ryos.settings_schema` — add a field to the
schema and it appears, with its bounds and its help text, in both front-ends.

`ScriptDialog` asks `ryos.scriptform` the same questions the Tk one does, and
renders the answer with Qt's message boxes.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import scriptform, settings_schema
from ..settings_schema import BOOL, CHOICE, INT, LIST

# Spin boxes need an upper bound; Qt's default of 99 would silently cap
# "maximum output lines" at two digits. Nothing in the schema is legitimately
# larger than this.
_SPIN_MAX = 1_000_000


class _FieldRow:
    """One schema field bound to the widget that edits it."""

    def __init__(self, spec: settings_schema.Field, widget: QWidget):
        self.spec = spec
        self.widget = widget

    def value(self):
        """The raw value, ready for `settings_schema.coerce`."""
        w = self.widget
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QSpinBox):
            return w.value()
        if isinstance(w, QComboBox):
            return w.currentText()
        return w.text()

    def set_value(self, value) -> None:
        w = self.widget
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QSpinBox):
            w.setValue(int(value or 0))
        elif isinstance(w, QComboBox):
            idx = w.findText(str(value))
            w.setCurrentIndex(max(0, idx))
        else:
            w.setText("" if value is None else str(value))


def build_field(spec: settings_schema.Field) -> QWidget:
    """The control for one field, chosen by its kind."""
    if spec.kind == BOOL:
        box = QCheckBox(spec.label)
        return box
    if spec.kind == INT:
        spin = QSpinBox()
        spin.setMinimum(spec.minimum if spec.minimum is not None else -_SPIN_MAX)
        spin.setMaximum(spec.maximum if spec.maximum is not None else _SPIN_MAX)
        return spin
    if spec.kind == CHOICE:
        combo = QComboBox()
        combo.addItems([str(c) for c in spec.choices])
        return combo
    if spec.kind == LIST:
        # Comma-separated, which is how the Tk tab presents it too.
        return QLineEdit()
    return QLineEdit()


class OptionsDialog(QDialog):
    """The settings dialog, generated from the schema.

    Nothing here knows what any individual setting means: the tabs, the
    controls, the bounds and the help text all come from
    `settings_schema.FIELDS`, and everything is coerced back through
    `settings_schema.coerce` — the same function the Tk dialog uses, so the
    two cannot disagree about what an empty box means.
    """

    def __init__(self, settings: dict, parent: QWidget | None = None,
                 on_save: Callable[[dict], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Options")
        self._settings = dict(settings)
        self._on_save = on_save
        self._rows: dict[str, _FieldRow] = {}

        col = QVBoxLayout(self)
        self.tabs = QTabWidget()
        for tab_name in settings_schema.TABS:
            fields = settings_schema.fields_for(tab_name)
            if not fields:
                continue
            self.tabs.addTab(self._build_tab(fields), tab_name)
        col.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    def _build_tab(self, fields) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        for spec in fields:
            widget = build_field(spec)
            row = _FieldRow(spec, widget)
            self._rows[spec.key] = row
            row.set_value(self._current(spec))
            if spec.help:
                widget.setToolTip(spec.help)
            if spec.kind == BOOL:
                # The checkbox carries its own label; a second one would
                # read as a heading for a control that already says it.
                form.addRow(widget)
            else:
                form.addRow(QLabel(spec.label), widget)
        return page

    def _current(self, spec: settings_schema.Field):
        value = self._settings.get(spec.key, spec.default)
        if spec.kind == LIST and isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        return value

    # -- saving ------------------------------------------------------------
    def values(self) -> dict:
        """Every field, coerced. Safe to merge straight into settings."""
        out = {}
        for key, row in self._rows.items():
            raw = row.value()
            if row.spec.kind == LIST:
                raw = [p.strip() for p in str(raw).split(",") if p.strip()]
            out[key] = settings_schema.coerce(key, raw)
        return out

    def save(self) -> None:
        self._settings.update(self.values())
        if self._on_save is not None:
            self._on_save(self._settings)
        self.accept()


class ScriptDialog(QDialog):
    """Add or edit one script.

    The rules are `ryos.scriptform`'s, shared with the Tk dialog; this only
    collects the fields and renders the verdict.
    """

    def __init__(self, parent: QWidget | None = None, *, name: str = "",
                 path: str = "", params: str = "", interpreter: str = "",
                 group_name: str = "", base_dir: str = "",
                 path_exists: Callable[[str], bool] | None = None,
                 on_save: Callable[[dict], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Script" if name else "Add Script")
        self._base_dir = base_dir
        self._group_name = group_name
        self._on_save = on_save
        self._path_exists = path_exists or (lambda p: True)

        form = QFormLayout(self)
        self.e_name = QLineEdit(name)
        self.e_path = QLineEdit(path)
        self.e_params = QLineEdit(params)
        self.e_interp = QLineEdit(interpreter)
        form.addRow(QLabel("Name"), self.e_name)
        form.addRow(QLabel("Path"), self.e_path)
        form.addRow(QLabel("Parameters"), self.e_params)
        form.addRow(QLabel("Interpreter"), self.e_interp)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def check(self) -> scriptform.Check:
        """The verdict on what is currently entered."""
        path = self.e_path.text().strip()
        return scriptform.validate(
            name=self.e_name.text(), path=path,
            interpreter=self.e_interp.text(), base_dir=self._base_dir,
            group_name=self._group_name,
            path_exists=bool(path) and self._path_exists(path))

    def save(self) -> None:
        verdict = self.check()
        if verdict.kind == scriptform.REFUSE:
            icon = (QMessageBox.Icon.Warning if verdict.severity == "warning"
                    else QMessageBox.Icon.Critical)
            box = QMessageBox(icon, verdict.title, verdict.message,
                              QMessageBox.StandardButton.Ok, self)
            box.exec()
            return
        if verdict.needs_confirmation:
            answer = QMessageBox.question(
                self, verdict.title, verdict.message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if self._on_save is not None:
            self._on_save({
                "name": self.e_name.text().strip(),
                "path": self.e_path.text().strip(),
                "params": self.e_params.text().strip(),
                "interpreter": self.e_interp.text().strip(),
                "group_name": self._group_name,
            })
        self.accept()


class ConfirmDialog(QDialog):
    """A yes/no prompt with a remembered "don't ask again" box.

    The Tk CloseToTrayPromptDialog in miniature; the pattern is the same
    wherever a confirmation can be suppressed.
    """

    def __init__(self, title: str, message: str, parent: QWidget | None = None,
                 remember_label: str = "Don't ask again"):
        super().__init__(parent)
        self.setWindowTitle(title)
        col = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        col.addWidget(label)
        self.remember = QCheckBox(remember_label)
        col.addWidget(self.remember)
        row = QHBoxLayout()
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes
                                   | QDialogButtonBox.StandardButton.No)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        col.addLayout(row)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

    @property
    def remembered(self) -> bool:
        return self.remember.isChecked()
