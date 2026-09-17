import json
from datetime import date, timedelta
from uuid import uuid4

import pytest
from app import adt_discharges, adt_net_change, table_filters
from app.database import get_engine
from app.seeding.admissions import build_daily_admissions
from app.seeding.base import SeedWindow
from app.seeding.discharges import DISCHARGE_TYPES, discharges
from app.seeding.facilities import build_facility_rows
from app.seeding.runner import run_seeders
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.schema import CreateSchema, DropSchema

DAY = date(2026, 9, 15)
PARAMS = {"start_date": str(DAY - timedelta(days=6)), "end_date": str(DAY)}


def test_discharge_generation_is_stable_and_dates_destinations_and_payers_are_consistent():
    facilities = build_facility_rows()
    from app.seeding.resident_movement import discharge_from_admission

    admitted = build_daily_admissions(DAY - timedelta(days=20), facilities)
    cities = {row["facility_code"]: row["city"] for row in facilities}
    rows = [discharge_from_admission(row, DAY, cities[row["facility_code"]]) for row in admitted]
    assert rows == [
        discharge_from_admission(row, DAY, cities[row["facility_code"]]) for row in admitted
    ]
    assert len({row["discharge_id"] for row in rows}) == len(rows)
    assert {row["discharge_type"] for row in rows} == set(DISCHARGE_TYPES)
    for row in rows:
        assert row["discharge_date"] == DAY
        assert row["los_days"] == (DAY - row["start_date"]).days >= 0
        if row["discharge_type"] == "Deceased":
            assert row["destination_type"] == "Funeral Home"
            assert row["destination_name"] == "Not applicable"
        if row["discharge_type"] == "Transfer":
            assert row["destination_type"] in ("Hospital", "Skilled Nursing", "Rehab Facility")


@pytest.fixture(scope="module")
def discharge_engine():
    owner = get_engine()
    schema = f"discharge_test_{uuid4().hex}"
    with owner.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(owner.url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        # Exercise all facilities over a shorter window in a private test schema.
        with pytest.MonkeyPatch.context() as patch:
            from app.seeding import resident_movement

            patch.setattr(resident_movement, "ANCHOR", DAY - timedelta(days=270))
            patch.setattr(
                SeedWindow,
                "ending_on",
                classmethod(
                    lambda cls, as_of=None: cls((as_of or DAY) - timedelta(days=89), as_of or DAY)
                ),
            )
            results = run_seeders(
                as_of=DAY, engine=engine, targets=("discharges",), log=lambda _: None
            )
            assert [result.name for result in results] == ["facilities", "admissions", "discharges"]
            repeated = run_seeders(
                as_of=DAY, engine=engine, targets=("discharges",), log=lambda _: None
            )
            assert all(result.changed_rows == 0 for result in repeated)
            # Deleting one event must repair its day and restore its deterministic identity.
            with engine.begin() as connection:
                target = connection.scalar(select(discharges.c.discharge_id).limit(1))
                connection.execute(discharges.delete().where(discharges.c.discharge_id == target))
            repaired = run_seeders(
                as_of=DAY, engine=engine, targets=("discharges",), log=lambda _: None
            )
            assert repaired[-1].row_count == results[-1].row_count
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(discharges.c.discharge_id).where(discharges.c.discharge_id == target)
                    )
                    == target
                )
            # Roll the date forward, retain overlapping events, and prune expired dates.
            run_seeders(
                as_of=DAY + timedelta(days=1),
                engine=engine,
                targets=("discharges",),
                log=lambda _: None,
            )
            with engine.connect() as connection:
                assert connection.scalar(
                    select(func.min(discharges.c.discharge_date))
                ) == DAY - timedelta(days=88)
                assert connection.scalar(
                    select(func.max(discharges.c.discharge_date))
                ) == DAY + timedelta(days=1)
        yield engine
    finally:
        engine.dispose()
        assert schema.startswith("discharge_test_") and len(schema) == 47
        with owner.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


@pytest.fixture
def client(discharge_engine, monkeypatch):
    monkeypatch.setattr(adt_discharges, "get_engine", lambda: discharge_engine)
    monkeypatch.setattr(adt_net_change, "get_engine", lambda: discharge_engine)
    monkeypatch.setattr(table_filters, "get_engine", lambda: discharge_engine)
    app = FastAPI()
    app.include_router(adt_discharges.router)
    app.include_router(adt_net_change.router)
    app.include_router(table_filters.router)
    with TestClient(app) as client:
        yield client


