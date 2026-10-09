"""Resident incidents: falls, skin tears, medication errors and the rest.

Run: python manage.py incident_logs --regenerate
Also rebuilt by every seed and update, after the day's ADT simulation.

Each stay is cut into 30-day blocks from admission. A block's incidents are
drawn as if the block were full -- how many, at the first block's higher rate
or the later blocks', and on which of its 30 days -- and an incident whose day
the stay has not reached is left out: a discharge came first, or the day is
still to come. So incidents fall only on days in a bed, at a rate that does not
drift with time, and a stay still in a bed gains incidents on their own days as
its days pass, never moving the ones it had. The first block's higher rate is
the risk soon after admission, when falls are likelier.

Every hospital transfer for a fall or injury also has its incident: a fall on
the transfer day, marked as sending the resident to hospital, so Incidents and
Hospital Transfers agree. Those are the only hospitalized incidents.

Each has a type, the resident's payer that day, a severity from 1 (no injury)
to 5 (severe) -- 4 or 5 for every hospitalized one -- the hour it happened, and
the day its investigation closed: 2 to 30 days later, most within two weeks. An incident whose closing day has not come yet is open.
Everything is drawn from the stay id's hash, not a random generator, so a
rebuild gives the same incidents.

Rebuilt whole, about 230,000 rows in about 20 seconds.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult
from source_data_generators.draws import draw as _draw, pick as _pick

THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"
# Incidents per resident day: higher in the first 30 days of a stay, when falls
# are likelier, then lower; about 6 per 1,000 resident days in all.
BLOCK_DAYS = 30
FIRST_BLOCK_RATE = 0.0081
LATER_RATE = 0.00475
# The transfer reason whose transfers each come with a fall incident that sent
# the resident to hospital. Those add about 0.3 per 1,000 resident days, which
# the two rates above leave room for.
HOSPITALIZING_REASON = 'Fall or injury'
# Percent of incidents by type, in schema.INCIDENT_TYPES order: Fall, Skin tear
# or bruise, Medication error, Resident altercation, Pressure injury, Elopement
# or wandering, Choking, Other.
TYPE_ODDS = (45, 15, 10, 9, 7, 4, 2, 8)
assert len(TYPE_ODDS) == len(schema.INCIDENT_TYPES) and sum(TYPE_ODDS) == 100
# Relative weight of each hour, 0-23: most incidents come with the morning care
# hours and the early evening, fewest overnight.
HOUR_WEIGHTS = (2, 2, 1.5, 1.5, 1.5, 2, 4, 6, 6.5, 6, 5, 4.5, 4, 4, 4, 4, 4.5, 5, 5, 5, 4.5, 3.5, 2.5, 2)
# Percent at each severity, 1 no injury to 5 severe. Most incidents cause no or
# minor harm; one that sent the resident to hospital is major or severe.
SEVERITY_ODDS = (45, 33, 17, 5, 0)
HOSPITALIZED_SEVERITY_ODDS = (0, 0, 0, 70, 30)
assert len(HOUR_WEIGHTS) == 24 and sum(SEVERITY_ODDS) == sum(HOSPITALIZED_SEVERITY_ODDS) == 100


def _type_case(draw):
    whens, total = [], 0
    for kind, share in zip(schema.INCIDENT_TYPES, TYPE_ODDS):
        total += share
        whens.append(f"WHEN {draw} < {total / 100} THEN '{kind}'")
    return 'CASE ' + ' '.join(whens[:-1]) + f" ELSE '{schema.INCIDENT_TYPES[-1]}' END"


def incidents_sql(table):
    block = "stay_id::text || ':' || block"
    seed = block + " || ':' || k"
    return f"""
