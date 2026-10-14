"""Agency vs In-house: each facility's hours and wages in a date range split by
who worked them, agency people or the facility's own staff, per role, for the
page to add up at any drilldown level and divide once.

The overview and the trend read daily_agency_facts: one row per facility,
role and day for the whole history, drawn from the staffing facts as those
are drawn from the census, with the agency hours billing a premium over the
day's rate on top of the facts' wages. The logs read the per-person hours,
since a log names people, and those exist for the last STAFF_HOURS_DAYS days
only, so the logs' range is clamped to them as the Employees tab's is.

The agency premium is what the agency hours cost over the same hours at the
in-house rate, measured at facility and role grain -- an agency CNA against that
building's own CNAs, never against its RNs or another building -- and summed:
a parent scope's premium is its facilities' added up, never recomputed from the
scope's blended rates. A facility and role with agency hours but no in-house
hours in the range is priced against its in-house roster's average rate.
"""
import csv
from datetime import date, timedelta
import io
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Numeric, String, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_agency_facts as mix, daily_runs, daily_staff_hours as hours, facilities, portfolios, regions,
    staff_members as staff)
from shared.staffing import ROLE_CODES, STAFF_HOURS_DAYS
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from ..common.tables import PageQuery, paginate
from ..clinical.coverage import require_generated
from .employees import employee_name, role_label, window
from .ppd import ROLE_LIST, Role, TrendQuery

GENERATOR = 'agency_summary'

def coverage(connection: Connection, generator: str, query: DateRange):
    """The days the rollup has, and a 409 if the range has a day it lacks: the
    seeder's checkpoints, as every fact table's report reads them."""
    first, last = connection.execute(select(func.min(daily_runs.c.simulation_date),
        func.max(daily_runs.c.simulation_date)).where(daily_runs.c.generator == generator)).one()
    require_generated(connection, (generator,), query.start_date, query.end_date)
    return query.start_date, query.end_date, first, last

MEASURES = ('agency_hours', 'agency_wages', 'inhouse_hours', 'inhouse_wages', 'agency_premium')


class RoleSplit(BaseModel):
    agency_hours: float = Field(description='Hours worked by agency employees in the range.')
    agency_wages: float = Field(description='Pay for those hours. The agency rate is agency_wages / agency_hours.')
    inhouse_hours: float = Field(description="Hours worked by the facility's own employees: full time, part time and PRN.")
    inhouse_wages: float = Field(description='Pay for those hours. The in-house rate is inhouse_wages / inhouse_hours.')
    agency_premium: float = Field(description='What the agency hours cost over the same hours at this facility '
        "and role's in-house rate. Additive: a scope's premium is its facilities' summed.")


class FacilityAgency(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    roles: dict[str, RoleSplit] = Field(description="Each role's split, by role code.")


class AgencyReport(BaseModel):
    start_date: date = Field(description='The range shown: the request clamped to the days kept.')
    end_date: date
    available_from: date = Field(description='The first day the rollup has.')
    available_through: date
    roles: list[Role] = Field(description='Every role, in report order.')
    items: list[FacilityAgency]


def role_splits(connection: Connection, start: date, end: date) -> dict[UUID, dict[str, dict]]:
    """Each facility and role's split over the range, with its agency premium
    priced at that facility and role's in-house rate, or its in-house roster's
    average where nobody in-house worked the range. Facility and role pairs
    with no hours are absent. The Staffing Overview reads the same premiums,
    so both reports show one figure."""
    split = {}
    for row in connection.execute(select(mix.c.facility_id, mix.c.role,
            func.sum(mix.c.agency_hours, type_=Numeric).label('agency_hours'),
            func.sum(mix.c.agency_wages, type_=Numeric).label('agency_wages'),
            func.sum(mix.c.inhouse_hours, type_=Numeric).label('inhouse_hours'),
            func.sum(mix.c.inhouse_wages, type_=Numeric).label('inhouse_wages'))
            .where(mix.c.summary_date.between(start, end))
            .group_by(mix.c.facility_id, mix.c.role)).mappings():
        split.setdefault(row['facility_id'], {})[row['role']] = {
            measure: float(row[measure]) for measure in MEASURES if measure != 'agency_premium'}
    rates = roster_rates(connection)
    for facility_id, roles in split.items():
        for code, sums in roles.items():
            sums['agency_premium'] = agency_premium(sums, rates.get((facility_id, code), 0.0))
    return split


def roster_rates(connection: Connection) -> dict[tuple[UUID, str], float]:
    """Each facility and role's in-house roster average rate: what agency hours
    are priced against where nobody in-house worked the range -- never zero and
    never another role's."""
    return {(facility_id, role): float(rate) for facility_id, role, rate in connection.execute(
        select(staff.c.facility_id, staff.c.role, func.avg(staff.c.hourly_rate))
        .where(staff.c.employment_type != 'agency').group_by(staff.c.facility_id, staff.c.role))}


def agency_premium(sums: dict, roster_rate: float) -> float:
    """What one facility and role's agency hours cost over the same hours at its
    in-house rate, from its sums over a range: the in-house wages over hours, or
    the roster's rate where nobody in-house worked. Shared with the Staffing
    Overview, so both reports price it alike."""
    inhouse_rate = sums['inhouse_wages'] / sums['inhouse_hours'] if sums['inhouse_hours'] > 0 else roster_rate
    return round(sums['agency_wages'] - sums['agency_hours'] * inhouse_rate, 2)


def report(connection: Connection, query: DateRange):
    start, end, available_from, available_through = coverage(connection, GENERATOR, query)
    split = role_splits(connection, start, end)
    empty = {measure: 0.0 for measure in MEASURES}
    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        facility_id: UUID = location['facility_id']
        roles = {code: split.get(facility_id, {}).get(code, empty) for code in ROLE_CODES}
        items.append(dict(facility_id=str(facility_id), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            roles=roles))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=start, end_date=end, available_from=available_from, available_through=available_through,
        roles=ROLE_LIST, items=items)


