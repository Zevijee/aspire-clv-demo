"""Staff: each facility's roster, and who worked how many hours each day.

Run: python manage.py staff_members --regenerate   # the roster, ~1 s
     python manage.py staff_hours --regenerate     # the last 120 days of hours

daily_staffing_facts says how many hours each role worked at each facility each
day, and nothing says who. These two tables say who, for the Staffing PPD
report's Employees tab, without changing a single hour: a day's hours for a
role are split across the roster members drawn to be working, so an employee's
hours add up to the role's, and the role's to the facility's.

The roster (staff_members) is reference data, built from the facilities alone.
Each facility and role gets as many people as its beds need: the role's target
PPD times the beds, at 88% occupancy, is the day's hours; eight hours a shift
gives the shifts a day; and 1.8 people per daily shift covers days off, since a
roster is 55% full time, 25% part time, 12% PRN and 8% agency. Everyone has a
name, a hire date -- most before 2023, the rest since -- and an hourly rate: the
role's base rate at the facility's pay, as the facts price it, moved up to 15%
by tenure. Agency people bill AGENCY_PREMIUM times the base pay instead and earn
no tenure: a contract, not a career. Wages are split by rate, so on a day an
agency person works they take the premium share of the day's wages and the
in-house staff a little less, and the day still adds up to the facts; the
Agency vs In-house report reads the difference as what agency cost over
in-house.

The hours (daily_staff_hours) are one row per person per day worked. On each
day a roster member is drawn to work by their employment type's habit (see
shared/staffing.py), scaled by how heavy the day is against target, and at
least one person always works a day with hours. The role's hours are split by
each worker's shift weight -- full-timers a little longer than part-timers,
everyone +/-20% -- so shifts come out around eight hours; wages are split by
the same weights at each person's rate, so a day's wages add up too, to the
cent on each side but for rounding.

Each row also carries its overtime: the person's hours over WEEKLY_HOURS in
their week (Monday to Sunday), spread over the days they worked that week in
proportion to each day's hours. A week's overtime is the sum of its days', so
the Overtime report reads sums at any grain instead of grouping every row by
person and week, which measured 8 s for 120 days. Spread, not placed on the
day the person crossed the line: nobody reaches 40 hours before Friday, so
placed that way every week's overtime fell on its last shifts -- 70% of a
Sunday's hours, zero Monday to Thursday -- which is true of a pay week and
useless on a chart; spread, each day runs 5-10%. A day added to a week in
progress moves the week's other days' share, so those are set again after it
is written.

Only the last 120 days are kept: at some 20,000 shifts a day over 253
facilities, the whole history would be ten times the largest table, on a
server where disk is the limit. Each update adds the new days and drops the
ones that fell out of the window; a checkpoint's count is that day's rows,
zero for a day before the window. Every draw is an md5 of the person and the
day, so a rebuild writes the same rows.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from random import Random

from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from shared.staffing import EMPLOYMENT_TYPES, ROLES, WEEKLY_HOURS
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw

SEED = 42
HOURS_DAYS = 120
SHIFT_HOURS = 8
OCCUPANCY = 0.88
MIN_ROSTER = 2
# Share of a roster by employment type, in EMPLOYMENT_TYPES order.
TYPE_MIX = (0.55, 0.25, 0.12, 0.08)
# The same pay the facts use: the state's wage index and the facility's own pay.
WAGE_INDEX = {'PA': 1.10, 'FL': 1.04}
FACILITY_PAY_RANGE = (0.94, 0.12)
TENURE_LIFT_PER_YEAR, TENURE_LIFT_MAX = 0.012, 0.15
# What an agency hour bills against the role's base pay. Wages are split by rate
# among the people who worked a day, so this is diluted on the way to the report:
# with in-house rates lifted ~7% by tenure and six or so people a day, agency
# reads about 1.75x in-house (measured: 1.45 here gave 1.28x; 1.9 gives ~1.75x),
# which is where agency bill rates sit against staff wages.
AGENCY_PREMIUM = 1.9
HIRED_BEFORE_HISTORY = 0.55
EARLIEST_HIRE = date(2012, 1, 1)
# A worker's shift against the roster's average, by employment type, before
# the +/-20% of the day.
SHIFT_WEIGHT = {'full_time': 1.0, 'part_time': 0.85, 'prn': 0.9, 'agency': 1.0}
CENTS = Decimal('0.01')


def sql_draw(seed):
    """What draws.draw(seed) gives in SQL, for the same seed, in Python."""
    return int(hashlib.md5(seed.encode()).hexdigest()[:8], 16) / 4294967296.0


class StaffMembersGenerator(BaseGenerator):
    name = 'staff_members'
    table = schema.staff_members
    depends_on = ('facilities',)

    def prepare_sources(self, connection):
        self._facilities = self.read_rows(connection, select(
            self.facilities.c.facility_id, self.facilities.c.beds, self.portfolios.c.state)
            .select_from(self.facilities.join(self.regions).join(self.portfolios))
            .order_by(self.facilities.c.facility_id))
        self._through = self.today()
        # Each roster is filled until its members' chances of working add up to
        # the shifts the role needs a day, so whatever mix of full-time, PRN and
        # agency people it draws, as many turn up on an average day as there are
        # shifts, and a shift comes out near SHIFT_HOURS. Never fewer than two:
        # a day with hours always has someone, and one person would never rest.
        chances = {code: chance for code, _label, chance in EMPLOYMENT_TYPES}
        latest_hire = self._through - timedelta(days=30)
        # Someone hired inside the hours window covers only part of it: the
        # roster is filled by the people who were there for all of it.
        window_start = self._through - timedelta(days=HOURS_DAYS)
        history_days = (latest_hire - self.SIMULATION_START).days
        self._people = []
        for facility in self._facilities:
            facility_id = str(facility['facility_id'])
            for code, _label, _group, target, base_rate in ROLES:
                shifts = target * facility['beds'] * OCCUPANCY / SHIFT_HOURS
                covered, number = 0.0, 0
                while number < MIN_ROSTER or covered < shifts:
                    rng = Random(self.source_id('staff-member', SEED, facility_id, code, number).int)
                    kind = rng.choices([kind for kind, *_ in EMPLOYMENT_TYPES], TYPE_MIX)[0]
                    # A roster's first two members have tenure: a small roster
                    # whose other member was hired last month would leave one
                    # person covering every day until then.
                    if number < MIN_ROSTER or rng.random() < HIRED_BEFORE_HISTORY:
                        hired = EARLIEST_HIRE + timedelta(days=rng.randrange(
                            (self.SIMULATION_START - EARLIEST_HIRE).days))
                    else:
                        hired = self.SIMULATION_START + timedelta(days=rng.randrange(history_days))
                    self._people.append((facility, code, base_rate, number, kind, hired, rng))
                    if hired <= window_start:
                        covered += chances[kind]
                    number += 1

    def expected_rows(self):
        return len(self._people)

    def write_generated(self, connection):
        # Ids are roster positions, so a roster that shrinks would leave people
        # behind under an upsert: the table is replaced whole, and the hours
        # built on it go with it, to be rebuilt by staff_hours.
        if self.progress:
            self.progress.set_phase('Remove the previous roster and its hours')
        connection.execute(schema.daily_staff_hours.delete())
        connection.execute(self.table.delete())
        return super().write_generated(connection)

    def generate(self):
        names = self.random_names(self.expected_rows(), seed=SEED + 7)
        latest_hire = self._through - timedelta(days=30)
        for facility, code, base_rate, number, kind, hired, rng in self._people:
            facility_id = str(facility['facility_id'])
            pay = base_rate * WAGE_INDEX.get(facility['state'], 1.0) * (
                FACILITY_PAY_RANGE[0] + FACILITY_PAY_RANGE[1] * sql_draw(f'staff-pay:{facility_id}:{code}'))
            if True:
                tenure_years = (latest_hire - hired).days / 365.25
                lift = AGENCY_PREMIUM if kind == 'agency' else (
                    1 + min(TENURE_LIFT_MAX, TENURE_LIFT_PER_YEAR * tenure_years))
                rate = Decimal(pay * lift * rng.uniform(0.97, 1.03))
                person = next(names)
                yield dict(staff_id=self.source_id('staff-member', SEED, facility_id, code, number),
                    facility_id=facility['facility_id'], role=code, first_name=person['first_name'],
                    last_name=person['last_name'], employment_type=kind, hire_date=hired,
                    hourly_rate=rate.quantize(CENTS, ROUND_HALF_UP))


CHANCE_SQL = 'CASE s.employment_type ' + ' '.join(
    f"WHEN '{code}' THEN {chance}" for code, _label, chance in EMPLOYMENT_TYPES) + ' ELSE 0.1 END'
WEIGHT_SQL = 'CASE s.employment_type ' + ' '.join(
    f"WHEN '{code}' THEN {weight}" for code, weight in SHIFT_WEIGHT.items()) + ' ELSE 1.0 END'
PERSON_DAY = "s.staff_id::text || ':' || f.summary_date::text"

# Only trusted temporary-table identifiers are interpolated; values stay bound.
HOURS_SQL = f"""
WITH facts AS (
    SELECT f.summary_date, f.facility_id, f.role, f.hours_worked, f.target_hours, f.wages
    FROM daily_staffing_facts f
    JOIN __DATES__ d ON d.summary_date = f.summary_date
    WHERE f.hours_worked > 0
),
candidates AS (
    -- Everyone on the role's roster, with their draw to work: the type's
    -- habit, scaled by how heavy the day is against target, so a light Sunday
    -- has fewer people in rather than everyone in for less. Only those hired
    -- by then are drawn; the rest stand last in line.
    SELECT f.summary_date, f.facility_id, f.role, f.hours_worked, f.wages, s.staff_id, s.hourly_rate,
        s.hire_date <= f.summary_date AS hired,
        {draw("'staff-works:' || " + PERSON_DAY)} AS works,
        ({CHANCE_SQL}) * least(1.3, f.hours_worked / greatest(f.target_hours, 1)) AS chance,
        ({WEIGHT_SQL}) * (0.8 + 0.4 * {draw("'staff-shift:' || " + PERSON_DAY)}) AS weight
    FROM facts f
    JOIN staff_members s ON s.facility_id = f.facility_id AND s.role = f.role
),
ranked AS (
    SELECT c.*, row_number() OVER (PARTITION BY c.summary_date, c.facility_id, c.role
        ORDER BY c.hired DESC, c.works - c.chance, c.staff_id) AS rank
    FROM candidates c
),
working AS (
    -- Drawn to work, and at least the likeliest one: a day with hours has
    -- someone, even where a one-person roster's only member was hired later.
    SELECT * FROM ranked WHERE (works < chance AND hired) OR rank = 1
),
shares AS (
    SELECT w.*, w.weight / sum(w.weight) OVER day AS share,
        (w.weight * w.hourly_rate) / sum(w.weight * w.hourly_rate) OVER day AS pay_share
    FROM working w
    WINDOW day AS (PARTITION BY w.summary_date, w.facility_id, w.role)
)
INSERT INTO __STAGE__ (work_date, staff_id, facility_id, role, hours, wages, overtime_hours)
SELECT summary_date, staff_id, facility_id, role,
    greatest(0.01, round((hours_worked * share)::numeric, 2)), round((wages * pay_share)::numeric, 2),
    -- Set once the rows are in the table, over whole weeks (OVERTIME_SQL).
    0
