"""Daily payer change facts built in PostgreSQL with one additive aggregate.

Run: python manage.py payer_changes_summary --regenerate
Optional: --from YYYY-MM-DD --through YYYY-MM-DD, or --date YYYY-MM-DD.

A payer change is a payer period that begins as a change rather than an
admission, so every row here pairs the period that ended with the one that
started. The grain is payer TYPE: measured at payer-id grain the table came to
99.9% of the source rows, which is a copy rather than a summary. Individual plan
names stay in res_payer_stays, where the logs read them.

Residents affected is deliberately not stored. It is a distinct count, and the
same resident can change payer on two different days, so no set of per-day rows
can be summed into it. The report counts it from res_payer_stays directly.
"""
from datetime import date, timedelta

from psycopg import sql
from sqlalchemy import func, inspect, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

# Only trusted temporary-table identifiers are interpolated; values stay bound.
FACTS_SQL = """
INSERT INTO __STAGE__ (summary_date, facility_id, previous_payer_type, new_payer_type, changes)
SELECT n.start_date, s.facility_id, pp.payer_type, np.payer_type, COUNT(*)
FROM res_payer_stays n
JOIN __DATES__ t ON t.summary_date = n.start_date
JOIN res_payer_stays p ON p.stay_id = n.stay_id AND p.period_number = n.period_number - 1
JOIN res_stays s ON s.stay_id = n.stay_id
JOIN payers np ON np.payer_id = n.payer_id
JOIN payers pp ON pp.payer_id = p.payer_id
WHERE n.period_number > 1
GROUP BY n.start_date, s.facility_id, pp.payer_type, np.payer_type
"""


class PayerChangesSummaryGenerator(BaseGenerator):
    name = 'payer_changes_summary'
    table = schema.daily_payer_change_facts
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
            self.progress.set_phase('Check payer periods')
        periods = self.res_payer_stays
        # One alias, reused: three separate alias() calls would emit the same
        # name three times and Postgres rejects the query.
        prior = periods.alias('prior')
        # Every change must have the period it moved from, or the pairing below
        # would silently drop it instead of reporting the gap.
        orphan = connection.scalar(select(periods.c.payer_stay_id).where(
            periods.c.period_number > 1,
            ~select(1).select_from(prior).where(
                prior.c.stay_id == periods.c.stay_id,
                prior.c.period_number == periods.c.period_number - 1).exists()
        ).limit(1))
        if orphan is not None:
            raise ValueError('Some payer periods have no preceding period. '
                'Rebuild res_stays before summarizing payer changes.')
        if self.progress:
            self.progress.set_phase('Read summary date range')
        first, last = connection.execute(select(
            func.min(periods.c.start_date), func.max(periods.c.start_date))
            .where(periods.c.period_number > 1)).one()
        self._start = min(self.START_DATE, first) if first else self.START_DATE
        last_completed = None
        if inspect(connection).has_table(self.daily_runs.name):
            last_completed = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
                .where(self.daily_runs.c.generator == 'adt'))
        self._end = last_completed or self.today()
        if last and last > self._end:
            raise ValueError('Future payer changes exist. Use seed --reset-history to replace legacy ADT history.')

    def generate(self):
        raise ValueError('Payer change facts are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        days = sorted(set(days))
        if not days:
            return GenerationResult(0, 0), {}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(days):,} dates')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _payer_change_fact_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=days))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _payer_change_fact_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _payer_change_fact_dates')

        # One pass. The self-join is paid here, once, instead of on every report.
        if self.progress:
            self.progress.set_phase('Aggregate payer changes', details=f'{len(days):,} dates; one source scan')
        stage = self.create_stage(connection, self.table)
        statement = FACTS_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_payer_change_fact_dates')
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
                DELETE FROM daily_payer_change_facts f USING _payer_change_fact_dates d
                WHERE f.summary_date = d.summary_date
            ''').rowcount
        # Only then drop the keys, so the insert builds them once over the
        # finished rows instead of maintaining them per row.
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
        for temporary in (stage, '_payer_change_fact_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}')
                .format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        days = [self._start + timedelta(days=offset)
            for offset in range((self._end - self._start).days + 1)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (PayerChangesSummaryGenerator,)


class DailyPayerChangesSummary(DailyGenerator):
    name = 'payer_changes_summary'
    table = schema.daily_payer_change_facts
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = PayerChangesSummaryGenerator(self.database_url)
        self._summary.progress = self.progress
        self._summary.prepare_sources(connection)

    def run_dates(self, connection, days):
        requested = set(days)
        fact_days = set(requested)
        if self.SIMULATION_START in requested:
            # Opening residents can change payer before the first simulation day
            # if their stay began in the late-2022 snapshot; fold those into the
            # first checkpoint exactly as the admission and discharge facts do.
            fact_days.update(self._summary._start + timedelta(days=offset)
                for offset in range((self.SIMULATION_START - self._summary._start).days))
        _, counts = self._summary.write_dates(connection, fact_days)
        opening_count = sum(count for day, count in counts.items() if day < self.SIMULATION_START)
        return {day: {self.table.name: counts[day] +
            (opening_count if day == self.SIMULATION_START else 0)} for day in requested}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyPayerChangesSummary,)