def test_net_change_reconciles_stays_events_and_previous_period(client, discharge_engine):
    start = DAY - timedelta(days=6)
    report = client.get("/api/v1/adt/net-change", params=PARAMS)
    assert report.status_code == 200
    data = report.json()
    assert data["prior_available"]
    assert len(data["items"]) == 253
    assert data["prior_start_date"] == str(start - timedelta(days=7))
    with discharge_engine.connect() as connection:
        for row in data["items"]:
            expected = connection.execute(
                text("""
                SELECT
                  (SELECT count(*) FROM adt_resident_stays WHERE facility_code = :code
                    AND start_date < :start AND (end_date IS NULL OR end_date >= :start)),
                  (SELECT count(*) FROM adt_resident_stays WHERE facility_code = :code
                    AND start_date <= :end AND (end_date IS NULL OR end_date > :end)),
                  (SELECT count(*) FROM adt_admissions WHERE facility_code = :code
                    AND admission_date BETWEEN :start AND :end),
                  (SELECT count(*) FROM adt_discharges WHERE facility_code = :code
                    AND discharge_date BETWEEN :start AND :end),
                  (SELECT count(*) FROM adt_admissions WHERE facility_code = :code
                    AND admission_date BETWEEN :prior AND :previous)
                  - (SELECT count(*) FROM adt_discharges WHERE facility_code = :code
                    AND discharge_date BETWEEN :prior AND :previous)
            """),
                {
                    "code": row["facility_code"],
                    "start": start,
                    "end": DAY,
                    "prior": start - timedelta(days=7),
                    "previous": start - timedelta(days=1),
                },
            ).one()
            assert tuple(
                row[key]
                for key in (
                    "opening_census",
                    "closing_census",
                    "admissions",
                    "discharges",
                    "prior_net_change",
                )
            ) == tuple(expected)
            assert row["net_change"] == row["admissions"] - row["discharges"]
            assert row["net_change"] == row["closing_census"] - row["opening_census"]


def test_net_change_rejects_uncovered_dates_and_marks_incomplete_prior(client):
    endpoint = "/api/v1/adt/net-change"
    assert (
        client.get(
            endpoint, params={"start_date": str(DAY), "end_date": str(DAY - timedelta(days=1))}
        ).status_code
        == 422
    )
    assert (
        client.get(
            endpoint, params={"start_date": str(DAY - timedelta(days=100)), "end_date": str(DAY)}
        ).status_code
        == 422
    )
    response = client.get(
        endpoint, params={"start_date": str(DAY - timedelta(days=88)), "end_date": str(DAY)}
    ).json()
    assert response["prior_available"] is False
    assert all(row["prior_net_change"] is None for row in response["items"])


def test_logs_reconcile_with_raw_discharge_dates_and_paginate_without_overlap(
    client, discharge_engine
):
    page = client.get("/api/v1/adt/discharges", params=PARAMS).json()
    with discharge_engine.connect() as connection:
        expected = connection.scalar(
            select(func.count())
            .select_from(discharges)
            .where(discharges.c.discharge_date.between(DAY - timedelta(days=6), DAY))
        )
    assert page["total"] == expected > 100
    assert len(page["items"]) == 50
    second = client.get("/api/v1/adt/discharges", params={**PARAMS, "offset": 50}).json()
    assert not (
        {row["discharge_id"] for row in page["items"]}
        & {row["discharge_id"] for row in second["items"]}
    )
    assert all(
        PARAMS["start_date"] <= row["discharge_date"] <= PARAMS["end_date"] for row in page["items"]
    )
    assert any(row["start_date"] < PARAMS["start_date"] for row in page["items"])


@pytest.mark.parametrize("key", adt_discharges.FILTER_KEYS)
def test_every_column_filter_applies_to_full_export(client, key):
    baseline = client.get("/api/v1/adt/discharges", params={**PARAMS, "export_all": True}).json()
    value = baseline["items"][0][key]
    result = client.get(
        "/api/v1/adt/discharges", params={**PARAMS, key: value, "export_all": True}
    ).json()
    expected = {row["discharge_id"] for row in baseline["items"] if row[key] == value}
    assert result["total"] == len(result["items"]) == len(expected)
    assert {row["discharge_id"] for row in result["items"]} == expected
    assert value in result["filter_options"][key]
    for option_key in adt_discharges.FILTER_KEYS:
        expected_options = {
            row[option_key] for row in baseline["items"] if option_key == key or row[key] == value
        }
        assert set(result["filter_options"][option_key]) == expected_options


