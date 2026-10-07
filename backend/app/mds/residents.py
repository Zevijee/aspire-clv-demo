"""The residents behind Current Medicare PDPM: everyone paid from their PDPM code
on the census day -- Federal Medicare and Managed Medicare PDPM -- with their
PDPM score, average daily rate and revenue to date.

Follows census/residents.py: the day's rows are found first through the range
index and materialized, and the joined, filtered list is built whole before it is
sorted and paged. Page and CSV share one statement. Filter options use a lighter
one with the same residents, filters and search but none of the columns no menu
shows; the materialized list cannot drop unused columns, so building it for a
menu of three states cost 340ms against 44ms.

- PDPM score is the four-letter PDPM code of the current payer period, from
  pdpm_assessments: PT/OT, SLP, nursing and NTA case-mix groups.
- Total revenue is every PDPM step of the current Medicare payer period summed
  through the census day, each step's daily rate times its days.
- Average rate is that revenue over the days on this payer, census day included.
- Length of stay is days since admission, as on the overview.
"""
import csv
from datetime import date, timedelta
import io
import json
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, String, and_, case, cast, false, func, literal, or_, select, true

from shared import pdpm as pdpm_rates
from shared.database.schema import (
    census_logs as logs, facilities, facility_payer_rates as contracts, payers,
    pdpm_assessments as assessments, pdpm_rate_logs as pdpm,
    portfolios, regions, res_payer_stays as periods, residents)
from ..common.errors import ApiError
from ..common.tables import Page, PageQuery
from .service import GROUP_LABELS, MEDICARE, census_day, pdpm_contract

# Column id -> the output column of the finished list it sorts, filters and
# searches on. Labels are what the table shows, so they are what filters match.
SORTS = {
    'resident': 'resident_name', 'facility': 'facility_name', 'state': 'state',
    'portfolio': 'portfolio', 'region': 'region', 'payer': 'payer_label',
    'payer-name': 'payer_name', 'admission-date': 'admission_date', 'los': 'length_of_stay',
    # The raw code, null while missing, so Missing care code ranks after every
    # code -- last A to Z, first Z to A -- rather than among the M codes.
    'ard': 'ard', 'pdpm-score': 'pdpm_code', 'average-rate': 'average_rate', 'total-revenue': 'total_revenue',
}
FILTERS = {
    'facility': 'facility_name', 'state': 'state', 'portfolio': 'portfolio', 'region': 'region',
    'payer': 'payer_label', 'payer-name': 'payer_name', 'pdpm-score': 'pdpm_score',
}
# A filter with no column of its own: each value is one part of one Overview
# category, "PT/OT: 0-5", matched by its own predicate. It is how a click on a
# chart segment opens exactly that segment's residents.
CATEGORY_FILTER = 'pdpm-category'
SEARCHABLE = ('resident_name', 'facility_name', 'state', 'portfolio', 'region', 'payer_label',
    'payer_name', 'pdpm_score')


class ResidentsQuery(PageQuery):
    # The shared filter-options client sends a date range; this list is always
    # the latest census day, so both are accepted and ignored.
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


class MedicareResident(BaseModel):
    stay_id: UUID
    resident_id: UUID
    facility_id: UUID
    resident_name: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    payer_type: str
    payer_name: str
    admission_date: date
    length_of_stay: int = Field(description='Days from admission to the census day.')
    ard: date | None = Field(description="The 5-day assessment's reference date; null until it is coded.")
    pdpm_score: str = Field(description='Four-letter PDPM code: PT/OT, SLP, nursing and NTA groups, '
        'or "Missing care code" before the code is available.')
    average_rate: float = Field(description='Total revenue over the days on this payer.')
    total_revenue: float = Field(description='PDPM revenue on this payer through the census day.')


class ResidentsPage(Page[MedicareResident]):
    census_date: date


def _current(day):
    """Every PDPM resident in a bed on the day, found through the range index."""
    return (select(logs).select_from(logs.join(payers, payers.c.payer_id == logs.c.payer_id)
            .join(contracts, pdpm_contract(logs)))
        .where(logs.c.in_bed.contains(day), payers.c.payer_type.in_(MEDICARE))
        .cte('current').prefix_with('MATERIALIZED'))


# The PDPM score shown before a resident's code is available.
NOT_CODED = 'Missing care code'


def _located(current, day):
    """The current rows with the columns every filter and search reads. The
    assessment joins only once its code is available on the day."""
    return (current
        .join(facilities, facilities.c.facility_id == current.c.facility_id)
        .join(regions).join(portfolios)
        .join(payers, payers.c.payer_id == current.c.payer_id)
        .outerjoin(assessments, and_(assessments.c.payer_stay_id == current.c.payer_stay_id,
            assessments.c.coded_date <= day)))


