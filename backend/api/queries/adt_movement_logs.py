"""SQL readers. Connections are supplied by services; imports never access a database."""

from datetime import date
import json
from typing import Literal

from sqlalchemy import String, cast, func, inspect, or_, select
from sqlalchemy.engine import Connection

from api.queries.errors import ReportQueryError
from api.queries.table_filters import MOVEMENT_COLUMNS, SOURCES, filter_conditions
from reporting.projections.movement_logs import movement_logs


def list_movement_logs(
    connection: Connection,
    start_date: date,
    end_date: date,
    offset: int = 0,
    page_size: int = 50,
    export_all: bool = False,
    sort_by: str = 'move_date',
    sort_direction: Literal['ascending', 'descending'] = 'descending',
    search: str = '',
    filters: str = '{}',
) -> dict:
    source = SOURCES['net-change-logs']
    if start_date > end_date or sort_by not in MOVEMENT_COLUMNS:
        raise ReportQueryError(422, 'Invalid dates or sort column.')
    try:
        selections = json.loads(filters)
    except (ValueError, TypeError) as error:
        raise ReportQueryError(422, 'Invalid log filters.') from error
    if not isinstance(selections, dict) or any(
        key not in source.filter_keys or not isinstance(values, list)
        or any(not isinstance(value, str) for value in values)
        for key, values in selections.items()
    ):
        raise ReportQueryError(422, 'Invalid log filters.')
    conditions = [movement_logs.c.move_date.between(start_date, end_date),
                  *filter_conditions(MOVEMENT_COLUMNS, selections).values()]
    if search.strip():
        conditions.append(or_(*(cast(column, String).icontains(search.strip(), autoescape=True)
                                for column in MOVEMENT_COLUMNS.values())))
    column = MOVEMENT_COLUMNS[sort_by]
    ordering = column.desc().nulls_last() if sort_direction == 'descending' else column.asc().nulls_last()
    if not all(inspect(connection).has_table(name) for name in source.required_tables):
        raise ReportQueryError(503, 'Movement logs are not available yet.')
    total = connection.scalar(select(func.count()).select_from(source.joined).where(*conditions))
    items = connection.execute(select(
        movement_logs.c.move_id, *(column.label(key) for key, column in MOVEMENT_COLUMNS.items())
    ).select_from(source.joined).where(*conditions)
        .order_by(ordering, movement_logs.c.move_id)
        .limit(None if export_all else page_size).offset(0 if export_all else offset)).mappings().all()
    return {'items': [dict(row) for row in items], 'total': total}
