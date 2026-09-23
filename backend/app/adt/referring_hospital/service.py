"""Aggregate monthly referral facts in PostgreSQL.

Every measure here is additive, so a hospital's total is a GROUP BY over the
facilities it referred into and no parent scope is stored. The report's own
windows -- 3 recent months against the preceding 24, inside 36 -- are applied
after aggregation, because they are ratios of sums rather than sums.

The 36 months end with the last complete month. An incomplete month would drag
every average down by however much of it has not happened yet, which is why the
report has never shown the current one.
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select, tuple_
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_runs, monthly_referral_facts as facts, portfolios, referring_hospitals, regions)
from ...common.errors import ApiError
from ...common.locations import LocationSelection, facility_locations
from .schemas import PerformanceQuery

GENERATOR = 'referrals_summary'
MONTHS = 36
RECENT_MONTHS = 3
BASELINE_MONTHS = 24
# The two windows the report compares, and the only months a receiving facility's
# own total covers. The nine months before them are history the chart shows and
# the comparison ignores.
COMPARED_MONTHS = RECENT_MONTHS + BASELINE_MONTHS


def _shift_month(month, offset):
    count = month.year * 12 + month.month - 1 + offset
    return date(count // 12, count % 12 + 1, 1)


def _window(today):
    """36 complete months ending with the month before the report's today."""
    current = today.replace(day=1)
    start = _shift_month(current, -MONTHS)
    return start, current - timedelta(days=1), [
        _shift_month(start, index).strftime('%Y-%m') for index in range(MONTHS)]


def _coverage(connection, start, end):
    """Completeness is the seeder's committed checkpoints, not row presence.

    A month in which a hospital referred nobody has no rows and must read as
    zero; a month never generated cannot be told apart from it by row presence.
    """
    first, last, generated_at = connection.execute(select(
        func.min(daily_runs.c.simulation_date), func.max(daily_runs.c.simulation_date),
        func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator == GENERATOR)).one()
    covered = connection.scalar(select(func.count()).select_from(daily_runs).where(
        daily_runs.c.generator == GENERATOR, daily_runs.c.simulation_date.between(start, end)))
    if covered != (end - start).days + 1:
        available = f'{first} through {last}' if first is not None else 'no completed dates'
        raise ApiError('summary_unavailable', 'Referring hospital performance needs 36 complete '
            f'months ending {end}. Referral facts are available for {available}. '
            'Run the seeder update before loading this report.', 409)
    return first, last, generated_at


def _comparisons(months):
    """The report's monthly comparison contract, over 36 complete months.

    Every value is a mean of sums rather than a mean of means, so a hospital's
    numbers stay correct however many facilities it referred into.
    """
    recent = sum(months[-RECENT_MONTHS:]) / RECENT_MONTHS
    previous = sum(months[-2 * RECENT_MONTHS:-RECENT_MONTHS]) / RECENT_MONTHS
    usual = sum(months[-COMPARED_MONTHS:-RECENT_MONTHS]) / BASELINE_MONTHS
    historical = sum(months) / MONTHS
    return dict(
        recent_average=recent, usual_average=usual, difference=recent - usual,
        difference_percent=(recent - usual) / usual * 100 if usual else None,
        previous_average=previous,
        change_percent=(recent - previous) / previous * 100 if previous else None,
        six_month_average=sum(months[-6:]) / 6, year_average=sum(months[-12:]) / 12,
        historical_average=historical, change_vs_average=recent - historical,
        previous_month_admissions=months[-1],
    )


def _directory(connection):
    """Hospital to location. A hospital refers into exactly one region."""
    return {row['hospital']: row for row in connection.execute(select(
        referring_hospitals.c.hospital, portfolios.c.state,
        portfolios.c.portfolio.label('portfolio_name'), regions.c.region.label('region_name'))
        .select_from(referring_hospitals.join(regions).join(portfolios))).mappings()}


