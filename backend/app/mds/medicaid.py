"""Current Medicaid: Texas Medicaid residents in a bed on the census day, with
their two-letter case-mix code -- nursing and NTA -- from medicaid_assessments.

Texas pays Medicaid on the PDPM nursing and NTA components alone; Florida and
Pennsylvania use other systems and are left out until they are modelled. The
report mirrors Current Medicare PDPM without a neutral rate: Medicaid pays the
census_logs rate, which no case-mix-neutral rate compares with here.

A resident's code is the latest one coded by the census day: a change of care
level is a reassessment with a new code, and until it is coded the previous one
stands. Residents with no code yet -- the first days of a Medicaid period --
are counted as missing a care code, in no category.

Facility rows carry sums; the page divides once at any scope.
"""
import csv
from datetime import date, timedelta
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, cast, false, func, literal, or_, select, true
from sqlalchemy.engine import Connection

from shared import pdpm as pdpm_rates
from shared.database.schema import (
    census_logs as logs, daily_runs, facilities, medicaid_assessments as assessments, payers, portfolios,
    regions, residents)
from ..census.service import _back, _previous_month
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from ..common.tables import Page, PageQuery
from .service import GENERATOR, census_day

# The states whose Medicaid pays on the nursing and NTA components.
STATES = ('TX',)
NOT_CODED = 'Missing care code'
# Nursing function score bands, nursing clinical categories by nursing letter,
# and NTA bands by NTA letter -- the same parts Current Medicare PDPM counts.
NURSING = {'score_0_5': (0, 5), 'score_6_14': (6, 14), 'score_15_16': (15, 16)}
NURSING_CATEGORY = {field: letters for field, _, letters in pdpm_rates.NURSING_CATEGORIES}
NTA = {'points_0': 'F', 'points_1_2': 'E', 'points_3_5': 'D', 'points_6_8': 'C', 'points_9_11': 'B',
    'points_12_plus': 'A'}


def _current(day):
    """Every Texas Medicaid resident in a bed on the day, with the latest code
    coded by then. The day's Medicaid rows are found first, in one pass of the
    in_bed range index; joined straight to the location tables, PostgreSQL
    repeated that scan once per Texas facility -- 164 times -- and took 1.8 s."""
    day_rows = (select(logs.c.payer_stay_id, logs.c.stay_id, logs.c.resident_id, logs.c.facility_id,
            logs.c.payer_id, logs.c.admission_date, logs.c.daily_rate)
        .select_from(logs.join(payers, payers.c.payer_id == logs.c.payer_id))
        .where(logs.c.in_bed.contains(day), payers.c.payer_type == 'medicaid')
        .cte('day_rows').prefix_with('MATERIALIZED'))
    code = (select(assessments.c.code, assessments.c.nursing_function_score, assessments.c.ard)
        .where(assessments.c.payer_stay_id == day_rows.c.payer_stay_id, assessments.c.coded_date <= day)
        .order_by(assessments.c.coded_date.desc()).limit(1).lateral('code'))
    return (select(day_rows, code.c.code, code.c.nursing_function_score, code.c.ard,
            facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio, regions.c.region,
            payers.c.payer_name)
        .select_from(day_rows
            .join(payers, payers.c.payer_id == day_rows.c.payer_id)
            .join(facilities, facilities.c.facility_id == day_rows.c.facility_id)
            .join(regions).join(portfolios)
            .outerjoin(code, true()))
        .where(portfolios.c.state.in_(STATES))
        .cte('current').prefix_with('MATERIALIZED'))


