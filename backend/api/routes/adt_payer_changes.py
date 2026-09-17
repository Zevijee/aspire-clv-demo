"""HTTP contracts; report work is delegated to services."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from api.services import adt_payer_changes as service

router = APIRouter(prefix='/api/v1/adt/payer-changes', tags=['ADT'])


def log_selections(
    resident_name: Annotated[list[str] | None, Query()] = None,
    facility_name: Annotated[list[str] | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    portfolio: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    previous_payer_type: Annotated[list[str] | None, Query()] = None,
    previous_payer_name: Annotated[list[str] | None, Query()] = None,
    new_payer_type: Annotated[list[str] | None, Query()] = None,
    new_payer_name: Annotated[list[str] | None, Query()] = None,
    change_category: Annotated[list[str] | None, Query()] = None,
    previous_los_days: Annotated[list[str] | None, Query()] = None,
    new_los_days: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
) -> dict:
    return locals()


@router.get('')
def list_payer_changes(
    start_date: date,
    end_date: date,
    selections: Annotated[dict, Depends(log_selections)],
    offset: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    export_all: bool = False,
    sort_by: str = 'effective_date',
    sort_direction: Literal['ascending', 'descending'] = 'descending',
    search: Annotated[str, Query(max_length=200)] = '',
) -> dict:
    return service.list_payer_changes(
        start_date=start_date,
        end_date=end_date,
        selections=selections,
        offset=offset,
        page_size=page_size,
        export_all=export_all,
        sort_by=sort_by,
        sort_direction=sort_direction,
        search=search,
    )


@router.get('/overview')
def overview(start_date: date, end_date: date) -> dict:
    return service.overview(start_date=start_date, end_date=end_date)


@router.get('/transitions')
def transitions(
    start_date: date,
    end_date: date,
    previous_payer_type: str,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
) -> list[dict]:
    return service.transitions(
        start_date=start_date,
        end_date=end_date,
        previous_payer_type=previous_payer_type,
        state=state,
        portfolio=portfolio,
        region=region,
        facility_name=facility_name,
    )
