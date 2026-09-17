"""SQL readers. Connections are supplied by services; imports never access a database."""

from datetime import date, timedelta
import json
from typing import Any, Literal

from sqlalchemy import String, and_, cast, func, inspect, or_, select
from sqlalchemy.engine import Connection

from api.queries.errors import ReportQueryError
from api.queries.table_filters import DISCHARGE_COLUMNS, SOURCES, table_filter_options
from data.models.adt_values import DISCHARGE_TYPES
from data.models.adt_values import PAYER_TYPES
from data.models.discharges import discharges
from data.models.facilities import facilities


COLUMNS = DISCHARGE_COLUMNS
FILTER_KEYS = SOURCES["discharges"].filter_keys


def list_discharges(
    connection: Connection,
    start_date: date | None = None,
    end_date: date | None = None,
    days: int = 30,
    offset: int = 0,
    page_size: int = 50,
    export_all: bool = False,
    sort_by: str = "discharge_date",
    sort_direction: Literal["ascending", "descending"] = "descending",
    search: str = "",
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
    """Paginate discharge events by discharge date; start_date on each row begins its stay."""
    if (start_date is None) != (end_date is None):
        raise ReportQueryError(422, "start_date and end_date must be provided together.")
    if start_date is not None and start_date > end_date:
        raise ReportQueryError(422, "start_date must not be after end_date.")
    if sort_by not in COLUMNS:
        raise ReportQueryError(422, "Unknown discharge sort column.")
    selections = {
        "resident_name": resident_name,
        "facility_name": facility_name,
        "state": state,
        "region": region,
        "portfolio": portfolio,
        "payer_type": payer_type,
        "payer_name": payer_name,
        "discharge_type": discharge_type,
        "destination_type": destination_type,
        "destination_name": destination_name,
    }
    joined = discharges.join(facilities, discharges.c.facility_code == facilities.c.facility_code)
    if not inspect(connection).has_table("adt_discharges"):
        raise ReportQueryError(503, "Discharge reporting data is not available yet.")
    if start_date is None:
        end_date = connection.scalar(select(func.max(discharges.c.discharge_date)))
        if end_date is None:
            return {"items": [], "total": 0, "filter_options": {key: [] for key in FILTER_KEYS}}
        start_date = end_date - timedelta(days=days - 1)
    period = discharges.c.discharge_date.between(start_date, end_date)
    base_filters = [period]
    column_filters = {
        key: COLUMNS[key].in_(values) for key, values in selections.items() if values
    }
    if search.strip():
        base_filters.append(
            or_(
                *(
                    cast(column, String).icontains(search.strip(), autoescape=True)
                    for column in COLUMNS.values()
                )
            )
        )
    filters = [*base_filters, *column_filters.values()]
    total = connection.scalar(select(func.count()).select_from(joined).where(*filters))
    sort_column = COLUMNS[sort_by]
    ordering = sort_column.desc() if sort_direction == "descending" else sort_column.asc()
    items = (
        connection.execute(
            select(
                discharges.c.discharge_id,
                *(column.label(key) for key, column in COLUMNS.items()),
            )
            .select_from(joined)
            .where(*filters)
            .order_by(ordering, discharges.c.discharge_id)
            .limit(None if export_all else page_size)
            .offset(0 if export_all else offset)
        )
        .mappings()
        .all()
    )
    filter_options = table_filter_options(
        connection,
        joined=joined,
        columns=COLUMNS,
        selections=selections,
        base_filters=base_filters,
        keys=FILTER_KEYS,
    )
    return {
        "items": [dict(row) for row in items],
        "total": int(total),
        "filter_options": filter_options,
    }


def discharge_overview(
    connection: Connection,
    start_date: date,
    end_date: date,
    payer_type: list[str] | None = None,
    destination_type: list[str] | None = None,
) -> dict:
    """One row per facility, including zero activity, for all hierarchy levels."""
    if start_date > end_date:
        raise ReportQueryError(422, "start_date must not be after end_date.")
    days = (end_date - start_date).days + 1
    prior_start = start_date - timedelta(days=days)
    prior_end = start_date - timedelta(days=1)
    selection_filters = _discharge_selection_filters(payer_type, destination_type)
    counts = (
        select(
            discharges.c.facility_code,
            func.sum(COLUMNS["los_days"])
            .filter(discharges.c.discharge_date.between(start_date, end_date))
            .label("total_los_days"),
            func.count()
            .filter(discharges.c.discharge_date.between(start_date, end_date))
            .label("total_discharges"),
            func.count()
            .filter(
                discharges.c.discharge_date.between(start_date, end_date),
                discharges.c.discharge_type == "AMA",
            )
            .label("ama_discharges"),
            func.count()
            .filter(
                discharges.c.discharge_date.between(start_date, end_date),
                discharges.c.discharge_type == "Transfer",
                discharges.c.destination_type == "Hospital",
            )
            .label("hospital_transfers"),
            func.count()
            .filter(discharges.c.discharge_date.between(prior_start, prior_end))
            .label("prior_period_discharges"),
        )
        .where(discharges.c.discharge_date.between(prior_start, end_date), *selection_filters)
        .group_by(discharges.c.facility_code)
        .subquery()
    )
    if not inspect(connection).has_table("adt_discharges"):
        raise ReportQueryError(503, "Discharge data is not available yet.")
    rows = (
        connection.execute(
            select(
                facilities.c.facility_code,
                facilities.c.name.label("facility_name"),
                COLUMNS["state"].label("state"),
                facilities.c.portfolio,
                facilities.c.region,
                func.coalesce(counts.c.total_los_days, 0).label("total_los_days"),
                func.coalesce(counts.c.total_discharges, 0).label("total_discharges"),
                func.coalesce(counts.c.ama_discharges, 0).label("ama_discharges"),
                func.coalesce(counts.c.hospital_transfers, 0).label("hospital_transfers"),
                func.coalesce(counts.c.prior_period_discharges, 0).label(
                    "prior_period_discharges"
                ),
            )
            .select_from(
                facilities.outerjoin(
                    counts, facilities.c.facility_code == counts.c.facility_code
                )
            )
            .order_by(facilities.c.facility_code)
        )
        .mappings()
        .all()
    )
    return {
        "items": [dict(row) for row in rows],
        "days": days,
        "prior_start_date": prior_start,
        "prior_end_date": prior_end,
    }


def _discharge_selection_filters(payer_type, destination_type):
    return [
        COLUMNS[key].in_(values)
        for key, values in (("payer_type", payer_type), ("destination_type", destination_type))
        if values
    ]


def _discharge_distribution(
    connection: Connection,
    dimension: str,
    start_date: date,
    end_date: date,
    state: str | None = None,
    portfolio: str | None = None,
    region: str | None = None,
    facility_name: str | None = None,
    payer_type: list[str] | None = None,
    destination_type: list[str] | None = None,
    location: list[str] | None = None,
) -> dict[str, int]:
    if start_date > end_date:
        raise ReportQueryError(422, "start_date must not be after end_date.")
    filters = [
        discharges.c.discharge_date.between(start_date, end_date),
        *_discharge_selection_filters(payer_type, destination_type),
    ]
    if location:
        location_filters = []
        for encoded in location:
            try:
                path = json.loads(encoded)
                if (
                    not isinstance(path, list)
                    or not 1 <= len(path) <= 4
                    or not all(isinstance(part, str) for part in path)
                ):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ReportQueryError(422, "Invalid location selection.") from None
            location_filters.append(
                and_(
                    *[
                        COLUMNS[key] == value
                        for key, value in zip(
                            ["state", "portfolio", "region", "facility_name"], path
                        )
                    ]
                )
            )
        filters.append(or_(*location_filters))
    for key, value in (
        ("state", state),
        ("portfolio", portfolio),
        ("region", region),
        ("facility_name", facility_name),
    ):
        if value is not None:
            filters.append(COLUMNS[key] == value)
    if not inspect(connection).has_table("adt_discharges"):
        raise ReportQueryError(503, "Discharge data is not available yet.")
    counts = dict(
        connection.execute(
            select(COLUMNS[dimension], func.count())
            .select_from(SOURCES["discharges"].joined)
            .where(*filters)
            .group_by(COLUMNS[dimension])
        ).all()
    )
    return counts


def discharges_by_type(
    connection: Connection,
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
    counts = _discharge_distribution(
        connection,
        "discharge_type",
        start_date,
        end_date,
        state,
        portfolio,
        region,
        facility_name,
        payer_type,
        destination_type,
        location,
    )
    return sorted(
        [{"label": label, "value": counts.get(label, 0)} for label in DISCHARGE_TYPES],
        key=lambda item: (-item["value"], item["label"]),
    )


def discharges_by_payer(
    connection: Connection,
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
    counts = _discharge_distribution(
        connection,
        "payer_type",
        start_date,
        end_date,
        state,
        portfolio,
        region,
        facility_name,
        payer_type,
        destination_type,
        location,
    )
    labels = sorted(
        "Commercial Medicare" if payer == "Medicare Advantage" else payer for payer in PAYER_TYPES
    )
    return [{"label": label, "value": counts.get(label, 0)} for label in labels]


def discharges_by_destination(
    connection: Connection,
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
    counts = _discharge_distribution(
        connection,
        "destination_type",
        start_date,
        end_date,
        state,
        portfolio,
        region,
        facility_name,
        payer_type,
        destination_type,
        location,
    )
    return sorted(
        [{"label": label, "value": value} for label, value in counts.items()],
        key=lambda item: (-item["value"], item["label"]),
    )


def discharges_daily_trend(
    connection: Connection,
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
    counts = _discharge_distribution(
        connection,
        "discharge_date",
        start_date,
        end_date,
        state,
        portfolio,
        region,
        facility_name,
        payer_type,
        destination_type,
        location,
    )
    return [
        {
            "date": start_date + timedelta(days=index),
            "value": counts.get(start_date + timedelta(days=index), 0),
        }
        for index in range((end_date - start_date).days + 1)
    ]
