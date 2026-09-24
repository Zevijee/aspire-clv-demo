"""Daily rates each payer plan pays each facility, generated from rules.

Run: python manage.py payer_rates --regenerate

Pure reference data. Nothing in the simulation reads a rate back, so changing any
rule below rebuilds one table in seconds and needs no reseed.

The rules follow how skilled nursing is actually paid:

- Medicare Part A pays per resident under PDPM, driven by the facility's case mix
  and wage index. One plan, so the facility is where it varies.
- Medicare Advantage (HMO and commercial) negotiates per facility, typically well
  below traditional Medicare.
- Medicaid is set by the state. Managed care plans pay close to the state rate,
  and Medicaid Pending is billed at it once approved.
- Hospice pays the facility room and board at 95% of its Medicaid rate, by
  statute, whatever the hospice plan.
- VA and private pay are contract and list prices, varying by facility.
"""
from decimal import Decimal, ROUND_HALF_UP
from random import Random

from sqlalchemy import select

from base import BaseGenerator

SEED = 42
# National average per diem at the middle of every range below, in dollars.
BASE_RATE = {
    'medicare': 720, 'medicare_comm': 560, 'medicare_hmo': 520,
    'va': 460, 'private': 390, 'medicaid': 270,
}
HOSPICE_SHARE_OF_MEDICAID = Decimal('0.95')
# Wage index and state Medicaid policy move every payer in a state together.
STATE_RANGE = (0.85, 1.20)
# Case mix. Wider for Medicare, where acuity drives the PDPM rate.
FACILITY_RANGE = (0.94, 1.06)
MEDICARE_CASE_MIX_RANGE = (0.88, 1.15)
# Contract spread between plans at one facility.
PLAN_RANGE = {'medicaid': (0.97, 1.03)}
DEFAULT_PLAN_RANGE = (0.92, 1.08)
CENTS = Decimal('0.01')


class PayerRateGenerator(BaseGenerator):
    name = 'payer_rates'
    table = BaseGenerator.facility_payer_rates
    depends_on = ('facilities', 'payers')

    def prepare_sources(self, connection):
        self._facilities = self.read_rows(connection, select(
            self.facilities.c.facility_id, self.portfolios.c.state)
            .select_from(self.facilities.join(self.regions).join(self.portfolios))
            .order_by(self.facilities.c.facility_id))
        self._payers = self.read_rows(connection, select(
            self.payers.c.payer_id, self.payers.c.payer_type, self.payers.c.payer_name)
            .order_by(self.payers.c.payer_id))
        unknown = {row['payer_type'] for row in self._payers} - {*BASE_RATE, 'hospice'}
        if unknown:
            raise ValueError(f'No rate rule for payer types: {", ".join(sorted(unknown))}.')

    def expected_rows(self):
        return len(self._facilities) * len(self._payers)

    @staticmethod
    def _draw(bounds, *parts):
        return Random(BaseGenerator.source_id('payer-rate', SEED, *parts).int).uniform(*bounds)

    def generate(self):
        for facility in self._facilities:
            facility_id = str(facility['facility_id'])
            level = (self._draw(STATE_RANGE, 'state', facility['state'])
                * self._draw(FACILITY_RANGE, 'facility', facility_id))
            medicaid = BASE_RATE['medicaid'] * level
            for payer in self._payers:
                payer_type = payer['payer_type']
                if payer_type == 'hospice':
                    rate = Decimal(medicaid) * HOSPICE_SHARE_OF_MEDICAID
                elif payer['payer_name'] == 'Medicaid Pending':
                    rate = Decimal(medicaid)
                else:
                    rate = BASE_RATE[payer_type] * level
                    if payer_type == 'medicare':
                        rate *= self._draw(MEDICARE_CASE_MIX_RANGE, 'case-mix', facility_id)
                    else:
                        rate *= self._draw(PLAN_RANGE.get(payer_type, DEFAULT_PLAN_RANGE),
                            'plan', facility_id, str(payer['payer_id']))
                    rate = Decimal(rate)
                yield dict(facility_id=facility['facility_id'], payer_id=payer['payer_id'],
                    daily_rate=rate.quantize(CENTS, ROUND_HALF_UP))


GENERATORS = (PayerRateGenerator,)
