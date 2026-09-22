"""Every movement that changes a census, as one list.

Three event kinds share a table here: admissions and discharges from the stay,
and payer changes from the periods inside it. They are unioned in SQL rather
than merged in Python so that sorting, filtering and paging stay server side and
a page is one query.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, and_, cast, func, literal, or_, select, union_all
from sqlalchemy.sql import label

from shared.database.schema import (
    discharge_logs, facilities, payers, portfolios, regions, res_payer_stays, res_stays, residents)
from ...common.dates import DateRange
from ...common.errors import ApiError
from ...common.tables import PageQuery, paginate

PAYER_LABELS = {'medicare': 'Medicare', 'medicare_hmo': 'Medicare HMO',
    'medicare_comm': 'Commercial Medicare', 'medicaid': 'Medicaid', 'private': 'Private Pay',
    'hospice': 'Hospice', 'va': 'VA'}
MOVE_TYPES = ('Admission', 'Discharge', 'Payer change')


def _payer_label(column):
    from sqlalchemy import case
    return case(PAYER_LABELS, value=column, else_=column)


def _movements():
    """One row per census-changing event, with a description built per kind."""
    resident_name = residents.c.first_name + ' ' + residents.c.last_name
    location = (res_stays
        .join(residents, residents.c.resident_id == res_stays.c.resident_id)
        .join(facilities, facilities.c.facility_id == res_stays.c.facility_id)
        .join(regions, regions.c.region_id == facilities.c.region_id)
        .join(portfolios, portfolios.c.portfolio_id == regions.c.portfolio_id))
    common = (res_stays.c.stay_id, resident_name.label('resident_name'),
        facilities.c.facility_id, facilities.c.facility.label('facility_name'),
        portfolios.c.state, portfolios.c.portfolio, regions.c.region)

    first_period = res_payer_stays.alias('first_period')
    admissions = select(
        label('move_id', cast(res_stays.c.stay_id, String) + literal(':admission')),
        *common,
        literal('Admission').label('move_type'),
        res_stays.c.admission_date.label('move_date'),
        (literal('Admitted on ') + _payer_label(payers.c.payer_type)).label('description'),
        literal(None).cast(String).label('los_days'),
    ).select_from(location
        .join(first_period, and_(first_period.c.stay_id == res_stays.c.stay_id,
            first_period.c.period_number == 1))
        .join(payers, payers.c.payer_id == first_period.c.payer_id))

    discharges = select(
        label('move_id', cast(res_stays.c.stay_id, String) + literal(':discharge')),
        *common,
        literal('Discharge').label('move_type'),
        discharge_logs.c.discharge_date.label('move_date'),
        (literal('Discharged to ') + discharge_logs.c.destination_name).label('description'),
        cast(discharge_logs.c.los, String).label('los_days'),
    ).select_from(location.join(discharge_logs, discharge_logs.c.stay_id == res_stays.c.stay_id))

    previous = res_payer_stays.alias('previous_period')
    new_payer = payers.alias('new_payer')
    previous_payer = payers.alias('previous_payer')
    changes = select(
        label('move_id', cast(res_payer_stays.c.payer_stay_id, String) + literal(':payer')),
        *common,
        literal('Payer change').label('move_type'),
        res_payer_stays.c.start_date.label('move_date'),
        (_payer_label(previous_payer.c.payer_type) + literal(' to ')
            + _payer_label(new_payer.c.payer_type)).label('description'),
        cast(previous.c.end_date - previous.c.start_date, String).label('los_days'),
    ).select_from(location
        .join(res_payer_stays, res_payer_stays.c.stay_id == res_stays.c.stay_id)
        .join(previous, and_(previous.c.stay_id == res_payer_stays.c.stay_id,
            previous.c.period_number == res_payer_stays.c.period_number - 1))
        .join(new_payer, new_payer.c.payer_id == res_payer_stays.c.payer_id)
        .join(previous_payer, previous_payer.c.payer_id == previous.c.payer_id)
    ).where(res_payer_stays.c.period_number > 1)

    return union_all(admissions, discharges, changes).subquery('movements')


moves = _movements()
columns = {
    'resident': moves.c.resident_name, 'facility': moves.c.facility_name,
    'state': moves.c.state, 'portfolio': moves.c.portfolio, 'region': moves.c.region,
    'move-type': moves.c.move_type, 'move-date': moves.c.move_date,
    'description': moves.c.description, 'facility-id': moves.c.facility_id,
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


class Movement(BaseModel):
    move_id: str
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    move_type: str
    move_date: date
    description: str
    los_days: int | None


def statement(query: LogsQuery, exclude=None):
    result = select(moves.c.move_id, moves.c.facility_id, moves.c.resident_name,
        moves.c.facility_name, moves.c.state, moves.c.portfolio, moves.c.region,
        moves.c.move_type, moves.c.move_date, moves.c.description,
        cast(moves.c.los_days, String).label('los_days'),
    ).where(moves.c.move_date.between(query.start_date, query.end_date))
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        if key == 'facility-id':
            values = [UUID(value) for value in values]
        result = result.where(columns[key].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(column, String).icontains(query.search.strip(), autoescape=True)
            for name, column in columns.items() if name != 'facility-id')))
    return result


def page(connection, query):
    source = statement(query)
    total = connection.scalar(select(func.count()).select_from(source.subquery()))
    source = paginate(source, query, columns=columns, default_sort='move-date',
        unique_key=moves.c.move_id)
    rows = [dict(row) for row in connection.execute(source).mappings().all()]
    for row in rows:
        row['los_days'] = int(row['los_days']) if row['los_days'] is not None else None
    return dict(items=rows, total=total, limit=query.limit, offset=query.offset)


def options(connection, query: FilterQuery):
    if query.column not in columns or query.column == 'facility-id':
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    source = statement(query, exclude=query.column).with_only_columns(
        cast(columns[query.column], String).label('option')).distinct().order_by('option')
    return dict(options=list(connection.scalars(source)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Region', 'region'), ('Portfolio', 'portfolio'), ('Move type', 'move_type'),
    ('Date', 'move_date'), ('Description', 'description'), ('LOS (days)', 'los_days'),
)


def csv_chunks(database, query):
    source = paginate(statement(query), query, columns=columns, default_sort='move-date',
        unique_key=moves.c.move_id).limit(None).offset(None)
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
