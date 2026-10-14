"""Each facility, role and day's new hires, the paid orientation they took and
the sign-on bonuses paid them. One row per facility, role and day with a hire,
for the whole history, for the Staffing Overview report.

Run: python manage.py onboarding_summary --regenerate
Also rebuilt by every seed and update, after the staffing facts.

Drawn straight from daily_staffing_facts, as the agency and overtime facts are:
there is no HR source, and the roster (staff_members) is built once with no
hires after it, so it cannot say who joined last month. A role's people are its
hours over a 40-hour week, and each year a share of them leave and are
replaced -- that role's turnover, moved by a facility habit:

    expected hires today = hours / 40 x 7 x turnover x habit / 365
    hires                = floor(expected + draw)        (expected < 1 a day)

The floor of the expectation plus a draw in [0, 1) is a hire with exactly the
expected probability, so hires over a year come to the role's turnover.

Each hire is paid their role's orientation (ROLE_RULES) at the day's in-house
rate (the facts' wages over hours), in two kinds: classroom hours -- policies,
compliance, infection control, the systems -- and floor hours, shadowing a
preceptor on the unit. Only Direct Care hires take it: the other departments'
hires are hired, and paid their sign-on bonus, with no orientation. A hire also earns their role's sign-on bonus, scaled by
the facility's bonus habit: some facilities pay none. Orientation is paid
time, not care, so it is never added to the facts' hours worked. A hire's
orientation and its pay are booked on the hire date, as one cohort.

How long each hire takes to finish, in calendar days from the hire date:

    classroom = the wait for the next class (0 to the facility's cadence, up
                to 6 days) + the 8-hour sessions, on weekdays only
    floor     = the 8-hour shifts beside a preceptor, at the facility's pace
                of 3 to 5 shifts a week, + 0 to 2 days lost to scheduling

and floor follows classroom, so a hire is signed off after both.
Every draw is an md5 of the facility, role and day, so a rebuild writes the
same rows.
"""
from datetime import timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from shared.staffing import ROLE_CODES
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw as _draw


def draw(seed):
    """A stable draw as a double, as the agency facts draw."""
    return f'({_draw(seed)})::float8'


# Per role: (yearly turnover, paid classroom orientation hours per hire, paid floor
# orientation hours per hire, sign-on bonus per hire in dollars). Turnover is the
# share of a role's people replaced in a year; nursing aides turn over most. Only
# Direct Care orients: every other role's orientation is zero.
ROLE_RULES = {
    'administrator': (0.20, 0, 0, 5000),
    'business_office_manager': (0.25, 0, 0, 1000),
    'hr_payroll': (0.25, 0, 0, 500),
    'rn': (0.45, 40, 60, 3000),
    'lpn': (0.45, 40, 60, 2000),
    'lpn_supervisor': (0.35, 40, 60, 2000),
    'lpn_wound_nurse': (0.30, 40, 60, 2000),
    'cna': (0.60, 24, 40, 750),
    'ncna': (0.70, 24, 40, 0),
    'cma': (0.50, 24, 40, 750),
    'cook': (0.45, 0, 0, 250),
    'dietary_aide': (0.55, 0, 0, 0),
    'dietary_manager': (0.30, 0, 0, 1000),
    'dietician': (0.25, 0, 0, 1500),
    'housekeeper': (0.55, 0, 0, 0),
    'housekeeping_director': (0.30, 0, 0, 500),
    'laundry_aide': (0.55, 0, 0, 0),
    'maintenance_director': (0.25, 0, 0, 1000),
    'social_services_director': (0.30, 0, 0, 1000),
    'transportation_driver': (0.45, 0, 0, 0),
    'adon_lpn': (0.35, 0, 0, 3000),
    'mds_rn': (0.30, 0, 0, 3000),
    'staffing_coordinator': (0.40, 0, 0, 500),
}
# Every role in shared/staffing.py has rules, and no other.
assert set(ROLE_RULES) == set(ROLE_CODES), 'ROLE_RULES must cover shared/staffing.py ROLE_CODES exactly'
# Orientation is taught in 8-hour classroom sessions and worked in 8-hour floor shifts.
SESSION_HOURS = 8
# A facility runs a class every 1 to 7 days, so a hire waits 0 to 6 for the next.
CLASS_CADENCE_DAYS = 7
# The floor shifts a facility's preceptors can take a hire on, a week: 3 to 5.
FLOOR_SHIFTS_A_WEEK = (3, 2)
# Days a hire loses between floor shifts to scheduling, 0 to 2.
FLOOR_DELAY_DAYS = 3
# A facility and role's turnover against the role's: 0.5 to 1.5 times it.
TURNOVER_HABIT = (0.5, 1.0)
# The share of facility and role pairs that pay no sign-on bonus at all; the
# rest pay 0.5 to 1.5 times the role's.
NO_BONUS_SHARE = 0.35

