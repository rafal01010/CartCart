from io import StringIO

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.core.telemetry import configure_telemetry


def test_telemetry_is_disabled_by_default() -> None:
    app = FastAPI()
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    configure_telemetry(app, settings)

    assert app.state.telemetry_enabled is False
    assert not hasattr(app.state, "telemetry_tracer_provider")


def test_telemetry_console_exporter_instruments_fastapi() -> None:
    stream = StringIO()
    app = FastAPI()
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        telemetry_enabled=True,
        telemetry_exporter="console",
        telemetry_service_name="cartcart-test",
    )
    configure_telemetry(app, settings, stream=stream)

    @app.get("/test/telemetry")
    async def telemetry_route() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        response = client.get("/test/telemetry")

    assert response.status_code == 200
    assert app.state.telemetry_enabled is True
    assert app.state.telemetry_exporter == "console"

    output = stream.getvalue()
    assert "cartcart-test" in output
    assert "/test/telemetry" in output
