"""Historical Medicare PDPM: every Medicare PDPM stay whose start -- or whose
5-day assessment's ARD -- falls in a date range, per facility, with its length
and what it was paid against the case-mix-neutral rate.

The stays are the PDPM Worksheet's: Federal Medicare or Managed Medicare PDPM
payer periods on a PDPM contract, selected by the same date and date basis, so
the two reports agree about which stays a range holds. A stay counts whole --
every day from its start through its end, or through the latest census day
while it is still running -- however much of it falls inside the range: the
range picks the stays, not the days.

Revenue is each PDPM rate step's daily rate times its days, as the Current
Medicare PDPM Residents tab sums it; neutral revenue is the national per diem
times each step's PDPM day factor over the same days, as Current Medicare PDPM
prices its neutral rate.

Census days and the daily trend follow the same selection: the selected
stays' days in a bed inside the range, from their PDPM rate steps, so every
number on the page is about the same stays and the date basis changes them
all. Census days are the trend's daily census summed. Average daily census
divides them by the range's days with census logs.

Facility rows carry sums, never averages. The page divides once, at whatever
scope it shows: rates by Medicare days, length of stay by stays, average daily
census by `census_range_days`.
"""
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, func, literal, select
from sqlalchemy.dialects.postgresql import DATERANGE
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_runs, facility_payer_rates as contracts, payers,
    pdpm_assessments as assessments, pdpm_rate_logs as pdpm, res_payer_stays as periods, res_stays as stays)
from ..common.locations import LocationSelection, facility_locations
from . import categories as category_counts
from .service import GENERATOR, MEDICARE, NATIONAL_PER_DIEM, census_day

# The longest range one request may ask for, as the worksheet allows.
MAX_RANGE_DAYS = 3660


class HistoricalQuery(BaseModel):
    # Inclusive, applied to each stay's start (start) or its 5-day ARD (ard).
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


class FacilityHistorical(BaseModel):
    facility_id: UUID
    facility_name: str
    state: str
    portfolio: str
    region: str
    federal: int = Field(description='Original Medicare PDPM stays in the range.')
    managed: int = Field(description='Managed Medicare PDPM stays in the range. Managed Medicare PPO pays '
        'per diem and is not counted.')
    medicare_days: int = Field(description='Days on Medicare across those stays, through each one\'s end or the '
        'census day. Divide by the stays for the average length of stay, and divide revenue by it for a rate.')
    actual_revenue: float = Field(description='What the payer paid over those days: each PDPM step\'s rate '
        'times its days.')
    neutral_revenue: float = Field(description='The same days at the case-mix-neutral rate: the national per '
        'diem times each step\'s PDPM day factor, with no care level or facility case-mix index.')
    census_days: int = Field(description="The selected stays' days in a bed inside the range. Divide by "
        '`census_range_days` for the average daily census.')


class HistoricalMedicare(BaseModel):
    start_date: date
    end_date: date
    date_basis: Literal['start', 'ard']
    census_date: date = Field(description='The latest census day: running stays are counted through it.')
    census_range_days: int = Field(description='Days in the range with census logs: the average daily '
        'census divides by these, so a range running past the census day is not diluted.')
    neutral_per_diem: float
    items: list[FacilityHistorical]


def _selected(query: HistoricalQuery, census_date: date):
    """The range's Medicare PDPM stays, one row each: the worksheet's stays, by
    stay start or ARD, with their facility, payer type and Medicare days through
    the census day. A subquery, not a materialized CTE, so PostgreSQL can plan
    each use's joins through it."""
    # census_logs ranges are half-open, as end_date is: the day after the last.
    through = literal(census_date + timedelta(days=1), Date)
    by_ard = query.date_basis == 'ard'
    # Start from the date the range applies to, so its index narrows the rows
    # first, as the worksheet does.
    source = (assessments.join(periods, periods.c.payer_stay_id == assessments.c.payer_stay_id)
        if by_ard else periods)
    source = (source
        .join(payers, payers.c.payer_id == periods.c.payer_id)
        .join(stays, stays.c.stay_id == periods.c.stay_id)
        .join(contracts, (contracts.c.facility_id == stays.c.facility_id)
            & (contracts.c.payer_id == periods.c.payer_id) & (contracts.c.payment_method == 'pdpm')))
    return (select(periods.c.payer_stay_id, stays.c.facility_id, payers.c.payer_type, stays.c.admission_date,
            (func.least(func.coalesce(periods.c.end_date, through), through) - periods.c.start_date)
                .label('medicare_days'))
        .select_from(source)
        .where(payers.c.payer_type.in_(MEDICARE),
            (assessments.c.ard if by_ard else periods.c.start_date).between(query.start_date, query.end_date))
        .subquery('selected'))


