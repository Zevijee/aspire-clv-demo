"""PBJ Compliance: each facility's nurse staffing for one Payroll-Based Journal
quarter, as CMS reads the PBJ submission for Care Compare, for the page to add
up at any drilldown level and divide once.

What CMS checks, and where it comes from here:

- Hours by PBJ job title: each staffing role's hours mapped to its PBJ code
  (PBJ_CODES), split between the facility's employees and agency (contract)
  staff, as PBJ reports them, from daily_staffing_facts and daily_agency_facts.
- Hours per resident day, reported (not case-mix adjusted): total nurse staffing
  is RN (codes 5-7), LPN (8-9) and nurse aide (10-12) hours; RN staffing codes 5-7;
  each over the quarter's resident days, summed first. Weekend total nurse
  staffing is the same over Saturdays and Sundays only.
- Resident days: each day's closing census, from daily_facility_staffing_facts.
  CMS takes the census from MDS; this is the census the other reports use.
- Days without an RN: days with residents and no RN hours. Four or more in a
  quarter give a one-star staffing rating on Care Compare. Days with fewer than
  8 RN hours stand in for 42 CFR 483.35(b)(1), an RN 8 consecutive hours a day;
  daily totals cannot show whether the hours were consecutive.
- Turnover over the 12 months to the quarter's end, from the roster: the
  facility's own nurses (agency staff are not its employees) who left, over the
  average of their headcount at the start and end, for all nurse roles and RN
  roles, and the administrators who left. CMS counts a departure after 90 days
  with no hours worked; the roster's termination dates are taken as they are.

409 unless every day of the quarter is generated.
"""
from collections import defaultdict
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import Float, and_, func, or_, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_agency_facts as agency, daily_facility_staffing_facts as facility_days, daily_staffing_facts as staffing,
    staff_members as staff)
from shared.staffing import ROLE_CODES
from ..clinical.coverage import require_generated
from ..common.dates import DateRange
from ..common.locations import LocationSelection, facility_locations

GENERATORS = ('staffing_summary', 'facility_staffing_summary', 'agency_summary')
# Each role's PBJ job title code, for the roles PBJ's nurse staffing measures
# read, and the administrator. The other roles are reported under PBJ's other
# codes but are not in the staffing measures.
PBJ_CODES = {
    'administrator': 1,
    'mds_rn': 6, 'rn': 7,
    'lpn_supervisor': 8, 'adon_lpn': 8, 'lpn': 9, 'lpn_wound_nurse': 9,
    'cna': 10, 'ncna': 11, 'cma': 12,
}
RN_ROLES = ('rn', 'mds_rn')
NURSE_ROLES = tuple(code for code, pbj in PBJ_CODES.items() if 5 <= pbj <= 12)
# Fewer RN hours than this on a day with residents: short of 8 hours of RN cover.
RN_DAILY_HOURS = 8
TURNOVER_DAYS = 365


