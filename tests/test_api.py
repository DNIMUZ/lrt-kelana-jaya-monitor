from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_declares_estimation() -> None:
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    assert response.json()["data_classification"] == "ESTIMATION"


def test_signal_summary_declares_signal_data() -> None:
    response = client.get("/api/v1/signals/summary")
    assert response.status_code == 200
    assert response.json()["data_classification"] == "SIGNAL"
