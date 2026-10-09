"""Fever / Infections: an alert board of possible outbreaks, as of one day.

Read from infection_logs, the seeder's record of every resident infection. Cases
of a contagious type -- respiratory, influenza-like illness, gastrointestinal --
are counted per facility and type over the 72 hours and the 7 days ending on the
day, and the counts set an alert:

    Outbreak: 3 or more new cases in 72 hours, or 5 or more in 7 days.
    Watch:    2 new cases in 72 hours, or 3 or 4 in 7 days.

A rule, not a label: the seeder does not mark which cases belong to an outbreak,
so the board finds clusters as an infection preventionist would, from onset
dates alone. Urinary tract and skin infections, and fevers with no known source,
do not spread from resident to resident and raise no alert; they still count
as new and active cases.

The day defaults to the latest one generated. A day is readable when the seven
days ending on it have all been generated; otherwise 409.
"""
import datetime
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import daily_runs, infection_logs as infections
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from .coverage import require_generated

GENERATORS = ('infection_logs',)
CONTAGIOUS = ('Respiratory', 'Influenza-like illness', 'Gastrointestinal')
# The two windows, in days ending on the day: 72 hours is that day and the two
# before it.
SHORT_DAYS, LONG_DAYS = 3, 7


def status(short: int, long: int) -> str:
    """The alert for one facility and type, from its case counts."""
    if short >= 3 or long >= 5:
        return 'outbreak'
    if short >= 2 or long >= 3:
        return 'watch'
    return 'clear'


class InfectionsQuery(BaseModel):
    # Absent means the latest generated day.
    date: datetime.date | None = None


class Alert(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    infection_type: str
    status: str = Field(description="'outbreak' or 'watch'.")
    cases_72_hours: int = Field(description='New cases with onset in the 72 hours ending on the day.')
    cases_7_days: int = Field(description='New cases with onset in the 7 days ending on the day.')
    with_fever: int = Field(description='Of the 7 days\' cases, those with a fever.')
    active: int = Field(description='Cases of the type not yet resolved on the day, whenever they began.')
    first_onset: date = Field(description='The earliest onset among the 7 days\' cases.')
    latest_onset: date
    wings: list[str] = Field(description='Wings with a case in the 7 days.')


class InfectionsBoard(BaseModel):
    date: datetime.date
    # The latest generated day, the date picker's last choice.
    latest: datetime.date
    facilities: int = Field(description='Every facility on the board.')
    facilities_in_outbreak: int
    facilities_on_watch: int = Field(description='Facilities with a watch and no outbreak.')
    new_cases_72_hours: int = Field(description='Every type, every facility.')
    active_cases: int = Field(description='Every type, every facility: begun on or before the day, not yet resolved.')
    alerts: list[Alert] = Field(description='Outbreaks first, then watches; most cases first within each.')


def latest_generated(connection: Connection) -> date | None:
    return connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == GENERATORS[0]))


def board(connection: Connection, query: InfectionsQuery):
    latest = latest_generated(connection)
    if latest is None:
        raise ApiError('summary_unavailable', 'Infections have not been generated yet. Run the seeder update.', 409)
    day = query.date or latest
    require_generated(connection, GENERATORS, day - timedelta(days=LONG_DAYS - 1), day)
    short_start = day - timedelta(days=SHORT_DAYS - 1)
    week = infections.c.onset_date.between(day - timedelta(days=LONG_DAYS - 1), day)
    clusters = connection.execute(
        select(infections.c.facility_id, infections.c.infection_type,
            func.count().filter(infections.c.onset_date >= short_start).label('short'),
            func.count().label('long'),
            func.count().filter(infections.c.fever).label('with_fever'),
            func.min(infections.c.onset_date).label('first_onset'),
            func.max(infections.c.onset_date).label('latest_onset'),
            func.array_agg(func.distinct(infections.c.wing)).label('wings'))
        .where(week, infections.c.infection_type.in_(CONTAGIOUS))
        .group_by(infections.c.facility_id, infections.c.infection_type)).mappings().all()
    # Active cases began at most 13 days before they resolve, so a bounded scan.
    is_active = (infections.c.onset_date <= day) & (infections.c.resolved_date > day)
    active = {(facility_id, kind): count for facility_id, kind, count in connection.execute(
        select(infections.c.facility_id, infections.c.infection_type, func.count())
        .where(infections.c.onset_date > day - timedelta(days=30), is_active)
        .group_by(infections.c.facility_id, infections.c.infection_type))}
    new_cases = connection.scalar(select(func.count()).select_from(infections)
        .where(infections.c.onset_date.between(short_start, day)))
    locations = {row['facility_id']: row for row in
        connection.execute(facility_locations(LocationSelection())).mappings()}

    alerts = []
    for row in clusters:
        level = status(row['short'], row['long'])
        if level == 'clear':
            continue
        location = locations[row['facility_id']]
        alerts.append(dict(facility_id=str(row['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            infection_type=row['infection_type'], status=level, cases_72_hours=row['short'],
            cases_7_days=row['long'], with_fever=row['with_fever'],
            active=active.get((row['facility_id'], row['infection_type']), 0),
            first_onset=row['first_onset'], latest_onset=row['latest_onset'], wings=sorted(row['wings'])))
    alerts.sort(key=lambda alert: (alert['status'] != 'outbreak', -alert['cases_7_days'],
        -alert['cases_72_hours'], alert['facility_name']))
    outbreak = {alert['facility_id'] for alert in alerts if alert['status'] == 'outbreak'}
    watch = {alert['facility_id'] for alert in alerts} - outbreak
    return dict(date=day, latest=latest, facilities=len(locations), facilities_in_outbreak=len(outbreak),
        facilities_on_watch=len(watch), new_cases_72_hours=new_cases, active_cases=sum(active.values()),
        alerts=alerts)
