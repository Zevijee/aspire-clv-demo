from app.main import app
from fastapi.testclient import TestClient


def test_health_endpoint_returns_service_status() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "aspire-analytics-api",
    }
