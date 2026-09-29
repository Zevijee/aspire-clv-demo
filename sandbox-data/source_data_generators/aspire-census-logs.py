"""Who was in a bed, at what care level and daily rate, for all of history.

Run: python manage.py census_logs --regenerate
Also rebuilt by every seed and update, after the day's simulation.

Three tables, built together:

- census_logs: one row per stretch in a bed at one payer and one care level,
  split from res_payer_stays. See the schema for why this shape rather than a
  row per resident per day.
- pdpm_rate_logs: the PDPM rate periods of each skilled payer period, built from
  the census rows so the two cannot disagree about a resident's base rate. The
  census row is not split by them.
- pdpm_assessments: the four-letter PDPM code of every Medicare payer period,
  with its nursing group drawn from the band the period's care level implies.

Care level is invented here, like referral sources: a pure output that nothing
in the simulation reads back, a function of the stay id alone, so changing any
rule below needs this rebuild and nothing more. Rules:

- Every stay starts at a level drawn from its id, and keeps it across payer
  changes, so skilled-to-Medicaid continues at the same acuity.
- Levels are reassessed every 92 days from admission, as the MDS quarterly
  assessment is. Each stay drifts upward at its own pace, or not at all, because
  long-stay residents tend to decline. Levels never step down.
- A skilled payer's rate also follows Medicare's PDPM variable per diem: days 1-3
  pay more, and from day 21 the therapy share falls 2% every 7 days.

A census row's rate is the facility and plan rate from facility_payer_rates times
the care level multiplier. A PDPM row's rate is that times the day's PDPM factor.
"""
from psycopg import sql
from sqlalchemy import func, select

from shared.database import schema
from base import BaseGenerator, DailyGenerator, GenerationResult

LEVELS = ('Low', 'Moderate', 'High', 'Complex')
LEVEL_MULTIPLIER = (0.88, 1.00, 1.14, 1.30)
# Cumulative shares of stays starting at each level.
LEVEL_SHARES = (0.30, 0.70, 0.92)
# Cumulative shares of stays rising one level every 2, 3 or 4 quarters. The
# remaining 20% never change level.
DRIFT_SHARES = ((0.25, 2), (0.55, 3), (0.80, 4))
ASSESSMENT_DAYS = 92
# PDPM: the share of the per diem in physical and occupational therapy, and in
# non-therapy ancillaries, and how each is adjusted by day of skilled coverage.
THERAPY_SHARE, NTA_SHARE = 0.42, 0.10
THERAPY_STEP_FROM, THERAPY_STEP_DAYS, THERAPY_STEP = 21, 7, 0.02
NTA_BOOST_THROUGH, NTA_BOOST = 3, 3

# PDPM classification. Payer types classified, and cumulative shares for each
# letter of the code. These are demo distributions, not CMS statistics.
PDPM_PAYER_TYPES = ('medicare', 'medicare_hmo', 'medicare_comm')
# PT/OT: clinical category (joint replacement or spinal surgery, other
# orthopedic, medical management, non-orthopedic surgery or acute neurologic),
# then function score band (0-5, 6-9, 10-23, 24). Letter = category * 4 + band.
PT_OT_CATEGORY_SHARES = (0.15, 0.35, 0.80)
PT_OT_FUNCTION_SHARES = (0.25, 0.55, 0.95)
# SLP, A (no condition, no swallowing need) through L.
SLP_SHARES = (0.55, 0.63, 0.65, 0.77, 0.82, 0.84, 0.90, 0.93, 0.95, 0.98, 0.99)
# NTA, A (12+ comorbidity points) through F (none).
NTA_SHARES = (0.03, 0.10, 0.25, 0.55, 0.85)
# Nursing letters each care level draws from, uniformly: A-G extensive services
# and high-acuity special care, down to R-Y behavioral and reduced physical function.
NURSING_BANDS = {'Complex': 'ABCDEFG', 'High': 'DEFGHIJK', 'Moderate': 'HIJKLMNOPQ', 'Low': 'RSTUVWXY'}

THROUGH = "SELECT max(simulation_date) AS day FROM sandbox_daily_runs WHERE generator = 'adt'"


def _uniform(salt):
    """A deterministic draw in [0, 1) from the stay id."""
    return (f"(('x' || substr(md5(c.stay_id::text || ':{salt}'), 1, 8))::bit(32)::bigint "
        '/ 4294967296.0)')


def _level_case():
    cases = ' '.join(f'WHEN {_uniform("care-level")} < {share} THEN {index}'
        for index, share in enumerate(LEVEL_SHARES))
    return f'CASE {cases} ELSE {len(LEVEL_SHARES)} END'


