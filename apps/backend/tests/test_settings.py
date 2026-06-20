from pathlib import Path

import pytest
from pydantic import ValidationError

from app.providers.youtube_transcript import TranscriptRuntimeIssue
from app.core.settings import (
    AmazonProductIntelligenceProviderName,
    DEFAULT_OPENAI_AGENT_MODEL,
    EnvironmentMode,
    ExtractionProviderName,
    IKEAStoreIntelligenceProviderName,
    SearchProviderName,
    Settings,
    TranscriptProviderName,
    VideoSearchProviderName,
)


def make_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_defaults_use_local_mode_and_repo_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CARTCART_OPENAI_API_KEY", raising=False)

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
    assert settings.live_agents_enabled is False
    assert settings.openai_model == DEFAULT_OPENAI_AGENT_MODEL
    assert settings.openai_agent_timeout_seconds == 45.0
    assert settings.openai_agent_max_turns == 8
    assert settings.openai_agent_tracing_enabled is False
    assert settings.openai_agent_trace_include_sensitive_data is False
    assert settings.openai_agent_trace_workflow_name == "cartcart-agent-run"
    assert settings.source_fetch_max_content_bytes == 2 * 1024 * 1024
    assert settings.source_fetch_user_agent == "CartCart/0.1 source-fetcher"
    assert settings.search_provider == SearchProviderName.FIXTURE
    assert settings.search_provider_enabled is False
    assert settings.extraction_provider == ExtractionProviderName.FIXTURE
    assert settings.extraction_provider_enabled is False
    assert settings.video_search_provider == VideoSearchProviderName.FIXTURE
    assert settings.video_search_provider_enabled is False
    assert settings.transcript_provider == TranscriptProviderName.FIXTURE
    assert settings.transcript_provider_enabled is False
    assert settings.youtube_transcript_languages == ("en",)
    assert settings.youtube_transcript_deno_executable == "deno"
    assert settings.youtube_transcript_timeout_seconds == 30.0
    assert settings.youtube_transcript_output_limit_bytes == 64 * 1024
    assert settings.youtube_transcript_temp_storage_limit_bytes == 5 * 1024 * 1024
    assert settings.youtube_transcript_max_segments == 5000
    assert (
        settings.amazon_product_intelligence_provider
        == AmazonProductIntelligenceProviderName.FIXTURE
    )
    assert settings.amazon_product_intelligence_provider_enabled is False
    assert (
        settings.ikea_store_intelligence_provider
        == IKEAStoreIntelligenceProviderName.FIXTURE
    )
    assert settings.ikea_store_intelligence_provider_enabled is False
    assert settings.tavily_api_key is None
    assert settings.brave_search_api_key is None
    assert settings.serpapi_api_key is None
    assert settings.youtube_data_api_key is None
    assert settings.openai_api_key is None
    assert settings.provider_readiness_warnings() == ()
    assert settings.agent_readiness_warnings() == ()
    assert settings.configuration_readiness_warnings() == ()
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
    assert (
        settings.resolved_eval_artifact_dir == settings.resolved_artifact_dir / "evals"
    )


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
    monkeypatch.setenv("CARTCART_LIVE_AGENTS_ENABLED", "true")
    monkeypatch.setenv("CARTCART_OPENAI_MODEL", "gpt-5.5")
    monkeypatch.setenv("CARTCART_OPENAI_AGENT_TIMEOUT_SECONDS", "55")
    monkeypatch.setenv("CARTCART_OPENAI_AGENT_MAX_TURNS", "12")
    monkeypatch.setenv("CARTCART_OPENAI_AGENT_TRACING_ENABLED", "true")
    monkeypatch.setenv(
        "CARTCART_OPENAI_AGENT_TRACE_INCLUDE_SENSITIVE_DATA", "false"
    )
    monkeypatch.setenv(
        "CARTCART_OPENAI_AGENT_TRACE_WORKFLOW_NAME", "cartcart-test-agents"
    )
    monkeypatch.setenv("CARTCART_SOURCE_FETCH_MAX_CONTENT_BYTES", "1048576")
    monkeypatch.setenv("CARTCART_SOURCE_FETCH_USER_AGENT", "CartCart-Test/1.0")
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("CARTCART_SEARCH_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_EXTRACTION_PROVIDER", "http_static")
    monkeypatch.setenv("CARTCART_EXTRACTION_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_VIDEO_SEARCH_PROVIDER", "youtube")
    monkeypatch.setenv("CARTCART_VIDEO_SEARCH_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_TRANSCRIPT_PROVIDER", "yt_dlp")
    monkeypatch.setenv("CARTCART_TRANSCRIPT_PROVIDER_ENABLED", "false")
    monkeypatch.setenv("CARTCART_YOUTUBE_TRANSCRIPT_LANGUAGES", '["en","ja"]')
    monkeypatch.setenv("CARTCART_YOUTUBE_TRANSCRIPT_DENO_EXECUTABLE", "deno-test")
    monkeypatch.setenv("CARTCART_YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("CARTCART_YOUTUBE_TRANSCRIPT_OUTPUT_LIMIT_BYTES", "32768")
    monkeypatch.setenv(
        "CARTCART_YOUTUBE_TRANSCRIPT_TEMP_STORAGE_LIMIT_BYTES", "1048576"
    )
    monkeypatch.setenv("CARTCART_YOUTUBE_TRANSCRIPT_MAX_SEGMENTS", "2500")
    monkeypatch.setenv("CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER", "serpapi")
    monkeypatch.setenv("CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER", "search")
    monkeypatch.setenv("CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("CARTCART_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("CARTCART_SERPAPI_API_KEY", "test-serpapi-key")
    monkeypatch.setenv("CARTCART_YOUTUBE_DATA_API_KEY", "test-youtube-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
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
    assert settings.live_agents_enabled is True
    assert settings.openai_model == "gpt-5.5"
    assert settings.openai_agent_timeout_seconds == 55
    assert settings.openai_agent_max_turns == 12
    assert settings.openai_agent_tracing_enabled is True
    assert settings.openai_agent_trace_include_sensitive_data is False
    assert settings.openai_agent_trace_workflow_name == "cartcart-test-agents"
    assert settings.source_fetch_max_content_bytes == 1048576
    assert settings.source_fetch_user_agent == "CartCart-Test/1.0"
    assert settings.search_provider == SearchProviderName.TAVILY
    assert settings.search_provider_enabled is True
    assert settings.extraction_provider == ExtractionProviderName.HTTP_STATIC
    assert settings.extraction_provider_enabled is True
    assert settings.video_search_provider == VideoSearchProviderName.YOUTUBE
    assert settings.video_search_provider_enabled is True
    assert settings.transcript_provider == TranscriptProviderName.YT_DLP
    assert settings.transcript_provider_enabled is False
    assert settings.youtube_transcript_languages == ("en", "ja")
    assert settings.youtube_transcript_deno_executable == "deno-test"
    assert settings.youtube_transcript_timeout_seconds == 25
    assert settings.youtube_transcript_output_limit_bytes == 32768
    assert settings.youtube_transcript_temp_storage_limit_bytes == 1048576
    assert settings.youtube_transcript_max_segments == 2500
    assert (
        settings.amazon_product_intelligence_provider
        == AmazonProductIntelligenceProviderName.SERPAPI
    )
    assert settings.amazon_product_intelligence_provider_enabled is True
    assert (
        settings.ikea_store_intelligence_provider
        == IKEAStoreIntelligenceProviderName.SEARCH
    )
    assert settings.ikea_store_intelligence_provider_enabled is True
    assert settings.tavily_api_key is not None
    assert settings.tavily_api_key.get_secret_value() == "test-tavily-key"
    assert settings.serpapi_api_key is not None
    assert settings.serpapi_api_key.get_secret_value() == "test-serpapi-key"
    assert settings.youtube_data_api_key is not None
    assert settings.youtube_data_api_key.get_secret_value() == "test-youtube-key"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-openai-key"
    assert settings.provider_readiness_warnings() == ()
    assert settings.agent_readiness_warnings() == ()
    assert settings.configuration_readiness_warnings() == ()
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


def test_settings_reject_removed_tavily_extraction_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARTCART_EXTRACTION_PROVIDER", "tavily")

    with pytest.raises(ValidationError):
        make_settings()


def test_removed_generic_shopping_settings_have_no_runtime_surface() -> None:
    assert "shopping_provider" not in Settings.model_fields
    assert "shopping_provider_enabled" not in Settings.model_fields


def test_enabled_http_static_extraction_requires_no_provider_key() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        extraction_provider=ExtractionProviderName.HTTP_STATIC,
        extraction_provider_enabled=True,
    )

    assert settings.provider_readiness_warnings() == ()


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


def test_enabled_youtube_metadata_provider_missing_key_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARTCART_VIDEO_SEARCH_PROVIDER", "youtube")
    monkeypatch.setenv("CARTCART_VIDEO_SEARCH_PROVIDER_ENABLED", "true")

    settings = make_settings()
    warnings = settings.provider_readiness_warnings()

    assert len(warnings) == 1
    assert warnings[0].provider == "video_search:youtube"
    assert warnings[0].missing_env_var == "CARTCART_YOUTUBE_DATA_API_KEY"


def test_enabled_ytdlp_transcript_provider_reports_runtime_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.providers.youtube_transcript.inspect_ytdlp_transcript_runtime",
        lambda executable: (
            TranscriptRuntimeIssue(
                code="missing_deno",
                message=f"Deno is missing at {executable}.",
            ),
        ),
    )
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        transcript_provider=TranscriptProviderName.YT_DLP,
        transcript_provider_enabled=True,
        youtube_transcript_deno_executable="deno-test",
    )

    warnings = settings.provider_readiness_warnings()

    assert len(warnings) == 1
    assert warnings[0].provider == "transcript:yt_dlp"
    assert warnings[0].code == "missing_deno"
    assert warnings[0].message == "Deno is missing at deno-test."


