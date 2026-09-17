"""Search must cover the full log result, with matching counts and column filters."""

import pytest
from app.database import get_engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

REPORT_DATE = "2026-09-09"
PARAMS = {"start_date": REPORT_DATE, "end_date": REPORT_DATE}
client = TestClient(app)


@pytest.fixture(scope="module")
def raw_logs():
    with get_engine().connect() as connection:
        rows = (
            connection.execute(
                text("""
            SELECT a.admission_id, a.resident_name, a.admission_date, a.payer_type,
                   a.payer_name, a.admission_source_type,
                   a.admission_source_name, f.name AS facility_name
            FROM adt_admissions a JOIN facilities f USING (facility_code)
            WHERE a.admission_date = :day
        """),
                {"day": REPORT_DATE},
            )
            .mappings()
            .all()
        )
    assert len(rows) > 50
    return rows


def matches(row, search):
    payer = "Managed Medicare" if row["payer_type"] == "Medicare Advantage" else row["payer_type"]
    return any(
        search.strip().lower() in str(value).lower()
        for value in (
            row["facility_name"],
            row["resident_name"],
            row["admission_date"],
            payer,
            row["payer_name"],
            row["admission_source_type"],
            row["admission_source_name"],
        )
    )


@pytest.mark.parametrize(
    "search", ["mEdIcArE", "Managed Medicare", REPORT_DATE, "%", "_", "no-such-resident-xyz"]
)
def test_search_counts_all_matching_records_and_escapes_wildcards(raw_logs, search):
    expected_ids = {str(row["admission_id"]) for row in raw_logs if matches(row, search)}
    response = client.get("/api/v1/adt/admissions", params={**PARAMS, "search": search})
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == len(expected_ids)
    assert len(result["items"]) == min(50, len(expected_ids))
    assert {item["admission_id"] for item in result["items"]} <= expected_ids
    if len(expected_ids) > 50:
        next_page = client.get(
            "/api/v1/adt/admissions", params={**PARAMS, "search": search, "offset": 50}
        ).json()
        assert next_page["total"] == result["total"]
        assert len(next_page["items"]) == min(50, len(expected_ids) - 50)
        assert {item["admission_id"] for item in next_page["items"]} <= expected_ids
        assert not (
            {item["admission_id"] for item in result["items"]}
            & {item["admission_id"] for item in next_page["items"]}
        )


def test_resident_search_finds_records_beyond_first_page_and_combines_filters(raw_logs):
    later_page = client.get("/api/v1/adt/admissions", params={**PARAMS, "offset": 50}).json()
    target = later_page["items"][0]
    search = f"  {target['resident_name'].swapcase()}  "
    expected_ids = {
        str(row["admission_id"])
        for row in raw_logs
        if matches(row, search)
        and row["facility_name"] == target["facility_name"]
        and row["payer_type"] == target["payer_type"]
    }
    response = client.get(
        "/api/v1/adt/admissions",
        params={
            **PARAMS,
            "search": search,
            "facility": target["facility_name"],
            "payer_type": target["payer_type"],
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == len(expected_ids)
    assert target["admission_id"] in {item["admission_id"] for item in result["items"]}
    assert {item["admission_id"] for item in result["items"]} <= expected_ids


def test_blank_search_restores_unfiltered_results():
    baseline = client.get("/api/v1/adt/admissions", params=PARAMS)
    cleared = client.get("/api/v1/adt/admissions", params={**PARAMS, "search": "  "})
    assert baseline.status_code == cleared.status_code == 200
    assert cleared.json() == baseline.json()


def test_search_length_is_validated():
    assert (
        client.get("/api/v1/adt/admissions", params={**PARAMS, "search": "x" * 201}).status_code
        == 422
    )


@pytest.mark.parametrize("field", ["payer_name", "admission_source_type"])
def test_search_includes_new_visible_columns(raw_logs, field):
    search = raw_logs[0][field]
    expected = {str(row["admission_id"]) for row in raw_logs if matches(row, search)}
    result = client.get("/api/v1/adt/admissions", params={**PARAMS, "search": search}).json()
    assert result["total"] == len(expected)
    assert {row["admission_id"] for row in result["items"]} <= expected


@pytest.mark.parametrize("direction", ["ascending", "descending"])
@pytest.mark.parametrize("column,field", [
    ("payer-name", "payer_name"), ("source-type", "admission_source_type"),
])
def test_new_columns_sort_across_the_full_result(raw_logs, column, field, direction):
    result = client.get("/api/v1/adt/admissions", params={
        **PARAMS, "sort_by": column, "sort_direction": direction,
    }).json()
    expected = sorted([row[field] for row in raw_logs], reverse=direction == "descending")
    assert [row[field] for row in result["items"]] == expected[:50]


def test_payer_name_and_source_type_filters_combine_with_existing_filters(raw_logs):
    target = raw_logs[0]
    params = {**PARAMS, "payer_name": target["payer_name"], "payer_type": target["payer_type"],
              "source_type": target["admission_source_type"]}
    expected = {str(row["admission_id"]) for row in raw_logs
                if row["payer_name"] == target["payer_name"]
                and row["payer_type"] == target["payer_type"]
                and row["admission_source_type"] == target["admission_source_type"]}
    result = client.get("/api/v1/adt/admissions", params=params).json()
    assert result["total"] == len(expected)
    assert {row["admission_id"] for row in result["items"]} <= expected
    assert set(result["filter_options"]["payer_name"]) == {row["payer_name"] for row in raw_logs}
    assert set(result["filter_options"]["source_type"]) == {
        row["admission_source_type"] for row in raw_logs
    }
    empty = client.get("/api/v1/adt/admissions", params={
        **params, "payer_name": "No such payer",
    }).json()
    assert empty["total"] == 0
    assert empty["items"] == []
