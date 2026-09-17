"""Reference edits use immutable codes; they never regenerate source histories."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from data.models import canonical as c
from data.writers.core import upsert_rows
from domain.identities import source_id


def upsert_payer_references(connection, records, *, organization_id="aspire-demo"):
    if connection.scalar(select(c.organizations.c.organization_id).where(
            c.organizations.c.organization_id == organization_id)) is None:
        raise ValueError("Create the organization before its payer references.")
    result = []
    for record in records:
        type_code, code = record["payer_type_code"], record["code"]
        plan_code = record.get("plan_code", code)
        type_id = source_id("shared", "references", "payer-type", type_code)
        payer_id = source_id(organization_id, "references", "payer", code)
        plan_id = source_id(organization_id, "references", "payer-plan", plan_code)
        prior_type = connection.scalar(select(c.payer_plans.c.payer_type_id).where(
            c.payer_plans.c.organization_id == organization_id,
            c.payer_plans.c.payer_plan_id == plan_id))
        if prior_type is not None and prior_type != type_id:
            raise ValueError("Changing a plan's payer type requires an explicit historical correction or new plan code.")
        upsert_rows(connection, c.payer_types, [dict(payer_type_id=type_id, code=type_code,
            name=record.get("type_name", type_code), is_active=record.get("type_active", True))])
        upsert_rows(connection, c.payers, [dict(organization_id=organization_id, payer_id=payer_id,
            code=code, name=record["name"], is_active=record.get("is_active", True))])
        upsert_rows(connection, c.payer_plans, [dict(organization_id=organization_id, payer_plan_id=plan_id,
            payer_id=payer_id, payer_type_id=type_id, code=plan_code,
            name=record.get("plan_name", record["name"]), is_active=record.get("is_active", True))])
        result.append(dict(payer_type_id=type_id, payer_id=payer_id, payer_plan_id=plan_id))
    return result


def ensure_legacy_payer(connection, organization_id, payer_type, payer_name):
    """Capture legacy text as an immutable source alias once, never as a live join key.

    Existing display names are deliberately not overwritten by repeat backfills.
    The old database did not distinguish insurer from plan; retain an explicit
    legacy-plan identity instead of inventing insurer relationships by name.
    """
    external_key = f"{len(payer_type)}:{payer_type}{payer_name}"
    key_query = select(c.payer_plan_source_keys.c.payer_plan_id).where(
        c.payer_plan_source_keys.c.organization_id == organization_id,
        c.payer_plan_source_keys.c.source_system == "legacy-adt",
        c.payer_plan_source_keys.c.external_key == external_key)
    existing = connection.scalar(key_query)
    if existing:
        return existing
    code = source_id(organization_id, "legacy-adt", "payer", external_key)
    type_id = source_id("shared", "references", "payer-type", payer_type)
    connection.execute(insert(c.payer_types).values(payer_type_id=type_id, code=payer_type,
        name="Commercial Medicare" if payer_type == "Medicare Advantage" else payer_type,
        is_active=True).on_conflict_do_nothing())
    payer_id = source_id(organization_id, "references", "payer", code)
    plan_id = source_id(organization_id, "references", "payer-plan", code)
    connection.execute(insert(c.payers).values(organization_id=organization_id, payer_id=payer_id,
        code=code, name=payer_name, is_active=True).on_conflict_do_nothing())
    connection.execute(insert(c.payer_plans).values(organization_id=organization_id, payer_plan_id=plan_id,
        payer_id=payer_id, payer_type_id=type_id, code=code, name=payer_name,
        is_active=True).on_conflict_do_nothing())
    upsert_rows(connection, c.payer_plan_source_keys, [dict(organization_id=organization_id,
        source_system="legacy-adt", external_key=external_key, payer_plan_id=plan_id)])
    return plan_id
