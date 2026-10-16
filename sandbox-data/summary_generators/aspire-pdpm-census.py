"""Calendar-month PDPM census facts, rolled up from the PDPM rate steps.

Run: python manage.py pdpm_census_summary --regenerate
Also rebuilt by every seed and update, after census_logs.

Feeds Current Medicare PDPM's Overview, which compares today with last month's,
the last 6 and 12 months' and the all-time average. Read from the steps alone
that meant all 924,406 Medicare steps on every load, 1.1 s; this is 24,613 rows.

The residents are the ones Current Medicare PDPM counts: Original Medicare and
Managed Medicare PDPM on a PDPM contract. A step that crosses a month boundary
is split between the two months, so every month holds exactly its own days.
The steps stop at the latest simulated day; an open step is cut there too.

Monthly Medicare PDPM Trending's Category breakdown reads six PDPM categories
from the same days: each period's assessment, counted from its coded_date, as
Current Medicare PDPM counts a resident in a category only once the code is
available. coded_days is the days with a code, the categories' denominator; the
categories overlap. The _residents columns count the residents coded in the
month -- the code took effect that month, while they were in a bed -- in all
and in each category, for its monthly trend; not the months after. The letters are Current Medicare PDPM's (backend/app/mds/
categories.py): PT/OT I-L Medical Management, SLP A (SA), nursing R-S
Behavioral and T-Y Reduced Physical Function, from shared/pdpm.py.

Rebuilt whole, about 6 s, because census_logs and its steps are: payer periods
are edited after the fact, so any month may change.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared import pdpm
from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

NURSING_LETTERS = {field: letters for field, _, letters in pdpm.NURSING_CATEGORIES}
THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"


def letters(values):
    return ', '.join(f"'{letter}'" for letter in values)


def facts_sql(table):
    return f"""
WITH through AS ({THROUGH}), periods AS MATERIALIZED (
    -- Each Medicare period once, with its facility and its code's categories,
    -- so the 1.1 million steps join to it by hash rather than one assessment
    -- lookup each: 81,000 periods.
    SELECT ps.payer_stay_id, s.facility_id, s.resident_id, p.payer_type, a.coded_date, coalesce(a.depression, false) AS depression,
           coalesce(substr(a.pdpm_code, 1, 1) IN ('I', 'J', 'K', 'L'), false) AS medical_management,
           coalesce(substr(a.pdpm_code, 2, 1) = 'A', false) AS slp_sa,
           coalesce(substr(a.pdpm_code, 3, 1) IN ({letters(NURSING_LETTERS['behavioral'])}), false) AS behavioral,
           coalesce(substr(a.pdpm_code, 3, 1) IN ({letters(NURSING_LETTERS['reduced_physical_function'])}), false)
               AS reduced_physical_function,
           coalesce(a.nursing_function_score BETWEEN 15 AND 16, false) AS gg_15_16
    FROM res_payer_stays ps
    JOIN payers p ON p.payer_id = ps.payer_id AND p.payer_type IN ('medicare', 'managed_medicare_pdpm')
    JOIN res_stays s ON s.stay_id = ps.stay_id
    -- A PDPM contract, as Current Medicare PDPM counts: per diem plans are out.
    JOIN facility_payer_rates c ON c.facility_id = s.facility_id AND c.payer_id = ps.payer_id
        AND c.payment_method = 'pdpm'
    -- The period's code, once it is available; none yet, and no day is coded.
    LEFT JOIN pdpm_assessments a ON a.payer_stay_id = ps.payer_stay_id
), steps AS (
    SELECT pe.*, l.daily_rate, l.pdpm_factor, lower(l.in_effect) AS starts,
           least(upper(l.in_effect), (SELECT day FROM through) + 1) AS ends
    FROM pdpm_rate_logs l
    JOIN periods pe ON pe.payer_stay_id = l.payer_stay_id
    WHERE lower(l.in_effect) <= (SELECT day FROM through)
), days AS (
    -- Each month a step touches, its days inside that month, and of those the
    -- days on or after the code was available.
    SELECT m::date AS month_start, st.facility_id, st.resident_id, st.payer_type, st.daily_rate, st.pdpm_factor, st.depression,
           st.medical_management, st.slp_sa, st.behavioral, st.reduced_physical_function, st.gg_15_16,
           least(st.ends, (m + interval '1 month')::date) - greatest(st.starts, m::date) AS days,
           greatest(0, least(st.ends, (m + interval '1 month')::date)
               - greatest(st.starts, m::date, coalesce(st.coded_date, st.ends))) AS coded,
           -- The step and month holding the day the code took effect.
           coalesce(st.coded_date >= greatest(st.starts, m::date)
               AND st.coded_date < least(st.ends, (m + interval '1 month')::date), false) AS coding
    FROM steps st
    CROSS JOIN LATERAL generate_series(date_trunc('month', st.starts), date_trunc('month', st.ends - 1),
        interval '1 month') AS m
)
INSERT INTO {table} (month_start, facility_id, payer_type, resident_days, actual_rates, factor_days, coded_days,
    depression_days, medical_management_days, slp_sa_days, behavioral_days, reduced_physical_function_days,
    nursing_gg_15_16_days, coded_residents, depression_residents, medical_management_residents, slp_sa_residents,
    behavioral_residents, reduced_physical_function_residents, nursing_gg_15_16_residents)
