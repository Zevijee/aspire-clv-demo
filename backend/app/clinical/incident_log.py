"""Incidents' Logs tab: one row per incident in the date range, from
incident_logs, with the same filter predicates for the page, its column filter
menus and the CSV export, as the transfer and discharge logs are built.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, case, cast, func, literal, or_, select

from shared.database.schema import (
    facilities, incident_logs as incidents, payers, portfolios, regions, residents)
from ..adt.discharges.logs import PAYER_LABELS
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.tables import PageQuery, paginate
from .coverage import latest_day

SEVERITY_LABELS = {1: 'No injury', 2: 'Minor', 3: 'Moderate', 4: 'Major', 5: 'Severe'}
resident_name = residents.c.first_name + ' ' + residents.c.last_name
hour = incidents.c.incident_hour
time_of_day = case((hour.between(6, 11), 'Morning'), (hour.between(12, 17), 'Afternoon'),
    (hour.between(18, 21), 'Evening'), else_='Night')


def columns(as_of: date):
    """The sortable, filterable columns. Still open depends on the day judged on."""
    return {
        'resident': resident_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
        'portfolio': portfolios.c.portfolio, 'region': regions.c.region,
        'incident-date': incidents.c.incident_date, 'hour': hour, 'time-of-day': time_of_day,
        'incident-type': incidents.c.incident_type,
        'severity': case(SEVERITY_LABELS, value=incidents.c.severity),
        'hospitalized': case((incidents.c.hospitalized, 'Yes'), else_='No'),
        'still-open': case((incidents.c.closed_date > literal(as_of, Date), 'Yes'), else_='No'),
        'closed-date': incidents.c.closed_date,
        'payer': case(PAYER_LABELS, value=payers.c.payer_type, else_=payers.c.payer_type),
        'payer-name': payers.c.payer_name,
    }


# Validation needs only the names; any day gives the same ones.
COLUMN_NAMES = tuple(columns(date.today()))
# Sorting by severity runs in level order, not by the names' spelling.
SORT_KEYS = {'severity': incidents.c.severity}


class LogsQuery(DateRange, PageQuery):
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)

    @field_validator('filters')
    @classmethod
    def valid_filters(cls, value):
        try:
            filters = json.loads(value)
        except ValueError:
            raise ValueError('filters must be a JSON object of selected values.') from None
        if not isinstance(filters, dict) or any(key not in COLUMN_NAMES for key in filters):
            raise ValueError('Unsupported log filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(LogsQuery):
    column: str = Field(max_length=100)


class Incident(BaseModel):
    incident_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    incident_date: date
    hour: int
    time_of_day: str
    incident_type: str
    severity: str
    hospitalized: str = Field(description='Yes when it sent the resident to a hospital.')
    still_open: str = Field(description='Yes when its investigation had not closed by the latest simulated day.')
    closed_date: date
    payer_type: str
    payer_name: str


def statement(query: LogsQuery, as_of: date, exclude=None):
    named = columns(as_of)
    result = select(incidents.c.incident_id, facilities.c.facility_id, resident_name.label('resident_name'),
        facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio, regions.c.region,
        incidents.c.incident_date, hour.label('hour'), time_of_day.label('time_of_day'), incidents.c.incident_type,
        named['severity'].label('severity'), named['hospitalized'].label('hospitalized'),
        named['still-open'].label('still_open'), incidents.c.closed_date, payers.c.payer_type, payers.c.payer_name,
    ).select_from(incidents.join(residents, residents.c.resident_id == incidents.c.resident_id)
        .join(facilities, incidents.c.facility_id == facilities.c.facility_id)
        .join(regions).join(portfolios).join(payers, incidents.c.payer_id == payers.c.payer_id)
    ).where(incidents.c.incident_date.between(query.start_date, query.end_date))
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        result = result.where(cast(named[key], String).in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(column, String).icontains(query.search.strip(), autoescape=True)
            for column in named.values())))
    return result


def _ordered(query: LogsQuery, as_of: date):
    return paginate(statement(query, as_of), query, columns={**columns(as_of), **SORT_KEYS},
        default_sort='incident-date', unique_key=incidents.c.incident_id)


def page(connection, query: LogsQuery):
    as_of = latest_day(connection)
    total = connection.scalar(select(func.count()).select_from(statement(query, as_of).subquery()))
    return dict(items=connection.execute(_ordered(query, as_of)).mappings().all(), total=total,
        limit=query.limit, offset=query.offset)


def options(connection, query: FilterQuery):
    if query.column not in COLUMN_NAMES:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    as_of = latest_day(connection)
    column = columns(as_of)[query.column]
    # Severity's menu reads in level order, like the donut.
    order = SORT_KEYS.get(query.column)
    source = statement(query, as_of, exclude=query.column)
    if order is not None:
        rows = connection.execute(source.with_only_columns(cast(column, String).label('option'), order.label('rank'))
            .distinct().order_by('rank')).all()
        return dict(options=[row.option for row in rows])
    return dict(options=list(connection.scalars(source.with_only_columns(
        cast(column, String).label('option')).distinct().order_by('option'))))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'), ('Region', 'region'),
    ('Portfolio', 'portfolio'), ('Incident date', 'incident_date'), ('Hour', 'hour'), ('Time of day', 'time_of_day'),
    ('Incident type', 'incident_type'), ('Severity', 'severity'), ('Resulted in hospitalization', 'hospitalized'),
    ('Still open', 'still_open'), ('Closed date', 'closed_date'), ('Payer type', 'payer_type'),
    ('Payer name', 'payer_name'),
)


def csv_chunks(database, query: LogsQuery):
    with database.connection() as connection:
        source = _ordered(query, latest_day(connection)).limit(None).offset(None)
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
                    if key == 'payer_type':
                        value = PAYER_LABELS.get(value, value)
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
