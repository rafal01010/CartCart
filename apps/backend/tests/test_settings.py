from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import EnvironmentMode, Settings


def make_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_defaults_use_local_mode_and_repo_data_dir() -> None:
    settings = make_settings()

    assert settings.environment == EnvironmentMode.LOCAL
    assert settings.backend_host == "127.0.0.1"
    assert settings.backend_port == 8000
    assert settings.log_level == "INFO"
    assert settings.telemetry_enabled is False
    assert settings.telemetry_exporter == "console"
    assert settings.telemetry_service_name == "cartcart-backend"
    assert settings.telemetry_otlp_endpoint == "http://127.0.0.1:4318/v1/traces"
    assert "http://localhost:5173" in settings.frontend_origins
    assert settings.resolved_data_dir.name == "data"
    assert settings.resolved_database_path == settings.resolved_data_dir / "cartcart.sqlite3"
    assert settings.resolved_artifact_dir == settings.resolved_data_dir / "artifacts"


def test_settings_read_prefixed_environment_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "cartcart-data"
    database_path = tmp_path / "custom.sqlite3"
    artifact_dir = tmp_path / "source-artifacts"

    monkeypatch.setenv("CARTCART_ENVIRONMENT", "fixture")
    monkeypatch.setenv("CARTCART_BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("CARTCART_BACKEND_PORT", "9000")
    monkeypatch.setenv("CARTCART_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CARTCART_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("CARTCART_TELEMETRY_EXPORTER", "otlp")
    monkeypatch.setenv("CARTCART_TELEMETRY_SERVICE_NAME", "cartcart-test")
    monkeypatch.setenv(
        "CARTCART_TELEMETRY_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces"
    )
    monkeypatch.setenv("CARTCART_FRONTEND_ORIGINS", '["http://frontend.test"]')
    monkeypatch.setenv("CARTCART_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CARTCART_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CARTCART_ARTIFACT_DIR", str(artifact_dir))

    settings = make_settings()

    assert settings.environment == EnvironmentMode.FIXTURE
    assert settings.backend_host == "0.0.0.0"
    assert settings.backend_port == 9000
    assert settings.log_level == "DEBUG"
    assert settings.telemetry_enabled is True
    assert settings.telemetry_exporter == "otlp"
    assert settings.telemetry_service_name == "cartcart-test"
    assert settings.telemetry_otlp_endpoint == "http://127.0.0.1:4318/v1/traces"
    assert settings.frontend_origins == ("http://frontend.test",)
    assert settings.resolved_data_dir == data_dir.resolve()
    assert settings.resolved_database_path == database_path.resolve()
    assert settings.resolved_artifact_dir == artifact_dir.resolve()


def test_settings_reject_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTCART_ENVIRONMENT", "unknown")

    with pytest.raises(ValidationError):
        make_settings()
