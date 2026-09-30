"""A group's page: collapsible Favorites, Pipelines and Scripts sections.

What goes in each section, the header and empty texts and the collapse state
are `ryos.sections`, shared with Tk. Each section is its own `CardList`, so a
drop reorders within the section it lands in -- favourites among favourites,
as in the Tk app.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
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
        self.header.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.header.setFlat(True)
        self.header.clicked.connect(self.toggle)
        col.addWidget(self.header)
        # Favorites are a strip of chips above the lists, not a second copy
        # of each row.
        self.cards = CardList(group, flow=key == sections.FAVORITES)
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
        self._set_collapsed(self.header.text().startswith(sections.COLLAPSED_MARK))

    def has_shown_cards(self) -> bool:
        return any(not c.isHidden() for c in self.cards.cards)

    def set_searching(self, active: bool) -> None:
        """While searching, a section with no match is hidden, heading and
        all; after, it comes back as it was."""
        if active:
            self.setVisible(self.has_shown_cards())
        else:
            self.setVisible(True)
            self.refresh()


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
        self.no_match = QLabel("")
        self.no_match.setObjectName("cardPath")
        self.no_match.setWordWrap(True)
        self.no_match.hide()
        col.addWidget(self.no_match)
        col.addStretch(1)

    def apply_search(self, query: str, *, say_when_empty: bool = True) -> bool:
        """Fit the page to a search (cards are already shown or hidden).
        True when anything on the page matches."""
        for section in self.sections.values():
            section.set_searching(bool(query))
        found = any(s.has_shown_cards() for s in self.sections.values())
        empty = bool(query) and not found
        self.no_match.setText(sections.no_match_text(query) if empty else "")
        self.no_match.setVisible(empty and say_when_empty)
        return found

    def rows(self) -> list:
        """Every row showing, top to bottom: the favourite chips, then the
        pipelines, then the scripts -- the order the keyboard walks."""
        return [c for key in sections.ORDER for c in self.section(key).cards
                if c.isVisibleTo(self)]

    def step_focus(self, row, step: str) -> None:
        """Move the keyboard focus from ``row`` by ``step``, into view."""
        rows = self.rows()
        current = rows.index(row) if row in rows else None
        target = sections.step_row(len(rows), current, step)
        if target is None:
            return
        rows[target].setFocus(Qt.FocusReason.TabFocusReason)
        self.show_row(rows[target])

    def show_row(self, row) -> None:
        """Scroll ``row`` into view."""
        from PySide6.QtWidgets import QScrollArea
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None:
            w.ensureWidgetVisible(row, 0, 24)

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
