"""Hospital Transfers' Logs tab: one row per transfer in the date range, from
transfer_logs, with the same filter predicates for the page, its column filter
menus and the CSV export, as the Discharges logs are built.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, and_, case, cast, func, or_, select

from shared.database.schema import (
    facilities, payers, portfolios, regions, res_stays, residents, transfer_logs as transfers)
from ..adt.discharges.logs import PAYER_LABELS
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.tables import PageQuery, paginate
from .hospital_transfers import WITHIN_DAYS

resident_name = residents.c.first_name + ' ' + residents.c.last_name
soon = transfers.c.days_since_admission <= WITHIN_DAYS
yes_no = lambda condition: case((condition, 'Yes'), else_='No')
columns = {
    'resident': resident_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region,
    'admission-date': transfers.c.admission_date, 'transfer-date': transfers.c.transfer_date,
    # Days from admission to the transfer, as the Overview's length of stay.
    'length-of-stay': transfers.c.days_since_admission,
    'within-30-days': yes_no(soon),
    'admission-source': transfers.c.admission_source_type,
    'rehospitalization': yes_no(and_(soon, transfers.c.admission_source_type == 'Hospital')),
    'payer': case(PAYER_LABELS, value=payers.c.payer_type, else_=payers.c.payer_type),
    'payer-name': payers.c.payer_name, 'reason': transfers.c.reason, 'hospital': transfers.c.hospital_name,
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
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(LogsQuery):
    column: str = Field(max_length=100)


class Transfer(BaseModel):
    transfer_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    admission_date: date
    transfer_date: date
    length_of_stay: int
    within_30_days: str
    admission_source: str
    rehospitalization: str
    payer_type: str
    payer_name: str
    reason: str
    hospital_name: str = Field(description='The hospital the resident was transferred to.')


def statement(query: LogsQuery, exclude=None):
    result = select(transfers.c.stay_id.label('transfer_id'), facilities.c.facility_id,
        resident_name.label('resident_name'), facilities.c.facility.label('facility_name'), portfolios.c.state,
        portfolios.c.portfolio, regions.c.region, transfers.c.admission_date, transfers.c.transfer_date,
        transfers.c.days_since_admission.label('length_of_stay'), columns['within-30-days'].label('within_30_days'),
        transfers.c.admission_source_type.label('admission_source'),
        columns['rehospitalization'].label('rehospitalization'),
        payers.c.payer_type, payers.c.payer_name, transfers.c.reason, transfers.c.hospital_name,
    ).select_from(transfers.join(res_stays, res_stays.c.stay_id == transfers.c.stay_id)
        .join(residents, res_stays.c.resident_id == residents.c.resident_id)
        .join(facilities, transfers.c.facility_id == facilities.c.facility_id)
        .join(regions).join(portfolios).join(payers, transfers.c.payer_id == payers.c.payer_id)
    ).where(transfers.c.transfer_date.between(query.start_date, query.end_date))
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        result = result.where(cast(columns[key], String).in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(column, String).icontains(query.search.strip(), autoescape=True)
            for column in columns.values())))
    return result


def page(connection, query: LogsQuery):
    source = statement(query)
    total = connection.scalar(select(func.count()).select_from(source.subquery()))
    source = paginate(source, query, columns=columns, default_sort='transfer-date', unique_key=transfers.c.stay_id)
    return dict(items=connection.execute(source).mappings().all(), total=total, limit=query.limit, offset=query.offset)


def options(connection, query: FilterQuery):
    if query.column not in columns:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    source = statement(query, exclude=query.column).with_only_columns(
        cast(columns[query.column], String).label('option')).distinct().order_by('option')
    return dict(options=list(connection.scalars(source)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'), ('Region', 'region'),
    ('Portfolio', 'portfolio'), ('Admission date', 'admission_date'), ('Transfer date', 'transfer_date'),
    ('Length of stay (days)', 'length_of_stay'), ('Within 30 days', 'within_30_days'),
    ('Admitted from', 'admission_source'), ('Rehospitalization', 'rehospitalization'),
    ('Hospital', 'hospital_name'), ('Reason', 'reason'), ('Payer type', 'payer_type'), ('Payer name', 'payer_name'),
)


def csv_chunks(database, query: LogsQuery):
    source = paginate(statement(query), query, columns=columns,
        default_sort='transfer-date', unique_key=transfers.c.stay_id).limit(None).offset(None)
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
