"""Shared schema lifecycle and readiness checks; importing never connects to a DB."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import os

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url

from . import schema
from .backfills import runner as backfills
from .console import RunProgress, message

MIGRATIONS = Path(__file__).resolve().parent / 'migrations'


def postgres_url(value):
    url = make_url(value)
    if url.get_backend_name() != 'postgresql':
        raise ValueError('This project requires a PostgreSQL database URL.')
    return url.set(drivername='postgresql+psycopg')


def describe_url(value):
    """Name the database a command is about to touch, without its credentials.

    There is one database and it runs in Docker, but the host reaches it on a
    published port while containers reach it on the compose network. Printing the
    resolved target is what makes those two spellings obviously the same database.
    """
    url = make_url(value)
    port = f':{url.port}' if url.port else ''
    return f'{url.database} @ {url.host or "localhost"}{port}'


def configuration(connection=None, *, draft=False):
    config = Config()
    config.set_main_option('script_location', str(MIGRATIONS).replace('%', '%%'))
    if connection is not None:
        config.attributes['connection'] = connection
    if draft:
        from .staging import DRAFT, metadata
        config.set_main_option('path_separator', 'os')
        config.set_main_option('version_path_separator', 'os')
        config.set_main_option('version_locations', os.pathsep.join(
            (str(MIGRATIONS / 'versions'), str(DRAFT / 'migrations' / 'versions'))).replace('%', '%%'))
        config.attributes['target_metadata'] = metadata()
    return config


def scripts():
    result = ScriptDirectory.from_config(configuration())
    if len(result.get_heads()) != 1:
        raise ValueError('The shared schema must have one migration head. Resolve migration branches first.')
    return result


def upgrade_plan():
    revisions = list(reversed(list(scripts().walk_revisions())))
    positions = {item.revision: index for index, item in enumerate(revisions)}
    jobs = {job.name: job for job in backfills.ordered_jobs()}
    for job in jobs.values():
        if job.required_revision not in positions:
            raise ValueError(f'Backfill {job.name} requires an unknown revision: {job.required_revision}.')
    for item in revisions:
        for name in getattr(item.module, 'required_backfills', ()):
            remaining, checked = [name], set()
            while remaining:
                dependency = remaining.pop()
                if dependency in checked:
                    continue
                checked.add(dependency)
                if dependency not in jobs:
                    raise ValueError(f'Migration {item.revision} requires unknown backfill {dependency}.')
                job = jobs[dependency]
                ancestors = {parent.revision for parent in scripts().iterate_revisions(item.down_revision or (), 'base')}
                if job.required_revision not in ancestors:
                    raise ValueError(f'Migration/backfill dependency cycle: {item.revision} requires {dependency}, '
                        'whose schema prerequisite is not an earlier ancestor.')
                remaining.extend(job.depends_on)
    return revisions


def applied_revisions(connection):
    heads = MigrationContext.configure(connection).get_current_heads()
    return {revision.revision: revision for revision in scripts().iterate_revisions(heads, 'base')}


def revision_checksum(revision):
    files = [Path(revision.path)]
    for artifact in getattr(revision.module, 'artifacts', ()):
        path = (MIGRATIONS / artifact).resolve()
        if not path.is_relative_to(MIGRATIONS.resolve()):
            raise ValueError('Migration artifacts must remain inside the migrations directory.')
        files.append(path)
    digest = sha256()
    for path in sorted(files):
        digest.update(path.relative_to(MIGRATIONS).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_text(encoding='utf-8-sig').encode('utf-8'))
        digest.update(b'\0')
    return digest.hexdigest()


def validate_migration_history(connection):
    revisions = applied_revisions(connection)
    if not inspect(connection).has_table(schema.migration_checksums.name):
        if revisions:
            raise ValueError('Migration versions exist without their checksum history. '
                'Do not stamp a database manually; use its recorded migration history.')
        return revisions
    records = dict(connection.execute(select(schema.migration_checksums.c.revision,
        schema.migration_checksums.c.checksum)).all())
    if set(records) != set(revisions):
        raise ValueError('Migration versions and checksum history disagree. Restore the matching database/code history.')
    for name, revision in revisions.items():
        if records[name] != revision_checksum(revision):
            raise ValueError(f'Applied migration {name} changed. Restore it and add a new corrective revision.')
    return revisions


def ensure_compatible(connection, *, required_backfills=None):
    """Read-only startup guard usable by both the API and seeder. Never runs upgrades.

    The default requires every registered backfill. An API feature can explicitly
    supply its own required backfill IDs; unknown IDs fail closed.
    """
    expected = set(scripts().get_heads())
    actual = set(MigrationContext.configure(connection).get_current_heads())
    if actual != expected:
        raise ValueError('Database schema does not match this code version. Run python manage.py upgrade '
            'from sandbox-data using the matching checkout.')
    validate_migration_history(connection)
    records = backfills.validate_history(connection)
    registered = {job.name for job in backfills.ordered_jobs()}
    required = registered if required_backfills is None else set(required_backfills)
    if required - registered:
        raise ValueError('Unknown required backfills: ' + ', '.join(sorted(required - registered)))
    pending = [name for name in required if records.get(name, {}).get('status') != 'complete']
    if pending:
        raise ValueError('Database backfills are incomplete: ' + ', '.join(sorted(pending))
            + '. Run python manage.py upgrade to resume.')


@contextmanager
def lifecycle_lock(connection, *, shared=False):
    """Session lock survives batch commits; always release before pooling the connection."""
    suffix = '_shared' if shared else ''
    connection.exec_driver_sql(f'SELECT pg_advisory_lock{suffix}(1935766390, 1)')
    connection.commit()
    try:
        yield
    finally:
        if connection.in_transaction():
            connection.rollback()
        connection.exec_driver_sql(f'SELECT pg_advisory_unlock{suffix}(1935766390, 1)')
        connection.commit()


@contextmanager
def seed_guard(connection):
    with lifecycle_lock(connection, shared=True):
        with connection.begin():
            ensure_compatible(connection)
        yield


def schema_differences(connection):
    def include_object(obj, name, type_, reflected, compare_to):
        return not (type_ == 'table' and reflected and compare_to is None)

    context = MigrationContext.configure(connection, opts=dict(compare_type=True,
        compare_server_default=True, include_object=include_object))
    differences = compare_metadata(context, schema.metadata)
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    for table in schema.metadata.sorted_tables:
        if table.name in tables:
            actual = inspector.get_pk_constraint(table.name)['constrained_columns']
            if actual != [column.name for column in table.primary_key]:
                differences.append(('primary_key', table.name, actual))
    return differences


def drop_everything(database_url):
    """Drop this package's tables and its migration history, for a fresh rebuild.

    A full reset regenerates reference data, residents and ADT deterministically
    from the same seed and saved facility list, so clearing rows in place buys
    nothing: it only costs the delete, the dead tuples it leaves behind, and the
    ordering rules needed to respect foreign keys. Dropping the tables is O(1)
    each and also removes columns left over from abandoned schema experiments.

    Only tables declared in this package's metadata are dropped, never the whole
    schema, so unrelated tables sharing the database are left alone. The Alembic
    version table goes too, so the following upgrade recreates everything at head.
    """
    engine = create_engine(postgres_url(database_url))
    try:
        with RunProgress('database') as progress:
            progress.set_phase('Drop existing tables',
                details=f'{len(schema.metadata.tables)} tables and migration history')
            with engine.begin() as connection:
                schema.metadata.drop_all(connection, checkfirst=True)
                connection.exec_driver_sql('DROP TABLE IF EXISTS alembic_version')
            progress.set_phase('Complete', details='dropped; schema will be recreated at head')
    finally:
        engine.dispose()


def upgrade(database_url, *, data=True, batch_size=10000, max_batches=None):
    if batch_size < 1 or (max_batches is not None and max_batches < 1):
        raise ValueError('Batch size and maximum batches must be positive.')
    plan = upgrade_plan()
    engine = create_engine(postgres_url(database_url))
    try:
        with engine.connect() as connection, lifecycle_lock(connection):
            with connection.begin():
                before = validate_migration_history(connection)
            pending = [item for item in plan if item.revision not in before]
            applied = dict(before)
            batches = 0
            for item in pending:
                required = set(getattr(item.module, 'required_backfills', ()))
                if required:
                    if not inspect(connection).has_table(schema.backfill_runs.name):
                        connection.rollback()
                        raise ValueError(f'{item.revision} requires backfills before their tracking tables exist.')
                    connection.rollback()
                    if data:
                        remaining = None if max_batches is None else max_batches - batches
                        batches += backfills.run(connection, set(applied), batch_size=batch_size,
                            max_batches=remaining)
                    with connection.begin():
                        records = backfills.validate_history(connection)
                        incomplete = [name for name in required if records.get(name, {}).get('status') != 'complete']
                        if incomplete:
                            raise ValueError(f'{item.revision} requires completed backfills: '
                                + ', '.join(sorted(incomplete)) + '. Run upgrade to continue.')
                with RunProgress(item.revision) as progress:
                    progress.set_phase('Migrating')
                    with connection.begin():
                        command.upgrade(configuration(connection), item.revision)
                        after = applied_revisions(connection)
                        for name in sorted(set(after) - set(applied)):
                            connection.execute(schema.migration_checksums.insert().values(
                                revision=name, checksum=revision_checksum(after[name])))
                    progress.set_phase('Complete', details='migration applied')
                applied = after
            with connection.begin():
                differences = schema_differences(connection)
                if differences:
                    raise ValueError('Schema differs from the code after migrations. '
                        'Create/review a migration for: ' + repr(differences))
            if not pending:
                message('  Schema  up to date')
            if data:
                remaining = None if max_batches is None else max_batches - batches
                backfills.run(connection, set(applied), batch_size=batch_size, max_batches=remaining)
                with connection.begin():
                    ensure_compatible(connection)
    finally:
        engine.dispose()


def check(database_url):
    engine = create_engine(postgres_url(database_url))
    try:
        with engine.connect() as connection, seed_guard(connection):
            with connection.begin():
                differences = schema_differences(connection)
                if differences:
                    raise ValueError('Schema drift detected: ' + repr(differences))
        message('  Schema and history  match')
    finally:
        engine.dispose()


def status(database_url):
    engine = create_engine(postgres_url(database_url))
    try:
        with engine.connect() as connection, lifecycle_lock(connection, shared=True):
            with connection.begin():
                applied = validate_migration_history(connection)
                message('Migrations')
                for revision in reversed(list(scripts().walk_revisions())):
                    state = 'applied' if revision.revision in applied else 'pending'
                    message(f'  {state:<10} {revision.revision}')
                records = (backfills.validate_history(connection)
                    if inspect(connection).has_table(schema.backfill_runs.name) else {})
                message('\nBackfills')
                for job in backfills.ordered_jobs():
                    row = records.get(job.name, {})
                    message(f'  {row.get("status", "pending"):<10} {job.name}')
                    if row.get('processed') or row.get('changed'):
                        message(f'             {row.get("processed", 0):,} checked, {row.get("changed", 0):,} changed')
    finally:
        engine.dispose()


def revision(database_url, message):
    if not message or not message.strip():
        raise ValueError('Supply --message describing the schema change.')
    from .staging import DRAFT, validate_draft
    validate_draft()
    if any((DRAFT / 'migrations' / 'versions').glob('*.py')):
        raise ValueError('This draft already has a migration. Review/edit it or apply the draft before generating another.')
    engine = create_engine(postgres_url(database_url))
    try:
        with engine.connect() as connection, lifecycle_lock(connection, shared=True):
            with connection.begin():
                ensure_compatible(connection, required_backfills=())
                if schema_differences(connection):
                    raise ValueError('The active schema differs from the database. Restore active schema.py and edit staged/schema.py.')
                command.revision(configuration(connection, draft=True), message=message.strip(),
                    autogenerate=True, version_path=str(DRAFT / 'migrations' / 'versions'))
        # The parameter `message` is the revision description, not the console writer.
        from .console import message as report
        report('  Staged migration created; the running API is unchanged.')
        report('  Review shared/database/staged/, then run update to apply it and catch up data.')
    finally:
        engine.dispose()
