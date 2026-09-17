"""SQL readers. Connections are supplied by services; imports never access a database."""

from dataclasses import dataclass
from datetime import date
import json
import math

from sqlalchemy import Date, String, bindparam, case, cast, func, inspect, or_, select
from sqlalchemy.engine import Connection

from api.queries.errors import ReportQueryError
from common.time import business_date
from data.models.admissions import admissions
from data.models.discharges import discharges
from data.models.facilities import facilities
from data.models.payer_changes import payer_changes
from domain.facilities import STATE_NAMES
from reporting.projections.movement_logs import movement_logs
"""Shared cascading filters for paginated tables; reports supply only column mappings."""


state_label = case(
    STATE_NAMES,
    value=facilities.c.state,
    else_=facilities.c.state,
)


def payer_label(table):
    return case(
        (table.c.payer_type == "Medicare Advantage", "Commercial Medicare"), else_=table.c.payer_type
    )


@dataclass(frozen=True)
class TableFilterSource:
    table: object
    date_column: object
    columns: dict
    filter_keys: tuple[str, ...]
    numeric_keys: tuple[str, ...] = ()
    required_tables: tuple[str, ...] = ()

    @property
    def joined(self):
        return self.table.join(facilities, self.table.c.facility_code == facilities.c.facility_code)


DISCHARGE_COLUMNS = {
    "resident_name": discharges.c.resident_name,
    "facility_name": facilities.c.name,
    "state": state_label,
    "region": facilities.c.region,
    "portfolio": facilities.c.portfolio,
    "start_date": discharges.c.start_date,
    "discharge_date": discharges.c.discharge_date,
    "payer_type": payer_label(discharges),
    "payer_name": discharges.c.payer_name,
    "discharge_type": discharges.c.discharge_type,
    "destination_type": discharges.c.destination_type,
    "destination_name": discharges.c.destination_name,
    "los_days": discharges.c.los_days,
}
PAYER_CHANGE_COLUMNS = {
    "resident_name": payer_changes.c.resident_name,
    "facility_name": facilities.c.name,
    "state": state_label,
    "region": facilities.c.region,
    "portfolio": facilities.c.portfolio,
    "effective_date": payer_changes.c.effective_date,
    **{
        f"{side}_payer_type": case(
            (payer_changes.c[f"{side}_payer_type"] == "Medicare Advantage", "Commercial Medicare"),
            else_=payer_changes.c[f"{side}_payer_type"],
        )
        for side in ("previous", "new")
    },
    "previous_payer_name": payer_changes.c.previous_payer_name,
    "new_payer_name": payer_changes.c.new_payer_name,
    "change_category": payer_changes.c.change_category,
    "status": case(
        (payer_changes.c.new_payer_end_date.is_(None)
         | (payer_changes.c.new_payer_end_date > bindparam("payer_los_as_of", callable_=business_date, type_=Date)), "Ongoing"),
        else_="Discharged",
    ),
    "previous_los_days": payer_changes.c.effective_date - payer_changes.c.previous_payer_start_date,
    "new_los_days": func.greatest(
        0,
        func.least(
            func.coalesce(
                payer_changes.c.new_payer_end_date,
                bindparam("payer_los_as_of", callable_=business_date, type_=Date),
            ),
            bindparam("payer_los_as_of", callable_=business_date, type_=Date),
        )
        - payer_changes.c.effective_date,
    ),
}
MOVEMENT_COLUMNS = {
    'resident_name': movement_logs.c.resident_name,
    'state': state_label, 'portfolio': facilities.c.portfolio,
    'region': facilities.c.region, 'facility_name': facilities.c.name,
    'move_type': movement_logs.c.move_type, 'move_date': movement_logs.c.move_date,
    'description': movement_logs.c.description, 'los_days': movement_logs.c.los_days,
}
SOURCES = {
    'net-change-logs': TableFilterSource(
        movement_logs, movement_logs.c.move_date, MOVEMENT_COLUMNS,
        ('resident_name', 'state', 'portfolio', 'region', 'facility_name', 'move_type'),
        required_tables=('adt_admissions', 'adt_discharges', 'adt_payer_changes'),
    ),
    "payer-changes": TableFilterSource(
        payer_changes,
        payer_changes.c.effective_date,
        PAYER_CHANGE_COLUMNS,
        tuple(key for key in PAYER_CHANGE_COLUMNS if key != "effective_date"),
        numeric_keys=("previous_los_days", "new_los_days"),
    ),
    "discharges": TableFilterSource(
        discharges,
        discharges.c.discharge_date,
        DISCHARGE_COLUMNS,
        (
            "resident_name",
            "facility_name",
            "state",
            "region",
            "portfolio",
            "payer_type",
            "payer_name",
            "discharge_type",
            "destination_type",
            "destination_name",
        ),
    ),
    "admissions": TableFilterSource(
        admissions,
        admissions.c.admission_date,
        {
            "resident": admissions.c.resident_name,
            "facility": facilities.c.name,
            "state": state_label,
            "region": facilities.c.region,
            "portfolio": facilities.c.portfolio,
            "admission-date": admissions.c.admission_date,
            "payer": payer_label(admissions),
            "payer-name": admissions.c.payer_name,
            "source-type": admissions.c.admission_source_type,
            "admission-source": admissions.c.admission_source_name,
            "readmission": case((admissions.c.is_readmission, "Yes"), else_="No"),
        },
        (
            "facility",
            "state",
            "region",
            "portfolio",
            "payer",
            "payer-name",
            "source-type",
            "admission-source",
            "readmission",
        ),
    ),
}


