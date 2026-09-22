"""Event details, table facets and CSV share the same filter predicates.

Mirrors the admissions logs module. Disposition is not a stored column: deaths
and acute transfers are implied by the destination, and only AMA carries its own
flag, so the label is assembled here from the two booleans and the destination.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, case, cast, func, or_, select

from shared.database.schema import (
    discharge_logs as logs, res_stays, residents, facilities, regions, portfolios, payers)
from ...common.dates import DateRange
from ...common.errors import ApiError
from ...common.tables import PageQuery, paginate

PAYER_LABELS = {'medicare': 'Medicare', 'medicare_hmo': 'Medicare HMO',
    'medicare_comm': 'Commercial Medicare', 'medicaid': 'Medicaid', 'private': 'Private Pay',
    'hospice': 'Hospice', 'va': 'VA'}
resident_name = residents.c.first_name + ' ' + residents.c.last_name
# The four dispositions are disjoint by construction, so the first match wins and
# every row lands in exactly one bucket.
disposition = case(
    (logs.c.is_deceased, 'Expired'),
    (logs.c.destination_type == 'Hospital', 'Transfer'),
    (logs.c.is_ama, 'AMA'),
    else_='Routine')
columns = {
    'resident': resident_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region,
    'admission-date': res_stays.c.admission_date, 'discharge-date': logs.c.discharge_date,
    'payer': case(PAYER_LABELS, value=payers.c.payer_type, else_=payers.c.payer_type),
    'payer-name': payers.c.payer_name, 'destination-type': logs.c.destination_type,
    'destination': logs.c.destination_name, 'disposition': disposition,
    'length-of-stay': logs.c.los, 'facility-id': facilities.c.facility_id,
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


class Discharge(BaseModel):
    discharge_id: UUID
    resident_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    admission_date: date
    discharge_date: date
    payer_type: str
    payer_name: str
    destination_type: str
    destination_name: str
    discharge_type: str
    is_deceased: bool
    is_ama: bool
    length_of_stay: int


def statement(query: LogsQuery, exclude=None):
    result = select(logs.c.stay_id.label('discharge_id'), residents.c.resident_id,
        facilities.c.facility_id, resident_name.label('resident_name'),
        facilities.c.facility.label('facility_name'), portfolios.c.state,
        portfolios.c.portfolio, regions.c.region, res_stays.c.admission_date,
        logs.c.discharge_date, payers.c.payer_type, payers.c.payer_name,
        logs.c.destination_type, logs.c.destination_name,
        disposition.label('discharge_type'), logs.c.is_deceased, logs.c.is_ama,
        logs.c.los.label('length_of_stay'),
    ).select_from(logs.join(res_stays).join(residents, res_stays.c.resident_id == residents.c.resident_id)
        .join(facilities, res_stays.c.facility_id == facilities.c.facility_id)
        .join(regions).join(portfolios).join(payers, logs.c.payer_id == payers.c.payer_id)
    ).where(logs.c.discharge_date.between(query.start_date, query.end_date))
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        if key == 'facility-id':
            values = [UUID(value) for value in values]
        if key == 'payer':
            values = [PAYER_LABELS.get(value, value) for value in values]
        result = result.where(columns[key].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(column, String).icontains(query.search.strip(), autoescape=True)
            for name, column in columns.items() if name != 'facility-id')))
    return result


def page(connection, query):
    source = statement(query)
    total = connection.scalar(select(func.count()).select_from(source.subquery()))
    source = paginate(source, query, columns=columns, default_sort='discharge-date', unique_key=logs.c.stay_id)
    return dict(items=connection.execute(source).mappings().all(), total=total, limit=query.limit, offset=query.offset)


def options(connection, query: FilterQuery):
    if query.column not in columns or query.column == 'facility-id':
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    source = statement(query, exclude=query.column).with_only_columns(
        cast(columns[query.column], String).label('option')).distinct().order_by('option')
    return dict(options=list(connection.scalars(source)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Region', 'region'), ('Portfolio', 'portfolio'), ('Admission date', 'admission_date'),
    ('Discharge date', 'discharge_date'), ('Payer type', 'payer_type'), ('Payer name', 'payer_name'),
    ('Discharge type', 'discharge_type'), ('Destination type', 'destination_type'),
    ('Destination', 'destination_name'), ('Length of stay (days)', 'length_of_stay'),
)


def csv_chunks(database, query):
    source = paginate(statement(query), query, columns=columns,
        default_sort='discharge-date', unique_key=logs.c.stay_id).limit(None).offset(None)
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
                    if key == 'payer_type':
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
