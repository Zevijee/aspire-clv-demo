"""HTTP contracts; report work is delegated to services."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from api.services import adt_net_change as service

router = APIRouter(prefix='/api/v1/adt/net-change', tags=['ADT'])


@router.get('/daily')
def daily_net_change(
    start_date: date,
    end_date: date,
    payer_type: Annotated[list[str] | None, Query()] = None,
    locations: str = '[]',
    path: str = '[]',
) -> dict:
    return service.daily_net_change(
        start_date=start_date,
        end_date=end_date,
        payer_type=payer_type,
        locations=locations,
        path=path,
    )


@router.get('/monthly-locations')
def monthly_locations(
    start_date: date,
    end_date: date,
    payer_type: Annotated[list[str] | None, Query()] = None,
) -> dict:
    return service.monthly_locations(
        start_date=start_date,
        end_date=end_date,
        payer_type=payer_type,
    )


@router.get('/payers')
def payer_net_change(start_date: date, end_date: date) -> dict:
    return service.payer_net_change(start_date=start_date, end_date=end_date)


@router.get('')
def net_change(
    start_date: date,
    end_date: date,
    payer_type: Annotated[list[str] | None, Query()] = None,
) -> dict:
    return service.net_change(start_date=start_date, end_date=end_date, payer_type=payer_type)
