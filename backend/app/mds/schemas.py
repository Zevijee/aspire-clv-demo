from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FacilityMedicare(BaseModel):
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str
    federal: int = Field(description='Residents on Original Medicare Part A on `census_date`.')
    hmo: int = Field(description='Residents on a Medicare Advantage HMO plan.')
    commercial: int = Field(description='Residents on a Medicare Advantage PPO or other commercial plan.')
    actual_rates: float = Field(description=
        "Sum of every Medicare resident's daily rate that day, after PDPM. Divide by "
        'the residents for the average; sum both first to average over facilities.')
    neutral_rates: float = Field(description=
        'Sum of the case-mix-neutral rate for the same residents: the national per '
        "diem times each resident's PDPM day factor, with no care level or facility "
        'case-mix index.')
    resident_days: int = Field(description=
        'Sum of days from admission to `census_date` across the Medicare residents. '
        'Divide by the residents for the average length of stay.')


class DataStatus(BaseModel):
    available_from: date | None
    available_through: date | None
    generated_at: datetime | None


class CurrentMedicare(BaseModel):
    as_of: date = Field(description="The report's today.")
    census_date: date = Field(description=
        'The day read: the latest day with census logs on or before `as_of`.')
    neutral_per_diem: float = Field(description=
        'The national Medicare per diem at a case-mix index of 1.0, before PDPM day adjustment.')
    items: list[FacilityMedicare]
    data_status: DataStatus
