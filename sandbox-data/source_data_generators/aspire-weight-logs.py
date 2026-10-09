"""Resident weigh-ins, for Weight Surveillance.

Run: python manage.py weight_logs --regenerate
Also run by every seed and update: a full build writes every weigh-in, a daily
run only the new days' -- a weight never changes once drawn.

Residents are weighed as nursing homes weigh them: on admission, weekly for the
first four weeks (days 0, 7, 14 and 21 of the stay), then every 30 days (28, 58,
88 and on), until discharge.

Each resident has a build -- about 95 to 235 lb, most near 165 -- and each stay
comes in within 4% of it. Through the stay the weight follows a course drawn
afresh for every 180 days, so a long stay has spells of steadiness and spells of
change:

    stable   58%  within half a percent a month either way
    losing   22%  1.5 to 4.5% a month
    gaining  10%  1.5 to 3.5% a month
    acute    10%  5 to 10% lost over the first 30 days, then steady

The changes add up across spells, held between 30% below and 20% above the
admission weight, and each weigh-in is a pound and a half either side of the
course: scales and clothing. Nothing marks a significant change; the report
finds them by the MDS rule, 5% in 30 days or 10% in 180.

Every draw comes from resident and stay ids and the day of the stay, so a
rebuild gives the same weights and the days already written never move.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw

THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"
PHASE_DAYS = 180
# Weekly for the first four weeks, then every 30 days from day 28.
WEEKLY_DAYS = (0, 7, 14, 21)
MONTHLY_FROM, MONTHLY_EVERY = 28, 30
# Each spell's course: the share of spells, then the monthly change in percent
# of the admission weight, as low + draw * spread.
STABLE, LOSING, GAINING = 0.58, 0.22, 0.10  # acute takes the rest
LOSING_RATE, GAINING_RATE, ACUTE_LOSS = (-1.5, -3.0), (1.5, 2.0), (-5.0, -5.0)
# Bounds on the accumulated change, in percent of the admission weight.
LOWEST_CHANGE, HIGHEST_CHANGE = -30.0, 20.0
NOISE_POUNDS = 3.0


def weights_sql(table, days=None):
    """Every weigh-in, or with days -- a SQL date array -- only those days'.
    Either way each stay's weigh-ins are computed from admission, since a row's
    running values reach back through the whole stay; drawn, not read, so a
    daily run never reads the table."""
    stay_filter = '' if days is None else f"""
      AND (s.discharge_date IS NULL OR s.discharge_date > (SELECT min(d) FROM unnest({days}) d))
      AND s.admission_date <= (SELECT max(d) FROM unnest({days}) d)"""
    day_filter = '' if days is None else f'AND w.weighed_on = ANY({days})'
    spell = "stay_id::text || ':' || phase"
    kind = draw(spell + " || ':course'")
    rate = draw(spell + " || ':rate'")
    return f"""
