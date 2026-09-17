"""SQL readers. Connections are supplied by services; imports never access a database."""

from datetime import date, timedelta
from typing import Literal

from sqlalchemy import String, cast, func, inspect, or_, select
from sqlalchemy.engine import Connection

from api.queries.errors import ReportQueryError
from api.queries.table_filters import PAYER_CHANGE_COLUMNS as COLUMNS
from api.queries.table_filters import SOURCES, filter_conditions
from common.time import business_date
from data.models.facilities import facilities
from data.models.payer_changes import payer_changes as events
"""Effective-date reporting for payer coverage changes."""


source = SOURCES["payer-changes"]


def validate_period(start_date: date, end_date: date):
    if start_date > end_date:
        raise ReportQueryError(422, "start_date must not be after end_date.")
    try:
        prior_start = start_date - timedelta(days=(end_date - start_date).days + 1)
    except OverflowError as error:
        raise ReportQueryError(422, "Date range exceeds the supported comparison period.") from error
    return prior_start, start_date - timedelta(days=1)


def require_data(connection: Connection):
    if not inspect(connection).has_table(events.name):
        raise ReportQueryError(503, "Payer changes are not available yet.")


def list_payer_changes(
    connection: Connection,
    start_date: date,
    end_date: date,
    selections: dict,
    offset: int = 0,
    page_size: int = 50,
    export_all: bool = False,
    sort_by: str = "effective_date",
    sort_direction: Literal["ascending", "descending"] = "descending",
    search: str = "",
) -> dict:
    validate_period(start_date, end_date)
    if sort_by not in COLUMNS:
        raise ReportQueryError(422, "Unknown payer change sort column.")
    filters = [events.c.effective_date.between(start_date, end_date)]
    filters.extend(filter_conditions(COLUMNS, selections, source.numeric_keys).values())
    if search.strip():
        filters.append(
            or_(
                *(
                    cast(column, String).icontains(search.strip(), autoescape=True)
                    for column in COLUMNS.values()
                )
            )
        )
    column = COLUMNS[sort_by]
    ordering = column.desc() if sort_direction == "descending" else column.asc()
    require_data(connection)
    total = connection.scalar(select(func.count()).select_from(source.joined).where(*filters))
    rows = (
        connection.execute(
            select(
                events.c.change_id,
                (
                    events.c.new_payer_end_date.is_(None)
                    | (events.c.new_payer_end_date > business_date())
                ).label("new_los_ongoing"),
                *(column.label(key) for key, column in COLUMNS.items()),
            )
            .select_from(source.joined)
            .where(*filters)
            .order_by(ordering, events.c.change_id)
            .limit(None if export_all else page_size)
            .offset(0 if export_all else offset)
        )
        .mappings()
        .all()
    )
    return {"items": [dict(row) for row in rows], "total": total}


def overview(connection: Connection, start_date: date, end_date: date) -> dict:
    prior_start, prior_end = validate_period(start_date, end_date)
    current = events.c.effective_date.between(start_date, end_date)
    counts = (
        select(
            events.c.facility_code,
            func.count().filter(current).label("total"),
            func.count(func.distinct(events.c.resident_id)).filter(current).label("residents"),
            func.count()
            .filter(events.c.effective_date.between(prior_start, prior_end))
            .label("prior"),
        )
        .where(
            events.c.effective_date.between(prior_start, end_date),
            events.c.change_category == "Payer type",
        )
        .group_by(events.c.facility_code)
        .subquery()
    )
    require_data(connection)
    rows = (
        connection.execute(
            select(
                facilities.c.facility_code,
                facilities.c.name.label("facility_name"),
                COLUMNS["state"].label("state"),
                facilities.c.portfolio,
                facilities.c.region,
                *(
                    func.coalesce(counts.c[key], 0).label(key)
                    for key in ("total", "residents", "prior")
                ),
            )
            .select_from(
                facilities.outerjoin(
                    counts,
                    facilities.c.facility_code == counts.c.facility_code,
                )
            )
            .order_by(facilities.c.facility_code)
        )
        .mappings()
        .all()
    )
    return {
        "items": [dict(row) for row in rows],
        "prior_start_date": prior_start,
        "prior_end_date": prior_end,
    }


def transitions(
    connection: Connection,
    start_date: date,
    end_date: date,
    previous_payer_type: str,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
) -> list[dict]:
    validate_period(start_date, end_date)
    filters = [
        events.c.effective_date.between(start_date, end_date),
        events.c.change_category == "Payer type",
        COLUMNS["previous_payer_type"] == previous_payer_type,
    ]
    filters.extend(
        COLUMNS[key] == value
        for key, value in (
            ("state", state),
            ("portfolio", portfolio),
            ("region", region),
            ("facility_name", facility_name),
        )
        if value is not None
    )
    require_data(connection)
    rows = (
        connection.execute(
            select(
                COLUMNS["new_payer_type"].label("label"),
                func.count().label("value"),
            )
            .select_from(source.joined)
            .where(*filters)
            .group_by(COLUMNS["new_payer_type"])
            .order_by(func.count().desc(), COLUMNS["new_payer_type"])
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