def performance(connection: Connection, query: PerformanceQuery, today: date):
    start, end, labels = _window(today)
    first, last, generated_at = _coverage(connection, start, end)
    last_month = _shift_month(start, MONTHS - 1)
    index_of = {label: index for index, label in enumerate(labels)}

    conditions = [facts.c.month_start.between(start, last_month)]
    if query.payer_types:
        conditions.append(facts.c.payer_type.in_(query.payer_types))
    if query.hospital is not None:
        conditions.append(facts.c.hospital == query.hospital)
    # Location selection narrows the admissions counted, not which hospitals
    # exist. An empty selection means unfiltered; a selection matching nothing
    # matches nothing, and never silently widens.
    all_rows = connection.execute(facility_locations(LocationSelection())).mappings().all()
    selected = ([] if query.match_none else
        connection.execute(facility_locations(query)).mappings().all())
    names = {row['facility_id']: row['facility_name'] for row in selected}
    if len(selected) != len(all_rows):
        conditions.append(facts.c.facility_id.in_(sorted(names)))

    if query.hospital is not None:
        # One hospital: the facility series is the answer, and the hospital's own
        # months roll up from it. An indexed lookup on (hospital, month_start).
        rows = connection.execute(select(
            facts.c.facility_id, facts.c.month_start,
            func.sum(facts.c.admissions).label('admissions')).where(*conditions)
            .group_by(facts.c.facility_id, facts.c.month_start)).mappings().all()
        hospitals = {query.hospital: [0] * MONTHS}
        facility_months = defaultdict(lambda: [0] * MONTHS)
        for row in rows:
            index = index_of[row['month_start'].strftime('%Y-%m')]
            hospitals[query.hospital][index] += row['admissions']
            facility_months[row['facility_id']][index] += row['admissions']
        receiving = {query.hospital: {facility_id: dict(
            facility_id=facility_id, facility=names[facility_id],
            admissions=sum(months[-COMPARED_MONTHS:]), months=months)
            for facility_id, months in facility_months.items()}}
    else:
        # Every hospital: one scan, two groupings. The month series and the
        # per-facility totals come from the same pass rather than two.
        compared = func.sum(facts.c.admissions).filter(
            facts.c.month_start >= _shift_month(start, MONTHS - COMPARED_MONTHS))
        rows = connection.execute(select(
            facts.c.hospital, facts.c.month_start, facts.c.facility_id,
            func.grouping(facts.c.month_start).label('no_month'),
            func.sum(facts.c.admissions).label('admissions'),
            compared.label('compared')).where(*conditions)
            .group_by(func.grouping_sets(
                tuple_(facts.c.hospital, facts.c.month_start),
                tuple_(facts.c.hospital, facts.c.facility_id)))).mappings().all()
        hospitals = defaultdict(lambda: [0] * MONTHS)
        receiving = defaultdict(dict)
        for row in rows:
            if row['no_month']:
                # A facility a hospital stopped referring to before the compared
                # window still has rows in the nine months before it. It is not a
                # receiving facility for a comparison that covers none of them.
                if row['compared']:
                    receiving[row['hospital']][row['facility_id']] = dict(
                        facility_id=row['facility_id'], facility=names[row['facility_id']],
                        admissions=row['compared'], months=[])
            else:
                hospitals[row['hospital']][index_of[row['month_start'].strftime('%Y-%m')]] = (
                    row['admissions'])

    directory = _directory(connection)
    items = []
    for hospital, months in hospitals.items():
        location = directory.get(hospital)
        if location is None or not sum(months):
            continue
        items.append(dict(hospital=hospital, state=location['state'],
            portfolio=location['portfolio_name'], region=location['region_name'],
            months=months, receiving_facilities=sorted(
                receiving.get(hospital, {}).values(),
                key=lambda row: (-row['admissions'], row['facility'])),
            **_comparisons(months)))
    items.sort(key=lambda row: row['hospital'])
    return dict(months=labels, start_date=start, end_date=end, items=items,
        data_status=dict(complete=True, available_from=first, available_through=last,
            generated_at=generated_at, schema_version=1))
