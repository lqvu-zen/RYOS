"""Schedule specs and the date maths behind them.

Pure and dependency-free, like ``search`` / ``grouping`` / ``screens`` /
``history``: no Tk, no database, and no clock of its own — every function that
needs "now" takes it as an argument. Every hard bug in every scheduler ever
written is a date-math bug, and this shape makes them all testable without
waiting for time to pass.

Everything works in **naive local time**. That is deliberate: "daily at 09:00"
means 09:00 on the user's wall clock, on both sides of a daylight-saving
boundary. The next run is always recomputed from a real timestamp rather than
by adding a fixed delta to the previous one, which is what would drift by an
hour twice a year.

A spec is a small dict, stored as JSON:

    interval  {"minutes": 30}
    daily     {"at": "09:00"}
    weekly    {"at": "09:00", "days": [0, 2, 4]}   # 0 = Monday

Every parser returns ``None`` for input it cannot use, so a corrupt or
hand-edited row disables its schedule instead of raising on the timer tick.
"""
from datetime import datetime, time, timedelta

INTERVAL = "interval"
DAILY = "daily"
WEEKLY = "weekly"
SPEC_TYPES = (INTERVAL, DAILY, WEEKLY)

# What to do about runs that came due while RYOS was closed.
CATCH_UP_SKIP = "skip"     # forget them; just schedule the next one
CATCH_UP_ONCE = "once"     # run once, however many were missed
CATCH_UP_ALL = "all"       # run each missed occurrence
CATCH_UP_MODES = (CATCH_UP_SKIP, CATCH_UP_ONCE, CATCH_UP_ALL)

# Even with catch_up="all", a laptop closed over a holiday must not come back
# to hundreds of queued runs.
MAX_CATCH_UP = 20

# An interval below this would fire faster than the tick can service it.
MIN_INTERVAL_MINUTES = 1

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_time_of_day(value) -> time | None:
    """'09:00' or '9:5' -> time(9, 0) / time(9, 5); None when unusable."""
    if isinstance(value, time):
        return value
    try:
        hh, _, mm = str(value).partition(":")
        hour, minute = int(hh), int(mm or 0)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def normalize_spec(spec_type: str, spec) -> dict | None:
    """Validate and clean a spec, or return None if it cannot drive a schedule."""
    if not isinstance(spec, dict):
        return None
    if spec_type == INTERVAL:
        raw = spec.get("minutes")
        try:
            minutes = int(raw)          # type: ignore[arg-type]  # guarded below
        except (TypeError, ValueError):
            return None
        if minutes < MIN_INTERVAL_MINUTES:
            return None
        return {"minutes": minutes}
    if spec_type == DAILY:
        at = parse_time_of_day(spec.get("at"))
        return None if at is None else {"at": f"{at.hour:02d}:{at.minute:02d}"}
    if spec_type == WEEKLY:
        at = parse_time_of_day(spec.get("at"))
        if at is None:
            return None
        days = spec.get("days")
        if not isinstance(days, (list, tuple, set)):
            return None
        clean = sorted({int(d) for d in days if isinstance(d, (int, float))
                        and 0 <= int(d) <= 6})
        if not clean:
            return None                 # a weekly schedule with no days never fires
        return {"at": f"{at.hour:02d}:{at.minute:02d}", "days": clean}
    return None


def next_occurrence(spec_type: str, spec, after: datetime) -> datetime | None:
    """First run strictly after `after`, or None for an unusable spec.

    Strictly after, so calling this with a just-fired time always advances
    rather than handing back the same moment and looping.
    """
    clean = normalize_spec(spec_type, spec)
    if clean is None:
        return None
    if spec_type == INTERVAL:
        return after + timedelta(minutes=clean["minutes"])
    at = parse_time_of_day(clean["at"])
    if at is None:
        return None                     # unreachable: normalize_spec re-emits it
    if spec_type == DAILY:
        candidate = datetime.combine(after.date(), at)
        return candidate if candidate > after else candidate + timedelta(days=1)
    if spec_type == WEEKLY:
        days = clean["days"]
        # At most 8 probes: today, then each of the next seven days.
        for offset in range(8):
            day = after.date() + timedelta(days=offset)
            if day.weekday() in days:
                candidate = datetime.combine(day, at)
                if candidate > after:
                    return candidate
    return None


def preview(spec_type: str, spec, after: datetime, count: int = 5) -> list:
    """The next `count` run times. Powers the dialog's "next runs" list.

    This is the cheapest possible confidence check on the date maths — for the
    user reading it and for the tests.
    """
    out: list[datetime] = []
    cursor = after
    for _ in range(max(0, count)):
        nxt = next_occurrence(spec_type, spec, cursor)
        if nxt is None:
            break
        out.append(nxt)
        cursor = nxt
    return out


def resolve_due(spec_type: str, spec, next_run_at: datetime | None,
                now: datetime, catch_up: str = CATCH_UP_ONCE):
    """Decide what a due schedule owes: ``(times_to_run, new_next_run_at)``.

    Called on every tick, and on the first tick after launch — which is where
    runs missed while RYOS was closed are settled, according to `catch_up`:

    * skip — none of them run; the schedule simply moves on
    * once — one run, no matter how many were missed
    * all  — every missed occurrence, capped at MAX_CATCH_UP so a machine
             that was off for a week doesn't come back to a stampede

    ``new_next_run_at`` is always recomputed from `now`, never by adding a
    delta to the old value, so a schedule can't march backwards in time after
    a clock change. A None result means the spec is unusable and the caller
    should stop scheduling it.
    """
    if normalize_spec(spec_type, spec) is None:
        return 0, None
    if next_run_at is None:                 # never scheduled: start from now
        return 0, next_occurrence(spec_type, spec, now)
    if next_run_at > now:                   # not due yet
        return 0, next_run_at
    if catch_up == CATCH_UP_SKIP:
        return 0, next_occurrence(spec_type, spec, now)
    if catch_up == CATCH_UP_ALL:
        missed, cursor = 0, next_run_at
        while cursor <= now and missed < MAX_CATCH_UP:
            missed += 1
            nxt = next_occurrence(spec_type, spec, cursor)
            if nxt is None:
                break
            cursor = nxt
        return missed, next_occurrence(spec_type, spec, now)
    return 1, next_occurrence(spec_type, spec, now)


def describe_spec(spec_type: str, spec) -> str:
    """A short human label, e.g. 'Daily at 09:00' or 'Mon, Wed at 18:30'."""
    clean = normalize_spec(spec_type, spec)
    if clean is None:
        return "Invalid schedule"
    if spec_type == INTERVAL:
        minutes = clean["minutes"]
        if minutes % 60 == 0:
            hours = minutes // 60
            return f"Every {hours} hour{'s' if hours != 1 else ''}"
        return f"Every {minutes} minute{'s' if minutes != 1 else ''}"
    if spec_type == DAILY:
        return f"Daily at {clean['at']}"
    days = ", ".join(_DAY_NAMES[d] for d in clean["days"])
    return f"{days} at {clean['at']}"
