"""SQL readers. Connections are supplied by services; imports never access a database."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Date, String, case, cast, func, literal, or_, select, text
from sqlalchemy.engine import Connection

from api.queries.errors import ReportQueryError
from common.time import business_date
from data.models.admissions import admissions
from data.models.admissions_reporting import daily, sources, state
from data.models.facilities import facilities
from data.models.hospital_reporting import monthly as hospital_monthly, hospitals as hospital_directory, publication as hospital_publication
from domain.facilities import STATE_NAMES
from domain.metrics.hospital_performance import monthly_comparisons


def admissions_publication(connection: Connection):
    publication = connection.execute(select(
        state.c.ready, state.c.first_date, state.c.latest_date,
    ).where(state.c.id == 1)).mappings().one_or_none()
    if (not publication or not publication["ready"]
            or publication["first_date"] is None or publication["latest_date"] is None
            or publication["first_date"] > publication["latest_date"]):
        raise ReportQueryError(
            503, "Admissions reporting has no complete published date range yet. "
            "Finish the source catch-up and reporting refresh before requesting this report.",
        )
    return publication


def resolve_date_range(
    connection: Connection,
    start_date: date | None,
    end_date: date | None,
    days: int,
    *,
    publication=None,
) -> tuple[date, date]:
    if (start_date is None) != (end_date is None):
        raise ReportQueryError(422, "start_date and end_date must be provided together.")
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise ReportQueryError(422, "start_date must not be after end_date.")
    publication = publication if publication is not None else admissions_publication(connection)
    first, latest = publication["first_date"], publication["latest_date"]
    if start_date is None:
        end_date = latest
        start_date = latest - timedelta(days=days - 1)
    if start_date < first or end_date > latest:
        raise ReportQueryError(
            422, f"Complete admissions data is available from {first} through {latest}. "
            "Choose dates within that range, or finish the missing source/reporting refresh.",
        )
    return start_date, end_date


def list_recent_admissions(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: list[str] | None = None,
    offset: int = 0,
    export_all: bool = False,
    page_size: int = 50,
    payer_type: list[str] | None = None,
    admission_source: list[str] | None = None,
    sort_by: str = "admission-date",
    sort_direction: str = "descending",
    search: str = "",
    state: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
    source_type: list[str] | None = None,
    payer_name: list[str] | None = None,
    is_readmission: bool | None = None,
) -> dict[str, Any]:
    """Return one page of raw admissions for a requested range or latest reporting days."""

    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    filters = [admissions.c.admission_date.between(start_date, end_date)]
    if is_readmission is not None:
        filters.append(admissions.c.is_readmission.is_(is_readmission))
    if facility:
        filters.append(facilities.c.name.in_(facility))
    if payer_type:
        filters.append(admissions.c.payer_type.in_(payer_type))
    if payer_name:
        filters.append(admissions.c.payer_name.in_(payer_name))
    if admission_source:
        filters.append(admissions.c.admission_source_name.in_(admission_source))
    state_codes = {name: code for code, name in STATE_NAMES.items()}
    hierarchy_filters = []
    for values, column in (
        ([state_codes.get(value, value) for value in state] if state else None, facilities.c.state),
        (portfolio, facilities.c.portfolio),
        (region, facilities.c.region),
    ):
        if values:
            hierarchy_filters.append(column.in_(values))
    filters.extend(hierarchy_filters)
    if source_type:
        filters.append(admissions.c.admission_source_type.in_(source_type))
    search_term = search.strip()
    if search_term:
        # Match the displayed payer label as well as the other visible log columns.
        payer_label = case(
            (admissions.c.payer_type == "Medicare Advantage", "Commercial Medicare"),
            else_=admissions.c.payer_type,
        )
        filters.append(
            or_(
                *(
                    column.icontains(search_term, autoescape=True)
                    for column in (
                        facilities.c.name,
                        case(STATE_NAMES, value=facilities.c.state, else_=facilities.c.state),
                        facilities.c.region,
                        facilities.c.portfolio,
                        admissions.c.resident_name,
                        case((admissions.c.is_readmission, "Yes"), else_="No"),
                        cast(admissions.c.admission_date, String),
                        payer_label,
                        admissions.c.payer_name,
                        admissions.c.admission_source_type,
                        admissions.c.admission_source_name,
                    )
                )
            )
        )
    sort_columns = {
        "admission-date": admissions.c.admission_date,
        "admission-source": admissions.c.admission_source_name,
        "facility": facilities.c.name,
        "state": facilities.c.state,
        "region": facilities.c.region,
        "portfolio": facilities.c.portfolio,
        "payer": admissions.c.payer_type,
        "payer-name": admissions.c.payer_name,
        "source-type": admissions.c.admission_source_type,
        "resident": admissions.c.resident_name,
        "readmission": admissions.c.is_readmission,
    }
    sort_column = sort_columns.get(sort_by, admissions.c.admission_date)
    is_descending = sort_direction != "ascending"
    order_by = sort_column.desc() if is_descending else sort_column.asc()

    option_rows = connection.execute(
        select(sources.c.admission_source_name, sources.c.facility_code, sources.c.payer_type,
               sources.c.admission_source_type)
        .where(sources.c.admission_date.between(start_date, end_date))
        .distinct()
    ).all()
    facility_codes = {row.facility_code for row in option_rows}
    filter_options = {
        "admission_source": sorted({row.admission_source_name for row in option_rows}),
        "payer": sorted({row.payer_type for row in option_rows}),
        "source_type": sorted({row.admission_source_type for row in option_rows}),
        "payer_name": list(connection.scalars(
            select(admissions.c.payer_name)
            .where(admissions.c.admission_date.between(start_date, end_date))
            .distinct().order_by(admissions.c.payer_name)
        )),
        "facility": list(
            connection.scalars(
                select(facilities.c.name)
                .where(facilities.c.facility_code.in_(facility_codes))
                .order_by(facilities.c.name)
            )
        ),
    }
    for dimension in ("state", "region", "portfolio"):
        values = connection.scalars(select(facilities.c[dimension]).where(
            facilities.c.facility_code.in_(facility_codes)
        ).distinct()).all()
        filter_options[dimension] = sorted(
            STATE_NAMES.get(value, value) if dimension == "state" else value for value in values
        )
    count_filters = report_filters(sources, start_date, end_date, facility, payer_type)
    count_filters.extend(hierarchy_filters)
    if source_type:
        count_filters.append(sources.c.admission_source_type.in_(source_type))
    if admission_source:
        count_filters.append(sources.c.admission_source_name.in_(admission_source))
    if search_term or payer_name or is_readmission is not None:
        total = connection.scalar(
            select(func.count())
            .select_from(
                admissions.join(
                    facilities, facilities.c.facility_code == admissions.c.facility_code
                )
            )
            .where(*filters)
        )
    else:
        total = connection.scalar(
            select(func.coalesce(func.sum(sources.c.admission_count), 0))
            .select_from(
                sources.join(facilities, facilities.c.facility_code == sources.c.facility_code)
            )
            .where(*count_filters)
        )
    results = connection.execute(
        select(
            admissions.c.admission_id,
            admissions.c.is_readmission,
            facilities.c.name.label("facility_name"),
            case(STATE_NAMES, value=facilities.c.state, else_=facilities.c.state).label("state"),
            facilities.c.region,
            facilities.c.portfolio,
            admissions.c.resident_name,
            admissions.c.admission_date,
            admissions.c.payer_type,
            admissions.c.payer_name,
            admissions.c.admission_source_type,
            admissions.c.admission_source_name,
        )
        .join(facilities, facilities.c.facility_code == admissions.c.facility_code)
        .where(*filters)
        .order_by(order_by, admissions.c.admission_id)
        .limit(None if export_all else page_size)
        .offset(0 if export_all else offset)
    )
    return {
        "filter_options": filter_options,
        "items": [dict(row) for row in results.mappings()],
        "total": int(total),
    }


def get_admissions_filter_options(connection: Connection) -> dict:
    """Return portfolio hierarchy values for aggregate admissions filters."""

    return {
        "locations": [
            {**row, "state": STATE_NAMES.get(row["state"], row["state"])}
            for row in connection.execute(select(
                facilities.c.state, facilities.c.portfolio, facilities.c.region,
                facilities.c.name.label("facility"),
            ).order_by(facilities.c.name)).mappings()
        ],
        "facilities": [
            row[0]
            for row in connection.execute(
                select(facilities.c.name).distinct().order_by(facilities.c.name)
            )
        ],
        "portfolios": [
            row[0]
            for row in connection.execute(
                select(facilities.c.portfolio).distinct().order_by(facilities.c.portfolio)
            )
        ],
        "regions": [
            row[0]
            for row in connection.execute(
                select(facilities.c.region).distinct().order_by(facilities.c.region)
            )
        ],
    }


def report_filters(
    table, start_date, end_date, facility=None, payer_type=None, portfolio=None, region=None
):
    filters = [table.c.admission_date.between(start_date, end_date)]
    for values, column in (
        (facility, facilities.c.name),
        (payer_type, table.c.payer_type),
        (portfolio, facilities.c.portfolio),
        (region, facilities.c.region),
    ):
        if values:
            filters.append(column.in_(values))
    return filters


def reporting_join(table):
    return table.join(facilities, facilities.c.facility_code == table.c.facility_code)


def get_admissions_daily_trend(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: list[str] | None = None,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Sum seeded daily counts, retaining zero days and all hierarchy filters."""
    daily = admissions_daily_for_sources(source_type)
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    counts = dict(
        connection.execute(
            select(daily.c.admission_date, func.sum(daily.c.total_admissions))
            .select_from(reporting_join(daily))
            .where(
                *report_filters(
                    daily, start_date, end_date, facility, payer_type, portfolio, region
                )
            )
            .group_by(daily.c.admission_date)
        ).all()
    )
    return [
        {
            "admission_date": start_date + timedelta(days=offset),
            "admission_count": int(counts.get(start_date + timedelta(days=offset), 0)),
        }
        for offset in range((end_date - start_date).days + 1)
    ]


