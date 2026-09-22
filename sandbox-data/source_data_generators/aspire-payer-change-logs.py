"""Payer changes flattened from the payer periods that imply them.

Run: python manage.py payer_change_logs --regenerate

A payer change is not a separate event the simulation records: it is the
boundary between two adjacent rows in res_payer_stays. That makes a log table
pure derivation, which is why one did not exist at first -- but reading the
boundary back costs a self-join on period_number - 1 on every query, and that
made the payer-change endpoints the slowest in the app. This pays the join once.

Nothing here is invented. Every column is copied or subtracted from the two
periods, so regenerating it cannot change any reported number.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, GenerationResult

LOGS_SQL = """
INSERT INTO __TABLE__ (payer_stay_id, stay_id, resident_id, facility_id, change_date,
    previous_payer_id, new_payer_id, previous_start_date, new_end_date, is_type_change)
SELECT n.payer_stay_id, n.stay_id, s.resident_id, s.facility_id, n.start_date,
       p.payer_id, n.payer_id, p.start_date, n.end_date,
       pp.payer_type IS DISTINCT FROM np.payer_type
FROM res_payer_stays n
JOIN res_payer_stays p ON p.stay_id = n.stay_id AND p.period_number = n.period_number - 1
JOIN res_stays s ON s.stay_id = n.stay_id
JOIN payers np ON np.payer_id = n.payer_id
JOIN payers pp ON pp.payer_id = p.payer_id
WHERE n.period_number > 1
"""


class PayerChangeLogGenerator(BaseGenerator):
    name = 'payer_change_logs'
    table = schema.payer_change_logs
    depends_on = ('res_stays',)
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        if self.progress:
            self.progress.set_phase('Check payer periods')
        periods = self.res_payer_stays
        prior = periods.alias('prior')
        # A change with no preceding period would be dropped by the join below
        # rather than reported, so refuse to build instead of losing rows.
        orphan = connection.scalar(select(periods.c.payer_stay_id).where(
            periods.c.period_number > 1,
            ~select(1).select_from(prior).where(
                prior.c.stay_id == periods.c.stay_id,
                prior.c.period_number == periods.c.period_number - 1).exists()
        ).limit(1))
        if orphan is not None:
            raise ValueError('Some payer periods have no preceding period. '
                'Rebuild res_stays before generating payer change logs.')
        self._total = connection.scalar(select(func.count()).select_from(periods)
            .where(periods.c.period_number > 1))

    def expected_rows(self):
        return self._total

    def generate(self):
        raise ValueError('Payer change logs are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        """Replace every row. The table is a projection, so a partial write has
        no meaning: a period edited anywhere changes only its own log row, and
        rebuilding all of them costs a single scan."""
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        if self.progress:
            self.progress.set_phase('Remove previous logs')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}')
            .format(self._table_identifier(self.table)).as_string(driver))
        if self.progress:
            self.progress.set_phase('Suspend keys for bulk replace')
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Flatten payer changes',
                details=f'{self._total:,} changes; one source scan')
        statement = LOGS_SQL.replace(
            '__TABLE__', self._table_identifier(self.table).as_string(driver))
        generated = connection.exec_driver_sql(statement).rowcount
        if generated != self._total:
            raise ValueError('Saved payer periods changed while logs were building; run again.')
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} published rows')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (PayerChangeLogGenerator,)
