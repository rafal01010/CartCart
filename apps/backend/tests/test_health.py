import pytest
from fastapi.testclient import TestClient

from app.core.settings import SearchProviderName, Settings
from app.main import create_app


def make_test_client(**settings_overrides: object) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        frontend_origins=("http://frontend.test",),
        **settings_overrides,
    )
    return TestClient(create_app(settings))


def test_healthz_reports_liveness() -> None:
    client = make_test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_configuration_readiness() -> None:
    client = make_test_client()

    response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["configuration"] == "ok"
    assert body["checks"]["agents"] == "ok"
    assert body["checks"]["providers"] == "ok"
    assert body["checks"]["data_dir"]
    assert body["warnings"] == []


def test_readyz_reports_provider_configuration_warnings() -> None:
    client = make_test_client(
        search_provider=SearchProviderName.TAVILY,
        search_provider_enabled=True,
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["configuration"] == "warning"
    assert body["checks"]["agents"] == "ok"
    assert body["checks"]["providers"] == "warning"
    assert body["warnings"][0]["provider"] == "search:tavily"
    assert body["warnings"][0]["missing_env_var"] == "CARTCART_TAVILY_API_KEY"


def test_readyz_reports_agent_configuration_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CARTCART_OPENAI_API_KEY", raising=False)
    client = make_test_client(
        live_agents_enabled=True,
        openai_api_key=None,
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["configuration"] == "warning"
    assert body["checks"]["agents"] == "warning"
    assert body["checks"]["providers"] == "ok"
    assert body["warnings"][0]["provider"] == "agents:openai"
    assert body["warnings"][0]["missing_env_var"] == "OPENAI_API_KEY"


def test_cors_allows_configured_frontend_origin() -> None:
    client = make_test_client()

    response = client.get("/healthz", headers={"Origin": "http://frontend.test"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://frontend.test"
