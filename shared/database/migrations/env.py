"""Alembic environment; connections come from the shared lifecycle runner."""
from alembic import context
from shared.database.schema import metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Other applications may own tables in the same database. Never propose dropping them.
    if type_ == 'table' and reflected and compare_to is None:
        return False
    return True


connection = context.config.attributes.get('connection')
if connection is None:
    raise ValueError('Use the shared database CLI; it supplies the database connection.')
context.configure(connection=connection, target_metadata=context.config.attributes.get('target_metadata', metadata),
    compare_type=True, compare_server_default=True, include_object=include_object)
with context.begin_transaction():
    context.run_migrations()
