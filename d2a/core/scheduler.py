"""Scheduler that decides whether to download now, based on a timezone-anchored interval."""

from datetime import datetime
from zoneinfo import ZoneInfo


def should_download_now(interval_hours: int, timezone: str, now: datetime | None = None) -> bool:
    """True if the current local hour (in timezone) is a multiple of interval_hours.
    If now isn't given, uses the real current time — self-checks inject now for
    deterministic testing. If interval_hours doesn't evenly divide 24 (e.g. 5, 7),
    the boundaries become uneven — a known limitation, no correction logic added."""
    zone = ZoneInfo(timezone)
    if now is None:
        now = datetime.now(zone)
    else:
        now = now.astimezone(zone)
    return now.hour % interval_hours == 0


if __name__ == "__main__":
    from datetime import timezone as dt_timezone

    kst = ZoneInfo("Asia/Seoul")

    at_midnight = datetime(2026, 7, 18, 0, 0, tzinfo=kst)
    assert should_download_now(interval_hours=24, timezone="Asia/Seoul", now=at_midnight) is True

    at_6am = datetime(2026, 7, 18, 6, 0, tzinfo=kst)
    assert should_download_now(interval_hours=6, timezone="Asia/Seoul", now=at_6am) is True
    assert should_download_now(interval_hours=24, timezone="Asia/Seoul", now=at_6am) is False

    at_5am = datetime(2026, 7, 18, 5, 0, tzinfo=kst)
    assert should_download_now(interval_hours=1, timezone="Asia/Seoul", now=at_5am) is True
    assert should_download_now(interval_hours=6, timezone="Asia/Seoul", now=at_5am) is False

    # a now passed in a different timezone should still convert correctly to the target timezone
    utc_midnight = datetime(2026, 7, 18, 0, 0, tzinfo=dt_timezone.utc)  # KST 09:00
    assert should_download_now(interval_hours=6, timezone="Asia/Seoul", now=utc_midnight) is False
    assert should_download_now(interval_hours=3, timezone="Asia/Seoul", now=utc_midnight) is True

    print("scheduler.py self-check OK")
