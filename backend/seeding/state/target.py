"""Explicit environment + database-identity protection for fake generation."""
from sqlalchemy import select, text
from common.config import get_settings
from data.models.seed_operations import target_identity


def require_demo_target(connection, instance_id=None):
    settings = get_settings()
    if settings.environment.lower() not in {'development', 'demo'}:
        raise ValueError('Fake generation is disabled outside development/demo environments.')
    expected = instance_id or settings.demo_instance_id
    if not expected:
        raise ValueError('Supply --demo-instance or DEMO_INSTANCE_ID after explicitly configuring this database as demo.')
    identity = connection.execute(select(target_identity).where(target_identity.c.id == 1)).mappings().one_or_none()
    name = connection.scalar(text('SELECT current_database()'))
    if identity is None or identity['environment'] != 'demo' or identity['database_name'] != name or identity['instance_id'] != expected:
        raise ValueError('Database demo identity does not match the explicitly requested target. Configure it through the migration CLI; generation will not claim it automatically.')
    return identity['instance_id']
