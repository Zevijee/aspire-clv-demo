"""Shared source lock identity; every writer/projector uses this same key."""
from sqlalchemy import text


def lock_source_scope(connection, organization_id):
    connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                       {'key': 'canonical-source:' + organization_id})
