"""Report use cases with explicit snapshot ownership."""

from datetime import date

from api.queries import table_filters as queries
from api.services.connection import report_connection


def get_table_filter_options(
    source_id: str,
    column: str,
    start_date: date,
    end_date: date,
    filters: str = '{}',
    search: str = '',
) -> dict:
    with report_connection() as connection:
        return queries.get_table_filter_options(
            connection,
            source_id=source_id,
            column=column,
            start_date=start_date,
            end_date=end_date,
            filters=filters,
            search=search,
        )
