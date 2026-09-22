from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ...common.dates import DateRange
from ...common.locations import LocationLevel, LocationSelection

DestinationType = Literal['Hospital', 'Skilled Nursing', 'Home', 'Rehab Facility',
    'Assisted Living', 'Community', 'Funeral Home']


class OverviewQuery(DateRange, LocationSelection):
    group_by: LocationLevel = 'state'
    payer_types: list[str] = Field(default_factory=list, max_length=100)
    destination_types: list[DestinationType] = Field(default_factory=list)
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
    discharges: int
    hospital_transfers: int = Field(description='Discharges to acute care.')
    ama_discharges: int = Field(description='Discharges against medical advice.')
    deceased_discharges: int
    length_of_stay_days: int = Field(description=
        'Summed length of stay. Divide by discharges rather than averaging averages.')
    average_length_of_stay: float
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


class PayerCount(BaseModel):
    payer_type: str
    discharges: int


class DestinationCount(BaseModel):
    destination_type: str
    discharges: int


class DispositionCount(BaseModel):
    """Derived from destination and the AMA measure; the four are disjoint."""
    discharge_type: str
    discharges: int


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
    by_destination: list[DestinationCount]
    by_disposition: list[DispositionCount]
    daily: list[DailyCount]
    data_status: SummaryStatus
