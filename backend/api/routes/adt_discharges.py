"""HTTP contracts; report work is delegated to services."""

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from api.services import adt_discharges as service

router = APIRouter(prefix='/api/v1/adt/discharges', tags=['ADT'])


@router.get('')
def list_discharges(
    start_date: date | None = None,
    end_date: date | None = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    export_all: bool = False,
    sort_by: str = 'discharge_date',
    sort_direction: Literal['ascending', 'descending'] = 'descending',
    search: Annotated[str, Query(max_length=200)] = '',
    resident_name: Annotated[list[str] | None, Query()] = None,
    facility_name: Annotated[list[str] | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    portfolio: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    payer_name: Annotated[list[str] | None, Query()] = None,
    discharge_type: Annotated[list[str] | None, Query()] = None,
    destination_type: Annotated[list[str] | None, Query()] = None,
    destination_name: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    return service.list_discharges(
        start_date=start_date,
        end_date=end_date,
        days=days,
        offset=offset,
        page_size=page_size,
        export_all=export_all,
        sort_by=sort_by,
        sort_direction=sort_direction,
        search=search,
        resident_name=resident_name,
        facility_name=facility_name,
        state=state,
        region=region,
        portfolio=portfolio,
        payer_type=payer_type,
        payer_name=payer_name,
        discharge_type=discharge_type,
        destination_type=destination_type,
        destination_name=destination_name,
    )


@router.get('/overview')
def discharge_overview(
    start_date: date,
    end_date: date,
    payer_type: Annotated[list[str] | None, Query()] = None,
    destination_type: Annotated[list[str] | None, Query()] = None,
) -> dict:
    return service.discharge_overview(
        start_date=start_date,
        end_date=end_date,
        payer_type=payer_type,
        destination_type=destination_type,
    )


@router.get('/by-type')
def discharges_by_type(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    destination_type: Annotated[list[str] | None, Query()] = None,
    location: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    return service.discharges_by_type(
        start_date=start_date,
        end_date=end_date,
        state=state,
        portfolio=portfolio,
        region=region,
        facility_name=facility_name,
        payer_type=payer_type,
        destination_type=destination_type,
        location=location,
    )


@router.get('/by-payer')
def discharges_by_payer(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    destination_type: Annotated[list[str] | None, Query()] = None,
    location: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    return service.discharges_by_payer(
        start_date=start_date,
        end_date=end_date,
        state=state,
        portfolio=portfolio,
        region=region,
        facility_name=facility_name,
        payer_type=payer_type,
        destination_type=destination_type,
        location=location,
    )


@router.get('/by-destination')
def discharges_by_destination(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    destination_type: Annotated[list[str] | None, Query()] = None,
    location: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    return service.discharges_by_destination(
        start_date=start_date,
        end_date=end_date,
        state=state,
        portfolio=portfolio,
        region=region,
        facility_name=facility_name,
        payer_type=payer_type,
        destination_type=destination_type,
        location=location,
    )


@router.get('/daily-trend')
def discharges_daily_trend(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    destination_type: Annotated[list[str] | None, Query()] = None,
    location: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    return service.discharges_daily_trend(
        start_date=start_date,
        end_date=end_date,
        state=state,
        portfolio=portfolio,
        region=region,
        facility_name=facility_name,
        payer_type=payer_type,
        destination_type=destination_type,
        location=location,
    )
