"""The people behind Turnover and Retention: everyone hired or leaving in a range,
one row per event, paged, sorted and filtered here, as the Employees tab is.

Read from the roster: a hire is a hire date in the range, a departure a
termination date in it, so someone hired and gone inside it has two rows. Each
departure says why (shared/turnover_reasons.py) and whether they chose to go;
each hire whether they replaced someone, and whom, or filled a new position.
Agency staff are left out, as the report leaves them out.

A range's rows are built once and kept, the last CACHE_SIZE ranges, until the
roster is rebuilt (its run is the stamp): a year is some 33,000 rows.
"""
from collections import OrderedDict
import csv
from dataclasses import dataclass
import datetime as dt
from datetime import date
import io
import json
import threading
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import aliased

from shared.database.schema import run_history, staff_members as staff
from shared.staffing import EMPLOYMENT_TYPES, ROLE_CODES, ROLES
from shared.turnover_reasons import REASON_LABELS, VOLUNTARY
from ..clinical.coverage import latest_day
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from ..common.tables import PageQuery

ROLE_LABELS = {code: label for code, label, *_ in ROLES}
ROLE_DEPARTMENTS = {code: department for code, _, department, *_ in ROLES}
TYPE_LABELS = {code: label for code, label, _ in EMPLOYMENT_TYPES}
CACHE_SIZE = 4

# Each filterable or searchable column, by the table's column id, and the row
# field it reads. The search reads every one of them.
DIMENSIONS = {
    'employee': 'employee_name', 'event': 'event', 'facility': 'facility_name', 'state': 'state',
    'portfolio': 'portfolio', 'region': 'region', 'department': 'department', 'role': 'role_label',
    'employment-type': 'employment_type', 'category': 'category', 'reason': 'reason',
}
FILTERS = ('event', 'facility', 'state', 'portfolio', 'region', 'department', 'role', 'employment-type', 'category',
    'reason')
SORT_FIELDS = {**DIMENSIONS, 'date': 'date', 'hire-date': 'hire_date', 'tenure': 'tenure_days'}
SORTABLE = tuple(SORT_FIELDS)
TEXT_FIELDS = set(DIMENSIONS.values())