FROM shares
"""


# Each day's share of the person's overtime for the week, Monday to Sunday:
# the week's hours over the line, spread over its days by hours.
OVERTIME_EXPR = f"round((greatest(total - {WEEKLY_HOURS}, 0) * hours / total)::numeric, 2)"
WEEK_TOTAL = "sum(hours) OVER (PARTITION BY staff_id, date_trunc('week', work_date))"

# The staged rows into the table with their overtime, from a window over the
# staged rows and the table's own rows in the weeks they touch: a whole build
# stages every row and the table is empty, so this is one sort of the stage
# and no join at all -- an UPDATE joining the rows back after the insert, with
# the keys suspended, joined 2.5M rows against 2.5M and crawled for ten
# minutes; by the week it was no better. A daily run stages a day or two and
# reads back the rest of their weeks, a few hundred thousand rows by date.
INSERT_SQL = f"""
INSERT INTO daily_staff_hours (work_date, staff_id, facility_id, role, hours, wages, overtime_hours)
SELECT work_date, staff_id, facility_id, role, hours, wages, {OVERTIME_EXPR}
FROM (
    SELECT r.*, {WEEK_TOTAL} AS total
    FROM (
        SELECT work_date, staff_id, facility_id, role, hours, wages, true AS staged FROM __STAGE__
        UNION ALL
        SELECT work_date, staff_id, facility_id, role, hours, wages, false
        FROM daily_staff_hours
        WHERE work_date >= %(week_start)s::date AND work_date < %(week_end)s::date
    ) r
) w
WHERE staged
"""

# A day written into a week already in the table moves the share of that
# week's other days: set those again, from the week's rows. Only rows the
# write did not cover are targets, and only when there are any -- a whole
# build writes every day, so there are none and this never runs. It must
# never run over the whole window: joined back against 2.5M unindexed rows
# it crawled for ten minutes, on three attempts. A daily run touches a week
# or two of rows, through the keys.
OTHER_ROWS_SQL = """
SELECT count(*) FROM daily_staff_hours
WHERE work_date >= %(week_start)s::date AND work_date < %(week_end)s::date AND work_date <> ALL(%(days)s::date[])
"""
OVERTIME_SQL = f"""
WITH weeks AS (
    SELECT work_date, staff_id, hours, {WEEK_TOTAL} AS total
    FROM daily_staff_hours
    WHERE work_date >= %(week_start)s::date AND work_date < %(week_end)s::date
),
overtime AS (
    SELECT work_date, staff_id, {OVERTIME_EXPR} AS hours FROM weeks
    WHERE work_date <> ALL(%(days)s::date[])
)
UPDATE daily_staff_hours h
SET overtime_hours = o.hours
FROM overtime o
WHERE h.work_date = o.work_date AND h.staff_id = o.staff_id
  AND h.work_date >= %(week_start)s::date AND h.work_date < %(week_end)s::date
  AND h.overtime_hours IS DISTINCT FROM o.hours
