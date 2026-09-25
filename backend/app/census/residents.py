"""Everyone in a bed on the census day: the residents behind the census count.

Read from census_logs, whose rows are stretches in a bed at one payer and care
level: a resident is in a bed on day d when a row's in_bed contains d. Verified
to match the census facts' count and payer split. A skilled resident's rate that
day comes from pdpm_rate_logs; everyone else's from the census row.

Two materialized steps, and both matter. The day's rows are found first through
the range index -- about 27,000 of them -- and every join hangs off that. The
joined, filtered list is then built whole before it is sorted and paged. Sorting
a LIMIT query over the joins let the planner walk an index on a large table and
rescan the small set per row: one sort ran past the 30s statement timeout.
Sorting 27,000 finished rows costs milliseconds whatever the column.

Page, filter options and CSV share one statement, so they cannot disagree.
"""
import csv
from datetime import date
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, and_, case, cast, func, literal, or_, select

from shared.database.schema import (
    census_logs as logs, daily_runs, facilities, payers, pdpm_rate_logs as pdpm, portfolios,
    regions, res_payer_stays as periods, residents)
from ..common.dates import OptionalDate
from ..common.errors import ApiError
from ..common.tables import Page, PageQuery
from .service import GENERATOR

PAYER_LABELS = {'medicare': 'Medicare', 'medicare_hmo': 'Medicare HMO',
    'medicare_comm': 'Commercial Medicare', 'medicaid': 'Medicaid', 'private': 'Private Pay',
    'hospice': 'Hospice', 'va': 'VA'}
CARE_LEVEL_ORDER = ('Low', 'Moderate', 'High', 'Complex')

# Column id -> the output column of the finished list it sorts, filters and
# searches on. Labels are what the table shows, so they are what filters match.
SORTS = {
    'resident': 'resident_name', 'facility': 'facility_name', 'state': 'state',
    'portfolio': 'portfolio', 'region': 'region', 'admission-date': 'admission_date',
    'days': 'days_in_facility', 'readmission': 'readmission_label', 'care-level': 'care_level_rank',
    'payer': 'payer_label', 'payer-name': 'payer_name', 'skilled': 'skilled_label',
    'payer-since': 'payer_since', 'daily-rate': 'daily_rate',
}
FILTERS = {
    'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'readmission': 'readmission_label', 'care-level': 'care_level', 'payer': 'payer_label',
    'payer-name': 'payer_name', 'skilled': 'skilled_label',
}
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region', 'payer_label', 'payer_name')


class ResidentsQuery(PageQuery):
    # The shared filter-options client always sends a date range. Here the list
    # is one day, so end_date is that day and start_date is accepted and ignored.
    # Omitted, the day is the latest completed census day, as on the overview.
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


class FilterQuery(ResidentsQuery):
    column: str = Field(max_length=100)


class Resident(BaseModel):
    stay_id: UUID
    resident_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    admission_date: date
    days_in_facility: int = Field(description='Days from admission to the census day.')
    is_readmission: bool = Field(description='Not this resident\'s first stay.')
    care_level: str
    payer_type: str
    payer_name: str
    is_skilled: bool
    payer_since: date = Field(description='When the current payer period began.')
    daily_rate: float = Field(description='The rate for the census day, after PDPM for skilled payers.')


class ResidentsPage(Page[Resident]):
    census_date: date


def census_day(connection, query: ResidentsQuery, today: date) -> date:
    """The requested day if it was generated, otherwise the latest completed one."""
    day = query.end_date or connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == GENERATOR, daily_runs.c.simulation_date <= today))
    if day is None:
        raise ApiError('summary_unavailable', 'Census has not been generated yet.', 409)
    if not connection.scalar(select(func.count()).select_from(daily_runs).where(
            daily_runs.c.generator == 'census_logs', daily_runs.c.simulation_date == day)):
        raise ApiError('summary_unavailable', f'Census logs for {day} have not been generated. '
            'Run the seeder update.', 409)
    return day


