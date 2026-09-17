"""Report use cases with explicit snapshot ownership."""

from datetime import date
from typing import Literal

from api.queries import adt_payer_changes as queries
from api.services.connection import report_connection


def list_payer_changes(
    start_date: date,
    end_date: date,
    selections: dict,
    offset: int = 0,
    page_size: int = 50,
    export_all: bool = False,
    sort_by: str = 'effective_date',
    sort_direction: Literal['ascending', 'descending'] = 'descending',
    search: str = '',
) -> dict:
    with report_connection() as connection:
        return queries.list_payer_changes(
            connection,
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


def overview(start_date: date, end_date: date) -> dict:
    with report_connection() as connection:
        return queries.overview(connection, start_date=start_date, end_date=end_date)


def transitions(
    start_date: date,
    end_date: date,
    previous_payer_type: str,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
) -> list[dict]:
    with report_connection() as connection:
        return queries.transitions(
            connection,
            start_date=start_date,
            end_date=end_date,
            previous_payer_type=previous_payer_type,
            state=state,
            portfolio=portfolio,
            region=region,
            facility_name=facility_name,
        )
