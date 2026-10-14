"""Each facility's day across every role: hours worked, target hours, closing
census and labour cost, one row per facility and day, for the HPPD and PPD
cost trends.

Run: python manage.py facility_staffing_summary --regenerate
Also rebuilt by every seed and update, after the staffing facts and the census.

A rollup of daily_staffing_facts over its 11 roles, with the day's closing
census from daily_payer_census_facts summed over payer types: 349,000 rows
against 3.8M and 2.5M. It exists for one measured reason: the PPD trend over
every role read a million staffing rows for a year and rolled 740,000 payer
rows up for the census, 1.5 s in the service and 3.6 s at the browser; from
this table a year is 92,000 rows. Hours and targets stay additive; census is
the facility's own and is never added across facilities' roles.

The cost columns are for the PPD cost trend, which read from the daily tables
measured 13.6 s for a year before orientation, training and bonuses. Each role's
day is priced first and then summed: the budget is its target hours at that
day's straight-time rate (the facts' wages over hours, the in-house rate), and
the agency premium its agency pay over its agency hours at that rate -- a day's
pricing of what the Staffing Overview prices over a whole range, so the trend's
premium can differ from the Overview's by cents on the dollar. Overtime pay
and, on paid holidays (shared/holidays.py), the pay for hours that were not
overtime come from daily_overtime_facts at straight time; the reader applies
their premiums. Orientation, training and sign-on bonuses come from the
onboarding and training facts.

Built whole in one INSERT ... SELECT for the requested dates, as the staffing
facts are: nothing is drawn, so a rebuild writes the same rows.
"""
from datetime import timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from shared.holidays import holidays
from base import BaseGenerator, DailyGenerator, GenerationResult

# Only trusted temporary-table identifiers are interpolated.
ROLLUP_SQL = """
WITH census AS (
    SELECT f.summary_date, f.facility_id, SUM(f.closing_census) AS closing_census
    FROM daily_payer_census_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    GROUP BY f.summary_date, f.facility_id
),
-- Each source read for the requested days on its own, then joined by role:
-- joined straight to the staffing rows, the overtime and agency tables were
-- read whole for every batch -- 32 s for a month.
overtime AS MATERIALIZED (
    SELECT o.summary_date, o.facility_id, o.role, o.overtime_wages,
        CASE WHEN o.summary_date = ANY(%(holidays)s::date[]) THEN o.wages - o.overtime_wages END AS holiday_wages
    FROM daily_overtime_facts o
    JOIN __DATES__ d ON d.summary_date = o.summary_date
),
agency AS MATERIALIZED (
    SELECT a.summary_date, a.facility_id, a.role, a.agency_wages, a.agency_hours
    FROM daily_agency_facts a
    JOIN __DATES__ d ON d.summary_date = a.summary_date
),
-- Each role's day, priced at its own straight-time rate.
roles AS (
    SELECT f.summary_date, f.facility_id, f.hours_worked, f.target_hours, f.wages,
        CASE WHEN f.hours_worked > 0 THEN f.wages / f.hours_worked END AS rate,
        o.overtime_wages, o.holiday_wages, a.agency_wages, a.agency_hours
    FROM daily_staffing_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    LEFT JOIN overtime o ON o.summary_date = f.summary_date AND o.facility_id = f.facility_id AND o.role = f.role
    LEFT JOIN agency a ON a.summary_date = f.summary_date AND a.facility_id = f.facility_id AND a.role = f.role
),
staffing AS (
    SELECT summary_date, facility_id, SUM(hours_worked) AS hours_worked, SUM(target_hours) AS target_hours,
        SUM(wages) AS wages, SUM(COALESCE(target_hours * rate, 0)) AS budget_wages,
        SUM(COALESCE(overtime_wages, 0)) AS overtime_wages, SUM(COALESCE(holiday_wages, 0)) AS holiday_wages,
        SUM(COALESCE(agency_wages - agency_hours * rate, 0)) AS agency_premium
    FROM roles
    GROUP BY summary_date, facility_id
),
onboarding AS (
    SELECT f.summary_date, f.facility_id,
        SUM(f.classroom_orientation_wages + f.floor_orientation_wages) AS orientation_wages, SUM(f.bonuses) AS bonuses
    FROM daily_onboarding_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    GROUP BY f.summary_date, f.facility_id
),
training AS (
    SELECT f.summary_date, f.facility_id, SUM(f.training_wages) AS training_wages
    FROM daily_training_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    GROUP BY f.summary_date, f.facility_id
)
INSERT INTO __STAGE__ (summary_date, facility_id, hours_worked, target_hours, closing_census, wages, budget_wages,
    overtime_wages, holiday_wages, agency_premium, orientation_wages, training_wages, bonuses)
SELECT c.summary_date, c.facility_id, COALESCE(s.hours_worked, 0), COALESCE(s.target_hours, 0), c.closing_census,
    round(COALESCE(s.wages, 0), 2), round(COALESCE(s.budget_wages, 0), 2), round(COALESCE(s.overtime_wages, 0), 2),
    round(COALESCE(s.holiday_wages, 0), 2), round(COALESCE(s.agency_premium, 0), 2),
    round(COALESCE(b.orientation_wages, 0), 2), round(COALESCE(t.training_wages, 0), 2), round(COALESCE(b.bonuses, 0), 2)
FROM census c
LEFT JOIN staffing s ON s.summary_date = c.summary_date AND s.facility_id = c.facility_id
LEFT JOIN onboarding b ON b.summary_date = c.summary_date AND b.facility_id = c.facility_id
LEFT JOIN training t ON t.summary_date = c.summary_date AND t.facility_id = c.facility_id
"""


class FacilityStaffingSummaryGenerator(BaseGenerator):
    name = 'facility_staffing_summary'
    table = schema.daily_facility_staffing_facts
    depends_on = ('staffing_summary', 'net_change_summary', 'overtime_summary', 'agency_summary',
        'onboarding_summary', 'training_summary')
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
        generated = connection.exec_driver_sql(statement, dict(holidays=holidays(days[0], days[-1]))).rowcount
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
        # In date order, so a range reads its own days' pages: stored in rebuild
        # order, 30 days of agency facts read 166,850 pages, 1.1 s cold; in date order 2,736.
        inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {} ORDER BY 1, 2')
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
    depends_on = ('staffing_summary', 'net_change_summary', 'overtime_summary', 'agency_summary',
        'onboarding_summary', 'training_summary')
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
