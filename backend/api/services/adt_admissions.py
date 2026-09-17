"""Report use cases with explicit snapshot ownership."""

from datetime import date
from typing import Any

from api.queries import adt_admissions as queries
from api.services.connection import report_connection
from reporting.results.cache import cached_report


@cached_report
def list_recent_admissions(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: list[str] | None = None,
    offset: int = 0,
    export_all: bool = False,
    page_size: int = 50,
    payer_type: list[str] | None = None,
    admission_source: list[str] | None = None,
    sort_by: str = 'admission-date',
    sort_direction: str = 'descending',
    search: str = '',
    state: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
    source_type: list[str] | None = None,
    payer_name: list[str] | None = None,
    is_readmission: bool | None = None,
) -> dict[str, Any]:
    with report_connection() as connection:
        return queries.list_recent_admissions(
            connection,
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


@cached_report
def get_admissions_filter_options() -> dict:
    with report_connection() as connection:
        return queries.get_admissions_filter_options(connection)


@cached_report
def get_admissions_daily_trend(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: list[str] | None = None,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_daily_trend(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
            source_type=source_type,
            facility=facility,
            payer_type=payer_type,
            portfolio=portfolio,
            region=region,
        )


@cached_report
def get_admissions_kpis(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
) -> dict[str, Any]:
    with report_connection() as connection:
        return queries.get_admissions_kpis(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
            facility=facility,
            payer_type=payer_type,
            portfolio=portfolio,
            region=region,
        )


@cached_report
def get_admissions_by_state(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_state(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )


@cached_report
def get_admissions_by_region(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_region(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )


@cached_report
def get_admissions_by_region_metrics(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: list[str] | None = None,
    level: str = 'portfolio',
    payer_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_region_metrics(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
            source_type=source_type,
            level=level,
            payer_type=payer_type,
        )


@cached_report
def get_admissions_by_facility_metrics(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: list[str] | None = None,
    payer_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_facility_metrics(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
            source_type=source_type,
            payer_type=payer_type,
        )


@cached_report
def get_admissions_by_region_and_payer(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, list[Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_region_and_payer(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )


@cached_report
def get_admissions_by_payer(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_payer(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )


@cached_report
def get_admissions_by_source_type(
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_source_type(
            connection,
            days=days,
            start_date=start_date,
            end_date=end_date,
            facility=facility,
            payer_type=payer_type,
            portfolio=portfolio,
            region=region,
        )


@cached_report
def get_historical_comparisons(start_date: date, end_date: date):
    with report_connection() as connection:
        return queries.get_historical_comparisons(
            connection,
            start_date=start_date,
            end_date=end_date,
        )


def referring_hospital_location_performance(
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
) -> dict:
    with report_connection() as connection:
        return queries.referring_hospital_location_performance(
            connection,
            facility=facility,
            payer_type=payer_type,
        )


def referring_hospital_performance(
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    hospital: str | None = None,
) -> dict:
    with report_connection() as connection:
        return queries.referring_hospital_performance(
            connection,
            facility=facility,
            payer_type=payer_type,
            hospital=hospital,
        )


@cached_report
def get_admissions_by_referring_hospital(
    start_date: date,
    end_date: date,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
    state: list[str] | None = None,
    source_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_admissions_by_referring_hospital(
            connection,
            start_date=start_date,
            end_date=end_date,
            facility=facility,
            payer_type=payer_type,
            portfolio=portfolio,
            region=region,
            state=state,
            source_type=source_type,
        )


@cached_report
def get_payer_by_facility(
    start_date: date,
    end_date: date,
    source_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.get_payer_by_facility(
            connection,
            start_date=start_date,
            end_date=end_date,
            source_type=source_type,
        )