def categories(connection: Connection, query: HistoricalQuery, today: date):
    """The range's stays counted by PDPM category, by the rules Current Medicare
    PDPM counts its residents: a stay counts once its code is available by the
    census day, and as a missing care code before."""
    census_date = census_day(connection, today)
    selected = _selected(query, census_date)
    return dict(census_date=census_date, items=category_counts.by_facility(
        connection, selected, literal(census_date, Date), selected.c.medicare_days))


def historical(connection: Connection, query: HistoricalQuery, today: date):
    census_date = census_day(connection, today)
    day = literal(census_date, Date)
    through = literal(census_date + timedelta(days=1), Date)
    selected = _selected(query, census_date)
    # Every rate step of the stay through the census day. A stay's steps cover
    # each of its days exactly once, so their days are its Medicare days --
    # measured equal over a year of stays -- and its first step counts it once.
    # Joined rather than summed per stay in a lateral subquery: 64,686
    # one-at-a-time lookups for a year cost 850 ms, the join 340 ms.
    source = selected.join(pdpm, (pdpm.c.payer_stay_id == selected.c.payer_stay_id)
        & (func.lower(pdpm.c.in_effect) <= day))
    step_days = func.least(func.upper(pdpm.c.in_effect), through) - func.lower(pdpm.c.in_effect)
    totals = {}
    for row in connection.execute(select(
            selected.c.facility_id, selected.c.payer_type, func.count().filter(pdpm.c.step == 1).label('stays'),
            func.sum(step_days).label('medicare_days'),
            func.sum(pdpm.c.daily_rate * step_days).label('actual_revenue'),
            func.sum(NATIONAL_PER_DIEM * pdpm.c.pdpm_factor * step_days).label('neutral_revenue'))
            .select_from(source)
            .group_by(selected.c.facility_id, selected.c.payer_type)).mappings():
        facility = totals.setdefault(row['facility_id'], dict(
            federal=0, managed=0, medicare_days=0, actual_revenue=0.0, neutral_revenue=0.0))
        facility[MEDICARE[row['payer_type']]] += row['stays']
        facility['medicare_days'] += row['medicare_days']
        facility['actual_revenue'] += float(row['actual_revenue'])
        facility['neutral_revenue'] += float(row['neutral_revenue'])

    # Census days: the selected stays' days inside the range, from the same
    # rate steps, which cover each Medicare day once -- the trend's daily census
    # summed, so the two always agree.
    last = min(query.end_date, census_date)
    census = {}
    if query.start_date <= last:
        window = func.daterange(literal(query.start_date, Date), literal(last + timedelta(days=1), Date),
            type_=DATERANGE)
        overlap = pdpm.c.in_effect * window
        census = dict(connection.execute(select(
                selected.c.facility_id, func.sum(func.upper(overlap) - func.lower(overlap)))
                .select_from(selected.join(pdpm, pdpm.c.payer_stay_id == selected.c.payer_stay_id))
                .where(pdpm.c.in_effect.overlaps(window))
                .group_by(selected.c.facility_id)).all())
    range_days = connection.scalar(select(func.count()).where(daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(query.start_date, last)))

    # Every facility, so one with no stays in the range reads as zero rather
    # than disappearing from its parent's drilldown.
    empty = dict(federal=0, managed=0, medicare_days=0, actual_revenue=0.0, neutral_revenue=0.0)
    items = [dict(facility_id=location['facility_id'], facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'],
            region=location['region_name'], **totals.get(location['facility_id'], empty),
            census_days=census.get(location['facility_id'], 0))
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(start_date=query.start_date, end_date=query.end_date, date_basis=query.date_basis,
        census_date=census_date, census_range_days=range_days, neutral_per_diem=float(NATIONAL_PER_DIEM),
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'],
            item['region'], item['facility_name'])))