def test_filter_options_combine_multiple_selections_and_search_and_restore_on_clear(client):
    baseline = client.get("/api/v1/adt/discharges", params={**PARAMS, "export_all": True}).json()
    selections = {"state": ["Texas", "Florida"], "payer_type": ["Managed Medicare"]}
    search = "Transfer"
    result = client.get(
        "/api/v1/adt/discharges",
        params={
            **PARAMS,
            **selections,
            "search": search,
            "page_size": 1,
        },
    ).json()
    for option_key in adt_discharges.FILTER_KEYS:
        expected = {
            row[option_key]
            for row in baseline["items"]
            if all(row[key] in values for key, values in selections.items() if key != option_key)
            and any(search.lower() in str(row[key]).lower() for key in adt_discharges.COLUMNS)
        }
        assert set(result["filter_options"][option_key]) == expected
    cleared = client.get("/api/v1/adt/discharges", params=PARAMS).json()
    assert cleared["filter_options"] == baseline["filter_options"]
    assert cleared["total"] == baseline["total"]


@pytest.mark.parametrize("column", list(adt_discharges.COLUMNS))
@pytest.mark.parametrize("direction", ["ascending", "descending"])
def test_sorting_uses_full_result_and_keeps_stable_page_order(client, column, direction):
    params = {**PARAMS, "sort_by": column, "sort_direction": direction}
    page = client.get("/api/v1/adt/discharges", params=params).json()
    full = client.get("/api/v1/adt/discharges", params={**params, "export_all": True}).json()
    assert page["items"] == full["items"][:50]
    values = [row[column] for row in full["items"]]
    assert values == sorted(values, reverse=direction == "descending")


@pytest.mark.parametrize(
    "search", ["Managed Medicare", "Deceased", "Texas", "%", "_", "no-such-person"]
)
def test_search_includes_displayed_fields_escapes_wildcards_and_combines_filters(client, search):
    baseline = client.get("/api/v1/adt/discharges", params={**PARAMS, "export_all": True}).json()
    expected = {
        row["discharge_id"]
        for row in baseline["items"]
        if row["state"] == "Texas"
        and any(search.lower() in str(row[key]).lower() for key in adt_discharges.COLUMNS)
    }
    result = client.get(
        "/api/v1/adt/discharges",
        params={**PARAMS, "search": search, "state": "Texas", "export_all": True},
    ).json()
    assert result["total"] == len(expected)
    assert {row["discharge_id"] for row in result["items"]} == expected


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": str(DAY)},
        {"start_date": str(DAY), "end_date": "2020-01-01"},
        {"offset": -1},
        {"page_size": 101},
        {"sort_by": "invalid"},
        {"sort_direction": "invalid"},
        {"search": "x" * 201},
    ],
)
def test_invalid_queries_are_rejected(client, params):
    assert client.get("/api/v1/adt/discharges", params=params).status_code == 422


def test_empty_results_preserve_table_response_shape(client):
    result = client.get(
        "/api/v1/adt/discharges", params={**PARAMS, "facility_name": "Missing"}
    ).json()
    assert result["items"] == []
    assert result["total"] == 0
    assert set(result["filter_options"]) == set(adt_discharges.FILTER_KEYS)


