"""Report use cases with explicit snapshot ownership."""

from datetime import date

from api.queries import adt_net_change as queries
from api.services.connection import report_connection


def daily_net_change(
    start_date: date,
    end_date: date,
    payer_type: list[str] | None = None,
    locations: str = '[]',
    path: str = '[]',
) -> dict:
    with report_connection() as connection:
        return queries.daily_net_change(
            connection,
            start_date=start_date,
            end_date=end_date,
            payer_type=payer_type,
            locations=locations,
            path=path,
        )


def monthly_locations(
    start_date: date,
    end_date: date,
    payer_type: list[str] | None = None,
) -> dict:
    with report_connection() as connection:
        return queries.monthly_locations(
            connection,
            start_date=start_date,
            end_date=end_date,
            payer_type=payer_type,
        )


def payer_net_change(start_date: date, end_date: date) -> dict:
    with report_connection() as connection:
        return queries.payer_net_change(connection, start_date=start_date, end_date=end_date)


def net_change(start_date: date, end_date: date, payer_type: list[str] | None = None) -> dict:
    with report_connection() as connection:
        return queries.net_change(
            connection,
            start_date=start_date,
            end_date=end_date,
            payer_type=payer_type,
        )