class DailyQuery(HistoricalQuery):
    # The drilldown's facilities; empty means every facility.
    facility_ids: list[UUID] = Field(default_factory=list, max_length=1000)


class DailyPoint(BaseModel):
    date: date
    census: int = Field(description='PDPM residents in a bed that day.')
    neutral_rates: float = Field(description="Their case-mix-neutral rates that day, summed: the national per "
        "diem times each resident's PDPM day factor. Divide by census for the day's average.")
    actual_rates: float = Field(description="Their actual daily rates that day, summed: what the payer paid. "
        "Divide by census for the day's average.")
    stay_days: int = Field(description="Their days since admission that day, summed, as Current Medicare PDPM "
        "counts length of stay. Divide by census for the day's average length of stay.")


class DailyTrend(BaseModel):
    census_date: date
    days: list[DailyPoint] = Field(description='Every day of the range through the census day.')


def daily(connection: Connection, query: DailyQuery, today: date):
    """Each day's census of the selected stays -- the stays the table counts,
    by stay start or ARD -- with their summed neutral and actual rates and days
    since admission, for the trend charts. The date basis changes it as it
    changes the table.

    Read from the PDPM rate steps, which cover each Medicare stay's days exactly
    once with the day factor in effect. Rather than listing every resident on
    every day -- 1.8 million rows for a year -- each step adds its resident and
    factor on the day it starts in the range and takes them away the day after it
    ends; a running sum over the days turns those changes into each day's level.
    Length of stay rides the same sum: a resident's days since admission on a
    day are the day less their admission date, so summed over everyone in a bed
    they are census times the day less their admission dates summed -- and
    those dates are one more running sum."""
    census_date = census_day(connection, today)
    last = min(query.end_date, census_date)
    if query.start_date > last:
        return dict(census_date=census_date, days=[])
    window = func.daterange(literal(query.start_date, Date), literal(last + timedelta(days=1), Date),
        type_=DATERANGE)
    # The table's stays first, by the same date and date basis, then only
    # their own steps through the primary key. Scanning every step in the range
    # and keeping the selected stays' took 4.9-8.7 s for a year.
    selected = _selected(query, census_date)
    chosen = select(selected.c.payer_stay_id, selected.c.admission_date)
    if query.facility_ids:
        chosen = chosen.where(selected.c.facility_id.in_(query.facility_ids))
    chosen = chosen.cte('chosen').prefix_with('MATERIALIZED')
    clipped = pdpm.c.in_effect * window
    # Admission dates as days since a fixed day, so they can be summed.
    epoch = date(2000, 1, 1)
    steps = (select(func.lower(clipped).label('starts'), func.upper(clipped).label('ends'),
            (NATIONAL_PER_DIEM * pdpm.c.pdpm_factor).label('rate'), pdpm.c.daily_rate.label('actual'),
            (chosen.c.admission_date - literal(epoch, Date)).label('admitted'))
        .select_from(chosen.join(pdpm, pdpm.c.payer_stay_id == chosen.c.payer_stay_id))
        .where(pdpm.c.in_effect.overlaps(window)).cte('steps'))
    changes = select(steps.c.starts.label('day'), literal(1).label('residents'), steps.c.rate, steps.c.actual,
            steps.c.admitted).union_all(
        select(steps.c.ends, literal(-1), -steps.c.rate, -steps.c.actual, -steps.c.admitted)
            .where(steps.c.ends <= last)).subquery('changes')
    by_day = {day: totals for day, *totals in connection.execute(
        select(changes.c.day, func.sum(changes.c.residents), func.sum(changes.c.rate), func.sum(changes.c.actual),
            func.sum(changes.c.admitted)).group_by(changes.c.day))}
    days, census, rates, actual, admitted = [], 0, 0.0, 0.0, 0
    for offset in range((last - query.start_date).days + 1):
        day = query.start_date + timedelta(days=offset)
        residents, rate, paid, admissions = by_day.get(day, (0, 0, 0, 0))
        census += residents
        rates += float(rate)
        actual += float(paid)
        admitted += int(admissions)
        days.append(dict(date=day, census=census, neutral_rates=round(rates, 2), actual_rates=round(actual, 2),
            stay_days=census * (day - epoch).days - admitted))
    return dict(census_date=census_date, days=days)
