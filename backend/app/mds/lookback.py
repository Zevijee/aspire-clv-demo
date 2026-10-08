"""Current Medicare PDPM against its own past: each facility's PDPM residents and
their summed actual and neutral daily rates today, and averaged over last
month, the last 6 months, the last year and all time: every day ever generated.

Periods follow Daily Census: last month is the previous calendar month, and the
trailing periods end yesterday -- 6 and 12 months back from the census day --
so today is never inside an average it is compared with. All time runs from
the first generated day to yesterday.

Whole months come from monthly_pdpm_census_facts, a rollup of the PDPM rate
steps; only today and a few edge days come from the steps themselves, which
cover each Medicare stay's days exactly once with the day's rate and day factor
-- measured equal to census_logs' PDPM census, day by day. Both count Federal
Medicare and Managed Medicare PDPM on a PDPM contract, as Current Medicare PDPM
does. From the steps alone every load read four years of them: 1.1 s. Now
~220 ms, most of it joining ~26k edge steps to their stays; carrying facility
and payer type on the steps would remove that, at a change to census_logs.

Facility rows carry sums; the page divides once at any scope. A period's
average daily census is its resident-days over its generated days; its rates
are summed rates over resident-days, so each is weighted by who was in a bed.
"""
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import Date, func, literal, or_, select
from sqlalchemy.dialects.postgresql import DATERANGE
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_runs, facility_payer_rates as contracts, monthly_pdpm_census_facts as facts, payers,
    pdpm_rate_logs as pdpm, res_payer_stays as periods, res_stays as stays)
from ..common.dates import rollup_plan
from ..common.errors import ApiError
from ..census.service import _back, _previous_month
from ..common.locations import LocationSelection, facility_locations
from .service import GENERATOR, MEDICARE, NATIONAL_PER_DIEM, census_day

# The monthly rollup's generator, whose checkpoint says how far it has been built.
ROLLUP = 'pdpm_census_summary'


class PeriodTotals(BaseModel):
    resident_days: int = Field(description='PDPM residents in a bed, summed over the days.')
    actual_rates: float = Field(description='Their daily rates, summed over the same days.')
    neutral_rates: float = Field(description='Their case-mix-neutral rates, summed over the same days.')


class Period(BaseModel):
    key: str
    label: str
    start: date
    end: date = Field(description='Inclusive.')
    days: int = Field(description='Generated days in the period: the average daily census divides by these.')


