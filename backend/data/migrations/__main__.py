"""Explicit, versioned schema upgrades. Never invoked by app startup or seed commands."""
import argparse
from sqlalchemy import Column, Integer, MetaData, Table, func, select, text
from data.db import get_engine
from data.migrations import v0001, v0002, v0003, v0004, v0005, v0006, v0007
from data.models import seed_tracking, monthly_activity

metadata = MetaData()
versions = Table('app_schema_migrations', metadata, Column('version', Integer, primary_key=True))
CURRENT_VERSION = 7


def require_schema(connection):
    if not connection.scalar(text("SELECT to_regclass('app_schema_migrations')")):
        raise ValueError('Apply the shared schema first: python -m data.migrations upgrade')
    if connection.scalar(select(func.max(versions.c.version))) != CURRENT_VERSION:
        raise ValueError('Database and application schema versions differ. Use matching code and shared migrations.')


def upgrade(connection):
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(current_schema() || :key))"), {'key': ':aspire-seeding'})
    metadata.create_all(connection)
    latest = connection.scalar(select(func.max(versions.c.version)))
    if latest is not None and latest > CURRENT_VERSION:
        raise ValueError('This database uses a newer schema than this application.')
    if connection.scalar(select(versions.c.version).where(versions.c.version == 1)) is None:
        v0001.upgrade(connection)
        seed_tracking.metadata.create_all(connection)
        monthly_activity.metadata.create_all(connection)
        connection.execute(versions.insert().values(version=1))
    if connection.scalar(select(versions.c.version).where(versions.c.version == 2)) is None:
        v0002.upgrade(connection)
        connection.execute(versions.insert().values(version=2))

    if connection.scalar(select(versions.c.version).where(versions.c.version == 3)) is None:
        v0003.upgrade(connection)
        connection.execute(versions.insert().values(version=3))
    if connection.scalar(select(versions.c.version).where(versions.c.version == 4)) is None:
        v0004.upgrade(connection)
        connection.execute(versions.insert().values(version=4))
    if connection.scalar(select(versions.c.version).where(versions.c.version == 5)) is None:
        v0005.upgrade(connection)
        connection.execute(versions.insert().values(version=5))
    if connection.scalar(select(versions.c.version).where(versions.c.version == 6)) is None:
        v0006.upgrade(connection)
        connection.execute(versions.insert().values(version=6))

    if connection.scalar(select(versions.c.version).where(versions.c.version == 7)) is None:
        v0007.upgrade(connection)
        connection.execute(versions.insert().values(version=7))



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('upgrade', 'configure-demo'))
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--instance-id', help='Explicit local demo identity; must match DEMO_INSTANCE_ID.')
    args = parser.parse_args()
    if args.preview:
        if args.command == 'configure-demo':
            print('Record this database as an explicitly configured demo target. No data is generated.')
            print('Offline preview only; no database connection or changes.')
            return
        print('Migration 1: shared ADT schema, reporting tables, seed completion and run tracking.')
        print('Migration 2: add Medicare HMO to the allowed admission payer types.')
        print('Migration 3: daily bed-hold snapshots for live census.')
        print('Migration 4: shared source identities/histories, scoped seed checkpoints and reporting coverage.')
        print('Migration 5: separate source/report publication tracking and facility reporting indexes.')
        print('Migration 6: durable resident-first source plans for resumable loading.')
        print('Migration 7: shared states and facility state foreign key; preserve existing data.')
        print('Offline preview only; no database connection or changes.')
        return
    with get_engine().begin() as connection:
        if args.command == 'upgrade':
            upgrade(connection)
        else:
            from common.config import get_settings
            from data.models.seed_operations import target_identity
            from sqlalchemy.dialects.postgresql import insert
            settings = get_settings()
            if settings.environment not in ('development', 'demo'):
                raise ValueError('Only an explicitly configured development/demo environment can be a seed target.')
            if not args.instance_id or args.instance_id != settings.demo_instance_id:
                raise ValueError('--instance-id must match the explicit DEMO_INSTANCE_ID configuration.')
            require_schema(connection)
            database_name = connection.scalar(text('SELECT current_database()'))
            existing = connection.execute(select(target_identity).where(target_identity.c.id == 1)).mappings().first()
            if existing and (existing['environment'] != 'demo' or existing['instance_id'] != args.instance_id
                             or existing['database_name'] != database_name):
                raise ValueError('Existing target identity differs; it cannot be silently reclassified.')
            connection.execute(insert(target_identity).values(id=1, environment='demo',
                database_name=database_name, instance_id=args.instance_id).on_conflict_do_nothing())
    print('Shared schema migration committed.' if args.command == 'upgrade' else 'Demo target identity recorded.')


if __name__ == '__main__':
    main()
