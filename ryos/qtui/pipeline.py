"""The Qt pipeline editor.

Everything it shows or decides comes from `ryos.pipelinesteps`, shared with
the Tk editor: row labels and policy marks, the move rules, the policy combo
wording, the trigger toggle, the per-step preset choice, the Add Step list
and the legend. This draws the controls and writes each change to the
database as it is made, as the Tk editor does; Save only renames.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from .. import pipelinesteps

LEGEND = pipelinesteps.LEGEND


class PipelineEditorDialog(QDialog):
    """Rename a pipeline; add, remove, reorder and configure its steps."""

    def __init__(self, parent: QWidget | None = None, *, db, pipeline_id: int,
                 name: str, group: str,
                 on_save: Callable[[], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Pipeline")
        self.db = db
        self.pipeline_id = pipeline_id
        self._on_save = on_save
        self._steps: list = []
        self._filling = False     # set while controls are loaded, not changed
        # Injectable, so the empty-name refusal can be checked without a box.
        self.warn: Callable[[str, str], None] = \
            lambda title, text: QMessageBox.warning(self, title, text)

        col = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(name)
        form.addRow(QLabel("Pipeline Name"), self.name_edit)
        col.addLayout(form)

        col.addWidget(QLabel("Steps"))
        self.list = QListWidget()
        col.addWidget(self.list, 1)

        controls = QHBoxLayout()
        self.up_button = QPushButton("▲ Up")
        self.down_button = QPushButton("▼ Down")
        self.remove_button = QPushButton("✕ Remove")
        self.trigger_button = QPushButton("∥ With Prev")
        for b in (self.up_button, self.down_button, self.remove_button,
                  self.trigger_button):
            controls.addWidget(b)
        controls.addStretch(1)
        col.addLayout(controls)

        legend = QLabel(LEGEND)
        legend.setObjectName("cardPath")
        legend.setWordWrap(True)
        col.addWidget(legend)

        policy = QFormLayout()
        self.on_failure = QComboBox()
        self.on_failure.addItems(list(pipelinesteps.FAIL_LABELS.values()))
        self.retries = QComboBox()
        self.retries.addItems([str(n) for n in pipelinesteps.RETRY_CHOICES])
        self.run_when = QComboBox()
        self.run_when.addItems(list(pipelinesteps.WHEN_LABELS.values()))
        self.preset = QComboBox()
        policy.addRow(QLabel("If it fails:"), self.on_failure)
        policy.addRow(QLabel("Retries:"), self.retries)
        policy.addRow(QLabel("Run this step:"), self.run_when)
        policy.addRow(QLabel("Step preset:"), self.preset)
        col.addLayout(policy)

        col.addWidget(QLabel("Add Step"))
        add_row = QHBoxLayout()
        self.add_combo = QComboBox()
        self._add_choices = pipelinesteps.add_step_choices(db.list_all(), group)
        self.add_combo.addItems(list(self._add_choices))
        self.add_button = QPushButton("Add")
        self.add_button.setObjectName("primary")
        self.add_button.setEnabled(bool(self._add_choices))
        add_row.addWidget(self.add_combo, 1)
        add_row.addWidget(self.add_button)
        col.addLayout(add_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

        self.up_button.clicked.connect(lambda: self.move_step(-1))
        self.down_button.clicked.connect(lambda: self.move_step(+1))
        self.remove_button.clicked.connect(self.remove_selected)
        self.trigger_button.clicked.connect(self.toggle_trigger)
        self.add_button.clicked.connect(self.add_step)
        for combo in (self.on_failure, self.retries, self.run_when):
            combo.currentIndexChanged.connect(self._policy_changed)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.list.currentRowChanged.connect(self._on_selection)
        self.reload()

    # -- the list ----------------------------------------------------------
    def reload(self, select: int | None = None) -> None:
        """Re-read the steps and refill the list, selecting ``select``."""
        keep = self.list.currentRow() if select is None else select
        self._steps = list(self.db.list_pipeline_steps(self.pipeline_id))
        self._filling = True
        try:
            self.list.clear()
            self.list.addItems(pipelinesteps.step_labels(self._steps))
        finally:
            self._filling = False
        self.list.setCurrentRow(keep if 0 <= keep < self.list.count() else -1)
        self._on_selection(self.list.currentRow())

    def selected_index(self) -> int | None:
        row = self.list.currentRow()
        return row if 0 <= row < len(self._steps) else None

    def _on_selection(self, row: int) -> None:
        if self._filling:
            return
        idx = self.selected_index()
        has = idx is not None
        count = len(self._steps)
        self.up_button.setEnabled(pipelinesteps.can_move(idx, count, -1))
        self.down_button.setEnabled(pipelinesteps.can_move(idx, count, +1))
        self.remove_button.setEnabled(has)
        self.trigger_button.setEnabled(
            not pipelinesteps.first_step_cannot_run_with_previous(idx))
        for combo in (self.on_failure, self.retries, self.run_when):
            combo.setEnabled(has)
        self._filling = True
        try:
            self.preset.clear()
            if idx is None:
                self.trigger_button.setText("∥ With Prev")
                self.preset.setEnabled(False)
                return
            step = self._steps[idx]
            on_failure, retries, run_when = pipelinesteps.policy_of(step)
            self.on_failure.setCurrentText(pipelinesteps.FAIL_LABELS[on_failure])
            self.retries.setCurrentText(str(retries))
            self.run_when.setCurrentText(pipelinesteps.WHEN_LABELS[run_when])
            self.trigger_button.setText(pipelinesteps.trigger_button_label(step))
            presets = self.db.list_param_presets(step[1])
            choices = pipelinesteps.preset_choices(presets)
            self.preset.addItems(choices)
            self.preset.setCurrentText(pipelinesteps.preset_shown(step[6], choices))
            self.preset.setEnabled(bool(presets))
        finally:
            self._filling = False

    # -- changes, each written as it is made --------------------------------------
    def move_step(self, delta: int) -> None:
        # Not `move`: that would override QWidget.move(x, y), which positions
        # the window.
        idx = self.selected_index()
        if idx is None or not pipelinesteps.can_move(idx, len(self._steps), delta):
            return
        ids = pipelinesteps.reorder([s[0] for s in self._steps], idx, delta)
        self.db.reorder_pipeline_steps(self.pipeline_id, ids)
        self.reload(select=idx + delta)

    def remove_selected(self) -> None:
        idx = self.selected_index()
        if idx is None:
            return
        self.db.remove_pipeline_step(self._steps[idx][0])
        self.reload(select=-1)

    def toggle_trigger(self) -> None:
        idx = self.selected_index()
        if idx is None or pipelinesteps.first_step_cannot_run_with_previous(idx):
            return
        self.db.set_step_trigger_mode(self._steps[idx][0],
                                      pipelinesteps.toggled_trigger(self._steps[idx]))
        self.reload(select=idx)

    def add_step(self) -> None:
        script_id = self._add_choices.get(self.add_combo.currentText())
        if script_id is None:
            return
        self.db.add_pipeline_step(self.pipeline_id, script_id)
        self.reload(select=len(self._steps))       # the new, last row

    def _policy_changed(self, _index: int) -> None:
        idx = self.selected_index()
        if self._filling or idx is None:
            return
        self.db.set_step_policy(
            self._steps[idx][0],
            **pipelinesteps.policy_from_labels(self.on_failure.currentText(),
                                               self.retries.currentText(),
                                               self.run_when.currentText()))
        self.reload(select=idx)

    def _preset_changed(self, _index: int) -> None:
        idx = self.selected_index()
        if self._filling or idx is None:
            return
        self.db.update_pipeline_step_params(
            self._steps[idx][0],
            pipelinesteps.override_from_choice(self.preset.currentText()))
        self.reload(select=idx)

    def save(self) -> bool:
        """Rename and close. The steps were saved as they changed."""
        name = self.name_edit.text().strip()
        if not name:
            self.warn(*pipelinesteps.NAME_REQUIRED)
            return False
        self.db.rename_pipeline(self.pipeline_id, name)
        if self._on_save is not None:
            self._on_save()
        self.accept()
        return True