@pytest.mark.parametrize("source_id", ["admissions", "discharges"])
def test_shared_table_options_respect_filters_search_dates_and_own_column(
    client, discharge_engine, source_id
):
    source = table_filters.SOURCES[source_id]
    with discharge_engine.connect() as connection:
        rows = list(
            connection.execute(
                select(*(column.label(key) for key, column in source.columns.items()))
                .select_from(source.joined)
                .where(source.date_column == DAY)
            ).mappings()
        )
    payer_key = "payer" if source_id == "admissions" else "payer_type"
    selections = {"state": ["Texas", "Florida"], payer_key: ["Medicaid"], "portfolio": ["Texas 1"]}
    for column in ("state", "portfolio", "region", payer_key):
        response = client.get(
            f"/api/v1/table-filter-options/{source_id}",
            params={
                "start_date": str(DAY),
                "end_date": str(DAY),
                "column": column,
                "filters": json.dumps(selections),
            },
        )
        assert response.status_code == 200
        expected = {
            row[column]
            for row in rows
            if all(row[key] in values for key, values in selections.items() if key != column)
        }
        assert set(response.json()["options"]) == expected
    # Search is applied to all rows in the date range, including records beyond a page.
    response = client.get(
        f"/api/v1/table-filter-options/{source_id}",
        params={
            "start_date": str(DAY),
            "end_date": str(DAY),
            "column": "portfolio",
            "search": "Medicaid",
            "filters": json.dumps({"state": ["Texas"]}),
        },
    )
    assert set(response.json()["options"]) == {
        row["portfolio"]
        for row in rows
        if row["state"] == "Texas"
        and any("medicaid" in str(value).lower() for value in row.values())
    }
    for search in ("%", "_", "no-such-person"):
        response = client.get(
            f"/api/v1/table-filter-options/{source_id}",
            params={
                "start_date": str(DAY),
                "end_date": str(DAY),
                "column": "portfolio",
                "search": search,
            },
        )
        assert response.json()["options"] == []


