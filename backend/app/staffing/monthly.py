"""Monthly Staffing Trending: each facility's hours, labour cost and premiums by
calendar month, with its census days, for the page to add up at any drilldown
level and divide once, month by month.

Everything is read from monthly rollups. Hours, pay and premiums come from
monthly_staffing_cost_facts, which holds every month whole and the month in
progress to its latest day, summed over the roles asked for (all when none).
Census days come from monthly_payer_census_facts, once per facility, summed over
payers: each day's closing census, the days the Staffing Overview divides by --
verified equal to summing daily_facility_staffing_facts by month for all 8,602
facility-months from January 2024, and a seventh of its time (16 ms against 87).

Turnover comes from the roster (staff_members), the facilities' own employees
as Turnover and Retention counts them, agency staff left out: each month's
headcount at its start and end, its hires and departures, and those employed
at its start still there at its end.

Labour cost is the PPD cost report's (laborCost on the page): straight-time
wages, the agency premium, time-and-a-half's half on overtime and holiday pay,
orientation and training pay, and bonuses. The agency premium is priced per
facility, role and month as agency.agency_premium prices it -- the month's agency
hours at its agency pay less the same hours at its in-house rate, or the
roster's where nobody in-house worked -- so a month's cost is what the PPD cost
report shows for that month.

The response is compact: each facility's measures as arrays aligned to `months`,
in `measures` order, not a dict per measure keyed by month (1.4 MB for 33
months, against half that). Every month carries how many of its days are
covered. Completeness comes from the generators' checkpoints: 409 if any day in
the range is missing. Absence of a row means zero.

Answers are kept in the process for the last CACHE_SIZE ranges and role picks,
as the Employees tab keeps its rows (employees._rows), until a generator they
read from records a run: building one reads 190,000 rollup rows and takes about
0.4 s, the same months again a few milliseconds.
"""
from calendar import monthrange
from collections import OrderedDict, defaultdict
from datetime import date, timedelta
import threading

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Float, and_, case, func, or_, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_runs, monthly_payer_census_facts as census_months, monthly_staffing_cost_facts as months, run_history,
    staff_members as staff)
from shared.staffing import ROLE_CODES
from ..clinical.coverage import require_generated
from ..common.errors import ApiError
from ..common.locations import LocationSelection, facility_locations
from .premiums import HOLIDAY_PREMIUM, OVERTIME_PREMIUM

MONTH = r'^\d{4}-(0[1-9]|1[0-2])$'
GENERATORS = ('staffing_summary', 'facility_staffing_summary', 'staffing_cost_summary', 'monthly_adt_summary')
# What the answer is read from: the rollups, and the roster for agency hours'
# in-house rate. A run of any of them makes a kept answer stale.
SOURCES = (*GENERATORS, 'staff_members')
CACHE_SIZE = 8
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()
# Each facility's arrays, in order: census days, then the sums of the rollup.
MEASURES = ('census_days', 'hours', 'target_hours', 'cost', 'agency_hours', 'overtime_hours', 'excess_wages',
    'agency_premium', 'overtime_premium', 'bonuses', 'new_hires', 'headcount_start', 'headcount_end', 'hires',
    'departures', 'retained')
# Where the roster's turnover counts sit in each facility's arrays.
TURNOVER_AT = MEASURES.index('headcount_start')


class MonthlyQuery(BaseModel):
    start_month: str = Field(pattern=MONTH, description='First month, YYYY-MM.')
    end_month: str = Field(pattern=MONTH, description='Last month, YYYY-MM, inclusive.')
    roles: list[str] = Field(default_factory=list, max_length=len(ROLE_CODES),
        description='Role codes to add up; none is every role.')

    @model_validator(mode='after')
    def ordered(self):
        if self.start_month > self.end_month:
            raise ValueError('The first month must not be after the last.')
        if self.months > 120:
            raise ValueError('Choose at most 120 months.')
        unknown = set(self.roles) - set(ROLE_CODES)
        if unknown:
            raise ValueError(f'Unknown roles: {", ".join(sorted(unknown))}.')
        return self

    @property
    def first_day(self):
        return date.fromisoformat(f'{self.start_month}-01')

    @property
    def last_day(self):
        year, month = map(int, self.end_month.split('-'))
        return date(year, month, monthrange(year, month)[1])

    @property
    def months(self):
        (start_year, start), (end_year, end) = (map(int, value.split('-'))
            for value in (self.start_month, self.end_month))
        return (end_year - start_year) * 12 + end - start + 1


