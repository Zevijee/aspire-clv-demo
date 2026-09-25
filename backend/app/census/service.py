"""Current census against last month's daily average, per facility.

Reads daily_payer_census_facts, the same dense table Net Change uses. Its payer
type split is what makes skilled census answerable; adt_daily_census has the
facility total only.

Census is a level, not a flow. Today's census is one day's closing census, never
a sum over days. Last month's average is the sum of every day's closing census
divided once by the days in the month -- per facility here, and because every
facility shares the same denominator, summing facility averages gives the parent
average exactly. Parent scopes are never stored.
"""
from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import and_, func, select, true
from sqlalchemy.engine import Connection

from shared.database.schema import (
    census_logs, daily_payer_census_facts as facts, daily_runs, payers, pdpm_rate_logs as pdpm)
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations

GENERATOR = 'net_change_summary'


# The history lookback: each column's key, label and distance back from the
# census day. Months are calendar months, so "3 months ago" from 31 May is 28 Feb.
LOOKBACK = (
    ('yesterday', 'Yesterday', dict(days=1)),
    ('week', '1 week ago', dict(days=7)),
    ('month', '1 month ago', dict(months=1)),
    ('month_3', '3 months ago', dict(months=3)),
    ('month_6', '6 months ago', dict(months=6)),
    ('month_9', '9 months ago', dict(months=9)),
    ('year', '1 year ago', dict(months=12)),
)


def _back(day, days=0, months=0):
    if days:
        return day - timedelta(days=days)
    count = day.year * 12 + day.month - 1 - months
    year, month = count // 12, count % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _previous_month(day):
    end = day.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


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

    lookback = [dict(key=key, label=label, date=_back(census_date, **distance))
        for key, label, distance in LOOKBACK]
    # The trailing year: the 12 months up to and including yesterday.
    year_start, year_end = _back(census_date, months=12), census_date - timedelta(days=1)
    year_days = (year_end - year_start).days + 1
    generated = set(connection.scalars(select(daily_runs.c.simulation_date).where(
        daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(year_start, census_date))))
    year_complete = sum(day <= year_end for day in generated) == year_days

    # A short list read once, so the aggregate below filters on literals rather
    # than joining payers on every fact row.
    skilled_types = sorted(set(connection.scalars(
        select(payers.c.payer_type).where(payers.c.is_skilled))))
    skilled = facts.c.payer_type.in_(skilled_types)
    today_rows = facts.c.summary_date == census_date
    month_rows = facts.c.summary_date.between(month_start, month_end)
    closing = facts.c.closing_census

    # One scan of the trailing year answers everything: last month and every
    # lookback day fall inside it. Measured: 205ms as three separate reads.
    year_rows = facts.c.summary_date.between(year_start, year_end)
    chosen = facts.c.payer_type.in_(payer_types) if payer_types else true()
    totals = {row['facility_id']: row for row in connection.execute(select(
        facts.c.facility_id,
        func.coalesce(func.sum(closing).filter(today_rows), 0).label('all_census'),
        func.coalesce(func.sum(closing).filter(and_(today_rows, chosen)), 0).label('census'),
        func.coalesce(func.sum(closing).filter(and_(today_rows, skilled, chosen)), 0).label('skilled_census'),
        func.coalesce(func.sum(closing).filter(and_(month_rows, chosen)), 0).label('month_census_days'),
        func.coalesce(func.sum(closing).filter(and_(month_rows, skilled, chosen)), 0).label('month_skilled_days'),
        func.coalesce(func.sum(closing).filter(and_(year_rows, chosen)), 0).label('year_census_days'),
        *(func.coalesce(func.sum(closing).filter(and_(facts.c.summary_date == entry['date'], chosen)), 0)
            .label(f"history_{entry['key']}") for entry in lookback))
        .where(facts.c.summary_date.between(min(year_start, month_start), census_date))
        .group_by(facts.c.facility_id)).mappings()}

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
            payer_census=payer_census.get(location['facility_id'], {}),
            payer_daily_rates=daily_rates.get(location['facility_id'], {}),
            # A day never generated reads as null rather than zero.
            history={entry['key']: row.get(f"history_{entry['key']}", 0)
                if entry['date'] in generated else None for entry in lookback},
            year_average=(row.get('year_census_days', 0) / year_days
                if year_complete else None),
            previous_average=(row.get('month_census_days', 0) / month_days
                if month_complete else None),
            previous_skilled_average=(row.get('month_skilled_days', 0) / month_days
                if month_complete else None)))

    return dict(as_of=today, census_date=census_date, previous_month=month_start,
        previous_month_days=month_days,
        lookback=lookback, year_start=year_start, year_end=year_end,
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'],
            item['region'], item['facility_name'])),
        data_status=dict(available_from=first, available_through=last, generated_at=generated_at))
