"""The bonuses each employee was paid: one row per bonus, for the Staffing
Overview's Employees tab.

Run: python manage.py staff_bonuses --regenerate
Also kept up by every update, after the staff hours.

Three kinds, as skilled nursing facilities pay them:

    pickup            a shift an employee picked up, beyond their schedule, at a
                      facility with a pickup program: a stable PICKUP share of
                      each role's shifts, at the role's pickup amount
    retention_90_day  ninety days after the hire date, at a facility with a
                      retention program, to someone still employed then
    anniversary       on each anniversary of the hire date, at a facility with a
                      retention program

A facility runs each program or not by a draw on its id: PICKUP_PROGRAM_SHARE
and RETENTION_PROGRAM_SHARE of facilities do. Agency employees are not the
facility's own and earn none. The pickups are drawn from daily_staff_hours,
never from its overtime, which a later day of the same week can move; the
retention bonuses from the roster's hire dates. Rows are kept for the same days
as daily_staff_hours (STAFF_HOURS_DAYS); older days are dropped. Every draw is an
md5 of the employee and day, so a rebuild writes the same rows.

These are not the sign-on bonuses of daily_onboarding_facts, which the Staffing
Overview counts per facility and role from its hires: the roster is built once,
so it cannot say who those hires were.
"""
from datetime import timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from shared.staffing import ROLE_CODES, STAFF_HOURS_DAYS
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw as _draw


def draw(seed):
    """A stable draw as a double, as the onboarding facts draw."""
    return f'({_draw(seed)})::float8'


# Per role: (share of shifts picked up, pickup bonus per shift, 90-day retention
# bonus, anniversary bonus), in dollars. Floor roles pick up shifts; office and
# management roles earn only the anniversary bonus.
BONUS_RULES = {
    'administrator': (0, 0, 0, 1000),
    'business_office_manager': (0, 0, 0, 300),
    'hr_payroll': (0, 0, 0, 250),
    'rn': (0.06, 100, 750, 750),
    'lpn': (0.06, 75, 500, 500),
    'lpn_supervisor': (0.04, 75, 500, 500),
    'lpn_wound_nurse': (0.03, 75, 500, 500),
    'cna': (0.08, 50, 300, 300),
    'ncna': (0.08, 40, 0, 200),
    'cma': (0.06, 50, 300, 300),
    'cook': (0.03, 25, 150, 200),
    'dietary_aide': (0.04, 25, 150, 150),
    'dietary_manager': (0, 0, 0, 300),
    'dietician': (0, 0, 0, 300),
    'housekeeper': (0.03, 25, 150, 150),
    'housekeeping_director': (0, 0, 0, 300),
    'laundry_aide': (0.03, 25, 150, 150),
    'maintenance_director': (0, 0, 0, 300),
    'social_services_director': (0, 0, 0, 300),
    'transportation_driver': (0.02, 25, 0, 150),
    'adon_lpn': (0, 0, 0, 750),
    'mds_rn': (0, 0, 0, 750),
    'staffing_coordinator': (0, 0, 0, 300),
}
# Every role in shared/staffing.py has rules, and no other.
assert set(BONUS_RULES) == set(ROLE_CODES), 'BONUS_RULES must cover shared/staffing.py ROLE_CODES exactly'
# The share of facilities that pay pickup bonuses, and retention bonuses.
PICKUP_PROGRAM_SHARE = 0.6
RETENTION_PROGRAM_SHARE = 0.7
RETENTION_DAYS = 90

RULES = ', '.join(f"('{code}', {share}, {pickup}, {retention}, {anniversary})"
    for code, (share, pickup, retention, anniversary) in BONUS_RULES.items())

