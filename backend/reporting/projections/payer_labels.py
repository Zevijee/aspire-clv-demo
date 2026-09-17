"""Refresh denormalized payer display labels without regenerating any events."""
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from data.models import canonical as c


def refresh_payer_labels(connection, organization_id, *, facility_codes=()):
    if not connection.in_transaction():
        raise ValueError('Payer label publication requires a caller-owned transaction.')
    plans = connection.execute(select(c.payer_plans.c.payer_plan_id, c.payer_plans.c.name,
        c.payer_types.c.code).select_from(c.payer_plans.join(c.payer_types,
            c.payer_types.c.payer_type_id == c.payer_plans.c.payer_type_id)).where(
                c.payer_plans.c.organization_id == organization_id)).mappings().all()
    for row in plans:
        alias = f"{len(row['code'])}:{row['code']}{row['name']}"
        existing = connection.scalar(select(c.payer_plan_source_keys.c.payer_plan_id).where(
            c.payer_plan_source_keys.c.organization_id == organization_id,
            c.payer_plan_source_keys.c.source_system == 'legacy-adt',
            c.payer_plan_source_keys.c.external_key == alias))
        if existing and existing != row['payer_plan_id']:
            raise ValueError('Two payer plans cannot share a type/name in the legacy serving contract.')
        connection.execute(insert(c.payer_plan_source_keys).values(organization_id=organization_id,
            source_system='legacy-adt', external_key=alias,
            payer_plan_id=row['payer_plan_id']).on_conflict_do_nothing())
    changed = 0
    scope = ' AND fact.facility_code=ANY(:codes)' if facility_codes else ''
    parameters = {'organization': organization_id, 'codes': list(facility_codes)}
    # Identifiers are schema-owned constants. Labels remain bound/query data.
    for table, kind, name in (
        ('adt_admissions', 'payer_type', 'payer_name'),
        ('adt_discharges', 'payer_type', 'payer_name'),
        ('adt_resident_stays', 'initial_payer_type', 'initial_payer_name'),
        ('adt_payer_periods', 'payer_type', 'payer_name'),
        ('adt_payer_changes', 'previous_payer_type', 'previous_payer_name'),
        ('adt_payer_changes', 'new_payer_type', 'new_payer_name'),
    ):
        changed += connection.execute(text(f"""
            UPDATE {table} fact SET {name}=p.name
            FROM facilities f, payer_plan_source_keys k JOIN payer_plans p
              ON p.organization_id=k.organization_id AND p.payer_plan_id=k.payer_plan_id
            WHERE fact.facility_code=f.facility_code AND f.organization_id=:organization
              AND k.organization_id=:organization AND k.source_system='legacy-adt'
              AND k.external_key=length(fact.{kind})::text || ':' || fact.{kind} || fact.{name}
              AND fact.{name} IS DISTINCT FROM p.name
              {scope}
        """), parameters).rowcount
    return changed