class FacilityLookback(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    periods: dict[str, PeriodTotals] = Field(description='Today and each average period, keyed by its `key`.')


class Lookback(BaseModel):
    census_date: date
    periods: list[Period] = Field(description='Today first, then the averages, nearest first.')
    items: list[FacilityLookback]


def lookback(connection: Connection, today: date):
    census_date = census_day(connection, today)
    yesterday = census_date - timedelta(days=1)
    first = connection.scalar(select(func.min(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == GENERATOR))
    month_start, month_end = _previous_month(census_date)
    spans = [('today', 'Today', census_date, census_date),
        ('month', 'Last month avg.', month_start, month_end),
        ('month_6', 'Last 6 months avg.', _back(census_date, months=6), yesterday),
        ('year', 'Last year avg.', _back(census_date, months=12), yesterday),
        ('all_time', 'All time avg.', first, yesterday)]
    # Never before the first generated day, and never an empty period.
    spans = [(key, label, max(start, first), end) for key, label, start, end in spans if end >= max(start, first)]
    generated = dict(connection.execute(select(*(
        func.count().filter(daily_runs.c.simulation_date.between(start, end)).label(key)
        for key, _, start, end in spans)).where(daily_runs.c.generator == GENERATOR)).one()._mapping)

    # Whole months come from the monthly rollup, and only a few days from the
    # rate steps: today, and the days of a rollup month outside the period (see
    # rollup_plan). All four years of steps took 1.1 s a load. The rollup is rebuilt
    # after census_logs on every update, so it must have reached the census day
    # being reported: its months then hold exactly the days through it.
    built = connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == ROLLUP))
    if built is None or built < census_date:
        raise ApiError('summary_unavailable', 'PDPM census facts are behind the census logs. '
            'Run the seeder update.', 409)
    # The rollup holds days only through the census day.
    plan = {key: rollup_plan(start, end, census_date) for key, _, start, end in spans}

    totals = {}
    def add(facility_id, key, days, actual, factor_days):
        entry = totals.setdefault(facility_id, {}).setdefault(key, [0, 0.0, 0.0])
        entry[0] += int(days or 0)
        entry[1] += float(actual or 0)
        entry[2] += float(NATIONAL_PER_DIEM) * float(factor_days or 0)

    whole = [(key, months) for key, (months, _) in plan.items() if months]
    if whole:
        for row in connection.execute(select(facts.c.facility_id, *(
                func.sum(facts.c[column]).filter(facts.c.month_start.between(*months)).label(f'{key}_{column}')
                for key, months in whole for column in ('resident_days', 'actual_rates', 'factor_days')))
                .group_by(facts.c.facility_id)).mappings():
            for key, _ in whole:
                add(row['facility_id'], key, row[f'{key}_resident_days'], row[f'{key}_actual_rates'],
                    row[f'{key}_factor_days'])

    edges = {key: ranges for key, (_, ranges) in plan.items() if ranges}
    if edges:
        # Each step's bounds as dates: its first day and the day after its last,
        # open steps cut after the census day. Overlaps are then date arithmetic.
        windows = {(start, end) for ranges in edges.values() for _, start, end in ranges}
        # The steps in those dates first, through the in_effect range index, and
        # only then their stays. Joined the other way round, PostgreSQL started
        # from every Medicare stay ever and probed each one's steps: 242k
        # lookups and 620 ms for two months of steps.
        in_range = (select(pdpm.c.payer_stay_id, pdpm.c.daily_rate, pdpm.c.pdpm_factor,
                func.lower(pdpm.c.in_effect).label('starts'),
                func.least(func.upper(pdpm.c.in_effect), literal(census_date + timedelta(days=1), Date)).label('ends'))
            .where(or_(*(pdpm.c.in_effect.overlaps(func.daterange(
                literal(start, Date), literal(end + timedelta(days=1), Date), type_=DATERANGE))
                for start, end in sorted(windows))))
            .cte('in_range').prefix_with('MATERIALIZED'))
        steps = (select(stays.c.facility_id, in_range.c.daily_rate, in_range.c.pdpm_factor,
                in_range.c.starts, in_range.c.ends)
            .select_from(in_range
                .join(periods, periods.c.payer_stay_id == in_range.c.payer_stay_id)
                .join(payers, payers.c.payer_id == periods.c.payer_id)
                .join(stays, stays.c.stay_id == periods.c.stay_id)
                .join(contracts, (contracts.c.facility_id == stays.c.facility_id)
                    & (contracts.c.payer_id == periods.c.payer_id) & (contracts.c.payment_method == 'pdpm')))
            .where(payers.c.payer_type.in_(MEDICARE))
            .subquery('steps'))

        def days_in(start, end):
            # A step's days inside the range, or zero when they miss each other.
            return func.greatest(func.least(steps.c.ends, literal(end + timedelta(days=1), Date))
                - func.greatest(steps.c.starts, literal(start, Date)), 0)

        columns = []
        for key, ranges in edges.items():
            # Signed: days taken away from a rollup month count negative.
            days = sum((sign * days_in(start, end) for sign, start, end in ranges[1:]),
                ranges[0][0] * days_in(ranges[0][1], ranges[0][2]))
            columns += [func.sum(days).label(f'{key}_days'), func.sum(days * steps.c.daily_rate).label(f'{key}_actual'),
                func.sum(days * steps.c.pdpm_factor).label(f'{key}_factor')]
        for row in connection.execute(select(steps.c.facility_id, *columns).group_by(steps.c.facility_id)).mappings():
            for key in edges:
                add(row['facility_id'], key, row[f'{key}_days'], row[f'{key}_actual'], row[f'{key}_factor'])

    def facility_periods(facility_id):
        sums = totals.get(facility_id, {})
        return {key: dict(zip(('resident_days', 'actual_rates', 'neutral_rates'), sums.get(key, (0, 0.0, 0.0))))
            for key, _, _, _ in spans}
    items = [dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            periods=facility_periods(location['facility_id']))
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(census_date=census_date,
        periods=[dict(key=key, label=label, start=start, end=end, days=generated[key])
            for key, label, start, end in spans],
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name'])))