class FacilityPbj(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    days: int = Field(description='Days in the quarter with residents.')
    resident_days: int = Field(description='Closing census summed over the quarter.')
    weekend_resident_days: int = Field(description='Closing census summed over its Saturdays and Sundays.')
    roles: dict[str, list[float]] = Field(description="Each PBJ role's [hours, weekend hours, agency hours] over the "
        'quarter, by role code.')
    days_without_rn: int = Field(description='Days with residents and no RN hours.')
    days_under_8_rn: int = Field(description=f'Days with residents and fewer than {RN_DAILY_HOURS} RN hours.')
    turnover: list[int] = Field(description='Over the 12 months to the quarter\'s end, the facility\'s own '
        'employees: [nurse departures, nurse headcount at the start, at the end, RN departures, RN headcount at the '
        'start, at the end, administrator departures].')


class PbjReport(BaseModel):
    start_date: date
    end_date: date
    due_date: date = Field(description='The PBJ submission deadline for the quarter: the 45th day after it ends.')
    codes: dict[str, int] = Field(description="Each role's PBJ job title code.")
    items: list[FacilityPbj]


def report(connection: Connection, query: DateRange):
    start, end = query.start_date, query.end_date
    require_generated(connection, GENERATORS, start, end)
    weekend = func.extract('isodow', staffing.c.summary_date) >= 6
    roles: dict = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
    for facility_id, role, hours, weekend_hours in connection.execute(select(staffing.c.facility_id, staffing.c.role,
            func.sum(staffing.c.hours_worked).cast(Float), func.sum(staffing.c.hours_worked).filter(weekend).cast(Float))
            .where(staffing.c.summary_date.between(start, end), staffing.c.role.in_(tuple(PBJ_CODES)))
            .group_by(staffing.c.facility_id, staffing.c.role)):
        roles[facility_id][role][0] = round(hours or 0.0, 1)
        roles[facility_id][role][1] = round(weekend_hours or 0.0, 1)
    for facility_id, role, hours in connection.execute(select(agency.c.facility_id, agency.c.role,
            func.sum(agency.c.agency_hours).cast(Float))
            .where(agency.c.summary_date.between(start, end), agency.c.role.in_(tuple(PBJ_CODES)))
            .group_by(agency.c.facility_id, agency.c.role)):
        roles[facility_id][role][2] = round(hours or 0.0, 1)

    # Each day's RN hours against its census, per facility.
    rn_hours = (select(staffing.c.summary_date, staffing.c.facility_id, func.sum(staffing.c.hours_worked).label('hours'))
        .where(staffing.c.summary_date.between(start, end), staffing.c.role.in_(RN_ROLES))
        .group_by(staffing.c.summary_date, staffing.c.facility_id).subquery())
    rn = func.coalesce(rn_hours.c.hours, 0)
    occupied = facility_days.c.closing_census > 0
    census = {facility_id: values for facility_id, *values in connection.execute(select(facility_days.c.facility_id,
            func.count().filter(occupied), func.coalesce(func.sum(facility_days.c.closing_census), 0),
            func.coalesce(func.sum(facility_days.c.closing_census)
                .filter(func.extract('isodow', facility_days.c.summary_date) >= 6), 0),
            func.count().filter(occupied, rn == 0), func.count().filter(occupied, rn < RN_DAILY_HOURS))
        .select_from(facility_days.outerjoin(rn_hours, and_(rn_hours.c.summary_date == facility_days.c.summary_date,
            rn_hours.c.facility_id == facility_days.c.facility_id)))
        .where(facility_days.c.summary_date.between(start, end)).group_by(facility_days.c.facility_id))}

    # Turnover: the facility's own employees over the 12 months to the quarter's end.
    year_start = end - timedelta(days=TURNOVER_DAYS - 1)
    before = year_start - timedelta(days=1)

    def employed(day):
        return and_(staff.c.hire_date <= day, or_(staff.c.termination_date.is_(None), staff.c.termination_date > day))

    left = staff.c.termination_date.between(year_start, end)
    nurse = staff.c.role.in_(NURSE_ROLES)
    registered = staff.c.role.in_(RN_ROLES)
    turnover = {facility_id: [int(value or 0) for value in values] for facility_id, *values in connection.execute(
        select(staff.c.facility_id,
            func.count().filter(nurse, left), func.count().filter(nurse, employed(before)),
            func.count().filter(nurse, employed(end)),
            func.count().filter(registered, left), func.count().filter(registered, employed(before)),
            func.count().filter(registered, employed(end)),
            func.count().filter(staff.c.role == 'administrator', left))
        .where(staff.c.employment_type != 'agency', staff.c.hire_date <= end).group_by(staff.c.facility_id))}

    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        facility_id = location['facility_id']
        days, resident_days, weekend_days, without_rn, under_8 = census.get(facility_id, (0, 0, 0, 0, 0))
        items.append(dict(facility_id=str(facility_id), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            days=int(days), resident_days=int(resident_days), weekend_resident_days=int(weekend_days),
            roles={code: roles[facility_id][code] for code in PBJ_CODES if code in ROLE_CODES},
            days_without_rn=int(without_rn), days_under_8_rn=int(under_8),
            turnover=turnover.get(facility_id, [0] * 7)))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=start, end_date=end, due_date=end + timedelta(days=45), codes=PBJ_CODES, items=items)