def test_enabled_amazon_product_provider_missing_key_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER", "serpapi")
    monkeypatch.setenv("CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER_ENABLED", "true")

    settings = make_settings()
    warnings = settings.provider_readiness_warnings()

    assert len(warnings) == 1
    assert warnings[0].provider == "amazon_product_intelligence:serpapi"
    assert warnings[0].missing_env_var == "CARTCART_SERPAPI_API_KEY"


def test_enabled_live_agents_missing_openai_key_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CARTCART_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CARTCART_LIVE_AGENTS_ENABLED", "true")

    settings = make_settings()
    warnings = settings.agent_readiness_warnings()

    assert len(warnings) == 1
    assert warnings[0].provider == "agents:openai"
    assert warnings[0].code == "missing_openai_api_key"
    assert warnings[0].missing_env_var == "OPENAI_API_KEY"
    assert settings.configuration_readiness_warnings() == warnings


def test_openai_key_accepts_standard_and_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CARTCART_OPENAI_API_KEY", "prefixed-openai-key")

    prefixed_settings = make_settings()

    assert prefixed_settings.openai_api_key is not None
    assert (
        prefixed_settings.openai_api_key.get_secret_value()
        == "prefixed-openai-key"
    )

    monkeypatch.setenv("OPENAI_API_KEY", "standard-openai-key")
    standard_settings = make_settings()

    assert standard_settings.openai_api_key is not None
    assert standard_settings.openai_api_key.get_secret_value() == "standard-openai-key"


def test_openai_key_accepts_standard_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CARTCART_OPENAI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CARTCART_LIVE_AGENTS_ENABLED=true\n"
        "OPENAI_API_KEY=env-file-openai-key\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.live_agents_enabled is True
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "env-file-openai-key"
    assert settings.agent_readiness_warnings() == ()


def test_settings_reject_cross_session_preference_profiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CARTCART_CROSS_SESSION_PREFERENCE_PROFILING_ENABLED", "true")

    with pytest.raises(ValidationError):
        make_settings()
