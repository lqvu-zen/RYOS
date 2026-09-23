"""The schedule dialog's form rules, independent of any toolkit.

`scheduling.py` holds the maths — when a spec next fires, what it previews
to. What lived only inside the Tk ScheduleDialog was the form around it:
which fields make up a spec for each mode, how a catch-up label maps back to
its key, how a preview line reads, and what to say when a spec is unusable.
Both front-ends ask this module (docs/plans/qt-migration.md).
"""

from __future__ import annotations

from datetime import datetime

from . import verdict
from .scheduling import (_DAY_NAMES, CATCH_UP_ALL, CATCH_UP_ONCE,
                         CATCH_UP_SKIP, DAILY, INTERVAL, WEEKLY, preview)

#: Weekday labels, Monday first, matching `datetime.weekday()`. The Tk dialog
#: carried its own copy; this is the one both forms read.
DAY_NAMES: tuple[str, ...] = _DAY_NAMES

#: How each catch-up policy is offered, in the order the dialog lists them.
CATCH_UP_LABELS: dict[str, str] = {
    CATCH_UP_ONCE: "Run once",
    CATCH_UP_SKIP: "Skip them",
    CATCH_UP_ALL: "Run every missed one",
}

MODES = (INTERVAL, DAILY, WEEKLY)

#: The strftime a preview line is written with.
PREVIEW_FORMAT = "%a %d %b  %H:%M"

INVALID = verdict.refuse(
    "Check the schedule",
    "That schedule can't run.\n\n"
    "Interval needs at least 1 minute, times look like 09:00, "
    "and a weekly schedule needs at least one day.",
    verdict.WARNING)


def raw_spec(mode: str, *, minutes: str = "", at: str = "",
             days=()) -> dict:
    """The spec fields a mode takes, from whatever the form holds.

    Only the fields the mode uses are included, so switching mode and saving
    never carries a stale value from the mode that was showing before.
    Normalisation is `scheduling.normalize_spec`'s job, not this one's.
    """
    if mode == INTERVAL:
        return {"minutes": str(minutes).strip()}
    if mode == DAILY:
        return {"at": str(at).strip()}
    return {"at": str(at).strip(), "days": _clean_days(list(days))}


def catch_up_from_label(label: str) -> str:
    """The catch-up key a label stands for; an unknown label means "once".

    "Once" is the fallback because it is the default and the gentlest: it
    neither drops missed runs silently nor floods the queue with them.
    """
    for key, text in CATCH_UP_LABELS.items():
        if text == label:
            return key
    return CATCH_UP_ONCE


def preview_lines(spec_type: str, spec, now: datetime | None = None,
                  count: int = 5) -> list[str]:
    """The next few firings, formatted for the dialog; [] for a bad spec."""
    if spec is None:
        return []
    when = now if now is not None else datetime.now()
    return [r.strftime(PREVIEW_FORMAT) for r in preview(spec_type, spec, when,
                                                        count)]


def check(spec) -> verdict.Verdict:
    """Whether a normalised spec can be saved."""
    return verdict.PROCEED if spec is not None else INVALID


#: What a new schedule's form starts at: every 30 minutes, 09:00, Mondays.
DEFAULT_FORM: dict = {
    "mode": INTERVAL,
    "minutes": "30",
    "at": "09:00",
    "days": [0],
    "catch_up": CATCH_UP_ONCE,
    "enabled": False,
}


def form_values(row) -> dict:
    """Form values for a stored schedule row, or the defaults for none.

    ``row`` is what `db.get_schedule()` returns. A spec that no longer parses
    falls back to the defaults field by field rather than refusing to open --
    the dialog is how someone repairs a bad schedule, so it must load one.
    """
    import json

    values = dict(DEFAULT_FORM)
    values["days"] = list(DEFAULT_FORM["days"])
    if not row:
        return values
    spec_type, raw, enabled, catch_up = row[4], row[5], row[6], row[7]
    try:
        spec = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        spec = {}
    if not isinstance(spec, dict):
        spec = {}
    if spec_type in MODES:
        values["mode"] = spec_type
    if spec_type == INTERVAL:
        values["minutes"] = str(spec.get("minutes", DEFAULT_FORM["minutes"]))
    else:
        values["at"] = str(spec.get("at", DEFAULT_FORM["at"]))
        if spec_type == WEEKLY:
            values["days"] = _clean_days(spec.get("days"))
    values["catch_up"] = catch_up if catch_up in CATCH_UP_LABELS else CATCH_UP_ONCE
    values["enabled"] = bool(enabled)
    return values


def _clean_days(raw) -> list[int]:
    """Weekday indexes from a stored spec, dropping anything unusable.

    Tolerant on purpose: a hand-edited or older spec with a stray value must
    still open, so the user can see and fix it.
    """
    out = set()
    for d in raw if isinstance(raw, (list, tuple)) else ():
        try:
            n = int(d)
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 6:
            out.add(n)
    return sorted(out)


#: A schedule only fires while RYOS is open, so switching one on offers to
#: start RYOS at login. Phrased as a confirmation, not a refusal: saying no is
#: a perfectly good answer for someone who keeps RYOS open anyway.
RUN_AT_LOGIN = verdict.confirm(
    "Start RYOS at login?",
    "Schedules only run while RYOS is open.\n\n"
    "Start RYOS automatically when you log in?")


def should_offer_run_at_login(*, enabled: bool, platform: str,
                              startup_enabled: bool) -> bool:
    """Whether saving this schedule should ask about starting at login.

    Only for a schedule that is switched on, only where the app knows how to
    register itself (Windows), and never when it is already registered --
    asking someone to turn on what is already on is noise.
    """
    return bool(enabled) and platform == "win32" and not startup_enabled
