"""Census days by calendar month, per facility, for Monthly Census Trending.

Read from monthly_payer_census_facts, whose census_days is every day's closing
census summed over the month -- verified equal to summing
daily_payer_census_facts by month, row for row. Census days are additive, so
the page sums facilities and months for any scope and divides once; the highest
and lowest month are picked after summing, never from facility answers.

The month in progress holds only the days generated so far, so every month
carries how many of its days are covered, and averages divide by those.
Completeness comes from the generator's checkpoints: 409 if any day in the
range is missing. Absence of a row means zero.
"""
from calendar import monthrange
from datetime import date, timedelta

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import daily_runs, monthly_payer_census_facts as months
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations

GENERATOR = 'monthly_adt_summary'
MONTH = r'^\d{4}-(0[1-9]|1[0-2])$'


class MonthlyQuery(BaseModel):
    start_month: str = Field(pattern=MONTH, description='First month, YYYY-MM.')
    end_month: str = Field(pattern=MONTH, description='Last month, YYYY-MM, inclusive.')
    # Narrows census to these payer types; empty means every payer.
    payer_types: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def ordered(self):
        if self.start_month > self.end_month:
            raise ValueError('The first month must not be after the last.')
        if self.months > 120:
            raise ValueError('Choose at most 120 months.')
        return self

    @property
    def first_day(self):
        return date.fromisoformat(f'{self.start_month}-01')

    @property
    def last_day(self):
        year, month = map(int, self.end_month.split('-'))
        return date(year, month, monthrange(year, month)[1])

    @property
    def months(self):
        (start_year, start), (end_year, end) = (map(int, value.split('-'))
            for value in (self.start_month, self.end_month))
        return (end_year - start_year) * 12 + end - start + 1


class Month(BaseModel):
    month: str = Field(description='YYYY-MM.')
    days: int = Field(description='Days of the month in the range: every day, except in the month in progress.')
    month_days: int = Field(description='Days in the calendar month.')


class FacilityMonths(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    capacity: int
    census_days: dict[str, int] = Field(description='Census days by YYYY-MM. Months with none are omitted.')
    opening_census: dict[str, int] = Field(description=
        "Census at the start of each month's first day, by YYYY-MM. Zeros are omitted.")
    closing_census: dict[str, int] = Field(description=
        "Census at the close of each month's last day in the range, by YYYY-MM. Zeros are omitted.")


class MonthlyTrend(BaseModel):
    start: date
    end: date = Field(description='The last day read: the end of the last month, or the latest generated day.')
    months: list[Month]
    items: list[FacilityMonths]


def monthly(connection: Connection, query: MonthlyQuery):
    latest = connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == GENERATOR))
    start, end = query.first_day, query.last_day
    if latest is not None:
        end = min(end, latest)
    covered = connection.scalar(select(func.count()).select_from(daily_runs).where(
        daily_runs.c.generator == GENERATOR, daily_runs.c.simulation_date.between(start, end)))
    if latest is None or end < start or covered != (end - start).days + 1:
        first = connection.scalar(select(func.min(daily_runs.c.simulation_date))
            .where(daily_runs.c.generator == GENERATOR))
        available = f'{first} through {latest}' if latest is not None else 'no completed dates'
        raise ApiError('summary_unavailable', f'Monthly census is available for {available}. '
            'The requested months include missing days. Run the seeder update or select completed months.', 409)

    conditions = [months.c.month_start.between(start, end)]
    if query.payer_types:
        conditions.append(months.c.payer_type.in_(query.payer_types))
    # Census is a level: opening and closing are the month's own boundaries,
    # never summed across months. The month in progress closes on the latest
    # generated day, which is what its row holds.
    measures = ('census_days', 'opening_census', 'closing_census')
    totals = {}
    for row in connection.execute(select(months.c.facility_id,
            func.to_char(months.c.month_start, 'YYYY-MM').label('month'),
            *(func.sum(months.c[measure]).label(measure) for measure in measures))
            .where(*conditions).group_by(months.c.facility_id, months.c.month_start)).mappings():
        facility = totals.setdefault(row['facility_id'], {measure: {} for measure in measures})
        for measure in measures:
            if row[measure]:
                facility[measure][row['month']] = int(row[measure])

    listed, cursor = [], start
    while cursor <= end:
        month_days = monthrange(cursor.year, cursor.month)[1]
        month_end = min(cursor.replace(day=month_days), end)
        listed.append(dict(month=cursor.strftime('%Y-%m'), days=(month_end - cursor).days + 1,
            month_days=month_days))
        cursor = cursor.replace(day=month_days) + timedelta(days=1)

    items = [dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            capacity=location['beds'], **totals.get(location['facility_id'], {measure: {} for measure in measures}))
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(start=start, end=end, months=listed,
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'], item['region'],
            item['facility_name'])))