ROLE = "f.facility_id::text || ':' || f.role"
DAY = ROLE + " || ':' || f.summary_date::text"
RULES = ', '.join(f"('{code}', {turnover}, {classroom}, {floor}, {bonus})"
    for code, (turnover, classroom, floor, bonus) in ROLE_RULES.items())

# Only trusted temporary-table identifiers are interpolated; values stay bound.
ONBOARDING_SQL = f"""
WITH rules (role, turnover, classroom_hours, floor_hours, sign_on) AS (VALUES {RULES}),
facts AS (
    SELECT f.summary_date, f.facility_id, f.role, f.hours_worked, f.wages / f.hours_worked AS rate
    FROM daily_staffing_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    WHERE f.hours_worked > 0
),
-- Each facility and role's habits, drawn once for its pairs. Materialized, as
-- the agency habits are, so the draw is not repeated on every row.
habits AS MATERIALIZED (
    SELECT f.facility_id, f.role,
        {TURNOVER_HABIT[0]} + {TURNOVER_HABIT[1]} * {draw("'turnover-habit:' || " + ROLE)} AS turnover_habit,
        CASE WHEN {draw("'bonus-habit:' || " + ROLE)} < {NO_BONUS_SHARE} THEN 0
            ELSE 0.5 + {draw("'bonus-size:' || " + ROLE)} END AS bonus_habit,
        floor({CLASS_CADENCE_DAYS} * {draw("'class-cadence:' || f.facility_id::text")})::int AS class_wait,
        {FLOOR_SHIFTS_A_WEEK[0]} + {FLOOR_SHIFTS_A_WEEK[1]} * {draw("'floor-pace:' || f.facility_id::text")} AS floor_pace
    FROM (SELECT DISTINCT facility_id, role FROM facts) f
),
hires AS (
    SELECT f.summary_date, f.facility_id, f.role, f.rate, r.classroom_hours, r.floor_hours, r.sign_on, h.bonus_habit,
        -- The weekday sessions run across weekends: N sessions span N days and two more per full week.
        CASE WHEN r.classroom_hours > 0 THEN
            floor((h.class_wait + 1) * {draw("'class-wait:' || " + DAY)})::int
            + ceil(r.classroom_hours / {SESSION_HOURS}.0)::int
            + 2 * floor((ceil(r.classroom_hours / {SESSION_HOURS}.0) - 1) / 5)::int ELSE 0 END AS classroom_days,
        CASE WHEN r.floor_hours > 0 THEN
            ceil(ceil(r.floor_hours / {SESSION_HOURS}.0) * 7 / h.floor_pace)::int
            + floor({FLOOR_DELAY_DAYS} * {draw("'floor-delay:' || " + DAY)})::int ELSE 0 END AS floor_days,
        floor(f.hours_worked / 40.0 * 7 * r.turnover * h.turnover_habit / 365
            + {draw("'hire:' || " + DAY)})::int AS new_hires
    FROM facts f
    JOIN habits h ON h.facility_id = f.facility_id AND h.role = f.role
    JOIN rules r ON r.role = f.role
)
INSERT INTO __STAGE__ (summary_date, facility_id, role, new_hires, bonuses,
    classroom_orientation_hours, classroom_orientation_wages, floor_orientation_hours, floor_orientation_wages,
    classroom_orientation_days, floor_orientation_days)
SELECT summary_date, facility_id, role, new_hires,
    round((new_hires * sign_on * bonus_habit)::numeric, 2),
    new_hires * classroom_hours,
    round((new_hires * classroom_hours * rate)::numeric, 2),
    new_hires * floor_hours,
    round((new_hires * floor_hours * rate)::numeric, 2),
    new_hires * classroom_days,
    new_hires * floor_days
FROM hires
WHERE new_hires > 0
"""


