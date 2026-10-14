"""Each facility, role and day's in-service training: the hours staff spent in
training sessions and their pay. One row per facility, role and weekday with a
session, for the whole history, for the Staffing Overview.

Run: python manage.py training_summary --regenerate
Also rebuilt by every seed and update, after the staffing facts.

Drawn straight from daily_staffing_facts, as the onboarding facts are: there is
no learning-management source. Every role owes yearly in-service hours per
full-time worker -- a CNA the federal 12, wound and MDS nurses more, support
staff a few -- moved by a facility habit, and held in sessions on weekdays:

    owed a weekday = hours / 40 x 7 x yearly hours x habit / 260
    a session      = on SESSION_CHANCE of weekdays, owed / SESSION_CHANCE hours,
                     0.6 to 1.4 times that

so a year's sessions come to the yearly hours. Hours are paid at the day's
in-house rate (the facts' wages over hours). Training is paid time, not care,
so it is never added to the facts' hours worked. Every draw is an md5 of the
facility, role and day, so a rebuild writes the same rows.
"""
from datetime import timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from shared.staffing import ROLE_CODES
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw as _draw


def draw(seed):
    """A stable draw as a double, as the onboarding facts draw."""
    return f'({_draw(seed)})::float8'


# Yearly in-service hours per full-time worker, by role.
TRAINING_HOURS = {
    'administrator': 8, 'business_office_manager': 6, 'hr_payroll': 6,
    'rn': 10, 'lpn': 10, 'lpn_supervisor': 10, 'lpn_wound_nurse': 14, 'cna': 12, 'ncna': 12, 'cma': 12,
    'cook': 6, 'dietary_aide': 6, 'dietary_manager': 8, 'dietician': 8,
    'housekeeper': 4, 'housekeeping_director': 6, 'laundry_aide': 4,
    'maintenance_director': 6, 'social_services_director': 8, 'transportation_driver': 6,
    'adon_lpn': 12, 'mds_rn': 16, 'staffing_coordinator': 6,
}
# Every role in shared/staffing.py has its hours, and no other.
assert set(TRAINING_HOURS) == set(ROLE_CODES), 'TRAINING_HOURS must cover shared/staffing.py ROLE_CODES exactly'
# The share of weekdays a facility and role holds a session.
SESSION_CHANCE = 0.15
WEEKDAYS_A_YEAR = 260
# A facility and role's training against the role's: 0.7 to 1.3 times it.
HABIT = (0.7, 0.6)

ROLE = "f.facility_id::text || ':' || f.role"
DAY = ROLE + " || ':' || f.summary_date::text"
RULES = ', '.join(f"('{code}', {hours})" for code, hours in TRAINING_HOURS.items())

# Only trusted temporary-table identifiers are interpolated; values stay bound.
TRAINING_SQL = f"""
WITH rules (role, yearly_hours) AS (VALUES {RULES}),
facts AS (
    SELECT f.summary_date, f.facility_id, f.role, f.hours_worked, f.wages / f.hours_worked AS rate
    FROM daily_staffing_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    WHERE f.hours_worked > 0 AND extract(isodow FROM f.summary_date) < 6
),
-- Each facility and role's habit, drawn once for its pairs.
habits AS MATERIALIZED (
    SELECT f.facility_id, f.role, {HABIT[0]} + {HABIT[1]} * {draw("'training-habit:' || " + ROLE)} AS habit
    FROM (SELECT DISTINCT facility_id, role FROM facts) f
),
sessions AS (
    SELECT f.summary_date, f.facility_id, f.role, f.rate,
        f.hours_worked / 40.0 * 7 * r.yearly_hours * h.habit / {WEEKDAYS_A_YEAR} / {SESSION_CHANCE}
            * (0.6 + 0.8 * {draw("'training-size:' || " + DAY)}) AS hours
    FROM facts f
    JOIN habits h ON h.facility_id = f.facility_id AND h.role = f.role
    JOIN rules r ON r.role = f.role
    WHERE {draw("'training-day:' || " + DAY)} < {SESSION_CHANCE}
)
INSERT INTO __STAGE__ (summary_date, facility_id, role, training_hours, training_wages)
SELECT summary_date, facility_id, role, round(hours::numeric, 1), round((round(hours::numeric, 1) * rate)::numeric, 2)
FROM sessions
WHERE round(hours::numeric, 1) > 0
"""


class TrainingSummaryGenerator(BaseGenerator):
    name = 'training_summary'
    table = schema.daily_training_facts
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
        raise ValueError('Training facts are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        days = sorted(set(days))
        if not days:
            return GenerationResult(0, 0), {}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(days):,} dates')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _training_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=days))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _training_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _training_dates')
        if self.progress:
            self.progress.set_phase('Draw each facility, role and day\'s sessions', details=f'{len(days):,} dates')
        stage = self.create_stage(connection, self.table)
        statement = TRAINING_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_training_dates')
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
                DELETE FROM daily_training_facts f USING _training_dates d WHERE f.summary_date = d.summary_date
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
        for temporary in (stage, '_training_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        days = [self._start + timedelta(days=offset) for offset in range((self._end - self._start).days + 1)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (TrainingSummaryGenerator,)


class DailyTrainingSummary(DailyGenerator):
    name = 'training_summary'
    table = schema.daily_training_facts
    owned_tables = (table,)
    depends_on = ('staffing_summary',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = TrainingSummaryGenerator(self.database_url)
        self._summary.progress = self.progress

    def run_dates(self, connection, days):
        _, counts = self._summary.write_dates(connection, days)
        return {day: {self.table.name: counts[day]} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyTrainingSummary,)
