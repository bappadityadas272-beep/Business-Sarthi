"""The app's idea of "today". Everything date-dependent reads the clock here, so the demo-only
advance-time endpoint (B-09, DEV_MODE) can move it forward without touching the system clock."""
from datetime import UTC, date, datetime, timedelta

_offset = timedelta(0)


def now() -> datetime:
    return datetime.now(UTC) + _offset


def today() -> date:
    return now().date()


def advance(days: int) -> date:
    """Move the app clock forward. Callers must check DEV_MODE."""
    global _offset
    if days < 0:
        raise ValueError("the clock only moves forward")
    _offset += timedelta(days=days)
    return today()


def reset() -> None:
    global _offset
    _offset = timedelta(0)
