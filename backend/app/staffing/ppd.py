"""Staffing PPD: hours worked per patient day, per facility and role, in a date
range, for the page to add up and divide once at any drilldown level, for any
set of roles.

PPD is hours over census days: each day's closing census summed over the range,
read once per facility from daily_payer_census_facts -- never once per role, so
any set of roles divides by the same census days. Target PPD is target hours
over the same census days.

Excess and short hours are measured each day at facility and role grain (see
daily_staffing_facts), so they add up across facilities and days without
offsetting: a state can show hours over target and hours short at once.
Excess wages are the excess hours at each day's rate; the average rate is wages
over hours.

Completeness comes from the seeder's checkpoints: a range with a day never
generated is a 409.
"""
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import daily_payer_census_facts as census, daily_staffing_facts as staffing
from shared.staffing import ROLE_CODES, ROLES
from ..clinical.coverage import require_generated
from ..common.dates import DateRange
from ..common.locations import LocationSelection, facility_locations

# Hours from the staffing facts; census days from the census summary.
GENERATORS = ('staffing_summary', 'net_change_summary')
MEASURES = ('hours', 'target_hours', 'excess_hours', 'short_hours', 'wages', 'excess_wages')


class Role(BaseModel):
    code: str
    label: str
    group: str = Field(description='Nursing, Therapy or Support.')


class RoleHours(BaseModel):
    hours: float = Field(description='Hours worked in the range.')
    target_hours: float = Field(description='Target PPD x census, each day, summed.')
    excess_hours: float = Field(description='Hours over the day\'s target, summed over days.')
    short_hours: float = Field(description='Hours under the day\'s target, summed over days.')
    wages: float = Field(description='Pay for the hours worked. Average rate is wages / hours.')
    excess_wages: float = Field(description='The excess hours at each day\'s rate: what staffing exactly '
        'to target would have saved.')


class FacilityStaffing(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    census_days: int = Field(description='Closing census summed over the range. PPD is hours / census_days.')
    roles: dict[str, RoleHours] = Field(description='Each role\'s sums, by role code.')


class PpdReport(BaseModel):
    start_date: date
    end_date: date
    roles: list[Role] = Field(description='Every role, in report order.')
    items: list[FacilityStaffing]


def _census_days(start: date, end: date, facility_ids=None):
    """Closing census rows in the range, over the given facilities or all."""
    conditions = [census.c.summary_date.between(start, end)]
    if facility_ids:
        conditions.append(census.c.facility_id.in_(facility_ids))
    return conditions


def ppd(connection: Connection, query: DateRange):
    require_generated(connection, GENERATORS, query.start_date, query.end_date)
    in_range = staffing.c.summary_date.between(query.start_date, query.end_date)
    sums = {}
    for row in connection.execute(select(staffing.c.facility_id, staffing.c.role,
            func.sum(staffing.c.hours_worked).label('hours'), func.sum(staffing.c.target_hours).label('target_hours'),
            func.sum(staffing.c.excess_hours).label('excess_hours'), func.sum(staffing.c.short_hours).label('short_hours'),
            func.sum(staffing.c.wages).label('wages'), func.sum(staffing.c.excess_wages).label('excess_wages'))
            .where(in_range).group_by(staffing.c.facility_id, staffing.c.role)).mappings():
        sums.setdefault(row['facility_id'], {})[row['role']] = {measure: float(row[measure]) for measure in MEASURES}
    census_days = dict(connection.execute(select(census.c.facility_id, func.sum(census.c.closing_census))
        .where(*_census_days(query.start_date, query.end_date)).group_by(census.c.facility_id)).all())

    empty = {measure: 0.0 for measure in MEASURES}
    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        roles = sums.get(location['facility_id'], {})
        items.append(dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            census_days=int(census_days.get(location['facility_id'], 0) or 0),
            roles={code: roles.get(code, empty) for code in ROLE_CODES}))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=query.start_date, end_date=query.end_date,
        roles=[dict(code=code, label=label, group=group) for code, label, group, *_ in ROLES], items=items)


class DailyPpdQuery(DateRange):
    # Empty means every role, every facility.
    roles: list[Literal[ROLE_CODES]] = Field(default_factory=list, max_length=len(ROLE_CODES))
    facility_ids: list[UUID] = Field(default_factory=list, max_length=1000)


class DailyPpd(BaseModel):
    days: list[dict] = Field(description='Every day of the range: its date, census, hours worked and '
        'target hours over the given roles and facilities. PPD is hours / census.')


def daily(connection: Connection, query: DailyPpdQuery):
    """Each day's hours and census for the trend, over the drilldown's facilities
    and the chosen roles."""
    require_generated(connection, GENERATORS, query.start_date, query.end_date)
    conditions = [staffing.c.summary_date.between(query.start_date, query.end_date)]
    if query.roles:
        conditions.append(staffing.c.role.in_(query.roles))
    if query.facility_ids:
        conditions.append(staffing.c.facility_id.in_(query.facility_ids))
    hours = {day: (float(worked), float(target)) for day, worked, target in connection.execute(
        select(staffing.c.summary_date, func.sum(staffing.c.hours_worked), func.sum(staffing.c.target_hours))
        .where(*conditions).group_by(staffing.c.summary_date))}
    daily_census = dict(connection.execute(select(census.c.summary_date, func.sum(census.c.closing_census))
        .where(*_census_days(query.start_date, query.end_date, query.facility_ids))
        .group_by(census.c.summary_date)).all())
    days = []
    for offset in range(query.days):
        day = query.start_date + timedelta(days=offset)
        worked, target = hours.get(day, (0.0, 0.0))
        days.append(dict(date=day, census=int(daily_census.get(day, 0) or 0), hours=worked, target_hours=target))
    return dict(days=days)