class PeopleQuery(DateRange, PageQuery):
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
            raise ValueError('Unsupported filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(PeopleQuery):
    column: str = Field(max_length=100)


class TurnoverPerson(BaseModel):
    staff_id: UUID
    event: str = Field(description='Hired or Left.')
    # The type by its module: a field named date hides the name for the fields after it.
    date: dt.date = Field(description='The hire date, or the termination date: the first day no longer employed.')
    employee_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    department: str
    role: str
    role_label: str
    employment_type: str
    hire_date: dt.date
    termination_date: dt.date | None
    tenure_days: int | None = Field(description='For a departure, the days from hire to leaving.')
    category: str = Field(description='Voluntary or Involuntary for a departure; Replacement or New position for a hire.')
    reason: str = Field(description='Why they left; for a hire, whom they replaced, or New position.')


class TurnoverPeoplePage(BaseModel):
    items: list[TurnoverPerson]
    total: int
    limit: int
    offset: int


@dataclass(slots=True)
class Row:
    staff_id: UUID
    event: str
    date: date
    employee_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    department: str
    role: str
    role_label: str
    employment_type: str
    hire_date: date
    termination_date: date | None
    tenure_days: int | None
    category: str
    reason: str
    # Every searchable label, lower-cased, for the search to read at once.
    text: str

    def item(self):
        return {name: getattr(self, name) for name in TurnoverPerson.model_fields}


_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


def _stamp(connection: Connection):
    """When the roster was last built: the kept rows are stale after it."""
    return connection.scalar(select(func.max(run_history.c.completed_at)).where(run_history.c.name == 'staff_members'))


def _build(connection: Connection, start: date, end: date) -> list[Row]:
    places = {location['facility_id']: location for location in
        connection.execute(facility_locations(LocationSelection())).mappings()}
    replaced = aliased(staff)
    statement = (select(staff.c.staff_id, staff.c.facility_id, staff.c.role, staff.c.first_name, staff.c.last_name,
            staff.c.employment_type, staff.c.hire_date, staff.c.termination_date, staff.c.termination_reason,
            replaced.c.first_name, replaced.c.last_name)
        .select_from(staff.outerjoin(replaced, replaced.c.staff_id == staff.c.replaces_staff_id))
        .where(staff.c.employment_type != 'agency',
            staff.c.hire_date.between(start, end) | staff.c.termination_date.between(start, end)))
    rows = []
    for (staff_id, facility_id, role, first, last, kind, hired, left, why, before_first,
            before_last) in connection.execute(statement):
        place = places[facility_id]
        common = dict(staff_id=staff_id, employee_name=f'{first} {last}', facility_name=place['facility_name'],
            state=place['state'], portfolio=place['portfolio_name'], region=place['region_name'],
            department=ROLE_DEPARTMENTS[role], role=role, role_label=ROLE_LABELS[role],
            employment_type=TYPE_LABELS[kind], hire_date=hired, termination_date=left)
        events = []
        if start <= hired <= end:
            replacement = before_first is not None
            events.append(dict(event='Hired', date=hired, tenure_days=None,
                category='Replacement' if replacement else 'New position',
                reason=f'Replaced {before_first} {before_last}' if replacement else 'New position'))
        if left is not None and start <= left <= end:
            events.append(dict(event='Left', date=left, tenure_days=(left - hired).days,
                category='Voluntary' if VOLUNTARY.get(why) else 'Involuntary', reason=REASON_LABELS.get(why, why)))
        for event in events:
            values = {**common, **event}
            text = '\x1f'.join(str(values[field]) for field in TEXT_FIELDS).lower()
            rows.append(Row(**values, text=text))
    rows.sort(key=lambda row: (row.date, row.employee_name))
    return rows


def _rows(connection: Connection, query: DateRange) -> list[Row]:
    latest = latest_day(connection)
    if latest is None or query.end_date > latest:
        raise ApiError('summary_unavailable', f'Turnover is available through {latest}. Select completed dates.', 409)
    key = (query.start_date, query.end_date, _stamp(connection))
    with _lock:
        rows = _cache.get(key)
        if rows is not None:
            _cache.move_to_end(key)
            return rows
    rows = _build(connection, query.start_date, query.end_date)
    with _lock:
        _cache[key] = rows
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return rows


def _matching(rows: list[Row], query: PeopleQuery, exclude=None) -> list[Row]:
    """The rows of the roles asked for, under the menus' selections, all but
    `exclude`'s, and the search."""
    if query.roles:
        roles = set(query.roles)
        rows = [row for row in rows if row.role in roles]
    selected = [(DIMENSIONS[key], set(values)) for key, values in json.loads(query.filters).items()
        if values and key != exclude]
    text = query.search.strip().lower()
    if not selected and not text:
        return rows
    return [row for row in rows if all(getattr(row, field) in values for field, values in selected)
        and (not text or text in row.text)]


def _sorted(rows: list[Row], query: PeopleQuery) -> list[Row]:
    """In the chosen order, newest first by default, a missing figure last."""
    field = SORT_FIELDS.get(query.sort or 'date', 'date')
    descending = query.direction == 'desc' if query.sort else True
    casefold = field in TEXT_FIELDS

    def key(row):
        value = getattr(row, field)
        if value is None:
            return (not descending, 0)
        return (descending, value.casefold() if casefold else value)
    return sorted(rows, key=key, reverse=descending)


def page(connection: Connection, query: PeopleQuery):
    if query.sort is not None and query.sort not in SORT_FIELDS:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    rows = _sorted(_matching(_rows(connection, query), query), query)
    return dict(items=[row.item() for row in rows[query.offset:query.offset + query.limit]], total=len(rows),
        limit=query.limit, offset=query.offset)


def options(connection: Connection, query: FilterQuery):
    """A menu's options: the events in the range, under every other filter and the search."""
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    field = DIMENSIONS[query.column]
    values = {getattr(row, field) for row in _matching(_rows(connection, query), query, exclude=query.column)}
    return dict(options=sorted(values, key=str.casefold))


EXPORT_COLUMNS = (
    ('Event', 'event'), ('Date', 'date'), ('Employee', 'employee_name'), ('Facility', 'facility_name'),
    ('State', 'state'), ('Portfolio', 'portfolio'), ('Region', 'region'), ('Department', 'department'),
    ('Role', 'role_label'), ('Type', 'employment_type'), ('Hired', 'hire_date'), ('Left', 'termination_date'),
    ('Tenure (days)', 'tenure_days'), ('Category', 'category'), ('Reason', 'reason'),
)


def csv_chunks(database, query: PeopleQuery):
    with database.connection() as connection:
        rows = _sorted(_matching(_rows(connection, query), query), query)
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
