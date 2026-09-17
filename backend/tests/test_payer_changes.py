"""Reconcile transitions, drill-downs and exports against isolated coverage histories."""

import json
from collections import defaultdict
from datetime import date, timedelta
from uuid import uuid4

import pytest
from app import adt_payer_changes, table_filters
from app.database import get_engine
from app.seeding.admissions import PAYER_NAMES
from app.seeding.base import SeedWindow
from app.seeding.facilities import build_facility_rows
from app.seeding.payer_changes import PayerChangesSeeder, build_daily_payer_changes, payer_changes
from app.seeding.runner import run_seeders
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.schema import CreateSchema, DropSchema

DAY = date(2026, 9, 15)
PARAMS = {"start_date": str(DAY - timedelta(days=59)), "end_date": str(DAY)}
URL = "/api/v1/adt/payer-changes"


def test_generator_is_stable_and_resident_histories_are_contiguous():
    facilities = build_facility_rows()[:5]
    histories = defaultdict(list)
    for offset in range(180):
        day = DAY - timedelta(days=offset)
        rows = build_daily_payer_changes(day, facilities)
        assert rows == build_daily_payer_changes(day, list(reversed(facilities)))
        for row in rows:
            assert row["effective_date"] == day
            for side in ("previous", "new"):
                assert row[f"{side}_payer_name"] in PAYER_NAMES[row[f"{side}_payer_type"]]
            assert (row["change_category"] == "Plan only") == (
                row["previous_payer_type"] == row["new_payer_type"]
            )
            assert (row["previous_payer_type"], row["previous_payer_name"]) != (
                row["new_payer_type"],
                row["new_payer_name"],
            )
            histories[row["resident_id"]].append(row)
    assert any(len(rows) > 1 for rows in histories.values())
    for rows in histories.values():
        rows.sort(key=lambda row: row["effective_date"])
        for previous, current in zip(rows, rows[1:]):
            assert previous["new_payer_type"] == current["previous_payer_type"]
            assert previous["new_payer_name"] == current["previous_payer_name"]
            assert previous["new_payer_end_date"] == current["effective_date"]
            assert current["previous_payer_start_date"] == previous["effective_date"]


