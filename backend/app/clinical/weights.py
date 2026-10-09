"""Weight Surveillance: every resident in a bed on the day, with their weights.

Read from weight_logs, the seeder's weigh-ins: on admission, weekly for four
weeks, then every 30 days. For each resident in a bed on the day (census_logs,
as the census Residents tab counts them), from this stay's weigh-ins up to the
day:

- admission weight, the first; current weight, the latest, and when it was
  taken; the change between them, in pounds and percent;
- highest and lowest, and the range between them, in pounds and as a percent of
  the highest;
- the change over 30 and 180 days: the current weight against the latest one
  taken at least that long before it, within the stay.

A significant change is the MDS's: 5% or more in 30 days, or 10% or more in
180. Loss outranks gain if both are true. A resident without a weigh-in far
enough back has no 30- or 180-day change and is judged on what there is.

Built like census Residents: the day's stays first through the range index,
then the finished list materialized before it is sorted and paged, so every
sort costs the same. Page and CSV share one statement. Filter options for the
location columns use a lighter list without the weights; the Flag menu needs
them and builds the full list.
"""
import csv
from datetime import date
import io
import json

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, case, cast, func, literal, or_, select

from shared.database.schema import (
    census_logs as logs, daily_runs, facilities, portfolios, regions, residents, weight_logs as weights)
from ..common.dates import OptionalDate
from ..common.errors import ApiError
from ..common.tables import Page, PageQuery

# The MDS's significant change: percent in 30 days, percent in 180.
SIGNIFICANT_30, SIGNIFICANT_180 = 5, 10
FLAGS = ('Significant loss', 'Significant gain', 'None')
# Days back a resident's latest weigh-in can be: weighed every 30 days at most.
WEIGHED_WITHIN = 30

SORTS = {
    'resident': 'resident_name', 'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio',
    'region': 'region', 'admission-date': 'admission_date', 'days': 'days_in_facility',
    'flag': 'flag_rank', 'admission-weight': 'admission_weight', 'current-weight': 'current_weight',
    'weighed-on': 'weighed_on', 'change': 'change', 'change-percent': 'change_percent',
    'highest': 'highest', 'lowest': 'lowest', 'range': 'weight_range', 'range-percent': 'range_percent',
    'change-30-days': 'change_30_days', 'change-180-days': 'change_180_days',
}
FILTERS = {'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'flag': 'flag'}
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region')


class WeightsQuery(PageQuery):
    # The shared filter-options client always sends a range; the list is one day,
    # end_date, and start_date is accepted and ignored. Omitted, the latest day.
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
            raise ValueError('Unsupported weight filter.')
        for values in filters.values():
            if (not isinstance(values, list) or len(values) > 1000
                    or any(not isinstance(item, str) or len(item) > 300 for item in values)):
                raise ValueError('Each filter must be a list of strings, with at most 1000 selections.')
        return value


class FilterQuery(WeightsQuery):
    column: str = Field(max_length=100)


class ResidentWeight(BaseModel):
    stay_id: str
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    admission_date: date
    days_in_facility: int
    admission_weight: float = Field(description='Pounds, at the first weigh-in of the stay.')
    current_weight: float = Field(description='Pounds, at the latest weigh-in on or before the day.')
    weighed_on: date = Field(description='When the current weight was taken.')
    change: float = Field(description='Current less admission weight, pounds.')
    change_percent: float
    highest: float
    lowest: float
    weight_range: float = Field(description='Highest less lowest, pounds.')
    range_percent: float = Field(description='The range as a percent of the highest.')
    change_30_days: float | None = Field(description='Percent, against the latest weight at least 30 days older.')
    change_180_days: float | None
    flag: str = Field(description="'Significant loss', 'Significant gain' or 'None'.")


class WeightsPage(Page[ResidentWeight]):
    census_date: date
    # Of the whole filtered list, the same on every page.
    significant_loss: int
    significant_gain: int


def weight_day(connection, query: WeightsQuery) -> date:
    """The requested day, or the latest with weights; 409 unless census and
    weights were both generated for it."""
    day = query.end_date or connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == 'weight_logs'))
    if day is None:
        raise ApiError('summary_unavailable', 'Weights have not been generated yet. Run the seeder update.', 409)
    for generator in ('census_logs', 'weight_logs'):
        if not connection.scalar(select(func.count()).select_from(daily_runs).where(
                daily_runs.c.generator == generator, daily_runs.c.simulation_date == day)):
            raise ApiError('summary_unavailable', f'The {day} {generator.replace("_", " ")} have not been '
                'generated. Run the seeder update.', 409)
    return day