SELECT month_start, facility_id, payer_type, sum(days), sum(days * daily_rate), sum(days * pdpm_factor), sum(coded),
    coalesce(sum(coded) FILTER (WHERE depression), 0), coalesce(sum(coded) FILTER (WHERE medical_management), 0),
    coalesce(sum(coded) FILTER (WHERE slp_sa), 0), coalesce(sum(coded) FILTER (WHERE behavioral), 0),
    coalesce(sum(coded) FILTER (WHERE reduced_physical_function), 0), coalesce(sum(coded) FILTER (WHERE gg_15_16), 0),
    -- Residents coded in the month, in each category: only the month the code
    -- took effect, not the months after.
    count(DISTINCT resident_id) FILTER (WHERE coding),
    count(DISTINCT resident_id) FILTER (WHERE coding AND depression),
    count(DISTINCT resident_id) FILTER (WHERE coding AND medical_management),
    count(DISTINCT resident_id) FILTER (WHERE coding AND slp_sa),
    count(DISTINCT resident_id) FILTER (WHERE coding AND behavioral),
    count(DISTINCT resident_id) FILTER (WHERE coding AND reduced_physical_function),
    count(DISTINCT resident_id) FILTER (WHERE coding AND gg_15_16)
FROM days
GROUP BY month_start, facility_id, payer_type
"""


class PdpmCensusSummaryGenerator(BaseGenerator):
    name = 'pdpm_census_summary'
    table = schema.monthly_pdpm_census_facts
    depends_on = ('census_logs',)
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        through = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'adt'))
        if through is None:
            raise ValueError('No simulated days yet. Run update before building PDPM census facts.')
        if connection.scalar(select(func.count()).select_from(schema.pdpm_rate_logs)) == 0:
            raise ValueError('There are no PDPM rate steps. Run python manage.py census_logs --regenerate first.')

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('PDPM census facts are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        self.show_table_progress(self.table)
        driver = connection.connection.driver_connection
        table = self._table_identifier(self.table)
        if self.progress:
            self.progress.set_phase('Remove previous facts')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(table).as_string(driver))
        suspended = self.suspend_indexes(connection, self.table)
        if self.progress:
            self.progress.set_phase('Roll up PDPM rate steps by month')
        # The aggregate's 1.1 million step-months spill to disk in 65 batches at
        # the default 4 MB, 12 s; in memory 5.6 s. Local to this transaction.
        connection.exec_driver_sql("SET LOCAL work_mem = '128MB'")
        generated = connection.exec_driver_sql(facts_sql(table.as_string(driver))).rowcount
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{generated:,} facility months')
        self.restore_indexes(connection, self.table, suspended)
        return GenerationResult(generated=generated, changed=generated)


GENERATORS = (PdpmCensusSummaryGenerator,)


class DailyPdpmCensusSummary(DailyGenerator):
    """Rebuilt whole whenever days are added. A checkpoint's count is the
    facility months starting that day, so only a month's first day has any."""
    name = 'pdpm_census_summary'
    table = schema.monthly_pdpm_census_facts
    owned_tables = (table,)
    # The steps census_logs writes, so never before that day's steps exist.
    depends_on = ('census_logs',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = PdpmCensusSummaryGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        starts = dict(connection.execute(select(self.table.c.month_start, func.count())
            .where(self.table.c.month_start.in_(days))
            .group_by(self.table.c.month_start)).all())
        return {day: {self.table.name: starts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyPdpmCensusSummary,)
