"""Daily discharge facts built in PostgreSQL with one additive aggregate.

Run: python manage.py discharges_summary --regenerate
Optional: --from YYYY-MM-DD --through YYYY-MM-DD, or --date YYYY-MM-DD.

One row per (date, facility, payer, destination) that had discharges. Parent
location totals are report GROUP BY results, so no scope is double counted and no
empty scope-day is stored. Transfers and deaths are read back from the
destination; only AMA needs its own measure. Length of stay is summed beside its
count rather than averaged: an average stored per row cannot be rolled up
correctly.
"""
from datetime import date, timedelta

from psycopg import sql
from sqlalchemy import func, inspect, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

# Only trusted temporary-table identifiers are interpolated; values stay bound.
FACTS_SQL = """
INSERT INTO __STAGE__ (summary_date, facility_id, payer_id, destination_type,
    destination_name, discharges, ama_discharges, length_of_stay_days)
SELECT d.discharge_date, s.facility_id, d.payer_id, d.destination_type,
       d.destination_name,
       COUNT(*),
       COUNT(*) FILTER (WHERE d.is_ama),
       SUM(d.los)
FROM discharge_logs d
JOIN __DATES__ t ON t.summary_date = d.discharge_date
JOIN res_stays s ON s.stay_id = d.stay_id
GROUP BY d.discharge_date, s.facility_id, d.payer_id, d.destination_type,
         d.destination_name
"""


class DischargesSummaryGenerator(BaseGenerator):
    name = 'discharges_summary'
    table = schema.daily_discharge_facts
    depends_on = ('discharge_logs',)
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
            self.progress.set_phase('Check discharge logs')
        logs, stays = self.discharge_logs, self.res_stays
        missing = connection.scalar(select(stays.c.stay_id).where(
            stays.c.discharge_date.is_not(None),
            ~select(logs.c.stay_id).where(logs.c.stay_id == stays.c.stay_id).exists()).limit(1))
        if missing is not None:
            raise ValueError('Some closed stays have no discharge log. Refresh discharge_logs before summarizing.')
        if self.progress:
            self.progress.set_phase('Read summary date range')
        first, last = connection.execute(select(
            func.min(logs.c.discharge_date), func.max(logs.c.discharge_date))).one()
        self._start = min(self.START_DATE, first) if first else self.START_DATE
        last_completed = None
        if inspect(connection).has_table(self.daily_runs.name):
            last_completed = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
                .where(self.daily_runs.c.generator == 'adt'))
        self._end = last_completed or self.today()
        if last and last > self._end:
            raise ValueError('Future discharge logs exist. Use seed --reset-history to replace legacy ADT history.')

    def generate(self):
        raise ValueError('Discharge facts are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        days = sorted(set(days))
        if not days:
            return GenerationResult(0, 0), {}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(days):,} dates')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _discharge_fact_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=days))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _discharge_fact_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _discharge_fact_dates')

        # One pass over the selected discharges. No per-scope or per-day query.
        if self.progress:
            self.progress.set_phase('Aggregate discharges', details=f'{len(days):,} dates; one source scan')
        stage = self.create_stage(connection, self.table)
        statement = FACTS_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_discharge_fact_dates')
        generated = connection.exec_driver_sql(statement).rowcount

        if self.progress:
            self.progress.set_phase('Count facts per date', details=f'{generated:,} rows staged')
        per_day = {day: 0 for day in days}
        counted = connection.exec_driver_sql(sql.SQL(
            'SELECT summary_date, COUNT(*) FROM {} GROUP BY summary_date')
            .format(sql.Identifier(stage)).as_string(driver)).all()
        for day, count in counted:
            per_day[day] = count

        # Delete first, while the keys still exist: the date predicate needs the
        # primary key to avoid scanning the whole table.
        if self.progress:
            self.progress.set_phase('Remove previous facts', details=f'{len(days):,} selected dates')
        if replace_all:
            removed = connection.execute(self.table.delete()).rowcount
        else:
            removed = connection.exec_driver_sql('''
                DELETE FROM daily_discharge_facts f USING _discharge_fact_dates d
                WHERE f.summary_date = d.summary_date
            ''').rowcount
        # Only then drop the keys, so the insert builds them once over the finished
        # rows instead of maintaining them per row.
        suspended = None
        if replace_all or self.replaces_most_rows(connection, self.table, generated):
            if self.progress:
                self.progress.set_phase('Suspend keys for bulk replace')
            suspended = self.suspend_indexes(connection, self.table)
        columns = sql.SQL(', ').join(map(sql.Identifier, self.table.c.keys()))
        if self.progress:
            self.progress.set_phase('Insert facts', details=f'{generated:,} rows; atomic replacement')
        inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {}')
            .format(self._table_identifier(self.table), columns, columns, sql.Identifier(stage))
            .as_string(driver)).rowcount
        if inserted != generated:
            raise ValueError('Published fact row count did not match staging.')
        if suspended is not None:
            if self.progress:
                self.progress.set_phase('Rebuild keys', details=f'{inserted:,} published rows')
            self.restore_indexes(connection, self.table, suspended)
        if self.progress:
            self.progress.set_phase('Clean temporary tables')
        for temporary in (stage, '_discharge_fact_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}')
                .format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        days = [self._start + timedelta(days=offset)
            for offset in range((self._end - self._start).days + 1)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (DischargesSummaryGenerator,)


class DailyDischargesSummary(DailyGenerator):
    name = 'discharges_summary'
    table = schema.daily_discharge_facts
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = DischargesSummaryGenerator(self.database_url)
        self._summary.progress = self.progress
        self._summary.prepare_sources(connection)

    def run_dates(self, connection, days):
        requested = set(days)
        fact_days = set(requested)
        if self.SIMULATION_START in requested:
            # Opening residents can discharge before the first simulation day only
            # if their stay began in the late-2022 snapshot; fold those into the
            # first checkpoint exactly as the admissions facts do.
            fact_days.update(self._summary._start + timedelta(days=offset)
                for offset in range((self.SIMULATION_START - self._summary._start).days))
        _, counts = self._summary.write_dates(connection, fact_days)
        opening_count = sum(count for day, count in counts.items() if day < self.SIMULATION_START)
        return {day: {self.table.name: counts[day] +
            (opening_count if day == self.SIMULATION_START else 0)} for day in requested}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyDischargesSummary,)