def _filter_columns():
    return (facilities.c.facility.label('facility_name'), portfolios.c.state, portfolios.c.portfolio,
        regions.c.region, payers.c.payer_type, payers.c.payer_name,
        case({payer_type: GROUP_LABELS[group] for payer_type, group in MEDICARE.items()},
            value=payers.c.payer_type, else_=payers.c.payer_type).label('payer_label'),
        func.coalesce(assessments.c.pdpm_code, NOT_CODED).label('pdpm_score'),
        # Null until coded, so no category matches a missing care code.
        assessments.c.pdpm_code, assessments.c.nursing_function_score, assessments.c.depression,
        assessments.c.cognitive_impairment, assessments.c.acute_neuro,
        assessments.c.mechanically_altered_diet, assessments.c.swallowing_disorder, assessments.c.slp_comorbidity)


def _category_predicates(listed):
    """Label -> condition for every part of every Overview category, in the
    order the Overview shows them. Labels are the category button and the part
    as the page names them, so the page can build one from a click."""
    from . import categories  # categories imports this module; import late
    code = listed.c.pdpm_code
    pt_ot, slp, nta = func.substr(code, 1, 1), func.substr(code, 2, 1), func.substr(code, 4, 1)
    position = lambda letter: func.ascii(letter) - ord('A')
    parts = {}
    for field, label in (('major_joint', 'Major Joint'), ('ortho', 'Ortho / Ortho Surgery'),
            ('acute_neuro', 'Acute Neuro / Non-Ortho'), ('medical_management', 'Medical Management')):
        parts[f'Primary Diagnosis: {label}'] = pt_ot.in_(list(categories.PRIMARY_DIAGNOSIS[field]))
    for band, label in enumerate(('0-5', '6-9', '10-23', '24')):
        parts[f'PT/OT: {label}'] = position(pt_ot) % 4 == band
    for index, field in enumerate(categories.SLP):
        speech, swallowing = divmod(index, 3)
        parts[f'SLP: {speech} speech, {swallowing} swallowing'] = slp == chr(ord('A') + index)
    for column, label in (('cognitive_impairment', 'Cognitive Ability'), ('acute_neuro', 'Acute Neuro Primary'),
            ('slp_comorbidity', 'Comorbidity'), ('mechanically_altered_diet', 'MAD'),
            ('swallowing_disorder', 'SD')):
        parts[f'Speech Comorbidity: {label}'] = listed.c[column].is_(True)
    for (low, high), label in zip(categories.NURSING.values(), ('0-5', '6-14', '15-16')):
        parts[f'Nursing: {label}'] = listed.c.nursing_function_score.between(low, high)
    for letter, label in zip(categories.NTA.values(), ('0', '1-2', '3-5', '6-8', '9-11', '12+')):
        parts[f'NTA: {label}'] = nta == letter
    for _, name, letters in pdpm_rates.NURSING_CATEGORIES:
        parts[f'Nursing Category: {name}'] = func.substr(code, 3, 1).in_(list(letters))
    parts['Depression: Yes'] = listed.c.depression.is_(True)
    parts['Depression: No'] = listed.c.depression.is_(False)
    return parts


def _filtered(listed, query: ResidentsQuery, exclude=None):
    result = select(listed)
    for key, values in json.loads(query.filters).items():
        if not values or key == exclude:
            continue
        if key == CATEGORY_FILTER:
            # OR within the filter, like every other; an unknown part matches nothing.
            parts = _category_predicates(listed)
            result = result.where(or_(false(), *(parts[value] for value in values if value in parts)))
        else:
            result = result.where(listed.c[FILTERS[key]].in_(values))
    if query.search.strip():
        result = result.where(or_(*(cast(listed.c[name], String).icontains(query.search.strip(), autoescape=True)
            for name in SEARCHABLE)))
    return result


