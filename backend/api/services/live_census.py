"""Report use cases with explicit snapshot ownership."""


from api.queries import live_census as queries
from api.services.connection import report_connection


def live_census() -> dict:
    with report_connection() as connection:
        return queries.live_census(connection)
