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
