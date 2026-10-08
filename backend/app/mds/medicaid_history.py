"""Historical Medicaid and Monthly Medicaid Trending: Texas Medicaid over time,
as Historical Medicare PDPM and Monthly Medicare PDPM Trending show Medicare.

Texas only, as Current Medicaid: its Medicaid pays on the PDPM nursing and NTA
components, Florida and Pennsylvania on other systems. No neutral rate.

Everything reads census_logs and medicaid_assessments. A Medicaid resident's
rate is the census row's -- there are no rate steps -- and a payer period's
census segments cover each of its days exactly once, so a stay's days and
revenue are its segments' days and rate times days, through the census day.

Historical Medicaid's stays are the Texas Medicaid payer periods whose start --
or whose first assessment's ARD -- falls in the range, each counted whole, as
Historical Medicare PDPM counts its stays. Census days are a level instead:
everyone in a bed inside the range, whenever their stay began. A stay's code
is its first assessment's, once coded by the census day.

Facility rows carry sums; the page divides once at any scope.
"""
import csv
from datetime import date, timedelta
import io
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, and_, case, cast, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import DATERANGE
from sqlalchemy.engine import Connection

from shared.database.schema import (
    census_logs as logs, daily_runs, facilities, medicaid_assessments as assessments,
    monthly_medicaid_census_facts as facts, payers, portfolios, regions,
    res_payer_stays as periods, res_stays as stays, residents)
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from ..common.tables import Page, PageQuery
from .historical import MAX_RANGE_DAYS
from .medicaid import NOT_CODED, NTA, NURSING, NURSING_CATEGORY, STATES, _part_conditions
from .monthly import MonthlyQuery, month_list
from .service import GENERATOR, census_day


def _texas_facilities(connection: Connection):
    return [location for location in connection.execute(facility_locations(LocationSelection())).mappings()
        if location['state'] in STATES]


def _located(location, **values):
    return dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
        state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'], **values)


def _sorted(items):
    return sorted(items, key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))


def _segments(census_date: date, window=None):
    """Texas Medicaid census segments, cut after the census day: each a stretch
    at one rate. With a window, only those overlapping it, through the in_bed
    range index first."""
    through = literal(census_date + timedelta(days=1), Date)
    rows = (select(logs.c.payer_stay_id, logs.c.facility_id, logs.c.admission_date, logs.c.daily_rate,
            func.lower(logs.c.in_bed).label('starts'), func.least(func.upper(logs.c.in_bed), through).label('ends'))
        .select_from(logs.join(payers, payers.c.payer_id == logs.c.payer_id))
        .where(payers.c.payer_type == 'medicaid', func.lower(logs.c.in_bed) <= literal(census_date, Date)))
    if window is not None:
        rows = rows.where(logs.c.in_bed.overlaps(window))
    rows = rows.cte('segments').prefix_with('MATERIALIZED')
    texas = (select(rows).select_from(rows.join(facilities, facilities.c.facility_id == rows.c.facility_id)
        .join(regions).join(portfolios)).where(portfolios.c.state.in_(STATES)).subquery('texas_segments'))
    return texas


def _stay_segments(selected, census_date: date, window, facility_ids=()):
    """The selected stays' own census segments overlapping the window, cut after
    the census day: the stays first, then their segments through the primary
    key. Scanning every Medicaid segment in the window and keeping theirs took
    1.1-1.7 s for a year."""
    chosen = select(selected.c.payer_stay_id, selected.c.facility_id)
    if facility_ids:
        chosen = chosen.where(selected.c.facility_id.in_(facility_ids))
    chosen = chosen.cte('chosen').prefix_with('MATERIALIZED')
    through = literal(census_date + timedelta(days=1), Date)
    return (select(chosen.c.payer_stay_id, chosen.c.facility_id, logs.c.admission_date, logs.c.daily_rate,
            func.lower(logs.c.in_bed).label('starts'), func.least(func.upper(logs.c.in_bed), through).label('ends'))
        .select_from(chosen.join(logs, logs.c.payer_stay_id == chosen.c.payer_stay_id))
        .where(logs.c.in_bed.overlaps(window), func.lower(logs.c.in_bed) <= literal(census_date, Date))
        .subquery('stay_segments'))


