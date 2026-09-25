"""Every resident ever admitted, with totals across all their stays.

Reads resident_summaries alone: a rollup rebuilt by each update, carrying its
own names and places. Live, the totals measured 2.1s a request; joining names
onto every row before sorting, 0.5-1.9s; from the one table, 30-150ms.

Page, filter options and CSV share one statement, so they cannot disagree.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, case, cast, func, or_, select

from shared.database.schema import resident_summaries as summaries
from ..common.dates import OptionalDate
from ..common.errors import ApiError
from ..common.tables import Page, PageQuery

# Column id -> the output column of the finished list it sorts, filters and searches.
SORTS = {
    'resident': 'resident_name', 'facility': 'facility_name', 'state': 'state',
    'portfolio': 'portfolio', 'region': 'region', 'days': 'days_in_facility',
    'stays': 'stays', 'admissions': 'admissions', 'discharges': 'discharges',
    'current': 'current_label', 'payers': 'payers',
}
FILTERS = {
    'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio',
    'region': 'region', 'current': 'current_label',
}
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region')


class SummariesQuery(PageQuery):
    # The shared filter-options client sends a date range; the report has none.
    start_date: OptionalDate = None
    end_date: OptionalDate = None
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
            raise ValueError('Unsupported resident filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(SummariesQuery):
    column: str = Field(max_length=100)


class ResidentSummary(BaseModel):
    resident_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    days_in_facility: int = Field(description='Days in a bed across every stay, through `as_of`.')
    stays: int
    admissions: int
    discharges: int
    is_current: bool = Field(description='In a bed on `as_of`.')
    payers: int = Field(description='Distinct payer plans across every stay.')


class SummariesPage(Page[ResidentSummary]):
    as_of: date | None = Field(description='The latest simulated day the totals run through.')


def _rows(query: SummariesQuery, exclude=None):
    listed = select(
        summaries.c.resident_id, summaries.c.facility_id, summaries.c.resident_name,
        summaries.c.facility_name, summaries.c.state, summaries.c.portfolio, summaries.c.region,
        summaries.c.days_in_facility, summaries.c.stays, summaries.c.admissions,
        summaries.c.discharges, summaries.c.is_current,
        case((summaries.c.is_current, 'Yes'), else_='No').label('current_label'),
        summaries.c.payers, summaries.c.as_of,
    ).subquery('listed')
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result, listed


def _ordered(query: SummariesQuery, *, with_total=False):
    result, listed = _rows(query)
    if with_total:
        # The total rides on the page, so the list is built once per request.
        result = result.add_columns(func.count().over().label('total'))
    column = listed.c[SORTS[query.sort or 'resident']]
    order = column.desc() if query.direction == 'desc' else column.asc()
    # Stable ties keep residents from moving unpredictably between pages.
    return result.order_by(order, listed.c.resident_id).limit(query.limit).offset(query.offset)


def valid_sort(query: SummariesQuery) -> bool:
    return query.sort is None or query.sort in SORTS


def page(connection, query: SummariesQuery):
    if not valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    rows = connection.execute(_ordered(query, with_total=True)).mappings().all()
    if rows:
        total = rows[0]['total']
    else:
        # An empty page past the end still needs the true total.
        result, _ = _rows(query)
        total = connection.scalar(select(func.count()).select_from(result.subquery()))
    as_of = rows[0]['as_of'] if rows else connection.scalar(select(func.max(summaries.c.as_of)))
    return dict(items=rows, total=total, limit=query.limit, offset=query.offset, as_of=as_of)


def options(connection, query: FilterQuery):
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    result, listed = _rows(query, exclude=query.column)
    source = result.with_only_columns(cast(listed.c[FILTERS[query.column]], String).label('option')).distinct()
    return dict(options=sorted(connection.scalars(source)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Portfolio', 'portfolio'), ('Region', 'region'), ('Days in facility', 'days_in_facility'),
    ('Stays', 'stays'), ('Admissions', 'admissions'), ('Discharges', 'discharges'),
    ('Currently in facility', 'is_current'), ('Payers', 'payers'),
)


def csv_chunks(database, query: SummariesQuery):
    source = _ordered(query).limit(None).offset(None)
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
