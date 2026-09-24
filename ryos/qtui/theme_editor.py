"""The Qt custom-theme editor.

Edits a seed -- a base mode, seven colours, optional advanced overrides --
and previews it with the same `build_palette` the app themes itself with.
The colour labels, the colour an un-overridden advanced row shows, the
contrast warnings and the save rule are `themeform` / `themes`, shared with
the Tk editor. `on_save(name, seed)` is called once with a valid theme.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QDialog,
                               QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from .. import themeform
from ..themes import (ADVANCED_KEYS, SEED_KEYS, build_palette,
                      contrast_warnings, is_hex_color)


def _swatch_style(color: str) -> str:
    return (f"background: {color}; border: 1px solid #808080; "
            f"min-width: 26px; max-width: 26px; min-height: 18px; padding: 0;")


class ThemeEditorDialog(QDialog):
    """Name a theme, pick its colours, see it, save it."""

    def __init__(self, parent: QWidget | None = None, *, seed: dict,
                 name: str = "", taken_names=(),
                 on_save: Callable[[str, dict], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Theme editor")
        self._seed = {"mode": seed.get("mode", "light")}
        for key in SEED_KEYS:
            self._seed[key] = seed.get(key, "#888888")
        for key, _label in ADVANCED_KEYS:
            if is_hex_color(seed.get(key)):
                self._seed[key] = seed[key]
        self._taken = set(taken_names)
        self._on_save = on_save
        # Injectable: a colour chooser and a message box both block.
        self.ask_color: Callable[[str, str], str | None] = self._ask_color
        self.warn: Callable[[str, str], None] = \
            lambda title, text: QMessageBox.warning(self, title, text)

        col = QVBoxLayout(self)
        col.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit(name)
        col.addWidget(self.name_edit)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Base"))
        self.mode_buttons = QButtonGroup(self)
        for label, value in (("☀ Light", "light"), ("🌙 Dark", "dark")):
            rb = QRadioButton(label)
            rb.setProperty("mode", value)
            rb.setChecked(self._seed["mode"] == value)
            self.mode_buttons.addButton(rb)
            mode_row.addWidget(rb)
        mode_row.addStretch(1)
        self.mode_buttons.buttonClicked.connect(
            lambda b: self._set("mode", b.property("mode")))
        col.addLayout(mode_row)

        body = QHBoxLayout()
        pickers = QVBoxLayout()
        self.swatches: dict[str, QPushButton] = {}
        for key, label in themeform.COLOR_LABELS.items():
            row = QHBoxLayout()
            sw = QPushButton()
            sw.clicked.connect(lambda _c=False, k=key: self.choose(k))
            self.swatches[key] = sw
            row.addWidget(sw)
            row.addWidget(QLabel(label), 1)
            pickers.addLayout(row)
        pickers.addStretch(1)
        body.addLayout(pickers)

        right = QVBoxLayout()
        right.addWidget(QLabel("Preview"))
        self.preview = QFrame()
        self.preview.setObjectName("themePreview")
        self._build_preview()
        right.addWidget(self.preview, 1)
        self.warnings = QLabel("")
        self.warnings.setWordWrap(True)
        right.addWidget(self.warnings)
        body.addLayout(right, 1)
        col.addLayout(body)

        col.addWidget(QLabel("ADVANCED  (optional — ↺ resets to auto)"))
        grid = QGridLayout()
        self.adv_swatches: dict[str, QPushButton] = {}
        self.adv_resets: dict[str, QPushButton] = {}
        for i, (key, label) in enumerate(ADVANCED_KEYS):
            cell = QHBoxLayout()
            sw = QPushButton()
            sw.clicked.connect(lambda _c=False, k=key: self.choose(k, advanced=True))
            reset = QPushButton("↺")
            reset.setFlat(True)
            reset.clicked.connect(lambda _c=False, k=key: self.reset(k))
            self.adv_swatches[key] = sw
            self.adv_resets[key] = reset
            cell.addWidget(sw)
            cell.addWidget(QLabel(label))
            cell.addWidget(reset)
            cell.addStretch(1)
            grid.addLayout(cell, i // 2, i % 2)
        col.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self.refresh()

    @property
    def seed(self) -> dict:
        return dict(self._seed)

    # -- changes -------------------------------------------------------------------
    def _set(self, key: str, value) -> None:
        self._seed[key] = value
        self.refresh()

    def choose(self, key: str, advanced: bool = False) -> None:
        current = (themeform.effective_color(self._seed, key) if advanced
                   else self._seed[key])
        title = "Advanced colour" if advanced else themeform.COLOR_LABELS[key]
        picked = self.ask_color(current, title)
        if picked and is_hex_color(picked):
            self._set(key, picked.lower())

    def reset(self, key: str) -> None:
        if key in self._seed:
            del self._seed[key]
            self.refresh()

    # -- showing it ----------------------------------------------------------------
    def refresh(self) -> None:
        for key, sw in self.swatches.items():
            sw.setStyleSheet(_swatch_style(self._seed[key]))
        for key, sw in self.adv_swatches.items():
            sw.setStyleSheet(_swatch_style(themeform.effective_color(self._seed, key)))
            self.adv_resets[key].setEnabled(themeform.is_overridden(self._seed, key))
        warnings = contrast_warnings(self._seed)
        self.warnings.setText("⚠ " + "  ".join(warnings) if warnings else "")
        self._paint_preview()

    def _build_preview(self) -> None:
        col = QVBoxLayout(self.preview)
        col.setContentsMargins(0, 0, 0, 0)
        self.p_header = QLabel("⚡ RYOS")
        col.addWidget(self.p_header)
        self.p_card = QFrame()
        card = QVBoxLayout(self.p_card)
        self.p_name = QLabel("deploy.py")
        self.p_path = QLabel("C:\\scripts\\deploy.py")
        buttons = QHBoxLayout()
        self.p_run = QLabel("Run")
        self.p_mod = QLabel("Modify")
        buttons.addWidget(self.p_run)
        buttons.addWidget(self.p_mod)
        buttons.addStretch(1)
        for w in (self.p_name, self.p_path):
            card.addWidget(w)
        card.addLayout(buttons)
        col.addWidget(self.p_card)
        self.p_term = QLabel("")
        col.addWidget(self.p_term)

    def _paint_preview(self) -> None:
        p = build_palette(self._seed)
        self.preview_palette = p
        self.preview.setStyleSheet(
            f"QFrame#themePreview {{ background: {p['bg']}; border: 1px solid {p['border']}; }}")
        self.p_header.setStyleSheet(
            f"background: {p['header_bg']}; color: {p['fg_on_dark']}; "
            f"font-weight: 700; padding: 5px 8px;")
        self.p_card.setStyleSheet(
            f"background: {p['card_bg']}; border: 1px solid {p['border']};")
        self.p_name.setStyleSheet(f"color: {p['name_fg']}; font-weight: 700; border: none;")
        self.p_path.setStyleSheet(f"color: {p['path_fg']}; font-size: 8pt; border: none;")
        self.p_run.setStyleSheet(f"background: {p['btn_run_bg']}; color: {p['btn_run_fg']}; "
                                 f"padding: 3px 10px; font-weight: 700; border: none;")
        self.p_mod.setStyleSheet(f"background: {p['btn_mod_bg']}; color: {p['btn_fg']}; "
                                 f"padding: 3px 10px; font-weight: 700; border: none;")
        self.p_term.setText(
            f"<span style='color:{p['out_stdout']}'>stdout</span>&nbsp;&nbsp;"
            f"<span style='color:{p['out_stderr']}'>stderr</span>&nbsp;&nbsp;"
            f"<span style='color:{p['out_status']}'>status</span>")
        self.p_term.setStyleSheet(f"background: {p['out_bg']}; padding: 4px 8px; "
                                  f"font-family: Consolas, monospace;")

    # -- saving -----------------------------------------------------------------------
    def save(self) -> bool:
        name = self.name_edit.text().strip()
        check = themeform.validate(name, self._seed, self._taken)
        if not check.ok:
            self.warn(check.title, check.message)
            return False
        if self._on_save is not None:
            self._on_save(name, dict(self._seed))
        self.accept()
        return True

    def _ask_color(self, current: str, title: str) -> str | None:
        color = QColorDialog.getColor(QColor(current), self, title)
        return color.name() if color.isValid() else None
