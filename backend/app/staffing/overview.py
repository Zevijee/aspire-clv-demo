"""Staffing Overview: each facility's hours and labour cost in a date range,
per role, for the page to add up at any drilldown level, for every role or a
chosen few, and divide once. The PPD report reads the same response.

Every measure is a sum. A period reads its whole calendar months from
monthly_staffing_cost_facts and only its edge days from the daily tables it
rolls up (rollup_plan): a year read three 7.7M-row tables, 5.8 s in the
service. The daily sources, and what each measure means:

- census days, from daily_facility_staffing_facts' closing census, once per
  facility and never per role, so any set of roles divides by the same days
- hours worked, target hours, excess hours, wages and excess wages, from
  daily_staffing_facts. Wages are straight time at the day's in-house rate,
  agency hours included at that rate.
- overtime hours and their straight-time pay, from daily_overtime_facts
- holiday hours and their pay: the hours on shared/holidays.py's days that
  were not overtime, from the same rows. An overtime hour on a holiday earns
  the overtime premium only, never both.
- agency and in-house hours and pay, from daily_agency_facts, and the agency
  premium priced from them as Agency vs In-house prices it (agency.agency_premium)
- new hires, bonuses, and orientation hours and pay in its two kinds,
  classroom and floor, with the days each hire took to finish each, from
  daily_onboarding_facts. Orientation is paid time, not care: it is in total
  hours and cost, never in hours worked or HPPD.
- in-service training hours and pay, from daily_training_facts: paid time,
  not care, like orientation.

The response is compact: each role's measures as an array in `measures` order,
not 15 named fields 5,566 times (2 MB). Completeness comes from the seeder's
checkpoints: a range with a day any source lacks is a 409.
"""
from collections import defaultdict
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy import Float, Numeric, func, select
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_agency_facts as agency_facts, daily_facility_staffing_facts as facility_days,
    daily_onboarding_facts as onboarding, daily_overtime_facts as overtime_facts, daily_runs,
    daily_staffing_facts as staffing, daily_training_facts as training, monthly_staffing_cost_facts as months)
from shared.holidays import holidays
from shared.staffing import ROLE_CODES
from ..clinical.coverage import require_generated
from ..common.dates import DateRange, rollup_plan
from ..common.locations import LocationSelection, facility_locations
from .agency import agency_premium, roster_rates
from .premiums import HOLIDAY_PREMIUM, OVERTIME_PREMIUM
from .ppd import ROLE_LIST, Role

GENERATORS = ('staffing_summary', 'facility_staffing_summary', 'overtime_summary', 'agency_summary',
    'onboarding_summary', 'training_summary', 'staffing_cost_summary')
# The measures each role's array holds, in order.
MEASURES = ('hours', 'target_hours', 'excess_hours', 'wages', 'excess_wages',
    'overtime_hours', 'overtime_wages', 'holiday_hours', 'holiday_wages', 'agency_hours', 'agency_premium',
    'new_hires', 'bonuses', 'agency_wages', 'inhouse_hours', 'training_hours', 'training_wages',
    'classroom_orientation_hours', 'classroom_orientation_wages', 'floor_orientation_hours', 'floor_orientation_wages',
    'classroom_orientation_days', 'floor_orientation_days')
# What is summed before the agency premium is priced from it.
SUMMED = ('hours', 'target_hours', 'excess_hours', 'wages', 'excess_wages', 'overtime_hours', 'overtime_wages',
    'holiday_hours', 'holiday_wages', 'agency_hours', 'agency_wages', 'inhouse_hours', 'inhouse_wages',
    'new_hires', 'bonuses', 'training_hours', 'training_wages', 'classroom_orientation_hours',
    'classroom_orientation_wages', 'floor_orientation_hours', 'floor_orientation_wages', 'classroom_orientation_days',
    'floor_orientation_days')


class FacilityOverview(BaseModel):
    facility_id: str
    facility_name: str
    state: str
    portfolio: str
    region: str
    census_days: int = Field(description='Closing census summed over the range, once per facility: HPPD for '
        'any set of roles is their hours over these days.')
    roles: dict[str, list[float]] = Field(description="Each role's measures by role code, in `measures` order.")


class OverviewReport(BaseModel):
    start_date: date
    end_date: date
    days: int = Field(description='Days in the range: average daily census is census days over this.')
    holidays: list[date] = Field(description='The paid holidays in the range.')
    overtime_premium: float = Field(description='What an overtime hour pays over straight time, as a share of its pay.')
    holiday_premium: float = Field(description='What a holiday hour pays over straight time, as a share of its pay.')
    measures: list[str] = Field(description="The order of each role's array: hours worked, target hours, excess "
        'hours, straight-time wages, excess wages, overtime hours and pay, holiday hours and pay, agency hours, '
        'the agency premium, new hires, bonuses, agency pay, in-house hours, in-service training hours and pay, '
        'classroom and floor orientation hours and pay, and the days hires took to finish each, summed over the '
        'hires: their average is these over new hires.')
    roles: list[Role] = Field(description='Every role, in report order, with its department.')
    items: list[FacilityOverview]


