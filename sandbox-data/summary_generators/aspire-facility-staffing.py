"""Each facility's day across every role: hours worked, target hours and
closing census, one row per facility and day, for the PPD report.

Run: python manage.py facility_staffing_summary --regenerate
Also rebuilt by every seed and update, after the staffing facts and the census.

A rollup of daily_staffing_facts over its 11 roles, with the day's closing
census from daily_payer_census_facts summed over payer types: 349,000 rows
against 3.8M and 2.5M. It exists for one measured reason: the PPD trend over
every role read a million staffing rows for a year and rolled 740,000 payer
rows up for the census, 1.5 s in the service and 3.6 s at the browser; from
this table a year is 92,000 rows. Hours and targets stay additive; census is
the facility's own and is never added across facilities' roles.

Built whole in one INSERT ... SELECT for the requested dates, as the staffing
facts are: nothing is drawn, so a rebuild writes the same rows.
"""
from datetime import timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

# Only trusted temporary-table identifiers are interpolated.
ROLLUP_SQL = """
WITH census AS (
    SELECT f.summary_date, f.facility_id, SUM(f.closing_census) AS closing_census
    FROM daily_payer_census_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    GROUP BY f.summary_date, f.facility_id
),
staffing AS (
    SELECT f.summary_date, f.facility_id, SUM(f.hours_worked) AS hours_worked, SUM(f.target_hours) AS target_hours
    FROM daily_staffing_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    GROUP BY f.summary_date, f.facility_id
)
INSERT INTO __STAGE__ (summary_date, facility_id, hours_worked, target_hours, closing_census)
SELECT c.summary_date, c.facility_id, COALESCE(s.hours_worked, 0), COALESCE(s.target_hours, 0), c.closing_census
FROM census c
LEFT JOIN staffing s ON s.summary_date = c.summary_date AND s.facility_id = c.facility_id
"""


class FacilityStaffingSummaryGenerator(BaseGenerator):
    name = 'facility_staffing_summary'
    table = schema.daily_facility_staffing_facts
    depends_on = ('staffing_summary', 'net_change_summary')
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
        raise ValueError('Facility staffing facts are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        days = sorted(set(days))
        if not days:
            return GenerationResult(0, 0), {}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(days):,} dates')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _facility_staffing_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=days))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _facility_staffing_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _facility_staffing_dates')
        if self.progress:
            self.progress.set_phase('Roll each facility day up', details=f'{len(days):,} dates')
        stage = self.create_stage(connection, self.table)
        statement = ROLLUP_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_facility_staffing_dates')
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
                DELETE FROM daily_facility_staffing_facts f USING _facility_staffing_dates d
                WHERE f.summary_date = d.summary_date
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
        for temporary in (stage, '_facility_staffing_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        days = [self._start + timedelta(days=offset) for offset in range((self._end - self._start).days + 1)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (FacilityStaffingSummaryGenerator,)


class DailyFacilityStaffingSummary(DailyGenerator):
    name = 'facility_staffing_summary'
    table = schema.daily_facility_staffing_facts
    owned_tables = (table,)
    depends_on = ('staffing_summary', 'net_change_summary')
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = FacilityStaffingSummaryGenerator(self.database_url)
        self._summary.progress = self.progress

    def run_dates(self, connection, days):
        _, counts = self._summary.write_dates(connection, days)
        return {day: {self.table.name: counts[day]} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyFacilityStaffingSummary,)
