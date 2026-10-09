"""Resident infections and fevers: sporadic cases, and outbreaks.

Run: python manage.py infection_logs --regenerate
Also rebuilt by every seed and update, after the day's ADT simulation and bed
assignments.

Sporadic cases come at about 2 per 1,000 resident days -- mostly urinary tract
and skin infections, which do not spread -- placed as incidents are: each stay
in 30-day blocks whose cases are drawn as if the block were full, kept once the
stay reaches their day.

Outbreaks are drawn per facility and 30-day block from 2023: in a winter block
(November to March) about one facility in eight starts one, otherwise about one
in twenty. An outbreak is a contagious type -- respiratory, influenza-like or
gastrointestinal -- through one wing for 7 to 21 days: about 30% of the
residents in that wing fall ill on a day within it, and about 4% of those
elsewhere in the facility. Nothing marks a case as part of an outbreak: the
Fever / Infections alert board finds outbreaks by its own rule.

Each case has the wing of the resident's bed that day, a fever or not (likelier
for influenza-like illness and respiratory), and resolves 3 to 13 days later.
Every draw comes from stay and facility ids, so a rebuild gives the same cases,
and an outbreak's days and wing never move as days are added.

Rebuilt whole in about 15 seconds.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw, pick

THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"
FIRST_DAY = '2023-01-01'
BLOCK_DAYS = 30
SPORADIC_RATE = 0.002
TYPES = [f"'{kind}'" for kind in schema.INFECTION_TYPES]
# Percent of sporadic cases by type, in schema.INFECTION_TYPES order:
# Respiratory, Influenza-like illness, Gastrointestinal, Urinary tract, Skin or
# soft tissue, Fever with no known source.
SPORADIC_TYPE_ODDS = (18, 4, 6, 38, 22, 12)
# The chance a case comes with a fever, by type, in the same order.
FEVER_CHANCE = (0.60, 0.90, 0.30, 0.40, 0.25, 1.0)
# A facility's chance of an outbreak starting in a 30-day block.
WINTER_OUTBREAK_CHANCE, OTHER_OUTBREAK_CHANCE = 0.13, 0.05
WINTER_MONTHS = (11, 12, 1, 2, 3)
# What an outbreak is, by season, in INFECTION_TYPES order; only the
# contagious types.
WINTER_OUTBREAK_ODDS = (45, 30, 25, 0, 0, 0)
OTHER_OUTBREAK_ODDS = (40, 5, 55, 0, 0, 0)
# The share of residents falling ill: in the outbreak's wing, and elsewhere.
WING_ATTACK, FACILITY_ATTACK = 0.30, 0.04
assert sum(SPORADIC_TYPE_ODDS) == sum(WINTER_OUTBREAK_ODDS) == sum(OTHER_OUTBREAK_ODDS) == 100


def _fever(kind, draw_sql):
    return 'CASE ' + ' '.join(f'WHEN {kind} = {value} THEN {draw_sql} < {chance}'
        for value, chance in zip(TYPES, FEVER_CHANCE)) + ' END'


def infections_sql(table):
    sporadic = "'sporadic:' || stay_id::text || ':' || block || ':' || k"
    outbreak = "'outbreak:' || x.facility_id::text || ':' || x.block || ':' || x.stay_id::text"
    episode = "e.facility_id::text || ':' || e.block"
    return f"""