def report(connection: Connection, query: DateRange):
    start, end = query.start_date, query.end_date
    require_generated(connection, GENERATORS, start, end)
    sums: dict = defaultdict(lambda: defaultdict(lambda: dict.fromkeys(SUMMED, 0.0)))

    def add(statement, names, sign=1):
        for facility_id, role, *values in connection.execute(statement):
            target = sums[facility_id][role]
            for name, value in zip(names, values):
                target[name] += sign * float(value or 0)

    # Sums as doubles: 6,000 rows of decimals per statement took longer to
    # convert than the statements took to run.
    def grouped(source, columns, *conditions):
        return (select(source.c.facility_id, source.c.role, *(func.sum(column, type_=Numeric).cast(Float) for _, column in columns))
            .where(*conditions).group_by(source.c.facility_id, source.c.role)), [name for name, _ in columns]

    # Whole months from the rollup, and the days to add or take away from the daily facts.
    through = connection.scalar(select(func.max(daily_runs.c.simulation_date))
        .where(daily_runs.c.generator == 'staffing_cost_summary'))
    whole, edges = rollup_plan(start, end, through)
    if whole:
        add(*grouped(months, [(name, months.c[column]) for name, column in (('hours', 'hours_worked'),
            *((name, name) for name in SUMMED if name != 'hours'))], months.c.month_start.between(*whole)))
    for sign, first, last in edges:
        add(*grouped(staffing, [(name, staffing.c[column]) for name, column in (('hours', 'hours_worked'),
            ('target_hours', 'target_hours'), ('excess_hours', 'excess_hours'), ('wages', 'wages'),
            ('excess_wages', 'excess_wages'))], staffing.c.summary_date.between(first, last)), sign)
        add(*grouped(overtime_facts, [('overtime_hours', overtime_facts.c.overtime_hours),
            ('overtime_wages', overtime_facts.c.overtime_wages)], overtime_facts.c.summary_date.between(first, last)), sign)
        days_off = holidays(first, last)
        if days_off:
            add(*grouped(overtime_facts, [('holiday_hours', overtime_facts.c.hours_worked - overtime_facts.c.overtime_hours),
                ('holiday_wages', overtime_facts.c.wages - overtime_facts.c.overtime_wages)],
                overtime_facts.c.summary_date.in_(days_off)), sign)
        add(*grouped(agency_facts, [(name, agency_facts.c[name]) for name in
            ('agency_hours', 'agency_wages', 'inhouse_hours', 'inhouse_wages')],
            agency_facts.c.summary_date.between(first, last)), sign)
        add(*grouped(onboarding, [(name, onboarding.c[name]) for name in
            ('new_hires', 'bonuses', 'classroom_orientation_hours', 'classroom_orientation_wages',
                'floor_orientation_hours', 'floor_orientation_wages', 'classroom_orientation_days',
                'floor_orientation_days')],
            onboarding.c.summary_date.between(first, last)), sign)
        add(*grouped(training, [(name, training.c[name]) for name in ('training_hours', 'training_wages')],
            training.c.summary_date.between(first, last)), sign)
    census_days = dict(connection.execute(select(facility_days.c.facility_id, func.sum(facility_days.c.closing_census))
        .where(facility_days.c.summary_date.between(start, end)).group_by(facility_days.c.facility_id)).all())

    rates = roster_rates(connection)
    empty = [0.0] * len(MEASURES)
    items = []
    for location in connection.execute(facility_locations(LocationSelection())).mappings():
        facility_id = location['facility_id']
        roles = {}
        for code in ROLE_CODES:
            values = sums.get(facility_id, {}).get(code)
            if values is None:
                roles[code] = empty
                continue
            values = dict(values, agency_premium=agency_premium(values, rates.get((facility_id, code), 0.0)))
            roles[code] = [round(values[name], 2) for name in MEASURES]
        items.append(dict(facility_id=str(facility_id), facility_name=location['facility_name'],
            state=location['state'], portfolio=location['portfolio_name'], region=location['region_name'],
            census_days=int(census_days.get(facility_id, 0) or 0), roles=roles))
    items.sort(key=lambda item: (item['state'], item['portfolio'], item['region'], item['facility_name']))
    return dict(start_date=start, end_date=end, days=query.days, holidays=holidays(start, end),
        overtime_premium=OVERTIME_PREMIUM, holiday_premium=HOLIDAY_PREMIUM, measures=list(MEASURES),
        roles=ROLE_LIST, items=items)
