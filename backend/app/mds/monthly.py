"""Monthly Medicare PDPM Trending: each facility's PDPM resident-days and summed
actual and neutral daily rates in each calendar month of a range, from
monthly_pdpm_census_facts.

The residents are Current Medicare PDPM's: Original Medicare and Managed
Medicare PDPM on a PDPM contract. Everything is additive, so the page sums
facilities and months for any scope and divides once: average daily census is
resident-days over the month's days, rates are summed rates over resident-days.
The neutral rate is the national per diem times the summed day factors, and a
month's daily revenue its summed actual rates over its days.

Months run through the census day: the month in progress counts only its days
so far, and each month carries the days its average divides by. The rollup is
rebuilt after census_logs on every update, so it must have reached the census
day; 409 if it has not. Absence of a row means zero.
"""
from calendar import monthrange
from datetime import date

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import daily_runs, monthly_pdpm_census_facts as facts
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from .lookback import ROLLUP
from .service import GENERATOR, NATIONAL_PER_DIEM, census_day

MONTH = r'^\d{4}-(0[1-9]|1[0-2])$'


class MonthlyQuery(BaseModel):
    start_month: str = Field(pattern=MONTH, description='First month, YYYY-MM.')
    end_month: str = Field(pattern=MONTH, description='Last month, YYYY-MM, inclusive.')

    @model_validator(mode='after')
    def ordered(self):
        if self.start_month > self.end_month:
            raise ValueError('The first month must not be after the last.')
        return self


class MonthTotals(BaseModel):
    resident_days: int = Field(description='PDPM residents in a bed, summed over the month\'s days.')
    actual_rates: float = Field(description='Their daily rates, summed over the same days.')
    neutral_rates: float = Field(description='Their case-mix-neutral rates, summed over the same days.')


class Month(BaseModel):
    month: str = Field(description='The month\'s first day.')
    days: int = Field(description='Its days with census, through the census day: what its average divides by.')


class FacilityMonthly(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    months: dict[str, MonthTotals] = Field(description='Each month with PDPM residents, keyed by its first day.')


class MonthlyMedicare(BaseModel):
    census_date: date = Field(description='The latest census day: the month in progress counts through it.')
    months: list[Month] = Field(description='Every month of the range with census, oldest first.')
    items: list[FacilityMonthly]


def month_list(connection: Connection, query: MonthlyQuery, census_date: date):
    """Each month of the range that has census, and its days with census: never
    before the first generated day, never after the census day."""
    first_day = connection.scalar(select(func.min(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == GENERATOR))
    year, month = map(int, query.start_month.split('-'))
    end_year, end_month = map(int, query.end_month.split('-'))
    months = []
    while (year, month) <= (end_year, end_month):
        start = max(date(year, month, 1), first_day)
        end = min(date(year, month, monthrange(year, month)[1]), census_date)
        if start <= end:
            months.append(dict(month=date(year, month, 1).isoformat(), days=(end - start).days + 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def monthly(connection: Connection, query: MonthlyQuery, today: date):
    census_date = census_day(connection, today)
    built = connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == ROLLUP))
    if built is None or built < census_date:
        raise ApiError('summary_unavailable', 'PDPM census facts are behind the census logs. '
            'Run the seeder update.', 409)
    months = month_list(connection, query, census_date)

    totals = {}
    if months:
        for row in connection.execute(select(facts.c.facility_id, facts.c.month_start,
                func.sum(facts.c.resident_days).label('resident_days'),
                func.sum(facts.c.actual_rates).label('actual_rates'),
                func.sum(facts.c.factor_days).label('factor_days'))
                .where(facts.c.month_start.between(date.fromisoformat(months[0]['month']),
                    date.fromisoformat(months[-1]['month'])))
                .group_by(facts.c.facility_id, facts.c.month_start)).mappings():
            totals.setdefault(row['facility_id'], {})[row['month_start'].isoformat()] = dict(
                resident_days=int(row['resident_days']), actual_rates=float(row['actual_rates']),
                neutral_rates=float(NATIONAL_PER_DIEM) * float(row['factor_days']))

    items = [dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            months=totals.get(location['facility_id'], {}))
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(census_date=census_date, months=months, items=sorted(items,
        key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name'])))
