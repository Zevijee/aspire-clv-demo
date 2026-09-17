from datetime import timedelta

from app.admissions_reporting import state
from app.database import get_engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select

with get_engine().connect() as connection:
    reporting_end = connection.scalar(select(state.c.latest_date).where(state.c.id == 1))
REPORT_END = reporting_end.isoformat()
REPORT_START = (reporting_end - timedelta(days=29)).isoformat()


def test_facilities_follow_state_portfolio_region_hierarchy() -> None:
    response = TestClient(app).get("/api/v1/facilities")

    assert response.status_code == 200
    facilities = response.json()
    portfolios: dict[str, dict[str, set[str]]] = {}
    for facility in facilities:
        portfolio = facility["portfolio"]
        portfolio_data = portfolios.setdefault(portfolio, {"regions": set(), "states": set()})
        portfolio_data["regions"].add(facility["region"])
        portfolio_data["states"].add(facility["state"])

    assert portfolios
    assert all(len(data["states"]) == 1 for data in portfolios.values())
    assert all(5 <= len(data["regions"]) <= 10 for data in portfolios.values())
    assert {
        state: len({facility["portfolio"] for facility in facilities if facility["state"] == state})
        for state in ("FL", "PA", "TX")
    } == {"FL": 3, "PA": 1, "TX": 5}


def test_admission_logs_are_paginated() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] > 50
    assert len(payload["items"]) == 50


def test_admission_logs_filter_and_sort_before_pagination() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions",
        params=[
            ("start_date", REPORT_START),
            ("end_date", REPORT_END),
            ("payer_type", "Medicare"),
            ("sort_by", "admission-date"),
            ("sort_direction", "ascending"),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    items = payload["items"]

    assert payload["total"] > len(items)
    assert all(item["payer_type"] == "Medicare" for item in items)
    assert [item["admission_date"] for item in items] == sorted(
        item["admission_date"] for item in items
    )
    assert payload["filter_options"]["facility"]
    assert payload["filter_options"]["payer"]
    assert payload["filter_options"]["admission_source"]


def test_admissions_kpis_include_prior_period_comparison() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/kpis",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    payload = response.json()
    prior_period = payload["prior_period"]

    assert payload["days_in_range"] == 30
    assert payload["total_admissions"] >= payload["readmission_count"] >= 0
    assert payload["readmission_count"] >= payload["readmission_within_30_days_count"] >= 0
    assert prior_period["total_admissions"] >= prior_period["readmission_count"] >= 0
    assert payload["unique_admission_source_count"] >= 0
    assert prior_period["unique_admission_source_count"] >= 0


def test_daily_admissions_trend_returns_each_requested_day() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/daily-trend",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    trend = response.json()

    assert len(trend) == 30
    assert trend[0]["admission_date"] == REPORT_START
    assert trend[-1]["admission_date"] == REPORT_END
    assert all(item["admission_count"] >= 0 for item in trend)


def test_admissions_by_region_returns_ranked_totals() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/by-region",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    ranking = response.json()

    assert ranking
    assert all(item["admission_count"] > 0 for item in ranking)
    assert ranking == sorted(
        ranking,
        key=lambda item: (-item["admission_count"], item["region"]),
    )


def test_admissions_by_region_metrics_include_prior_period_comparison() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/by-region/metrics",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    metrics = response.json()

    assert metrics
    assert all(
        metric["state"]
        and metric["facility_count"] > 0
        and metric["total_admissions"] >= 0
        and metric["readmission_count"] >= 0
        and metric["medicare_admission_count"] >= 0
        and metric["prior_period_admissions"] >= 0
        and metric["prior_period_medicare_admission_count"] >= 0
        and metric["admissions_change"]
        == metric["total_admissions"] - metric["prior_period_admissions"]
        and metric["medicare_admissions_change"]
        == metric["medicare_admission_count"] - metric["prior_period_medicare_admission_count"]
        for metric in metrics
    )


def test_admissions_by_region_metrics_include_portfolio_context() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/by-region/metrics",
        params={"start_date": REPORT_START, "end_date": REPORT_END, "level": "region"},
    )

    assert response.status_code == 200
    metrics = response.json()

    assert metrics
    assert all(
        metric["state"]
        and metric["portfolio"]
        and metric["region"]
        and metric["facility_count"] > 0
        for metric in metrics
    )


def test_portfolio_metrics_filter_by_payer_type() -> None:
    client = TestClient(app)
    all_metrics = client.get(
        "/api/v1/adt/admissions/by-region/metrics",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    ).json()
    medicare_metrics = client.get(
        "/api/v1/adt/admissions/by-region/metrics",
        params=[
            ("start_date", REPORT_START),
            ("end_date", REPORT_END),
            ("payer_type", "Medicare"),
        ],
    )

    assert medicare_metrics.status_code == 200
    assert len(medicare_metrics.json()) == len(all_metrics)
    assert sum(metric["total_admissions"] for metric in medicare_metrics.json()) < sum(
        metric["total_admissions"] for metric in all_metrics
    )


def test_admissions_by_facility_metrics_include_all_requested_metrics() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/by-facility/metrics",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    metrics = response.json()

    assert metrics
    assert all(
        metric["facility_name"]
        and metric["state"]
        and metric["region"]
        and metric["total_admissions"] >= 0
        and metric["readmission_count"] >= 0
        and metric["medicare_admission_count"] >= 0
        and metric["prior_period_admissions"] >= 0
        and metric["prior_period_medicare_admission_count"] >= 0
        and metric["admissions_change"]
        == metric["total_admissions"] - metric["prior_period_admissions"]
        and metric["medicare_admissions_change"]
        == metric["medicare_admission_count"] - metric["prior_period_medicare_admission_count"]
        for metric in metrics
    )
    assert metrics == sorted(metrics, key=lambda metric: metric["facility_name"])


def test_admissions_by_source_type_returns_ranked_totals() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/by-admission-source-type",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    distribution = response.json()

    assert distribution
    assert all(item["admission_count"] > 0 for item in distribution)
    assert distribution == sorted(
        distribution,
        key=lambda item: (-item["admission_count"], item["admission_source_type"]),
    )


def test_admissions_by_region_and_payer_returns_a_complete_matrix() -> None:
    response = TestClient(app).get(
        "/api/v1/adt/admissions/by-region-and-payer",
        params={"start_date": REPORT_START, "end_date": REPORT_END},
    )

    assert response.status_code == 200
    payload = response.json()
    payer_types = payload["payer_types"]
    regions = payload["regions"]

    assert payer_types
    assert regions
    assert all(set(region["admission_counts"]) == set(payer_types) for region in regions)
    assert regions == sorted(
        regions,
        key=lambda region: (
            -sum(region["admission_counts"].values()),
            region["region"],
        ),
    )
