"""Independent location references, persisted before facilities use them."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from data.models.facilities import states
from data.models import canonical as c
from data.writers.core import write_rows
from domain.identities import source_id
from domain.us_states import US_STATES
from seeding.base import BaseSeeder, SeedResult
from seeding.reference_data.facilities import build_facility_rows


def selected_facilities(context):
    return [row for row in build_facility_rows()
        if not context.facility_codes or row['facility_code'] in context.facility_codes]


class StatesSeeder(BaseSeeder):
    name = 'states'

    def seed(self, context):
        codes = sorted({row['state'] for row in selected_facilities(context)})
        rows = [dict(state_code=code, name=US_STATES[code]) for code in codes]
        result = write_rows(context.connection, states, rows, batch_size=context.batch_size)
        return SeedResult(self.name, len(rows), result.changed)

    def validate(self, context, result):
        pass


class PortfoliosSeeder(BaseSeeder):
    name = 'portfolios'

    def seed(self, context):
        context.connection.execute(insert(c.organizations).values(organization_id='aspire-demo',
            name='Aspire demo', reporting_timezone='America/New_York').on_conflict_do_nothing())
        rows = {}
        for facility in selected_facilities(context):
            code = f"{facility['state']}:{facility['portfolio']}"
            rows[code] = dict(organization_id='aspire-demo',
                portfolio_id=source_id('aspire-demo', 'legacy-adt', 'portfolio', code),
                code=code, name=facility['portfolio'])
        result = write_rows(context.connection, c.portfolios, rows.values(), batch_size=context.batch_size)
        return SeedResult(self.name, len(rows), result.changed)

    def validate(self, context, result):
        pass


class RegionsSeeder(BaseSeeder):
    name = 'regions'
    dependencies = ('portfolios',)

    def seed(self, context):
        portfolios = set(context.connection.scalars(select(c.portfolios.c.code).where(
            c.portfolios.c.organization_id == 'aspire-demo')))
        rows = {}
        for facility in selected_facilities(context):
            parent = f"{facility['state']}:{facility['portfolio']}"
            if parent not in portfolios:
                raise ValueError('Portfolio references are missing. Populate portfolios before regions.')
            code = f"{parent}:{facility['region']}"
            rows[code] = dict(organization_id='aspire-demo',
                region_id=source_id('aspire-demo', 'legacy-adt', 'region', code),
                code=code, name=facility['region'])
        result = write_rows(context.connection, c.regions, rows.values(), batch_size=context.batch_size)
        return SeedResult(self.name, len(rows), result.changed)

    def validate(self, context, result):
        pass