WITH through AS ({THROUGH}), stays AS (
    -- Days in a bed through the latest simulated day, as the census counts them.
    SELECT s.stay_id, s.resident_id, s.facility_id, s.admission_date,
           least(coalesce(s.discharge_date, (SELECT day FROM through) + 1), (SELECT day FROM through) + 1)
             - s.admission_date AS days
    FROM res_stays s
    WHERE s.admission_date <= (SELECT day FROM through)
), blocks AS (
    -- Each block's incidents, drawn as if the block were full.
    SELECT st.*, block,
           floor({BLOCK_DAYS} * CASE WHEN block = 0 THEN {FIRST_BLOCK_RATE} ELSE {LATER_RATE} END
             + {_draw(block + " || ':count'")})::int AS incidents
    FROM stays st CROSS JOIN LATERAL generate_series(0, (st.days - 1) / {BLOCK_DAYS}) AS block
    WHERE st.days > 0
), placed AS (
    SELECT b.*, k, block * {BLOCK_DAYS} + floor({_draw(seed + " || ':day'")} * {BLOCK_DAYS})::int AS offset_days
    FROM blocks b CROSS JOIN LATERAL generate_series(1, b.incidents) AS k
)
INSERT INTO {table} (incident_id, stay_id, resident_id, facility_id, incident_date, incident_type, payer_id,
    closed_date, hospitalized, severity, incident_hour)
SELECT md5({seed.replace('stay_id', 'p.stay_id')})::uuid, p.stay_id, resident_id, facility_id, admission_date + offset_days,
       {_type_case(_draw(seed.replace('stay_id', 'p.stay_id') + " || ':type'"))}, ps.payer_id,
       admission_date + offset_days + 2 + floor(power({_draw(seed.replace('stay_id', 'p.stay_id') + " || ':closed'")}, 2) * 29)::int,
       false,
       {_pick(_draw(seed.replace('stay_id', 'p.stay_id') + " || ':severity'"), range(1, 6), SEVERITY_ODDS)},
       {_pick(_draw(seed.replace('stay_id', 'p.stay_id') + " || ':hour'"), range(24), HOUR_WEIGHTS)}
FROM placed p
-- The payer that day: the payer period covering it. end_date is the day after
-- the period's last day, as census ranges are; every stay day has exactly one.
JOIN res_payer_stays ps ON ps.stay_id = p.stay_id AND ps.start_date <= p.admission_date + p.offset_days
    AND (ps.end_date IS NULL OR ps.end_date > p.admission_date + p.offset_days)
-- Only the days the stay has reached: before a discharge, and up to the latest day.
WHERE offset_days < days
UNION ALL
-- The falls that sent a resident to hospital: one per hospital transfer for a
-- fall or injury, on its transfer day, with the transfer's payer. Keyed by the
-- stay, which has at most one transfer.
SELECT md5('transfer:' || t.stay_id::text)::uuid, t.stay_id, s.resident_id, t.facility_id, t.transfer_date, 'Fall',
       t.payer_id, t.transfer_date + 2 + floor(power({_draw("'transfer:' || t.stay_id::text || ':closed'")}, 2) * 29)::int,
       true,
       {_pick(_draw("'transfer:' || t.stay_id::text || ':severity'"), range(1, 6), HOSPITALIZED_SEVERITY_ODDS)},
       {_pick(_draw("'transfer:' || t.stay_id::text || ':hour'"), range(24), HOUR_WEIGHTS)}
FROM transfer_logs t JOIN res_stays s ON s.stay_id = t.stay_id
WHERE t.reason = '{HOSPITALIZING_REASON}'
"""


class IncidentLogsGenerator(BaseGenerator):
    name = 'incident_logs'
    table = schema.incident_logs
    # The hospitalized falls come from the transfers, so they rebuild together.
    depends_on = ('res_stays', 'transfer_logs')
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        if connection.scalar(select(func.count()).select_from(schema.res_stays)) == 0:
            raise ValueError('There are no stays. Run update before building incident logs.')
        if connection.scalar(select(func.count()).select_from(schema.transfer_logs)) == 0:
            raise ValueError('There are no transfer logs. Run python manage.py transfer_logs --regenerate first.')

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Incident logs are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous incidents')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Record incidents')
        generated = connection.exec_driver_sql(incidents_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} incidents')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (IncidentLogsGenerator,)


class DailyIncidentLogs(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is that day's
    incidents."""
    name = 'incident_logs'
    table = schema.incident_logs
    owned_tables = (table,)
    # After the day's transfers, whose fall transfers it reads.
    depends_on = ('transfer_logs',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = IncidentLogsGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        counts = dict(connection.execute(select(self.table.c.incident_date, func.count())
            .where(self.table.c.incident_date.in_(days))
            .group_by(self.table.c.incident_date)).all())
        return {day: {self.table.name: counts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyIncidentLogs,)
