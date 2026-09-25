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
