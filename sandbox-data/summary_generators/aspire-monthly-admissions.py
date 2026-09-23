"""Calendar-month admission and discharge facts, rolled up in PostgreSQL.

Run: python manage.py monthly_adt_facts --regenerate
Optional: --from YYYY-MM-DD --through YYYY-MM-DD, or --date YYYY-MM-DD.

Two tables from one generator because they are the same shape over two source
tables and are always wanted together: the monthly ADT report has an admissions
view and a discharges view, and each needs a dimension the payer census rollup
cannot carry.

`monthly_payer_census_facts` already holds monthly admissions and discharges and
serves the same report's net change view. It cannot serve these, because it has
no referral source or destination and could not gain one: its opening and closing
census are a level rather than a flow, and a resident's presence in a bed does
not divide by where they arrived from or left for.

Rolled up from the daily fact tables rather than rebuilt from the logs, for the
same reason as referrals: the daily facts are written earlier in the same run and
reading the rows the daily reports read means the monthly and daily views cannot
disagree.

Flows only -- no census, no running balance -- so a month is the sum of its own
days and only the months containing changed days need rebuilding.
"""
from datetime import date

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

# Only trusted temporary-table identifiers are interpolated; values stay bound.
# Each month joins on a date range rather than on date_trunc(summary_date), which
# keeps the daily table's primary key usable so rebuilding one month reads one
# month instead of scanning four years.
ADMISSIONS_SQL = """
INSERT INTO __STAGE__ (month_start, facility_id, payer_type, source_type,
    admissions, readmissions, readmissions_30_day)
SELECT m.month_start, f.facility_id, p.payer_type, f.source_type,
       SUM(f.admissions), SUM(f.readmissions), SUM(f.readmissions_30_day)
FROM __MONTHS__ m
JOIN daily_admission_facts f
  ON f.summary_date >= m.month_start
 AND f.summary_date < m.month_start + INTERVAL '1 month'
JOIN payers p ON p.payer_id = f.payer_id
GROUP BY m.month_start, f.facility_id, p.payer_type, f.source_type
"""

DISCHARGES_SQL = """
INSERT INTO __STAGE__ (month_start, facility_id, payer_type, destination_type,
    discharges, ama_discharges, length_of_stay_days)
SELECT m.month_start, f.facility_id, p.payer_type, f.destination_type,
       SUM(f.discharges), SUM(f.ama_discharges), SUM(f.length_of_stay_days)
FROM __MONTHS__ m
JOIN daily_discharge_facts f
  ON f.summary_date >= m.month_start
 AND f.summary_date < m.month_start + INTERVAL '1 month'
JOIN payers p ON p.payer_id = f.payer_id
GROUP BY m.month_start, f.facility_id, p.payer_type, f.destination_type
"""


def month_of(day):
    return day.replace(day=1)


def next_month(month):
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


