"""Census over a date range, per facility.

Census is a level, not a flow. Census days are every day's closing census summed
over the range; the average daily census divides that once by the days in the
range; occupancy divides it once more by beds. Open census is the first day's
opening and close census the last day's closing -- never a sum across days.

Every measure here sums across facilities, so parents are summed on the page,
never stored. Reads daily_payer_census_facts, the table Net Change and Live
Census read; absence of a row means zero, and completeness comes from its
generator's checkpoints.
"""
from datetime import date, timedelta
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import daily_payer_census_facts as facts, daily_runs
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from .service import GENERATOR


class TrendingQuery(DateRange):
    # Narrows census to these payer types; empty means every payer. Occupancy is
    # then the selected payers' share of beds.
    payer_types: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def bounded(self):
        if self.days > 3660:
            raise ValueError('Choose a range of at most 3,660 days.')
        return self


class FacilityTrend(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    capacity: int = Field(description='Licensed beds.')
    census_days: int = Field(description='Every day\'s closing census, summed over the range.')
    opening_census: int = Field(description='Census at the start of the first day.')
    closing_census: int = Field(description='Census at the close of the last day.')


class Range(BaseModel):
    start: date
    end: date
    days: int


class Trending(BaseModel):
    range: Range
    items: list[FacilityTrend]


class DailyQuery(TrendingQuery):
    # The facilities the chart covers, from the drilldown the page is showing.
    # Empty means every facility.
    facility_ids: list[UUID] = Field(default_factory=list, max_length=1000)


class DailyCensus(BaseModel):
    date: date
    census: int = Field(description='Closing census that day, summed over the facilities.')
    opening_census: int = Field(description='Census at the start of that day.')


class DailyTrend(BaseModel):
    range: Range
    days: list[DailyCensus]


def _require_coverage(connection: Connection, query: TrendingQuery):
    covered = connection.scalar(select(func.count()).select_from(daily_runs).where(
        daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(query.start_date, query.end_date)))
    if covered != query.days:
        first, last = connection.execute(select(func.min(daily_runs.c.simulation_date),
            func.max(daily_runs.c.simulation_date)).where(daily_runs.c.generator == GENERATOR)).one()
        available = f'{first} through {last}' if first is not None else 'no completed dates'
        raise ApiError('summary_unavailable', f'Census is available for {available}. '
            'The requested period includes missing days. Run the seeder update or select completed dates.', 409)


def _conditions(query: TrendingQuery):
    conditions = [facts.c.summary_date.between(query.start_date, query.end_date)]
    if query.payer_types:
        conditions.append(facts.c.payer_type.in_(query.payer_types))
    return conditions


def daily(connection: Connection, query: DailyQuery):
    """Closing census each day of the range, for the trend line. Every day is
    listed, zero included, because the range is known to be generated."""
    _require_coverage(connection, query)
    conditions = _conditions(query)
    if query.facility_ids:
        conditions.append(facts.c.facility_id.in_(query.facility_ids))
    totals = {row.summary_date: row for row in connection.execute(select(facts.c.summary_date,
        func.sum(facts.c.closing_census).label('census'), func.sum(facts.c.opening_census).label('opening'))
        .where(*conditions).group_by(facts.c.summary_date))}
    days = [query.start_date + timedelta(days=offset) for offset in range(query.days)]
    return dict(range=dict(start=query.start_date, end=query.end_date, days=query.days),
        days=[dict(date=day, census=totals[day].census if day in totals else 0,
            opening_census=totals[day].opening if day in totals else 0) for day in days])


def trending(connection: Connection, query: TrendingQuery):
    _require_coverage(connection, query)

    closing = facts.c.closing_census
    totals = {row['facility_id']: row for row in connection.execute(select(
        facts.c.facility_id,
        func.coalesce(func.sum(closing), 0).label('census_days'),
        func.coalesce(func.sum(facts.c.opening_census).filter(
            facts.c.summary_date == query.start_date), 0).label('opening_census'),
        func.coalesce(func.sum(closing).filter(
            facts.c.summary_date == query.end_date), 0).label('closing_census'))
        .where(*_conditions(query))
        .group_by(facts.c.facility_id)).mappings()}

    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        row = totals.get(location['facility_id'], {})
        items.append(dict(facility_id=str(location['facility_id']),
            facility_name=location['facility_name'], state=location['state'],
            portfolio=location['portfolio_name'], region=location['region_name'],
            capacity=location['beds'], census_days=row.get('census_days', 0),
            opening_census=row.get('opening_census', 0), closing_census=row.get('closing_census', 0)))
    return dict(range=dict(start=query.start_date, end=query.end_date, days=query.days),
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'],
            item['region'], item['facility_name'])))
