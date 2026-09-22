from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ...common.dates import DateRange
from ...common.locations import LocationLevel, LocationSelection


class OverviewQuery(DateRange, LocationSelection):
    group_by: LocationLevel = 'state'
    payer_types: list[str] = Field(default_factory=list, max_length=100,
        description='Restricts every measure to these payer types.')
    match_none: bool = False

    @model_validator(mode='after')
    def bounded_range(self):
        if self.days > 3660:
            raise ValueError('Choose a date range of at most 10 years.')
        return self


class Range(BaseModel):
    start: date
    end: date
    days: int


class Metrics(BaseModel):
    opening_census: int
    closing_census: int
    admissions: int
    discharges: int
    payer_changes_in: int = Field(description=
        'Moves into the selected payer types from another type. With no payer '
        'filter these equal payer_changes_out and cancel, because every move is '
        'both out of one type and into another.')
    payer_changes_out: int
    net_change: int = Field(description='closing_census - opening_census.')
    average_per_day: float


class LocationPart(BaseModel):
    level: LocationLevel
    id: str
    name: str


class LocationMetrics(Metrics):
    id: str
    name: str
    level: LocationLevel
    path: list[LocationPart]
    facility_ids: list[UUID]
    facility_count: int


class PayerMetrics(Metrics):
    payer_type: str


class DailyCount(Metrics):
    date: date


class SummaryStatus(BaseModel):
    complete: bool
    available_from: date | None
    available_through: date | None
    generated_at: datetime | None
    schema_version: int = 1


class MonthlyQuery(DateRange, LocationSelection):
    payer_types: list[str] = Field(default_factory=list, max_length=100)
    match_none: bool = False

    @model_validator(mode='after')
    def bounded_range(self):
        if self.days > 3660:
            raise ValueError('Choose a date range of at most 10 years.')
        return self


class MonthlyLocation(BaseModel):
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str


class MonthlyCount(BaseModel):
    facility_id: UUID
    month: str = Field(description='Calendar month as YYYY-MM.')
    admissions: int
    discharges: int
    net_change: int


class MonthlyDay(BaseModel):
    date: date
    value: int
    opening_census: int
    closing_census: int
    admissions: int
    discharges: int
    payer_changes_in: int
    payer_changes_out: int


class MonthlyTrendMonth(MonthlyDay):
    month: str = Field(description='Calendar month as YYYY-MM.')
    end_date: date = Field(description='Last day shown for this month.')
    days: list[MonthlyDay] = Field(description=
        'The days inside this month, for the highest and lowest day columns.')


class MonthlyTrend(BaseModel):
    months: list[MonthlyTrendMonth]


class MonthlyLocations(BaseModel):
    locations: list[MonthlyLocation]
    items: list[MonthlyCount]


class Overview(BaseModel):
    range: Range
    group_by: LocationLevel
    totals: Metrics
    locations: list[LocationMetrics]
    by_payer: list[PayerMetrics]
    daily: list[DailyCount]
    data_status: SummaryStatus
