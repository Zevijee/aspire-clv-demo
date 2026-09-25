"""Every resident ever admitted, totalled across all their stays.

Run: python manage.py resident_summaries --regenerate
Also rebuilt by every seed and update, after the day's simulation.

A pure rollup of res_stays and res_payer_stays for the Residents report, which
needs to sort, filter and page 187,000 residents; computed live it measured 2.1s
a request. Nothing is invented here, so rebuilding cannot change a reported
number. Rebuilt whole, because an added day can discharge anyone.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"


def summaries_sql(table):
    return f"""
WITH through AS ({THROUGH}), stays AS (
    SELECT s.resident_id, min(s.facility_id::text)::uuid AS facility_id, count(*) AS stays,
           count(s.discharge_date) AS discharges,
           sum(coalesce(s.discharge_date, (SELECT day FROM through)) - s.admission_date) AS days,
           min(s.admission_date) AS first_admission, max(s.admission_date) AS last_admission,
           max(s.discharge_date) AS last_discharge
    FROM res_stays s
    WHERE s.admission_date <= (SELECT day FROM through)
    GROUP BY s.resident_id
), payers_used AS (
    SELECT s.resident_id, count(DISTINCT ps.payer_id) AS payers,
           count(DISTINCT p.payer_type) AS payer_types
    FROM res_payer_stays ps
    JOIN res_stays s ON s.stay_id = ps.stay_id
    JOIN payers p ON p.payer_id = ps.payer_id
    WHERE ps.start_date <= (SELECT day FROM through)
    GROUP BY s.resident_id
)
INSERT INTO {table} (resident_id, facility_id, resident_name, facility_name, state, portfolio,
    region, stays, admissions, discharges, is_current, days_in_facility, payers, payer_types,
    first_admission, last_admission, last_discharge, as_of)
SELECT s.resident_id, s.facility_id, r.first_name || ' ' || r.last_name, f.facility, o.state,
       o.portfolio, g.region, s.stays, s.stays, s.discharges, s.discharges < s.stays,
       s.days, p.payers, p.payer_types, s.first_admission, s.last_admission, s.last_discharge,
       (SELECT day FROM through)
FROM stays s
JOIN payers_used p ON p.resident_id = s.resident_id
JOIN residents r ON r.resident_id = s.resident_id
JOIN facilities f ON f.facility_id = s.facility_id
JOIN regions g ON g.region_id = f.region_id
JOIN portfolios o ON o.portfolio_id = g.portfolio_id
"""


class ResidentSummaryGenerator(BaseGenerator):
    name = 'resident_summaries'
    table = schema.resident_summaries
    depends_on = ('res_stays',)
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        stays = self.res_stays
        through = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'adt'))
        if through is None:
            raise ValueError('No simulated days yet. Run update before building resident summaries.')
        # One facility per resident is what lets facility_id sit on the summary.
        # Refuse rather than report a resident under an arbitrary one.
        split = connection.scalar(select(func.count()).select_from(
            select(stays.c.resident_id).group_by(stays.c.resident_id)
            .having(func.count(func.distinct(stays.c.facility_id)) > 1).subquery()))
        if split:
            raise ValueError(f'{split:,} residents have stays at more than one facility; '
                'resident_summaries assumes one facility per resident.')
        self._residents = connection.scalar(select(func.count(func.distinct(stays.c.resident_id)))
            .where(stays.c.admission_date <= through))

    def expected_rows(self):
        return self._residents

    def generate(self):
        raise ValueError('Resident summaries are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous summaries')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase("Total every resident's stays", details=f'{self._residents:,} residents')
        generated = connection.exec_driver_sql(summaries_sql(table.as_string(driver))).rowcount
        if generated != self._residents:
            raise ValueError('Saved stays changed while resident summaries were building; run again.')
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} residents')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (ResidentSummaryGenerator,)


class DailyResidentSummaries(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is the
    residents first admitted that day."""
    name = 'resident_summaries'
    table = schema.resident_summaries
    owned_tables = (table,)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = ResidentSummaryGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        firsts = dict(connection.execute(select(self.table.c.first_admission, func.count())
            .where(self.table.c.first_admission.in_(days))
            .group_by(self.table.c.first_admission)).all())
        return {day: {self.table.name: firsts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyResidentSummaries,)
