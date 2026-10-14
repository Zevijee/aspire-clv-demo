"""The paid holidays staffing pays a premium on, shared by the API and the
staffing cost rollup so a month from the rollup and a day from the daily facts
count the same days.

Its own file, not shared/staffing.py: every staffing generator fingerprints
that one, and a calendar edit must rebuild only what reads the calendar.
"""
from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth weekday (Monday 0) of a month; n = -1 is the last."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def holidays(start: date, end: date) -> list[date]:
    """The paid holidays from start to end: New Year's Day, Memorial Day,
    Independence Day, Labor Day, Thanksgiving and Christmas, on the day itself.
    A facility is open every day, so nothing moves to an observed weekday."""
    days = []
    for year in range(start.year, end.year + 1):
        days += [date(year, 1, 1), _nth_weekday(year, 5, 0, -1), date(year, 7, 4),
            _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 11, 3, 4), date(year, 12, 25)]
    return sorted(day for day in days if start <= day <= end)
