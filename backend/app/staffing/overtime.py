"""Overtime: each facility's hours over WEEKLY_HOURS a week per person, per
role, in a date range, for the page to add up at any drilldown level and
divide once; the same hours day by day for the Trending tab; and every shift
with overtime for the Logs tab.

Overtime is a person's hours over WEEKLY_HOURS in a week, Monday to Sunday,
as the Employees tab counts it. The overview and the trend read
daily_overtime_facts: one row per facility, role and day for the whole
history, drawn from the staffing facts as those are drawn from the census,
each day's overtime a share of its hours. The logs read the per-person hours,
which carry each person's own overtime for the week spread over the days they
worked, since a log names people; those exist for the last STAFF_HOURS_DAYS
days only, so the logs' range is clamped to them as the Employees tab's is.

Wages in the facts are straight time: nothing in the data pays more for an
overtime hour. The overtime premium is what time-and-a-half would add, half
the overtime hours' straight-time pay, measured at each row and summed.
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
    daily_overtime_facts as mix, daily_runs, daily_staff_hours as hours, facilities, portfolios, regions,
    staff_members as staff)
from shared.staffing import ROLE_CODES, ROLES, STAFF_HOURS_DAYS, WEEKLY_HOURS
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from ..common.tables import PageQuery, paginate
from ..clinical.coverage import require_generated
from .employees import employee_name, role_label, type_label, window
from .ppd import Role, TrendQuery

GENERATOR = 'overtime_summary'

def coverage(connection: Connection, generator: str, query: DateRange):
    """The days the rollup has, and a 409 if the range has a day it lacks: the
    seeder's checkpoints, as every fact table's report reads them."""
    first, last = connection.execute(select(func.min(daily_runs.c.simulation_date),
        func.max(daily_runs.c.simulation_date)).where(daily_runs.c.generator == generator)).one()
    require_generated(connection, (generator,), query.start_date, query.end_date)
    return query.start_date, query.end_date, first, last

# What an overtime hour costs over straight time, as a share of its pay.
PREMIUM = 0.5
MEASURES = ('hours', 'wages', 'overtime_hours', 'overtime_wages', 'overtime_shifts')

# The straight-time pay of a row's overtime hours.
overtime_pay = hours.c.overtime_hours * cast(hours.c.wages, Numeric) / hours.c.hours


class RoleOvertime(BaseModel):
    hours: float = Field(description='Hours worked in the range.')
    wages: float = Field(description='Pay for those hours. The average rate is wages / hours.')
    overtime_hours: float = Field(description=f'Hours over {WEEKLY_HOURS} in a week per person, summed.')
    overtime_wages: float = Field(description='Straight-time pay of the overtime hours. The premium, what '
        f'time-and-a-half would add, is {PREMIUM} x this.')
    overtime_shifts: int = Field(description='Shifts with overtime in the range.')


class FacilityOvertime(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    roles: dict[str, RoleOvertime] = Field(description="Each role's sums, by role code.")


class OvertimeReport(BaseModel):
    start_date: date = Field(description='The range shown: the request clamped to the days kept.')
    end_date: date
    available_from: date = Field(description='The first day the rollup has.')
    available_through: date
    weekly_hours: int = Field(description='The weekly line overtime is counted above.')
    premium: float = Field(description='What an overtime hour costs over straight time, as a share of its pay.')
    roles: list[Role] = Field(description='Every role, in report order.')
    items: list[FacilityOvertime]


def report(connection: Connection, query: DateRange):
    start, end, available_from, available_through = coverage(connection, GENERATOR, query)
    sums = {}
    for row in connection.execute(select(mix.c.facility_id, mix.c.role,
            func.sum(mix.c.hours_worked, type_=Numeric).label('hours'),
            func.sum(mix.c.wages, type_=Numeric).label('wages'),
            func.sum(mix.c.overtime_hours, type_=Numeric).label('overtime_hours'),
            func.sum(mix.c.overtime_wages, type_=Numeric).label('overtime_wages'),
            func.sum(mix.c.overtime_shifts).label('overtime_shifts'))
            .where(mix.c.summary_date.between(start, end)).group_by(mix.c.facility_id, mix.c.role)).mappings():
        sums.setdefault(row['facility_id'], {})[row['role']] = {
            measure: (int(row[measure]) if measure == 'overtime_shifts' else float(row[measure])) for measure in MEASURES}
    empty = {measure: 0 for measure in MEASURES}
    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        roles = sums.get(location['facility_id'], {})
        items.append(dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            roles={code: roles.get(code, empty) for code in ROLE_CODES}))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=start, end_date=end, available_from=available_from, available_through=available_through,
        weekly_hours=WEEKLY_HOURS, premium=PREMIUM,
        roles=[dict(code=code, label=label, group=group) for code, label, group, *_ in ROLES], items=items)


# --- Trending ----------------------------------------------------------------

class FacilityOvertimeTrend(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    hours: list[float] = Field(description="Hours worked each day of the range, in the response's date order.")
    overtime_hours: list[float] = Field(description="Each day's overtime hours.")
    overtime_wages: list[float] = Field(description="Straight-time pay of each day's overtime hours.")


class OvertimeTrend(BaseModel):
    start_date: date = Field(description='The range shown: the request clamped to the days kept.')
    end_date: date
    available_from: date
    available_through: date
    dates: list[date] = Field(description="Every day of the range, the index of each facility's arrays.")
    items: list[FacilityOvertimeTrend]


def trend(connection: Connection, query: TrendQuery):
    """Every facility's hours, overtime hours and the overtime's straight-time
    pay for each day of the range, over the chosen roles or all, as arrays in
    date order, for the Trending tab to add up at any drilldown level and read
    day by day."""
    start, end, available_from, available_through = coverage(connection, GENERATOR, query)
    dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    index = {day: position for position, day in enumerate(dates)}
    conditions = [mix.c.summary_date.between(start, end)]
    if query.roles:
        conditions.append(mix.c.role.in_(query.roles))
    by_day = (select(mix.c.facility_id, mix.c.summary_date.label('work_date'),
            func.sum(mix.c.hours_worked, type_=Numeric).label('hours'),
            func.sum(mix.c.overtime_hours, type_=Numeric).label('overtime_hours'),
            func.sum(mix.c.overtime_wages, type_=Numeric).label('overtime_wages'))
        .where(*conditions).group_by(mix.c.facility_id, mix.c.summary_date).subquery())
    # aggregate_order_by: a plain keyword is ignored and the arrays come back
    # in any order, as the PPD trend found.
    ordered = lambda column: func.array_agg(aggregate_order_by(column, by_day.c.work_date))
    series = {}
    for facility_id, days, *values in connection.execute(select(by_day.c.facility_id, ordered(by_day.c.work_date),
            ordered(by_day.c.hours), ordered(by_day.c.overtime_hours), ordered(by_day.c.overtime_wages))
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
        worked, overtime, pay = series.get(location['facility_id'], empty)
        items.append(dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            hours=worked, overtime_hours=overtime, overtime_wages=pay))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=start, end_date=end, available_from=available_from, available_through=available_through,
        dates=dates, items=items)


# --- Logs --------------------------------------------------------------------
# One row per person per day with overtime: who, where, how much of the day
# was over the line and what it cost. Sorting, filtering, the column menus and
# the CSV share one statement, as the Employees tab does.

DIMENSIONS = {
    'employee': employee_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region, 'role': role_label,
    'employment-type': type_label,
}
FILTERS = ('facility', 'state', 'portfolio', 'region', 'role', 'employment-type')
SORTABLE = ('date', *DIMENSIONS, 'hours', 'overtime', 'rate', 'premium')


class LogsQuery(DateRange, PageQuery):
    # The bar's role picker; empty means every role.
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
            raise ValueError('Unsupported overtime log filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class LogsFilterQuery(LogsQuery):
    column: str = Field(max_length=100)


class OvertimeShift(BaseModel):
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
    employment_type: str = Field(description='Full time, Part time, PRN or Agency.')
    hours: float = Field(description='Hours worked that day.')
    overtime_hours: float = Field(description=f"The day's share of the person's hours over {WEEKLY_HOURS} that week.")
    rate: float = Field(description='Wages over hours.')
    premium: float = Field(description=f'What time-and-a-half would add: {PREMIUM} x the overtime hours at the rate.')


class OvertimeLogsPage(BaseModel):
    items: list[OvertimeShift]
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
    premium = (overtime_pay * PREMIUM).label('premium')
    source = (hours.join(staff, staff.c.staff_id == hours.c.staff_id)
        .join(facilities, facilities.c.facility_id == hours.c.facility_id).join(regions).join(portfolios))
    statement = (select(hours.c.work_date, hours.c.staff_id, employee_name.label('employee_name'),
            hours.c.facility_id, facilities.c.facility.label('facility_name'), portfolios.c.state,
            portfolios.c.portfolio, regions.c.region, hours.c.role, role_label.label('role_label'),
            type_label.label('employment_type'), hours.c.hours, hours.c.overtime_hours, rate, premium)
        .select_from(source)
        .where(hours.c.work_date.between(start, end), hours.c.overtime_hours > 0))
    if query.roles:
        statement = statement.where(hours.c.role.in_(query.roles))
    columns = {**DIMENSIONS, 'date': hours.c.work_date, 'hours': hours.c.hours,
        'overtime': hours.c.overtime_hours, 'rate': rate, 'premium': premium}
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
    """A menu's options: the people with overtime in the range, under every
    other filter and the search, from the roster alone."""
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    start, end, *_ = window(connection, query)
    worked = exists().where(hours.c.staff_id == staff.c.staff_id, hours.c.work_date.between(start, end),
        hours.c.overtime_hours > 0, *([hours.c.role.in_(query.roles)] if query.roles else []))
    source = (select(*(column.label(key) for key, column in DIMENSIONS.items()))
        .select_from(staff.join(facilities, facilities.c.facility_id == staff.c.facility_id).join(regions).join(portfolios))
        .where(worked))
    source = _dimension_filters(source, query, exclude=query.column).subquery()
    return dict(options=list(connection.scalars(select(cast(source.c[query.column], String).label('option'))
        .distinct().order_by('option'))))


EXPORT_COLUMNS = (
    ('Date', 'work_date'), ('Employee', 'employee_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Portfolio', 'portfolio'), ('Region', 'region'), ('Role', 'role_label'), ('Type', 'employment_type'),
    ('Hours', 'hours'), ('Overtime hours', 'overtime_hours'), ('Hourly rate', 'rate'), ('Overtime premium', 'premium'),
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