def _current(day):
    """The day's stays, found first through the range index."""
    return (select(logs.c.stay_id, logs.c.resident_id, logs.c.facility_id, logs.c.admission_date)
        .where(logs.c.in_bed.contains(day)).cte('current').prefix_with('MATERIALIZED'))


def _percent(new, old):
    return func.round((new - old) * 100 / old, 1)


def _rows(query: WeightsQuery, census_date: date, exclude=None):
    """The finished, filtered list for one day, as a materialized CTE."""
    day = literal(census_date, Date)
    current = _current(day)
    # Each resident's latest weigh-in, which carries the stay's state as of it.
    # Everyone in a bed is weighed at least every 30 days, so it lies in the 30
    # days to the day: a range of rows stored together by date, about 55,000,
    # rather than a lookup per stay, which read nearly the whole table and key.
    recent = (select(weights).distinct(weights.c.stay_id)
        .where(weights.c.weighed_on.between(day - WEIGHED_WITHIN, day))
        .order_by(weights.c.stay_id, weights.c.weighed_on.desc()).cte('recent').prefix_with('MATERIALIZED'))
    summary = (select(current.c.stay_id, recent.c.weighed_on, recent.c.highest, recent.c.lowest,
            recent.c.admission_weight, recent.c.weight.label('current_weight'),
            recent.c.weight_30_days_before.label('weight_30'), recent.c.weight_180_days_before.label('weight_180'))
        .select_from(current.join(recent, recent.c.stay_id == current.c.stay_id)).subquery('summary'))
    change_30 = _percent(summary.c.current_weight, summary.c.weight_30)
    change_180 = _percent(summary.c.current_weight, summary.c.weight_180)
    loss = or_(change_30 <= -SIGNIFICANT_30, change_180 <= -SIGNIFICANT_180)
    gain = or_(change_30 >= SIGNIFICANT_30, change_180 >= SIGNIFICANT_180)
    rows = select(
        current.c.stay_id,
        (residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'),
        facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio,
        regions.c.region, current.c.admission_date,
        (day - current.c.admission_date).label('days_in_facility'),
        summary.c.admission_weight, summary.c.current_weight, summary.c.weighed_on,
        (summary.c.current_weight - summary.c.admission_weight).label('change'),
        _percent(summary.c.current_weight, summary.c.admission_weight).label('change_percent'),
        summary.c.highest, summary.c.lowest,
        (summary.c.highest - summary.c.lowest).label('weight_range'),
        func.round((summary.c.highest - summary.c.lowest) * 100 / summary.c.highest, 1).label('range_percent'),
        change_30.label('change_30_days'), change_180.label('change_180_days'),
        case((loss, FLAGS[0]), (gain, FLAGS[1]), else_=FLAGS[2]).label('flag'),
        case((loss, 0), (gain, 1), else_=2).label('flag_rank'),
    ).select_from(current
        .join(summary, summary.c.stay_id == current.c.stay_id)
        .join(residents, residents.c.resident_id == current.c.resident_id)
        .join(facilities, facilities.c.facility_id == current.c.facility_id)
        .join(regions).join(portfolios))
    listed = rows.cte('listed').prefix_with('MATERIALIZED')
    return _filtered(listed, query, exclude), listed


def _filtered(listed, query: WeightsQuery, exclude=None):
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if values and key != exclude:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result


def _option_rows(query: WeightsQuery, census_date: date, exclude):
    """The same residents, filters and search without the weights, for a menu
    that does not need them: no Flag filter applied and not the Flag menu."""
    current = _current(literal(census_date, Date))
    listed = select(current.c.stay_id,
            (residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'),
            facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio,
            regions.c.region).select_from(current
        .join(residents, residents.c.resident_id == current.c.resident_id)
        .join(facilities, facilities.c.facility_id == current.c.facility_id)
        .join(regions).join(portfolios)).cte('listed').prefix_with('MATERIALIZED')
    return _filtered(listed, query, exclude), listed


def _ordered(query: WeightsQuery, census_date: date, *, with_totals=False):
    result, listed = _rows(query, census_date)
    if with_totals:
        # Totals ride on the page, so the list is built once per request.
        result = result.add_columns(func.count().over().label('total'),
            func.count().filter(listed.c.flag == FLAGS[0]).over().label('significant_loss'),
            func.count().filter(listed.c.flag == FLAGS[1]).over().label('significant_gain'))
    column = listed.c[SORTS[query.sort or 'flag']]
    order = column.desc() if query.direction == 'desc' else column.asc()
    # Stable ties keep residents from moving between pages; within a flag, the
    # largest 30-day change first.
    return result.order_by(order, func.abs(listed.c.change_30_days).desc().nulls_last(),
        listed.c.stay_id).limit(query.limit).offset(query.offset)


def page(connection, query: WeightsQuery):
    if query.sort is not None and query.sort not in SORTS:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    census_date = weight_day(connection, query)
    rows = connection.execute(_ordered(query, census_date, with_totals=True)).mappings().all()
    if rows:
        totals = {key: rows[0][key] for key in ('total', 'significant_loss', 'significant_gain')}
    else:
        # An empty page past the end still needs the true totals.
        result, listed = _rows(query, census_date)
        filtered = result.subquery()
        totals = connection.execute(select(func.count().label('total'),
            func.count().filter(filtered.c.flag == FLAGS[0]).label('significant_loss'),
            func.count().filter(filtered.c.flag == FLAGS[1]).label('significant_gain'))
            .select_from(filtered)).mappings().one()
    items = [dict(row, stay_id=str(row['stay_id'])) for row in rows]
    return dict(items=items, limit=query.limit, offset=query.offset, census_date=census_date, **totals)


def options(connection, query: FilterQuery):
    if query.column not in FILTERS:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    census_date = weight_day(connection, query)
    needs_weights = query.column == 'flag' or bool(json.loads(query.filters).get('flag'))
    result, listed = (_rows if needs_weights else _option_rows)(query, census_date, exclude=query.column)
    column = listed.c[FILTERS[query.column]]
    options = set(connection.scalars(result.with_only_columns(cast(column, String).label('option')).distinct()))
    if query.column == 'flag':
        return dict(options=[flag for flag in FLAGS if flag in options])
    return dict(options=sorted(options))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Portfolio', 'portfolio'), ('Region', 'region'), ('Admission date', 'admission_date'),
    ('Days in facility', 'days_in_facility'), ('Flag', 'flag'), ('Admission weight (lb)', 'admission_weight'),
    ('Current weight (lb)', 'current_weight'), ('Weighed on', 'weighed_on'),
    ('Change since admission (lb)', 'change'), ('Change since admission (%)', 'change_percent'),
    ('Highest (lb)', 'highest'), ('Lowest (lb)', 'lowest'), ('Highest to lowest (lb)', 'weight_range'),
    ('Highest to lowest (%)', 'range_percent'), ('30-day change (%)', 'change_30_days'),
    ('180-day change (%)', 'change_180_days'),
)


def csv_chunks(database, query: WeightsQuery):
    with database.connection() as connection:
        census_date = weight_day(connection, query)
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
