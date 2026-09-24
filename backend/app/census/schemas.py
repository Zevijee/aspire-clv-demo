from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FacilityCensus(BaseModel):
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str
    capacity: int = Field(description='Licensed beds.')
    census: int = Field(description='Residents in a bed at the close of `as_of`.')
    skilled_census: int = Field(description='Of `census`, residents on a skilled payer.')
    payer_census: dict[str, int] = Field(description=
        '`census` by payer type. Types with no residents are omitted.')
    payer_daily_rates: dict[str, float] = Field(description=
        'Sum of every resident\'s daily rate on `census_date`, by payer type. Divide '
        'by the matching `payer_census` for the average rate; sum both first to '
        'average over several facilities.')
    history: dict[str, int | None] = Field(description=
        'Census on each `lookback` day, keyed by its `key`. Null when that day was '
        'never generated.')
    year_average: float | None = Field(description=
        'Average daily census from `year_start` through `year_end`. Unrounded, so '
        'facilities sum to the parent average. Null unless every day is generated.')
    previous_average: float | None = Field(description=
        'Average daily census across every day of `previous_month`. Unrounded, so '
        'summing facilities gives the parent average exactly. Null when that month '
        'is not completely generated.')
    previous_skilled_average: float | None = Field(description=
        'Average daily skilled census across `previous_month`, on the same terms.')


class Lookback(BaseModel):
    key: str
    label: str
    date: date


class DataStatus(BaseModel):
    available_from: date | None
    available_through: date | None
    generated_at: datetime | None


class LiveCensus(BaseModel):
    as_of: date = Field(description='The report\'s today.')
    census_date: date = Field(description=
        'The day census is read from: the latest completed day on or before `as_of`.')
    previous_month: date = Field(description='First day of the calendar month before `census_date`.')
    previous_month_days: int
    lookback: list[Lookback] = Field(description='The history columns, nearest first.')
    year_start: date
    year_end: date
    items: list[FacilityCensus]
    data_status: DataStatus
