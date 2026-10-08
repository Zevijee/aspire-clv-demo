"""Calendar-month Medicaid census facts, rolled up from census_logs.

Run: python manage.py medicaid_census_summary --regenerate
Also rebuilt by every seed and update, after census_logs.

Feeds Monthly Medicaid Trending. Read from census_logs it split 161,419 census
segments between months on every load: 1.3 s for 24 months, 3.6 s for every
month since 2023.

The residents are the ones the Medicaid reports count: Medicaid in a state
whose Medicaid pays on PDPM case mix, MEDICAID_CASE_MIX_STATES in
aspire-census-logs.py and STATES in the API's mds/medicaid.py. A segment that
crosses a month boundary is split between the two months, so every month holds
exactly its own days. Segments stop at the latest simulated day.

Rebuilt whole, about 6 s, because census_logs is: payer periods are
edited after the fact, so any month may change.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

STATES = ('TX',)
THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"


def facts_sql(table):
    states = ', '.join(f"'{state}'" for state in STATES)
    return f"""
WITH through AS ({THROUGH}), medicaid AS MATERIALIZED (
    -- Medicaid first, in one scan. Joined to Texas directly, PostgreSQL takes
    -- Texas for one facility and scans census_logs once per facility: 92 s.
    SELECT l.facility_id, l.daily_rate, lower(l.in_bed) AS starts,
           least(upper(l.in_bed), (SELECT day FROM through) + 1) AS ends
    FROM census_logs l
    JOIN payers p ON p.payer_id = l.payer_id AND p.payer_type = 'medicaid'
    WHERE lower(l.in_bed) <= (SELECT day FROM through)
), segments AS (
    SELECT m.* FROM medicaid m
    JOIN facilities f ON f.facility_id = m.facility_id
    JOIN regions r ON r.region_id = f.region_id
    JOIN portfolios o ON o.portfolio_id = r.portfolio_id AND o.state IN ({states})
), days AS (
    -- Each month a segment touches, and its days inside that month.
    SELECT m::date AS month_start, s.facility_id, s.daily_rate,
           least(s.ends, (m + interval '1 month')::date) - greatest(s.starts, m::date) AS days
    FROM segments s
    CROSS JOIN LATERAL generate_series(date_trunc('month', s.starts), date_trunc('month', s.ends - 1),
        interval '1 month') AS m
)
INSERT INTO {table} (month_start, facility_id, resident_days, actual_rates)
SELECT month_start, facility_id, sum(days), sum(days * daily_rate)
FROM days
GROUP BY month_start, facility_id
"""


class MedicaidCensusSummaryGenerator(BaseGenerator):
    name = 'medicaid_census_summary'
    table = schema.monthly_medicaid_census_facts
    depends_on = ('census_logs',)
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        through = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'adt'))
        if through is None:
            raise ValueError('No simulated days yet. Run update before building Medicaid census facts.')
        if connection.scalar(select(func.count()).select_from(schema.census_logs)) == 0:
            raise ValueError('There are no census logs. Run python manage.py census_logs --regenerate first.')

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Medicaid census facts are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous facts')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Roll up Medicaid census by month')
        generated = connection.exec_driver_sql(facts_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} facility months')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (MedicaidCensusSummaryGenerator,)


class DailyMedicaidCensusSummary(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is the
    facility months starting that day, so only a month's first day has any."""
    name = 'medicaid_census_summary'
    table = schema.monthly_medicaid_census_facts
    owned_tables = (table,)
    depends_on = ('census_logs',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = MedicaidCensusSummaryGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        starts = dict(connection.execute(select(self.table.c.month_start, func.count())
            .where(self.table.c.month_start.in_(days))
            .group_by(self.table.c.month_start)).all())
        return {day: {self.table.name: starts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyMedicaidCensusSummary,)
