from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ...common.dates import DateRange
from ...common.locations import LocationLevel, LocationSelection


class OverviewQuery(DateRange, LocationSelection):
    group_by: LocationLevel = 'state'
    payer_types: list[str] = Field(default_factory=list, max_length=100,
        description='Restricts to changes that moved TO these payer types.')
    previous_payer_types: list[str] = Field(default_factory=list, max_length=100,
        description='Restricts to changes that moved FROM these payer types.')
    type_changes_only: bool = Field(default=True,
        description='Exclude plan-only moves, where the payer type did not change.')
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
    changes: int
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
    residents: int = Field(description=
        'Distinct residents with a change in this scope. Not additive across '
        'scopes: a resident who moved facility is counted in each.')


class Transition(BaseModel):
    previous_payer_type: str
    new_payer_type: str
    changes: int


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
    residents: int = Field(description='Distinct residents across the whole selection.')
    locations: list[LocationMetrics]
    transitions: list[Transition]
    daily: list[DailyCount]
    data_status: SummaryStatus
