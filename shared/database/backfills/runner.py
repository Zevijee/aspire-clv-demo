"""Versioned backfills. Each batch and its checkpoint commit in one transaction."""
from hashlib import sha256
from pathlib import Path

from sqlalchemy import inspect, select, func

from shared.database.schema import backfill_runs
from shared.database.console import RunProgress
from . import discharge_payer_los_v1

JOBS = (discharge_payer_los_v1,)


def ordered_jobs():
    registry = {job.name: job for job in JOBS}
    if len(registry) != len(JOBS):
        raise ValueError('Duplicate backfill IDs.')
    ordered, visiting, done = [], set(), set()

    def visit(name):
        if name in done:
            return
        if name in visiting or name not in registry:
            raise ValueError(f'Invalid backfill dependency: {name}.')
        visiting.add(name)
        job = registry[name]
        for parent in job.depends_on:
            visit(parent)
        visiting.remove(name)
        done.add(name)
        ordered.append(job)

    for name in registry:
        visit(name)
    return ordered


def checksum(job):
    # Keep transformation SQL/code in the immutable job, not mutable shared helpers.
    return sha256(Path(job.__file__).read_text(encoding='utf-8-sig').encode('utf-8')).hexdigest()


def validate_history(connection):
    jobs = {job.name: job for job in ordered_jobs()}
    records = {row['name']: row for row in connection.execute(select(backfill_runs)).mappings()}
    for name, record in records.items():
        if name not in jobs or record['checksum'] != checksum(jobs[name]):
            raise ValueError(f'Backfill {name} is missing or changed. Restore it and add a new job ID.')
    return records


def run(connection, revisions, *, batch_size=10000, max_batches=None):
    """Caller holds the exclusive lifecycle lock across all batch transactions."""
    batches = 0
    with connection.begin():
        validate_history(connection)
    for job in ordered_jobs():
        with RunProgress(job.name) as progress:
            progress.set_phase('Backfill', unit='rows this run')
            while True:
                if max_batches is not None and batches >= max_batches:
                    progress.set_phase('Paused', details='batch limit reached; rerun upgrade to resume')
                    return batches
                with connection.begin():
                    row = connection.execute(select(backfill_runs).where(backfill_runs.c.name == job.name)).mappings().first()
                    if row and row['status'] == 'complete':
                        progress.set_phase('Skipped', details='already complete')
                        break
                    if row is None:
                        connection.execute(backfill_runs.insert().values(name=job.name, checksum=checksum(job),
                            status='pending', checkpoint={}, processed=0, changed=0))
                        row = dict(checkpoint={}, processed=0, changed=0)
                    complete = set(connection.scalars(select(backfill_runs.c.name).where(backfill_runs.c.status == 'complete')))
                    tables = set(inspect(connection).get_table_names())
                    reason = None
                    if job.required_revision not in revisions:
                        reason = 'required schema revision is not applied'
                    elif set(job.depends_on) - complete:
                        reason = 'prerequisite backfills are incomplete'
                    elif set(job.required_tables) - tables:
                        reason = 'source tables are absent'
                    elif hasattr(job, 'ready'):
                        # Return None when ready, or a reason to retry on a later upgrade.
                        reason = job.ready(connection)
                    if reason:
                        connection.execute(backfill_runs.update().where(backfill_runs.c.name == job.name)
                            .values(status='deferred', updated_at=func.now()))
                        progress.set_phase('Deferred', details=reason)
                        break
                    checkpoint, processed, changed, finished = job.run_batch(connection, row['checkpoint'], batch_size)
                    if processed == 0 and not finished:
                        raise ValueError(f'Backfill {job.name} made no progress; batch rolled back.')
                    connection.execute(backfill_runs.update().where(backfill_runs.c.name == job.name).values(
                        status='complete' if finished else 'running', checkpoint=checkpoint,
                        processed=row['processed'] + processed, changed=row['changed'] + changed,
                        updated_at=func.now()))
                batches += 1
                details = (f'{row["processed"] + processed:,} checked, '
                    f'{row["changed"] + changed:,} changed')
                progress.advance(processed, details=details)
                if finished:
                    progress.set_phase('Complete', details=details)
                    break
    return batches
