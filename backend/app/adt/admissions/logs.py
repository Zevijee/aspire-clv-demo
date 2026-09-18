"""Event details, table facets and CSV share the same filter predicates."""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, case, cast, func, or_, select

from shared.database.schema import admission_logs as logs, res_stays, residents, facilities, regions, portfolios, payers
from shared.database.schema import medicaid_applications as applications
from ...common.dates import DateRange
from ...common.errors import ApiError
from ...common.tables import PageQuery, paginate

PAYER_LABELS = {'medicare': 'Medicare', 'medicare_hmo': 'Medicare HMO',
    'medicare_comm': 'Commercial Medicare', 'medicaid': 'Medicaid', 'private': 'Private Pay',
    'hospice': 'Hospice', 'va': 'VA'}
resident_name = residents.c.first_name + ' ' + residents.c.last_name
columns = {
    'resident': resident_name, 'facility': facilities.c.facility, 'state': portfolios.c.state,
    'portfolio': portfolios.c.portfolio, 'region': regions.c.region, 'admission-date': logs.c.admission_date,
    'payer': case(PAYER_LABELS, value=payers.c.payer_type, else_=payers.c.payer_type),
    'payer-name': payers.c.payer_name, 'source-type': logs.c.source_type,
    'admission-source': logs.c.source_name,
    'readmission': case((logs.c.is_readmission, 'Yes'), else_='No'),
    'readmission-30-day': case((logs.c.is_30_day_readmission, 'Yes'), else_='No'),
    'facility-id': facilities.c.facility_id,
    'medicaid-pending-on-admission': case((applications.c.stay_id.is_not(None), 'Yes'), else_='No'),
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


class Admission(BaseModel):
    admission_id: UUID
    resident_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    admission_date: date
    payer_type: str
    payer_name: str
    admission_source_type: str
    admission_source_name: str
    is_readmission: bool
    is_30_day_readmission: bool
    started_medicaid_pending: bool
    medicaid_approved_date: date | None


def statement(query: LogsQuery, exclude=None):
    result = select(logs.c.stay_id.label('admission_id'), residents.c.resident_id,
        facilities.c.facility_id, resident_name.label('resident_name'),
        facilities.c.facility.label('facility_name'), portfolios.c.state,
        portfolios.c.portfolio, regions.c.region, logs.c.admission_date,
        payers.c.payer_type, payers.c.payer_name, logs.c.source_type.label('admission_source_type'),
        logs.c.source_name.label('admission_source_name'), logs.c.is_readmission, logs.c.is_30_day_readmission,
        applications.c.stay_id.is_not(None).label('started_medicaid_pending'),
        applications.c.approved_date.label('medicaid_approved_date'),
    ).select_from(logs.join(res_stays).join(residents, res_stays.c.resident_id == residents.c.resident_id)
        .join(facilities, res_stays.c.facility_id == facilities.c.facility_id)
        .join(regions).join(portfolios).join(payers, logs.c.payer_id == payers.c.payer_id)
        .outerjoin(applications, applications.c.stay_id == logs.c.stay_id)
    ).where(logs.c.admission_date.between(query.start_date, query.end_date))
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
    source = paginate(source, query, columns=columns, default_sort='admission-date', unique_key=logs.c.stay_id)
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
    ('Payer type', 'payer_type'), ('Payer name', 'payer_name'),
    ('Admission source type', 'admission_source_type'), ('Admission source name', 'admission_source_name'),
    ('Readmission', 'is_readmission'), ('Readmission within 30 days', 'is_30_day_readmission'),
    ('Started Medicaid Pending', 'started_medicaid_pending'), ('Medicaid approved date', 'medicaid_approved_date'),
)


def csv_chunks(database, query):
    source = paginate(statement(query), query, columns=columns,
        default_sort='admission-date', unique_key=logs.c.stay_id).limit(None).offset(None)
    with database.connection() as connection:
        with connection.execute(source.execution_options(yield_per=1000)) as result:
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            writer.writerow([label for label, _ in EXPORT_COLUMNS])
            yield '\ufeff' + buffer.getvalue()
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
