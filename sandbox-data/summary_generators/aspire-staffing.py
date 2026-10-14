"""Daily staffing facts: hours worked, target hours and wages per facility, role
and day, for the Staffing PPD report.

Run: python manage.py staffing_summary --regenerate
Optional: --from YYYY-MM-DD --through YYYY-MM-DD, or --date YYYY-MM-DD.

There is no timekeeping source to summarise, so this is the source: each role's
hours are its target for the day's census, moved by the habits that make real
buildings differ.

    hours = target PPD x census x (1 + building + role + weekend + day)

- building: the whole facility's habit, -6% to +10%, so some buildings run
  heavy across every role and a few run lean.
- role: this role at this facility, -10% to +12%: the over-scheduled CNA floor
  or the dietary department a hire short.
- weekend: Saturday and Sunday run lighter by department: the office
  departments, Admin & General and Nursing Admin, are mostly off (-85%: a
  manager on call), Non-Nursing a little (-5%), Direct Care barely (-4%).
- day: scheduling noise, +/-8%, so even a building on target overall has days
  over and days short.

Census is daily_payer_census_facts' closing census, the same census the report
divides by, so target hours are exactly target HPPD x census days -- less the
office departments' weekends, which are their schedule, not a shortfall.

The hourly rate is the role's base rate x the state's wage index x the
facility's own pay, 94% to 106%, rising 3% a year from 2023. On some days part of
a role's hours are agency at 1.45x: each facility and role has its own agency
habit, from almost never to about one day in seven. The office departments
never use agency: their roles are salaried staff.

Excess and short hours are measured each day: the hours over the target, or the
hours under it. Excess wages are the excess hours at that day's rate -- what the
day would have cost less staffed exactly to target. Every draw is an md5 of the
facility, role and day, so a rebuild writes the same rows.
"""
from datetime import timedelta

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from shared.staffing import OFFICE_DEPARTMENTS, ROLES
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw as _draw

def draw(seed):
    """A stable draw as a double: numeric draws carry a scale that grows with every
    multiplication, and the rate's chain of them cost 7 of the build's 8 minutes."""
    return f'({_draw(seed)})::float8'


WEEKEND = {'Admin & General': -0.85, 'Direct Care': -0.04, 'Non-Nursing': -0.05, 'Nursing Admin': -0.85}
WAGE_INDEX = {'PA': 1.10, 'FL': 1.04}
AGENCY_PREMIUM = 1.45
ANNUAL_RAISE = 0.03

FACILITY = 'fa.facility_id::text'
ROLE = FACILITY + " || ':' || r.role"
DAY = "h.facility_id::text || ':' || h.role || ':' || h.summary_date::text"
ROLE_VALUES = ', '.join(f"('{code}', '{department}', {target}::float8, {rate}::float8)"
    for code, _label, department, _group, target, rate in ROLES)
OFFICE_SQL = ', '.join(f"'{department}'" for department in OFFICE_DEPARTMENTS)
WEEKEND_SQL = 'CASE r.department ' + ' '.join(
    f"WHEN '{group}' THEN {lift}" for group, lift in WEEKEND.items()) + ' ELSE 0 END'
WAGE_SQL = 'CASE p.state ' + ' '.join(
    f"WHEN '{state}' THEN {index}" for state, index in WAGE_INDEX.items()) + ' ELSE 1.0 END'

# Only trusted temporary-table identifiers are interpolated; values stay bound.
FACTS_SQL = f"""
WITH census AS (
    SELECT f.summary_date, f.facility_id, SUM(f.closing_census) AS census
    FROM daily_payer_census_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    GROUP BY f.summary_date, f.facility_id
),
roles (role, department, target_ppd, base_rate) AS (VALUES {ROLE_VALUES}),
-- Each facility and role's habits, drawn once for its 5,566 pairs. Materialized:
-- inlined, the planner substitutes every draw into the join and runs it on each
-- of 3.8M rows, which measured 381 s against 184 s.
habits AS MATERIALIZED (
    SELECT fa.facility_id, r.role, r.target_ppd,
        {WEEKEND_SQL} AS weekend, r.department IN ({OFFICE_SQL}) AS office,
        (-0.06 + 0.16 * {draw("'staff-building:' || " + FACILITY)})
            + (-0.10 + 0.22 * {draw("'staff-role:' || " + ROLE)}) AS bias,
        r.base_rate * {WAGE_SQL} * (0.94 + 0.12 * {draw("'staff-pay:' || " + ROLE)}) AS pay,
        -- Squared, so most facilities rarely use agency; never the office departments.
        CASE WHEN r.department IN ({OFFICE_SQL}) THEN 0
            ELSE 0.15 * power({draw("'staff-agency-habit:' || " + ROLE)}, 2) END AS agency_share
    FROM facilities fa
    JOIN regions g ON g.region_id = fa.region_id
    JOIN portfolios p ON p.portfolio_id = g.portfolio_id
    CROSS JOIN roles r
),
-- An office role's weekend is its schedule, not a shortfall, so its budget
-- drops with it; every other role keeps a full weekend budget and works under it.
targets AS (
    SELECT c.summary_date, c.facility_id, h.role, h.bias, h.pay, h.agency_share,
        h.target_ppd * c.census * CASE WHEN extract(isodow FROM c.summary_date) >= 6 AND h.office
            THEN 1 + h.weekend ELSE 1 END AS day_target,
        CASE WHEN extract(isodow FROM c.summary_date) >= 6 AND NOT h.office THEN h.weekend ELSE 0 END AS weekend
    FROM census c
    JOIN habits h ON h.facility_id = c.facility_id
    WHERE c.census > 0
),
shaped AS (
    SELECT h.summary_date, h.facility_id, h.role,
        round(h.day_target::numeric, 1) AS target_hours,
        greatest(0, round((h.day_target * (1 + h.bias + h.weekend
            + (-0.08 + 0.16 * {draw("'staff-day:' || " + DAY)})))::numeric, 1)) AS hours,
        round((h.pay * (1 + {ANNUAL_RAISE} * (h.summary_date - DATE '2023-01-01') / 365.0)
            * CASE WHEN {draw("'staff-agency:' || " + DAY)} < h.agency_share
                THEN {AGENCY_PREMIUM} ELSE 1 END)::numeric, 4) AS rate
    FROM targets h
)
INSERT INTO __STAGE__ (summary_date, facility_id, role, hours_worked, target_hours, excess_hours,
    short_hours, wages, excess_wages)
SELECT summary_date, facility_id, role, hours, target_hours,
    greatest(hours - target_hours, 0), greatest(target_hours - hours, 0),
    round(hours * rate, 2), round(greatest(hours - target_hours, 0) * rate, 2)
FROM shaped
"""


