"""Calendar-month staffing cost facts: every measure the Staffing Overview and PPD
reports read, per facility, role and month, rolled up in PostgreSQL.

Run: python manage.py staffing_cost_summary --regenerate
Also kept up by every update, after the facts it reads.

A year of the Overview read three daily tables of 7.7M rows each -- staffing,
overtime and agency -- and the service took 5.8 s. A period now reads its whole
months here, 23 roles x 253 facilities a month, and only the days at its edges
from the daily tables (rollup_plan in the API).

Rolled up from the daily fact tables, as the monthly ADT facts are, so a month
here and the same days read daily cannot disagree: hours, targets and wages from
daily_staffing_facts; overtime from daily_overtime_facts, whose hours on paid
holidays (shared/holidays.py) that were not overtime are the holiday hours;
agency and in-house hours and pay from daily_agency_facts; hires, classroom
and floor orientation, and bonuses from daily_onboarding_facts; in-service training from
daily_training_facts. Flows only, no balance, so a month is
the sum of its own days and only months with changed days are rebuilt.
"""
from datetime import date, timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from shared.holidays import holidays
from base import BaseGenerator, DailyGenerator, GenerationResult

# Only trusted temporary-table identifiers are interpolated; values stay bound.
# Each source is summed by month on its own, on a date range so its primary key
# serves, then the four are joined on (month, facility, role): the overtime and
# agency rows exist only where a role worked, and hires only on hiring days.
COST_SQL = """
WITH months AS (SELECT month_start, (month_start + INTERVAL '1 month')::date AS month_end FROM __MONTHS__),
staffing AS (
    SELECT m.month_start, f.facility_id, f.role,
        SUM(f.hours_worked) AS hours_worked, SUM(f.target_hours) AS target_hours,
        SUM(f.excess_hours) AS excess_hours, SUM(f.wages) AS wages, SUM(f.excess_wages) AS excess_wages
    FROM months m
    JOIN daily_staffing_facts f ON f.summary_date >= m.month_start AND f.summary_date < m.month_end
    GROUP BY m.month_start, f.facility_id, f.role
),
overtime AS (
    SELECT m.month_start, f.facility_id, f.role,
        SUM(f.overtime_hours) AS overtime_hours, SUM(f.overtime_wages) AS overtime_wages,
        SUM(f.hours_worked - f.overtime_hours) FILTER (WHERE f.summary_date = ANY(%(holidays)s::date[])) AS holiday_hours,
        SUM(f.wages - f.overtime_wages) FILTER (WHERE f.summary_date = ANY(%(holidays)s::date[])) AS holiday_wages
    FROM months m
    JOIN daily_overtime_facts f ON f.summary_date >= m.month_start AND f.summary_date < m.month_end
    GROUP BY m.month_start, f.facility_id, f.role
),
agency AS (
    SELECT m.month_start, f.facility_id, f.role,
        SUM(f.agency_hours) AS agency_hours, SUM(f.agency_wages) AS agency_wages,
        SUM(f.inhouse_hours) AS inhouse_hours, SUM(f.inhouse_wages) AS inhouse_wages
    FROM months m
    JOIN daily_agency_facts f ON f.summary_date >= m.month_start AND f.summary_date < m.month_end
    GROUP BY m.month_start, f.facility_id, f.role
),
onboarding AS (
    SELECT m.month_start, f.facility_id, f.role,
        SUM(f.new_hires) AS new_hires, SUM(f.bonuses) AS bonuses,
        SUM(f.classroom_orientation_hours) AS classroom_orientation_hours,
        SUM(f.classroom_orientation_wages) AS classroom_orientation_wages,
        SUM(f.floor_orientation_hours) AS floor_orientation_hours,
        SUM(f.floor_orientation_wages) AS floor_orientation_wages,
        SUM(f.classroom_orientation_days) AS classroom_orientation_days,
        SUM(f.floor_orientation_days) AS floor_orientation_days
    FROM months m
    JOIN daily_onboarding_facts f ON f.summary_date >= m.month_start AND f.summary_date < m.month_end
    GROUP BY m.month_start, f.facility_id, f.role
),
training AS (
    SELECT m.month_start, f.facility_id, f.role,
        SUM(f.training_hours) AS training_hours, SUM(f.training_wages) AS training_wages
    FROM months m
    JOIN daily_training_facts f ON f.summary_date >= m.month_start AND f.summary_date < m.month_end
    GROUP BY m.month_start, f.facility_id, f.role
)
INSERT INTO __STAGE__ (month_start, facility_id, role, hours_worked, target_hours, excess_hours, wages,
    excess_wages, overtime_hours, overtime_wages, holiday_hours, holiday_wages, agency_hours, agency_wages,
    inhouse_hours, inhouse_wages, new_hires, bonuses, training_hours, training_wages,
    classroom_orientation_hours, classroom_orientation_wages, floor_orientation_hours, floor_orientation_wages,
    classroom_orientation_days, floor_orientation_days)
SELECT s.month_start, s.facility_id, s.role, s.hours_worked, s.target_hours, s.excess_hours, s.wages,
    s.excess_wages, COALESCE(o.overtime_hours, 0), COALESCE(o.overtime_wages, 0),
    COALESCE(o.holiday_hours, 0), COALESCE(o.holiday_wages, 0),
    COALESCE(a.agency_hours, 0), COALESCE(a.agency_wages, 0), COALESCE(a.inhouse_hours, 0),
    COALESCE(a.inhouse_wages, 0), COALESCE(h.new_hires, 0), COALESCE(h.bonuses, 0),
    COALESCE(t.training_hours, 0), COALESCE(t.training_wages, 0),
    COALESCE(h.classroom_orientation_hours, 0), COALESCE(h.classroom_orientation_wages, 0),
    COALESCE(h.floor_orientation_hours, 0), COALESCE(h.floor_orientation_wages, 0),
    COALESCE(h.classroom_orientation_days, 0), COALESCE(h.floor_orientation_days, 0)
FROM staffing s
LEFT JOIN overtime o USING (month_start, facility_id, role)
LEFT JOIN agency a USING (month_start, facility_id, role)
LEFT JOIN onboarding h USING (month_start, facility_id, role)
LEFT JOIN training t USING (month_start, facility_id, role)
"""


