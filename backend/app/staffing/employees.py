"""PPD's Employees tab: one row per staff member with hours in the range, from
daily_staff_hours, which keeps only the last STAFF_HOURS_DAYS days.

Each person's shifts, hours and wages are summed over the range; overtime is the
hours over 40 in each ISO week, summed; PPD is the person's hours over their
facility's census days in the range, the same census the PPD report divides by.
Sorting, filtering, the column menus and the CSV share one statement, as the
clinical logs do, and the menus read the roster alone, never the sums.
"""
import csv
from datetime import date
import io
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Float, Numeric, String, case, cast, exists, func, literal, or_, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_facility_staffing_facts as census, daily_staff_hours as hours, facilities, portfolios, regions,
    staff_members as staff)
from shared.staffing import EMPLOYMENT_TYPES, ROLE_CODES, ROLES, STAFF_HOURS_DAYS, WEEKLY_HOURS
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.tables import PageQuery, paginate

ROLE_LABELS = {code: label for code, label, *_ in ROLES}
TYPE_LABELS = {code: label for code, label, _ in EMPLOYMENT_TYPES}
employee_name = staff.c.first_name + ' ' + staff.c.last_name
role_label = case(ROLE_LABELS, value=staff.c.role, else_=staff.c.role)
type_label = case(TYPE_LABELS, value=staff.c.employment_type, else_=staff.c.employment_type)
# The columns a menu can filter and the search reads: the roster's, never a sum.
DIMENSIONS = {
    'employee': employee_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region, 'role': role_label,
    'employment-type': type_label,
}
FILTERS = ('facility', 'state', 'portfolio', 'region', 'role', 'employment-type')
SORTABLE = (*DIMENSIONS, 'hire-date', 'shifts', 'hours', 'avg-shift', 'hours-per-week', 'overtime', 'ppd',
    'rate', 'wages')


