"""Calendar date primitives; each feature decides which dates its data supports."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

# An optional date where an empty query parameter means "not given". The shared
# table filter client always sends start_date and end_date, empty before a
# report knows its dates; a plain `date | None` rejects the empty string.
OptionalDate = Annotated[date | None, BeforeValidator(lambda value: value or None)]


class DateRange(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    start_date: date
    end_date: date

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.start_date > self.end_date:
            raise ValueError('start_date must be on or before end_date.')
        if self.end_date == date.max:
            raise ValueError('end_date must allow an exclusive upper boundary.')
        return self

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def exclusive_end(self):
        return self.end_date + timedelta(days=1)


def today(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def month_after(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def month_end(month: date) -> date:
    return month_after(month) - timedelta(days=1)


def rollup_plan(start: date, end: date, through: date):
    """How to add up an inclusive period from a monthly rollup and its daily
    source, reading as few daily rows as possible.

    Returns the whole months to read from the rollup, (first, last) or None, and
    signed inclusive date ranges to add (+1) or take away (-1) from the daily
    rows. Either the period's own days come from the daily rows, or the months
    covering it come from the rollup less the days of them outside the period --
    whichever reads fewer days. Last 6 months, Apr 7 to yesterday, is April to
    October less Apr 1-6 and less today: 7 days instead of 183. `through` is the
    last day the rollup holds; nothing past it is taken away."""
    first, last = start.replace(day=1), end.replace(day=1)
    outside = []
    if start > first:
        outside.append((-1, first, start - timedelta(days=1)))
    held = min(month_end(last), through)
    if end < held:
        outside.append((-1, end + timedelta(days=1), held))
    by_months = sum((b - a).days + 1 for _, a, b in outside)
    direct = (end - start).days + 1
    if direct <= by_months:
        return None, [(1, start, end)]
    return (first, last), outside
