"""The Qt Appearance dialog: theme, custom themes, and the accent colour.

The Tk options dialog has this as its Appearance tab; the Qt options form is
generated from `settings_schema`, which holds settings, not a theme gallery,
so this is its own dialog under Options. Every rule -- which theme a name
means, the accent swatch, the names a theme may take, saving and deleting
custom themes -- is `themes` / `themeform`, shared with Tk.

Changes preview live through ``on_preview(subset)``; Cancel previews the
subset the dialog opened with, and Save hands the final subset back through
``on_save``. Custom themes are written to ``themes_dir`` as they are created,
edited, deleted or imported, as in Tk; ``on_customs(table)`` reports each new
table so the window can resolve them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from .. import themeform
from ..themes import export_theme, import_theme, theme_choices
from .theme_editor import ThemeEditorDialog


class AppearanceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, settings: dict,
                 customs: dict, themes_dir,
                 on_preview: Callable[[dict], None] | None = None,
                 on_save: Callable[[dict], None] | None = None,
                 on_customs: Callable[[dict], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Appearance")
        self._theme = settings.get("theme", "light")
        self._accent = settings.get("accent_color")
        self._themes_dir = Path(themes_dir)
        self._customs = dict(customs)
        self._on_preview = on_preview or (lambda _s: None)
        self._on_save = on_save or (lambda _s: None)
        self._on_customs = on_customs or (lambda _c: None)
        self._original = self.subset()
        # The dialogs this opens, and its questions, are injectable.
        self.run_editor: Callable[[QDialog], None] = lambda dlg: dlg.exec()
        self.ask_color: Callable[[str], str | None] = self._ask_color
        self.ask_yes_no: Callable[[str, str], bool] = \
            lambda title, text: QMessageBox.question(self, title, text) == \
            QMessageBox.StandardButton.Yes
        self.warn: Callable[[str, str], None] = \
            lambda title, text: QMessageBox.warning(self, title, text)
        self.ask_save_path: Callable[[str], str | None] = self._ask_save_path
        self.ask_open_path: Callable[[], str | None] = self._ask_open_path
        self.ask_dir: Callable[[str], str | None] = self._ask_dir

        col = QVBoxLayout(self)
        col.addWidget(QLabel("THEME"))
        self.theme_combo = QComboBox()
        self.theme_combo.currentIndexChanged.connect(self._on_pick)
        col.addWidget(self.theme_combo)

        actions = QHBoxLayout()
        self.create_button = QPushButton("Create…")
        self.edit_button = QPushButton("Edit…")
        self.delete_button = QPushButton("Delete")
        self.export_button = QPushButton("Export…")
        self.import_button = QPushButton("Import…")
        for b, slot in ((self.create_button, self.create_theme),
                        (self.edit_button, self.edit_theme),
                        (self.delete_button, self.delete_theme),
                        (self.export_button, self.export_theme),
                        (self.import_button, self.import_theme)):
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        col.addLayout(actions)

        col.addWidget(QLabel("Themes folder (drop .json files here)"))
        folder = QHBoxLayout()
        self.folder_label = QLabel(str(self._themes_dir))
        self.folder_label.setObjectName("cardPath")
        folder.addWidget(self.folder_label, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_folder)
        open_folder = QPushButton("Open")
        open_folder.clicked.connect(self._open_folder)
        folder.addWidget(browse)
        folder.addWidget(open_folder)
        col.addLayout(folder)

        col.addWidget(QLabel("ACCENT COLOR"))
        accent = QHBoxLayout()
        self.accent_swatch = QLabel()
        self.accent_swatch.setFixedSize(32, 22)
        accent.addWidget(self.accent_swatch)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.pick_accent)
        reset = QPushButton("Reset")
        reset.clicked.connect(self.reset_accent)
        accent.addWidget(choose)
        accent.addWidget(reset)
        accent.addStretch(1)
        col.addLayout(accent)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self._fill_themes()

    # -- state -----------------------------------------------------------------------
    def subset(self) -> dict:
        return {"theme": self._theme, "accent_color": self._accent,
                "themes_dir": str(self._themes_dir)}

    @property
    def theme(self) -> str:
        return self._theme

    def _fill_themes(self) -> None:
        self._choices = theme_choices(self._customs)
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItems([label for _id, label in self._choices])
        ids = [tid for tid, _ in self._choices]
        self.theme_combo.setCurrentIndex(ids.index(self._theme) if self._theme in ids else 0)
        self.theme_combo.blockSignals(False)
        self._sync()

    def _sync(self) -> None:
        custom = themeform.is_custom(self._theme, self._customs)
        for b in (self.edit_button, self.delete_button, self.export_button):
            b.setEnabled(custom)
        color = themeform.accent_shown(self._theme, self._accent, self._customs)
        self.accent_swatch.setStyleSheet(
            f"background: {color}; border: 1px solid #808080;")

    def select_theme(self, theme_id: str) -> None:
        self._theme = theme_id
        self._fill_themes()
        self._on_preview(self.subset())

    def _on_pick(self, index: int) -> None:
        if 0 <= index < len(self._choices):
            self.select_theme(self._choices[index][0])

    def _customs_changed(self, table: dict) -> None:
        self._customs = dict(table)
        self._on_customs(self._customs)

    # -- custom themes -------------------------------------------------------------------
    def create_theme(self) -> None:
        self.run_editor(ThemeEditorDialog(
            self, seed=themeform.current_seed(self._theme, self._customs),
            taken_names=themeform.taken_names(self._customs),
            on_save=self._saved))

    def edit_theme(self) -> None:
        if not themeform.is_custom(self._theme, self._customs):
            return
        old = self._theme
        self.run_editor(ThemeEditorDialog(
            self, seed=self._customs[old], name=old,
            taken_names=themeform.taken_names(self._customs, exclude=old),
            on_save=lambda name, seed: self._saved(name, seed, replacing=old)))

    def _saved(self, name: str, seed: dict, replacing: str | None = None) -> None:
        self._customs_changed(themeform.save_theme(self._themes_dir, name, seed,
                                                   replacing))
        self.select_theme(name)

    def delete_theme(self) -> None:
        name = self._theme
        if not themeform.is_custom(name, self._customs):
            return
        if not self.ask_yes_no(*themeform.delete_prompt(name)):
            return
        self._customs_changed(themeform.delete_theme(self._themes_dir, name))
        self.select_theme("light")

    def export_theme(self) -> None:
        name = self._theme
        if not themeform.is_custom(name, self._customs):
            return
        path = self.ask_save_path(f"{name}.json")
        if not path:
            return
        try:
            export_theme(name, self._customs[name], path)
        except OSError as exc:
            self.warn("Export theme", f"Could not write file:\n{exc}")

    def import_theme(self) -> None:
        path = self.ask_open_path()
        if not path:
            return
        try:
            name, seed = import_theme(path)
        except ValueError as exc:
            self.warn("Import theme", str(exc))
            return
        name = themeform.unique_theme_name(name or Path(path).stem,
                                           themeform.taken_names(self._customs))
        self._saved(name, seed)

    def browse_folder(self) -> None:
        chosen = self.ask_dir(str(self._themes_dir))
        if not chosen:
            return
        from ..themes import load_user_themes
        self._themes_dir = Path(chosen)
        self.folder_label.setText(chosen)
        self._customs_changed(load_user_themes(self._themes_dir))
        self._fill_themes()
        self._on_preview(self.subset())

    # -- accent ------------------------------------------------------------------------
    def pick_accent(self) -> None:
        picked = self.ask_color(themeform.accent_shown(self._theme, self._accent,
                                                       self._customs))
        if picked:
            self._accent = picked.lower()
            self._sync()
            self._on_preview(self.subset())

    def reset_accent(self) -> None:
        self._accent = None
        self._sync()
        self._on_preview(self.subset())

    # -- closing -----------------------------------------------------------------------
    def save(self) -> None:
        self._on_save(self.subset())
        self.accept()

    def reject(self) -> None:
        """Cancel, Esc or the close box: put back the look the dialog opened
        with. Custom-theme files already written stay written, as in Tk."""
        self._on_preview(self._original)
        super().reject()

    cancel = reject

    # -- the real prompts ----------------------------------------------------------------
    def _ask_color(self, current: str) -> str | None:
        color = QColorDialog.getColor(QColor(current), self, "Accent color")
        return color.name() if color.isValid() else None

    def _ask_save_path(self, initial: str) -> str | None:
        path, _f = QFileDialog.getSaveFileName(self, "Export theme", initial,
                                               "RYOS theme (*.json);;All files (*.*)")
        return path or None

    def _ask_open_path(self) -> str | None:
        path, _f = QFileDialog.getOpenFileName(self, "Import theme", "",
                                               "RYOS theme (*.json);;All files (*.*)")
        return path or None

    def _ask_dir(self, start: str) -> str | None:
        return QFileDialog.getExistingDirectory(self, "Themes folder", start) or None

    def _open_folder(self) -> None:
        try:
            os.startfile(str(self._themes_dir))  # noqa: S606 - Windows reveal
        except (OSError, AttributeError):
            pass
