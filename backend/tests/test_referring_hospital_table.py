from datetime import timedelta

import pytest
from app.admissions_reporting import state
from app.adt_admissions import STATE_NAMES, comparison_metrics
from app.database import get_engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select, text

client = TestClient(app)
ENDPOINT = "/api/v1/adt/admissions/by-referring-hospital"


@pytest.mark.parametrize("period_days,scope,window", [
    (30, False, "current"), (1, False, "current"), (30, True, "current"),
    (30, False, "prior-only"), (30, False, "empty"),
])
def test_hospital_table_matches_raw_admissions(period_days, scope, window):
    with get_engine().connect() as connection:
        first, latest = connection.execute(
            select(state.c.first_date, state.c.latest_date).where(state.c.id == 1)
        ).one()
        end = latest if window == "current" else (
            latest + timedelta(days=period_days) if window == "prior-only"
            else first - timedelta(days=1)
        )
        start = end - timedelta(days=period_days - 1)
        prior_start = start - timedelta(days=period_days)
        raw = connection.execute(text("""
            SELECT a.*, f.name AS facility_name, f.portfolio, f.region
            FROM adt_admissions a JOIN facilities f USING (facility_code)
            WHERE a.admission_date BETWEEN :start AND :end
        """), {"start": prior_start, "end": end}).mappings().all()
    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    hospitals = [row for row in raw if row["admission_source_type"] == "Hospital"]
    if scope:
        target = hospitals[0]
        params.update(facility=target["facility_name"], portfolio=target["portfolio"],
                      region=target["region"], payer_type=target["payer_type"])
        hospitals = [row for row in hospitals
                     if all(row[key] == target[key]
                            for key in ["facility_name", "portfolio", "region", "payer_type"])]
    expected = {}
    receiving_facilities = {}
    for row in hospitals:
        facilities = receiving_facilities.setdefault(row["admission_source_name"], set())
        metrics = expected.setdefault(row["admission_source_name"], {
            "admission_count": 0, "prior_period_admissions": 0,
            "readmission_count": 0, "readmission_within_30_days_count": 0,
        })
        if row["admission_date"] < start:
            metrics["prior_period_admissions"] += 1
        else:
            facilities.add(row["facility_code"])
            metrics["admission_count"] += 1
            if row["is_readmission"]:
                metrics["readmission_count"] += 1
                days = row["readmission_days_since_prior"]
                if days is not None and days <= 30:
                    metrics["readmission_within_30_days_count"] += 1
    response = client.get(ENDPOINT, params=params)
    assert response.status_code == 200
    rows = response.json()
    assert {row["hospital"] for row in rows} == set(expected)
    assert len(rows) == len(expected)
    for row in rows:
        assert row["receiving_facility_codes"] == sorted(receiving_facilities[row["hospital"]])
        assert len(row["receiving_facility_codes"]) <= row["admission_count"]
        for key, value in expected[row["hospital"]].items():
            assert row[key] == value
        assert row["admissions_change"] == row["admission_count"] - row["prior_period_admissions"]
        assert row["average_admissions_per_day"] == row["admission_count"] / period_days
        assert 0 <= row["readmission_within_30_days_count"] <= row["readmission_count"]
        assert row["readmission_count"] <= row["admission_count"]
    if window == "prior-only":
        assert rows
        assert all(row["admission_count"] == 0 and row["admissions_change"] < 0 for row in rows)
    elif window == "empty":
        assert rows == []
    else:
        assert rows
        assert [row["admission_count"] for row in rows] == sorted(
            [row["admission_count"] for row in rows], reverse=True
        )
    no_matches = client.get(ENDPOINT, params={**params, "payer_type": "NO_MATCH"})
    assert no_matches.status_code == 200
    assert no_matches.json() == []


def test_hospital_table_rejects_reversed_dates():
    response = client.get(ENDPOINT, params={"start_date": "2026-09-15", "end_date": "2026-09-01"})
    assert response.status_code == 422


@pytest.mark.parametrize("depth", range(5))
@pytest.mark.parametrize("source_types", [None, ["Hospital", "Home"], ["Home"]])
def test_modal_hospitals_match_overview_counts_at_each_level(depth, source_types):
    with get_engine().connect() as connection:
        end = connection.scalar(select(state.c.latest_date).where(state.c.id == 1))
        target = connection.execute(text(
            "SELECT name, state, portfolio, region FROM facilities ORDER BY facility_code LIMIT 1"
        )).mappings().one()
    start = end - timedelta(days=29)
    params = {"start_date": start.isoformat(), "end_date": end.isoformat(),
              "payer_type": "Medicare"}
    if source_types:
        params["source_type"] = source_types
    for index, key in enumerate(["state", "portfolio", "region", "name"]):
        if index < depth:
            params["facility" if key == "name" else key] = (
                STATE_NAMES[target[key]] if key == "state" else target[key]
            )
    level = "facility" if depth == 4 else "region" if depth == 3 else "portfolio"
    overview = comparison_metrics(start, end, level, ["Medicare"], source_types)
    expected = set()
    for row in overview:
        if depth >= 1 and row["state"] != STATE_NAMES[target["state"]]:
            continue
        portfolio_key = "region" if level == "portfolio" else "portfolio"
        if depth >= 2 and row[portfolio_key] != target["portfolio"]:
            continue
        if depth >= 3 and row["region"] != target["region"]:
            continue
        if depth == 4 and row["facility_name"] != target["name"]:
            continue
        expected.update(row["referring_hospitals"])
    response = client.get(ENDPOINT, params=params)
    assert response.status_code == 200
    current_rows = [row for row in response.json() if row["admission_count"] > 0]
    assert {row["hospital"] for row in current_rows} == expected
    assert len(current_rows) == len(expected)
    if current_rows:
        hospital = current_rows[0]
        logs_response = client.get("/api/v1/adt/admissions", params={
            **params, "source_type": "Hospital", "admission_source": hospital["hospital"],
        })
        assert logs_response.status_code == 200
        logs = logs_response.json()
        assert logs["total"] == hospital["admission_count"]
        assert all(row["admission_source_name"] == hospital["hospital"]
                   and row["admission_source_type"] == "Hospital" for row in logs["items"])
    with get_engine().connect() as connection:
        clauses = ["a.admission_date BETWEEN :start AND :end",
                   "a.admission_source_type = 'Hospital'", "a.payer_type = 'Medicare'"]
        raw_params = {"start": start, "end": end}
        for index, key in enumerate(["state", "portfolio", "region", "name"]):
            if index < depth:
                clauses.append(f"f.{key} = :{key}")
                raw_params[key] = target[key]
        count = connection.scalar(text(
            "SELECT count(*) FROM adt_admissions a JOIN facilities f USING (facility_code) WHERE "
            + " AND ".join(clauses)
        ), raw_params)
    assert sum(row["admission_count"] for row in current_rows) == (
        0 if source_types == ["Home"] else count
    )