class OnboardingSummaryGenerator(BaseGenerator):
    name = 'onboarding_summary'
    table = schema.daily_onboarding_facts
    depends_on = ('staffing_summary',)
    transaction_isolation = 'REPEATABLE READ'

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        self._end = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'staffing_summary'))
        if self._end is None:
            raise ValueError('Daily staffing facts are missing. Run staffing_summary first.')
        self._start = self.SIMULATION_START

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Onboarding facts are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        days = sorted(set(days))
        if not days:
            return GenerationResult(0, 0), {}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(days):,} dates')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _onboarding_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=days))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _onboarding_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _onboarding_dates')
        if self.progress:
            self.progress.set_phase('Draw each facility, role and day\'s hires', details=f'{len(days):,} dates')
        stage = self.create_stage(connection, self.table)
        statement = ONBOARDING_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_onboarding_dates')
        generated = connection.exec_driver_sql(statement).rowcount
        per_day = {day: 0 for day in days}
        for day, count in connection.exec_driver_sql(sql.SQL(
                'SELECT summary_date, COUNT(*) FROM {} GROUP BY summary_date')
                .format(sql.Identifier(stage)).as_string(driver)).all():
            per_day[day] = count
        if self.progress:
            self.progress.set_phase('Remove previous rows', details=f'{len(days):,} selected dates')
        if replace_all:
            removed = connection.execute(self.table.delete()).rowcount
        else:
            removed = connection.exec_driver_sql('''
                DELETE FROM daily_onboarding_facts f USING _onboarding_dates d WHERE f.summary_date = d.summary_date
            ''').rowcount
        suspended = None
        if replace_all or self.replaces_most_rows(connection, self.table, generated):
            suspended = self.suspend_indexes(connection, self.table)
        columns = sql.SQL(', ').join(map(sql.Identifier, self.table.c.keys()))
        if self.progress:
            self.progress.set_phase('Insert rows', details=f'{generated:,} rows')
        # In date order, so a range reads its own days' pages: stored in rebuild
        # order, 30 days of agency facts read 166,850 pages, 1.1 s cold; in date order 2,736.
        inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {} ORDER BY 1, 2')
            .format(self._table_identifier(self.table), columns, columns, sql.Identifier(stage))
            .as_string(driver)).rowcount
        if inserted != generated:
            raise ValueError('Published row count did not match staging.')
        if suspended is not None:
            self.restore_indexes(connection, self.table, suspended)
        for temporary in (stage, '_onboarding_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        days = [self._start + timedelta(days=offset) for offset in range((self._end - self._start).days + 1)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (OnboardingSummaryGenerator,)


class DailyOnboardingSummary(DailyGenerator):
    name = 'onboarding_summary'
    table = schema.daily_onboarding_facts
    owned_tables = (table,)
    depends_on = ('staffing_summary',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = OnboardingSummaryGenerator(self.database_url)
        self._summary.progress = self.progress

    def run_dates(self, connection, days):
        _, counts = self._summary.write_dates(connection, days)
        return {day: {self.table.name: counts[day]} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyOnboardingSummary,)