class EmployeesQuery(DateRange, PageQuery):
    # Empty means every role.
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
            raise ValueError('Unsupported employee filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(EmployeesQuery):
    column: str = Field(max_length=100)


class Employee(BaseModel):
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
    hire_date: date
    shifts: int = Field(description='Days worked in the range.')
    hours: float
    avg_shift: float = Field(description='Hours over shifts.')
    hours_per_week: float = Field(description='Hours over the weeks in the range.')
    overtime_hours: float = Field(description=f'Hours over {WEEKLY_HOURS} in a week, summed over the range.')
    census_days: int = Field(description="The facility's closing census summed over the range.")
    ppd: float | None = Field(description="The person's hours over their facility's census days.")
    avg_rate: float = Field(description='Wages over hours.')
    wages: float


class EmployeesPage(BaseModel):
    items: list[Employee]
    total: int
    limit: int
    offset: int
    start_date: date = Field(description='The range shown: the request clamped to the days kept.')
    end_date: date
    available_from: date = Field(description=f'The first day with hours: only the last {STAFF_HOURS_DAYS} are kept.')
    available_through: date


# Working memory for this request's transaction. Measured at 120 days: with the
# default 4 MB the aggregate ran in 161 batches and the sorts spilled 80 MB to
# disk each; this keeps them in memory. Local to the transaction, so nothing
# else inherits it.
WORK_MEM = '64MB'


def window(connection: Connection, query: DateRange):
    """The request's range clamped to the days kept, and the days kept. Also
    sets the transaction's working memory, since every request starts here."""
    connection.exec_driver_sql("SELECT set_config('work_mem', %s, true)", (WORK_MEM,))
    available_from, available_through = connection.execute(
        select(func.min(hours.c.work_date), func.max(hours.c.work_date))).one()
    if available_from is None:
        raise ApiError('summary_unavailable', 'No staff hours have been generated yet. Run the seeder update.', 409)
    start, end = max(query.start_date, available_from), min(query.end_date, available_through)
    if start > end:
        raise ApiError('summary_unavailable', f'Staff hours are kept for the last {STAFF_HOURS_DAYS} days only, '
            f'{available_from} to {available_through}. Select dates in that range.', 409)
    return start, end, available_from, available_through


def _hours_conditions(query: EmployeesQuery, start: date, end: date):
    conditions = [hours.c.work_date.between(start, end)]
    if query.roles:
        conditions.append(hours.c.role.in_(query.roles))
    return conditions


def _dimension_filters(statement, query: EmployeesQuery, exclude=None):
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            statement = statement.where(cast(DIMENSIONS[key], String).in_(values))
    if query.search.strip():
        text = query.search.strip()
        statement = statement.where(or_(*(cast(column, String).icontains(text, autoescape=True)
            for column in DIMENSIONS.values())))
    return statement


def _overtime(week_hours):
    """Hours over the weekly threshold, summed over weeks."""
    return func.sum(func.greatest(week_hours - literal(WEEKLY_HOURS, Numeric), literal(0, Numeric)), type_=Numeric)


def statement(query: EmployeesQuery, start: date, end: date, *, overtime_for_all: bool):
    """The rows and the columns they sort by. Overtime needs the week level of
    every hour row, 2.5M of them at 120 days, hashed into 650,000 groups; the
    page computes it for its 50 people afterwards instead (see page), and asks
    for it here only to sort by it or to export every row."""
    # The totals group the table itself by staff_id, whose distinct count the
    # planner knows, so it joins the 40,000 people by hash; grouped from a
    # weekly subquery it guessed 200 and looped.
    #
    # The sums are typed as plain numerics. Left to itself SQLAlchemy keeps the
    # column's NUMERIC(5, 2) and casts a divisor back to it for true division,
    # and a 120-day total passes 999.99 hours: "numeric field overflow".
    conditions = _hours_conditions(query, start, end)
    totals = (select(hours.c.staff_id, func.count().label('shifts'),
            func.sum(hours.c.hours, type_=Numeric).label('hours'), func.sum(hours.c.wages, type_=Numeric).label('wages'))
        .where(*conditions).group_by(hours.c.staff_id).subquery())
    # One row per facility and day from the rollup, not a row per payer type.
    census_days = (select(census.c.facility_id, func.sum(census.c.closing_census).label('census_days'))
        .where(census.c.summary_date.between(start, end)).group_by(census.c.facility_id).subquery())
    weeks = literal(((end - start).days + 1) / 7.0, Float)
    measures = {
        'hire-date': staff.c.hire_date, 'shifts': totals.c.shifts, 'hours': totals.c.hours,
        'avg-shift': totals.c.hours / totals.c.shifts, 'hours-per-week': totals.c.hours / weeks,
        'ppd': totals.c.hours / func.nullif(census_days.c.census_days, 0),
        'rate': totals.c.wages / totals.c.hours, 'wages': totals.c.wages,
    }
    source = (totals.join(staff, staff.c.staff_id == totals.c.staff_id)
        .join(facilities, facilities.c.facility_id == staff.c.facility_id).join(regions).join(portfolios)
        .outerjoin(census_days, census_days.c.facility_id == staff.c.facility_id))
    columns = [staff.c.staff_id, employee_name.label('employee_name'), staff.c.facility_id,
        facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio, regions.c.region,
        staff.c.role, role_label.label('role_label'), type_label.label('employment_type'), staff.c.hire_date,
        totals.c.shifts, totals.c.hours, measures['avg-shift'].label('avg_shift'),
        measures['hours-per-week'].label('hours_per_week'),
        func.coalesce(census_days.c.census_days, 0).label('census_days'), measures['ppd'].label('ppd'),
        measures['rate'].label('avg_rate'), totals.c.wages]
    if overtime_for_all:
        weekly = (select(hours.c.staff_id, func.date_trunc('week', hours.c.work_date).label('week'),
                func.sum(hours.c.hours, type_=Numeric).label('hours'))
            .where(*conditions).group_by(hours.c.staff_id, 'week').subquery())
        overtime = (select(weekly.c.staff_id, _overtime(weekly.c.hours).label('overtime'))
            .group_by(weekly.c.staff_id).subquery())
        source = source.outerjoin(overtime, overtime.c.staff_id == totals.c.staff_id)
        measures['overtime'] = func.coalesce(overtime.c.overtime, 0)
        columns.append(measures['overtime'].label('overtime_hours'))
    result = select(*columns).select_from(source)
    return _dimension_filters(result, query), {**DIMENSIONS, **measures}


# Each sort key's column on the page, for ordering the page again once the
# overtime of its 50 people has been added.
LABELS = {'employee': 'employee_name', 'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio',
    'region': 'region', 'role': 'role_label', 'employment-type': 'employment_type', 'hire-date': 'hire_date',
    'shifts': 'shifts', 'hours': 'hours', 'avg-shift': 'avg_shift', 'hours-per-week': 'hours_per_week',
    'overtime': 'overtime_hours', 'ppd': 'ppd', 'rate': 'avg_rate', 'wages': 'wages'}


def _roster(query: EmployeesQuery, start: date, end: date, exclude=None):
    """The roster members with hours in the range, under the dimension filters
    and the search: what the page lists, before any sum is computed."""
    # An existence probe per roster member through the (staff_id, work_date)
    # index, not a distinct over every hour row in the range.
    worked = exists().where(hours.c.staff_id == staff.c.staff_id, *_hours_conditions(query, start, end))
    source = (select(staff.c.staff_id, *(column.label(key) for key, column in DIMENSIONS.items()))
        .select_from(staff.join(facilities, facilities.c.facility_id == staff.c.facility_id).join(regions).join(portfolios))
        .where(worked))
    return _dimension_filters(source, query, exclude=exclude)


def page(connection: Connection, query: EmployeesQuery):
    start, end, available_from, available_through = window(connection, query)
    sort = query.sort or 'hours'
    by_overtime = sort == 'overtime'
    rows, columns = statement(query, start, end, overtime_for_all=by_overtime)
    # The total rides on the page, as the Residents report does, so the sums
    # are computed once per request.
    ordered = paginate(rows.add_columns(func.count().over().label('total')), query, columns=columns,
        default_sort='hours', unique_key=staff.c.staff_id)
    if not by_overtime:
        # Overtime for the page's people only: each one's weeks through the
        # (staff_id, work_date) index, a few hundred rows apiece.
        paged = ordered.subquery('page')
        # correlate: without it SQLAlchemy puts the page into this FROM as well,
        # and every person gets everyone's weeks.
        weeks = (select(func.sum(hours.c.hours, type_=Numeric).label('hours'))
            .where(hours.c.staff_id == paged.c.staff_id, *_hours_conditions(query, start, end))
            .group_by(func.date_trunc('week', hours.c.work_date)).correlate(paged)).subquery('weeks')
        overtime = (select(func.coalesce(_overtime(weeks.c.hours), literal(0, Numeric)))
            .select_from(weeks).correlate(paged).scalar_subquery())
        key = paged.c[LABELS[sort]]
        ordered = (select(paged, overtime.label('overtime_hours'))
            .order_by(key.desc() if query.direction == 'desc' else key.asc(), paged.c.staff_id))
    items = connection.execute(ordered).mappings().all()
    if items:
        total = items[0]['total']
    else:
        # An empty page past the end still needs the true total: counted from
        # the roster, never by running the sums again.
        total = connection.scalar(select(func.count()).select_from(_roster(query, start, end).subquery()))
    return dict(items=items, total=total, limit=query.limit, offset=query.offset, start_date=start, end_date=end,
        available_from=available_from, available_through=available_through)


def options(connection: Connection, query: FilterQuery):
    """A menu's options: the roster members with hours in the range, under every
    other filter and the search. The sums are never computed for a menu."""
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    start, end, *_ = window(connection, query)
    source = _roster(query, start, end, exclude=query.column).subquery()
    return dict(options=list(connection.scalars(select(cast(source.c[query.column], String).label('option'))
        .distinct().order_by('option'))))


EXPORT_COLUMNS = (
    ('Employee', 'employee_name'), ('Facility', 'facility_name'), ('State', 'state'), ('Portfolio', 'portfolio'),
    ('Region', 'region'), ('Role', 'role_label'), ('Type', 'employment_type'), ('Hired', 'hire_date'),
    ('Shifts', 'shifts'), ('Hours worked', 'hours'), ('Avg. shift', 'avg_shift'), ('Hours per week', 'hours_per_week'),
    ('Overtime hours', 'overtime_hours'), ('Census days', 'census_days'), ('PPD', 'ppd'),
    ('Avg. hourly rate', 'avg_rate'), ('Wages', 'wages'),
)


def csv_chunks(database, query: EmployeesQuery):
    with database.connection() as connection:
        start, end, *_ = window(connection, query)
        rows, columns = statement(query, start, end, overtime_for_all=True)
        source = paginate(rows, query, columns=columns, default_sort='hours',
            unique_key=staff.c.staff_id).limit(None).offset(None)
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
