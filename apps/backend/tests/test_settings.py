from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import (
    EnvironmentMode,
    ExtractionProviderName,
    SearchProviderName,
    Settings,
    ShoppingProviderName,
)


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
    assert settings.default_region_code == "US"
    assert settings.provider_timeout_seconds == 10.0
    assert settings.provider_rate_limit_per_minute == 60
    assert settings.search_provider == SearchProviderName.FIXTURE
    assert settings.search_provider_enabled is False
    assert settings.extraction_provider == ExtractionProviderName.FIXTURE
    assert settings.extraction_provider_enabled is False
    assert settings.shopping_provider == ShoppingProviderName.DISABLED
    assert settings.shopping_provider_enabled is False
    assert settings.tavily_api_key is None
    assert settings.brave_search_api_key is None
    assert settings.serpapi_api_key is None
    assert settings.provider_readiness_warnings() == ()
    assert settings.resolved_data_dir.name == "data"
    assert settings.resolved_database_path == (
        settings.resolved_data_dir / "cartcart.sqlite3"
    )
    assert settings.resolved_artifact_dir == settings.resolved_data_dir / "artifacts"
    assert settings.raw_source_snapshot_retention_days == 30
    assert settings.extracted_content_retention_days == 30
    assert settings.screenshot_retention_days == 7
    assert settings.agent_output_retention_days == 30
    assert settings.trace_retention_days == 14
    assert settings.eval_artifact_retention_days == 30
    assert settings.screenshots_enabled is False
    assert settings.cross_session_preference_profiling_enabled is False
    assert settings.resolved_raw_source_snapshot_dir == (
        settings.resolved_artifact_dir / "raw-sources"
    )
    assert settings.resolved_extracted_content_dir == (
        settings.resolved_artifact_dir / "extracted-content"
    )
    assert settings.resolved_screenshot_dir == (
        settings.resolved_artifact_dir / "screenshots"
    )
    assert settings.resolved_agent_output_dir == (
        settings.resolved_artifact_dir / "agent-outputs"
    )
    assert settings.resolved_trace_dir == settings.resolved_artifact_dir / "traces"
    assert settings.resolved_eval_artifact_dir == settings.resolved_artifact_dir / "evals"


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
    monkeypatch.setenv("CARTCART_DEFAULT_REGION_CODE", "ph")
    monkeypatch.setenv("CARTCART_PROVIDER_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("CARTCART_PROVIDER_RATE_LIMIT_PER_MINUTE", "30")
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_EXTRACTION_PROVIDER", "tavily")
    monkeypatch.setenv("CARTCART_EXTRACTION_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_SHOPPING_PROVIDER", "serpapi")
    monkeypatch.setenv("CARTCART_SHOPPING_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("CARTCART_SERPAPI_API_KEY", "test-serpapi-key")
    monkeypatch.setenv("CARTCART_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CARTCART_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CARTCART_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("CARTCART_RAW_SOURCE_SNAPSHOT_RETENTION_DAYS", "10")
    monkeypatch.setenv("CARTCART_EXTRACTED_CONTENT_RETENTION_DAYS", "11")
    monkeypatch.setenv("CARTCART_SCREENSHOT_RETENTION_DAYS", "12")
    monkeypatch.setenv("CARTCART_AGENT_OUTPUT_RETENTION_DAYS", "13")
    monkeypatch.setenv("CARTCART_TRACE_RETENTION_DAYS", "14")
    monkeypatch.setenv("CARTCART_EVAL_ARTIFACT_RETENTION_DAYS", "15")
    monkeypatch.setenv("CARTCART_SCREENSHOTS_ENABLED", "true")

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
    assert settings.default_region_code == "PH"
    assert settings.provider_timeout_seconds == 7.5
    assert settings.provider_rate_limit_per_minute == 30
    assert settings.search_provider == SearchProviderName.TAVILY
    assert settings.search_provider_enabled is True
    assert settings.extraction_provider == ExtractionProviderName.TAVILY
    assert settings.extraction_provider_enabled is True
    assert settings.shopping_provider == ShoppingProviderName.SERPAPI
    assert settings.shopping_provider_enabled is True
    assert settings.tavily_api_key is not None
    assert settings.tavily_api_key.get_secret_value() == "test-tavily-key"
    assert settings.serpapi_api_key is not None
    assert settings.serpapi_api_key.get_secret_value() == "test-serpapi-key"
    assert settings.provider_readiness_warnings() == ()
    assert settings.resolved_data_dir == data_dir.resolve()
    assert settings.resolved_database_path == database_path.resolve()
    assert settings.resolved_artifact_dir == artifact_dir.resolve()
    assert settings.raw_source_snapshot_retention_days == 10
    assert settings.extracted_content_retention_days == 11
    assert settings.screenshot_retention_days == 12
    assert settings.agent_output_retention_days == 13
    assert settings.trace_retention_days == 14
    assert settings.eval_artifact_retention_days == 15
    assert settings.screenshots_enabled is True
    assert settings.resolved_raw_source_snapshot_dir == (
        artifact_dir.resolve() / "raw-sources"
    )


def test_settings_reject_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTCART_ENVIRONMENT", "unknown")

    with pytest.raises(ValidationError):
        make_settings()


def test_enabled_live_provider_missing_key_produces_readiness_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER_ENABLED", "true")

    settings = make_settings()
    warnings = settings.provider_readiness_warnings()

    assert len(warnings) == 1
    assert warnings[0].provider == "search:brave"
    assert warnings[0].code == "missing_provider_key"
    assert warnings[0].missing_env_var == "CARTCART_BRAVE_SEARCH_API_KEY"


def test_disabled_provider_missing_key_does_not_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER_ENABLED", "false")

    settings = make_settings()

    assert settings.provider_readiness_warnings() == ()


def test_settings_reject_cross_session_preference_profiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARTCART_CROSS_SESSION_PREFERENCE_PROFILING_ENABLED", "true")

    with pytest.raises(ValidationError):
        make_settings()
