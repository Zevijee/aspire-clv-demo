"""The residents behind Historical Medicare PDPM: one row per Medicare PDPM stay
whose start -- or 5-day ARD, by date_basis -- falls in the range, the same
stays its Overview and Category breakdown count (historical._selected).

Each row is the stay as the Overview measures it: Medicare days through its end
or the census day, revenue at each PDPM step's rate, the neutral revenue at the
national per diem times each step's day factor, and their averages per day. The
PDPM score is the coded 5-day assessment, or Missing care code until it is
coded by the census day, as the Category breakdown counts it.

Follows residents.py: the finished, filtered list is built whole as a
materialized CTE, then sorted and paged; page and CSV share one statement.
Filter options use a lighter list with the same stays, filters and search but
no revenue, which no menu shows (the trap AGENTS.md records for these tables).
"""
import csv
from datetime import date, timedelta
import io
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, case, cast, func, literal, or_, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    facilities, facility_payer_rates as contracts, payers, pdpm_assessments as assessments,
    pdpm_rate_logs as pdpm, portfolios, regions, res_payer_stays as periods, res_stays as stays, residents)
from ..common.errors import ApiError
from ..common.tables import Page, PageQuery
from .historical import MAX_RANGE_DAYS
from .residents import NOT_CODED
from .service import GROUP_LABELS, MEDICARE, NATIONAL_PER_DIEM, census_day

# Column id -> the output column of the finished list it sorts, filters and
# searches on. Labels are what the table shows, so they are what filters match.
SORTS = {
    'resident': 'resident_name', 'facility': 'facility_name', 'payer': 'payer_label',
    'payer-name': 'payer_name', 'medicare-start': 'medicare_start', 'ard': 'ard', 'active': 'active',
    'medicare-days': 'medicare_days', 'pdpm-score': 'pdpm_code', 'average-rate': 'average_rate',
    'neutral-rate': 'neutral_rate', 'total-revenue': 'total_revenue', 'neutral-revenue': 'neutral_revenue',
}
FILTERS = {
    'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'payer': 'payer_label', 'payer-name': 'payer_name', 'active': 'active', 'pdpm-score': 'pdpm_score',
}
# Sorting by these needs every stay's revenue before paging; any other order
# pages first and prices only the page's stays.
REVENUE_SORTS = ('average-rate', 'neutral-rate', 'total-revenue', 'neutral-revenue')
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region', 'payer_label',
    'payer_name', 'pdpm_score')


class ResidentsQuery(PageQuery):
    # Inclusive, applied to each stay's start (start) or its 5-day ARD (ard).
    start_date: date
    end_date: date
    date_basis: Literal['start', 'ard'] = 'start'
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)

    @field_validator('end_date')
    @classmethod
    def valid_range(cls, value, info):
        start = info.data.get('start_date')
        if start is not None and start > value:
            raise ValueError('start_date must be on or before end_date.')
        if start is not None and (value - start).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f'The range is at most {MAX_RANGE_DAYS} days.')
        return value

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


class HistoricalResident(BaseModel):
    payer_stay_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    payer_label: str = Field(description='Federal Medicare or Managed Medicare PDPM.')
    payer_name: str
    medicare_start: date = Field(description='First day of this Medicare payer period.')
    ard: date | None = Field(description="The 5-day assessment's reference date; null until it is coded.")
    active: str = Field(description='Yes while this Medicare stay is still running on the census day.')
    medicare_days: int = Field(description='Days on this Medicare stay, through its end or the census day.')
    pdpm_score: str = Field(description='Four-letter PDPM code, or "Missing care code" until it is coded.')
    average_rate: float = Field(description='Total revenue per Medicare day.')
    neutral_rate: float = Field(description='Neutral revenue per Medicare day.')
    total_revenue: float = Field(description='Every PDPM step of the stay, its rate times its days.')
    neutral_revenue: float = Field(description='The same days at the national per diem times the day factor.')


class ResidentsPage(Page[HistoricalResident]):
    census_date: date


