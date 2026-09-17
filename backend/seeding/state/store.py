"""Transactional generator checkpoints and complete zero-activity days."""
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from data.models.seed_operations import boundaries
from data.models.seed_tracking import coverage
from data.writers.core import write_rows


def load_boundary(connection, dataset, scope_key, before, version, scenario_key):
    row = connection.execute(select(boundaries).where(boundaries.c.dataset == dataset,
        boundaries.c.scope_key == scope_key, boundaries.c.through_date < before)
        .order_by(boundaries.c.through_date.desc()).limit(1)).mappings().one_or_none()
    if row is None:
        return None
    if row['version'] != version or row['scenario_key'] != scenario_key:
        raise ValueError(f'Checkpoint for {dataset}/{scope_key} has incompatible versions; request a scoped rebuild.')
    return row['payload']


def save_boundary(connection, dataset, scope_key, through, version, scenario_key, payload):
    stmt = insert(boundaries).values(dataset=dataset, scope_key=scope_key, through_date=through,
        version=version, scenario_key=scenario_key, payload=payload)
    connection.execute(stmt.on_conflict_do_update(index_elements=[boundaries.c.dataset,
        boundaries.c.scope_key, boundaries.c.through_date], set_={name: getattr(stmt.excluded, name)
            for name in ('version', 'scenario_key', 'payload')}))


def mark_coverage(context, dataset, window, counts):
    rows = [dict(dataset=context.dataset_key(dataset), seed_date=window.start_date + timedelta(days=i),
        row_count=counts.get(window.start_date + timedelta(days=i), 0)) for i in range(window.days)]
    write_rows(context.connection, coverage, rows, batch_size=context.batch_size)
