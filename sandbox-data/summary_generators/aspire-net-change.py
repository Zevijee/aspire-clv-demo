"""Daily census and movement by payer type, built in PostgreSQL.

Run: python manage.py net_change_summary --regenerate
Optional: --from YYYY-MM-DD --through YYYY-MM-DD, or --date YYYY-MM-DD.

adt_daily_census one level down. A payer change moves a resident between payer
types without changing the facility total, so net change by payer cannot be
derived from the facility census -- it needs its own flow:

    closing = opening + admissions + changes_in - discharges - changes_out

The table is dense: every facility/payer pair carries a row for every day from
its first movement onward, not only days that moved. A sparse table holding a
running total measured three times smaller but needed a LATERAL lookup per pair
at each period boundary, at 546ms against 73ms for this form.

Because the census is a running total, a partial rebuild would be wrong: any day
recomputed in isolation loses the balance carried into it. Every run therefore
rebuilds the whole table, which takes about as long as one day would.
"""
from datetime import date, timedelta

from psycopg import sql
from sqlalchemy import func, inspect, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult
from summary_generators.payer_movements import MOVEMENTS_CTE

# Only trusted temporary-table identifiers are interpolated; values stay bound.
FACTS_SQL = """
INSERT INTO __STAGE__ (summary_date, facility_id, payer_type, opening_census,
    admissions, discharges, changes_in, changes_out, closing_census)
WITH """ + MOVEMENTS_CTE.strip() + """, daily AS (
    SELECT day, facility_id, payer_type, sum(adm)::int AS admissions,
           sum(dis)::int AS discharges, sum(cin)::int AS changes_in,
           sum(cout)::int AS changes_out
    FROM moved GROUP BY day, facility_id, payer_type
), pairs AS (
    -- Each pair starts on its own first movement, so a payer a facility never
    -- used contributes no rows at all.
    SELECT facility_id, payer_type, min(day) AS first_day FROM daily
    GROUP BY facility_id, payer_type
), grid AS (
    SELECT p.facility_id, p.payer_type, d::date AS summary_date
    FROM pairs p
    CROSS JOIN LATERAL generate_series(p.first_day, %(last_day)s::date, interval '1 day') d
), balanced AS (
    SELECT g.facility_id, g.payer_type, g.summary_date,
           coalesce(m.admissions, 0) AS admissions,
           coalesce(m.discharges, 0) AS discharges,
           coalesce(m.changes_in, 0) AS changes_in,
           coalesce(m.changes_out, 0) AS changes_out,
           sum(coalesce(m.admissions, 0) + coalesce(m.changes_in, 0)
             - coalesce(m.discharges, 0) - coalesce(m.changes_out, 0))
             OVER (PARTITION BY g.facility_id, g.payer_type ORDER BY g.summary_date) AS closing
    FROM grid g
    LEFT JOIN daily m ON m.facility_id = g.facility_id
        AND m.payer_type = g.payer_type AND m.day = g.summary_date
)
SELECT summary_date, facility_id, payer_type,
       closing - admissions - changes_in + discharges + changes_out,
       admissions, discharges, changes_in, changes_out, closing
FROM balanced
"""

# Appending days after the last built one. The balance carried into the first new
# day is already stored, so only the new days are computed instead of all 1,361.
EXTEND_SQL = """
INSERT INTO daily_payer_census_facts (summary_date, facility_id, payer_type,
    opening_census, admissions, discharges, changes_in, changes_out, closing_census)
WITH carried AS (
    SELECT facility_id, payer_type, closing_census
    FROM daily_payer_census_facts WHERE summary_date = %(previous_day)s
), """ + MOVEMENTS_CTE.strip() + """, daily AS (
    SELECT day, facility_id, payer_type, sum(adm)::int AS admissions,
           sum(dis)::int AS discharges, sum(cin)::int AS changes_in,
           sum(cout)::int AS changes_out
    FROM moved WHERE day BETWEEN %(first_day)s AND %(last_day)s
    GROUP BY day, facility_id, payer_type
), pairs AS (
    -- Pairs already carrying a balance, plus any first seen in this window.
    SELECT facility_id, payer_type FROM carried
    UNION
    SELECT facility_id, payer_type FROM daily
), grid AS (
    SELECT p.facility_id, p.payer_type, d::date AS summary_date
    FROM pairs p
    CROSS JOIN generate_series(%(first_day)s::date, %(last_day)s::date, interval '1 day') d
), balanced AS (
    SELECT g.facility_id, g.payer_type, g.summary_date,
           coalesce(m.admissions, 0) AS admissions,
           coalesce(m.discharges, 0) AS discharges,
           coalesce(m.changes_in, 0) AS changes_in,
           coalesce(m.changes_out, 0) AS changes_out,
           coalesce(c.closing_census, 0)
             + sum(coalesce(m.admissions, 0) + coalesce(m.changes_in, 0)
                 - coalesce(m.discharges, 0) - coalesce(m.changes_out, 0))
                 OVER (PARTITION BY g.facility_id, g.payer_type ORDER BY g.summary_date) AS closing
    FROM grid g
    LEFT JOIN daily m ON m.facility_id = g.facility_id
        AND m.payer_type = g.payer_type AND m.day = g.summary_date
    LEFT JOIN carried c ON c.facility_id = g.facility_id AND c.payer_type = g.payer_type
)
SELECT summary_date, facility_id, payer_type,
       closing - admissions - changes_in + discharges + changes_out,
       admissions, discharges, changes_in, changes_out, closing
FROM balanced
"""


