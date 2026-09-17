"""Report use cases with explicit snapshot ownership."""

from typing import Any

from api.queries import facilities as queries
from api.services.connection import report_connection


def list_facilities() -> list[dict[str, Any]]:
    with report_connection() as connection:
        return queries.list_facilities(connection)