@pytest.mark.parametrize("filters", ['{"invalid":["x"]}', "[]", "{", '{"state":"Texas"}'])
def test_shared_filter_endpoint_rejects_invalid_filter_contracts(client, filters):
    response = client.get(
        "/api/v1/table-filter-options/discharges",
        params={
            **PARAMS,
            "column": "state",
            "filters": filters,
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("length", [1, 7, 30])
def test_overview_totals_and_prior_period_match_raw_logs(client, discharge_engine, length):
    start = DAY - timedelta(days=length - 1)
    response = client.get(
        "/api/v1/adt/discharges/overview",
        params={
            "start_date": str(start),
            "end_date": str(DAY),
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["days"] == length
    assert result["prior_start_date"] == str(start - timedelta(days=length))
    assert result["prior_end_date"] == str(start - timedelta(days=1))
    assert len(result["items"]) == 253
    with discharge_engine.connect() as connection:
        for field, lower, upper in (
            ("total_discharges", start, DAY),
            ("prior_period_discharges", start - timedelta(days=length), start - timedelta(days=1)),
        ):
            expected = dict(
                connection.execute(
                    select(discharges.c.facility_code, func.count())
                    .where(discharges.c.discharge_date.between(lower, upper))
                    .group_by(discharges.c.facility_code)
                ).all()
            )
            assert sum(row[field] for row in result["items"]) == sum(expected.values())
            assert all(
                row[field] == expected.get(row["facility_code"], 0) for row in result["items"]
            )


def test_overview_keeps_all_zero_activity_facilities_and_validates_dates(client):
    result = client.get(
        "/api/v1/adt/discharges/overview",
        params={
            "start_date": "2000-01-01",
            "end_date": "2000-01-30",
        },
    ).json()
    assert len(result["items"]) == 253
    assert all(
        row["total_discharges"] == row["prior_period_discharges"] == 0 for row in result["items"]
    )
    assert (
        client.get(
            "/api/v1/adt/discharges/overview",
            params={
                "start_date": "2026-09-15",
                "end_date": "2026-09-01",
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize("depth", [0, 1, 2, 3, 4])
def test_discharge_type_ranking_matches_logs_at_every_drilldown_level(client, depth):
    target = client.get("/api/v1/adt/discharges", params=PARAMS).json()["items"][0]
    scope = {key: target[key] for key in ("state", "portfolio", "region", "facility_name")[:depth]}
    params = {**PARAMS, **scope}
    response = client.get("/api/v1/adt/discharges/by-type", params=params)
    assert response.status_code == 200
    ranked = response.json()
    logs = client.get("/api/v1/adt/discharges", params={**params, "export_all": True}).json()
    assert {item["label"] for item in ranked} == set(DISCHARGE_TYPES)
    assert sum(item["value"] for item in ranked) == logs["total"]
    for item in ranked:
        assert item["value"] == sum(row["discharge_type"] == item["label"] for row in logs["items"])
    assert ranked == sorted(ranked, key=lambda item: (-item["value"], item["label"]))


def test_discharge_type_ranking_preserves_zero_categories_and_rejects_reversed_dates(client):
    response = client.get("/api/v1/adt/discharges/by-type", params={**PARAMS, "state": "Missing"})
    assert response.status_code == 200
    assert len(response.json()) == 4
    assert all(item["value"] == 0 for item in response.json())
    assert (
        client.get(
            "/api/v1/adt/discharges/by-type",
            params={
                "start_date": "2026-09-15",
                "end_date": "2026-09-01",
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize("depth", [0, 1, 2, 3, 4])
def test_discharge_payer_donut_matches_logs_and_type_chart_at_every_level(client, depth):
    target = client.get("/api/v1/adt/discharges", params=PARAMS).json()["items"][0]
    scope = {key: target[key] for key in ("state", "portfolio", "region", "facility_name")[:depth]}
    params = {**PARAMS, **scope}
    response = client.get("/api/v1/adt/discharges/by-payer", params=params)
    assert response.status_code == 200
    items = response.json()
    logs = client.get("/api/v1/adt/discharges", params={**params, "export_all": True}).json()
    types = client.get("/api/v1/adt/discharges/by-type", params=params).json()
    assert (
        sum(item["value"] for item in items)
        == logs["total"]
        == sum(item["value"] for item in types)
    )
    assert [item["label"] for item in items] == sorted(item["label"] for item in items)
    assert "Managed Medicare" in [item["label"] for item in items]
    for item in items:
        assert item["value"] == sum(row["payer_type"] == item["label"] for row in logs["items"])


def test_discharge_payer_donut_keeps_empty_categories_and_validates_dates(client):
    response = client.get("/api/v1/adt/discharges/by-payer", params={**PARAMS, "state": "Missing"})
    assert response.status_code == 200
    assert len(response.json()) == 6
    assert all(item["value"] == 0 for item in response.json())
    assert (
        client.get(
            "/api/v1/adt/discharges/by-payer",
            params={
                "start_date": "2026-09-15",
                "end_date": "2026-09-01",
            },
        ).status_code
        == 422
    )


def test_reconciliation_repairs_discharge_labels_and_preserves_resident_fields(
    discharge_engine, monkeypatch
):
    from app.seeding import resident_movement
    from app.seeding.base import SeedContext, datasets

    monkeypatch.setattr(resident_movement, "ANCHOR", DAY - timedelta(days=270))
    from app.seeding.discharges import GENERATOR_VERSION, DischargesSeeder

    with discharge_engine.begin() as connection:
        before = (
            connection.execute(select(discharges).order_by(discharges.c.discharge_id))
            .mappings()
            .all()
        )
        connection.execute(
            discharges.update()
            .where(discharges.c.discharge_type == "Deceased")
            .values(destination_type="Not applicable")
        )
        connection.execute(
            datasets.update()
            .where(datasets.c.name == "discharges")
            .values(version="discharges-daily-v1")
        )
        context = SeedContext(
            connection,
            SeedWindow(DAY - timedelta(days=88), DAY + timedelta(days=1)),
            log=lambda _: None,
        )
        seeder = DischargesSeeder()
        result = seeder.seed(context)
        seeder.validate(context, result)
        assert result.changed_rows == 2 * len(before)
        after = (
            connection.execute(select(discharges).order_by(discharges.c.discharge_id))
            .mappings()
            .all()
        )
        assert after == before
        assert (
            connection.scalar(select(datasets.c.version).where(datasets.c.name == "discharges"))
            == GENERATOR_VERSION
        )
        assert seeder.seed(context).changed_rows == 0


@pytest.mark.parametrize("depth", [0, 1, 2, 3, 4])
def test_destination_ranking_matches_logs_at_each_drilldown_level(client, depth):
    target = client.get("/api/v1/adt/discharges", params=PARAMS).json()["items"][0]
    scope = {key: target[key] for key in ("state", "portfolio", "region", "facility_name")[:depth]}
    params = {**PARAMS, **scope}
    response = client.get("/api/v1/adt/discharges/by-destination", params=params)
    assert response.status_code == 200
    items = response.json()
    logs = client.get("/api/v1/adt/discharges", params={**params, "export_all": True}).json()
    assert sum(item["value"] for item in items) == logs["total"]
    assert {item["label"] for item in items} == {row["destination_type"] for row in logs["items"]}
    for item in items:
        assert item["value"] == sum(
            row["destination_type"] == item["label"] for row in logs["items"]
        )
    assert items == sorted(items, key=lambda item: (-item["value"], item["label"]))
    if depth == 0:
        assert "Funeral Home" in {item["label"] for item in items}


def test_destination_ranking_empty_results_and_invalid_dates(client):
    response = client.get(
        "/api/v1/adt/discharges/by-destination", params={**PARAMS, "state": "Missing"}
    )
    assert response.status_code == 200
    assert response.json() == []
    assert (
        client.get(
            "/api/v1/adt/discharges/by-destination",
            params={
                "start_date": "2026-09-15",
                "end_date": "2026-09-01",
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize("depth", [0, 1, 2, 3, 4])
@pytest.mark.parametrize(
    "selection",
    [
        {"payer_type": ["Managed Medicare", "Medicare"], "destination_type": ["Home", "Hospital"]},
        {"destination_type": ["Funeral Home"]},
    ],
)
def test_chart_filters_ama_and_daily_trend_reconcile_with_logs(client, depth, selection):
    target = client.get("/api/v1/adt/discharges", params=PARAMS).json()["items"][0]
    scope = {key: target[key] for key in ("state", "portfolio", "region", "facility_name")[:depth]}
    params = {**PARAMS, **selection, **scope}
    logs = client.get("/api/v1/adt/discharges", params={**params, "export_all": True}).json()
    overview = client.get("/api/v1/adt/discharges/overview", params={**PARAMS, **selection}).json()
    rows = [
        row for row in overview["items"] if all(row[key] == value for key, value in scope.items())
    ]
    assert sum(row["total_discharges"] for row in rows) == logs["total"]
    assert sum(row["ama_discharges"] for row in rows) == sum(
        row["discharge_type"] == "AMA" for row in logs["items"]
    )
    for row in rows:
        assert row["hospital_transfers"] == sum(
            log["facility_name"] == row["facility_name"]
            and log["discharge_type"] == "Transfer"
            and log["destination_type"] == "Hospital"
            for log in logs["items"]
        )
    for row in rows:
        assert 0 <= row["ama_discharges"] <= row["total_discharges"]
    trend = client.get("/api/v1/adt/discharges/daily-trend", params=params).json()
    assert len(trend) == 7
    assert [row["date"] for row in trend] == [
        str(DAY - timedelta(days=6 - index)) for index in range(7)
    ]
    assert sum(row["value"] for row in trend) == logs["total"]
    for point in trend:
        assert point["value"] == sum(
            row["discharge_date"] == point["date"] for row in logs["items"]
        )
    # A chart applies the opposite chart's filter but retains its own alternatives.
    destinations = client.get(
        "/api/v1/adt/discharges/by-destination",
        params={
            **PARAMS,
            **scope,
            **{key: value for key, value in selection.items() if key != "destination_type"},
        },
    ).json()
    payers = client.get(
        "/api/v1/adt/discharges/by-payer",
        params={
            **PARAMS,
            **scope,
            **{key: value for key, value in selection.items() if key != "payer_type"},
        },
    ).json()
    assert (
        sum(
            item["value"]
            for item in destinations
            if not selection.get("destination_type")
            or item["label"] in selection["destination_type"]
        )
        == logs["total"]
    )
    assert (
        sum(
            item["value"]
            for item in payers
            if not selection.get("payer_type") or item["label"] in selection["payer_type"]
        )
        == logs["total"]
    )
    prior_params = {
        **selection,
        **scope,
        "start_date": overview["prior_start_date"],
        "end_date": overview["prior_end_date"],
    }
    prior = client.get("/api/v1/adt/discharges", params=prior_params).json()
    assert sum(row["prior_period_discharges"] for row in rows) == prior["total"]


def test_daily_trend_keeps_zero_days_and_rejects_invalid_range(client):
    response = client.get(
        "/api/v1/adt/discharges/daily-trend", params={**PARAMS, "state": "Missing"}
    )
    assert response.status_code == 200
    assert len(response.json()) == 7
    assert all(point["value"] == 0 for point in response.json())
    assert (
        client.get(
            "/api/v1/adt/discharges/daily-trend",
            params={
                "start_date": "2026-09-15",
                "end_date": "2026-09-01",
            },
        ).status_code
        == 422
    )
