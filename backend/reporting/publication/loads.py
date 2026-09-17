"""Shared two-phase publication contract for demo loading and production ETL."""
from datetime import date
from sqlalchemy import select, func, text
from data.locking import lock_source_scope
from data.models.reporting_publication import loads
from reporting.planner import ReportScope


def require_no_pending_load(connection):
    # Allow the older schema to keep serving until migration 5 is explicitly applied.
    if connection.scalar(text("SELECT to_regclass('reporting_source_loads')")) and connection.scalar(
            select(loads.c.load_id).where(loads.c.status.not_in(('complete', 'superseded'))).limit(1)):
        from reporting.results.cache import ReportingUnavailableError
        raise ReportingUnavailableError('Source data or reporting summaries are being prepared. Complete or resume the load before opening reports.')


def finish_load(connection, load_id):
    row = connection.execute(select(loads).where(loads.c.load_id == load_id)).mappings().one_or_none()
    if row is None:
        raise ValueError('Unknown source load ID.')
    lock_source_scope(connection, row['organization_id'])
    row = connection.execute(select(loads).where(loads.c.load_id == load_id).with_for_update()).mappings().one()
    if row['status'] == 'complete':
        return {}
    if row['status'] == 'superseded':
        raise ValueError('This source load was superseded by a full reset; finish the replacement load instead.')
    if row['status'] != 'sources_complete':
        raise ValueError('Source loading is incomplete. Resume its loader before building reports.')
    from reporting.runner import refresh_reports
    from reporting.publication.state import publish
    results = {}
    if row['scope'].get('replace_history'):
        from reporting.runner import clear_facility_history
        for code in sorted({code for task in row['scope'].get('tasks', []) for code in task['facilities']}):
            clear_facility_history(connection, code)
    # Group facilities with the same dirty interval; never refresh per facility
    # when the requested interval is identical across the source batch.
    for task in row['scope'].get('tasks', []):
        scope = ReportScope(date.fromisoformat(task['from']), date.fromisoformat(task['through']),
            tuple(task['facilities']), organization_id=row['organization_id'])
        counts = refresh_reports(connection, task['reports'], scope, publish=False)
        for name, count in counts.items():
            results[name] = results.get(name, 0) + count
    publish(connection)
    connection.execute(loads.update().where(loads.c.load_id == load_id).values(status='complete', updated_at=func.now()))
    return results