# Only trusted temporary-table identifiers are interpolated; values stay bound.
BONUS_SQL = f"""
WITH rules (role, pickup_share, pickup_amount, retention_amount, anniversary_amount) AS (VALUES {RULES}),
programs AS MATERIALIZED (
    SELECT f.facility_id,
        {draw("'pickup-program:' || f.facility_id::text")} < {PICKUP_PROGRAM_SHARE} AS pickup,
        {draw("'retention-program:' || f.facility_id::text")} < {RETENTION_PROGRAM_SHARE} AS retention
    FROM facilities f
),
pickups AS (
    SELECT h.work_date AS bonus_date, h.staff_id, h.facility_id, h.role, 'pickup' AS kind,
        r.pickup_amount::numeric AS amount
    FROM daily_staff_hours h
    JOIN __DATES__ d ON d.summary_date = h.work_date
    JOIN staff_members s ON s.staff_id = h.staff_id AND s.employment_type <> 'agency'
    JOIN rules r ON r.role = h.role AND r.pickup_share > 0
    JOIN programs p ON p.facility_id = h.facility_id AND p.pickup
    WHERE {draw("'pickup:' || h.staff_id::text || ':' || h.work_date::text")} < r.pickup_share
),
retention AS (
    SELECT d.summary_date, s.staff_id, s.facility_id, s.role, 'retention_90_day', r.retention_amount::numeric
    FROM __DATES__ d
    JOIN staff_members s ON s.hire_date + {RETENTION_DAYS} = d.summary_date AND s.employment_type <> 'agency'
        AND (s.termination_date IS NULL OR s.termination_date > d.summary_date)
    JOIN rules r ON r.role = s.role AND r.retention_amount > 0
    JOIN programs p ON p.facility_id = s.facility_id AND p.retention
),
anniversaries AS (
    SELECT d.summary_date, s.staff_id, s.facility_id, s.role, 'anniversary', r.anniversary_amount::numeric
    FROM __DATES__ d
    JOIN staff_members s ON to_char(s.hire_date, 'MM-DD') = to_char(d.summary_date, 'MM-DD')
        AND s.hire_date < d.summary_date AND s.employment_type <> 'agency'
        AND (s.termination_date IS NULL OR s.termination_date > d.summary_date)
    JOIN rules r ON r.role = s.role AND r.anniversary_amount > 0
    JOIN programs p ON p.facility_id = s.facility_id AND p.retention
)
INSERT INTO __STAGE__ (bonus_date, staff_id, facility_id, role, kind, amount)
SELECT * FROM pickups
UNION ALL SELECT * FROM retention
UNION ALL SELECT * FROM anniversaries
"""


class StaffBonusesGenerator(BaseGenerator):
    name = 'staff_bonuses'
    table = schema.daily_staff_bonuses
    depends_on = ('staff_hours', 'staff_members')
    transaction_isolation = 'REPEATABLE READ'

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        self._end = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'staff_hours'))
        if self._end is None:
            raise ValueError('Staff hours are missing. Run staff_hours first.')

    def window_start(self, connection):
        """The first day kept: the staff hours' window, ending on their latest day."""
        end = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'staff_hours'))
        return None if end is None else end - timedelta(days=STAFF_HOURS_DAYS - 1)

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Staff bonuses are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        """Rows for the requested days inside the window; days before it are
        dropped and counted as zero."""
        first = self.window_start(connection)
        days = sorted(set(days))
        kept = [day for day in days if first is not None and day >= first]
        per_day = {day: 0 for day in days}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Drop days before the window')
        removed = 0
        if replace_all:
            removed = connection.execute(self.table.delete()).rowcount
        elif first is not None:
            removed = connection.execute(self.table.delete().where(self.table.c.bonus_date < first)).rowcount
        if not kept:
            return GenerationResult(0, removed), per_day
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(kept):,} dates in the window')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _staff_bonus_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=kept))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _staff_bonus_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _staff_bonus_dates')
        if self.progress:
            self.progress.set_phase('Draw each employee\'s bonuses', details=f'{len(kept):,} dates')
        stage = self.create_stage(connection, self.table)
        statement = BONUS_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_staff_bonus_dates')
        generated = connection.exec_driver_sql(statement).rowcount
        for day, count in connection.exec_driver_sql(sql.SQL(
                'SELECT bonus_date, COUNT(*) FROM {} GROUP BY bonus_date')
                .format(sql.Identifier(stage)).as_string(driver)).all():
            per_day[day] = count
        if not replace_all:
            if self.progress:
                self.progress.set_phase('Remove previous rows', details=f'{len(kept):,} selected dates')
            removed += connection.exec_driver_sql('''
                DELETE FROM daily_staff_bonuses b USING _staff_bonus_dates d WHERE b.bonus_date = d.summary_date
            ''').rowcount
        columns = sql.SQL(', ').join(map(sql.Identifier, self.table.c.keys()))
        if self.progress:
            self.progress.set_phase('Insert rows', details=f'{generated:,} rows')
        inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {}')
            .format(self._table_identifier(self.table), columns, columns, sql.Identifier(stage))
            .as_string(driver)).rowcount
        if inserted != generated:
            raise ValueError('Published row count did not match staging.')
        for temporary in (stage, '_staff_bonus_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        first = self._end - timedelta(days=STAFF_HOURS_DAYS - 1)
        days = [first + timedelta(days=offset) for offset in range(STAFF_HOURS_DAYS)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (StaffBonusesGenerator,)


class DailyStaffBonuses(DailyGenerator):
    """The new days' bonuses, and the window moved on with the staff hours'."""
    name = 'staff_bonuses'
    table = schema.daily_staff_bonuses
    owned_tables = (table,)
    depends_on = ('staff_hours',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = StaffBonusesGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        _, counts = self._builder.write_dates(connection, days)
        return {day: {self.table.name: counts[day]} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyStaffBonuses,)