def _drift_case():
    cases = ' '.join(f'WHEN {_uniform("care-drift")} < {share} THEN {quarters}'
        for share, quarters in DRIFT_SHARES)
    return f'CASE {cases} END'


def _pdpm_factor(day):
    therapy = (f'CASE WHEN {day} < {THERAPY_STEP_FROM} THEN 1 ELSE 1 - {THERAPY_STEP} * '
        f'(({day} - {THERAPY_STEP_FROM}) / {THERAPY_STEP_DAYS} + 1) END')
    nta = f'CASE WHEN {day} <= {NTA_BOOST_THROUGH} THEN {NTA_BOOST} ELSE 1 END'
    return f'({1 - THERAPY_SHARE - NTA_SHARE} + {THERAPY_SHARE} * {therapy} + {NTA_SHARE} * {nta})'


def _draw(column, salt):
    """A deterministic draw in [0, 1) from any id column."""
    return (f"(('x' || substr(md5({column}::text || ':{salt}'), 1, 8))::bit(32)::bigint "
        '/ 4294967296.0)')


def _index(draw, shares):
    cases = ' '.join(f'WHEN {draw} < {share} THEN {index}' for index, share in enumerate(shares))
    return f'CASE {cases} ELSE {len(shares)} END'


def _letter(index):
    return f'chr(65 + {index})'


def assessment_sql(table, census):
    """One PDPM code per Medicare payer period, from its first census row."""
    column = 'c.payer_stay_id'
    pt_ot = (f'{_index(_draw(column, "pdpm-category"), PT_OT_CATEGORY_SHARES)} * 4 + '
        f'{_index(_draw(column, "pdpm-function"), PT_OT_FUNCTION_SHARES)}')
    nursing = 'CASE c.care_level ' + ' '.join(
        f"WHEN '{level}' THEN substr('{letters}', 1 + floor({_draw(column, 'pdpm-nursing')} * {len(letters)})::int, 1)"
        for level, letters in NURSING_BANDS.items()) + ' END'
    types = ', '.join(f"'{payer_type}'" for payer_type in PDPM_PAYER_TYPES)
    return f"""
INSERT INTO {table} (payer_stay_id, pdpm_code)
SELECT c.payer_stay_id,
       {_letter(pt_ot)} || {_letter(_index(_draw(column, 'pdpm-slp'), SLP_SHARES))}
       || {nursing} || {_letter(_index(_draw(column, 'pdpm-nta'), NTA_SHARES))}
FROM {census} c JOIN payers p ON p.payer_id = c.payer_id
WHERE c.segment = 1 AND p.payer_type IN ({types})
"""


def census_sql(table):
    levels = ', '.join(f"'{level}'" for level in LEVELS)
    multipliers = ', '.join(str(value) for value in LEVEL_MULTIPLIER)
    top = len(LEVELS) - 1
    step = f'n * c.quarters_per_step * {ASSESSMENT_DAYS}'
    return f"""
WITH through AS ({THROUGH}), periods AS (
    SELECT ps.payer_stay_id, ps.stay_id, s.resident_id, s.facility_id, ps.payer_id,
           s.admission_date, s.admission_number > 1 AS is_readmission,
           ps.start_date, ps.end_date, r.daily_rate AS base_rate
    FROM res_payer_stays ps
    JOIN res_stays s ON s.stay_id = ps.stay_id
    JOIN facility_payer_rates r ON r.facility_id = s.facility_id AND r.payer_id = ps.payer_id
    WHERE ps.start_date <= (SELECT day FROM through)
), care AS (
    SELECT c.*, {_level_case()} AS base_level, {_drift_case()} AS quarters_per_step
    FROM periods c
), bounds AS (
    -- The start of each payer period, and every date its care level changes.
    SELECT payer_stay_id, start_date AS bound FROM care
    UNION
    SELECT c.payer_stay_id, c.admission_date + {step}
    FROM care c CROSS JOIN LATERAL generate_series(1, {top} - c.base_level) n
    WHERE c.quarters_per_step IS NOT NULL
      AND c.admission_date + {step} > c.start_date
      AND c.admission_date + {step} < coalesce(c.end_date, 'infinity')
      AND c.admission_date + {step} <= (SELECT day FROM through)
), segments AS (
    SELECT payer_stay_id, bound AS segment_start,
           lead(bound) OVER w AS next_bound, row_number() OVER w AS segment
    FROM bounds WINDOW w AS (PARTITION BY payer_stay_id ORDER BY bound)
)
INSERT INTO {table} (payer_stay_id, segment, stay_id, resident_id, facility_id, payer_id,
    admission_date, is_readmission, care_level, in_bed, daily_rate)
SELECT c.payer_stay_id, g.segment, c.stay_id, c.resident_id, c.facility_id, c.payer_id,
       c.admission_date, c.is_readmission, (ARRAY[{levels}])[l.level + 1],
       daterange(g.segment_start, coalesce(g.next_bound, c.end_date, 'infinity'), '[)'),
       round(c.base_rate * (ARRAY[{multipliers}])[l.level + 1], 2)
FROM segments g
JOIN care c ON c.payer_stay_id = g.payer_stay_id
CROSS JOIN LATERAL (SELECT least({top}, c.base_level + CASE WHEN c.quarters_per_step IS NULL THEN 0
    ELSE (g.segment_start - c.admission_date) / ({ASSESSMENT_DAYS} * c.quarters_per_step) END) AS level) l
-- Written in order of when each stretch ends, so the rows in a bed on any day
-- sit together at the table's tail -- and today's, still open, are its last
-- pages. Every census-day list starts by finding them; scattered, that read
-- touched pages across the whole table.
ORDER BY coalesce(g.next_bound, c.end_date, 'infinity'), g.segment_start
"""


