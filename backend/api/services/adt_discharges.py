"""Report use cases with explicit snapshot ownership."""

from datetime import date
from typing import Any, Literal

from api.queries import adt_discharges as queries
from api.services.connection import report_connection


def list_discharges(
    start_date: date | None = None,
    end_date: date | None = None,
    days: int = 30,
    offset: int = 0,
    page_size: int = 50,
    export_all: bool = False,
    sort_by: str = 'discharge_date',
    sort_direction: Literal['ascending', 'descending'] = 'descending',
    search: str = '',
    resident_name: list[str] | None = None,
    facility_name: list[str] | None = None,
    state: list[str] | None = None,
    region: list[str] | None = None,
    portfolio: list[str] | None = None,
    payer_type: list[str] | None = None,
    payer_name: list[str] | None = None,
    discharge_type: list[str] | None = None,
    destination_type: list[str] | None = None,
    destination_name: list[str] | None = None,
) -> dict[str, Any]:
    with report_connection() as connection:
        return queries.list_discharges(
            connection,
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


def discharge_overview(
    start_date: date,
    end_date: date,
    payer_type: list[str] | None = None,
    destination_type: list[str] | None = None,
) -> dict:
    with report_connection() as connection:
        return queries.discharge_overview(
            connection,
            start_date=start_date,
            end_date=end_date,
            payer_type=payer_type,
            destination_type=destination_type,
        )


def discharges_by_type(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: list[str] | None = None,
    destination_type: list[str] | None = None,
    location: list[str] | None = None,
) -> list[dict]:
    with report_connection() as connection:
        return queries.discharges_by_type(
            connection,
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


def discharges_by_payer(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: list[str] | None = None,
    destination_type: list[str] | None = None,
    location: list[str] | None = None,
) -> list[dict]:
    with report_connection() as connection:
        return queries.discharges_by_payer(
            connection,
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


def discharges_by_destination(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: list[str] | None = None,
    destination_type: list[str] | None = None,
    location: list[str] | None = None,
) -> list[dict]:
    with report_connection() as connection:
        return queries.discharges_by_destination(
            connection,
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


def discharges_daily_trend(
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: list[str] | None = None,
    destination_type: list[str] | None = None,
    location: list[str] | None = None,
) -> list[dict]:
    with report_connection() as connection:
        return queries.discharges_daily_trend(
            connection,
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