def _rows(query: ResidentsQuery, census_date: date, exclude=None):
    """The finished, filtered list for one day, as a materialized CTE."""
    day = literal(census_date, Date)
    current = (select(logs).where(logs.c.in_bed.contains(day))
        .cte('current').prefix_with('MATERIALIZED'))
    rows = select(
        current.c.stay_id, current.c.resident_id, current.c.facility_id,
        (residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'),
        facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio,
        regions.c.region, current.c.admission_date,
        (day - current.c.admission_date).label('days_in_facility'),
        current.c.is_readmission,
        case((current.c.is_readmission, 'Yes'), else_='No').label('readmission_label'),
        current.c.care_level,
        case({level: rank for rank, level in enumerate(CARE_LEVEL_ORDER)},
            value=current.c.care_level).label('care_level_rank'),
        payers.c.payer_type, payers.c.payer_name, payers.c.is_skilled,
        case(PAYER_LABELS, value=payers.c.payer_type, else_=payers.c.payer_type).label('payer_label'),
        case((payers.c.is_skilled, 'Yes'), else_='No').label('skilled_label'),
        periods.c.start_date.label('payer_since'),
        func.coalesce(pdpm.c.daily_rate, current.c.daily_rate).label('daily_rate'),
    ).select_from(current
        .join(residents, residents.c.resident_id == current.c.resident_id)
        .join(facilities, facilities.c.facility_id == current.c.facility_id)
        .join(regions).join(portfolios)
        .join(payers, payers.c.payer_id == current.c.payer_id)
        .join(periods, periods.c.payer_stay_id == current.c.payer_stay_id)
        .outerjoin(pdpm, and_(pdpm.c.payer_stay_id == current.c.payer_stay_id,
            pdpm.c.in_effect.contains(day))))
    listed = rows.cte('listed').prefix_with('MATERIALIZED')
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result, listed


def _ordered(query: ResidentsQuery, census_date: date, *, with_total=False):
    result, listed = _rows(query, census_date)
    if with_total:
        # The total rides on the page, so the list is built once per request
        # rather than once to count and again to page.
        result = result.add_columns(func.count().over().label('total'))
    column = listed.c[SORTS[query.sort or 'resident']]
    order = column.desc() if query.direction == 'desc' else column.asc()
    # Stable ties keep residents from moving unpredictably between pages.
    return result.order_by(order, listed.c.stay_id).limit(query.limit).offset(query.offset)


def valid_sort(query: ResidentsQuery) -> bool:
    return query.sort is None or query.sort in SORTS


def page(connection, query: ResidentsQuery, today: date):
    if not valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    census_date = census_day(connection, query, today)
    rows = connection.execute(_ordered(query, census_date, with_total=True)).mappings().all()
    if rows:
        total = rows[0]['total']
    else:
        # An empty page past the end still needs the true total.
        result, _ = _rows(query, census_date)
        total = connection.scalar(select(func.count()).select_from(result.subquery()))
    return dict(items=rows, total=total, limit=query.limit, offset=query.offset, census_date=census_date)


def options(connection, query: FilterQuery, today: date):
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    census_date = census_day(connection, query, today)
    result, listed = _rows(query, census_date, exclude=query.column)
    column = listed.c[FILTERS[query.column]]
    source = result.with_only_columns(cast(column, String).label('option')).distinct()
    options = list(connection.scalars(source))
    if query.column == 'care-level':
        return dict(options=[level for level in CARE_LEVEL_ORDER if level in options])
    return dict(options=sorted(options))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Portfolio', 'portfolio'), ('Region', 'region'), ('Admission date', 'admission_date'),
    ('Days in facility', 'days_in_facility'), ('Readmission', 'is_readmission'),
    ('Care level', 'care_level'), ('Payer type', 'payer_label'), ('Payer name', 'payer_name'),
    ('Skilled', 'is_skilled'), ('Payer since', 'payer_since'), ('Daily rate', 'daily_rate'),
)


def csv_chunks(database, query: ResidentsQuery, today: date):
    with database.connection() as connection:
        census_date = census_day(connection, query, today)
        source = _ordered(query, census_date).limit(None).offset(None)
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
