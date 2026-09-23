"""Calendar-month hospital referral facts, rolled up in PostgreSQL.

Run: python manage.py referrals_summary --regenerate
Optional: --from YYYY-MM-DD --through YYYY-MM-DD, or --date YYYY-MM-DD.

Feeds the referring hospital report, which reads 36 complete months for every
hospital on every load.

Rolled up from daily_admission_facts rather than rebuilt from admission_logs.
monthly_adt_summary reads its source instead because rolling up its daily table
would have required an eight-minute rebuild of that table first; here the daily
facts are built earlier in the same run by admissions_summary, and the whole
rollup costs about 300ms. Reading the rows the admissions report reads also
means the two can never disagree about a hospital's admissions.

Flows only -- no census and no running balance -- so a month is the sum of its
own days and only the months containing changed days need rebuilding. That is
what separates this from net_change_summary and monthly_adt_summary, both of
which must recompute from the first affected row onward.
"""
from datetime import date

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

# Only trusted temporary-table identifiers are interpolated; values stay bound.
# Joining each month on a date range rather than on date_trunc(summary_date)
# keeps the daily table's primary key usable, so rebuilding one month reads one
# month instead of scanning four years.
REFERRALS_SQL = """
INSERT INTO __STAGE__ (month_start, hospital, facility_id, payer_type,
    admissions, readmissions, readmissions_30_day)
SELECT m.month_start, f.source_name, f.facility_id, p.payer_type,
       SUM(f.admissions), SUM(f.readmissions), SUM(f.readmissions_30_day)
FROM __MONTHS__ m
JOIN daily_admission_facts f
  ON f.summary_date >= m.month_start
 AND f.summary_date < m.month_start + INTERVAL '1 month'
JOIN payers p ON p.payer_id = f.payer_id
WHERE f.source_type = 'Hospital'
GROUP BY m.month_start, f.source_name, f.facility_id, p.payer_type
"""


def month_of(day):
    return day.replace(day=1)


def next_month(month):
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


class ReferralsSummaryGenerator(BaseGenerator):
    name = 'referrals_summary'
    table = schema.monthly_referral_facts
    depends_on = ('admissions_summary',)
    transaction_isolation = 'REPEATABLE READ'

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        if self.progress:
            self.progress.set_phase('Check referring hospitals')
        facts, hospitals = schema.daily_admission_facts, self.referring_hospitals
        # The foreign key would catch this on insert; naming the hospital and the
        # command that fixes it is worth one indexed lookup.
        unknown = connection.scalar(select(facts.c.source_name).where(
            facts.c.source_type == 'Hospital',
            ~select(hospitals.c.hospital).where(
                hospitals.c.hospital == facts.c.source_name).exists()).limit(1))
        if unknown is not None:
            raise ValueError(f'Admission facts refer to {unknown!r}, which is not a saved '
                'referring hospital. Run referring_hospitals before summarizing referrals.')
        if self.progress:
            self.progress.set_phase('Read summary date range')
        first, last = connection.execute(select(
            func.min(facts.c.summary_date), func.max(facts.c.summary_date))).one()
        # Opening admissions keep their late-2022 dates, so the first month is the
        # daily table's own first month rather than the simulation start.
        self._first_month = month_of(first) if first else month_of(self.SIMULATION_START)
        self._last_month = month_of(last) if last else self._first_month

    def generate(self):
        raise ValueError('Referral facts are built directly with INSERT ... SELECT.')

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
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare months', details=f'{len(months):,} months')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _referral_months ON COMMIT DROP AS
            SELECT unnest(%(months)s::date[]) AS month_start
        ''', dict(months=months))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _referral_months (month_start)')
        connection.exec_driver_sql('ANALYZE _referral_months')

        if self.progress:
            self.progress.set_phase('Roll up referrals',
                details=f'{len(months):,} months; one pass over the daily facts')
        stage = self.create_stage(connection, self.table)
        statement = REFERRALS_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__MONTHS__', '_referral_months')
        generated = connection.exec_driver_sql(statement).rowcount

        if self.progress:
            self.progress.set_phase('Count facts per month', details=f'{generated:,} rows staged')
        per_month = {month: 0 for month in months}
        for month, count in connection.exec_driver_sql(sql.SQL(
                'SELECT month_start, COUNT(*) FROM {} GROUP BY month_start')
                .format(sql.Identifier(stage)).as_string(driver)).all():
            per_month[month] = count

        # Replace the selected months in the transaction that publishes them.
        # Delete first, while the keys still exist: month_start leads the primary
        # key, so the predicate never scans the whole table.
        if self.progress:
            self.progress.set_phase('Remove previous facts', details=f'{len(months):,} selected months')
        if replace_all:
            removed = connection.execute(self.table.delete()).rowcount
        else:
            removed = connection.exec_driver_sql('''
                DELETE FROM monthly_referral_facts f USING _referral_months m
                WHERE f.month_start = m.month_start
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
        for temporary in (stage, '_referral_months'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}')
                .format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_month

    def write_generated(self, connection):
        result, _ = self.write_months(connection, self.every_month(), replace_all=True)
        return result


GENERATORS = (ReferralsSummaryGenerator,)


class DailyReferralsSummary(DailyGenerator):
    name = 'referrals_summary'
    table = schema.monthly_referral_facts
    owned_tables = (table,)
    # The daily facts, not the simulation: this reads what admissions_summary
    # wrote, so it must not run for a day before that day's facts exist.
    depends_on = ('admissions_summary',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = ReferralsSummaryGenerator(self.database_url)
        self._summary.progress = self.progress
        self._summary.prepare_sources(connection)

    def run_dates(self, connection, days):
        requested = sorted(set(days))
        # Each rebuilt month is owned by the last requested day inside it. The grain
        # is the month, so counting a month once keeps the checkpoints from either
        # double counting it or dividing it arbitrarily across its days.
        owners = {month_of(day): day for day in requested}
        if self.SIMULATION_START in requested:
            # Opening admissions keep their late-2022 dates and belong to the first
            # simulation checkpoint, so their months roll up with it.
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


DAILY_GENERATORS = (DailyReferralsSummary,)
