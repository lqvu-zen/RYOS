"""Scroll maths for a marquee label, shared by the Tk and Qt front-ends.

`ui/widgets.py` had this arithmetic inline in a `tk.Canvas` subclass, and Qt
has no marquee widget either, so both toolkits need the same rules. They live
here so there is one answer rather than two that drift
(docs/plans/qt-migration.md).

Pure: no widget, no timer, no toolkit. The caller measures the text, owns the
timer, and paints.
"""

from __future__ import annotations

# Defaults matching the original Tk widget, so behaviour is unchanged.
IDLE_MS = 1500      # pause before starting, and again after each full pass
TICK_MS = 25        # between steps while scrolling
SPEED = 1           # pixels per step
GAP = 80            # blank run after the text before it wraps around


def needs_scroll(text_width: int, view_width: int) -> bool:
    """Whether the text is too wide to sit still.

    Equal widths do not scroll: the text already fits exactly, and nudging it
    would hide the last pixel for no reason.
    """
    return text_width > view_width


def advance(offset: int, text_width: int, *, gap: int = GAP,
            speed: int = SPEED) -> tuple[int, bool]:
    """One step. Returns ``(new_offset, wrapped)``.

    ``wrapped`` is True on the step that completes a pass and resets to the
    start, which is the caller's cue to pause rather than continue at tick
    speed.
    """
    moved = offset + speed
    if moved >= text_width + gap:
        return 0, True
    return moved, False


def next_delay(wrapped: bool, *, idle_ms: int = IDLE_MS,
               tick_ms: int = TICK_MS) -> int:
    """How long to wait before the next step, in milliseconds."""
    return idle_ms if wrapped else tick_ms


def pass_steps(text_width: int, *, gap: int = GAP, speed: int = SPEED) -> int:
    """Steps in one full pass, for tests and for estimating a cycle's length."""
    if speed <= 0:
        raise ValueError("speed must be positive, or the marquee never moves")
    span = text_width + gap
    return (span + speed - 1) // speed
