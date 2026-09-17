"""Report use cases with explicit snapshot ownership."""

from datetime import date
from typing import Literal

from api.queries import adt_movement_logs as queries
from api.services.connection import report_connection


def list_movement_logs(
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
    with report_connection() as connection:
        return queries.list_movement_logs(
            connection,
            start_date=start_date,
            end_date=end_date,
            offset=offset,
            page_size=page_size,
            export_all=export_all,
            sort_by=sort_by,
            sort_direction=sort_direction,
            search=search,
            filters=filters,
        )
