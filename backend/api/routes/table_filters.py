"""HTTP contracts; report work is delegated to services."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from api.services import table_filters as service

router = APIRouter(prefix='/api/v1/table-filter-options', tags=['tables'])


@router.get('/{source_id}')
def get_table_filter_options(
    source_id: str,
    column: str,
    start_date: date,
    end_date: date,
    filters: Annotated[str, Query(max_length=100000)] = '{}',
    search: Annotated[str, Query(max_length=200)] = '',
) -> dict:
    return service.get_table_filter_options(
        source_id=source_id,
        column=column,
        start_date=start_date,
        end_date=end_date,
        filters=filters,
        search=search,
    )
