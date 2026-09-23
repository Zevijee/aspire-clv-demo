from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ...common.locations import LocationSelection


class PerformanceQuery(LocationSelection):
    """The period is the report's own, not the caller's.

    Referring hospital compares the last 3 complete months against the preceding
    24, inside 36 complete months of history. Those windows are the report's
    definition of recent and usual, so there is no date range to pass and no
    `group_by`: the grain is the hospital, and location selection narrows which
    admissions count rather than how they are grouped.
    """
    payer_types: list[str] = Field(default_factory=list, max_length=100)
    # Naming one hospital returns only that hospital, with a month series on each
    # receiving facility. The list view needs 384 hospitals and no facility
    # series; the detail view needs one hospital and all of its series.
    hospital: str | None = Field(default=None, max_length=200)
    match_none: bool = False


class ReceivingFacility(BaseModel):
    facility_id: UUID
    facility: str
    admissions: int = Field(description=
        'Admissions across the 27 months the performance comparison covers.')
    months: list[int] = Field(description=
        'Monthly admissions, aligned with the response `months`. Empty unless one '
        'hospital was requested.')


class Hospital(BaseModel):
    hospital: str
    state: str
    portfolio: str
    region: str
    months: list[int] = Field(description='Monthly admissions, aligned with `months`.')
    receiving_facilities: list[ReceivingFacility]
    recent_average: float = Field(description='Mean of the last 3 complete months.')
    usual_average: float = Field(description='Mean of the 24 months before those 3.')
    difference: float
    difference_percent: float | None = Field(description='Null when the baseline is zero.')
    previous_average: float = Field(description='Mean of the 3 months before the recent 3.')
    change_percent: float | None
    six_month_average: float
    year_average: float
    historical_average: float = Field(description='Mean of all 36 months.')
    change_vs_average: float
    previous_month_admissions: int


class PerformanceStatus(BaseModel):
    complete: bool
    available_from: date | None
    available_through: date | None
    generated_at: datetime | None
    schema_version: int = 1


class Performance(BaseModel):
    months: list[str] = Field(description='36 complete months as YYYY-MM, oldest first.')
    start_date: date
    end_date: date
    items: list[Hospital]
    data_status: PerformanceStatus
