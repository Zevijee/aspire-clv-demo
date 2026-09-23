"""Referring hospital reference rows from hard_coded_data/hospitals.json."""
from sqlalchemy import select

from base import BaseGenerator


class ReferringHospitalGenerator(BaseGenerator):
    """One row per hospital, linked to the region it refers into.

    hospitals.json is keyed by region name and load_hospitals already rejects a
    duplicate hospital inside one region. The name is also the key that admission
    rows carry as source_name, so it has to be unique across regions too; a name
    used by two regions is ambiguous rather than harmless, and is rejected here.
    """
    name = 'referring_hospitals'
    table = BaseGenerator.referring_hospitals
    depends_on = ('regions',)

    def prepare_sources(self, connection):
        # Region names are unique across portfolios, so the name in hospitals.json
        # resolves to one region without needing its state and portfolio too.
        self._region_keys = {row['region']: row['region_id'] for row in self.read_rows(
            connection, select(self.regions.c.region_id, self.regions.c.region))}

    def expected_rows(self):
        return len(self.generate())

    def generate(self):
        rows, regions = [], {}
        for region, hospitals in sorted(self.load_hospitals().items()):
            region_id = self.parent_key(self._region_keys, region, 'regions')
            for entry in hospitals:
                hospital = entry['hospital']
                if hospital in regions:
                    raise ValueError(f'Hospital {hospital!r} is listed under both '
                        f'{regions[hospital]} and {region}. Hospital names identify the '
                        'referral source on every admission and must be unique.')
                regions[hospital] = region
                rows.append(dict(hospital=hospital, region_id=region_id))
        return sorted(rows, key=lambda row: row['hospital'])


GENERATORS = (ReferringHospitalGenerator,)