WITH through AS ({THROUGH}), stays AS MATERIALIZED (
    SELECT s.stay_id, s.resident_id, s.admission_date,
           least(coalesce(s.discharge_date, (SELECT day FROM through) + 1), (SELECT day FROM through) + 1)
             - s.admission_date AS days
    FROM res_stays s
    WHERE s.admission_date <= (SELECT day FROM through){stay_filter}
), admitted AS (
    -- The resident's build, a bell from three draws, and this stay's start near it.
    SELECT st.*,
           (95 + 140 * ({draw("resident_id::text || ':build:1'")} + {draw("resident_id::text || ':build:2'")}
                 + {draw("resident_id::text || ':build:3'")}) / 3)
             * (1 + ({draw("stay_id::text || ':admitted'")} - 0.5) * 0.08) AS admission_weight
    FROM stays st WHERE st.days > 0
), spells AS (
    SELECT stay_id, phase,
           CASE WHEN {kind} < {STABLE} THEN ({rate} - 0.5)
                WHEN {kind} < {STABLE + LOSING} THEN {LOSING_RATE[0]} + {rate} * {LOSING_RATE[1]}
                WHEN {kind} < {STABLE + LOSING + GAINING} THEN {GAINING_RATE[0]} + {rate} * {GAINING_RATE[1]}
                ELSE {ACUTE_LOSS[0]} + {rate} * {ACUTE_LOSS[1]} END AS rate,
           {kind} >= {STABLE + LOSING + GAINING} AS acute
    FROM admitted CROSS JOIN LATERAL generate_series(0, (days - 1) / {PHASE_DAYS}) AS phase
), courses AS (
    -- The change carried into each spell from those before it.
    SELECT *, coalesce(sum(CASE WHEN acute THEN rate ELSE rate * {PHASE_DAYS // 30} END) OVER (
               PARTITION BY stay_id ORDER BY phase ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS before
    FROM spells
), weighins AS (
    SELECT a.stay_id, a.admission_weight, a.admission_date + day AS weighed_on, day
    FROM admitted a CROSS JOIN LATERAL (
        SELECT unnest(ARRAY{list(WEEKLY_DAYS)}) AS day
        UNION ALL
        SELECT {MONTHLY_FROM} + {MONTHLY_EVERY} * k
        FROM generate_series(0, greatest(a.days - 1 - {MONTHLY_FROM}, -1) / {MONTHLY_EVERY}) AS k
        WHERE a.days > {MONTHLY_FROM}
    ) offsets
    WHERE day < a.days
), weighed AS (
    SELECT w.stay_id, w.weighed_on, w.day,
       round(least(400, greatest(60, w.admission_weight * (1 + greatest({LOWEST_CHANGE}, least({HIGHEST_CHANGE},
           c.before + c.rate * CASE WHEN c.acute THEN least(mod(w.day, {PHASE_DAYS}), 30)
                                    ELSE mod(w.day, {PHASE_DAYS}) END / 30.0)) / 100)
         + ({draw("w.stay_id::text || ':' || w.day || ':scale'")} - 0.5) * {NOISE_POUNDS}))::numeric, 1)
         AS weight
    FROM weighins w
    JOIN courses c ON c.stay_id = w.stay_id AND c.phase = w.day / {PHASE_DAYS}
), running AS (
    -- Each weigh-in with the stay as of it. A weight's day is days since admission.
    SELECT w.*,
           first_value(weight) OVER stay_so_far AS admission_weight,
           max(weight) OVER stay_so_far AS highest,
           min(weight) OVER stay_so_far AS lowest,
           (max(ARRAY[day, weight]) OVER (PARTITION BY stay_id ORDER BY day
               RANGE BETWEEN UNBOUNDED PRECEDING AND 30 PRECEDING))[2] AS weight_30_days_before,
           (max(ARRAY[day, weight]) OVER (PARTITION BY stay_id ORDER BY day
               RANGE BETWEEN UNBOUNDED PRECEDING AND 180 PRECEDING))[2] AS weight_180_days_before
    FROM weighed w
    WINDOW stay_so_far AS (PARTITION BY stay_id ORDER BY day ROWS UNBOUNDED PRECEDING)
)
INSERT INTO {table} (stay_id, weighed_on, weight, admission_weight, highest, lowest,
    weight_30_days_before, weight_180_days_before)
SELECT stay_id, weighed_on, weight, admission_weight, highest, lowest, weight_30_days_before,
       weight_180_days_before
FROM running w
WHERE true {day_filter}
-- In date order, so a day's weigh-ins sit together as daily runs append them.
ORDER BY weighed_on, stay_id
"""


class WeightLogsGenerator(BaseGenerator):
    name = 'weight_logs'
    table = schema.weight_logs
    depends_on = ('res_stays',)
    transaction_isolation = 'REPEATABLE READ'

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Weight logs are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous weigh-ins')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Record weigh-ins')
        generated = connection.exec_driver_sql(weights_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} weigh-ins')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (WeightLogsGenerator,)


class DailyWeightLogs(DailyGenerator):
    """A whole build when every day is asked for; otherwise only the asked days'
    weigh-ins, replaced. A checkpoint's count is that day's weigh-ins."""
    name = 'weight_logs'
    table = schema.weight_logs
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def run_dates(self, connection, days):
        # From the first simulated day, a whole build: it also writes the
        # weigh-ins before it of residents already in a bed on that day, which
        # no checkpointed day owns.
        first = connection.scalar(select(func.min(schema.daily_runs.c.simulation_date))
            .where(schema.daily_runs.c.generator == 'adt'))
        if first is None or min(days) <= first:
            builder = WeightLogsGenerator(self.database_url)
            builder.progress = self.progress
            builder.write_generated(connection)
        else:
            dates = 'ARRAY[' + ', '.join(f"date '{day.isoformat()}'" for day in days) + ']'
            connection.execute(self.table.delete().where(self.table.c.weighed_on.in_(days)))
            connection.exec_driver_sql(weights_sql('weight_logs', dates))
        counts = dict(connection.execute(select(self.table.c.weighed_on, func.count())
            .where(self.table.c.weighed_on.in_(days))
            .group_by(self.table.c.weighed_on)).all())
        return {day: {self.table.name: counts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyWeightLogs,)
