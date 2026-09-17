"""HTTP contracts; report work is delegated to services."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from api.services import adt_movement_logs as service

router = APIRouter(prefix='/api/v1/adt/net-change/logs', tags=['ADT'])


@router.get('')
def list_movement_logs(
    start_date: date,
    end_date: date,
    offset: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    export_all: bool = False,
    sort_by: str = 'move_date',
    sort_direction: Literal['ascending', 'descending'] = 'descending',
    search: Annotated[str, Query(max_length=200)] = '',
    filters: Annotated[str, Query(max_length=100000)] = '{}',
) -> dict:
    return service.list_movement_logs(
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
