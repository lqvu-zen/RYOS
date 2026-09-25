"""A group's page: collapsible Favorites, Pipelines and Scripts sections.

What goes in each section, the header and empty texts and the collapse state
are `ryos.sections`, shared with Tk. Each section is its own `CardList`, so a
drop reorders within the section it lands in -- favourites among favourites,
as in the Tk app.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .. import sections
from .dragdrop import CardList


class Section(QWidget):
    """One header that folds, and the cards beneath it."""

    def __init__(self, group: str, key: str, collapsed: bool,
                 on_toggle: Callable[[str], bool], parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self._on_toggle = on_toggle
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.header = QPushButton(sections.header_text(key, collapsed))
        self.header.setObjectName("sectionHeader")
        self.header.setFlat(True)
        self.header.clicked.connect(self.toggle)
        col.addWidget(self.header)
        self.cards = CardList(group)
        self.empty = QLabel(sections.EMPTY[key])
        self.empty.setObjectName("cardPath")
        # Wraps, so the hint never sets the page's minimum width.
        self.empty.setWordWrap(True)
        col.addWidget(self.empty)
        col.addWidget(self.cards)
        self._set_collapsed(collapsed)

    def toggle(self) -> None:
        self._set_collapsed(self._on_toggle(self.key))

    @property
    def collapsed(self) -> bool:
        return self.cards.isHidden() and self.empty.isHidden()

    def _set_collapsed(self, collapsed: bool) -> None:
        self.header.setText(sections.header_text(self.key, collapsed))
        has_cards = bool(self.cards.cards)
        self.cards.setVisible(not collapsed and has_cards)
        self.empty.setVisible(not collapsed and not has_cards)

    def refresh(self) -> None:
        """Re-show after cards were added, keeping the collapsed state."""
        self._set_collapsed(self.header.text().startswith("▶"))


class GroupPage(QWidget):
    """Every section for one group, top to bottom."""

    def __init__(self, group: str, collapse: sections.CollapseState,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.group = group
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        self.sections: dict[str, Section] = {}
        for key in sections.ORDER:
            section = Section(group, key, collapse.is_collapsed(group, key),
                              lambda k: collapse.toggle(group, k))
            self.sections[key] = section
            col.addWidget(section)
        col.addStretch(1)

    def section(self, key: str) -> CardList:
        return self.sections[key].cards

    @property
    def cards(self) -> list:
        """The group's own cards, pipelines then scripts -- not the favourite
        copies, which are shortcuts to the same items."""
        return (self.section(sections.PIPELINES).cards
                + self.section(sections.SCRIPTS).cards)

    @property
    def favorite_cards(self) -> list:
        return self.section(sections.FAVORITES).cards
