"""When to start, when to stop - pure logic, no Django, so it can be tested on its own
(tests/test_schedule.py). service.py feeds it the clock and the input levels and carries out what
it decides."""
import datetime

WEEKDAYS = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}
WEEKDAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# A start is only made this long after the planned time - a Pi that comes up at 11:00 shouldn't
# start a "10:28" recording in the middle of nothing (or after the service).
START_WINDOW = datetime.timedelta(minutes=20)

STOP_MAX = "max"
STOP_QUIET = "quiet"


_DAY_NAMES = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4, "samstag": 5,
    "sonnabend": 5, "sonntag": 6,
}


def _day(word):
    word = word.strip().lower().rstrip(".")
    if word in WEEKDAYS:
        return WEEKDAYS[word]
    if word in _DAY_NAMES:
        return _DAY_NAMES[word]
    raise ValueError(f"Unbekannter Wochentag '{word}' - z.B. 'So' oder 'Sa, So'")


def parse_weekdays(text):
    """'So' / 'Sa, So' / 'Fr-Mo' / 'Sonntag' -> set of weekday numbers (Monday = 0). Only the
    two-letter abbreviations and full names count - 'Sonnabend' is Saturday, not 'So...'.
    Raises ValueError."""
    days = set()
    for part in (text or "").replace(";", ",").split(","):
        if not part.strip():
            continue
        if "-" in part:
            first, last = (_day(p) for p in part.split("-", 1))
            day = first
            while True:
                days.add(day)
                if day == last:
                    break
                day = (day + 1) % 7
            continue
        days.add(_day(part))
    if not days:
        raise ValueError("Mindestens einen Wochentag angeben, z.B. 'So'")
    return days


def parse_time(text):
    """'10:28' -> datetime.time. Raises ValueError."""
    try:
        hours, minutes = (int(p) for p in (text or "").strip().split(":"))
        return datetime.time(hours, minutes)
    except (ValueError, TypeError):
        raise ValueError(f"Uhrzeit '{text}' nicht verstanden - bitte als HH:MM, z.B. 10:28")


def planned_starts(now, weekdays, start_time, days_ahead=8):
    """Planned start datetimes (same tzinfo as now) from today on."""
    for offset in range(days_ahead):
        day = (now + datetime.timedelta(days=offset)).date()
        if day.weekday() in weekdays:
            yield datetime.datetime.combine(day, start_time, tzinfo=now.tzinfo)


def start_due(now, weekdays, start_time, last_start_date):
    """The planned start for today, if it's due now and wasn't made yet - else None."""
    for planned in planned_starts(now, weekdays, start_time, days_ahead=1):
        if planned <= now < planned + START_WINDOW and last_start_date != planned.date():
            return planned
    return None


def next_start(now, weekdays, start_time, last_start_date):
    for planned in planned_starts(now, weekdays, start_time):
        if planned + START_WINDOW > now and last_start_date != planned.date():
            return planned
    return None


class QuietTracker:
    """Remembers since when it has been quiet (in recording time). Any loud moment resets it."""

    def __init__(self):
        self.quiet_since = None

    def feed(self, elapsed, loud):
        if loud:
            self.quiet_since = None
        elif self.quiet_since is None:
            self.quiet_since = elapsed
        return self.quiet_since


def stop_reason(elapsed, quiet_since, normal, tolerance, maximum, quiet_needed):
    """Why the recording should end now, or None. All values are timedeltas into the recording.

    Quiet only counts from (normal length - tolerance) on: a long prayer or a pause halfway
    through is no end. The quiet stretch itself may have begun earlier - what matters is that it
    has lasted quiet_needed when it's checked."""
    if elapsed >= maximum:
        return STOP_MAX
    if (elapsed >= normal - tolerance and quiet_since is not None
            and elapsed - quiet_since >= quiet_needed):
        return STOP_QUIET
    return None
