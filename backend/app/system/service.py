from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import daily_runs
from ..common.dates import today


def data_status(connection: Connection, report_timezone: str):
    day = today(report_timezone)
    statement = select(
        daily_runs.c.generator,
        func.min(daily_runs.c.simulation_date).label('first_completed_date'),
        func.max(daily_runs.c.simulation_date).label('latest_completed_date'),
        func.count().label('completed_days'),
        func.max(daily_runs.c.completed_at).label('last_completed_at'),
    ).group_by(daily_runs.c.generator).order_by(daily_runs.c.generator)
    generators = []
    for record in connection.execute(statement).mappings():
        row = dict(record)
        first, last = row['first_completed_date'], row['latest_completed_date']
        contiguous = row['completed_days'] == (last - first).days + 1
        row.update(contiguous=contiguous, complete_through_today=contiguous and first <= day <= last)
        generators.append(row)
    return dict(as_of=day, timezone=report_timezone, generated_at=datetime.now(timezone.utc), generators=generators)