def pdpm_sql(table, census):
    """PDPM rate periods for skilled payer periods, from the census rows just built.

    Each step takes the rate of the census row containing its first day. Care
    level is reassessed quarterly and skilled coverage ends by day 100, so a
    step crossing a care level change is possible only in principle.
    """
    return f"""
WITH through AS ({THROUGH}), skilled AS (
    SELECT ps.payer_stay_id, ps.start_date, ps.end_date
    FROM res_payer_stays ps JOIN payers p ON p.payer_id = ps.payer_id
    WHERE p.is_skilled AND ps.start_date <= (SELECT day FROM through)
), starts AS (
    SELECT s.payer_stay_id, s.end_date, step.day, s.start_date + step.day - 1 AS step_start
    FROM skilled s CROSS JOIN (
        SELECT 1 AS day UNION ALL SELECT {NTA_BOOST_THROUGH + 1}
        UNION ALL SELECT generate_series({THERAPY_STEP_FROM}, 1100, {THERAPY_STEP_DAYS})) step
    WHERE s.start_date + step.day - 1 < coalesce(s.end_date, 'infinity')
      AND s.start_date + step.day - 1 <= (SELECT day FROM through)
), ordered AS (
    SELECT *, lead(step_start) OVER w AS next_start, row_number() OVER w AS step
    FROM starts WINDOW w AS (PARTITION BY payer_stay_id ORDER BY step_start)
)
INSERT INTO {table} (payer_stay_id, step, skilled_day, in_effect, pdpm_factor, daily_rate)
SELECT o.payer_stay_id, o.step, o.day,
       daterange(o.step_start, coalesce(o.next_start, o.end_date, 'infinity'), '[)'),
       f.factor, round(c.daily_rate * f.factor, 2)
FROM ordered o
JOIN {census} c ON c.payer_stay_id = o.payer_stay_id AND c.in_bed @> o.step_start
CROSS JOIN LATERAL (SELECT round({_pdpm_factor('o.day')}, 4) AS factor) f
-- In order of when each step ends, like census_logs, so one day's steps are together.
ORDER BY coalesce(o.next_start, o.end_date, 'infinity'), o.step_start
"""