def _part_conditions(rows):
    """Label -> condition for every part of every category, in page order. Labels
    are "Category: part" as the page names them, so a chart click can open one."""
    nursing, nta = func.substr(rows.c.code, 1, 1), func.substr(rows.c.code, 2, 1)
    parts = {}
    for (low, high), label in zip(NURSING.values(), ('0-5', '6-14', '15-16')):
        parts[f'Nursing: {label}'] = rows.c.nursing_function_score.between(low, high)
    for _, name, letters in pdpm_rates.NURSING_CATEGORIES:
        parts[f'Nursing Category: {name}'] = nursing.in_(list(letters))
    for letter, label in zip(NTA.values(), ('0', '1-2', '3-5', '6-8', '9-11', '12+')):
        parts[f'NTA: {label}'] = nta == letter
    return parts


class Overview(BaseModel):
    census_date: date
    items: list[dict] = Field(description='Per Texas facility: residents, summed daily rates and days since '
        'admission, the residents not yet coded and their days, and the coded residents counted by nursing '
        'function score band, nursing category and NTA band.')


def overview(connection: Connection, today: date):
    census_date = census_day(connection, today)
    day = literal(census_date, Date)
    current = _current(day)
    nursing, nta = func.substr(current.c.code, 1, 1), func.substr(current.c.code, 2, 1)
    coded = current.c.code.is_not(None)
    columns = [func.count().label('residents'), func.sum(current.c.daily_rate).label('actual_rates'),
        func.sum(day - current.c.admission_date).label('resident_days'),
        func.count().filter(~coded).label('no_score'),
        func.coalesce(func.sum(day - current.c.admission_date).filter(~coded), 0).label('no_score_days')]
    columns += [func.count().filter(current.c.nursing_function_score.between(low, high)).label(f'nursing.{field}')
        for field, (low, high) in NURSING.items()]
    columns += [func.count().filter(nursing.in_(list(letters))).label(f'nursing_category.{field}')
        for field, letters in NURSING_CATEGORY.items()]
    columns += [func.count().filter(nta == letter).label(f'nta.{field}') for field, letter in NTA.items()]
    totals = {row['facility_id']: row for row in connection.execute(
        select(current.c.facility_id, *columns).group_by(current.c.facility_id)).mappings()}

    def item(location):
        row = totals.get(location['facility_id'], {})
        get = lambda key: row.get(key, 0) or 0
        return dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            residents=get('residents'), actual_rates=float(get('actual_rates')), resident_days=int(get('resident_days')),
            no_score=get('no_score'), no_score_days=int(get('no_score_days')),
            nursing={field: get(f'nursing.{field}') for field in NURSING},
            nursing_category={field: get(f'nursing_category.{field}') for field in NURSING_CATEGORY},
            nta={field: get(f'nta.{field}') for field in NTA})
    items = [item(location) for location in connection.execute(facility_locations(LocationSelection())).mappings()
        if location['state'] in STATES]
    return dict(census_date=census_date, items=sorted(items,
        key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name'])))


# --- Look-back -------------------------------------------------------------

def lookback(connection: Connection, today: date):
    """Each facility's Medicaid resident-days and summed daily rates today and
    averaged over last month, the last 6 months, the last year and all time, as
    Current Medicare PDPM's look-back defines them. Read from the census rows
    alone: a Medicaid resident's rate is the census row's, with no steps."""
    census_date = census_day(connection, today)
    yesterday = census_date - timedelta(days=1)
    first = connection.scalar(select(func.min(daily_runs.c.simulation_date)).where(daily_runs.c.generator == GENERATOR))
    month_start, month_end = _previous_month(census_date)
    spans = [('today', 'Today', census_date, census_date),
        ('month', 'Last month avg.', month_start, month_end),
        ('month_6', 'Last 6 months avg.', _back(census_date, months=6), yesterday),
        ('year', 'Last year avg.', _back(census_date, months=12), yesterday),
        ('all_time', 'All time avg.', first, yesterday)]
    spans = [(key, label, max(start, first), end) for key, label, start, end in spans if end >= max(start, first)]
    generated = dict(connection.execute(select(*(
        func.count().filter(daily_runs.c.simulation_date.between(start, end)).label(key)
        for key, _, start, end in spans)).where(daily_runs.c.generator == GENERATOR)).one()._mapping)
    through = literal(census_date + timedelta(days=1), Date)
    rows = (select(logs.c.facility_id, logs.c.daily_rate, func.lower(logs.c.in_bed).label('starts'),
            func.least(func.upper(logs.c.in_bed), through).label('ends'))
        .select_from(logs.join(payers, payers.c.payer_id == logs.c.payer_id)
            .join(facilities, facilities.c.facility_id == logs.c.facility_id).join(regions).join(portfolios))
        .where(payers.c.payer_type == 'medicaid', portfolios.c.state.in_(STATES)).subquery('rows'))

    def days_in(start, end):
        return func.greatest(func.least(rows.c.ends, literal(end + timedelta(days=1), Date))
            - func.greatest(rows.c.starts, literal(start, Date)), 0)
    columns = []
    for key, _, start, end in spans:
        days = days_in(start, end)
        columns += [func.sum(days).label(f'{key}_days'), func.sum(days * rows.c.daily_rate).label(f'{key}_actual')]
    totals = {row['facility_id']: row for row in connection.execute(
        select(rows.c.facility_id, *columns).group_by(rows.c.facility_id)).mappings()}
    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        if location['state'] not in STATES:
            continue
        row = totals.get(location['facility_id'])
        items.append(dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            periods={key: dict(resident_days=int(row[f'{key}_days'] or 0) if row else 0,
                actual_rates=float(row[f'{key}_actual'] or 0) if row else 0.0) for key, _, _, _ in spans}))
    return dict(census_date=census_date,
        periods=[dict(key=key, label=label, start=start, end=end, days=generated[key]) for key, label, start, end in spans],
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name'])))


# --- Residents -------------------------------------------------------------

SORTS = {'resident': 'resident_name', 'facility': 'facility_name', 'payer-name': 'payer_name',
    'admission-date': 'admission_date', 'los': 'length_of_stay', 'ard': 'ard', 'code': 'code_sort',
    'daily-rate': 'daily_rate', 'total-revenue': 'total_revenue'}
FILTERS = {'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'payer-name': 'payer_name', 'code': 'case_mix_code'}
CATEGORY_FILTER = 'medicaid-category'
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region', 'payer_name', 'case_mix_code')


class ResidentsQuery(PageQuery):
    # The shared filter-options client sends a date range; this list is always
    # the census day, so both are accepted and ignored.
    start_date: str | None = Field(default=None, max_length=20)
    end_date: str | None = Field(default=None, max_length=20)
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)

    @field_validator('filters')
    @classmethod
    def valid_filters(cls, value):
        try:
            filters = json.loads(value)
        except ValueError:
            raise ValueError('filters must be a JSON object of selected values.') from None
        if not isinstance(filters, dict) or any(key not in FILTERS and key != CATEGORY_FILTER for key in filters):
            raise ValueError('Unsupported resident filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(ResidentsQuery):
    column: str = Field(max_length=100)


class MedicaidResident(BaseModel):
    stay_id: UUID
    payer_stay_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    payer_name: str
    admission_date: date
    length_of_stay: int = Field(description='Days from admission to the census day.')
    ard: date | None = Field(description="The current code's assessment reference date; null until coded.")
    case_mix_code: str = Field(description='Two letters, nursing and NTA, or "Missing care code" until coded.')
    daily_rate: float = Field(description='The Medicaid rate on the census day.')
    total_revenue: float = Field(description='Medicaid revenue on this payer through the census day.')


class ResidentsPage(Page[MedicaidResident]):
    census_date: date


def _filtered(listed, query: ResidentsQuery, exclude=None):
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        if key == CATEGORY_FILTER:
            parts = _part_conditions(listed)
            result = result.where(or_(false(), *(parts[value] for value in values if value in parts)))
        else:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result


def _rows(query: ResidentsQuery, census_date: date, *, with_revenue=True):
    day = literal(census_date, Date)
    current = _current(day)
    columns = [current.c.stay_id, current.c.payer_stay_id, current.c.facility_name, current.c.state,
        current.c.portfolio, current.c.region, current.c.payer_name, current.c.code, current.c.nursing_function_score,
        func.coalesce(current.c.code, NOT_CODED).label('case_mix_code'),
        # The raw code, null while missing, so Missing care code sorts last.
        current.c.code.label('code_sort')]
    source = current
    if with_revenue or query.search.strip():
        source = source.join(residents, residents.c.resident_id == current.c.resident_id)
        columns.append((residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'))
    if with_revenue:
        # This payer period's census rows through the census day, each its rate
        # times its days: Medicaid has no rate steps.
        through = literal(census_date + timedelta(days=1), Date)
        segment_days = func.least(func.upper(logs.c.in_bed), through) - func.lower(logs.c.in_bed)
        revenue = (select(func.coalesce(func.sum(logs.c.daily_rate * segment_days), 0).label('total_revenue'))
            .where(logs.c.payer_stay_id == current.c.payer_stay_id, func.lower(logs.c.in_bed) <= day)
            .lateral('revenue'))
        source = source.join(revenue, true())
        columns += [current.c.admission_date, (day - current.c.admission_date).label('length_of_stay'),
            current.c.ard, current.c.daily_rate, revenue.c.total_revenue]
    listed = select(*columns).select_from(source).cte('listed').prefix_with('MATERIALIZED')
    return _filtered(listed, query), listed


def valid_sort(query: ResidentsQuery) -> bool:
    return query.sort is None or query.sort in SORTS


def _ordered(query: ResidentsQuery, census_date: date, *, with_total=False):
    result, listed = _rows(query, census_date)
    if with_total:
        result = result.add_columns(func.count().over().label('total'))
    column = listed.c[SORTS[query.sort or 'resident']]
    order = column.desc() if query.direction == 'desc' else column.asc()
    order = (order.nulls_first() if query.direction == 'desc' else order.nulls_last()) \
        if query.sort == 'code' else order.nulls_last()
    return result.order_by(order, listed.c.payer_stay_id).limit(query.limit).offset(query.offset)


def residents_page(connection: Connection, query: ResidentsQuery, today: date):
    if not valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    census_date = census_day(connection, today)
    rows = connection.execute(_ordered(query, census_date, with_total=True)).mappings().all()
    if rows:
        total = rows[0]['total']
    else:
        result, _ = _rows(query, census_date, with_revenue=False)
        total = connection.scalar(select(func.count()).select_from(result.subquery()))
    return dict(items=rows, total=total, limit=query.limit, offset=query.offset, census_date=census_date)


def residents_options(connection: Connection, query: FilterQuery, today: date):
    if query.column not in FILTERS and query.column != CATEGORY_FILTER:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    # No revenue or names unless a search needs them: no menu shows either.
    result, listed = _rows(query, census_day(connection, today), with_revenue=False)
    result, listed = _filtered(listed, query, exclude=query.column), listed
    if query.column == CATEGORY_FILTER:
        parts = _part_conditions(listed)
        counts = connection.execute(result.with_only_columns(
            *(func.count().filter(condition) for condition in parts.values()))).one()
        return dict(options=[label for label, count in zip(parts, counts) if count])
    column = listed.c[FILTERS[query.column]]
    return dict(options=sorted(connection.scalars(
        result.with_only_columns(cast(column, String).label('option')).distinct()),
        key=lambda option: (option == NOT_CODED, option)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'), ('Portfolio', 'portfolio'),
    ('Region', 'region'), ('Payer name', 'payer_name'), ('Admission date', 'admission_date'),
    ('Length of stay', 'length_of_stay'), ('ARD', 'ard'), ('Case-mix code', 'case_mix_code'),
    ('Daily rate', 'daily_rate'), ('Total revenue', 'total_revenue'),
)


def residents_csv(database, query: ResidentsQuery, today: date):
    with database.connection() as connection:
        census_date = census_day(connection, today)
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
