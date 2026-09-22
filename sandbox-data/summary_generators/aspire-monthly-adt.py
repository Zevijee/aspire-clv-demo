"""Calendar-month census and movement by payer type, built in PostgreSQL.

Run: python manage.py monthly_adt_summary --regenerate
Optional: --from YYYY-MM-DD --through YYYY-MM-DD, or --date YYYY-MM-DD.

Feeds the monthly ADT trending report. Built straight from res_payer_stays
rather than rolled up from daily_payer_census_facts: the expensive part of the
daily build is expanding every facility/payer pair across 1,361 days, and months
need balances at about 45 boundaries instead. Measured 3s here against 8 minutes
to rebuild the daily table first, for identical rows.

Same identity as the daily table, enforced by a CHECK:

    closing = opening + admissions + changes_in - discharges - changes_out

Flows are summed over the month. Census is a level, so the opening balance is
what the previous months left behind, carried by a running total.
"""
from datetime import date

from psycopg import sql
from sqlalchemy import func, inspect, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult
from summary_generators.payer_movements import MOVEMENTS_CTE

MONTHLY_SQL = """
INSERT INTO __TABLE__ (month_start, facility_id, payer_type, opening_census,
    admissions, discharges, changes_in, changes_out, closing_census)
WITH """ + MOVEMENTS_CTE.strip() + """, monthly AS (
    SELECT date_trunc('month', day)::date AS month_start, facility_id, payer_type,
           sum(adm)::int AS admissions, sum(dis)::int AS discharges,
           sum(cin)::int AS changes_in, sum(cout)::int AS changes_out
    FROM moved GROUP BY 1, 2, 3
), pairs AS (
    -- Each pair starts on its own first month, so a payer a facility never used
    -- contributes no rows at all.
    SELECT facility_id, payer_type, min(month_start) AS first_month
    FROM monthly GROUP BY 1, 2
), grid AS (
    -- Dense months per pair: a month with no movement still carries the balance.
    SELECT p.facility_id, p.payer_type, d::date AS month_start
    FROM pairs p
    CROSS JOIN LATERAL generate_series(p.first_month,
        date_trunc('month', %(last_day)s::date)::date, interval '1 month') d
), balanced AS (
    SELECT g.facility_id, g.payer_type, g.month_start,
           coalesce(m.admissions, 0) AS admissions,
           coalesce(m.discharges, 0) AS discharges,
           coalesce(m.changes_in, 0) AS changes_in,
           coalesce(m.changes_out, 0) AS changes_out,
           sum(coalesce(m.admissions, 0) + coalesce(m.changes_in, 0)
             - coalesce(m.discharges, 0) - coalesce(m.changes_out, 0))
             OVER (PARTITION BY g.facility_id, g.payer_type ORDER BY g.month_start) AS closing
    FROM grid g
    LEFT JOIN monthly m ON m.facility_id = g.facility_id
        AND m.payer_type = g.payer_type AND m.month_start = g.month_start
)
SELECT month_start, facility_id, payer_type,
       closing - admissions - changes_in + discharges + changes_out,
       admissions, discharges, changes_in, changes_out, closing
FROM balanced
"""


class MonthlyAdtSummaryGenerator(BaseGenerator):
    name = 'monthly_adt_summary'
    table = schema.monthly_payer_census_facts
    depends_on = ('res_stays',)
    transaction_isolation = 'REPEATABLE READ'
    START_DATE = date(2023, 1, 1)

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        if self.progress:
            self.progress.set_phase('Read summary date range')
        periods = self.res_payer_stays
        first, last = connection.execute(select(
            func.min(periods.c.start_date), func.max(periods.c.start_date))).one()
        self._start = min(self.START_DATE, first) if first else self.START_DATE
        last_completed = None
        if inspect(connection).has_table(self.daily_runs.name):
            last_completed = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
                .where(self.daily_runs.c.generator == 'adt'))
        self._end = last_completed or self.today()
        if last and last > self._end:
            raise ValueError('Future payer periods exist. Use seed --reset-history to replace legacy ADT history.')

    def generate(self):
        raise ValueError('Monthly facts are built directly with INSERT ... SELECT.')

    def rebuild(self, connection, last_day):
        """Rebuild every month. A running balance makes partial rebuilds wrong.

        Written straight into the table rather than through a staging copy: the
        whole table is replaced anyway, and the transaction still makes it
        atomic, so a failure rolls back to the previous contents.
        """
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Remove previous months')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}')
            .format(self._table_identifier(self.table)).as_string(driver))
        if self.progress:
            self.progress.set_phase('Suspend keys for bulk replace')
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Balance monthly census',
                details=f'through {last_day}; one source scan')
        statement = MONTHLY_SQL.replace(
            '__TABLE__', self._table_identifier(self.table).as_string(driver))
        generated = connection.exec_driver_sql(statement, dict(last_day=last_day)).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} published rows')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated, generated)

    def write_generated(self, connection):
        return self.rebuild(connection, self._end)


GENERATORS = (MonthlyAdtSummaryGenerator,)


class DailyMonthlyAdtSummary(DailyGenerator):
    name = 'monthly_adt_summary'
    table = schema.monthly_payer_census_facts
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = MonthlyAdtSummaryGenerator(self.database_url)
        self._summary.progress = self.progress
        self._summary.prepare_sources(connection)

    def run_dates(self, connection, days):
        requested = sorted(set(days))
        result = self._summary.rebuild(connection, requested[-1])
        # Checkpoints are per day, but the table's grain is the month. Attribute
        # the rows to the last requested day so the count is recorded once
        # rather than divided arbitrarily across the days of a month.
        return {day: {self.table.name: result.generated if day == requested[-1] else 0}
            for day in requested}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyMonthlyAdtSummary,)