def get_admissions_kpis(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
) -> dict[str, Any]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    period_days = (end_date - start_date).days + 1
    return {
        **get_admissions_kpi_metrics(connection, start_date, end_date, facility, payer_type, portfolio, region),
        "prior_period": get_admissions_kpi_metrics(
            connection,
            start_date - timedelta(days=period_days),
            start_date - timedelta(days=1),
            facility,
            payer_type,
            portfolio,
            region,
        ),
    }


def get_admissions_kpi_metrics(
    connection: Connection,
    start_date, end_date, facility=None, payer_type=None, portfolio=None, region=None
):
    period_days = (end_date - start_date).days + 1
    metrics = (
        connection.execute(
            select(
                func.coalesce(func.sum(daily.c.total_admissions), 0).label("total_admissions"),
                func.coalesce(func.sum(daily.c.readmission_count), 0).label(
                    "readmission_count"
                ),
                func.coalesce(func.sum(daily.c.readmission_within_30_days_count), 0).label(
                    "readmission_within_30_days_count"
                ),
            )
            .select_from(reporting_join(daily))
            .where(
                *report_filters(
                    daily, start_date, end_date, facility, payer_type, portfolio, region
                )
            )
        )
        .mappings()
        .one()
    )
    # Distinct counts are not additive: count names across the whole selected range.
    source_count = connection.scalar(
        select(func.count(func.distinct(sources.c.admission_source_name)))
        .select_from(reporting_join(sources))
        .where(
            *report_filters(
                sources, start_date, end_date, facility, payer_type, portfolio, region
            )
        )
    )
    return {
        **{key: int(value) for key, value in metrics.items()},
        "unique_admission_source_count": source_count,
        "days_in_range": period_days,
        "average_admissions_per_day": int(metrics["total_admissions"]) / period_days,
    }


