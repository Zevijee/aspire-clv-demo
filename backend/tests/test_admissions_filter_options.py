from app.adt_admissions import STATE_NAMES
from app.database import get_engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text


def test_overview_options_include_every_facility_with_its_drilldown_hierarchy():
    response = TestClient(app).get('/api/v1/adt/admissions/filter-options')
    assert response.status_code == 200
    payload = response.json()
    with get_engine().connect() as connection:
        expected = [
            {**row, 'state': STATE_NAMES.get(row['state'], row['state'])}
            for row in connection.execute(text(
                'SELECT state, portfolio, region, name AS facility FROM facilities ORDER BY name'
            )).mappings()
        ]
    assert expected
    assert payload['locations'] == expected
    for plural, field in [
        ('facilities', 'facility'), ('portfolios', 'portfolio'), ('regions', 'region'),
    ]:
        assert set(payload[plural]) == {row[field] for row in expected}
