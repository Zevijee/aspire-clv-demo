"""The Staffing Overview's Employees tab: one row per employee with hours in the
range, from daily_staff_hours, which keeps only the last STAFF_HOURS_DAYS days.

Each person's shifts, hours, wages and overtime are summed over the range --
overtime is the stored share of each week's hours over 40 on the days worked, as
the Overtime report counts it -- and PPD is the person's hours over their
facility's census days in the range, the same census the PPD report divides by.

Every request used to sum the range's hours again before it sorted, filtered or
paged: 714,000 hour rows for 30 days, 0.33 s for the sums alone, 0.6-1.4 s a
request and 6.7 s sorted by overtime over 120 days. Now a range's rows are
built once, one per employee, and kept: sorting, filtering, search, paging, the
column menus and the CSV are then worked out from them in memory, in
milliseconds. They are kept for the last CACHE_SIZE ranges asked for and built
again as soon as the data changes -- any update or rebuild of the roster, the
hours or the bonuses (data_stamp). The API builds the default range, the last
DEFAULT_DAYS days, ahead of the first request (warm), so nobody waits for it.
"""
from collections import OrderedDict
import csv
from dataclasses import dataclass
from datetime import date, timedelta
import io
import json
import threading
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Float, Numeric, case, func, literal, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_facility_staffing_facts as census, daily_runs, daily_staff_bonuses as bonuses, daily_staff_hours as hours,
    facilities, portfolios, regions, run_history, staff_members as staff)
from shared.holidays import holidays
from shared.staffing import EMPLOYMENT_TYPES, ROLE_CODES, ROLES, STAFF_HOURS_DAYS, WEEKLY_HOURS
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.tables import PageQuery
from .premiums import HOLIDAY_PREMIUM, OVERTIME_PREMIUM

ROLE_LABELS = {code: label for code, label, *_ in ROLES}
ROLE_DEPARTMENTS = {code: department for code, _, department, *_ in ROLES}
TYPE_LABELS = {code: label for code, label, _ in EMPLOYMENT_TYPES}
# The roster's labels, in SQL: the Overtime logs label their rows with them too.
employee_name = staff.c.first_name + ' ' + staff.c.last_name
role_label = case(ROLE_LABELS, value=staff.c.role, else_=staff.c.role)
department_label = case(ROLE_DEPARTMENTS, value=staff.c.role, else_=staff.c.role)
type_label = case(TYPE_LABELS, value=staff.c.employment_type, else_=staff.c.employment_type)
# Whether the person still works here, as of today, whatever the range: a past
# range shows who has left since.
left = staff.c.termination_date <= func.current_date()

# Each filterable or searchable column, by the table's column id, and the row
# field it reads. The search reads every one of them.
DIMENSIONS = {
    'employee': 'employee_name', 'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio',
    'region': 'region', 'department': 'department', 'role': 'role_label', 'employment-type': 'employment_type',
    'status': 'status', 'agency': 'agency',
}
FILTERS = ('facility', 'state', 'portfolio', 'region', 'department', 'role', 'employment-type', 'status', 'agency')
# Each sortable column id and the row figure it sorts by.
SORT_FIELDS = {**DIMENSIONS, 'hire-date': 'hire_date', 'shifts': 'shifts', 'hours': 'hours', 'avg-shift': 'avg_shift',
    'hours-per-week': 'hours_per_week', 'overtime': 'overtime_hours', 'overtime-share': 'overtime_share', 'ppd': 'ppd',
    'rate': 'avg_rate',
    'wages': 'wages', 'overtime-premium': 'overtime_premium', 'holiday-premium': 'holiday_premium',
    'bonuses': 'bonuses'}
SORTABLE = tuple(SORT_FIELDS)
TEXT_FIELDS = set(DIMENSIONS.values())

# The ranges kept, newest last. Each is one row per employee with hours in it,
# some 45,000, about 15 MB.
CACHE_SIZE = 4
# The report's default range: the last 30 days, through today, as the page opens.
DEFAULT_DAYS = 30
# The generators whose output the rows are built from.
SOURCES = ('staff_members', 'staff_hours', 'staff_bonuses')


