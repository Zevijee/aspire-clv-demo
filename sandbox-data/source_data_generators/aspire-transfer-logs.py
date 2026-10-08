"""Hospital transfers: one row per discharge to a hospital, with a clinical reason.

Run: python manage.py transfer_logs --regenerate
Also rebuilt by every seed and update, after the day's ADT simulation.

Each transfer copies what the clinical reports cut it by -- facility, date,
payer, admission date and source -- from the stay and its logs, and gets a
reason. The reason is drawn from the stay id's hash, not a random generator, so
a rebuild gives every transfer the same reason. Its odds depend on the stay:

    rehospitalization  admitted from a hospital, sent back within 30 days:
                       infections and surgical complications lead
    early              any other transfer within 30 days of admission:
                       respiratory and cardiac lead
    long stay          after 30 days: falls, UTIs and changes in mental
                       status take a larger share

Rebuilt whole, about 98,000 rows in a few seconds, because discharge logs are
rebuilt whole too and any day's transfers may change with them.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

WITHIN_DAYS = 30
# Percent of each kind of transfer by reason, in schema.TRANSFER_REASONS order:
# Respiratory, Cardiac, Infection or sepsis, Urinary tract infection, Fall or
# injury, Change in mental status, Gastrointestinal, Dehydration or
# electrolytes, Surgical complication, Planned procedure, Other.
REASON_ODDS = {
    'rehospitalization': (14, 13, 16, 7, 6, 6, 9, 6, 14, 4, 5),
    'early': (16, 14, 14, 9, 10, 9, 9, 7, 3, 4, 5),
    'long_stay': (18, 13, 12, 11, 14, 10, 8, 7, 1, 3, 3),
}
assert all(len(odds) == len(schema.TRANSFER_REASONS) and sum(odds) == 100 for odds in REASON_ODDS.values())


def _reason_case(odds):
    """The reason for a draw `draw` in [0, 1), by cumulative odds."""
    whens, total = [], 0
    for reason, share in zip(schema.TRANSFER_REASONS, odds):
        total += share
        whens.append(f"WHEN draw < {total / 100} THEN '{reason}'")
    return 'CASE ' + ' '.join(whens[:-1]) + f" ELSE '{schema.TRANSFER_REASONS[-1]}' END"


def transfers_sql(table):
    return f"""
WITH transfers AS (
    SELECT d.stay_id, s.facility_id, d.discharge_date, d.payer_id, s.admission_date,
           d.discharge_date - s.admission_date AS days, a.source_type,
           -- A stable draw in [0, 1) from the stay id: 32 bits of its md5.
           ('x' || lpad(substr(md5(d.stay_id::text), 1, 8), 16, '0'))::bit(64)::bigint / 4294967296.0 AS draw
    FROM discharge_logs d
    JOIN res_stays s ON s.stay_id = d.stay_id
    JOIN admission_logs a ON a.stay_id = d.stay_id
    WHERE d.destination_type = 'Hospital'
)
INSERT INTO {table} (stay_id, facility_id, transfer_date, payer_id, admission_date, days_since_admission,
    admission_source_type, reason)
SELECT stay_id, facility_id, discharge_date, payer_id, admission_date, days, source_type,
       CASE WHEN days <= {WITHIN_DAYS} AND source_type = 'Hospital' THEN {_reason_case(REASON_ODDS['rehospitalization'])}
            WHEN days <= {WITHIN_DAYS} THEN {_reason_case(REASON_ODDS['early'])}
            ELSE {_reason_case(REASON_ODDS['long_stay'])} END
FROM transfers
"""


class TransferLogsGenerator(BaseGenerator):
    name = 'transfer_logs'
    table = schema.transfer_logs
    depends_on = ('discharge_logs', 'admission_logs')
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        if connection.scalar(select(func.count()).select_from(schema.discharge_logs)) == 0:
            raise ValueError('There are no discharge logs. Run update before building transfer logs.')

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Transfer logs are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous transfers')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Record hospital transfers')
        generated = connection.exec_driver_sql(transfers_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} transfers')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (TransferLogsGenerator,)


class DailyTransferLogs(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is that day's
    transfers."""
    name = 'transfer_logs'
    table = schema.transfer_logs
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = TransferLogsGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        counts = dict(connection.execute(select(self.table.c.transfer_date, func.count())
            .where(self.table.c.transfer_date.in_(days))
            .group_by(self.table.c.transfer_date)).all())
        return {day: {self.table.name: counts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyTransferLogs,)
