import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


APP_TIMEZONE = ZoneInfo(os.getenv("TIME_TRACKER_TIMEZONE", "America/Chicago"))


def utc_now() -> datetime:
    """Return a naive UTC datetime for consistent database storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_to_utc(value: datetime) -> datetime:
    """Convert a local wall-clock datetime to naive UTC for storage."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utc_to_local(value: datetime) -> datetime:
    """Convert a stored naive UTC datetime to the configured local timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TIMEZONE)


def local_day_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    start = local_to_utc(datetime.combine(start_date, time.min))
    end = local_to_utc(datetime.combine(end_date + timedelta(days=1), time.min))
    return start, end
