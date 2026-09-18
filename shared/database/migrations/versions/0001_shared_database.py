"""Adopt the existing sandbox schema or create an empty database schema.

The frozen snapshot is deliberately independent of the live schema definitions.
Existing tables are validated before this revision is recorded; no blind stamping.
"""
from hashlib import sha256
from pathlib import Path

from alembic import op
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select

from shared.database.migrations.snapshots.v0001 import metadata, migration_history

revision = '0001_shared_database'
down_revision = None
branch_labels = None
depends_on = None
artifacts = ('snapshots/v0001.py', 'legacy/001_remove_state_counts.sql',
    'legacy/002_add_payer_is_skilled.sql')


def upgrade():
    connection = op.get_bind()
    migration_history.create(connection, checkfirst=True)
    applied = dict(connection.execute(select(migration_history.c.name, migration_history.c.checksum)).all())
    legacy = Path(__file__).resolve().parents[1] / 'legacy'
    files = sorted(legacy.glob('*.sql'))
    missing = set(applied) - {path.name for path in files}
    if missing:
        raise ValueError('Unknown legacy migration history: ' + ', '.join(sorted(missing)))
    for path in files:
        script = path.read_text(encoding='utf-8-sig')
        checksum = sha256(script.encode('utf-8')).hexdigest()
        if path.name in applied:
            if applied[path.name] != checksum:
                raise ValueError(f'Legacy migration {path.name} was changed. Restore the applied file.')
            continue
        connection.exec_driver_sql(script)
        connection.execute(migration_history.insert().values(name=path.name, checksum=checksum))

    existing = set(inspect(connection).get_table_names())

    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == 'table':
            return name in metadata.tables and name in existing
        return True

    context = MigrationContext.configure(connection, opts=dict(include_object=include_object,
        compare_type=True, compare_server_default=True))
    differences = compare_metadata(context, metadata)
    # Alembic does not compare primary keys; check those explicitly during adoption.
    inspector = inspect(connection)
    for table in metadata.sorted_tables:
        if table.name in existing:
            actual = inspector.get_pk_constraint(table.name)['constrained_columns']
            if actual != [column.name for column in table.primary_key]:
                raise ValueError(f'Cannot adopt {table.name}: primary key differs from the baseline.')
    if differences:
        raise ValueError('Existing schema differs from the supported sandbox baseline. '
            'Upgrade was rolled back; review these differences before writing a migration: '
            + repr(differences))
    metadata.create_all(connection, checkfirst=True)


def downgrade():
    raise ValueError('Adoption cannot be undone by dropping saved data. Add a corrective migration.')
