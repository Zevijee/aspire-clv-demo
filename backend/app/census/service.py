"""Current census against last month's daily average, per facility.

Reads daily_payer_census_facts, the same dense table Net Change uses. Its payer
type split is what makes skilled census answerable; adt_daily_census has the
facility total only.

Census is a level, not a flow. Today's census is one day's closing census, never
a sum over days. The look-back compares it with single earlier days and with
averages (see lookback_periods). A period's census days -- closing census
summed over its days -- divided by its generated days is its average daily
census; for a one-day period, that day's census. Whole months come from
monthly_payer_census_facts and only the days at a period's edges from the
daily table; a single day reads the daily table alone.
Measured equal: the rollup's census_days matches the daily closing census summed
in all 85,609 month, facility and payer rows. Last month's average is the sum of every day's closing census
divided once by the days in the month -- per facility here, and because every
facility shares the same denominator, summing facility averages gives the parent
average exactly. Parent scopes are never stored.
"""
from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.engine import Connection

from shared.database.schema import (
    census_logs, daily_payer_census_facts as facts, daily_runs, monthly_payer_census_facts as months, payers,
    pdpm_rate_logs as pdpm)
from ..common.dates import rollup_plan
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations

GENERATOR = 'net_change_summary'
# The monthly rollup's generator, whose checkpoint says how far it has been built.
ROLLUP = 'monthly_adt_summary'


# The census day's movement, from daily_payer_census_facts: opening census, then
# the flows that take it to the closing census.
FLOWS = ('opening_census', 'admissions', 'discharges', 'changes_in', 'changes_out')


def _back(day, days=0, months=0):
    if days:
        return day - timedelta(days=days)
    count = day.year * 12 + day.month - 1 - months
    year, month = count // 12, count % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _previous_month(day):
    end = day.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def lookback_periods(census_date, first):
    """What a look-back compares the census day with, shared by Daily Census and
    both Current PDPM reports. Both kinds, as the product owner asked: first
    the real value on single earlier days, nearest first -- yesterday, and the
    same day a week, a month, 6 months and a year back -- then the averages.
    A single day is a period of one day, so the same sums give that day's value
    alone. Of the averages, last month is the previous calendar month, and the
    trailing periods end yesterday -- 6 and 12 calendar months back from the
    census day -- so today is never inside an average it is compared with. All
    time runs from the first generated day. Never before it, and never an
    empty period.

    Each is (key, label, start, end, average)."""
    yesterday = census_date - timedelta(days=1)
    month_start, month_end = _previous_month(census_date)
    days = [('day_1', 'Yesterday', yesterday), ('day_7', 'Week ago', _back(census_date, days=7)),
        ('day_month', 'Month ago', _back(census_date, months=1)),
        ('day_month_6', '6 months ago', _back(census_date, months=6)),
        ('day_year', 'Year ago', _back(census_date, months=12))]
    spans = [(key, label, day, day, False) for key, label, day in days] + [
        ('month', 'Last month', month_start, month_end, True),
        ('month_6', 'Last 6 months', _back(census_date, months=6), yesterday, True),
        ('year', 'Last year', _back(census_date, months=12), yesterday, True),
        ('all_time', 'All time', first, yesterday, True)]
    return [(key, label, max(start, first), end, average) for key, label, start, end, average in spans
        if end >= max(start, first)]