# --- Trending ----------------------------------------------------------------

class FacilityAgencyTrend(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    agency_hours: list[float] = Field(description="Agency hours each day of the range, in the response's date order.")
    inhouse_hours: list[float] = Field(description="The facility's own employees' hours each day.")
    agency_wages: list[float] = Field(description='Pay for the agency hours each day.')


class AgencyTrend(BaseModel):
    start_date: date = Field(description='The range shown: the request clamped to the days kept.')
    end_date: date
    available_from: date
    available_through: date
    dates: list[date] = Field(description="Every day of the range, the index of each facility's arrays.")
    items: list[FacilityAgencyTrend]


def trend(connection: Connection, query: TrendQuery):
    """Every facility's agency hours, in-house hours and agency wages for each
    day of the range, over the chosen roles or all, as arrays in date order,
    for the Trending tab to add up at any drilldown level and read day by day.
    Arrays rather than a row per facility and day, as the PPD trend does: 253
    rows to place, not 30,000."""
    start, end, available_from, available_through = coverage(connection, GENERATOR, query)
    dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    index = {day: position for position, day in enumerate(dates)}
    conditions = [mix.c.summary_date.between(start, end)]
    if query.roles:
        conditions.append(mix.c.role.in_(query.roles))
    by_day = (select(mix.c.facility_id, mix.c.summary_date.label('work_date'),
            func.sum(mix.c.agency_hours, type_=Numeric).label('agency_hours'),
            func.sum(mix.c.inhouse_hours, type_=Numeric).label('inhouse_hours'),
            func.sum(mix.c.agency_wages, type_=Numeric).label('agency_wages'))
        .where(*conditions)
        .group_by(mix.c.facility_id, mix.c.summary_date).subquery())
    # aggregate_order_by: a plain keyword is ignored and the arrays come back
    # in any order, as the PPD trend found.
    ordered = lambda column: func.array_agg(aggregate_order_by(column, by_day.c.work_date))
    series = {}
    for facility_id, days, *values in connection.execute(select(by_day.c.facility_id, ordered(by_day.c.work_date),
            ordered(by_day.c.agency_hours), ordered(by_day.c.inhouse_hours), ordered(by_day.c.agency_wages))
            .group_by(by_day.c.facility_id)):
        if len(days) == len(dates) and days[0] == dates[0]:
            series[facility_id] = [[float(value) for value in column] for column in values]
        else:
            placed = [[0.0] * len(dates) for _ in values]
            for position, day in enumerate(days):
                for column, values_of in zip(placed, values):
                    column[index[day]] = float(values_of[position])
            series[facility_id] = placed
    empty = [[0.0] * len(dates)] * 3
    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        agency_hours, inhouse_hours, agency_wages = series.get(location['facility_id'], empty)
        items.append(dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            agency_hours=agency_hours, inhouse_hours=inhouse_hours, agency_wages=agency_wages))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=start, end_date=end, available_from=available_from, available_through=available_through,
        dates=dates, items=items)


# --- Logs --------------------------------------------------------------------
# One row per agency person per day worked: who, where, how long and what it
# cost. Sorting, filtering, the column menus and the CSV share one statement,
# as the Employees tab does, and the menus read the roster alone.

# The columns a menu can filter and the search reads: the roster's, never a sum.
DIMENSIONS = {
    'employee': employee_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region, 'role': role_label,
}
FILTERS = ('facility', 'state', 'portfolio', 'region', 'role')
SORTABLE = ('date', *DIMENSIONS, 'hours', 'rate', 'wages')


