from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import (
    JSON,
    Column,
    Date,
    Integer,
    MetaData,
    String,
    Table,
    select,
    text,
)
from data.writers.core import write_rows

from seeding.base import BaseSeeder, SeedContext, SeedResult


from data.models.facilities import metadata, facilities
from seeding.reference_data.facilities import build_facility_rows

class FacilitiesSeeder(BaseSeeder):
    name = "facilities"
    dependencies = ('states', 'portfolios', 'regions')

    def seed(self, context: SeedContext) -> SeedResult:
        rows = [row for row in build_facility_rows() if not context.facility_codes or row["facility_code"] in context.facility_codes]
        existing = {
            row["facility_code"]: dict(row)
            for row in context.connection.execute(select(facilities)).mappings()
        }
        if context.changed_fields:
            rows = [{key: value if key in context.changed_fields or key == 'facility_code' else existing.get(row['facility_code'], {}).get(key,value)
                for key,value in row.items()} for row in rows]
        if context.canonical_first:
            from data.models import canonical as c
            from data.models.facilities import states
            known_states = set(context.connection.scalars(select(states.c.state_code)))
            known_portfolios = set(context.connection.scalars(select(c.portfolios.c.code).where(
                c.portfolios.c.organization_id == 'aspire-demo')))
            known_regions = set(context.connection.scalars(select(c.regions.c.code).where(
                c.regions.c.organization_id == 'aspire-demo')))
            for row in rows:
                portfolio = f"{row['state']}:{row['portfolio']}"
                region = f"{portfolio}:{row['region']}"
                if row['state'] not in known_states or portfolio not in known_portfolios or region not in known_regions:
                    raise ValueError('Location references are missing. Populate states, portfolios and regions before facilities.')
        changed = [row for row in rows if any(existing.get(row["facility_code"], {}).get(key) != value for key, value in row.items())]
        if context.operation != 'full-reset':
            for row in changed:
                prior = existing.get(row['facility_code'])
                if prior and prior.get('licensed_beds') != row['licensed_beds']:
                    from data.models.stays import census
                    if context.connection.scalar(select(census.c.census_date).where(census.c.facility_code == row['facility_code']).limit(1)):
                        raise ValueError('Reference update would change a populated facility capacity. This scenario needs an explicit coordinated capacity repair; ordinary update will not regenerate residents.')
        if changed:
            write_rows(context.connection, facilities, changed, batch_size=context.batch_size)
        return SeedResult(self.name, len(rows), len(changed))

    def validate(self, context, result):
        expected = [row for row in build_facility_rows() if not context.facility_codes or row['facility_code'] in context.facility_codes]
        actual = {row['facility_code']: dict(row) for row in context.connection.execute(select(facilities)).mappings()}
        if any(any(actual.get(row['facility_code'], {}).get(key) != value for key, value in row.items()
            if not context.changed_fields or key in context.changed_fields or key == 'facility_code') for row in expected):
            raise ValueError('Requested facility references did not reconcile to the selected demo definitions.')
