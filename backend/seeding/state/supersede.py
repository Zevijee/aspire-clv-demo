"""An explicit full reset may replace a failed demo load, never an active one."""
from sqlalchemy import select, func
from data.models.seed_tracking import runs
from data.models.seed_operations import source_plans
from data.models.reporting_publication import loads


def supersede_failed_load(connection, load_id, replacement_id, plan):
    # Caller already holds the organization source lock. A concurrent resume
    # may hold the run row while waiting for that lock: skip it, never deadlock
    # or take over a run whose ownership is changing.
    previous = connection.execute(select(runs).where(runs.c.run_id == load_id)
        .with_for_update(skip_locked=True)).mappings().one_or_none()
    if previous is None or previous['status'] != 'failed':
        raise ValueError(f'Source load {load_id} is active or not a failed demo run; full reset cannot replace it.')
    recorded = previous['plan']
    if recorded.get('organization_id') != plan.organization_id or not set(
            recorded.get('facility_codes', ())) <= set(plan.facility_codes):
        raise ValueError('Full reset does not cover the unfinished load scope.')
    connection.execute(runs.update().where(runs.c.run_id == load_id).values(
        status='superseded', finished_at=func.now()))
    scope = dict(connection.scalar(select(loads.c.scope).where(loads.c.load_id == load_id)))
    scope['superseded_by'] = replacement_id
    connection.execute(loads.update().where(loads.c.load_id == load_id).values(
        status='superseded', scope=scope, updated_at=func.now()))
    connection.execute(source_plans.delete().where(source_plans.c.run_id == load_id))