def ranked_counts(connection: Connection, column, start_date, end_date):
    count = func.sum(daily.c.total_admissions).label("admission_count")
    return [
        dict(row)
        for row in connection.execute(
            select(column, count)
            .select_from(reporting_join(daily))
            .where(daily.c.admission_date.between(start_date, end_date))
            .group_by(column)
            .order_by(count.desc(), column)
        ).mappings()
    ]


def get_admissions_by_state(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    return [
        {**row, "state": STATE_NAMES.get(row["state"], row["state"])}
        for row in ranked_counts(connection, facilities.c.state, start_date, end_date)
    ]


def get_admissions_by_region(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    return ranked_counts(connection, facilities.c.region, start_date, end_date)


def admissions_daily_for_sources(source_type):
    if not source_type:
        return daily
    return (
        select(
            admissions.c.admission_date,
            admissions.c.facility_code,
            admissions.c.payer_type,
            func.count().label("total_admissions"),
            func.sum(case((admissions.c.is_readmission, 1), else_=0)).label("readmission_count"),
            func.sum(case((admissions.c.is_readmission & (admissions.c.readmission_days_since_prior <= 30), 1), else_=0)).label("readmission_within_30_days_count"),
        )
        .where(admissions.c.admission_source_type.in_(source_type))
        .group_by(admissions.c.admission_date, admissions.c.facility_code, admissions.c.payer_type)
        .subquery()
    )


def comparison_metrics(connection: Connection, start_date, end_date, level, payer_type=None, source_type=None):
    daily = admissions_daily_for_sources(source_type)
    period_days = (end_date - start_date).days + 1
    prior_start = start_date - timedelta(days=period_days)
    current = daily.c.admission_date.between(start_date, end_date)
    prior = daily.c.admission_date.between(prior_start, start_date - timedelta(days=1))
    medicare = daily.c.payer_type == "Medicare"

    def total(condition, column, name):
        return func.coalesce(func.sum(case((condition, column), else_=0)), 0).label(name)

    # Reduce to one row per facility before joining its hierarchy. Facility and region
    # denominators stay correct even when the selected payer/range has no admissions.
    conditions = [daily.c.admission_date.between(prior_start, end_date)]
    if payer_type:
        conditions.append(daily.c.payer_type.in_(payer_type))
    metrics = (
        select(
            daily.c.facility_code,
            total(current, daily.c.total_admissions, "total_admissions"),
            total(prior, daily.c.total_admissions, "prior_period_admissions"),
            total(current, daily.c.readmission_count, "readmission_count"),
            total(current, daily.c.readmission_within_30_days_count, "readmission_within_30_days_count"),
            total(current & medicare, daily.c.total_admissions, "medicare_admission_count"),
            total(
                prior & medicare, daily.c.total_admissions, "prior_period_medicare_admission_count"
            ),
        )
        .where(*conditions)
        .group_by(daily.c.facility_code)
        .subquery()
    )
    if level == "facility":
        columns = [
            facilities.c.name.label("facility_name"),
            facilities.c.portfolio,
            facilities.c.region,
            facilities.c.state,
        ]
        groups = [
            facilities.c.facility_code,
            facilities.c.name,
            facilities.c.portfolio,
            facilities.c.region,
            facilities.c.state,
        ]
    else:
        dimension = facilities.c.portfolio if level == "portfolio" else facilities.c.region
        columns = [
            dimension.label("region"),
            facilities.c.state,
            facilities.c.portfolio if level == "region" else None,
            func.count(facilities.c.facility_code).label("facility_count"),
            func.count(func.distinct(facilities.c.region)).label("region_count"),
        ]
        groups = [facilities.c.state, dimension]
        if level == "region":
            groups.append(facilities.c.portfolio)
    metric_columns = [
        func.coalesce(func.sum(column), 0).label(column.name)
        for column in metrics.c
        if column.name != "facility_code"
    ]
    query = (
        select(*columns, *metric_columns)
        .select_from(
            facilities.outerjoin(metrics, metrics.c.facility_code == facilities.c.facility_code)
        )
        .group_by(*groups)
    )
    query = (
        query.order_by(facilities.c.name)
        if level == "facility"
        else query.order_by(metric_columns[0].desc(), dimension)
    )
    rows = [dict(row) for row in connection.execute(query).mappings()]
    # Keep identities so state rows and table totals can union hospitals instead
    # of adding distinct counts from overlapping facilities or portfolios.
    hospital_dimensions = [facilities.c.state]
    hospital_keys = ["state"]
    if level == "portfolio":
        hospital_dimensions.append(facilities.c.portfolio)
        hospital_keys.append("region")
    else:
        hospital_dimensions.extend([facilities.c.portfolio, facilities.c.region])
        hospital_keys.extend(["portfolio", "region"])
        if level == "facility":
            hospital_dimensions.append(facilities.c.name)
            hospital_keys.append("facility_name")
    hospital_filters = report_filters(sources, start_date, end_date, payer_type=payer_type)
    hospital_filters.append(sources.c.admission_source_type == "Hospital")
    if source_type:
        hospital_filters.append(sources.c.admission_source_type.in_(source_type))
    hospitals = {}
    for hospital in connection.execute(
        select(*hospital_dimensions, sources.c.admission_source_name)
        .select_from(reporting_join(sources))
        .where(*hospital_filters)
        .distinct()
    ):
        hospitals.setdefault(tuple(hospital[:-1]), []).append(hospital[-1])
    for row in rows:
        row["referring_hospitals"] = sorted(
            hospitals.get(tuple(row[key] for key in hospital_keys), [])
        )
        for column in metric_columns:
            row[column.name] = int(row[column.name])
    return [
        {
            **row,
            "state": STATE_NAMES.get(row["state"], row["state"]),
            "admissions_change": row["total_admissions"] - row["prior_period_admissions"],
            "average_admissions_per_day": row["total_admissions"] / period_days,
            "medicare_admissions_change": row["medicare_admission_count"]
            - row["prior_period_medicare_admission_count"],
        }
        for row in rows
    ]


def get_admissions_by_region_metrics(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: list[str] | None = None,
    level: str = "portfolio",
    payer_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    if level not in {"portfolio", "region"}:
        raise ReportQueryError(422, "level must be portfolio or region.")
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    return comparison_metrics(connection, start_date, end_date, level, payer_type, source_type)


def get_admissions_by_facility_metrics(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    source_type: list[str] | None = None,
    payer_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    return comparison_metrics(connection, start_date, end_date, "facility", payer_type, source_type)


def get_admissions_by_region_and_payer(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, list[Any]]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    region_counts = {}
    payer_totals = {}
    for row in connection.execute(
        select(
            facilities.c.region,
            daily.c.payer_type,
            func.sum(daily.c.total_admissions).label("admission_count"),
        )
        .select_from(reporting_join(daily))
        .where(daily.c.admission_date.between(start_date, end_date))
        .group_by(facilities.c.region, daily.c.payer_type)
    ).mappings():
        count = int(row["admission_count"])
        region_counts.setdefault(row["region"], {})[row["payer_type"]] = count
        payer_totals[row["payer_type"]] = payer_totals.get(row["payer_type"], 0) + count
    payers = sorted(payer_totals, key=lambda payer: (-payer_totals[payer], payer))
    regions = sorted(
        region_counts, key=lambda region: (-sum(region_counts[region].values()), region)
    )
    return {
        "payer_types": payers,
        "regions": [
            {
                "region": region,
                "admission_counts": {
                    payer: region_counts[region].get(payer, 0) for payer in payers
                },
            }
            for region in regions
        ],
    }


def get_admissions_by_payer(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    return ranked_counts(connection, daily.c.payer_type, start_date, end_date)


def get_admissions_by_source_type(
    connection: Connection,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, days)
    count = func.sum(sources.c.admission_count).label("admission_count")
    return [
        dict(row)
        for row in connection.execute(
            select(
                sources.c.admission_source_type,
                count,
            )
            .select_from(reporting_join(sources))
            .where(
                *report_filters(
                    sources, start_date, end_date, facility, payer_type, portfolio, region
                )
            )
            .group_by(sources.c.admission_source_type)
            .order_by(count.desc(), sources.c.admission_source_type)
        ).mappings()
    ]


def get_historical_comparisons(connection: Connection, start_date: date, end_date: date):
    """One cached aggregate for all drill-down levels and historical baselines."""
    from calendar import monthrange

    coverage = admissions_publication(connection)
    start_date, end_date = resolve_date_range(
        connection, start_date, end_date, 30, publication=coverage,
    )
    days = (end_date - start_date).days + 1

    def years_ago(value, years):
        year = value.year - years
        return value.replace(year=year, day=min(value.day, monthrange(year, value.month)[1]))

    first, latest = coverage["first_date"], coverage["latest_date"]
    periods = [
        ("prior", start_date - timedelta(days=days), start_date - timedelta(days=1)),
        ("average", first, latest),
        ("year", years_ago(start_date, 1), years_ago(end_date, 1)),
        ("two-years", years_ago(start_date, 2), years_ago(end_date, 2)),
    ]
    totals = (
        select(
            daily.c.facility_code,
            *[
                func.sum(
                    case(
                        (daily.c.admission_date.between(begin, end), daily.c.total_admissions),
                        else_=0,
                    )
                ).label(key)
                for key, begin, end in periods
            ],
        )
        .group_by(daily.c.facility_code)
        .subquery()
    )
    query = select(
        facilities.c.name.label("name"),
        facilities.c.state,
        facilities.c.portfolio,
        facilities.c.region,
        *[func.coalesce(totals.c[key], 0).label(key) for key, _, _ in periods],
    ).select_from(
        facilities.outerjoin(totals, totals.c.facility_code == facilities.c.facility_code)
    )
    items = [dict(row) for row in connection.execute(query).mappings()]
    for item in items:
        item["state"] = STATE_NAMES.get(item["state"], item["state"])
        for key, begin, end in periods:
            item[key] = (
                float(item[key]) / ((end - begin).days + 1)
                if begin >= first and end <= latest
                else None
            )
    return {
        "periods": [{"key": key, "start": begin, "end": end} for key, begin, end in periods],
        "items": items,
    }


def referring_hospital_location_performance(
    connection: Connection,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
) -> dict:
    current = business_date().replace(day=1)
    def months_before(count):
        number = current.year * 12 + current.month - 1 - count
        return date(number // 12, number % 12 + 1, 1)
    recent_start, baseline_start = months_before(3), months_before(27)
    resolve_date_range(connection, baseline_start, current - timedelta(days=1), 30)
    location_query = select(facilities.c.facility_code, facilities.c.name.label('facility'),
        facilities.c.state, facilities.c.portfolio, facilities.c.region)
    if facility:
        location_query = location_query.where(facilities.c.name.in_(facility))
    locations = [dict(row) for row in connection.execute(location_query).mappings()]
    rows = connection.execute(select(
        admissions.c.facility_code, admissions.c.admission_source_name.label('hospital'),
        func.count().filter(admissions.c.admission_date >= recent_start).label('recent'),
        func.count().filter(admissions.c.admission_date < recent_start).label('baseline'),
    ).select_from(reporting_join(admissions)).where(
        admissions.c.admission_source_type == 'Hospital',
        *report_filters(admissions, baseline_start, current - timedelta(days=1),
                        facility=facility, payer_type=payer_type),
    ).group_by(admissions.c.facility_code, admissions.c.admission_source_name)).mappings().all()
    return {'locations': [{**row, 'state': STATE_NAMES.get(row['state'], row['state'])} for row in locations],
            'items': [dict(row) for row in rows], 'recent_start': recent_start,
            'baseline_start': baseline_start, 'end_date': current - timedelta(days=1)}


def referring_hospital_performance(
    connection: Connection,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    hospital: str | None = None,
) -> dict:
    def shift_month(month, offset):
        number = month.year * 12 + month.month - 1 + offset
        return date(number // 12, number % 12 + 1, 1)

    if not connection.scalar(text("SELECT to_regclass('adt_referring_hospital_publication')")):
        raise ReportQueryError(503, 'Hospital reporting has not been published yet.')
    published = connection.execute(select(
        hospital_publication, state.c.ready.label('daily_ready'),
        state.c.first_date.label('daily_first'), state.c.latest_date.label('daily_latest'),
    ).select_from(hospital_publication.outerjoin(state, state.c.id == 1))).mappings().one_or_none()
    if not published or published['start_date'] is None or published['end_date'] is None:
        raise ReportQueryError(503, 'Hospital reporting has no complete published date range yet.')
    today = published['end_date']
    current_month = today.replace(day=1)
    start = shift_month(current_month, -36)
    end = current_month - timedelta(days=1)
    if published['start_date'] > start:
        raise ReportQueryError(
            503, 'Hospital performance requires 36 complete published months plus the current month. '
            'Complete the missing history and refresh hospital reporting before loading this report.',
        )
    if (not published['daily_ready'] or published['daily_first'] is None
            or published['daily_latest'] is None or published['daily_first'] > current_month
            or published['daily_latest'] < today):
        raise ReportQueryError(
            503, 'Current-month hospital counts are not complete through the hospital publication date. '
            'Refresh admissions daily reporting for the missing dates before loading this report.',
        )
    months = [shift_month(start, index).strftime('%Y-%m') for index in range(36)]
    filters = [hospital_monthly.c.month.between(start, end), hospital_monthly.c.admissions > 0]
    current_filters = [sources.c.admission_date.between(current_month, today),
                       sources.c.admission_source_type == 'Hospital']
    if facility:
        selected_facilities = select(facilities.c.facility_code).where(facilities.c.name.in_(facility))
        filters.append(hospital_monthly.c.facility_code.in_(selected_facilities))
        current_filters.append(sources.c.facility_code.in_(selected_facilities))
    if payer_type:
        filters.append(hospital_monthly.c.payer_type.in_(payer_type))
        current_filters.append(sources.c.payer_type.in_(payer_type))
    if hospital:
        filters.append(hospital_monthly.c.hospital == hospital)
        current_filters.append(sources.c.admission_source_name == hospital)
    historical_totals = select(
        hospital_monthly.c.hospital, hospital_monthly.c.month,
        hospital_monthly.c.facility_code,
        func.sum(hospital_monthly.c.admissions).label('count'),
    ).where(*filters).group_by(hospital_monthly.c.hospital, hospital_monthly.c.month,
                              hospital_monthly.c.facility_code)
    # A facility catch-up may have newer MTD counts than the shared publication.
    # Bound this numerator to the same published day used for the average divisor.
    current_totals = select(
        sources.c.admission_source_name.label('hospital'),
        literal(current_month, type_=Date).label('month'), sources.c.facility_code,
        func.sum(sources.c.admission_count).label('count'),
    ).where(*current_filters).group_by(sources.c.admission_source_name, sources.c.facility_code)
    totals = historical_totals.union_all(current_totals).subquery()
    rows = connection.execute(select(
        totals, facilities.c.name.label('facility'),
        hospital_directory.c.state, hospital_directory.c.portfolio, hospital_directory.c.region,
    ).select_from(totals.join(facilities, totals.c.facility_code == facilities.c.facility_code)
                  .join(hospital_directory, totals.c.hospital == hospital_directory.c.hospital))).mappings().all()
    hospitals = {}
    month_indexes = {month: index for index, month in enumerate(months)}
    for row in rows:
        entry = hospitals.setdefault(row['hospital'], {
            'hospital': row['hospital'], 'months': [0] * 36, 'receiving': {}, 'current': 0,
            'state': STATE_NAMES.get(row['state'], row['state']),
            'portfolio': row['portfolio'], 'region': row['region'],
        })
        count = int(row['count'])
        if row['month'] == current_month:
            entry['current'] += count
            continue
        index = month_indexes[row['month'].strftime('%Y-%m')]
        entry['months'][index] += count
        receiver = entry['receiving'].setdefault(row['facility_code'], {
            'facility_code': row['facility_code'], 'facility': row['facility'],
            'admissions': 0, 'months': [0] * 36 if hospital else [],
        })
        if hospital:
            receiver['months'][index] += count
        if index >= 9:
            receiver['admissions'] += count
    items = []
    for entry in hospitals.values():
        values = entry['months']
        if not sum(values) and not entry['current']:
            continue
        receivers = [row for row in entry.pop('receiving').values() if row['admissions'] > 0]
        current = entry.pop('current')
        items.append({**entry,
            'receiving_facilities': sorted(receivers, key=lambda row: (-row['admissions'], row['facility'])),
            **monthly_comparisons(values, current, today.day)})
    return {'items': items, 'months': months, 'start_date': start, 'end_date': end}


def get_admissions_by_referring_hospital(
    connection: Connection,
    start_date: date,
    end_date: date,
    facility: list[str] | None = None,
    payer_type: list[str] | None = None,
    portfolio: list[str] | None = None,
    region: list[str] | None = None,
    state: list[str] | None = None,
    source_type: list[str] | None = None,
) -> list[dict[str, Any]]:
    start_date, end_date = resolve_date_range(connection, start_date, end_date, 30)
    period_days = (end_date - start_date).days + 1
    prior_start = start_date - timedelta(days=period_days)
    current = admissions.c.admission_date.between(start_date, end_date)
    prior = admissions.c.admission_date.between(prior_start, start_date - timedelta(days=1))
    count = func.count().filter(current).label("admission_count")
    prior_count = func.count().filter(prior).label("prior_period_admissions")
    history_start, history_end = connection.execute(select(
        func.min(admissions.c.admission_date), func.max(admissions.c.admission_date)
    )).one()
    if history_start is None or history_end is None:
        return []
    history_days = (history_end - history_start).days + 1
    filters = report_filters(
        admissions, min(prior_start, history_start), max(end_date, history_end), facility, payer_type, portfolio, region
    )
    if state:
        state_codes = {name: code for code, name in STATE_NAMES.items()}
        filters.append(facilities.c.state.in_([state_codes.get(value, value) for value in state]))
    if source_type:
        filters.append(admissions.c.admission_source_type.in_(source_type))
    rows = [
        dict(row)
        for row in connection.execute(
            select(
                admissions.c.admission_source_name.label("hospital"), count, prior_count,
                func.count().label("historical_admissions"),
                func.array_agg(func.distinct(admissions.c.facility_code)).filter(current).label(
                    "receiving_facility_codes"
                ),
                func.count().filter(current & admissions.c.is_readmission).label(
                    "readmission_count"
                ),
                func.count().filter(
                    current & admissions.c.is_readmission
                    & (admissions.c.readmission_days_since_prior <= 30)
                ).label("readmission_within_30_days_count"),
            )
            .select_from(reporting_join(admissions))
            .where(
                admissions.c.admission_source_type == "Hospital",
                *filters,
            )
            .group_by(admissions.c.admission_source_name)
            .order_by(count.desc(), admissions.c.admission_source_name)
        ).mappings()
    ]
    return [
        {**row, "receiving_facility_codes": sorted(row["receiving_facility_codes"] or []),
         "admissions_change": row["admission_count"] - row["prior_period_admissions"],
         "average_admissions_per_day": row["admission_count"] / period_days,
         "historical_average_per_day": row["historical_admissions"] / history_days,
         "expected_admissions": row["historical_admissions"] / history_days * period_days,
         "variance_from_expected": row["admission_count"] - row["historical_admissions"] / history_days * period_days,
         "history_start_date": history_start, "history_end_date": history_end}
        for row in rows
    ]


def get_payer_by_facility(
    connection: Connection,
    start_date: date, end_date: date, source_type: list[str] | None = None
) -> list[dict[str, Any]]:
    daily = admissions_daily_for_sources(source_type)
    start_date, end_date = resolve_date_range(connection, start_date, end_date, 30)
    rows = [
        dict(row)
        for row in connection.execute(
            select(
                facilities.c.facility_code,
                facilities.c.name.label("facility"),
                facilities.c.state,
                facilities.c.portfolio,
                facilities.c.region,
                daily.c.payer_type,
                func.sum(daily.c.total_admissions).label("admissions"),
            )
            .select_from(reporting_join(daily))
            .where(daily.c.admission_date.between(start_date, end_date))
            .group_by(
                facilities.c.facility_code,
                facilities.c.name,
                facilities.c.state,
                facilities.c.portfolio,
                facilities.c.region,
                daily.c.payer_type,
            )
        ).mappings()
    ]
    return [
        {
            **row,
            "admissions": int(row["admissions"]),
            "state": STATE_NAMES.get(row["state"], row["state"]),
        }
        for row in rows
    ]
