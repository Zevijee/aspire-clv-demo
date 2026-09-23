from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ...common.dates import DateRange
from ...common.locations import LocationLevel, LocationSelection

SourceType = Literal['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility', 'Assisted Living', 'Community']


class OverviewQuery(DateRange, LocationSelection):
    group_by: LocationLevel = 'state'
    payer_types: list[str] = Field(default_factory=list, max_length=100)
    source_types: list[SourceType] = Field(default_factory=list)
    match_none: bool = False

    @model_validator(mode='after')
    def bounded_range(self):
        if self.days > 3660:
            raise ValueError('Choose a date range of at most 10 years.')
        return self


class MonthlyQuery(DateRange, LocationSelection):
    """Monthly admissions trending, narrowed by payer and by where they came from.

    The Monthly ADT report reads census from the payer census rollup, which has
    no source dimension and could not have one: a resident's presence in a bed
    cannot be split by the place they arrived from. Admissions can, because
    source_type is already at the grain of daily_admission_facts, so this reads
    that table instead. Verified identical: across all 48 months both tables
    report the same monthly admissions, 434,437 in total.
    """
    payer_types: list[str] = Field(default_factory=list, max_length=100)
    source_types: list[SourceType] = Field(default_factory=list)
    match_none: bool = False

    @model_validator(mode='after')
    def bounded_range(self):
        if self.days > 3660:
            raise ValueError('Choose a date range of at most 10 years.')
        return self


class MonthlyDay(BaseModel):
    date: date
    admissions: int


class MonthlyMonth(MonthlyDay):
    month: str = Field(description='Calendar month as YYYY-MM.')
    end_date: date = Field(description='Last day shown for this month.')
    days: list[MonthlyDay] = Field(description=
        'The days inside this month, for the highest and lowest day columns.')


class MonthlyTrend(BaseModel):
    months: list[MonthlyMonth]
    by_source: list['SourceCount'] = Field(description=
        'Admissions per source type across the range, ignoring the source filter '
        'so the filter shows what it is being compared against.')


class MonthlyLocation(BaseModel):
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str


class MonthlyLocationCount(BaseModel):
    facility_id: UUID
    month: str
    admissions: int


class MonthlyLocations(BaseModel):
    locations: list[MonthlyLocation]
    items: list[MonthlyLocationCount]


class Range(BaseModel):
    start: date
    end: date
    days: int


class Metrics(BaseModel):
    admissions: int
    medicaid_pending_admissions: int = Field(description=
        'Admissions that started pending Medicaid; retained after retroactive payer approval.')
    readmissions: int
    readmissions_30_day: int
    referring_hospitals: int
    average_per_day: float


class Hospital(BaseModel):
    hospital_name: str
    admissions: int


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
    hospitals: list[Hospital]


class PayerCount(BaseModel):
    payer_type: str
    admissions: int


class SourceCount(BaseModel):
    source_type: str
    admissions: int


class DailyCount(Metrics):
    date: date


class SummaryStatus(BaseModel):
    complete: bool
    available_from: date | None
    available_through: date | None
    generated_at: datetime | None
    schema_version: int = 1


class Overview(BaseModel):
    range: Range
    group_by: LocationLevel
    totals: Metrics
    locations: list[LocationMetrics]
    by_payer: list[PayerCount]
    by_source: list[SourceCount]
    hospitals: list[Hospital]
    daily: list[DailyCount]
    data_status: SummaryStatus
