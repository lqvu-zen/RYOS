"""How a card is laid out and what its Run button says — toolkit-free.

`ui/cards.py` held these as module globals and resolved colours against the Tk
palette on the spot. Qt needs the same spacing and the same Run/Retry rule but
resolves colours through a stylesheet, so the *decisions* live here and each
front-end binds them to its own palette (docs/plans/qt-migration.md).

Nothing here imports a toolkit or a palette: the run-button rule returns
palette **keys**, not colours.
"""

from __future__ import annotations

from dataclasses import dataclass

SIZES = ("small", "medium", "large")
DEFAULT_SIZE = "medium"

# Hover dwell before the compact-mode detail preview appears, in ms.
PREVIEW_DELAY_MS = 1000

# (padx, pady) for a card's body frame, by (compact, size).
CARD_PADDING: dict[tuple[bool, str], tuple[int, int]] = {
    (False, "small"): (12, 6),
    (False, "medium"): (12, 10),
    (False, "large"): (12, 14),
    (True, "small"): (10, 2),
    (True, "medium"): (10, 4),
    (True, "large"): (10, 8),
}

# (row_pady, row_ipady, stop_pady, name_pady) for running rows and card packing.
ROW_METRICS: dict[tuple[bool, str], tuple[int, int, int, int]] = {
    (False, "small"): (3, 1, 3, 4),
    (False, "medium"): (5, 2, 5, 6),
    (False, "large"): (8, 4, 7, 9),
    (True, "small"): (1, 0, 1, 1),
    (True, "medium"): (2, 0, 2, 2),
    (True, "large"): (5, 2, 4, 5),
}


def card_padding(compact: bool, size: str) -> tuple[int, int]:
    """(padx, pady) for the card body. An unknown size falls back to medium."""
    return CARD_PADDING.get((compact, size), CARD_PADDING[(compact, DEFAULT_SIZE)])


def row_metrics(compact: bool, size: str) -> tuple[int, int, int, int]:
    """(row_pady, row_ipady, stop_pady, name_pady). Unknown size → medium."""
    return ROW_METRICS.get((compact, size), ROW_METRICS[(compact, DEFAULT_SIZE)])


# --- the Run button -----------------------------------------------------------
RUN = "run"
RETRY = "retry"


@dataclass(frozen=True)
class RunButton:
    """What a card's Run button shows, as palette keys rather than colours.

    `hover_fg_key` is deliberately separate from `fg_key`: the retry state sits
    on `error`, a mid red, and hovers to `btn_stop_active`, a near-black one,
    and no single ink clears both. Each front-end resolves `hover_fg_key`
    through its own "readable ink on this fill" helper.
    """

    state: str
    glyph: str
    fg_key: str
    bg_key: str
    hover_key: str
    hover_fg_key: str
    tooltip: str

    @property
    def is_retry(self) -> bool:
        return self.state == RETRY


def run_button(last_status: str | None) -> RunButton:
    """What the Run button becomes, given the last run's outcome.

    After a failure the Run button *is* the retry: same action, so it needs no
    second control, and unlike a status badge the button strip is present in
    every card mode and size. The ↻ glyph rather than ✕ keeps it from reading
    as a stop button while it is red.
    """
    if last_status == "error":
        return RunButton(RETRY, "↻", "error_fg", "error", "btn_stop_active",
                         "btn_stop_active",
                         "Last run failed — click to run it again")
    return RunButton(RUN, "▶", "btn_run_fg", "btn_run_bg", "btn_run_hover",
                     "btn_run_hover", "Run")


# --- the last-run status chip -------------------------------------------------
@dataclass(frozen=True)
class StatusBadge:
    """The reporting-only chip beside a card's name."""

    text: str
    fg_key: str
    bg_key: str


def status_badge(status: str | None) -> StatusBadge | None:
    """The chip for a last-run status, or None when there is nothing to say.

    Reports only — the Run button carries the retry, so this never needs to be
    clickable.
    """
    if status == "error":
        return StatusBadge("✕ Failed", "error_fg", "error")
    if status == "ok":
        return StatusBadge("✓ OK", "ok_fg", "ok")
    return None