class LogsQuery(DateRange, PageQuery):
    # The bar's role picker; empty means every role. The table's own Role
    # column filter narrows further, by label, through `filters`.
    roles: list[Literal[ROLE_CODES]] = Field(default_factory=list, max_length=len(ROLE_CODES))
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)

    @field_validator('filters')
    @classmethod
    def valid_filters(cls, value):
        try:
            filters = json.loads(value)
        except ValueError:
            raise ValueError('filters must be a JSON object of selected values.') from None
        if not isinstance(filters, dict) or any(key not in FILTERS for key in filters):
            raise ValueError('Unsupported agency log filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class LogsFilterQuery(LogsQuery):
    column: str = Field(max_length=100)


class AgencyShift(BaseModel):
    work_date: date
    staff_id: UUID
    employee_name: str
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str
    role: str
    role_label: str
    hire_date: date = Field(description="The agency employee's first day on the roster.")
    hours: float = Field(description='Hours worked that day.')
    rate: float = Field(description='Wages over hours.')
    wages: float


class AgencyLogsPage(BaseModel):
    items: list[AgencyShift]
    total: int
    limit: int
    offset: int
    start_date: date = Field(description='The range shown: the request clamped to the days kept.')
    end_date: date
    available_from: date = Field(description=f'The first day with hours: only the last {STAFF_HOURS_DAYS} are kept.')
    available_through: date


def _dimension_filters(statement, query: LogsQuery, exclude=None):
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            statement = statement.where(cast(DIMENSIONS[key], String).in_(values))
    if query.search.strip():
        text = query.search.strip()
        statement = statement.where(or_(*(cast(column, String).icontains(text, autoescape=True)
            for column in DIMENSIONS.values())))
    return statement


def _shifts(query: LogsQuery, start: date, end: date):
    """The rows and the columns they sort by."""
    rate = (cast(hours.c.wages, Numeric) / hours.c.hours).label('rate')
    source = (hours.join(staff, staff.c.staff_id == hours.c.staff_id)
        .join(facilities, facilities.c.facility_id == hours.c.facility_id).join(regions).join(portfolios))
    statement = (select(hours.c.work_date, hours.c.staff_id, employee_name.label('employee_name'),
            hours.c.facility_id, facilities.c.facility.label('facility_name'), portfolios.c.state,
            portfolios.c.portfolio, regions.c.region, hours.c.role, role_label.label('role_label'),
            staff.c.hire_date, hours.c.hours, rate, hours.c.wages)
        .select_from(source)
        .where(hours.c.work_date.between(start, end), staff.c.employment_type == 'agency'))
    if query.roles:
        statement = statement.where(hours.c.role.in_(query.roles))
    columns = {**DIMENSIONS, 'date': hours.c.work_date, 'hours': hours.c.hours, 'rate': rate, 'wages': hours.c.wages}
    return _dimension_filters(statement, query), columns


# A row is one person on one day: the pair keeps ties from moving between
# pages, and in the sort's direction it is the order of the table's indexes on
# (work_date, staff_id), so the default date sort reads a page and stops.
SHIFT_KEY = (hours.c.work_date, hours.c.staff_id)


def logs(connection: Connection, query: LogsQuery):
    start, end, available_from, available_through = window(connection, query)
    rows, columns = _shifts(query, start, end)
    # The total counted on its own: carried on the page as a window it made
    # every page read and sort every matching row, 82,000 for 30 days of
    # overtime; counted apart, the index answers it and the page reads 50.
    total = connection.scalar(select(func.count()).select_from(rows.subquery()))
    items = connection.execute(paginate(rows, query, columns=columns, default_sort='date',
        unique_key=SHIFT_KEY)).mappings().all()
    return dict(items=items, total=total, limit=query.limit, offset=query.offset, start_date=start, end_date=end,
        available_from=available_from, available_through=available_through)


def log_options(connection: Connection, query: LogsFilterQuery):
    """A menu's options: the agency people with hours in the range, under every
    other filter and the search, from the roster alone."""
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    start, end, *_ = window(connection, query)
    worked = exists().where(hours.c.staff_id == staff.c.staff_id, hours.c.work_date.between(start, end))
    source = (select(*(column.label(key) for key, column in DIMENSIONS.items()))
        .select_from(staff.join(facilities, facilities.c.facility_id == staff.c.facility_id).join(regions).join(portfolios))
        .where(staff.c.employment_type == 'agency', worked))
    if query.roles:
        source = source.where(staff.c.role.in_(query.roles))
    source = _dimension_filters(source, query, exclude=query.column).subquery()
    return dict(options=list(connection.scalars(select(cast(source.c[query.column], String).label('option'))
        .distinct().order_by('option'))))


EXPORT_COLUMNS = (
    ('Date', 'work_date'), ('Employee', 'employee_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Portfolio', 'portfolio'), ('Region', 'region'), ('Role', 'role_label'), ('First day', 'hire_date'),
    ('Hours', 'hours'), ('Hourly rate', 'rate'), ('Wages', 'wages'),
)


def csv_chunks(database, query: LogsQuery):
    with database.connection() as connection:
        start, end, *_ = window(connection, query)
        rows, columns = _shifts(query, start, end)
        source = paginate(rows, query, columns=columns, default_sort='date',
            unique_key=SHIFT_KEY).limit(None).offset(None)
        with connection.execute(source.execution_options(yield_per=1000)) as result:
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            writer.writerow([label for label, _ in EXPORT_COLUMNS])
            yield '﻿' + buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            for row in result.mappings():
                values = []
                for _, key in EXPORT_COLUMNS:
                    value = row[key]
                    if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')):
                        value = "'" + value
                    values.append(value)
                writer.writerow(values)
                if buffer.tell() > 65536:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate(0)
            if buffer.tell():
                yield buffer.getvalue()