class MonthlyAdtFactsGenerator(BaseGenerator):
    name = 'monthly_adt_facts'
    table = schema.monthly_admission_facts
    related_tables = (schema.monthly_discharge_facts,)
    depends_on = ('admissions_summary', 'discharges_summary')
    transaction_isolation = 'REPEATABLE READ'

    SOURCES = (
        (schema.monthly_admission_facts, ADMISSIONS_SQL, schema.daily_admission_facts),
        (schema.monthly_discharge_facts, DISCHARGES_SQL, schema.daily_discharge_facts),
    )

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        if self.progress:
            self.progress.set_phase('Read summary date range')
        first, last = None, None
        for _, _, daily in self.SOURCES:
            low, high = connection.execute(select(
                func.min(daily.c.summary_date), func.max(daily.c.summary_date))).one()
            first = low if first is None else min(first, low) if low else first
            last = high if last is None else max(last, high) if high else last
        # Opening admissions keep their late-2022 dates, so the first month is
        # the daily tables' own first month rather than the simulation start.
        self._first_month = month_of(first) if first else month_of(self.SIMULATION_START)
        self._last_month = month_of(last) if last else self._first_month

    def generate(self):
        raise ValueError('Monthly ADT facts are built directly with INSERT ... SELECT.')

    def every_month(self):
        months, month = [], self._first_month
        while month <= self._last_month:
            months.append(month)
            month = next_month(month)
        return months

    def write_months(self, connection, months, *, replace_all=False):
        """Replace whole months atomically. A month is the sum of its own days."""
        months = sorted(set(months))
        if not months:
            return GenerationResult(0, 0), {}
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare months', details=f'{len(months):,} months')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _monthly_adt_months ON COMMIT DROP AS
            SELECT unnest(%(months)s::date[]) AS month_start
        ''', dict(months=months))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _monthly_adt_months (month_start)')
        connection.exec_driver_sql('ANALYZE _monthly_adt_months')

        generated = removed = published = 0
        per_month = {month: 0 for month in months}
        for table, statement_sql, _ in self.SOURCES:
            self.show_table_progress(table)
            if self.progress:
                self.progress.set_phase(f'Roll up {table.name}',
                    details=f'{len(months):,} months; one pass over the daily facts')
            stage = self.create_stage(connection, table)
            statement = statement_sql.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
            statement = statement.replace('__MONTHS__', '_monthly_adt_months')
            staged = connection.exec_driver_sql(statement).rowcount
            generated += staged

            # Attribute rows to months for the checkpoint record. Admissions and
            # discharges both land on the month, so they add together.
            for month, count in connection.exec_driver_sql(sql.SQL(
                    'SELECT month_start, COUNT(*) FROM {} GROUP BY month_start')
                    .format(sql.Identifier(stage)).as_string(driver)).all():
                per_month[month] += count

            # Replace the selected months in the transaction that publishes them.
            # Delete first, while the keys still exist: month_start leads the
            # primary key, so the predicate never scans the whole table.
            if self.progress:
                self.progress.set_phase('Remove previous facts',
                    details=f'{len(months):,} selected months')
            if replace_all:
                removed += connection.execute(table.delete()).rowcount
            else:
                removed += connection.exec_driver_sql(sql.SQL(
                    'DELETE FROM {} f USING _monthly_adt_months m WHERE f.month_start = m.month_start')
                    .format(self._table_identifier(table)).as_string(driver)).rowcount
            # Only then drop the keys, so the insert builds them once over the
            # finished rows instead of maintaining them per row.
            suspended = None
            if replace_all or self.replaces_most_rows(connection, table, staged):
                if self.progress:
                    self.progress.set_phase('Suspend keys for bulk replace')
                suspended = self.suspend_indexes(connection, table)
            columns = sql.SQL(', ').join(map(sql.Identifier, table.c.keys()))
            if self.progress:
                self.progress.set_phase('Insert facts',
                    details=f'{staged:,} rows; atomic replacement')
            inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {}')
                .format(self._table_identifier(table), columns, columns, sql.Identifier(stage))
                .as_string(driver)).rowcount
            if inserted != staged:
                raise ValueError(f'Published {table.name} row count did not match staging.')
            published += inserted
            if suspended is not None:
                if self.progress:
                    self.progress.set_phase('Rebuild keys', details=f'{inserted:,} published rows')
                self.restore_indexes(connection, table, suspended)
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}')
                .format(sql.Identifier(stage)).as_string(driver))

        if self.progress:
            self.progress.set_phase('Clean temporary tables')
        connection.exec_driver_sql('DROP TABLE _monthly_adt_months')
        return GenerationResult(generated, removed + published), per_month

    def write_generated(self, connection):
        result, _ = self.write_months(connection, self.every_month(), replace_all=True)
        return result


GENERATORS = (MonthlyAdtFactsGenerator,)


class DailyMonthlyAdtFacts(DailyGenerator):
    name = 'monthly_adt_facts'
    table = schema.monthly_admission_facts
    owned_tables = (schema.monthly_admission_facts, schema.monthly_discharge_facts)
    # Reads what admissions_summary and discharges_summary wrote, so it must not
    # run for a day before those days' facts exist.
    depends_on = ('admissions_summary', 'discharges_summary')
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = MonthlyAdtFactsGenerator(self.database_url)
        self._summary.progress = self.progress
        self._summary.prepare_sources(connection)

    def run_dates(self, connection, days):
        requested = sorted(set(days))
        # Each rebuilt month is owned by the last requested day inside it. The
        # grain is the month, so counting a month once keeps the checkpoints from
        # either double counting it or dividing it arbitrarily across its days.
        owners = {month_of(day): day for day in requested}
        if self.SIMULATION_START in requested:
            month = self._summary._first_month
            while month < month_of(self.SIMULATION_START):
                owners.setdefault(month, self.SIMULATION_START)
                month = next_month(month)
        _, counts = self._summary.write_months(connection, owners)
        rows = dict.fromkeys(requested, 0)
        for month, owner in owners.items():
            rows[owner] += counts.get(month, 0)
        return {day: {self.table.name: rows[day]} for day in requested}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyMonthlyAdtFacts,)
