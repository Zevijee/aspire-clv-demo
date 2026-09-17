"""Independent payer reference updates; no population regeneration."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from data.models import canonical as c
from data.writers.references import upsert_payer_references, ensure_legacy_payer
from seeding.reference_data.payers import PAYER_REFERENCES
from seeding.base import BaseSeeder, SeedResult

class PayersSeeder(BaseSeeder):
    name = 'payers'
    dependencies = ()

    def seed(self, context):
        organization = 'aspire-demo'
        context.connection.execute(insert(c.organizations).values(organization_id=organization,
            name='Aspire demo', reporting_timezone='America/New_York').on_conflict_do_nothing())
        selected = [row for row in PAYER_REFERENCES if not context.entity_ids or row['code'] in context.entity_ids]
        if context.entity_ids and len(selected) != len(context.entity_ids):
            raise ValueError('Unknown payer reference code in entity scope.')
        current = {row['code']: row['name'] for row in context.connection.execute(select(c.payers)
            .where(c.payers.c.organization_id == organization)).mappings()}
        types = dict(context.connection.execute(select(c.payer_types.c.code, c.payer_types.c.name)).all())
        if context.changed_fields:
            selected = [dict(row, name=row['name'] if 'name' in context.changed_fields else current.get(row['code'],row['name']),
                type_name=row['type_name'] if 'type_name' in context.changed_fields else types.get(row['payer_type_code'],row['type_name'])) for row in selected]
        changed = [row for row in selected if current.get(row['code']) != row['name'] or types.get(row['payer_type_code']) != row['type_name']]
        for row in selected:
            ensure_legacy_payer(context.connection, organization, row['source_type'], row['source_name'])
        if changed:
            upsert_payer_references(context.connection, changed, organization_id=organization)
        return SeedResult(self.name, len(selected), len(changed))

    def validate(self, context, result):
        return None
