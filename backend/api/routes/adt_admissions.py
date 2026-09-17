"""HTTP contracts; report work is delegated to services."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from api.services import adt_admissions as service

router = APIRouter(prefix='/api/v1/adt/admissions', tags=['ADT'])


@router.get('')
def list_recent_admissions(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: Annotated[list[str] | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    export_all: bool = False,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    payer_type: Annotated[list[str] | None, Query()] = None,
    admission_source: Annotated[list[str] | None, Query()] = None,
    sort_by: str = 'admission-date',
    sort_direction: str = 'descending',
    search: Annotated[str, Query(max_length=200)] = '',
    state: Annotated[list[str] | None, Query()] = None,
    portfolio: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    source_type: Annotated[list[str] | None, Query()] = None,
    payer_name: Annotated[list[str] | None, Query()] = None,
    is_readmission: bool | None = None,
) -> dict[str, Any]:
    return service.list_recent_admissions(
        days=days,
        start_date=start_date,
        end_date=end_date,
        facility=facility,
        offset=offset,
        export_all=export_all,
        page_size=page_size,
        payer_type=payer_type,
        admission_source=admission_source,
        sort_by=sort_by,
        sort_direction=sort_direction,
        search=search,
        state=state,
        portfolio=portfolio,
        region=region,
        source_type=source_type,
        payer_name=payer_name,
        is_readmission=is_readmission,
    )


@router.get('/filter-options')
def get_admissions_filter_options() -> dict:
    return service.get_admissions_filter_options()


@router.get('/daily-trend')
def get_admissions_daily_trend(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: Annotated[list[str] | None, Query()] = None,
    facility: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    portfolio: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_daily_trend(
        days=days,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        facility=facility,
        payer_type=payer_type,
        portfolio=portfolio,
        region=region,
    )


@router.get('/kpis')
def get_admissions_kpis(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    portfolio: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    return service.get_admissions_kpis(
        days=days,
        start_date=start_date,
        end_date=end_date,
        facility=facility,
        payer_type=payer_type,
        portfolio=portfolio,
        region=region,
    )


@router.get('/by-state')
def get_admissions_by_state(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_by_state(days=days, start_date=start_date, end_date=end_date)


@router.get('/by-region')
def get_admissions_by_region(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_by_region(days=days, start_date=start_date, end_date=end_date)


@router.get('/by-region/metrics')
def get_admissions_by_region_metrics(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: Annotated[list[str] | None, Query()] = None,
    level: str = 'portfolio',
    payer_type: Annotated[list[str] | None, Query()] = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_by_region_metrics(
        days=days,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        level=level,
        payer_type=payer_type,
    )


@router.get('/by-facility/metrics')
def get_admissions_by_facility_metrics(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_by_facility_metrics(
        days=days,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        payer_type=payer_type,
    )


@router.get('/by-region-and-payer')
def get_admissions_by_region_and_payer(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, list[Any]]:
    return service.get_admissions_by_region_and_payer(
        days=days,
        start_date=start_date,
        end_date=end_date,
    )


@router.get('/by-payer')
def get_admissions_by_payer(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_by_payer(days=days, start_date=start_date, end_date=end_date)


@router.get('/by-admission-source-type')
def get_admissions_by_source_type(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    portfolio: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_by_source_type(
        days=days,
        start_date=start_date,
        end_date=end_date,
        facility=facility,
        payer_type=payer_type,
        portfolio=portfolio,
        region=region,
    )


@router.get('/historical-comparisons')
def get_historical_comparisons(start_date: date, end_date: date):
    return service.get_historical_comparisons(start_date=start_date, end_date=end_date)


@router.get('/referring-hospital-location-performance')
def referring_hospital_location_performance(
    facility: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
) -> dict:
    return service.referring_hospital_location_performance(facility=facility, payer_type=payer_type)


@router.get('/referring-hospital-performance')
def referring_hospital_performance(
    facility: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    hospital: str | None = None,
) -> dict:
    return service.referring_hospital_performance(
        facility=facility,
        payer_type=payer_type,
        hospital=hospital,
    )


@router.get('/by-referring-hospital')
def get_admissions_by_referring_hospital(
    start_date: date,
    end_date: date,
    facility: Annotated[list[str] | None, Query()] = None,
    payer_type: Annotated[list[str] | None, Query()] = None,
    portfolio: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    source_type: Annotated[list[str] | None, Query()] = None,
) -> list[dict[str, Any]]:
    return service.get_admissions_by_referring_hospital(
        start_date=start_date,
        end_date=end_date,
        facility=facility,
        payer_type=payer_type,
        portfolio=portfolio,
        region=region,
        state=state,
        source_type=source_type,
    )


@router.get('/payer-by-facility')
def get_payer_by_facility(
    start_date: date,
    end_date: date,
    source_type: Annotated[list[str] | None, Query()] = None,
) -> list[dict[str, Any]]:
    return service.get_payer_by_facility(
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
    )