class EmployeesQuery(DateRange, PageQuery):
    # Empty means every role.
    roles: list[Literal[ROLE_CODES]] = Field(default_factory=list, max_length=len(ROLE_CODES))
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)
    # Only the employees with overtime in the range: the Overview's overtime window.
    overtime_only: bool = False

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
    department: str = Field(description="The role's department: Admin & General, Direct Care, Non-Nursing or Nursing Admin.")
    role: str
    role_label: str
    employment_type: str = Field(description='Full time, Part time, PRN or Agency.')
    status: str = Field(description='Active, or Left once the termination date has passed.')
    agency: str = Field(description='Yes for agency staff, No for the facility\'s own employees.')
    termination_date: date | None = Field(description='The day the employee left; null while they work here.')
    hire_date: date
    shifts: int = Field(description='Days worked in the range.')
    hours: float
    avg_shift: float = Field(description='Hours over shifts.')
    hours_per_week: float = Field(description='Hours over the weeks in the range.')
    overtime_hours: float = Field(description=f'Hours over {WEEKLY_HOURS} in a week, spread over the days worked, '
        'summed over the range, as the Overtime report counts them.')
    overtime_share: float = Field(description='Overtime hours over hours worked.')
    census_days: int = Field(description="The facility's closing census summed over the range.")
    ppd: float | None = Field(description="The employee's hours over their facility's census days.")
    avg_rate: float = Field(description='Wages over hours.')
    wages: float
    overtime_premium: float = Field(description='What the overtime hours paid over straight time: the overtime '
        f'hours at the average rate, times {OVERTIME_PREMIUM}.')
    holiday_premium: float = Field(description='What the hours on paid holidays that were not overtime paid over '
        f'straight time: their pay times {HOLIDAY_PREMIUM}, as the Staffing Overview counts it.')
    bonuses: float = Field(description='The pickup, 90-day retention and anniversary bonuses paid in the range.')


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
        raise ApiError('summary_unavailable', 'No employee hours have been generated yet. Run the seeder update.', 409)
    start, end = max(query.start_date, available_from), min(query.end_date, available_through)
    if start > end:
        raise ApiError('summary_unavailable', f'Employee hours are kept for the last {STAFF_HOURS_DAYS} days only, '
            f'{available_from} to {available_through}. Select dates in that range.', 409)
    return start, end, available_from, available_through


@dataclass(slots=True)
class Row:
    """One employee over the range: the sums, and the roster's labels."""
    staff_id: UUID
    employee_name: str
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str
    department: str
    role: str
    role_label: str
    employment_type: str
    status: str
    agency: str
    termination_date: date | None
    hire_date: date
    shifts: int
    hours: float
    wages: float
    overtime_hours: float
    holiday_wages: float
    census_days: int
    bonuses: float
    weeks: float
    # Every searchable label, lower-cased, for the search to read at once.
    text: str

    # The figures worked out from the sums, for a page or a sort.
    @property
    def avg_shift(self): return self.hours / self.shifts if self.shifts else 0.0
    @property
    def hours_per_week(self): return self.hours / self.weeks if self.weeks else 0.0
    @property
    def overtime_share(self): return self.overtime_hours / self.hours if self.hours else 0.0
    @property
    def ppd(self): return self.hours / self.census_days if self.census_days else None
    @property
    def avg_rate(self): return self.wages / self.hours if self.hours else 0.0
    @property
    def overtime_premium(self): return self.overtime_hours * self.avg_rate * OVERTIME_PREMIUM
    @property
    def holiday_premium(self): return self.holiday_wages * HOLIDAY_PREMIUM

    def item(self):
        return {name: getattr(self, name) for name in Employee.model_fields}


_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


def data_stamp(connection: Connection):
    """When the rows' sources last changed: the latest day any of them wrote, or
    the latest whole rebuild. A change means the kept rows are stale."""
    days = select(func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator.in_(SOURCES)).scalar_subquery()
    runs = select(func.max(run_history.c.completed_at)).where(run_history.c.name.in_(SOURCES)).scalar_subquery()
    return connection.execute(select(days, runs)).one()