def _window(start: date, end: date):
    return func.daterange(literal(start, Date), literal(end + timedelta(days=1), Date), type_=DATERANGE)


# --- Historical Medicaid: the stays ----------------------------------------

class HistoricalQuery(BaseModel):
    # Inclusive, applied to each stay's start (start) or its first ARD (ard).
    start_date: date
    end_date: date
    date_basis: Literal['start', 'ard'] = 'start'

    @field_validator('end_date')
    @classmethod
    def valid_range(cls, value, info):
        start = info.data.get('start_date')
        if start is not None and start > value:
            raise ValueError('start_date must be on or before end_date.')
        if start is not None and (value - start).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f'The range is at most {MAX_RANGE_DAYS} days.')
        return value


def _stays(query: HistoricalQuery, census_date: date, *, names=False):
    """The range's Texas Medicaid stays, one row each, with their first
    assessment once coded by the census day. The date basis's column narrows
    the rows first, as Historical Medicare PDPM's selection does."""
    day = literal(census_date, Date)
    first = assessments.alias('first_assessment')
    by_ard = query.date_basis == 'ard'
    # The range's Medicaid periods first, from the date column alone, then
    # their places. Joined the other way round, PostgreSQL takes Texas for one
    # row and walks every Texas stay's payer periods: 1.8 s even for 30 days.
    basis = (select(assessments.c.payer_stay_id).where(assessments.c.segment == 1,
            assessments.c.ard.between(query.start_date, query.end_date)) if by_ard
        else select(periods.c.payer_stay_id).where(periods.c.start_date.between(query.start_date, query.end_date)))
    candidates = (select(periods.c.payer_stay_id, periods.c.stay_id, periods.c.start_date, periods.c.end_date,
            payers.c.payer_name, stays.c.facility_id, stays.c.resident_id)
        .select_from(periods.join(payers, payers.c.payer_id == periods.c.payer_id)
            .join(stays, stays.c.stay_id == periods.c.stay_id))
        .where(periods.c.payer_stay_id.in_(basis), payers.c.payer_type == 'medicaid', periods.c.start_date <= day)
        .cte('candidates').prefix_with('MATERIALIZED'))
    joined = (candidates.join(facilities, facilities.c.facility_id == candidates.c.facility_id)
        .join(regions).join(portfolios)
        .outerjoin(first, and_(first.c.payer_stay_id == candidates.c.payer_stay_id, first.c.segment == 1)))
    coded = func.coalesce(first.c.coded_date <= day, False)
    columns = [candidates.c.payer_stay_id, candidates.c.stay_id, candidates.c.facility_id, candidates.c.start_date,
        candidates.c.end_date, candidates.c.payer_name, facilities.c.facility.label('facility_name'),
        portfolios.c.state, portfolios.c.portfolio, regions.c.region,
        case((coded, first.c.code), else_=None).label('code'),
        case((coded, first.c.nursing_function_score), else_=None).label('nursing_function_score'),
        case((coded, first.c.ard), else_=None).label('ard'),
        case(((candidates.c.end_date.is_(None)) | (candidates.c.end_date > day), 'Yes'), else_='No').label('active')]
    if names:
        joined = joined.join(residents, residents.c.resident_id == candidates.c.resident_id)
        columns.append((residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'))
    return (select(*columns).select_from(joined).where(portfolios.c.state.in_(STATES))
        .subquery('selected'))


def _stay_revenue(census_date: date, selected):
    """Each selected stay's days and revenue through the census day, from its
    census segments: joined rather than read per stay, as Historical Medicare
    PDPM measured for its rate steps."""
    through = literal(census_date + timedelta(days=1), Date)
    days = func.least(func.upper(logs.c.in_bed), through) - func.lower(logs.c.in_bed)
    return (select(logs.c.payer_stay_id, func.sum(days).label('days'), func.sum(days * logs.c.daily_rate).label('revenue'))
        .where(logs.c.payer_stay_id == selected.c.payer_stay_id, func.lower(logs.c.in_bed) <= literal(census_date, Date))
        .group_by(logs.c.payer_stay_id))


def historical(connection: Connection, query: HistoricalQuery, today: date):
    """Per Texas facility: the range's stays, their Medicaid days and revenue,
    and those same stays' days in a bed inside the range -- the trend's daily
    census summed -- so the date basis changes every number alike."""
    census_date = census_day(connection, today)
    selected = _stays(query, census_date)
    through = literal(census_date + timedelta(days=1), Date)
    days = func.least(func.upper(logs.c.in_bed), through) - func.lower(logs.c.in_bed)
    totals = {row['facility_id']: row for row in connection.execute(
        select(selected.c.facility_id, func.count(func.distinct(selected.c.payer_stay_id)).label('stays'),
            func.coalesce(func.sum(days), 0).label('medicaid_days'),
            func.coalesce(func.sum(days * logs.c.daily_rate), 0).label('actual_revenue'))
        .select_from(selected.outerjoin(logs, and_(logs.c.payer_stay_id == selected.c.payer_stay_id,
            func.lower(logs.c.in_bed) <= literal(census_date, Date))))
        .group_by(selected.c.facility_id)).mappings()}

    last = min(query.end_date, census_date)
    census = {}
    if query.start_date <= last:
        window = _window(query.start_date, last)
        segments = _stay_segments(selected, census_date, window)
        overlap = func.greatest(func.least(segments.c.ends, literal(last + timedelta(days=1), Date))
            - func.greatest(segments.c.starts, literal(query.start_date, Date)), 0)
        census = dict(connection.execute(select(segments.c.facility_id, func.sum(overlap))
            .group_by(segments.c.facility_id)).all())
    range_days = connection.scalar(select(func.count()).where(daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(query.start_date, last)))

    items = []
    for location in _texas_facilities(connection):
        row = totals.get(location['facility_id'], {})
        items.append(_located(location, stays=int(row.get('stays', 0)), medicaid_days=int(row.get('medicaid_days', 0)),
            actual_revenue=float(row.get('actual_revenue', 0)), census_days=int(census.get(location['facility_id'], 0) or 0)))
    return dict(start_date=query.start_date, end_date=query.end_date, date_basis=query.date_basis,
        census_date=census_date, census_range_days=range_days, items=_sorted(items))


class DailyQuery(HistoricalQuery):
    # The drilldown's facilities; empty means every Texas facility.
    facility_ids: list[UUID] = Field(default_factory=list, max_length=1000)


def daily(connection: Connection, query: DailyQuery, today: date):
    """Each day's census of the selected stays -- the stays the table counts,
    by stay start or first ARD -- with their summed daily rates and days since
    admission, for the trend charts: a running sum of what each census segment
    adds the day it starts and takes away the day after it ends, as Historical
    Medicare PDPM's trend does with rate steps. Days since admission sum as
    census times the day less the summed admission dates."""
    census_date = census_day(connection, today)
    last = min(query.end_date, census_date)
    if query.start_date > last:
        return dict(census_date=census_date, days=[])
    # The table's stays, by the same date and date basis, and only theirs.
    segments = _stay_segments(_stays(query, census_date), census_date, _window(query.start_date, last),
        query.facility_ids)
    start = literal(query.start_date, Date)
    starts = func.greatest(segments.c.starts, start)
    epoch = segments.c.admission_date - literal(date(2000, 1, 1), Date)
    changes = (select(starts.label('day'), literal(1).label('census'), segments.c.daily_rate.label('rate'),
            epoch.label('admitted'))
        .union_all(select(segments.c.ends, literal(-1), -segments.c.daily_rate, -epoch)
            .where(segments.c.ends <= last)).subquery('changes'))
    by_day = {row.day: row for row in connection.execute(select(changes.c.day, func.sum(changes.c.census).label('census'),
        func.sum(changes.c.rate).label('rate'), func.sum(changes.c.admitted).label('admitted')).group_by(changes.c.day))}
    days, census, rates, admitted = [], 0, 0.0, 0
    for offset in range((last - query.start_date).days + 1):
        day = query.start_date + timedelta(days=offset)
        row = by_day.get(day)
        if row:
            census += int(row.census)
            rates += float(row.rate)
            admitted += int(row.admitted)
        since = census * (day - date(2000, 1, 1)).days - admitted
        days.append(dict(date=day, census=census, actual_rates=round(rates, 2), stay_days=since))
    return dict(census_date=census_date, days=days)


def categories(connection: Connection, query: HistoricalQuery, today: date):
    """The range's stays by their first assessment's category, once coded by the
    census day; stays not yet coded are in no_score."""
    census_date = census_day(connection, today)
    selected = _stays(query, census_date)
    nursing, nta = func.substr(selected.c.code, 1, 1), func.substr(selected.c.code, 2, 1)
    coded = selected.c.code.is_not(None)
    columns = [func.count().filter(~coded).label('no_score')]
    columns += [func.count().filter(selected.c.nursing_function_score.between(low, high)).label(f'nursing.{field}')
        for field, (low, high) in NURSING.items()]
    columns += [func.count().filter(nursing.in_(list(letters))).label(f'nursing_category.{field}')
        for field, letters in NURSING_CATEGORY.items()]
    columns += [func.count().filter(nta == letter).label(f'nta.{field}') for field, letter in NTA.items()]
    totals = {row['facility_id']: row for row in connection.execute(
        select(selected.c.facility_id, *columns).group_by(selected.c.facility_id)).mappings()}
    items = []
    for location in _texas_facilities(connection):
        row = totals.get(location['facility_id'], {})
        get = lambda key: row.get(key, 0) or 0
        items.append(_located(location, no_score=get('no_score'),
            nursing={field: get(f'nursing.{field}') for field in NURSING},
            nursing_category={field: get(f'nursing_category.{field}') for field in NURSING_CATEGORY},
            nta={field: get(f'nta.{field}') for field in NTA}))
    return dict(census_date=census_date, items=_sorted(items))


# --- Historical Medicaid: the residents ------------------------------------

SORTS = {'resident': 'resident_name', 'facility': 'facility_name', 'payer-name': 'payer_name',
    'medicaid-start': 'start_date', 'ard': 'ard', 'active': 'active', 'medicaid-days': 'medicaid_days',
    'code': 'code', 'average-rate': 'average_rate', 'total-revenue': 'total_revenue'}
FILTERS = {'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'payer-name': 'payer_name', 'active': 'active', 'code': 'case_mix_code'}
CATEGORY_FILTER = 'medicaid-category'
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region', 'payer_name', 'case_mix_code')


class ResidentsQuery(PageQuery):
    start_date: date
    end_date: date
    date_basis: Literal['start', 'ard'] = 'start'
    filters: str = Field(default='{}', max_length=100000)
    search: str = Field(default='', max_length=200)

    @field_validator('end_date')
    @classmethod
    def valid_range(cls, value, info):
        return HistoricalQuery.valid_range(value, info)

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


class HistoricalMedicaidResident(BaseModel):
    payer_stay_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    payer_name: str
    start_date: date = Field(description='First day of this Medicaid payer period.')
    ard: date | None = Field(description="The first assessment's reference date; null until coded.")
    active: str = Field(description='Yes while this Medicaid stay is still running on the census day.')
    medicaid_days: int
    case_mix_code: str = Field(description='The first code, or "Missing care code" until it is coded.')
    average_rate: float | None
    total_revenue: float


class ResidentsPage(Page[HistoricalMedicaidResident]):
    census_date: date


def _resident_rows(query: ResidentsQuery, census_date: date, *, with_revenue=True):
    selected = _stays(query, census_date, names=True)
    columns = [selected, func.coalesce(selected.c.code, NOT_CODED).label('case_mix_code')]
    source = selected
    if with_revenue:
        revenue = _stay_revenue(census_date, selected).lateral('revenue')
        source = selected.outerjoin(revenue, revenue.c.payer_stay_id == selected.c.payer_stay_id)
        columns += _revenue_columns(revenue)
    listed = select(*columns).select_from(source).cte('listed').prefix_with('MATERIALIZED')
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if not values:
            continue
        if key == CATEGORY_FILTER:
            parts = _part_conditions(listed)
            result = result.where(or_(false(), *(parts[value] for value in values if value in parts)))
        else:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result, listed


def valid_sort(query: ResidentsQuery) -> bool:
    return query.sort is None or query.sort in SORTS


REVENUE_SORTS = ('medicaid-days', 'average-rate', 'total-revenue')


def _revenue_columns(revenue):
    return [func.coalesce(revenue.c.days, 0).label('medicaid_days'),
        func.round(revenue.c.revenue / func.nullif(revenue.c.days, 0), 2).label('average_rate'),
        func.round(func.coalesce(revenue.c.revenue, 0), 2).label('total_revenue')]


def _order(query: ResidentsQuery, rows):
    column = rows.c[SORTS[query.sort or 'resident']]
    order = column.desc() if query.direction == 'desc' else column.asc()
    order = (order.nulls_first() if query.direction == 'desc' else order.nulls_last())         if query.sort == 'code' else order.nulls_last()
    return order, rows.c.payer_stay_id


def _ordered(query: ResidentsQuery, census_date: date, *, with_total=False, paged=True):
    """The sorted rows. Only a revenue sort prices every stay: otherwise the page
    is cut first and only its stays are priced, as Historical Medicare PDPM's
    list does. Pricing all of a year's 43,386 stays took 2.7 s."""
    priced = query.sort in REVENUE_SORTS or not paged
    result, listed = _resident_rows(query, census_date, with_revenue=priced)
    if with_total:
        result = result.add_columns(func.count().over().label('total'))
    result = result.order_by(*_order(query, listed))
    if paged:
        result = result.limit(query.limit).offset(query.offset)
    if priced:
        return result
    page = result.subquery('page')
    revenue = _stay_revenue(census_date, page).lateral('revenue')
    return (select(page, *_revenue_columns(revenue))
        .select_from(page.outerjoin(revenue, revenue.c.payer_stay_id == page.c.payer_stay_id))
        .order_by(*_order(query, page)))


def residents_page(connection: Connection, query: ResidentsQuery, today: date):
    if not valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    census_date = census_day(connection, today)
    rows = connection.execute(_ordered(query, census_date, with_total=True)).mappings().all()
    if rows:
        total = rows[0]['total']
    else:
        result, _ = _resident_rows(query, census_date, with_revenue=False)
        total = connection.scalar(select(func.count()).select_from(result.subquery()))
    return dict(items=rows, total=total, limit=query.limit, offset=query.offset, census_date=census_date)


def residents_options(connection: Connection, query: FilterQuery, today: date):
    if query.column not in FILTERS and query.column != CATEGORY_FILTER:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    # The menu's own filter left out, and no revenue: no menu shows it.
    others = {key: values for key, values in json.loads(query.filters).items() if key != query.column}
    narrowed = query.model_copy(update=dict(filters=json.dumps(others)))
    result, listed = _resident_rows(narrowed, census_day(connection, today), with_revenue=False)
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
    ('Region', 'region'), ('Payer name', 'payer_name'), ('Medicaid start', 'start_date'), ('ARD', 'ard'),
    ('Active', 'active'), ('Medicaid days', 'medicaid_days'), ('Case-mix code', 'case_mix_code'),
    ('Average rate', 'average_rate'), ('Total revenue', 'total_revenue'),
)


def residents_csv(database, query: ResidentsQuery, today: date):
    with database.connection() as connection:
        census_date = census_day(connection, today)
        source = _ordered(query, census_date, paged=False)
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


# --- Monthly Medicaid Trending ---------------------------------------------

ROLLUP = 'medicaid_census_summary'


def monthly(connection: Connection, query: MonthlyQuery, today: date):
    """Per Texas facility and calendar month: Medicaid resident-days and summed
    daily rates, from monthly_medicaid_census_facts. Months run through the
    census day, each with the days its average divides by. 409 if the rollup
    has not reached the census day; absence of a row means zero."""
    census_date = census_day(connection, today)
    built = connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == ROLLUP))
    if built is None or built < census_date:
        raise ApiError('summary_unavailable', 'Medicaid census facts are behind the census logs. '
            'Run the seeder update.', 409)
    months = month_list(connection, query, census_date)
    totals = {}
    if months:
        for row in connection.execute(select(facts.c.facility_id, facts.c.month_start, facts.c.resident_days,
                facts.c.actual_rates).where(facts.c.month_start.between(date.fromisoformat(months[0]['month']),
                    date.fromisoformat(months[-1]['month'])))).mappings():
            totals.setdefault(row['facility_id'], {})[row['month_start'].isoformat()] = dict(
                resident_days=int(row['resident_days']), actual_rates=float(row['actual_rates']))
    items = [_located(location, months=totals.get(location['facility_id'], {}))
        for location in _texas_facilities(connection)]
    return dict(census_date=census_date, months=months, items=_sorted(items))
