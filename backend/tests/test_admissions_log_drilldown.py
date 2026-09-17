from datetime import timedelta

import pytest
from app.admissions_reporting import state
from app.adt_admissions import STATE_NAMES, comparison_metrics
from app.database import get_engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select, text

client = TestClient(app)


@pytest.fixture(scope="module")
def reporting_logs():
    with get_engine().connect() as connection:
        end = connection.scalar(select(state.c.latest_date).where(state.c.id == 1))
        start = end - timedelta(days=29)
        rows = connection.execute(text("""
            SELECT a.*, f.name AS facility_name, f.state, f.portfolio, f.region
            FROM adt_admissions a JOIN facilities f USING (facility_code)
            WHERE a.admission_date BETWEEN :start AND :end
        """), {"start": start, "end": end}).mappings().all()
    assert rows
    target = next(row for row in rows if row["admission_source_type"] == "Hospital")
    return start, end, rows, target


@pytest.mark.parametrize("depth", range(5))
@pytest.mark.parametrize("filtered", [False, True])
@pytest.mark.parametrize("readmissions_only", [False, True])
def test_clicked_total_matches_logs_and_pagination(
    reporting_logs, depth, filtered, readmissions_only,
):
    start, end, rows, target = reporting_logs
    fields = ["state", "portfolio", "region", "facility_name"][:depth]
    selected = [row for row in rows if all(row[key] == target[key] for key in fields)]
    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    for key in fields:
        params["facility" if key == "facility_name" else key] = (
            STATE_NAMES[target[key]] if key == "state" else target[key]
        )
    payers = sources = None
    if filtered:
        payers, sources = [target["payer_type"]], ["Hospital"]
        params.update(payer_type=payers, source_type=sources)
        selected = [row for row in selected if row["payer_type"] in payers
                    and row["admission_source_type"] in sources]
    if readmissions_only:
        params["is_readmission"] = "true"
        selected = [row for row in selected if row["is_readmission"]]
    expected_ids = {str(row["admission_id"]) for row in selected}
    level = "portfolio" if depth <= 2 else "region" if depth == 3 else "facility"
    metrics = comparison_metrics(start, end, level, payers, sources)
    matches = []
    for row in metrics:
        if depth >= 1 and row["state"] != STATE_NAMES[target["state"]]:
            continue
        portfolio_key = "region" if level == "portfolio" else "portfolio"
        if depth >= 2 and row[portfolio_key] != target["portfolio"]:
            continue
        if depth >= 3 and row["region"] != target["region"]:
            continue
        if depth == 4 and row["facility_name"] != target["facility_name"]:
            continue
        matches.append(row)
    metric = "readmission_count" if readmissions_only else "total_admissions"
    assert sum(row[metric] for row in matches) == len(expected_ids)
    response = client.get("/api/v1/adt/admissions", params=params)
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == len(expected_ids)
    if readmissions_only:
        assert all(item["is_readmission"] for item in result["items"])
    assert {item["admission_id"] for item in result["items"]} <= expected_ids
    assert len(result["items"]) == min(50, len(expected_ids))
    if len(expected_ids) > 50:
        next_page = client.get("/api/v1/adt/admissions", params={**params, "offset": 50}).json()
        assert next_page["total"] == result["total"]
        assert {item["admission_id"] for item in next_page["items"]} <= expected_ids
        assert not ({item["admission_id"] for item in result["items"]}
                    & {item["admission_id"] for item in next_page["items"]})


def test_drilldown_combines_search_and_source_name_filters(reporting_logs):
    start, end, rows, target = reporting_logs
    expected = {str(row["admission_id"]) for row in rows
                if row["state"] == target["state"] and row["portfolio"] == target["portfolio"]
                and row["region"] == target["region"]
                and row["payer_type"] == target["payer_type"]
                and row["admission_source_type"] == "Hospital"
                and row["admission_source_name"] == target["admission_source_name"]
                and row["resident_name"] == target["resident_name"]}
    params = dict(start_date=start.isoformat(), end_date=end.isoformat(),
                  state=target["state"], portfolio=target["portfolio"], region=target["region"],
                  payer_type=target["payer_type"], source_type="Hospital",
                  admission_source=target["admission_source_name"], search=target["resident_name"])
    result = client.get("/api/v1/adt/admissions", params=params).json()
    assert result["total"] == len(expected)
    assert {item["admission_id"] for item in result["items"]} == expected
    empty = client.get("/api/v1/adt/admissions", params={**params, "state": "Unknown"}).json()
    assert empty["total"] == 0
    assert empty["items"] == []


def test_custom_facility_group_reconciles_metrics_charts_hospitals_and_logs(reporting_logs):
    start, end, raw, _ = reporting_logs
    names = sorted({row['facility_name'] for row in raw})
    chosen = names[::max(1, len(names) // 10)][:10]
    assert len(chosen) == 10
    params = {'start_date': start.isoformat(), 'end_date': end.isoformat(),
              'facility': chosen, 'payer_type': ['Medicare', 'Medicare Advantage']}
    expected = [row for row in raw if row['facility_name'] in chosen
                and row['payer_type'] in params['payer_type']]
    base = '/api/v1/adt/admissions'

    def get(suffix, query=params):
        response = client.get(base + suffix, params=query)
        assert response.status_code == 200
        return response.json()

    metrics = comparison_metrics(start, end, 'facility', params['payer_type'])
    selected_metrics = [row for row in metrics if row['facility_name'] in chosen]
    assert len(selected_metrics) == 10
    assert sum(row['total_admissions'] for row in selected_metrics) == len(expected)
    assert get('')['total'] == len(expected)
    assert get('', {**params, 'is_readmission': 'true'})['total'] == sum(
        row['is_readmission'] for row in expected
    )
    assert sum(row['admission_count'] for row in get('/daily-trend')) == len(expected)
    assert sum(row['admission_count'] for row in get('/by-admission-source-type')) == len(
        expected
    )
    hospitals = get('/by-referring-hospital')
    assert sum(row['admission_count'] for row in hospitals) == sum(
        row['admission_source_type'] == 'Hospital' for row in expected
    )
    hospital = next(row for row in hospitals if row['admission_count'] > 0)
    assert get('', {**params, 'source_type': 'Hospital',
                    'admission_source': hospital['hospital']})['total'] == hospital[
                        'admission_count'
                    ]