class CensusLogGenerator(BaseGenerator):
    name = 'census_logs'
    table = schema.census_logs
    related_tables = (schema.pdpm_rate_logs, schema.pdpm_assessments)
    depends_on = ('res_stays', 'payer_rates')
    transaction_isolation = 'REPEATABLE READ'

    def prepare_sources(self, connection):
        if self.progress:
            self.progress.set_phase('Check payer periods and rates')
        periods, stays, rates = self.res_payer_stays, self.res_stays, self.facility_payer_rates
        through = connection.scalar(select(func.max(self.daily_runs.c.simulation_date))
            .where(self.daily_runs.c.generator == 'adt'))
        if through is None:
            raise ValueError('No simulated days yet. Run update before building census logs.')
        # The build joins every period to its rate. A period with no rate would be
        # dropped rather than reported, so refuse instead of losing residents.
        unrated = connection.scalar(select(func.count()).select_from(
            periods.join(stays, periods.c.stay_id == stays.c.stay_id)
            .outerjoin(rates, (rates.c.facility_id == stays.c.facility_id)
                & (rates.c.payer_id == periods.c.payer_id)))
            .where(periods.c.start_date <= through, rates.c.payer_id.is_(None)))
        if unrated:
            raise ValueError(f'{unrated:,} payer periods have no daily rate. '
                'Run python manage.py payer_rates --regenerate first.')
        self._periods = connection.scalar(select(func.count()).select_from(periods)
            .where(periods.c.start_date <= through))
        self._skilled = connection.scalar(select(func.count()).select_from(
            periods.join(self.payers, self.payers.c.payer_id == periods.c.payer_id))
            .where(periods.c.start_date <= through, self.payers.c.is_skilled))
        self._medicare = connection.scalar(select(func.count()).select_from(
            periods.join(self.payers, self.payers.c.payer_id == periods.c.payer_id))
            .where(periods.c.start_date <= through, self.payers.c.payer_type.in_(PDPM_PAYER_TYPES)))

    def expected_rows(self):
        return None

    def generate(self):
        raise ValueError('Census logs are built directly with INSERT ... SELECT.')

    def write_generated(self, connection):
        """Replace every row of both tables. Payer periods are edited after the
        fact, so any row may have changed; rebuilding is one pass over them."""
        driver = connection.connection.driver_connection
        census_table, pdpm_table = self.table, schema.pdpm_rate_logs
        census = self._table_identifier(census_table)
        pdpm = self._table_identifier(pdpm_table)
        assessments = self._table_identifier(schema.pdpm_assessments)
        self.show_table_progress(census_table)
        if self.progress:
            self.progress.set_phase('Remove previous logs')
        connection.exec_driver_sql(sql.SQL('TRUNCATE {}, {}, {}').format(census, pdpm, assessments).as_string(driver))

        if self.progress:
            self.progress.set_phase('Suspend keys for bulk replace')
        suspended = self.suspend_indexes(connection, census_table)
        if self.progress:
            self.progress.set_phase('Split stays by payer and care level',
                details=f'{self._periods:,} payer periods')
        census_rows = connection.exec_driver_sql(census_sql(census.as_string(driver))).rowcount
        covered = connection.scalar(select(func.count(func.distinct(census_table.c.payer_stay_id))))
        if covered != self._periods:
            raise ValueError('Saved payer periods changed while census logs were building; run again.')
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{census_rows:,} census rows')
        # Restored before the PDPM build, which looks census rows up by period.
        self.restore_indexes(connection, census_table, suspended)

        self.show_table_progress(pdpm_table)
        suspended = self.suspend_indexes(connection, pdpm_table)
        if self.progress:
            self.progress.set_phase('PDPM rate periods', details=f'{self._skilled:,} skilled payer periods')
        pdpm_rows = connection.exec_driver_sql(
            pdpm_sql(pdpm.as_string(driver), census.as_string(driver))).rowcount
        rated = connection.scalar(select(func.count(func.distinct(pdpm_table.c.payer_stay_id))))
        if rated != self._skilled:
            raise ValueError(f'{self._skilled - rated:,} skilled payer periods got no PDPM rate; run again.')
        if self.progress:
            self.progress.set_phase('Rebuild keys', details=f'{pdpm_rows:,} PDPM rows')
        self.restore_indexes(connection, pdpm_table, suspended)

        self.show_table_progress(schema.pdpm_assessments)
        if self.progress:
            self.progress.set_phase('PDPM codes', details=f'{self._medicare:,} Medicare payer periods')
        assessed = connection.exec_driver_sql(
            assessment_sql(assessments.as_string(driver), census.as_string(driver))).rowcount
        if assessed != self._medicare:
            raise ValueError(f'{self._medicare - assessed:,} Medicare payer periods got no PDPM code; run again.')
        written = census_rows + pdpm_rows + assessed
        return GenerationResult(generated=written, changed=written)


GENERATORS = (CensusLogGenerator,)


class DailyCensusLogs(DailyGenerator):
    """Rebuilt whole whenever days are added, because an added day can close or
    rewrite an earlier period. A checkpoint's count is the census rows starting
    that day."""
    name = 'census_logs'
    table = schema.census_logs
    owned_tables = (table, schema.pdpm_rate_logs, schema.pdpm_assessments)
    depends_on = ('adt',)
    bulk_dates = True

    def prepare_daily(self, connection):
        self._builder = CensusLogGenerator(self.database_url)
        self._builder.progress = self.progress
        self._builder.prepare_sources(connection)

    def run_dates(self, connection, days):
        self._builder.write_generated(connection)
        starts = dict(connection.execute(select(func.lower(self.table.c.in_bed), func.count())
            .where(func.lower(self.table.c.in_bed).in_(days))
            .group_by(func.lower(self.table.c.in_bed))).all())
        return {day: {self.table.name: starts.get(day, 0)} for day in days}

    def run_day(self, connection, day):
        return self.run_dates(connection, [day])[day]


DAILY_GENERATORS = (DailyCensusLogs,)