class NetChangeSummaryGenerator(BaseGenerator):
    name = 'net_change_summary'
    table = schema.daily_payer_census_facts
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
        raise ValueError('Payer census facts are built directly with INSERT ... SELECT.')

    def rebuild(self, connection, last_day):
        """Rebuild every row. The running balance makes partial rebuilds wrong.

        Written straight into the table rather than through a staging copy. The
        other fact generators stage so that a failure leaves the published rows
        untouched, but this one replaces all of them anyway, and at 2.5M rows the
        extra copy cost more than the whole aggregate. The transaction still
        makes it atomic: a failure rolls back to the previous contents.
        """
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Remove previous facts')
        removed = connection.exec_driver_sql(sql.SQL('TRUNCATE {}')
            .format(self._table_identifier(self.table)).as_string(driver)).rowcount
        if self.progress:
            self.progress.set_phase('Suspend keys for bulk replace')
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Balance payer census',
                details=f'through {last_day}; one source scan')
        statement = FACTS_SQL.replace(
            '__STAGE__', self._table_identifier(self.table).as_string(driver))
        generated = connection.exec_driver_sql(statement, dict(last_day=last_day)).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} published rows')
        self.restore_indexes(connection, self.table, suspended)

        if self.progress:
            self.progress.set_phase('Count facts per date', details=f'{generated:,} rows')
        counted = connection.exec_driver_sql(sql.SQL(
            'SELECT summary_date, COUNT(*) FROM {} GROUP BY summary_date')
            .format(self._table_identifier(self.table)).as_string(driver)).all()
        per_day = {day: count for day, count in counted}
        return GenerationResult(generated, generated), per_day

    def extend(self, connection, first_day, last_day):
        """Append days after the last built one, carrying the stored balance in."""
        self.show_table_progress(self.table)
        if self.progress:
            self.progress.set_phase('Extend payer census',
                details=f'{first_day} through {last_day}')
        connection.exec_driver_sql(
            'DELETE FROM daily_payer_census_facts WHERE summary_date BETWEEN %(first_day)s AND %(last_day)s',
            dict(first_day=first_day, last_day=last_day))
        generated = connection.exec_driver_sql(EXTEND_SQL, dict(
            previous_day=first_day - timedelta(days=1),
            first_day=first_day, last_day=last_day)).rowcount
        counted = connection.exec_driver_sql(
            'SELECT summary_date, COUNT(*) FROM daily_payer_census_facts '
            'WHERE summary_date BETWEEN %(first_day)s AND %(last_day)s GROUP BY summary_date',
            dict(first_day=first_day, last_day=last_day)).all()
        return GenerationResult(generated, generated), {day: count for day, count in counted}

    def write_generated(self, connection):
        result, _ = self.rebuild(connection, self._end)
        return result


GENERATORS = (NetChangeSummaryGenerator,)


class DailyNetChangeSummary(DailyGenerator):
    name = 'net_change_summary'
    table = schema.daily_payer_census_facts
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = NetChangeSummaryGenerator(self.database_url)
        self._summary.progress = self.progress
        self._summary.prepare_sources(connection)

    def run_dates(self, connection, days):
        requested = sorted(set(days))
        built_through = connection.scalar(select(func.max(self.table.c.summary_date)))
        if built_through is not None and requested[0] == built_through + timedelta(days=1):
            # A contiguous tail: the balance carried into the first new day is
            # already stored, so only the new days need computing.
            _, counts = self._summary.extend(connection, requested[0], requested[-1])
        else:
            # Anything else -- an empty table, a gap, or a rewritten earlier day --
            # changes balances downstream of it, so the whole table is rebuilt.
            _, counts = self._summary.rebuild(connection, requested[-1])
        first = self._summary._start
        opening_count = sum(count for day, count in counts.items() if day < self.SIMULATION_START)
        return {day: {self.table.name: counts.get(day, 0) +
            (opening_count if day == self.SIMULATION_START and first < self.SIMULATION_START else 0)}
            for day in requested}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyNetChangeSummary,)
