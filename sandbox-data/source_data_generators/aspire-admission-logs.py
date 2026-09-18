"""Admission logs linked to saved stays and their admission payer.

Hospital scores are relative weights within the facility's saved region.
Readmission means a later admission for the same resident at the same facility;
the 30-day flag additionally requires 0-30 days since the previous discharge.
"""
from itertools import accumulate
from random import Random

from sqlalchemy import and_, func, select

from base import COPY_BATCH_SIZE, BaseGenerator, GenerationResult


class AdmissionLogGenerator(BaseGenerator):
    name = 'admission_logs'
    table = BaseGenerator.admission_logs
    SEED = 42
    # Approximate demo baselines, varied by facility and calendar period.
    SOURCE_WEIGHTS = {
        'Hospital': 50, 'Home': 18, 'Skilled Nursing': 12,
        'Rehab Facility': 9, 'Assisted Living': 7, 'Community': 4,
    }
    SOURCE_NAMES = {
        'Skilled Nursing': ('Maple Grove Nursing Center', 'Oakwood Skilled Nursing'),
        'Home': ('Private Residence', 'Family Residence'),
        'Rehab Facility': ('Cedar Ridge Rehabilitation Center', 'Meadowbrook Rehab Center'),
        'Assisted Living': ('Willow Court Assisted Living', 'Pinecrest Assisted Living'),
        'Community': ('Community Care Services', 'Local Senior Services'),
    }

    @classmethod
    def pick_source_type(cls, facility_id, day, rng):
        mix = cls.varied_mix(cls.SEED, 'admission-source-types', facility_id, day,
            tuple(cls.SOURCE_WEIGHTS.items()))
        labels, weights = zip(*mix)
        return rng.choices(labels, weights=weights, k=1)[0]

    def prepare_sources(self, connection):
        hospitals = self.load_hospitals()
        self._hospital_choices = {}
        for row in self.read_rows(connection, select(self.regions.c.region_id, self.regions.c.region)):
            entries = hospitals.get(row['region'])
            if entries is not None:
                self._hospital_choices[row['region_id']] = (
                    tuple(entry['hospital'] for entry in entries),
                    tuple(accumulate(entry['score'] for entry in entries)))
        self._total = connection.scalar(select(func.count()).select_from(self.res_stays))
        self._remaining = self._total

        stays, periods = self.res_stays, self.res_payer_stays
        window = dict(partition_by=(stays.c.resident_id, stays.c.facility_id),
            order_by=(stays.c.admission_date, stays.c.stay_id))
        self._admission_query = select(
            stays.c.stay_id, stays.c.admission_date, stays.c.facility_id,
            self.facilities.c.region_id,
            periods.c.payer_id, periods.c.start_date.label('payer_start_date'),
            periods.c.start_reason,
            func.row_number().over(**window).label('admission_sequence'),
            func.lag(stays.c.discharge_date).over(**window).label('previous_discharge'),
        ).select_from(stays.outerjoin(self.facilities,
            stays.c.facility_id == self.facilities.c.facility_id).outerjoin(periods,
            and_(periods.c.stay_id == stays.c.stay_id, periods.c.period_number == 1))
        ).order_by(stays.c.resident_id, stays.c.facility_id,
            stays.c.admission_date, stays.c.stay_id)

    def expected_rows(self):
        return self._total

    def generate(self):
        """Transform one already-fetched batch; no queries while COPY is active."""
        for row in self._admission_batch:
            rng = Random(self.source_id('daily-admission-source', self.SEED, str(row['stay_id'])).int)
            if (row['payer_id'] is None or row['payer_start_date'] != row['admission_date']
                    or row['start_reason'] != 'admission'):
                raise ValueError(f"Stay {row['stay_id']} needs a first payer period matching its admission.")
            region_id = row['region_id']
            if region_id not in self._hospital_choices:
                raise ValueError(f"Stay {row['stay_id']} has no hospital list for its saved facility region. "
                    'Add that region to hospitals.json before generating admission logs.')
            if self._remaining <= 0:
                raise ValueError('Saved stays changed while admission logs were loading; run again.')
            source_type = self.pick_source_type(row['facility_id'], row['admission_date'], rng)
            if source_type == 'Hospital':
                names, cumulative = self._hospital_choices[region_id]
                source_name = rng.choices(names, cum_weights=cumulative, k=1)[0]
            else:
                source_name = rng.choice(self.SOURCE_NAMES[source_type])
            self._remaining -= 1
            is_readmission = row['admission_sequence'] > 1
            previous_discharge = row['previous_discharge']
            within_30_days = (is_readmission and previous_discharge is not None
                and 0 <= (row['admission_date'] - previous_discharge).days <= 30)
            yield dict(stay_id=row['stay_id'], admission_date=row['admission_date'],
                payer_id=row['payer_id'], source_type=source_type, source_name=source_name,
                is_readmission=is_readmission, is_30_day_readmission=within_30_days)

    def write_generated(self, connection):
        """Stream saved admissions in bounded batches, then COPY and merge atomically."""
        stage = self.create_stage(connection, self.table)
        generated = 0
        if self.progress:
            self.progress.set_phase('Generate + COPY', total=self._total, unit='admission logs')
        # Fetch between COPY operations: one server cursor, never a query per stay.
        with connection.execute(self._admission_query.execution_options(
                yield_per=COPY_BATCH_SIZE)) as result:
            for batch in result.mappings().partitions(COPY_BATCH_SIZE):
                self._admission_batch = batch
                copied = self.copy_rows(connection, self.table, stage, self.generate())
                generated += copied
                if self.progress:
                    self.progress.advance(copied)
        self._admission_batch = ()
        if self._remaining:
            raise ValueError('Saved stays changed while admission logs were loading; run again.')
        if self.progress:
            self.progress.set_phase('Merge', details=f'{generated:,} admission logs staged')
        changed = self.merge_stage(connection, self.table, stage)
        return GenerationResult(generated=generated, changed=changed)


GENERATORS = (AdmissionLogGenerator,)
