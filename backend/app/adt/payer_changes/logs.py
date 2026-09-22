"""Event details, table facets and CSV share the same filter predicates.

One row per payer period that began as a change, paired with the period it moved
from. LOS is calendar days under each payer: the previous period is always
closed, and the new one runs to its end date or, while still open, to today.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, case, cast, func, or_, select

from shared.database.schema import (
    facilities, payer_change_logs as changes, payers, portfolios, regions, residents)
from ...common.dates import DateRange
from ...common.errors import ApiError
from ...common.tables import PageQuery, paginate

PAYER_LABELS = {'medicare': 'Medicare', 'medicare_hmo': 'Medicare HMO',
    'medicare_comm': 'Commercial Medicare', 'medicaid': 'Medicaid', 'private': 'Private Pay',
    'hospice': 'Hospice', 'va': 'VA'}

new_payer = payers.alias('new_payer')
previous_payer = payers.alias('previous_payer')
resident_name = residents.c.first_name + ' ' + residents.c.last_name

# A change that stays inside one payer type is a plan move, not a payer-type
# change. The overview counts only the latter; the logs can show both.
category = case((changes.c.is_type_change, 'Payer type'), else_='Plan only')
status = case((changes.c.new_end_date.is_(None), 'Ongoing'), else_='Discharged')
previous_los = changes.c.change_date - changes.c.previous_start_date
# An open period has no end date, so it is measured through today. That makes the
# value move with the calendar, which the column header states -- and is why it
# is derived here rather than stored on the log row.
new_los = func.coalesce(changes.c.new_end_date, func.current_date()) - changes.c.change_date

columns = {
    'resident': resident_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region,
    'effective-date': changes.c.change_date,
    'previous-payer': case(PAYER_LABELS, value=previous_payer.c.payer_type,
        else_=previous_payer.c.payer_type),
    'previous-payer-name': previous_payer.c.payer_name,
    'new-payer': case(PAYER_LABELS, value=new_payer.c.payer_type, else_=new_payer.c.payer_type),
    'new-payer-name': new_payer.c.payer_name,
    'category': category, 'status': status,
    'previous-los': previous_los, 'new-los': new_los,
    'facility-id': facilities.c.facility_id,
}


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
        if not isinstance(filters, dict) or any(key not in columns for key in filters):
            raise ValueError('Unsupported log filter.')
        for key, values in filters.items():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
            if key == 'facility-id':
                try:
                    [UUID(item) for item in values]
                except ValueError:
                    raise ValueError('Facility IDs must be UUIDs.') from None
        return value


class FilterQuery(LogsQuery):
    column: str = Field(max_length=100)


class PayerChange(BaseModel):
    change_id: UUID
    resident_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    effective_date: date
    previous_payer_type: str
    previous_payer_name: str
    new_payer_type: str
    new_payer_name: str
    change_category: str
    status: str
    previous_los_days: int
    new_los_days: int
    new_los_ongoing: bool


def statement(query: LogsQuery, exclude=None):
    result = select(
        changes.c.payer_stay_id.label('change_id'), changes.c.resident_id,
        changes.c.facility_id, resident_name.label('resident_name'),
        facilities.c.facility.label('facility_name'), portfolios.c.state,
        portfolios.c.portfolio, regions.c.region,
        changes.c.change_date.label('effective_date'),
        previous_payer.c.payer_type.label('previous_payer_type'),
        previous_payer.c.payer_name.label('previous_payer_name'),
        new_payer.c.payer_type.label('new_payer_type'),
        new_payer.c.payer_name.label('new_payer_name'),
        category.label('change_category'), status.label('status'),
        previous_los.label('previous_los_days'), new_los.label('new_los_days'),
        changes.c.new_end_date.is_(None).label('new_los_ongoing'),
    ).select_from(changes
        .join(residents, residents.c.resident_id == changes.c.resident_id)
        .join(facilities, facilities.c.facility_id == changes.c.facility_id)
        .join(regions, regions.c.region_id == facilities.c.region_id)
        .join(portfolios, portfolios.c.portfolio_id == regions.c.portfolio_id)
        .join(new_payer, new_payer.c.payer_id == changes.c.new_payer_id)
        .join(previous_payer, previous_payer.c.payer_id == changes.c.previous_payer_id)
    ).where(changes.c.change_date.between(query.start_date, query.end_date))
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        if key == 'facility-id':
            values = [UUID(value) for value in values]
        if key in ('previous-payer', 'new-payer'):
            values = [PAYER_LABELS.get(value, value) for value in values]
        result = result.where(columns[key].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(column, String).icontains(query.search.strip(), autoescape=True)
            for name, column in columns.items() if name != 'facility-id')))
    return result


def page(connection, query):
    source = statement(query)
    total = connection.scalar(select(func.count()).select_from(source.subquery()))
    source = paginate(source, query, columns=columns, default_sort='effective-date',
        unique_key=changes.c.payer_stay_id)
    return dict(items=connection.execute(source).mappings().all(), total=total,
        limit=query.limit, offset=query.offset)


def options(connection, query: FilterQuery):
    if query.column not in columns or query.column == 'facility-id':
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    source = statement(query, exclude=query.column).with_only_columns(
        cast(columns[query.column], String).label('option')).distinct().order_by('option')
    return dict(options=list(connection.scalars(source)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Region', 'region'), ('Portfolio', 'portfolio'), ('Effective date', 'effective_date'),
    ('Previous payer type', 'previous_payer_type'), ('Previous payer name', 'previous_payer_name'),
    ('New payer type', 'new_payer_type'), ('New payer name', 'new_payer_name'),
    ('Change category', 'change_category'), ('Status', 'status'),
    ('Previous payer LOS (days)', 'previous_los_days'), ('New payer LOS (days)', 'new_los_days'),
)


def csv_chunks(database, query):
    source = paginate(statement(query), query, columns=columns, default_sort='effective-date',
        unique_key=changes.c.payer_stay_id).limit(None).offset(None)
    with database.connection() as connection:
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
                    if key in ('previous_payer_type', 'new_payer_type'):
                        value = PAYER_LABELS.get(value, value)
                    if isinstance(value, bool):
                        value = 'Yes' if value else 'No'
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