def _source(query: ResidentsQuery, day):
    """The range's stays with every column a filter or search reads, as the
    Overview selects them: the date basis's index narrows the rows first."""
    by_ard = query.date_basis == 'ard'
    source = (assessments.join(periods, periods.c.payer_stay_id == assessments.c.payer_stay_id)
        if by_ard else periods)
    source = (source
        .join(payers, payers.c.payer_id == periods.c.payer_id)
        .join(stays, stays.c.stay_id == periods.c.stay_id)
        .join(contracts, (contracts.c.facility_id == stays.c.facility_id)
            & (contracts.c.payer_id == periods.c.payer_id) & (contracts.c.payment_method == 'pdpm'))
        .join(facilities, facilities.c.facility_id == stays.c.facility_id)
        .join(regions).join(portfolios))
    if not by_ard:
        source = source.outerjoin(assessments, assessments.c.payer_stay_id == periods.c.payer_stay_id)
    coded = func.coalesce(assessments.c.coded_date <= day, False)
    columns = (periods.c.payer_stay_id, facilities.c.facility.label('facility_name'), portfolios.c.state,
        portfolios.c.portfolio, regions.c.region, payers.c.payer_name,
        case({payer_type: GROUP_LABELS[group] for payer_type, group in MEDICARE.items()},
            value=payers.c.payer_type, else_=payers.c.payer_type).label('payer_label'),
        # end_date is the day after the last, as census_logs ranges are.
        case(((periods.c.end_date.is_(None)) | (periods.c.end_date > day), 'Yes'), else_='No').label('active'),
        case((coded, assessments.c.pdpm_code), else_=NOT_CODED).label('pdpm_score'))
    condition = (payers.c.payer_type.in_(MEDICARE),
        (assessments.c.ard if by_ard else periods.c.start_date).between(query.start_date, query.end_date))
    return source, columns, condition, coded


def _filtered(listed, query: ResidentsQuery, exclude=None):
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result


def _revenue(census_date: date, stay_ids):
    """Each stay's steps through the census day, summed once per stay: Medicare
    days, revenue at each step's rate, and neutral revenue at the national per
    diem times each step's day factor. stay_ids is a list or a selectable."""
    day = literal(census_date, Date)
    through = literal(census_date + timedelta(days=1), Date)
    step_days = func.least(func.upper(pdpm.c.in_effect), through) - func.lower(pdpm.c.in_effect)
    return (select(pdpm.c.payer_stay_id, func.sum(step_days).label('days'),
            func.sum(pdpm.c.daily_rate * step_days).label('actual'),
            func.sum(NATIONAL_PER_DIEM * pdpm.c.pdpm_factor * step_days).label('neutral'))
        .where(pdpm.c.payer_stay_id.in_(stay_ids), func.lower(pdpm.c.in_effect) <= day)
        .group_by(pdpm.c.payer_stay_id))


def _priced(days, actual, neutral):
    """The four revenue columns from a stay's days and summed revenue."""
    return (func.round(actual / func.nullif(days, 0), 2).label('average_rate'),
        func.round(neutral / func.nullif(days, 0), 2).label('neutral_rate'),
        func.round(actual, 2).label('total_revenue'), func.round(neutral, 2).label('neutral_revenue'))


