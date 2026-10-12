"""Each facility, role and day's hours split between agency staff and the
facility's own, with the pay of each. One row per facility, role and day with
hours, for the whole history, for the Agency vs In-house report.

Run: python manage.py agency_summary --regenerate
Also rebuilt by every seed and update, after the staffing facts.

Drawn straight from daily_staffing_facts, as the facts are drawn from the
census: there is no timekeeping source, so this is the source. Each facility
and role has an agency habit -- most use almost none, a few a quarter of their
hours -- and each day moves around it, weekends leaning on agency more.
Nothing here comes from the per-person hours, which exist for the last 120
days only (daily_staff_hours): a rollup of those covered four months where
every other report covers four years. The Logs tab still names the roster's
agency people from the person rows, so its shifts for a day and this table's
agency hours for it agree in kind, not to the hour.

    agency hours = hours x habit x (0.5 to 1.5 for the day) x 1.3 at weekends

Wages: in-house hours keep the day's rate from the facts, and agency hours
bill AGENCY_PREMIUM times it, on top, so the report's extra spent on agency is
the agency hours at the premium over the rate. Every draw is an md5 of the
facility, role and day, so a rebuild writes the same rows.
"""
from datetime import timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw as _draw


def draw(seed):
    """A stable draw as a double: numeric draws carry a scale that grows with
    every multiplication, as the staffing facts found."""
    return f'({_draw(seed)})::float8'


# What an agency hour bills over the day's rate: the same premium the roster's
# agency people carry, so the Logs tab prices agency alike.
AGENCY_PREMIUM = 1.9
# A facility and role's share of hours that are agency: squared, so most use
# almost none and a few lean on it.
AGENCY_HABIT_MAX = 0.25
WEEKEND_LIFT = 1.3

ROLE = "f.facility_id::text || ':' || f.role"
DAY = ROLE + " || ':' || f.summary_date::text"

# Only trusted temporary-table identifiers are interpolated; values stay bound.
AGENCY_SQL = f"""
WITH facts AS (
    SELECT f.summary_date, f.facility_id, f.role, f.hours_worked, f.wages / f.hours_worked AS rate,
        extract(isodow FROM f.summary_date) >= 6 AS weekend
    FROM daily_staffing_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    WHERE f.hours_worked > 0
),
-- Each facility and role's habit, drawn once for its pairs. Materialized, as
-- the staffing facts' habits are, so the draw is not repeated on every row.
habits AS MATERIALIZED (
    SELECT f.facility_id, f.role, {AGENCY_HABIT_MAX} * power({draw("'agency-habit:' || " + ROLE)}, 2) AS habit
    FROM (SELECT DISTINCT facility_id, role FROM facts) f
),
split AS (
    SELECT f.summary_date, f.facility_id, f.role, f.hours_worked, f.rate,
        round((f.hours_worked * least(0.5, h.habit * (0.5 + {draw("'agency-day:' || " + DAY)})
            * CASE WHEN f.weekend THEN {WEEKEND_LIFT} ELSE 1 END))::numeric, 2) AS agency_hours
    FROM facts f
    JOIN habits h ON h.facility_id = f.facility_id AND h.role = f.role
)
INSERT INTO __STAGE__ (summary_date, facility_id, role, agency_hours, agency_wages, inhouse_hours, inhouse_wages)
SELECT summary_date, facility_id, role,
    agency_hours, round((agency_hours * rate * {AGENCY_PREMIUM})::numeric, 2),
    hours_worked - agency_hours, round(((hours_worked - agency_hours) * rate)::numeric, 2)
FROM split
"""


class AgencySummaryGenerator(BaseGenerator):
    name = 'agency_summary'
    table = schema.daily_agency_facts
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
        raise ValueError('Agency facts are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        days = sorted(set(days))
        if not days:
            return GenerationResult(0, 0), {}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(days):,} dates')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _agency_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=days))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _agency_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _agency_dates')
        if self.progress:
            self.progress.set_phase('Split each facility, role and day', details=f'{len(days):,} dates')
        stage = self.create_stage(connection, self.table)
        statement = AGENCY_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_agency_dates')
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
                DELETE FROM daily_agency_facts f USING _agency_dates d WHERE f.summary_date = d.summary_date
            ''').rowcount
        suspended = None
        if replace_all or self.replaces_most_rows(connection, self.table, generated):
            suspended = self.suspend_indexes(connection, self.table)
        columns = sql.SQL(', ').join(map(sql.Identifier, self.table.c.keys()))
        if self.progress:
            self.progress.set_phase('Insert rows', details=f'{generated:,} rows')
        inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {}')
            .format(self._table_identifier(self.table), columns, columns, sql.Identifier(stage))
            .as_string(driver)).rowcount
        if inserted != generated:
            raise ValueError('Published row count did not match staging.')
        if suspended is not None:
            self.restore_indexes(connection, self.table, suspended)
        for temporary in (stage, '_agency_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        days = [self._start + timedelta(days=offset) for offset in range((self._end - self._start).days + 1)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (AgencySummaryGenerator,)


class DailyAgencySummary(DailyGenerator):
    name = 'agency_summary'
    table = schema.daily_agency_facts
    owned_tables = (table,)
    depends_on = ('staffing_summary',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = AgencySummaryGenerator(self.database_url)
        self._summary.progress = self.progress

    def run_dates(self, connection, days):
        _, counts = self._summary.write_dates(connection, days)
        return {day: {self.table.name: counts[day]} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyAgencySummary,)
