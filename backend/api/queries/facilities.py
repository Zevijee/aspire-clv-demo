"""SQL readers. Connections are supplied by services; imports never access a database."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from data.models.facilities import facilities


def list_facilities(connection: Connection) -> list[dict[str, Any]]:
    """Return the configured facility portfolio in stable code order."""

    results = connection.execute(
        select(
            facilities.c.facility_code,
            facilities.c.name,
            facilities.c.city,
            facilities.c.state,
            facilities.c.portfolio,
            facilities.c.region,
            facilities.c.market,
            facilities.c.operating_group,
            facilities.c.licensed_beds,
            facilities.c.opened_date,
        ).order_by(facilities.c.facility_code)
    )
    return [dict(row) for row in results.mappings()]