def _rows(query: ResidentsQuery, census_date: date, *, with_revenue=True):
    """The finished, filtered list, as a materialized CTE. Without revenue it
    skips the steps entirely: Medicare days come from the payer period, which
    the steps cover exactly once (measured equal over a year of stays)."""
    day = literal(census_date, Date)
    through = literal(census_date + timedelta(days=1), Date)
    source, columns, condition, coded = _source(query, day)
    medicare_days = func.least(func.coalesce(periods.c.end_date, through), through) - periods.c.start_date
    extra = []
    if with_revenue:
        revenue = _revenue(census_date, select(periods.c.payer_stay_id).select_from(source).where(*condition)
            ).subquery('revenue')
        source = source.outerjoin(revenue, revenue.c.payer_stay_id == periods.c.payer_stay_id)
        extra = _priced(func.coalesce(revenue.c.days, 0), func.coalesce(revenue.c.actual, 0),
            func.coalesce(revenue.c.neutral, 0))
    listed = (select(*columns,
            (residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'),
            periods.c.start_date.label('medicare_start'),
            case((coded, assessments.c.ard), else_=None).label('ard'),
            # The raw code, null while missing, so Missing care code sorts last.
            case((coded, assessments.c.pdpm_code), else_=None).label('pdpm_code'),
            medicare_days.label('medicare_days'), *extra)
        .select_from(source.join(residents, residents.c.resident_id == stays.c.resident_id))
        .where(*condition)
        .cte('listed').prefix_with('MATERIALIZED'))
    return _filtered(listed, query), listed


def _option_rows(query: ResidentsQuery, census_date: date, exclude):
    """The same stays, filters and search, without revenue or names unless a
    search needs them: no menu shows either."""
    source, columns, condition, _ = _source(query, literal(census_date, Date))
    columns = list(columns)
    if query.search.strip():
        source = source.join(residents, residents.c.resident_id == stays.c.resident_id)
        columns.append((residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'))
    listed = select(*columns).select_from(source).where(*condition).cte('listed').prefix_with('MATERIALIZED')
    return _filtered(listed, query, exclude), listed


def _ordered(query: ResidentsQuery, census_date: date, *, with_total=False, with_revenue=True):
    result, listed = _rows(query, census_date, with_revenue=with_revenue)
    if with_total:
        result = result.add_columns(func.count().over().label('total'))
    column = listed.c[SORTS[query.sort or 'resident']]
    order = column.desc() if query.direction == 'desc' else column.asc()
    # A missing care code ranks after every code ascending and before them
    # descending, as on Current Medicare PDPM; a blank ARD stays at the bottom.
    order = (order.nulls_first() if query.direction == 'desc' else order.nulls_last()) \
        if query.sort == 'pdpm-score' else order.nulls_last()
    return result.order_by(order, listed.c.payer_stay_id).limit(query.limit).offset(query.offset)


def valid_sort(query: ResidentsQuery) -> bool:
    return query.sort is None or query.sort in SORTS


def page(connection: Connection, query: ResidentsQuery, today: date):
    if not valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    census_date = census_day(connection, today)
    # Revenue for every stay only when the order needs it; otherwise the page is
    # cut first and only its stays are priced. A year of stays priced whole took
    # ~1 s a page.
    priced = query.sort in REVENUE_SORTS
    rows = [dict(row) for row in connection.execute(
        _ordered(query, census_date, with_total=True, with_revenue=priced)).mappings()]
    if rows:
        total = rows[0]['total']
    else:
        # An empty page past the end still needs the true total.
        result, _ = _rows(query, census_date, with_revenue=False)
        total = connection.scalar(select(func.count()).select_from(result.subquery()))
    if rows and not priced:
        revenue = _revenue(census_date, [row['payer_stay_id'] for row in rows]).subquery('revenue')
        prices = {row['payer_stay_id']: row for row in connection.execute(select(revenue.c.payer_stay_id,
            *_priced(revenue.c.days, revenue.c.actual, revenue.c.neutral))).mappings()}
        empty = dict(average_rate=None, neutral_rate=None, total_revenue=0, neutral_revenue=0)
        for row in rows:
            price = prices.get(row['payer_stay_id'], empty)
            row.update({key: price[key] or 0 for key in empty})
    return dict(items=rows, total=total, limit=query.limit, offset=query.offset, census_date=census_date)


def options(connection: Connection, query: FilterQuery, today: date):
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    result, listed = _option_rows(query, census_day(connection, today), exclude=query.column)
    column = listed.c[FILTERS[query.column]]
    # Alphabetical, with Missing care code after every code, as the column sorts.
    return dict(options=sorted(connection.scalars(
        result.with_only_columns(cast(column, String).label('option')).distinct()),
        key=lambda option: (option == NOT_CODED, option)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Portfolio', 'portfolio'), ('Region', 'region'), ('Payer', 'payer_label'), ('Payer name', 'payer_name'),
    ('Medicare start', 'medicare_start'), ('ARD', 'ard'), ('Active', 'active'), ('Medicare days', 'medicare_days'),
    ('PDPM score', 'pdpm_score'), ('Average rate', 'average_rate'), ('Neutral rate', 'neutral_rate'),
    ('Total revenue', 'total_revenue'), ('Neutral revenue', 'neutral_revenue'),
)


def csv_chunks(database, query: ResidentsQuery, today: date):
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
