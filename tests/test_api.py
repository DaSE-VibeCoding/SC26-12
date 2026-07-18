from fastapi.testclient import TestClient

from fintrace.api.app import app

client = TestClient(app)


def test_health_reports_local_file_storage() -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok", "storage": "local_files"}


def test_company_endpoint_resolves_fallback() -> None:
    response = client.get("/api/v1/companies/600519?target_year=2026")
    assert response.status_code == 200
    assert response.json()["company_info_year_used"] == 2025


def test_calendar_endpoint_returns_frontend_timeline() -> None:
    response = client.get("/api/v1/companies/600519/calendar")
    assert response.status_code == 200
    assert "events" in response.json()


def test_financial_endpoint_returns_facts_and_traces() -> None:
    response = client.get("/api/v1/companies/600519/financial")
    assert response.status_code == 200
    payload = response.json()
    assert payload["facts"]
    assert payload["traces"]


def test_financial_series_is_chart_ready() -> None:
    response = client.get("/api/v1/companies/600519/financial-series")
    assert response.status_code == 200
    assert len(response.json()["series"]["revenue"]) == 2