class StaffingSummaryGenerator(BaseGenerator):
    name = 'staffing_summary'
    table = schema.daily_staffing_facts
    depends_on = ('net_change_summary',)
    transaction_isolation = 'REPEATABLE READ'

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        if self.progress:
            self.progress.set_phase('Read census days')
        # The census the targets are set against: whatever net change has built.
        self._end = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'net_change_summary'))
        if self._end is None:
            raise ValueError('Daily payer census facts are missing. Run net_change_summary first.')
        self._start = self.SIMULATION_START

    def generate(self):
        raise ValueError('Staffing facts are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        days = sorted(set(days))
        if not days:
            return GenerationResult(0, 0), {}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(days):,} dates')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _staffing_fact_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=days))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _staffing_fact_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _staffing_fact_dates')

        if self.progress:
            self.progress.set_phase('Staff each facility', details=f'{len(days):,} dates; one census scan')
        stage = self.create_stage(connection, self.table)
        statement = FACTS_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_staffing_fact_dates')
        generated = connection.exec_driver_sql(statement).rowcount

        per_day = {day: 0 for day in days}
        counted = connection.exec_driver_sql(sql.SQL(
            'SELECT summary_date, COUNT(*) FROM {} GROUP BY summary_date')
            .format(sql.Identifier(stage)).as_string(driver)).all()
        for day, count in counted:
            per_day[day] = count

        # Delete first, while the keys still exist, then drop them for a bulk
        # insert, as the admission facts do.
        if self.progress:
            self.progress.set_phase('Remove previous facts', details=f'{len(days):,} selected dates')
        if replace_all:
            removed = connection.execute(self.table.delete()).rowcount
        else:
            removed = connection.exec_driver_sql('''
                DELETE FROM daily_staffing_facts f USING _staffing_fact_dates d
                WHERE f.summary_date = d.summary_date
            ''').rowcount
        suspended = None
        if replace_all or self.replaces_most_rows(connection, self.table, generated):
            suspended = self.suspend_indexes(connection, self.table)
        columns = sql.SQL(', ').join(map(sql.Identifier, self.table.c.keys()))
        if self.progress:
            self.progress.set_phase('Insert facts', details=f'{generated:,} rows; atomic replacement')
        # In date order, so a range reads its own days' pages: stored in rebuild
        # order, 30 days of agency facts read 166,850 pages, 1.1 s cold; in date order 2,736.
        inserted = connection.exec_driver_sql(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {} ORDER BY 1, 2')
            .format(self._table_identifier(self.table), columns, columns, sql.Identifier(stage))
            .as_string(driver)).rowcount
        if inserted != generated:
            raise ValueError('Published fact row count did not match staging.')
        if suspended is not None:
            if self.progress:
                self.progress.set_phase('Rebuild keys', details=f'{inserted:,} published rows')
            self.restore_indexes(connection, self.table, suspended)
        for temporary in (stage, '_staffing_fact_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}')
                .format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        days = [self._start + timedelta(days=offset) for offset in range((self._end - self._start).days + 1)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (StaffingSummaryGenerator,)


class DailyStaffingSummary(DailyGenerator):
    name = 'staffing_summary'
    table = schema.daily_staffing_facts
    owned_tables = (table,)
    depends_on = ('net_change_summary',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._summary = StaffingSummaryGenerator(self.database_url)
        self._summary.progress = self.progress

    def run_dates(self, connection, days):
        _, counts = self._summary.write_dates(connection, days)
        return {day: {self.table.name: counts[day]} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyStaffingSummary,)