"""


class StaffHoursGenerator(BaseGenerator):
    name = 'staff_hours'
    table = schema.daily_staff_hours
    depends_on = ('staffing_summary', 'staff_members')
    transaction_isolation = 'REPEATABLE READ'

    def can_reuse(self, connection, counts):
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        return recorded is not None and recorded == counts

    def prepare_sources(self, connection):
        if self.progress:
            self.progress.set_phase('Read staffing days')
        self._end = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'staffing_summary'))
        if self._end is None:
            raise ValueError('Daily staffing facts are missing. Run staffing_summary first.')
        if connection.scalar(select(func.count()).select_from(schema.staff_members)) == 0:
            raise ValueError('There is no staff roster. Run staff_members first.')

    def window_start(self, connection):
        """The first day kept: the window ends on the latest staffing day."""
        end = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'staffing_summary'))
        return None if end is None else end - timedelta(days=HOURS_DAYS - 1)

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Staff hours are built directly with INSERT ... SELECT.')

    def write_dates(self, connection, days, *, replace_all=False):
        """Rows for the requested days inside the window; days before it are
        dropped and counted as zero."""
        first = self.window_start(connection)
        days = sorted(set(days))
        kept = [day for day in days if first is not None and day >= first]
        per_day = {day: 0 for day in days}
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Drop days before the window')
        removed = 0
        if replace_all:
            removed = connection.execute(self.table.delete()).rowcount
        elif first is not None:
            removed = connection.execute(self.table.delete().where(self.table.c.work_date < first)).rowcount
        if not kept:
            return GenerationResult(0, removed), per_day
        if self.progress:
            self.progress.set_phase('Prepare dates', details=f'{len(kept):,} dates in the window')
        connection.exec_driver_sql('''
            CREATE TEMP TABLE _staff_hour_dates ON COMMIT DROP AS
            SELECT unnest(%(days)s::date[]) AS summary_date
        ''', dict(days=kept))
        connection.exec_driver_sql('CREATE UNIQUE INDEX ON _staff_hour_dates (summary_date)')
        connection.exec_driver_sql('ANALYZE _staff_hour_dates')
        if self.progress:
            self.progress.set_phase('Split each day across the roster', details=f'{len(kept):,} dates')
        stage = self.create_stage(connection, self.table)
        statement = HOURS_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver))
        statement = statement.replace('__DATES__', '_staff_hour_dates')
        generated = connection.exec_driver_sql(statement).rowcount
        for day, count in connection.exec_driver_sql(sql.SQL(
                'SELECT work_date, COUNT(*) FROM {} GROUP BY work_date')
                .format(sql.Identifier(stage)).as_string(driver)).all():
            per_day[day] = count
        if not replace_all:
            if self.progress:
                self.progress.set_phase('Remove previous rows', details=f'{len(kept):,} selected dates')
            removed += connection.exec_driver_sql('''
                DELETE FROM daily_staff_hours h USING _staff_hour_dates d WHERE h.work_date = d.summary_date
            ''').rowcount
        suspended = None
        if replace_all or self.replaces_most_rows(connection, self.table, generated):
            suspended = self.suspend_indexes(connection, self.table)
        # The weeks the written days touch, Monday to the Sunday after the last.
        week_start = min(kept) - timedelta(days=min(kept).weekday())
        week_end = max(kept) + timedelta(days=7 - max(kept).weekday())
        weeks = dict(week_start=week_start, week_end=week_end)
        if self.progress:
            self.progress.set_phase('Insert hours with overtime', details=f'{generated:,} rows')
        # The window sorts every staged row by person and day: 2.5M rows on a
        # whole build, which the default 4 MB spills to disk many times over.
        # Local to this transaction; the server's deploy sets the same.
        connection.exec_driver_sql("SET LOCAL work_mem = '256MB'")
        inserted = connection.exec_driver_sql(
            INSERT_SQL.replace('__STAGE__', sql.Identifier(stage).as_string(driver)), weeks).rowcount
        if inserted != generated:
            raise ValueError('Published staff hour row count did not match staging.')
        others = dict(weeks, days=kept)
        if not replace_all and connection.exec_driver_sql(OTHER_ROWS_SQL, others).scalar():
            if self.progress:
                self.progress.set_phase('Set overtime on the written days\' weeks', details=f'{week_start} to {week_end}')
            connection.exec_driver_sql(OVERTIME_SQL, others)
        if suspended is not None:
            if self.progress:
                self.progress.set_phase('Rebuild keys', details=f'{inserted:,} rows')
            self.restore_indexes(connection, self.table, suspended)
        for temporary in (stage, '_staff_hour_dates'):
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(temporary)).as_string(driver))
        return GenerationResult(generated, removed + inserted), per_day

    def write_generated(self, connection):
        first = self._end - timedelta(days=HOURS_DAYS - 1)
        days = [first + timedelta(days=offset) for offset in range(HOURS_DAYS)]
        result, _ = self.write_dates(connection, days, replace_all=True)
        return result


GENERATORS = (StaffMembersGenerator, StaffHoursGenerator)


class DailyStaffHours(DailyGenerator):
    """The new days' hours, and the window moved on: a checkpoint's count is that
    day's rows, zero for a day before the window, whose rows are not kept."""
    name = 'staff_hours'
    table = schema.daily_staff_hours
    owned_tables = (table,)
    # The roster is reference data, built before any daily handler runs
    # (manage.py's reference list), so only the daily dependency is declared.
    depends_on = ('staffing_summary',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = StaffHoursGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        _, counts = self._builder.write_dates(connection, days)
        return {day: {self.table.name: counts[day]} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyStaffHours,)