def _build(connection: Connection, query: EmployeesQuery, start: date, end: date) -> list[Row]:
    """One row per employee with hours in the range: one statement, its sums
    grouped by person, the roster's labels joined on."""
    conditions = [hours.c.work_date.between(start, end)]
    if query.roles:
        conditions.append(hours.c.role.in_(query.roles))
    # Pay on paid holidays for the hours that were not overtime: an overtime
    # hour on a holiday earns the overtime premium only, as in the Overview.
    days_off = holidays(start, end)
    holiday_wages = (func.sum(case((hours.c.work_date.in_(days_off), hours.c.wages
            - hours.c.overtime_hours * hours.c.wages / func.nullif(hours.c.hours, 0)), else_=0), type_=Numeric)
        if days_off else literal(0, Numeric))
    # Plain numerics: left to itself SQLAlchemy keeps NUMERIC(5, 2) and a
    # 120-day total passes 999.99 hours, "numeric field overflow".
    totals = (select(hours.c.staff_id, func.count().label('shifts'),
            func.sum(hours.c.hours, type_=Numeric).label('hours'), func.sum(hours.c.wages, type_=Numeric).label('wages'),
            func.sum(hours.c.overtime_hours, type_=Numeric).label('overtime_hours'), holiday_wages.label('holiday_wages'))
        .where(*conditions).group_by(hours.c.staff_id).subquery())
    paid = (select(bonuses.c.staff_id, func.sum(bonuses.c.amount, type_=Numeric).label('bonuses'))
        .where(bonuses.c.bonus_date.between(start, end)).group_by(bonuses.c.staff_id).subquery())
    # One row per facility and day from the rollup, not a row per payer type.
    census_days = (select(census.c.facility_id, func.sum(census.c.closing_census).label('census_days'))
        .where(census.c.summary_date.between(start, end)).group_by(census.c.facility_id).subquery())
    statement = (select(staff.c.staff_id, employee_name, staff.c.facility_id, facilities.c.facility,
            portfolios.c.state, portfolios.c.portfolio, regions.c.region, staff.c.role, staff.c.employment_type,
            case((left, staff.c.termination_date)), staff.c.hire_date, totals.c.shifts,
            # Doubles, not decimals: 45,000 rows of Decimal took longer to read
            # than the statement took to run.
            *(column.cast(Float) for column in (totals.c.hours, totals.c.wages, totals.c.overtime_hours,
                totals.c.holiday_wages)),
            func.coalesce(census_days.c.census_days, 0), func.coalesce(paid.c.bonuses, 0).cast(Float))
        .select_from(totals.join(staff, staff.c.staff_id == totals.c.staff_id)
            .join(facilities, facilities.c.facility_id == staff.c.facility_id).join(regions).join(portfolios)
            .outerjoin(census_days, census_days.c.facility_id == staff.c.facility_id)
            .outerjoin(paid, paid.c.staff_id == totals.c.staff_id))
        # Ties in any sort fall back to this order: sorting is stable.
        .order_by(staff.c.staff_id))
    weeks = ((end - start).days + 1) / 7.0
    # One string object per repeated label, not one per row.
    shared: dict[str, str] = {}
    keep = lambda text: shared.setdefault(text, text)
    rows = []
    # Read through the driver's cursor: plain tuples, without a Row object each.
    compiled = statement.compile(connection, compile_kwargs={'render_postcompile': True})
    cursor = connection.connection.driver_connection.cursor()
    cursor.execute(str(compiled), compiled.params)
    for (staff_id, name, facility_id, facility, state, portfolio, region, role, kind, gone, hired, shifts, worked,
            wages, overtime, holiday, census_total, paid_bonuses) in cursor:
        labels = (name, keep(facility), keep(state), keep(portfolio), keep(region), keep(ROLE_DEPARTMENTS[role]),
            keep(ROLE_LABELS[role]), keep(TYPE_LABELS[kind]), 'Left' if gone else 'Active',
            'Yes' if kind == 'agency' else 'No')
        rows.append(Row(staff_id, name, facility_id, labels[1], labels[2], labels[3], labels[4], labels[5], role,
            labels[6], labels[7], labels[8], labels[9], gone, hired, shifts, worked, wages, overtime, holiday,
            int(census_total), paid_bonuses, weeks,
            '\x1f'.join(labels).lower()))
    return rows


def _rows(connection: Connection, query: EmployeesQuery, start: date, end: date) -> list[Row]:
    """The range's rows, from the kept ones while the data has not changed."""
    key = (start, end, tuple(sorted(query.roles)), data_stamp(connection))
    with _lock:
        rows = _cache.get(key)
        if rows is not None:
            _cache.move_to_end(key)
            return rows
    rows = _build(connection, query, start, end)
    with _lock:
        _cache[key] = rows
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return rows


def _matching(rows: list[Row], query: EmployeesQuery, exclude=None) -> list[Row]:
    """The rows under the menus' selections, all but `exclude`'s, and the search."""
    if query.overtime_only:
        rows = [row for row in rows if row.overtime_hours > 0]
    selected = [(DIMENSIONS[key], set(values)) for key, values in json.loads(query.filters).items()
        if values and key != exclude]
    text = query.search.strip().lower()
    if not selected and not text:
        return rows
    return [row for row in rows if all(getattr(row, field) in values for field, values in selected)
        and (not text or text in row.text)]


def _sorted(rows: list[Row], query: EmployeesQuery) -> list[Row]:
    """In the chosen order, a missing figure last either way, ties in staff
    order: the rows come in it and Python's sort keeps it, reversed or not."""
    field = SORT_FIELDS.get(query.sort or 'hours', 'hours')
    descending = (query.direction or 'desc') == 'desc' if query.sort else True
    casefold = field in TEXT_FIELDS
    def key(row):
        value = getattr(row, field)
        if value is None:
            return (not descending, 0)
        return (descending, value.casefold() if casefold else value)
    return sorted(rows, key=key, reverse=descending)


