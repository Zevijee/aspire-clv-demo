from datetime import timedelta

import pytest
from app.admissions_reporting import state
from app.adt_admissions import STATE_NAMES, admissions, facilities
from app.database import get_engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.mark.parametrize("level", ["portfolio", "region", "facility"])
@pytest.mark.parametrize(
    "payers,source_types,empty_range",
    [(None, None, False), (["Medicare"], ["Hospital", "Home"], False),
     (None, ["Home"], False), (["NO_MATCH"], None, False), (None, None, True)],
)
def test_referring_hospitals_match_distinct_raw_sources(level, payers, source_types, empty_range):
    with get_engine().connect() as connection:
        coverage = connection.execute(
            select(state.c.first_date, state.c.latest_date).where(state.c.id == 1)
        ).one()
        end = coverage.first_date - timedelta(days=1) if empty_range else coverage.latest_date
        start = end - timedelta(days=29)
        dimensions = [facilities.c.state, facilities.c.portfolio]
        keys = ["state", "region"] if level == "portfolio" else ["state", "portfolio", "region"]
        if level != "portfolio":
            dimensions.append(facilities.c.region)
        if level == "facility":
            dimensions.append(facilities.c.name)
            keys.append("facility_name")
        conditions = [admissions.c.admission_date.between(start, end),
                      admissions.c.admission_source_type == "Hospital"]
        if payers:
            conditions.append(admissions.c.payer_type.in_(payers))
        if source_types:
            conditions.append(admissions.c.admission_source_type.in_(source_types))
        expected = {}
        for row in connection.execute(
            select(*dimensions, admissions.c.admission_source_name)
            .select_from(admissions.join(facilities,
                                        facilities.c.facility_code == admissions.c.facility_code))
            .where(*conditions)
            .distinct()
        ):
            key = (STATE_NAMES.get(row[0], row[0]), *row[1:-1])
            expected.setdefault(key, set()).add(row[-1])

    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    if payers:
        params["payer_type"] = payers
    if source_types:
        params["source_type"] = source_types
    if level != "facility":
        params["level"] = level
    endpoint = "by-facility" if level == "facility" else "by-region"
    response = TestClient(app).get(f"/api/v1/adt/admissions/{endpoint}/metrics", params=params)
    assert response.status_code == 200
    rows = response.json()
    assert rows
    for row in rows:
        hospitals = row["referring_hospitals"]
        assert hospitals == sorted(expected.get(tuple(row[key] for key in keys), set()))
        if row["total_admissions"] == 0:
            assert hospitals == []
    if payers is None and source_types is None and not empty_range:
        assert expected