def month_of(day):
    return day.replace(day=1)


def next_month(month):
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


class StaffingCostSummaryGenerator(BaseGenerator):
    name = 'staffing_cost_summary'
    table = schema.monthly_staffing_cost_facts
    depends_on = ('staffing_summary', 'overtime_summary', 'agency_summary', 'onboarding_summary', 'training_summary')
    transaction_isolation = 'REPEATABLE READ'

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        last = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'staffing_summary'))
        if last is None:
            raise ValueError('Daily staffing facts are missing. Run staffing_summary first.')
        self._first_month = month_of(self.SIMULATION_START)
        self._last_month = month_of(last)

    def generate(self):
        raise ValueError('Monthly staffing cost facts are built directly with INSERT ... SELECT.')

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
            CREATE TEMP TABLE _staffing_cost_months ON COMMIT DROP AS
            SELECT unnest(%(months)s::date[]) AS month_start
        ''', dict(months=months))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _staffing_cost_months (month_start)')
        connection.exec_driver_sql('ANALYZE _staffing_cost_months')
        if self.progress:
            self.progress.set_phase('Roll up each facility, role and month', details=f'{len(months):,} months')
        stage = self.create_stage(connection, self.table)
        statement = COST_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__MONTHS__', '_staffing_cost_months')
        days_off = holidays(months[0], next_month(months[-1]) - timedelta(days=1))
        generated = connection.exec_driver_sql(statement, dict(holidays=days_off)).rowcount
        per_month = {month: 0 for month in months}
        for month, count in connection.exec_driver_sql(sql.SQL(
                'SELECT month_start, COUNT(*) FROM {} GROUP BY month_start')
                .format(sql.Identifier(stage)).as_string(driver)).all():
            per_month[month] = count
        if self.progress:
            self.progress.set_phase('Remove previous facts', details=f'{len(months):,} selected months')
        if replace_all:
            removed = connection.execute(self.table.delete()).rowcount
        else:
            removed = connection.exec_driver_sql('''
                DELETE FROM monthly_staffing_cost_facts f USING _staffing_cost_months m
                WHERE f.month_start = m.month_start
            ''').rowcount
        suspended = None
        if replace_all or self.replaces_most_rows(connection, self.table, generated):
            suspended = self.suspend_indexes(connection, self.table)
        columns = sql.SQL(', ').join(map(sql.Identifier, self.table.c.keys()))
        if self.progress:
            self.progress.set_phase('Insert facts', details=f'{generated:,} rows')
        # In date order, so a range reads its own days' pages: stored in rebuild
        # order, 30 days of agency facts read 166,850 pages, 1.1 s cold; in date order 2,736.
        inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {} ORDER BY 1, 2')
            .format(self._table_identifier(self.table), columns, columns, sql.Identifier(stage))
            .as_string(driver)).rowcount
        if inserted != generated:
            raise ValueError('Published row count did not match staging.')
        if suspended is not None:
            self.restore_indexes(connection, self.table, suspended)
        for temporary in (stage, '_staffing_cost_months'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_month

    def write_generated(self, connection):
        result, _ = self.write_months(connection, self.every_month(), replace_all=True)
        return result


GENERATORS = (StaffingCostSummaryGenerator,)


class DailyStaffingCostSummary(DailyGenerator):
    name = 'staffing_cost_summary'
    table = schema.monthly_staffing_cost_facts
    owned_tables = (table,)
    depends_on = ('staffing_summary', 'overtime_summary', 'agency_summary', 'onboarding_summary', 'training_summary')
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = StaffingCostSummaryGenerator(self.database_url)
        self._summary.progress = self.progress
        self._summary.prepare_sources(connection)

    def run_dates(self, connection, days):
        requested = sorted(set(days))
        # Each rebuilt month is owned by the last requested day inside it, so a
        # month's rows are counted once in the checkpoints.
        owners = {month_of(day): day for day in requested}
        _, counts = self._summary.write_months(connection, owners)
        rows = dict.fromkeys(requested, 0)
        for month, owner in owners.items():
            rows[owner] += counts.get(month, 0)
        return {day: {self.table.name: rows[day]} for day in requested}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyStaffingCostSummary,)
