"""Explicit demo hospital reference update, scoped through selected facilities."""
from sqlalchemy import select
from data.writers.core import write_rows
from seeding.reference_data.hospital_directory import HOSPITAL_DIRECTORY
from data.models.hospital_reporting import hospitals
from data.models.facilities import facilities
from seeding.base import BaseSeeder, SeedResult


def _selected(context):
    if not context.facility_codes:
        raise ValueError('Hospital definitions require explicit resolved facilities.')
    locations = set(context.connection.execute(select(facilities.c.state,facilities.c.portfolio,facilities.c.region)
        .where(facilities.c.facility_code.in_(context.facility_codes))).all())
    return [dict(hospital=name,**location) for name,location in HOSPITAL_DIRECTORY.items()
        if (location['state'],location['portfolio'],location['region']) in locations]

class HospitalsSeeder(BaseSeeder):
    name = 'hospitals'
    dependencies = ('facilities',)

    def seed(self, context):
        existing = {row['hospital']:dict(row) for row in context.connection.execute(select(hospitals)).mappings()}
        rows = _selected(context)
        if context.changed_fields:
            rows = [{key:value if key in context.changed_fields or key == 'hospital' else existing.get(row['hospital'],{}).get(key,value)
                for key,value in row.items()} for row in rows]
        changed = [row for row in rows if existing.get(row['hospital']) != row]
        if changed:
            write_rows(context.connection, hospitals, changed, batch_size=context.batch_size)
        return SeedResult(self.name,len(rows),len(changed))

    def validate(self, context, result):
        expected = _selected(context)
        actual = {row['hospital']:dict(row) for row in context.connection.execute(select(hospitals)).mappings()}
        if any(any(actual.get(row['hospital'],{}).get(key) != value for key,value in row.items()
            if not context.changed_fields or key in context.changed_fields or key == 'hospital') for row in expected):
            raise ValueError('Selected hospital references did not reconcile.')
