"""Deterministic identity from immutable source keys, never display labels."""
from uuid import NAMESPACE_URL, uuid5


def source_id(organization_id: str, source_system: str, entity: str, external_key: str) -> str:
    if not all((organization_id, source_system, entity, external_key)):
        raise ValueError("Organization, source system, entity and external key are required.")
    # Length delimiters prevent ambiguous concatenations.
    values = (organization_id, source_system, entity, external_key)
    return str(uuid5(NAMESPACE_URL, "".join(f"{len(value)}:{value}" for value in values)))