def filter_conditions(columns, selections, numeric_keys=()):
    conditions = {}
    for key, values in selections.items():
        if not values:
            continue
        if key not in numeric_keys:
            conditions[key] = columns[key].in_(values)
            continue
        try:
            if len(values) == 1:
                values = json.loads(values[0])
            if not isinstance(values, list):
                raise ValueError()
            operator = values[0]
            if operator not in ("equal", "greater-than", "less-than", "between"):
                raise ValueError()
            if len(values) != (3 if operator == "between" else 2):
                raise ValueError()
            numbers = [float(value) for value in values[1:]]
            if not all(math.isfinite(value) for value in numbers):
                raise ValueError()
        except (ValueError, TypeError, IndexError) as error:
            raise ReportQueryError(422, "Invalid numeric table filter.") from error
        column, value = columns[key], numbers[0]
        conditions[key] = (
            column.between(min(numbers), max(numbers))
            if operator == "between"
            else column > value
            if operator == "greater-than"
            else column < value
            if operator == "less-than"
            else column == value
        )
    return conditions


def table_filter_options(
    connection: Connection, *, joined, columns, selections, base_filters, keys, numeric_keys=()
):
    """AND between columns, OR within a column, exclude only the list's own selection."""
    conditions = filter_conditions(columns, selections, numeric_keys)
    return {
        key: list(
            connection.scalars(
                select(columns[key])
                .select_from(joined)
                .where(
                    *base_filters,
                    *(condition for other, condition in conditions.items() if other != key),
                )
                .distinct()
                .order_by(columns[key])
            )
        )
        for key in keys
    }


def get_table_filter_options(
    connection: Connection,
    source_id: str,
    column: str,
    start_date: date,
    end_date: date,
    filters: str = "{}",
    search: str = "",
) -> dict:
    source = SOURCES.get(source_id)
    if source is None:
        raise ReportQueryError(404, "Unknown table data source.")
    if column not in source.filter_keys or start_date > end_date:
        raise ReportQueryError(422, "Invalid filter column or date range.")
    try:
        selections = json.loads(filters)
    except (ValueError, TypeError) as error:
        raise ReportQueryError(422, "Invalid table filters.") from error
    if not isinstance(selections, dict) or any(
        key not in source.filter_keys
        or not isinstance(values, list)
        or any(not isinstance(value, str) for value in values)
        for key, values in selections.items()
    ):
        raise ReportQueryError(422, "Invalid table filters.")
    base_filters = [source.date_column.between(start_date, end_date)]
    if search.strip():
        base_filters.append(
            or_(
                *(
                    cast(value, String).icontains(search.strip(), autoescape=True)
                    for value in source.columns.values()
                )
            )
        )
    if not all(inspect(connection).has_table(name)
               for name in (source.required_tables or (source.table.name,))):
        raise ReportQueryError(503, "Table data is not available yet.")
    options = table_filter_options(
        connection,
        joined=source.joined,
        columns=source.columns,
        selections=selections,
        base_filters=base_filters,
        keys=(column,),
        numeric_keys=source.numeric_keys,
    )
    return {"options": options[column]}
