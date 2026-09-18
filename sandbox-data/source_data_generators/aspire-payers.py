"""Payer reference rows from hard_coded_data/payers.json."""
from base import BaseGenerator


class PayerGenerator(BaseGenerator):
    """One payer per category/name pair, with a repeatable primary key."""
    name = 'payers'
    table = BaseGenerator.payers

    def expected_rows(self):
        return len(self.generate())

    def generate(self):
        return [dict(payer_id=self.source_id('payer', row['payer_type'], row['payer_name']),
            is_skilled=row['payer_type'] in self.SKILLED_PAYER_TYPES,
            **row) for row in self.load_payers()]


GENERATORS = (PayerGenerator,)
