"""Current Medicare: who is on a Medicare payer on the census day, what each is
paid, and the case-mix-neutral rate for the same residents.

Read from census_logs, like the Residents tab and Daily Census's rates, so the
three cannot disagree about who is in a bed or what they are paid. Every Medicare
payer is skilled, so each resident's rate that day is the PDPM step in
pdpm_rate_logs.

The neutral rate ignores case mix entirely: the national per diem times the
resident's PDPM day factor, with no care level and no facility case-mix index.
The day factor stays because it is Medicare's variable per diem schedule, not
acuity. What separates the two rates is then everything specific to the facility
and resident -- wage index, case mix, care level -- and, for Medicare Advantage,
the negotiated contract.

Facility rows carry sums, never averages. The page divides once, at whatever
scope it shows, so every average is weighted by residents.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, and_, func, literal, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    census_logs as logs, daily_runs, payers, pdpm_rate_logs as pdpm)
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations

GENERATOR = 'census_logs'
# Payer type -> the report's field for its residents.
MEDICARE = {'medicare': 'federal', 'medicare_hmo': 'hmo', 'medicare_comm': 'commercial'}
# Medicare Part A per diem at national average wage index and a case-mix index
# of 1.0, before PDPM day adjustments. The demo's stand-in for CMS's published
# unadjusted national rate; it is the midpoint the payer_rates generator
# (BASE_RATE['medicare']) scatters facility rates around, so keep them equal.
NATIONAL_PER_DIEM = Decimal(720)


def census_day(connection: Connection, today: date) -> date:
    """The latest day with census logs on or before today, shared by both tabs."""
    census_date = connection.scalar(select(func.max(daily_runs.c.simulation_date)).where(
        daily_runs.c.generator == GENERATOR, daily_runs.c.simulation_date <= today))
    if census_date is None:
        raise ApiError('summary_unavailable', 'Census logs have not been generated yet. '
            'Run the seeder update.', 409)
    return census_date


def current(connection: Connection, today: date):
    first, last, generated_at = connection.execute(select(
        func.min(daily_runs.c.simulation_date), func.max(daily_runs.c.simulation_date),
        func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator == GENERATOR)).one()
    census_date = census_day(connection, today)

    day = literal(census_date, Date)
    actual = func.coalesce(pdpm.c.daily_rate, logs.c.daily_rate)
    totals = {}
    for row in connection.execute(select(
            logs.c.facility_id, payers.c.payer_type, func.count().label('residents'),
            func.sum(actual).label('actual_rates'),
            func.sum(NATIONAL_PER_DIEM * func.coalesce(pdpm.c.pdpm_factor, 1)).label('neutral_rates'),
            # Days in the facility, as the Residents tab counts them.
            func.sum(day - logs.c.admission_date).label('resident_days'))
            .select_from(logs
                .join(payers, payers.c.payer_id == logs.c.payer_id)
                .outerjoin(pdpm, and_(pdpm.c.payer_stay_id == logs.c.payer_stay_id,
                    pdpm.c.in_effect.contains(day))))
            .where(logs.c.in_bed.contains(day), payers.c.payer_type.in_(MEDICARE))
            .group_by(logs.c.facility_id, payers.c.payer_type)).mappings():
        facility = totals.setdefault(row['facility_id'], dict(
            federal=0, hmo=0, commercial=0, actual_rates=0.0, neutral_rates=0.0, resident_days=0))
        facility[MEDICARE[row['payer_type']]] = row['residents']
        facility['actual_rates'] += float(row['actual_rates'])
        facility['neutral_rates'] += float(row['neutral_rates'])
        facility['resident_days'] += row['resident_days']

    # Every facility, so one with no Medicare residents reads as zero rather
    # than disappearing from its parent's drilldown.
    empty = dict(federal=0, hmo=0, commercial=0, actual_rates=0.0, neutral_rates=0.0, resident_days=0)
    items = [dict(facility_id=location['facility_id'], facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'],
            region=location['region_name'], **totals.get(location['facility_id'], empty))
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(as_of=today, census_date=census_date, neutral_per_diem=float(NATIONAL_PER_DIEM),
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'],
            item['region'], item['facility_name'])),
        data_status=dict(available_from=first, available_through=last, generated_at=generated_at))
