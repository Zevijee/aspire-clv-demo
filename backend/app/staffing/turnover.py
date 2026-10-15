"""Turnover and Retention: each facility's own employees between two dates, per
role, for the page to add up at any drilldown level and divide once.

Read from the roster (staff_members): each employee's hire date and, for those
who left, their termination date, the first day they no longer work. Someone is
employed on a day from their hire date up to the day before it. Agency staff are
left out: they are not the facility's employees, so neither their coming nor
their going is the facility's turnover.

Per facility and role, every count a sum:

- start headcount: employed on the day before the range, before any of its
  hires and departures
- end headcount: employed on its last day
- hires: hire dates in the range; departures: termination dates in it. So the
  end headcount is the start's plus the hires less the departures, whoever was
  hired and left inside it counted in both.
- retained: employed both before the range and on its last day
- 90-day eligible: hires whose 90th day fell in the range; 90-day retained: those
  of them still employed on it
- tenure days: the end headcount's days since hire, summed

The page divides: turnover is departures over the average of the start and end
headcount, scaled to a year; retention the retained over the start headcount;
90-day retention the 90-day retained over the eligible; average tenure the
tenure days over the end headcount.

The roster's dates are drawn ahead -- departures and replacements up to a year
past today -- so the range ends no later than the latest generated day: 409
past it. Answers come from one statement over the roster, about 170,000 rows.
"""
from collections import defaultdict
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Connection

from shared.database.schema import staff_members as staff
from shared.staffing import ROLE_CODES
from ..clinical.coverage import latest_day
from ..common.dates import DateRange
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from .ppd import ROLE_LIST, Role

# What each role's array holds, in order.
MEASURES = ('start_headcount', 'end_headcount', 'hires', 'departures', 'retained', 'eligible_90', 'retained_90',
    'tenure_days')
RETENTION_DAYS = 90


class FacilityTurnover(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    roles: dict[str, list[float]] = Field(description="Each role's counts by role code, in `measures` order.")


class TurnoverReport(BaseModel):
    start_date: date
    end_date: date
    days: int = Field(description='Days in the range: turnover is scaled from these to a year.')
    measures: list[str] = Field(description="The order of each role's array: the headcount before the range and on "
        'its last day, hires and departures in it, those employed both before and at the end, the hires whose 90th '
        'day fell in the range and those of them still employed on it, and the end headcount\'s days since hire.')
    roles: list[Role] = Field(description='Every role, in report order, with its department.')
    items: list[FacilityTurnover]


def report(connection: Connection, query: DateRange):
    start, end = query.start_date, query.end_date
    latest = latest_day(connection)
    if latest is None or end > latest:
        raise ApiError('summary_unavailable', f'Turnover is available through {latest}. The requested period '
            'includes days not generated yet. Run the seeder update or select completed dates.', 409)

    def employed(day):
        """Employed on the day: hired by it, and not yet gone."""
        return and_(staff.c.hire_date <= day, or_(staff.c.termination_date.is_(None), staff.c.termination_date > day))

    before = start - timedelta(days=1)
    ninetieth = staff.c.hire_date + RETENTION_DAYS
    counted = {
        'start_headcount': employed(before),
        'end_headcount': employed(end),
        'hires': staff.c.hire_date.between(start, end),
        'departures': staff.c.termination_date.between(start, end),
        'retained': and_(employed(before), employed(end)),
        'eligible_90': ninetieth.between(start, end),
        'retained_90': and_(ninetieth.between(start, end),
            or_(staff.c.termination_date.is_(None), staff.c.termination_date > ninetieth)),
    }
    columns = [func.count().filter(condition) for condition in counted.values()]
    columns.append(func.coalesce(func.sum(end - staff.c.hire_date).filter(employed(end)), 0))
    sums: dict = defaultdict(dict)
    for facility_id, role, *values in connection.execute(select(staff.c.facility_id, staff.c.role, *columns)
            # Nobody hired after the range counts; a leaver of any date might, as
            # a 90-day hire who left before the range began.
            .where(staff.c.employment_type != 'agency', staff.c.hire_date <= end)
            .group_by(staff.c.facility_id, staff.c.role)):
        sums[facility_id][role] = [float(value or 0) for value in values]

    empty = [0.0] * len(MEASURES)
    items = [dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            roles={code: sums.get(location['facility_id'], {}).get(code, empty) for code in ROLE_CODES})
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=start, end_date=end, days=query.days, measures=list(MEASURES), roles=ROLE_LIST, items=items)
