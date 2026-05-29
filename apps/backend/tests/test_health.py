from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app


def make_test_client() -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        frontend_origins=("http://frontend.test",),
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
    assert body["checks"]["data_dir"]


def test_cors_allows_configured_frontend_origin() -> None:
    client = make_test_client()

    response = client.get("/healthz", headers={"Origin": "http://frontend.test"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://frontend.test"