def live(connection: Connection, today: date, payer_types: list[str] | None = None):
    """payer_types narrows census, skilled census, averages and history to those
    payers. The payer mix and rates are that filter's own facets, so they keep
    every payer; all_census stays unfiltered, because a bed held by another
    payer's resident is not empty."""
    first, last, generated_at = connection.execute(select(
        func.min(daily_runs.c.simulation_date), func.max(daily_runs.c.simulation_date),
        func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator == GENERATOR)).one()
    # The latest completed day, not the latest row: completeness is the seeder's
    # checkpoint, and a day with an empty facility has no row to find.
    census_date = connection.scalar(select(func.max(daily_runs.c.simulation_date)).where(
        daily_runs.c.generator == GENERATOR, daily_runs.c.simulation_date <= today))
    if census_date is None:
        raise ApiError('summary_unavailable', 'Census has not been generated yet. '
            'Run the seeder update, including net_change_summary.', 409)

    month_start, month_end = _previous_month(census_date)
    month_days = (month_end - month_start).days + 1
    covered = connection.scalar(select(func.count()).select_from(daily_runs).where(
        daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(month_start, month_end)))
    month_complete = covered == month_days

    chosen_periods = lookback_periods(census_date, first)
    spans = [(key, label, start, end) for key, label, start, end, _ in chosen_periods]
    averages = {key: average for key, _, _, _, average in chosen_periods}
    generated = dict(connection.execute(select(*(
        func.count().filter(daily_runs.c.simulation_date.between(start, end)).label(key)
        for key, _, start, end in spans)).where(daily_runs.c.generator == GENERATOR)).one()._mapping)

    # A short list read once, so the aggregate below filters on literals rather
    # than joining payers on every fact row.
    skilled_types = sorted(set(connection.scalars(
        select(payers.c.payer_type).where(payers.c.is_skilled))))
    skilled = facts.c.payer_type.in_(skilled_types)
    today_rows = facts.c.summary_date == census_date
    month_rows = facts.c.summary_date.between(month_start, month_end)
    closing = facts.c.closing_census

    # One scan answers today and last month.
    chosen = facts.c.payer_type.in_(payer_types) if payer_types else true()
    totals = {row['facility_id']: row for row in connection.execute(select(
        facts.c.facility_id,
        func.coalesce(func.sum(closing).filter(today_rows), 0).label('all_census'),
        func.coalesce(func.sum(closing).filter(and_(today_rows, chosen)), 0).label('census'),
        func.coalesce(func.sum(closing).filter(and_(today_rows, skilled, chosen)), 0).label('skilled_census'),
        # The census day's movement on the selected payers: opening plus the
        # flows is the closing census above, the same identity Net Change reads.
        *(func.coalesce(func.sum(facts.c[flow]).filter(and_(today_rows, chosen)), 0).label(flow)
            for flow in FLOWS),
        func.coalesce(func.sum(closing).filter(and_(month_rows, chosen)), 0).label('month_census_days'),
        func.coalesce(func.sum(closing).filter(and_(month_rows, skilled, chosen)), 0).label('month_skilled_days'))
        .where(facts.c.summary_date.between(month_start, census_date))
        .group_by(facts.c.facility_id)).mappings()}

    # The periods' census days: whole months from the monthly rollup, and only
    # the days at a period's edges from the daily facts (see rollup_plan); a
    # single day is read from the daily facts alone. The rollup must reach
    # yesterday, the last day any period holds.
    built = connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == ROLLUP))
    if spans and (built is None or built < census_date - timedelta(days=1)):
        raise ApiError('summary_unavailable', 'Monthly census facts are behind the daily census. '
            'Run the seeder update.', 409)
    plan = {key: rollup_plan(start, end, built) for key, _, start, end in spans}
    period_days = {}

    def add(facility_id, key, census_days, skilled_days):
        entry = period_days.setdefault(facility_id, {}).setdefault(key, [0, 0])
        entry[0] += int(census_days or 0)
        entry[1] += int(skilled_days or 0)

    whole = [(key, span) for key, (span, _) in plan.items() if span]
    if whole:
        month_chosen = months.c.payer_type.in_(payer_types) if payer_types else true()
        month_skilled = months.c.payer_type.in_(skilled_types)
        for row in connection.execute(select(months.c.facility_id, *(
                func.sum(months.c.census_days).filter(and_(months.c.month_start.between(*span), month_chosen, *extra))
                    .label(f'{key}_{name}')
                for key, span in whole for name, extra in (('census', ()), ('skilled', (month_skilled,)))))
                .group_by(months.c.facility_id)).mappings():
            for key, _ in whole:
                add(row['facility_id'], key, row[f'{key}_census'], row[f'{key}_skilled'])

    edges = {key: ranges for key, (_, ranges) in plan.items() if ranges}
    if edges:
        # Each range's sum, signed: days taken away from a rollup month count negative.
        columns = [sum((sign * func.coalesce(func.sum(closing).filter(and_(
                facts.c.summary_date.between(start, end), chosen, *extra)), 0)
                for sign, start, end in ranges)).label(f'{key}_{name}')
            for key, ranges in edges.items() for name, extra in (('census', ()), ('skilled', (skilled,)))]
        windows = sorted({(start, end) for ranges in edges.values() for _, start, end in ranges})
        for row in connection.execute(select(facts.c.facility_id, *columns)
                .where(or_(*(facts.c.summary_date.between(start, end) for start, end in windows)))
                .group_by(facts.c.facility_id)).mappings():
            for key in edges:
                add(row['facility_id'], key, row[f'{key}_census'], row[f'{key}_skilled'])

    # The payer mix is the same census split by payer type. Kept per facility so
    # the report can sum it for whatever scope is drilled into.
    payer_census = {}
    for row in connection.execute(select(facts.c.facility_id, facts.c.payer_type, closing)
            .where(today_rows, closing > 0)).mappings():
        payer_census.setdefault(row['facility_id'], {})[row['payer_type']] = row['closing_census']

    # Every resident's daily rate that day, summed per facility and payer type. The
    # report divides by residents once, at whatever scope it shows, so the
    # average is weighted by who is actually in the beds -- never an average of
    # plan rates. Read from census_logs, which carries plan and care level, with
    # the day's PDPM rate for skilled payers -- the same rates the Residents tab
    # lists, so the two cannot disagree.
    daily_rates = {}
    for row in connection.execute(select(census_logs.c.facility_id, payers.c.payer_type,
            func.sum(func.coalesce(pdpm.c.daily_rate, census_logs.c.daily_rate)).label('daily_rates'))
            .select_from(census_logs
                .join(payers, census_logs.c.payer_id == payers.c.payer_id)
                .outerjoin(pdpm, and_(pdpm.c.payer_stay_id == census_logs.c.payer_stay_id,
                    pdpm.c.in_effect.contains(census_date))))
            .where(census_logs.c.in_bed.contains(census_date))
            .group_by(census_logs.c.facility_id, payers.c.payer_type)).mappings():
        daily_rates.setdefault(row['facility_id'], {})[row['payer_type']] = float(row['daily_rates'])

    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        # Absence of a row means zero; the checkpoints above already proved the
        # days were generated.
        row = totals.get(location['facility_id'], {})
        items.append(dict(
            facility_id=location['facility_id'], facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'],
            region=location['region_name'], capacity=location['beds'],
            census=row.get('census', 0), all_census=row.get('all_census', 0),
            skilled_census=row.get('skilled_census', 0),
            **{flow: row.get(flow, 0) for flow in FLOWS},
            payer_census=payer_census.get(location['facility_id'], {}),
            payer_daily_rates=daily_rates.get(location['facility_id'], {}),
            periods={key: dict(zip(('census_days', 'skilled_days'),
                period_days.get(location['facility_id'], {}).get(key, (0, 0)))) for key, _, _, _ in spans},
            previous_average=(row.get('month_census_days', 0) / month_days
                if month_complete else None),
            previous_skilled_average=(row.get('month_skilled_days', 0) / month_days
                if month_complete else None)))

    return dict(as_of=today, census_date=census_date, previous_month=month_start,
        previous_month_days=month_days,
        periods=[dict(key=key, label=label, start=start, end=end, days=generated[key], average=averages[key])
            for key, label, start, end in spans],
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'],
            item['region'], item['facility_name'])),
        data_status=dict(available_from=first, available_through=last, generated_at=generated_at))