WITH through AS ({THROUGH}), stays AS (
    -- Days in a bed through the latest simulated day, as the census counts them.
    SELECT s.stay_id, s.resident_id, s.facility_id, s.admission_date,
           least(coalesce(s.discharge_date, (SELECT day FROM through) + 1), (SELECT day FROM through) + 1)
             - s.admission_date AS days
    FROM res_stays s
    WHERE s.admission_date <= (SELECT day FROM through)
), blocks AS (
    SELECT st.*, block,
           floor({BLOCK_DAYS} * {SPORADIC_RATE} + {draw("stay_id::text || ':' || block || ':count'")})::int AS cases
    FROM stays st CROSS JOIN LATERAL generate_series(0, (st.days - 1) / {BLOCK_DAYS}) AS block
    WHERE st.days > 0
), sporadic AS (
    SELECT md5({sporadic})::uuid AS infection_id, b.stay_id, b.resident_id, b.facility_id,
           b.admission_date + block * {BLOCK_DAYS} + floor({draw(sporadic + " || ':day'")} * {BLOCK_DAYS})::int AS onset,
           {pick(draw(sporadic + " || ':type'"), TYPES, SPORADIC_TYPE_ODDS)} AS infection_type,
           {draw(sporadic + " || ':fever'")} AS fever_draw,
           {draw(sporadic + " || ':resolved'")} AS resolved_draw,
           block * {BLOCK_DAYS} + floor({draw(sporadic + " || ':day'")} * {BLOCK_DAYS})::int AS offset_days, b.days
    FROM blocks b CROSS JOIN LATERAL generate_series(1, b.cases) AS k
), facility_wings AS (
    SELECT facility_id, array_agg(DISTINCT wing ORDER BY wing) AS wings FROM facility_beds GROUP BY facility_id
), episodes AS (
    -- Each facility's 30-day blocks; some start an outbreak.
    SELECT f.facility_id, block, date '{FIRST_DAY}' + block * {BLOCK_DAYS} AS block_start, f.wings
    FROM facility_wings f
    CROSS JOIN generate_series(0, ((SELECT day FROM through) - date '{FIRST_DAY}') / {BLOCK_DAYS}) AS block
), outbreaks AS MATERIALIZED (
    -- Materialized: a few thousand rows, joined to bed assignments by facility.
    -- Inlined, the planner pairs every assignment with every block first.
    SELECT e.facility_id, e.block,
           e.block_start + floor({draw(episode + " || ':start'")} * {BLOCK_DAYS})::int AS starts,
           7 + floor({draw(episode + " || ':length'")} * 15)::int AS length,
           e.wings[1 + floor({draw(episode + " || ':wing'")} * cardinality(e.wings))::int] AS wing,
           CASE WHEN extract(month FROM e.block_start) IN {WINTER_MONTHS}
                THEN {pick(draw(episode + " || ':type'"), TYPES, WINTER_OUTBREAK_ODDS)}
                ELSE {pick(draw(episode + " || ':type'"), TYPES, OTHER_OUTBREAK_ODDS)} END AS infection_type
    FROM episodes e
    WHERE {draw(episode + " || ':outbreak'")} < CASE WHEN extract(month FROM e.block_start) IN {WINTER_MONTHS}
        THEN {WINTER_OUTBREAK_CHANCE} ELSE {OTHER_OUTBREAK_CHANCE} END
), exposed AS (
    -- Everyone in a bed in the facility during the outbreak, once each.
    SELECT DISTINCT ON (o.facility_id, o.block, b.stay_id) o.*, b.stay_id, b.resident_id, fb.wing AS bed_wing
    FROM outbreaks o
    JOIN bed_assignments b ON b.facility_id = o.facility_id
        AND b.in_bed && daterange(o.starts, o.starts + o.length)
    JOIN facility_beds fb ON fb.bed_id = b.bed_id
    ORDER BY o.facility_id, o.block, b.stay_id, lower(b.in_bed)
), outbreak_cases AS (
    SELECT md5({outbreak})::uuid AS infection_id, x.stay_id, x.resident_id, x.facility_id,
           x.starts + floor({draw(outbreak + " || ':day'")} * x.length)::int AS onset, x.infection_type,
           {draw(outbreak + " || ':fever'")} AS fever_draw, {draw(outbreak + " || ':resolved'")} AS resolved_draw
    FROM exposed x
    WHERE {draw(outbreak + " || ':ill'")} < CASE WHEN x.bed_wing = x.wing THEN {WING_ATTACK} ELSE {FACILITY_ATTACK} END
), cases AS (
    SELECT infection_id, stay_id, resident_id, facility_id, onset, infection_type, fever_draw, resolved_draw
    FROM sporadic WHERE offset_days < days
    UNION ALL
    SELECT infection_id, stay_id, resident_id, facility_id, onset, infection_type, fever_draw, resolved_draw
    FROM outbreak_cases
)
INSERT INTO {table} (infection_id, stay_id, resident_id, facility_id, wing, onset_date, resolved_date,
    infection_type, fever)
SELECT c.infection_id, c.stay_id, c.resident_id, c.facility_id, fb.wing, c.onset,
       c.onset + 3 + floor(c.resolved_draw * 11)::int, c.infection_type, {_fever('c.infection_type', 'c.fever_draw')}
FROM cases c
-- The resident's bed that day, which also keeps only days in a bed, through
-- the latest simulated day.
JOIN bed_assignments b ON b.stay_id = c.stay_id AND b.in_bed @> c.onset
JOIN facility_beds fb ON fb.bed_id = b.bed_id
WHERE c.onset <= (SELECT day FROM through)
"""


class InfectionLogsGenerator(BaseGenerator):
    name = 'infection_logs'
    table = schema.infection_logs
    depends_on = ('res_stays', 'bed_assignments')
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        if connection.scalar(select(func.count()).select_from(schema.bed_assignments)) == 0:
            raise ValueError('There are no bed assignments. Run python manage.py bed_assignments --regenerate first.')

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Infection logs are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous infections')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Record infections and outbreaks')
        generated = connection.exec_driver_sql(infections_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} infections')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (InfectionLogsGenerator,)


class DailyInfectionLogs(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is that day's
    new infections."""
    name = 'infection_logs'
    table = schema.infection_logs
    owned_tables = (table,)
    # After the day's bed assignments, which say where each resident slept.
    depends_on = ('bed_assignments',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = InfectionLogsGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        counts = dict(connection.execute(select(self.table.c.onset_date, func.count())
            .where(self.table.c.onset_date.in_(days))
            .group_by(self.table.c.onset_date)).all())
        return {day: {self.table.name: counts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyInfectionLogs,)
