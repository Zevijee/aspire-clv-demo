"""Discharge destinations and final payer LOS, using saved admission episodes.

LOS counts days from the final payer period's start to discharge, excluding the
discharge day, consistent with the saved payer periods' [start, end) dates.

Open stays have no discharge log. Death is a synthetic outcome eligible only on
a resident's final stay across all facilities, and only if that stay is closed.
Destination weights and death share are demo settings, not clinical statistics.
"""
from itertools import accumulate
from random import Random

from sqlalchemy import and_, func, select

from base import COPY_BATCH_SIZE, BaseGenerator, GenerationResult


class DischargeLogGenerator(BaseGenerator):
    name = 'discharge_logs'
    table = BaseGenerator.discharge_logs
    SEED = 42
    DECEASED_SHARE = 0.05
    DESTINATION_WEIGHTS = {
        'Hospital': 25, 'Skilled Nursing': 10, 'Home': 40,
        'Rehab Facility': 10, 'Assisted Living': 10, 'Community': 5,
    }
    DESTINATION_NAMES = {
        'Skilled Nursing': ('Maple Grove Nursing Center', 'Oakwood Skilled Nursing'),
        'Home': ('Private Residence', 'Family Residence'),
        'Rehab Facility': ('Cedar Ridge Rehabilitation Center', 'Meadowbrook Rehab Center'),
        'Assisted Living': ('Willow Court Assisted Living', 'Pinecrest Assisted Living'),
        'Community': ('Community Care Services', 'Local Senior Services'),
        'Funeral Home': ('Evergreen Memorial Funeral Home', 'Willow Brook Funeral Home'),
    }

    def prepare_sources(self, connection):
        hospitals = self.load_hospitals()
        self._hospital_choices = {}
        for row in self.read_rows(connection, select(self.regions.c.region_id, self.regions.c.region)):
            entries = hospitals.get(row['region'])
            if entries is not None:
                self._hospital_choices[row['region_id']] = (
                    tuple(entry['hospital'] for entry in entries),
                    tuple(accumulate(entry['score'] for entry in entries)))
        self._total = connection.scalar(select(func.count()).select_from(self.res_stays)
            .where(self.res_stays.c.discharge_date.is_not(None)))
        self._rng = Random(self.SEED)
        self._destination_types = tuple(self.DESTINATION_WEIGHTS)
        self._destination_cumulative = tuple(accumulate(self.DESTINATION_WEIGHTS.values()))

        stays, periods = self.res_stays, self.res_payer_stays
        # Include open stays in this window so a resident currently admitted
        # cannot be assigned a death on an earlier, already closed stay.
        history = select(stays.c.stay_id, stays.c.resident_id, stays.c.facility_id,
            stays.c.admission_date, stays.c.discharge_date,
            func.lead(stays.c.stay_id).over(partition_by=stays.c.resident_id,
                order_by=(stays.c.admission_date, stays.c.stay_id)).label('next_stay_id')
        ).subquery('stay_history')
        final_payers = select(periods.c.stay_id, periods.c.payer_id,
            periods.c.start_date, periods.c.end_date, periods.c.end_reason,
            func.row_number().over(partition_by=periods.c.stay_id,
                order_by=periods.c.period_number.desc()).label('payer_rank')
        ).subquery('final_payers')
        self._discharge_query = select(history.c.stay_id,
            history.c.admission_date, history.c.discharge_date, history.c.next_stay_id,
            self.facilities.c.region_id, final_payers.c.payer_id,
            final_payers.c.start_date.label('payer_start_date'),
            final_payers.c.end_date.label('payer_end_date'), final_payers.c.end_reason,
        ).select_from(history.outerjoin(self.facilities,
            history.c.facility_id == self.facilities.c.facility_id).outerjoin(final_payers,
            and_(final_payers.c.stay_id == history.c.stay_id, final_payers.c.payer_rank == 1))
        ).where(history.c.discharge_date.is_not(None)).order_by(
            history.c.resident_id, history.c.admission_date, history.c.stay_id)

    def expected_rows(self):
        return self._total

    def generate(self):
        """Transform an already-fetched batch without querying during COPY."""
        rng = self._rng
        for row in self._discharge_batch:
            if (row['payer_id'] is None or row['payer_start_date'] is None
                    or row['payer_end_date'] != row['discharge_date']
                    or row['end_reason'] != 'discharge'):
                raise ValueError(f"Stay {row['stay_id']} needs a final payer period matching its discharge.")
            los = (row['discharge_date'] - row['payer_start_date']).days
            if los <= 0:
                raise ValueError(f"Stay {row['stay_id']} must discharge after its final payer period starts.")
            is_deceased = row['next_stay_id'] is None and rng.random() < self.DECEASED_SHARE
            destination_type = ('Funeral Home' if is_deceased else rng.choices(
                self._destination_types, cum_weights=self._destination_cumulative, k=1)[0])
            if destination_type == 'Hospital':
                if row['region_id'] not in self._hospital_choices:
                    raise ValueError(f"Stay {row['stay_id']} has no hospital list for its saved facility region. "
                        'Add that region to hospitals.json before generating discharge logs.')
                names, cumulative = self._hospital_choices[row['region_id']]
                destination_name = rng.choices(names, cum_weights=cumulative, k=1)[0]
            else:
                destination_name = rng.choice(self.DESTINATION_NAMES[destination_type])
            yield dict(stay_id=row['stay_id'], discharge_date=row['discharge_date'],
                payer_id=row['payer_id'], destination_type=destination_type,
                destination_name=destination_name, is_deceased=is_deceased, los=los)

    def write_generated(self, connection):
        """Stream saved discharges in bounded batches and commit logs atomically."""
        stage = self.create_stage(connection, self.table)
        generated = 0
        if self.progress:
            self.progress.set_phase('Generate + COPY', total=self._total, unit='discharge logs')
        with connection.execute(self._discharge_query.execution_options(
                yield_per=COPY_BATCH_SIZE)) as result:
            for batch in result.mappings().partitions(COPY_BATCH_SIZE):
                self._discharge_batch = batch
                copied = self.copy_rows(connection, self.table, stage, self.generate())
                generated += copied
                if self.progress:
                    self.progress.advance(copied)
        self._discharge_batch = ()
        if generated != self._total:
            raise ValueError('Saved stays changed while discharge logs were loading; run again.')
        if self.progress:
            self.progress.set_phase('Merge', details=f'{generated:,} discharge logs staged')
        changed = self.merge_stage(connection, self.table, stage)
        return GenerationResult(generated=generated, changed=changed)


GENERATORS = (DischargeLogGenerator,)
