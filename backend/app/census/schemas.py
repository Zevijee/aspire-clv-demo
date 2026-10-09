from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PeriodTotals(BaseModel):
    census_days: int = Field(description='Residents in a bed at the close of each day, summed over the '
        "period's days, on the selected payers. Divide by the period's `days` for its average daily census.")
    skilled_days: int = Field(description='Of `census_days`, those on a skilled payer.')


class FacilityCensus(BaseModel):
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str
    capacity: int = Field(description='Licensed beds.')
    census: int = Field(description='Residents in a bed at the close of `as_of`, on the selected payers.')
    all_census: int = Field(description='Every resident in a bed, whatever payer filter is applied. '
        "Empty beds come from this, since a bed held by another payer's resident is not empty.")
    skilled_census: int = Field(description='Of `census`, residents on a skilled payer.')
    opening_census: int = Field(description='Residents in a bed at the start of `census_date`, on the selected payers.')
    admissions: int = Field(description='Admissions on `census_date`, on the selected payers.')
    discharges: int = Field(description='Discharges on `census_date`, from the selected payers.')
    changes_in: int = Field(description='Payer changes into the selected payer types on `census_date`, from '
        'any other type. With no payer filter they move no one in or out of the facility.')
    changes_out: int = Field(description='Payer changes out of the selected payer types to any other.')
    payer_census: dict[str, int] = Field(description=
        '`census` by payer type. Types with no residents are omitted.')
    payer_daily_rates: dict[str, float] = Field(description=
        'Sum of every resident\'s daily rate on `census_date`, by payer type. Divide '
        'by the matching `payer_census` for the average rate; sum both first to '
        'average over several facilities.')
    periods: dict[str, PeriodTotals] = Field(description=
        "Each average period's sums, keyed by its `key`. Sum facilities first, then divide once.")
    previous_average: float | None = Field(description=
        'Average daily census across every day of `previous_month`. Unrounded, so '
        'summing facilities gives the parent average exactly. Null when that month '
        'is not completely generated.')
    previous_skilled_average: float | None = Field(description=
        'Average daily skilled census across `previous_month`, on the same terms.')


class Period(BaseModel):
    key: str
    label: str
    start: date
    end: date = Field(description='Inclusive.')
    days: int = Field(description='Generated days in the period: its averages divide by these.')
    average: bool = Field(description='An average over its days; false for a single day, whose value is '
        "that day's alone (start equals end).")


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
    periods: list[Period] = Field(description='What census is compared with: its real value on single '
        'earlier days first -- yesterday, and the same day a week, a month, 6 months and a year back -- then '
        'the averages over last month, the last 6 months and the last year ending yesterday, and all time.')
    items: list[FacilityCensus]
    data_status: DataStatus