def warm(database) -> None:
    """Build the default range's rows ahead of the first request, if the data
    has changed since they were built; otherwise only the stamp is read."""
    with database.connection() as connection:
        today = date.today()
        query = EmployeesQuery(start_date=today - timedelta(days=DEFAULT_DAYS - 1), end_date=today)
        start, end, *_ = window(connection, query)
        _rows(connection, query, start, end)


def page(connection: Connection, query: EmployeesQuery):
    start, end, available_from, available_through = window(connection, query)
    rows = _sorted(_matching(_rows(connection, query, start, end), query), query)
    items = [row.item() for row in rows[query.offset:query.offset + query.limit]]
    return dict(items=items, total=len(rows), limit=query.limit, offset=query.offset, start_date=start, end_date=end,
        available_from=available_from, available_through=available_through)


def options(connection: Connection, query: FilterQuery):
    """A menu's options: the employees with hours in the range, under every
    other filter and the search."""
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    start, end, *_ = window(connection, query)
    field = DIMENSIONS[query.column]
    values = {getattr(row, field) for row in _matching(_rows(connection, query, start, end), query, exclude=query.column)}
    return dict(options=sorted(values, key=str.casefold))


class PackedEmployees(BaseModel):
    start_date: date
    end_date: date
    weeks: float = Field(description='The weeks in the range: hours per week is hours over these.')
    overtime_premium: float = Field(description='What an overtime hour pays over straight time, as a share.')
    facilities: list[list[str]] = Field(description='Each facility as [name, state, portfolio, region].')
    roles: dict[str, list[str]] = Field(description="Each role code's [label, department].")
    rows: list[list] = Field(description='One per employee: name, facility index, role code, type, left (0 or 1), '
        'termination date, hire date, shifts, hours, wages, overtime hours, holiday premium, bonuses.')


def packed(connection: Connection, query: DateRange):
    """Every employee with hours in the range, compactly, for a report export
    to carry: its windows filter, sort and page them in the browser. Repeated
    labels are listed once and referred to by index: 44,000 employees come to
    some 3 MB."""
    start, end, *_ = window(connection, query)
    rows = _rows(connection, EmployeesQuery(start_date=query.start_date, end_date=query.end_date), start, end)
    facilities: dict[tuple, int] = {}
    out = []
    for row in rows:
        key = (row.facility_name, row.state, row.portfolio, row.region)
        out.append([row.employee_name, facilities.setdefault(key, len(facilities)), row.role, row.employment_type,
            1 if row.status == 'Left' else 0, row.termination_date.isoformat() if row.termination_date else '',
            row.hire_date.isoformat(), row.shifts, round(row.hours, 2), round(row.wages, 2), round(row.overtime_hours, 2),
            round(row.holiday_premium, 2), round(row.bonuses, 2)])
    return dict(start_date=start, end_date=end, weeks=((end - start).days + 1) / 7.0, overtime_premium=OVERTIME_PREMIUM,
        facilities=[list(key) for key in facilities], roles={code: [ROLE_LABELS[code], ROLE_DEPARTMENTS[code]]
        for code in ROLE_CODES}, rows=out)


EXPORT_COLUMNS = (
    ('Employee', 'employee_name'), ('Status', 'status'), ('Left on', 'termination_date'), ('Facility', 'facility_name'),
    ('State', 'state'), ('Portfolio', 'portfolio'), ('Region', 'region'), ('Department', 'department'),
    ('Role', 'role_label'), ('Type', 'employment_type'), ('Agency', 'agency'), ('Hired', 'hire_date'),
    ('Avg. hourly rate', 'avg_rate'), ('Shifts', 'shifts'), ('Hours worked', 'hours'),
    ('Hours per week', 'hours_per_week'), ('Overtime hours', 'overtime_hours'),
    ('Overtime premium', 'overtime_premium'), ('Holiday premium', 'holiday_premium'), ('Bonuses', 'bonuses'),
    ('Wages', 'wages'),
)


def csv_chunks(database, query: EmployeesQuery):
    with database.connection() as connection:
        start, end, *_ = window(connection, query)
        rows = _sorted(_matching(_rows(connection, query, start, end), query), query)
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow([label for label, _ in EXPORT_COLUMNS])
    yield '﻿' + buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in rows:
        values = []
        for _, field in EXPORT_COLUMNS:
            value = getattr(row, field)
            if isinstance(value, float):
                value = round(value, 2)
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