def _rows(query: ResidentsQuery, census_date: date, exclude=None):
    """The finished, filtered list for one day, as a materialized CTE."""
    day = literal(census_date, Date)
    current = _current(day)
    # Each PDPM step's days up to and including the census day, times its rate.
    # A lateral subquery per resident reads each period's few steps through the
    # primary key, once for both columns that use it; a join scanned all 1.1M
    # steps and cost two thirds of the query.
    through = literal(census_date + timedelta(days=1), Date)
    step_days = func.least(func.upper(pdpm.c.in_effect), through) - func.lower(pdpm.c.in_effect)
    revenue = (select(func.coalesce(func.sum(pdpm.c.daily_rate * step_days), 0).label('total_revenue'))
        .where(pdpm.c.payer_stay_id == current.c.payer_stay_id, func.lower(pdpm.c.in_effect) <= day)
        .lateral('revenue'))
    rows = select(
        current.c.stay_id, current.c.resident_id, current.c.facility_id,
        (residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'),
        *_filter_columns(),
        current.c.admission_date,
        (day - current.c.admission_date).label('length_of_stay'),
        # Joined only once coded, like the score, so the two appear together.
        assessments.c.ard,
        func.round(revenue.c.total_revenue / (day - periods.c.start_date + 1), 2).label('average_rate'),
        revenue.c.total_revenue,
    ).select_from(_located(current, day)
        .join(residents, residents.c.resident_id == current.c.resident_id)
        .join(periods, periods.c.payer_stay_id == current.c.payer_stay_id)
        .join(revenue, true()))
    listed = rows.cte('listed').prefix_with('MATERIALIZED')
    return _filtered(listed, query, exclude), listed


def _option_rows(query: ResidentsQuery, census_date: date, exclude):
    """The same residents and filters, without revenue, stay length or payer
    periods, which no filter menu shows. Names are joined only for a search."""
    day = literal(census_date, Date)
    current = _current(day)
    source, columns = _located(current, day), [current.c.stay_id, *_filter_columns()]
    if query.search.strip():
        source = source.join(residents, residents.c.resident_id == current.c.resident_id)
        columns.append((residents.c.first_name + ' ' + residents.c.last_name).label('resident_name'))
    listed = select(*columns).select_from(source).cte('listed').prefix_with('MATERIALIZED')
    return _filtered(listed, query, exclude), listed


def _ordered(query: ResidentsQuery, census_date: date, *, with_total=False):
    result, listed = _rows(query, census_date)
    if with_total:
        result = result.add_columns(func.count().over().label('total'))
    column = listed.c[SORTS[query.sort or 'resident']]
    order = column.desc() if query.direction == 'desc' else column.asc()
    # A missing care code ranks as the last value: after P ascending, before it
    # descending. A blank ARD stays at the bottom either way.
    order = (order.nulls_first() if query.direction == 'desc' else order.nulls_last())         if query.sort == 'pdpm-score' else order.nulls_last()
    # Stable ties keep residents from moving unpredictably between pages.
    return result.order_by(order, listed.c.stay_id).limit(query.limit).offset(query.offset)


def valid_sort(query: ResidentsQuery) -> bool:
    return query.sort is None or query.sort in SORTS


def page(connection, query: ResidentsQuery, today: date):
    if not valid_sort(query):
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    census_date = census_day(connection, today)
    rows = connection.execute(_ordered(query, census_date, with_total=True)).mappings().all()
    if rows:
        total = rows[0]['total']
    else:
        # An empty page past the end still needs the true total.
        result, _ = _rows(query, census_date)
        total = connection.scalar(select(func.count()).select_from(result.subquery()))
    return dict(items=rows, total=total, limit=query.limit, offset=query.offset, census_date=census_date)


def options(connection, query: FilterQuery, today: date):
    if query.column not in FILTERS and query.column != CATEGORY_FILTER:
        raise ApiError('invalid_filter', 'Unsupported filter column.')
    census_date = census_day(connection, today)
    result, listed = _option_rows(query, census_date, exclude=query.column)
    if query.column == CATEGORY_FILTER:
        # Every part with at least one resident under the other filters, in
        # Overview order: one pass counts them all.
        parts = _category_predicates(listed)
        counts = connection.execute(result.with_only_columns(
            *(func.count().filter(condition) for condition in parts.values()))).one()
        return dict(options=[label for label, count in zip(parts, counts) if count])
    column = listed.c[FILTERS[query.column]]
    # Alphabetical, but Missing care code after every code, as the column sorts,
    # rather than among the M codes.
    return dict(options=sorted(connection.scalars(
        result.with_only_columns(cast(column, String).label('option')).distinct()),
        key=lambda option: (option == NOT_CODED, option)))


EXPORT_COLUMNS = (
    ('Resident', 'resident_name'), ('Facility', 'facility_name'), ('State', 'state'),
    ('Portfolio', 'portfolio'), ('Region', 'region'), ('Payer', 'payer_label'),
    ('Payer name', 'payer_name'), ('Admission date', 'admission_date'), ('Length of stay', 'length_of_stay'),
    ('ARD', 'ard'), ('PDPM score', 'pdpm_score'),
    ('Average rate', 'average_rate'), ('Total revenue', 'total_revenue'),
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
