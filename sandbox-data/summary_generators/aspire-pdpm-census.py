"""Calendar-month PDPM census facts, rolled up from the PDPM rate steps.

Run: python manage.py pdpm_census_summary --regenerate
Also rebuilt by every seed and update, after census_logs.

Feeds Current Medicare PDPM's Overview, which compares today with last month's,
the last 6 and 12 months' and the all-time average. Read from the steps alone
that meant all 924,406 Medicare steps on every load, 1.1 s; this is 24,613 rows.

The residents are the ones Current Medicare PDPM counts: Original Medicare and
Managed Medicare PDPM on a PDPM contract. A step that crosses a month boundary
is split between the two months, so every month holds exactly its own days.
The steps stop at the latest simulated day; an open step is cut there too.

Rebuilt whole, about 2 s, because census_logs and its steps are: payer periods
are edited after the fact, so any month may change.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"


def facts_sql(table):
    return f"""
WITH through AS ({THROUGH}), steps AS (
    SELECT s.facility_id, p.payer_type, l.daily_rate, l.pdpm_factor, lower(l.in_effect) AS starts,
           least(upper(l.in_effect), (SELECT day FROM through) + 1) AS ends
    FROM pdpm_rate_logs l
    JOIN res_payer_stays ps ON ps.payer_stay_id = l.payer_stay_id
    JOIN payers p ON p.payer_id = ps.payer_id AND p.payer_type IN ('medicare', 'managed_medicare_pdpm')
    JOIN res_stays s ON s.stay_id = ps.stay_id
    -- A PDPM contract, as Current Medicare PDPM counts: per diem plans are out.
    JOIN facility_payer_rates c ON c.facility_id = s.facility_id AND c.payer_id = ps.payer_id
        AND c.payment_method = 'pdpm'
    WHERE lower(l.in_effect) <= (SELECT day FROM through)
), days AS (
    -- Each month a step touches, and its days inside that month.
    SELECT m::date AS month_start, st.facility_id, st.payer_type, st.daily_rate, st.pdpm_factor,
           least(st.ends, (m + interval '1 month')::date) - greatest(st.starts, m::date) AS days
    FROM steps st
    CROSS JOIN LATERAL generate_series(date_trunc('month', st.starts), date_trunc('month', st.ends - 1),
        interval '1 month') AS m
)
INSERT INTO {table} (month_start, facility_id, payer_type, resident_days, actual_rates, factor_days)
SELECT month_start, facility_id, payer_type, sum(days), sum(days * daily_rate), sum(days * pdpm_factor)
FROM days
GROUP BY month_start, facility_id, payer_type
"""


class PdpmCensusSummaryGenerator(BaseGenerator):
    name = 'pdpm_census_summary'
    table = schema.monthly_pdpm_census_facts
    depends_on = ('census_logs',)
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        through = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'adt'))
        if through is None:
            raise ValueError('No simulated days yet. Run update before building PDPM census facts.')
        if connection.scalar(select(func.count()).select_from(schema.pdpm_rate_logs)) == 0:
            raise ValueError('There are no PDPM rate steps. Run python manage.py census_logs --regenerate first.')

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('PDPM census facts are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous facts')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Roll up PDPM rate steps by month')
        generated = connection.exec_driver_sql(facts_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} facility months')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (PdpmCensusSummaryGenerator,)


class DailyPdpmCensusSummary(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is the
    facility months starting that day, so only a month's first day has any."""
    name = 'pdpm_census_summary'
    table = schema.monthly_pdpm_census_facts
    owned_tables = (table,)
    # The steps census_logs writes, so never before that day's steps exist.
    depends_on = ('census_logs',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = PdpmCensusSummaryGenerator(self.database_url)
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


DAILY_GENERATORS = (DailyPdpmCensusSummary,)