class Month(BaseModel):
    month: str = Field(description='YYYY-MM.')
    days: int = Field(description='Days of the month in the range: every day, except in the month in progress.')
    month_days: int = Field(description='Days in the calendar month.')


class FacilityMonths(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    values: list[list[float]] = Field(description="One array per measure, in `measures` order, each a value per "
        "month in `months` order, over the roles asked for: census days, the month's closing census summed, once per "
        "facility; hours worked; budget hours, each day's target HPPD times its census; labour cost, as the PPD cost "
        "report counts it; agency hours; overtime hours, those over 40 in an employee's week; overbudget excess "
        "spend, the hours over each day's budget at straight time; the agency premium, priced as the cost is; and "
        'the overtime premium, what overtime paid over straight time; sign-on bonuses, and the new hires they were '
        "paid to; and the facility's own employees: headcount at the month's start and end, hires, departures, and "
        'those employed at its start still there at its end.')


class MonthlyStaffing(BaseModel):
    start: date
    end: date = Field(description='The last day read: the end of the last month, or the latest generated day.')
    months: list[Month]
    measures: list[str] = Field(description="The order of each facility's `values`.")
    items: list[FacilityMonths]


def data_stamp(connection: Connection):
    """When the sources last changed: the latest day any of them wrote, or the
    latest whole rebuild."""
    days = select(func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator.in_(SOURCES)).scalar_subquery()
    runs = select(func.max(run_history.c.completed_at)).where(run_history.c.name.in_(SOURCES)).scalar_subquery()
    return connection.execute(select(days, runs)).one()


def monthly(connection: Connection, query: MonthlyQuery):
    """The months' answer, from the kept ones while the data has not changed."""
    key = (query.start_month, query.end_month, tuple(sorted(query.roles)), tuple(data_stamp(connection)))
    with _lock:
        answer = _cache.get(key)
        if answer is not None:
            _cache.move_to_end(key)
            return answer
    answer = _build(connection, query)
    with _lock:
        _cache[key] = answer
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return answer


def _turnover(connection: Connection, values: dict, roles: list[str], start: date, end: date, position: dict):
    """Each facility's own employees month by month, into its arrays: the
    headcount the day before the range, then each month's hires and departures
    carry it on. A departure in the month of its hire was never there at the
    month's start, so it is not one of those the month failed to retain."""
    own = and_(staff.c.employment_type != 'agency', staff.c.role.in_(roles))
    before = start - timedelta(days=1)
    headcount = dict(connection.execute(select(staff.c.facility_id, func.count())
        .where(own, staff.c.hire_date <= before,
            or_(staff.c.termination_date.is_(None), staff.c.termination_date > before))
        .group_by(staff.c.facility_id)).all())
    hires: dict = defaultdict(dict)
    for facility_id, month, count in connection.execute(select(staff.c.facility_id,
            func.to_char(staff.c.hire_date, 'YYYY-MM').label('month'), func.count())
            .where(own, staff.c.hire_date.between(start, end)).group_by(staff.c.facility_id, 'month')):
        hires[facility_id][month] = count
    departures: dict = defaultdict(dict)
    for facility_id, month, count, new in connection.execute(select(staff.c.facility_id,
            func.to_char(staff.c.termination_date, 'YYYY-MM').label('month'), func.count(),
            func.count().filter(func.date_trunc('month', staff.c.hire_date)
                == func.date_trunc('month', staff.c.termination_date)))
            .where(own, staff.c.termination_date.between(start, end)).group_by(staff.c.facility_id, 'month')):
        departures[facility_id][month] = (count, new)
    for facility_id in set(headcount) | set(hires) | set(departures):
        arrays = values[facility_id]
        current = float(headcount.get(facility_id, 0))
        for month, at in sorted(position.items(), key=lambda entry: entry[1]):
            hired = hires[facility_id].get(month, 0)
            left, left_new = departures[facility_id].get(month, (0, 0))
            arrays[TURNOVER_AT][at] = current
            arrays[TURNOVER_AT + 1][at] = current + hired - left
            arrays[TURNOVER_AT + 2][at] = float(hired)
            arrays[TURNOVER_AT + 3][at] = float(left)
            arrays[TURNOVER_AT + 4][at] = current - (left - left_new)
            current += hired - left


def warm(database) -> None:
    """Build the page's default months -- the 36 before this one, every role --
    ahead of the first request, if the data has changed since; otherwise only
    the stamp is read. As the page's month picker defaults (getReportMonthRange)."""
    today = date.today()
    end = today.replace(day=1) - timedelta(days=1)
    index = end.year * 12 + end.month - 1 - 35
    first = date(index // 12, index % 12 + 1, 1)
    with database.connection() as connection:
        monthly(connection, MonthlyQuery(start_month=first.strftime('%Y-%m'), end_month=end.strftime('%Y-%m')))


def _build(connection: Connection, query: MonthlyQuery):
    latest = connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == 'staffing_cost_summary'))
    start, end = query.first_day, query.last_day
    if latest is not None:
        end = min(end, latest)
    if latest is None or end < start:
        raise ApiError('summary_unavailable', 'Monthly staffing is not generated for these months yet. '
            'Run the seeder update or select completed months.', 409)
    require_generated(connection, GENERATORS, start, end)

    listed, cursor = [], start
    while cursor <= end:
        month_days = monthrange(cursor.year, cursor.month)[1]
        month_end = min(cursor.replace(day=month_days), end)
        listed.append(dict(month=cursor.strftime('%Y-%m'), days=(month_end - cursor).days + 1, month_days=month_days))
        cursor = cursor.replace(day=month_days) + timedelta(days=1)
    position = {entry['month']: index for index, entry in enumerate(listed)}
    values: dict = defaultdict(lambda: [[0.0] * len(listed) for _ in MEASURES])

    roles = query.roles or list(ROLE_CODES)
    # Each facility and role's in-house roster rate, for agency hours where nobody
    # in-house worked the month (agency.roster_rates).
    roster = (select(staff.c.facility_id, staff.c.role, func.avg(staff.c.hourly_rate).label('rate'))
        .where(staff.c.employment_type != 'agency').group_by(staff.c.facility_id, staff.c.role).subquery())
    # In doubles from the start: the eight sums in numeric arithmetic took 0.34 s
    # for 33 months, in doubles a fraction of it, and every figure is rounded to
    # the cent or the tenth after.
    column = {name: months.c[name].cast(Float) for name in ('hours_worked', 'target_hours', 'wages', 'agency_wages',
        'agency_hours', 'inhouse_wages', 'inhouse_hours', 'overtime_wages', 'holiday_wages', 'overtime_hours',
        'classroom_orientation_wages', 'floor_orientation_wages', 'training_wages', 'bonuses', 'excess_wages',
        'new_hires')}
    inhouse_rate = case((column['inhouse_hours'] > 0, column['inhouse_wages'] / column['inhouse_hours']),
        else_=func.coalesce(roster.c.rate.cast(Float), 0.0))
    premium_of_row = column['agency_wages'] - column['agency_hours'] * inhouse_rate
    cost_of_row = (column['wages'] + premium_of_row
        + column['overtime_wages'] * OVERTIME_PREMIUM + column['holiday_wages'] * HOLIDAY_PREMIUM
        + column['classroom_orientation_wages'] + column['floor_orientation_wages'] + column['training_wages']
        + column['bonuses'])
    summed = (column['hours_worked'], column['target_hours'], cost_of_row, column['agency_hours'],
        column['overtime_hours'], column['excess_wages'], premium_of_row, column['overtime_wages'] * OVERTIME_PREMIUM,
        column['bonuses'], column['new_hires'])
    for facility_id, month, *sums in connection.execute(select(months.c.facility_id,
            func.to_char(months.c.month_start, 'YYYY-MM'),
            *(func.sum(value, type_=Float) for value in summed))
            .select_from(months.outerjoin(roster, (roster.c.facility_id == months.c.facility_id)
                & (roster.c.role == months.c.role)))
            .where(months.c.month_start.between(start, end), months.c.role.in_(roles))
            .group_by(months.c.facility_id, months.c.month_start)):
        at = position[month]
        for index, value in enumerate(sums, start=1):
            values[facility_id][index][at] = round(value or 0.0, 2)
    for facility_id, month, days in connection.execute(select(census_months.c.facility_id,
            func.to_char(census_months.c.month_start, 'YYYY-MM'), func.sum(census_months.c.census_days))
            .where(census_months.c.month_start.between(start, end))
            .group_by(census_months.c.facility_id, census_months.c.month_start)):
        if month in position:
            values[facility_id][0][position[month]] = float(days or 0)

    _turnover(connection, values, roles, start, end, position)
    items = [dict(facility_id=str(location['facility_id']), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            values=values[location['facility_id']])
        for location in connection.execute(facility_locations(LocationSelection())).mappings()]
    return dict(start=start, end=end, months=listed, measures=list(MEASURES),
        items=sorted(items, key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name'])))