@pytest.fixture(scope="module")
def engine():
    owner = get_engine()
    schema = f"payer_test_{uuid4().hex}"
    with owner.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = create_engine(owner.url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                SeedWindow,
                "ending_on",
                classmethod(
                    lambda cls, as_of=None: cls((as_of or DAY) - timedelta(days=179), as_of or DAY)
                ),
            )
            results = run_seeders(
                as_of=DAY, engine=isolated, targets=("payer_changes",), log=lambda _: None
            )
            assert [result.name for result in results] == ["facilities", "payer_changes"]
            repeated = run_seeders(
                as_of=DAY, engine=isolated, targets=("payer_changes",), log=lambda _: None
            )
            assert all(result.changed_rows == 0 for result in repeated)
            with isolated.begin() as connection:
                target = connection.execute(select(payer_changes).limit(1)).mappings().one()
                connection.execute(
                    payer_changes.delete().where(payer_changes.c.change_id == target["change_id"])
                )
            repaired = run_seeders(
                as_of=DAY, engine=isolated, targets=("payer_changes",), log=lambda _: None
            )
            assert repaired[-1].row_count == results[-1].row_count
            with isolated.connect() as connection:
                restored = (
                    connection.execute(
                        select(payer_changes).where(
                            payer_changes.c.change_id == target["change_id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                assert dict(restored) == dict(target)
            # A validation failure must roll back a rolling-window update.
            with pytest.MonkeyPatch.context() as failure:

                def fail(*args):
                    raise ValueError("rollback check")

                failure.setattr(PayerChangesSeeder, "validate", fail)
                with pytest.raises(ValueError, match="rollback check"):
                    run_seeders(
                        as_of=DAY + timedelta(days=1),
                        engine=isolated,
                        targets=("payer_changes",),
                        log=lambda _: None,
                    )
            with isolated.connect() as connection:
                assert connection.scalar(select(func.max(payer_changes.c.effective_date))) == DAY
                assert (
                    connection.scalar(select(func.count()).select_from(payer_changes))
                    == results[-1].row_count
                )
        yield isolated
    finally:
        isolated.dispose()
        assert schema.startswith("payer_test_") and len(schema) == 43
        with owner.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(adt_payer_changes, "get_engine", lambda: engine)
    monkeypatch.setattr(table_filters, "get_engine", lambda: engine)
    app = FastAPI()
    app.include_router(adt_payer_changes.router)
    app.include_router(table_filters.router)
    return TestClient(app)


def get(client, path="", **params):
    response = client.get(URL + path, params={**PARAMS, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_overview_totals_distinct_residents_prior_and_zero_facilities(client, engine):
    overview = get(client, "/overview")
    assert len(overview["items"]) == 253
    current = get(client, export_all=True, change_category="Payer type")
    assert sum(row["total"] for row in overview["items"]) == current["total"]
    prior = get(
        client,
        start_date=overview["prior_start_date"],
        end_date=overview["prior_end_date"],
        change_category="Payer type",
    )
    assert sum(row["prior"] for row in overview["items"]) == prior["total"]
    with engine.connect() as connection:
        residents = connection.scalar(
            select(func.count(func.distinct(payer_changes.c.resident_id))).where(
                payer_changes.c.effective_date.between(
                    date.fromisoformat(PARAMS["start_date"]), date.fromisoformat(PARAMS["end_date"])
                ),
                payer_changes.c.change_category == "Payer type",
            )
        )
    assert sum(row["residents"] for row in overview["items"]) == residents
    assert residents < current["total"]
    empty = get(client, "/overview", start_date="2030-01-01", end_date="2030-01-01")
    assert len(empty["items"]) == 253
    assert all(row["total"] == row["residents"] == row["prior"] == 0 for row in empty["items"])


def test_all_donuts_reconcile_and_each_slice_opens_matching_logs(client):
    facility = get(client, "/overview")["items"][0]
    for depth in range(5):
        keys = ["state", "portfolio", "region", "facility_name"][:depth]
        scope = {key: facility[key] for key in keys}
        count = 0
        for payer in PAYER_NAMES:
            label = "Managed Medicare" if payer == "Medicare Advantage" else payer
            slices = get(client, "/transitions", previous_payer_type=label, **scope)
            for item in slices:
                assert item["label"] != label
                logs = get(
                    client,
                    previous_payer_type=label,
                    new_payer_type=item["label"],
                    change_category="Payer type",
                    **scope,
                )
                assert logs["total"] == item["value"]
                count += item["value"]
        assert count == get(client, change_category="Payer type", **scope)["total"]


def test_search_pagination_sort_export_and_plan_only_changes(client):
    all_rows = get(client, export_all=True)
    assert all_rows["total"] == len(all_rows["items"]) > 100
    assert len({row["change_id"] for row in all_rows["items"]}) == all_rows["total"]
    first = get(client)
    second = get(client, offset=50)
    assert first["items"] == all_rows["items"][:50]
    assert second["items"] == all_rows["items"][50:100]
    target = second["items"][0]
    selected = get(
        client,
        search=target["resident_name"].swapcase(),
        previous_payer_type=target["previous_payer_type"],
        export_all=True,
    )
    expected = [
        row
        for row in all_rows["items"]
        if row["resident_name"] == target["resident_name"]
        and row["previous_payer_type"] == target["previous_payer_type"]
    ]
    assert selected["items"] == expected
    for search in ("%", "_", "nonexistent-resident"):
        assert get(client, search=search)["total"] == 0
    managed = get(client, search="Managed Medicare", export_all=True)
    assert managed["total"] > 0
    assert all(
        "Managed Medicare" in (row["previous_payer_type"], row["new_payer_type"])
        for row in managed["items"]
    )
    plans = get(client, change_category="Plan only", export_all=True)
    assert plans["total"] > 0
    assert all(row["previous_payer_type"] == row["new_payer_type"] for row in plans["items"])
    ascending = get(client, sort_by="effective_date", sort_direction="ascending")["items"]
    assert [row["effective_date"] for row in ascending] == sorted(
        row["effective_date"] for row in ascending
    )


def test_shared_cascading_options_respect_other_columns_and_search(client):
    filters = {
        "previous_payer_type": ["Medicare"],
        "new_payer_type": ["Medicaid"],
        "change_category": ["Payer type"],
        "state": ["Texas"],
    }
    rows = get(
        client,
        previous_payer_type="Medicare",
        change_category="Payer type",
        state="Texas",
        search="Medicare",
        export_all=True,
    )["items"]
    response = client.get(
        "/api/v1/table-filter-options/payer-changes",
        params={
            **PARAMS,
            "column": "new_payer_type",
            "filters": json.dumps(filters),
            "search": "Medicare",
        },
    )
    assert response.status_code == 200
    assert set(response.json()["options"]) == {row["new_payer_type"] for row in rows}
    assert len(response.json()["options"]) > 1


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-10-01"},
        {"sort_by": "invalid"},
        {"offset": -1},
        {"page_size": 101},
        {"search": "x" * 201},
        {"start_date": "0001-01-01"},
    ],
)
def test_invalid_requests_are_rejected(client, params):
    assert client.get(URL, params={**PARAMS, **params}).status_code == 422


def test_payer_los_uses_full_periods_and_sorts_numerically(client, engine):
    exported = get(client, export_all=True)
    with engine.connect() as connection:
        raw = {
            row["change_id"]: row for row in connection.execute(select(payer_changes)).mappings()
        }
    for row in exported["items"]:
        event = raw[row["change_id"]]
        assert (
            row["previous_los_days"]
            == (event["effective_date"] - event["previous_payer_start_date"]).days
        )
        end = event["new_payer_end_date"]
        assert row["new_los_days"] == max(
            0, (min(end or date.today(), date.today()) - event["effective_date"]).days
        )
        assert row["new_los_ongoing"] == (end is None or end > date.today())
    # Selecting only the event day must not truncate the following payer period.
    event = exported["items"][-1]
    same_day = get(
        client,
        start_date=event["effective_date"],
        end_date=event["effective_date"],
        export_all=True,
    )
    match = next(row for row in same_day["items"] if row["change_id"] == event["change_id"])
    assert match == event
    assert match["new_los_days"] > 0
    for key in ("previous_los_days", "new_los_days"):
        sorted_rows = get(client, sort_by=key, sort_direction="ascending", export_all=True)["items"]
        assert [row[key] for row in sorted_rows] == sorted(row[key] for row in sorted_rows)


def test_ongoing_same_day_and_completed_periods(client, engine):
    # Use a rollback-only transaction so other fixture tests retain their dataset.
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            target = connection.scalar(select(payer_changes.c.change_id).limit(1))
            for age, end, expected, ongoing in (
                (10, None, 10, True),
                (10, date.today() + timedelta(days=4), 10, True),
                (10, date.today() - timedelta(days=3), 7, False),
                (0, date.today(), 0, False),
            ):
                effective = date.today() - timedelta(days=age)
                connection.execute(
                    payer_changes.update()
                    .where(payer_changes.c.change_id == target)
                    .values(
                        effective_date=effective,
                        previous_payer_start_date=effective - timedelta(days=24),
                        new_payer_end_date=end,
                    )
                )
                row = (
                    connection.execute(
                        select(
                            table_filters.PAYER_CHANGE_COLUMNS["previous_los_days"].label(
                                "previous"
                            ),
                            table_filters.PAYER_CHANGE_COLUMNS["new_los_days"].label("new"),
                            (
                                payer_changes.c.new_payer_end_date.is_(None)
                                | (payer_changes.c.new_payer_end_date > date.today())
                            ).label("ongoing"),
                        ).where(payer_changes.c.change_id == target)
                    )
                    .mappings()
                    .one()
                )
                assert dict(row) == {"previous": 24, "new": expected, "ongoing": ongoing}
        finally:
            transaction.rollback()


@pytest.mark.parametrize("column", ["previous_los_days", "new_los_days"])
@pytest.mark.parametrize(
    "values",
    [["equal", "40"], ["greater-than", "25"], ["less-than", "10"], ["between", "30", "10"]],
)
def test_los_filters_match_full_export_and_pagination(client, column, values):
    rows = get(client, export_all=True)["items"]

    def matches(row):
        value = row[column]
        if values[0] == "equal":
            return value == 40
        if values[0] == "greater-than":
            return value > 25
        if values[0] == "less-than":
            return value < 10
        return 10 <= value <= 30

    expected = [row for row in rows if matches(row)]
    selected = get(client, export_all=True, **{column: values})
    assert selected["items"] == expected
    assert selected["total"] == len(expected)
    assert get(client, **{column: values})["items"] == expected[:50]


def test_both_los_filters_cascade_into_payer_options(client):
    filters = {"previous_los_days": ["greater-than", "40"], "new_los_days": ["between", "0", "15"]}
    rows = get(client, export_all=True, **filters)["items"]
    assert rows
    assert all(row["previous_los_days"] > 40 and 0 <= row["new_los_days"] <= 15 for row in rows)
    response = client.get(
        "/api/v1/table-filter-options/payer-changes",
        params={
            **PARAMS,
            "column": "new_payer_type",
            "filters": json.dumps(filters),
        },
    )
    assert response.status_code == 200
    assert set(response.json()["options"]) == {row["new_payer_type"] for row in rows}


@pytest.mark.parametrize("values", [["equal", "NaN"], ["between", "2"], ["invalid", "2"]])
def test_invalid_los_filters_are_rejected(client, values):
    assert client.get(URL, params={**PARAMS, "new_los_days": values}).status_code == 422


def test_encoded_numeric_filters_survive_shared_option_normalization(client):
    filters = {
        "previous_los_days": [json.dumps(["greater-than", "40"])],
        "new_los_days": [json.dumps(["between", "10", "10"])],
    }
    result = get(client, export_all=True, **filters)
    expected = get(
        client,
        export_all=True,
        previous_los_days=["greater-than", "40"],
        new_los_days=["equal", "10"],
    )
    assert result == expected
    response = client.get(
        "/api/v1/table-filter-options/payer-changes",
        params={**PARAMS, "column": "new_payer_type", "filters": json.dumps(filters)},
    )
    assert response.status_code == 200
    assert set(response.json()["options"]) == {row["new_payer_type"] for row in result["items"]}
