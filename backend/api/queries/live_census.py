"""SQL readers. Connections are supplied by services; imports never access a database."""

from datetime import date, timedelta

from sqlalchemy import func, select, inspect
from sqlalchemy.engine import Connection

from api.queries.errors import ReportQueryError
from api.queries.table_filters import state_label
from common.time import business_date
from data.models.bed_holds import bed_holds
from data.models.facilities import facilities
from data.models.stays import census, state
"""Current census and previous complete calendar month comparison."""


def live_census(connection: Connection) -> dict:
    today = business_date()
    previous_end = today.replace(day=1) - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    publication = connection.execute(select(state).where(state.c.id == 1)).mappings().one_or_none()
    if not publication or not publication["ready"]:
        raise ReportQueryError(503, "Census data needs refreshing.")
    current = select(census.c.facility_code, census.c.closing_census).where(
        census.c.census_date == today).subquery()
    previous = select(census.c.facility_code,
        func.avg(census.c.closing_census).label("average"),
        func.count().label("days")
    ).where(census.c.census_date.between(previous_start, previous_end)).group_by(
        census.c.facility_code).subquery()
    records = connection.execute(select(
        facilities.c.facility_code, facilities.c.name.label("facility_name"), state_label.label("state"),
        facilities.c.portfolio, facilities.c.region,
        facilities.c.licensed_beds.label("capacity"), current.c.closing_census.label("census"),
        previous.c.average, previous.c.days,
    ).select_from(facilities.outerjoin(current, current.c.facility_code == facilities.c.facility_code)
        .outerjoin(previous, previous.c.facility_code == facilities.c.facility_code))
        .where(facilities.c.opened_date <= today).order_by(facilities.c.name)).mappings()
    records = list(records)
    holds = dict(connection.execute(select(bed_holds.c.facility_code, bed_holds.c.bed_holds)
        .where(bed_holds.c.census_date == today)).all()) if inspect(connection).has_table("census_bed_holds_daily") else {}
    items = []
    for record in records:
        row = dict(record)
        average = row.pop("average")
        days = row.pop("days")
        row["previous_average"] = float(average) if days == previous_end.day and average is not None else None
        row["bed_holds"] = holds.get(row["facility_code"])
        items.append(row)
    return {"as_of": today.isoformat(), "available_through": publication["end_date"],
        "previous_month": previous_start.isoformat(), "items": items}
