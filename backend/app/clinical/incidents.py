"""Incidents: resident incidents in a date range, per facility, for the page to
sum and divide at any drilldown level.

Read from incident_logs, the seeder's record of every incident. Resulted in
hospitalization counts the incidents that sent the resident to a hospital: each
is a hospital transfer for a fall or injury, so the count agrees with Hospital
Transfers. Still open counts the range's incidents whose investigation had not
closed by the latest simulated day.

The rate is incidents per 1,000 resident days, as Hospital Transfers counts its
own: each day's closing census summed over the range.

Payer types, incident types and severities filter the report. Each breakdown
-- by type and by severity -- applies the other filters but not its own, so it
keeps every slice to click, as Hospital Transfers' donuts do; everything else
applies them all. Payer types narrow resident days too, so a payer's rate
divides by that payer's days.

Severity runs from 1 (no injury) to 5 (severe); 4 and 5 are major. Time of day
groups the hour each happened: morning 6:00-11:59, afternoon 12:00-17:59,
evening 18:00-21:59, night 22:00-5:59.
"""
from datetime import date, timedelta
from uuid import UUID
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    INCIDENT_TYPES, daily_payer_census_facts as census, incident_logs as incidents, payers)
from ..common.dates import DateRange
from ..common.locations import LocationSelection, facility_locations
from .coverage import latest_day, require_generated
from .hospital_transfers import PayerType

# Incidents from their log; resident days from the census summary.
GENERATORS = ('incident_logs', 'net_change_summary')


class FacilityIncidents(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    incidents: int = Field(description='Incidents in the range.')
    hospitalized: int = Field(description='Incidents that sent the resident to a hospital.')
    still_open: int = Field(description="Of the range's incidents, those not closed by the latest simulated day.")
    resident_days: int = Field(description='Closing census summed over the range: the rate per 1,000 divides by it.')
    morning: int = Field(description='Incidents from 6:00 to 11:59.')
    afternoon: int = Field(description='Incidents from 12:00 to 17:59.')
    evening: int = Field(description='Incidents from 18:00 to 21:59.')
    night: int = Field(description='Incidents from 22:00 to 5:59.')
    types: dict[str, int] = Field(description='Incidents by type.')
    severities: dict[str, int] = Field(description='Incidents by severity, 1 to 5, keyed by the level.')


class IncidentsReport(BaseModel):
    start_date: date
    end_date: date
    # The day "still open" is judged on.
    as_of: date
    items: list[FacilityIncidents]


class IncidentsQuery(DateRange):
    # Empty means every payer type, every incident type.
    payer_types: list[PayerType] = Field(default_factory=list, max_length=20)
    incident_types: list[Literal[INCIDENT_TYPES]] = Field(default_factory=list, max_length=20)
    # Whole numbers 1-5. Not a Literal: a query parameter arrives as text, which
    # a Literal of numbers rejects; an int field reads "4" as 4.
    severities: list[Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=list, max_length=5)


# The hour's part of the day.
TIMES_OF_DAY = {'morning': (6, 11), 'afternoon': (12, 17), 'evening': (18, 21)}


def _filters(query: IncidentsQuery, skip: str | None = None):
    """The query's filters on incident rows, less the one a breakdown shows."""
    conditions = []
    if query.payer_types and skip != 'payers':
        conditions.append(incidents.c.payer_id.in_(select(payers.c.payer_id)
            .where(payers.c.payer_type.in_(query.payer_types))))
    if query.incident_types and skip != 'types':
        conditions.append(incidents.c.incident_type.in_(query.incident_types))
    if query.severities and skip != 'severities':
        conditions.append(incidents.c.severity.in_(query.severities))
    return conditions


def incidents_report(connection: Connection, query: IncidentsQuery):
    require_generated(connection, GENERATORS, query.start_date, query.end_date)
    as_of = latest_day(connection)
    in_range = incidents.c.incident_date.between(query.start_date, query.end_date)
    totals = {row['facility_id']: row for row in connection.execute(
        select(incidents.c.facility_id, func.count().label('incidents'),
            func.count().filter(incidents.c.hospitalized).label('hospitalized'),
            func.count().filter(incidents.c.closed_date > as_of).label('still_open'),
            *(func.count().filter(incidents.c.incident_hour.between(first, last)).label(part)
                for part, (first, last) in TIMES_OF_DAY.items()),
            # Night wraps midnight: everything not in the three above.
            func.count().filter(~incidents.c.incident_hour.between(6, 21)).label('night'))
        .where(in_range, *_filters(query))
        .group_by(incidents.c.facility_id)).mappings()}
    # The two breakdowns, per facility, so the page scopes them as it scopes the
    # table; each applies the other's filter and keeps all of its own slices.
    by_severity, by_type = {}, {}
    for facility_id, level, count in connection.execute(
            select(incidents.c.facility_id, incidents.c.severity, func.count())
            .where(in_range, *_filters(query, skip='severities')).group_by(incidents.c.facility_id, incidents.c.severity)):
        by_severity.setdefault(facility_id, {})[str(level)] = count
    for facility_id, kind, count in connection.execute(
            select(incidents.c.facility_id, incidents.c.incident_type, func.count())
            .where(in_range, *_filters(query, skip='types')).group_by(incidents.c.facility_id, incidents.c.incident_type)):
        by_type.setdefault(facility_id, {})[kind] = count
    # A payer's rate divides by that payer's days.
    census_filters = [census.c.payer_type.in_(query.payer_types)] if query.payer_types else []
    resident_days = dict(connection.execute(
        select(census.c.facility_id, func.sum(census.c.closing_census))
        .where(census.c.summary_date.between(query.start_date, query.end_date), *census_filters)
        .group_by(census.c.facility_id)).all())
    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        row = totals.get(location['facility_id'], {})
        items.append(dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            incidents=int(row.get('incidents', 0)), hospitalized=int(row.get('hospitalized', 0)),
            still_open=int(row.get('still_open', 0)),
            **{part: int(row.get(part, 0)) for part in (*TIMES_OF_DAY, 'night')},
            resident_days=int(resident_days.get(location['facility_id'], 0) or 0),
            types=by_type.get(location['facility_id'], {}), severities=by_severity.get(location['facility_id'], {})))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=query.start_date, end_date=query.end_date, as_of=as_of, items=items)


class DailyIncidentsQuery(IncidentsQuery):
    # The drilldown's facilities; empty means every facility.
    facility_ids: list[UUID] = Field(default_factory=list, max_length=1000)


class DailyIncidents(BaseModel):
    days: list[dict] = Field(description='Every day of the range: its date and incidents, zero included.')


def daily(connection: Connection, query: DailyIncidentsQuery):
    """Each day's incidents for the trend: the same incidents and filters as the
    table, over the drilldown's facilities. A day with none is zero."""
    require_generated(connection, GENERATORS, query.start_date, query.end_date)
    conditions = _filters(query)
    if query.facility_ids:
        conditions.append(incidents.c.facility_id.in_(query.facility_ids))
    counts = dict(connection.execute(select(incidents.c.incident_date, func.count())
        .where(incidents.c.incident_date.between(query.start_date, query.end_date), *conditions)
        .group_by(incidents.c.incident_date)).all())
    return dict(days=[dict(date=query.start_date + timedelta(days=offset),
            incidents=counts.get(query.start_date + timedelta(days=offset), 0))
        for offset in range(query.days)])
