"""The Qt Quick Run bar.

Type a script name, get ranked suggestions from the group's folder, press
Return to run it. Everything that decides anything is shared with the Tk bar:

* the index and its ranking — `quickrun_index.QuickRunIndex`, `quickrun`;
* when suggestions show, how the keys move through them, what Tab and Return
  put in the box, what Escape closes — `quickrun`'s bar rules;
* what submitting does — `quickrun_actions.plan_submit` / `ensure_script`,
  which the shell calls when `submitted` fires.

The suggestion list is part of the bar rather than a separate popup window:
a popup takes the keyboard focus away from the box being typed into, which is
the one thing a completion list must never do.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget,
                               QPushButton, QVBoxLayout, QWidget)

from .. import quickrun as qr

PLACEHOLDER = "script name [params...]"


class QuickRunBar(QWidget):
    """One group's Quick Run bar.

    ``submitted`` carries the raw text; resolving and running it is the
    shell's job, through the shared submit plan, so this widget never touches
    the database or the job machinery.
    """

    submitted = Signal(str)
    closed = Signal()

    def __init__(self, *, base_dir: str, index, index_args: Callable[[], dict],
                 max_suggestions: int = 10, autocomplete: bool = True,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("quickRunBar")
        self.base_dir = base_dir
        self._index = index
        self._index_args = index_args
        self._max = max(1, int(max_suggestions))
        self._autocomplete = autocomplete

        col = QVBoxLayout(self)
        col.setContentsMargins(8, 4, 8, 4)
        col.setSpacing(2)
        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(PLACEHOLDER)
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("primary")
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("dark")
        self.close_button.setFixedWidth(34)
        row.addWidget(self.entry, 1)
        row.addWidget(self.run_button)
        row.addWidget(self.close_button)
        col.addLayout(row)

        self.suggestions = QListWidget()
        self.suggestions.setObjectName("quickRunSuggestions")
        # The list must never take focus from the box being typed into.
        self.suggestions.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggestions.hide()
        col.addWidget(self.suggestions)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(qr.SUGGEST_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.refresh)

        self.entry.textEdited.connect(lambda _t: self._debounce.start())
        self.entry.installEventFilter(self)
        self.suggestions.itemClicked.connect(
            lambda item: self.accept_suggestion(item.text(), submit=True))
        self.run_button.clicked.connect(self.submit)
        self.close_button.clicked.connect(self.close_bar)

    # -- opening and closing -------------------------------------------------
    def open(self) -> None:
        """Show the bar, focus it, and start building the index if needed."""
        self.entry.clear()
        self.show()
        self.entry.setFocus()
        if self._autocomplete:
            self._index.get(self.base_dir, **self._index_args())

    def close_bar(self) -> None:
        self.hide_suggestions()
        self.hide()
        self.closed.emit()

    # -- suggestions -----------------------------------------------------------
    @property
    def suggestions_open(self) -> bool:
        return self.suggestions.isVisible()

    def refresh(self) -> None:
        """Recompute the list from what is typed, by the shared rules."""
        if not self._autocomplete:
            return
        head = qr.suggestion_query(self.entry.text())
        if head is None:
            self.hide_suggestions()
            return
        if self._index.cached(self.base_dir) is None:
            self.show_suggestions([qr.INDEXING])
            return
        items = self._index.suggestions(self.base_dir, head, max_n=self._max,
                                        **self._index_args())
        if items:
            self.show_suggestions(items)
        else:
            self.hide_suggestions()

    def on_index_ready(self, base_dir: str) -> None:
        """A background build finished; refresh if it was ours and we are open."""
        if base_dir == self.base_dir and self.isVisible():
            self.refresh()

    def show_suggestions(self, items: list) -> None:
        self.suggestions.clear()
        self.suggestions.addItems(items)
        rows = min(len(items), self._max)
        height = self.suggestions.sizeHintForRow(0) if items else 18
        self.suggestions.setFixedHeight(max(1, rows) * max(height, 16) + 4)
        self.suggestions.show()
        # Pre-select the best match so Return runs it straight away -- but
        # never the "indexing" placeholder, which is not a file.
        if items and qr.is_selectable(items[0]):
            self.suggestions.setCurrentRow(0)
        else:
            self.suggestions.setCurrentRow(-1)

    def hide_suggestions(self) -> None:
        self.suggestions.hide()
        self.suggestions.clear()

    def selected(self) -> str | None:
        item = self.suggestions.currentItem()
        return item.text() if (item is not None and self.suggestions_open) else None

    def move_selection(self, delta: int) -> None:
        # Not `move`: that would override QWidget.move(x, y), which Qt's
        # layouts call to position the widget.
        row = self.suggestions.currentRow()
        nxt = qr.move_selection(row if row >= 0 else None,
                                self.suggestions.count(), delta)
        if nxt is not None:
            self.suggestions.setCurrentRow(nxt)

    # -- accepting and submitting -------------------------------------------
    def accept_suggestion(self, rel: str, *, submit: bool) -> None:
        """Take a suggestion: Tab keeps typing, Return and click run it."""
        if not qr.is_selectable(rel):
            return
        self.entry.setText(qr.accepted_text(rel, submit=submit))
        self.entry.end(False)
        self.hide_suggestions()
        if submit:
            self.submit()

    def submit(self) -> None:
        text = self.entry.text()
        if not text.strip():
            return
        self.hide_suggestions()
        self.submitted.emit(text)

    # -- keys ------------------------------------------------------------------
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:   # noqa: N802
        if obj is not self.entry or event.type() != QEvent.Type.KeyPress:
            return False
        key = event.key()
        if key == Qt.Key.Key_Down and self.suggestions_open:
            self.move_selection(+1)
            return True
        if key == Qt.Key.Key_Up and self.suggestions_open:
            self.move_selection(-1)
            return True
        if key == Qt.Key.Key_Tab:
            # Consumed either way: Tab here completes, it does not move focus.
            pick = self.selected()
            if pick is not None:
                self.accept_suggestion(pick, submit=False)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            pick = self.selected()
            if pick is not None and qr.is_selectable(pick):
                self.accept_suggestion(pick, submit=True)
            else:
                self.submit()
            return True
        if key == Qt.Key.Key_Escape:
            if qr.escape_action(self.suggestions_open) == qr.CLOSE_SUGGESTIONS:
                self.hide_suggestions()
            else:
                self.close_bar()
            return True
        return False


class MainThreadInvoker(QObject):
    """Run a callable on the thread that created this object.

    The Quick Run index builds on a worker thread and hands its result back
    through a ``schedule`` function. ``QTimer.singleShot`` is the obvious
    choice and the wrong one: called from a plain Python thread it has no
    event loop to post to, so the callback silently never runs. A signal
    emitted from the worker with a queued connection is delivered on the
    receiver's thread instead -- which is exactly the hop the Tk app makes
    with ``after(0, ...)``, but safe, and testable.

    Create it on the UI thread.
    """

    _call = Signal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, fn) -> None:
        fn()

    def __call__(self, fn) -> None:
        self._call.emit(fn)
