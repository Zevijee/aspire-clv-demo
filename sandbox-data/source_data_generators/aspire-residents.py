"""Residents per facility using the local first-name and surname lists."""
from base import BaseGenerator
from sqlalchemy import select


class ResidentGenerator(BaseGenerator):
    """Pick one 8-14 multiplier per facility and generate beds * multiplier residents.

    Resident IDs use the saved facility ID and row number. The same DB facilities and
    seed reproduce the same residents; names are unique across the generated set.
    This is the facility's resident population, not simultaneous bed occupancy.
    """
    name = 'residents'
    table = BaseGenerator.residents
    SEED = 42
    MIN_RESIDENTS_PER_BED = 8
    MAX_RESIDENTS_PER_BED = 14

    def prepare_sources(self, connection):
        self._facility_rows = self.read_rows(connection, select(
            self.facilities.c.facility_id, self.facilities.c.beds)
            .order_by(self.facilities.c.facility_id))

    def expected_rows(self):
        return sum(facility['resident_count'] for facility in self.resident_facilities(seed=self.SEED,
            minimum=self.MIN_RESIDENTS_PER_BED, maximum=self.MAX_RESIDENTS_PER_BED))

    def generate(self):
        facilities = self.resident_facilities(seed=self.SEED,
            minimum=self.MIN_RESIDENTS_PER_BED, maximum=self.MAX_RESIDENTS_PER_BED)

        total = sum(facility['resident_count'] for facility in facilities)
        names = self.random_names(total, seed=self.SEED)
        for facility in facilities:
            facility_id = facility['facility_id']
            resident_id = self.numbered_ids('resident', str(facility_id))
            for number in range(1, facility['resident_count'] + 1):
                yield dict(resident_id=resident_id(number),
                    facility_id=facility_id, **next(names))


GENERATORS = (ResidentGenerator,)
