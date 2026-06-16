from enum import StrEnum
from functools import lru_cache
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas.base import CartCartBaseModel
from app.schemas.regions import RegionCode


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class EnvironmentMode(StrEnum):
    LOCAL = "local"
    TEST = "test"
    FIXTURE = "fixture"
    LIVE = "live"
    PRODUCTION = "production"


class SearchProviderName(StrEnum):
    FIXTURE = "fixture"
    TAVILY = "tavily"
    BRAVE = "brave"


class ExtractionProviderName(StrEnum):
    DISABLED = "disabled"
    FIXTURE = "fixture"
    HTTP_STATIC = "http_static"


class VideoSearchProviderName(StrEnum):
    DISABLED = "disabled"
    FIXTURE = "fixture"
    YOUTUBE = "youtube"


class TranscriptProviderName(StrEnum):
    DISABLED = "disabled"
    FIXTURE = "fixture"
    YT_DLP = "yt_dlp"


class AmazonProductIntelligenceProviderName(StrEnum):
    DISABLED = "disabled"
    FIXTURE = "fixture"
    SERPAPI = "serpapi"


class IKEAStoreIntelligenceProviderName(StrEnum):
    DISABLED = "disabled"
    FIXTURE = "fixture"
    SEARCH = "search"


class ProviderReadinessWarning(CartCartBaseModel):
    provider: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    missing_env_var: str | None = Field(default=None, min_length=1, max_length=120)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="CARTCART_",
        extra="ignore",
    )

    environment: EnvironmentMode = EnvironmentMode.LOCAL
    backend_host: str = "127.0.0.1"
    backend_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    telemetry_enabled: bool = False
    telemetry_exporter: Literal["console", "otlp"] = "console"
    telemetry_service_name: str = "cartcart-backend"
    telemetry_otlp_endpoint: str = "http://127.0.0.1:4318/v1/traces"
    frontend_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    default_region_code: RegionCode = "US"
    provider_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    provider_rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)
    source_fetch_max_content_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
    )
    source_fetch_user_agent: str = Field(
        default="CartCart/0.1 source-fetcher",
        min_length=1,
        max_length=300,
    )
    search_provider: SearchProviderName = SearchProviderName.FIXTURE
    search_provider_enabled: bool = False
    extraction_provider: ExtractionProviderName = ExtractionProviderName.FIXTURE
    extraction_provider_enabled: bool = False
    video_search_provider: VideoSearchProviderName = VideoSearchProviderName.FIXTURE
    video_search_provider_enabled: bool = False
    transcript_provider: TranscriptProviderName = TranscriptProviderName.FIXTURE
    transcript_provider_enabled: bool = False
    youtube_transcript_languages: tuple[str, ...] = Field(
        default=("en",),
        min_length=1,
        max_length=10,
    )
    youtube_transcript_deno_executable: str = Field(
        default="deno",
        min_length=1,
        max_length=1024,
    )
    youtube_transcript_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    youtube_transcript_output_limit_bytes: int = Field(
        default=64 * 1024,
        ge=4096,
        le=1024 * 1024,
    )
    youtube_transcript_temp_storage_limit_bytes: int = Field(
        default=5 * 1024 * 1024,
        ge=64 * 1024,
        le=50 * 1024 * 1024,
    )
    youtube_transcript_max_segments: int = Field(default=5000, ge=1, le=20000)
    amazon_product_intelligence_provider: AmazonProductIntelligenceProviderName = (
        AmazonProductIntelligenceProviderName.FIXTURE
    )
    amazon_product_intelligence_provider_enabled: bool = False
    ikea_store_intelligence_provider: IKEAStoreIntelligenceProviderName = (
        IKEAStoreIntelligenceProviderName.FIXTURE
    )
    ikea_store_intelligence_provider_enabled: bool = False
    tavily_api_key: SecretStr | None = Field(default=None, min_length=1)
    brave_search_api_key: SecretStr | None = Field(default=None, min_length=1)
    serpapi_api_key: SecretStr | None = Field(default=None, min_length=1)
    youtube_data_api_key: SecretStr | None = Field(default=None, min_length=1)
    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    database_path: Path | None = None
    artifact_dir: Path | None = None
    raw_source_snapshot_retention_days: int = Field(default=30, ge=0)
    extracted_content_retention_days: int = Field(default=30, ge=0)
    screenshot_retention_days: int = Field(default=7, ge=0)
    agent_output_retention_days: int = Field(default=30, ge=0)
    trace_retention_days: int = Field(default=14, ge=0)
    eval_artifact_retention_days: int = Field(default=30, ge=0)
    screenshots_enabled: bool = False
    cross_session_preference_profiling_enabled: bool = False

    @field_validator("youtube_transcript_languages")
    @classmethod
    def _validate_youtube_transcript_languages(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        language_pattern = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
        if any(language_pattern.fullmatch(language) is None for language in value):
            raise ValueError(
                "YouTube transcript languages must be plain BCP 47 language tags."
            )
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def _reject_cross_session_preference_profiling(self) -> "Settings":
        if self.cross_session_preference_profiling_enabled:
            raise ValueError(
                "Cross-session preference profiling must remain disabled for MVP."
            )
        return self

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def resolved_database_path(self) -> Path:
        if self.database_path is not None:
            return self.database_path.expanduser().resolve()
        return self.resolved_data_dir / "cartcart.sqlite3"

    @property
    def resolved_artifact_dir(self) -> Path:
        if self.artifact_dir is not None:
            return self.artifact_dir.expanduser().resolve()
        return self.resolved_data_dir / "artifacts"

    @property
    def resolved_raw_source_snapshot_dir(self) -> Path:
        return self.resolved_artifact_dir / "raw-sources"

    @property
    def resolved_extracted_content_dir(self) -> Path:
        return self.resolved_artifact_dir / "extracted-content"

    @property
    def resolved_screenshot_dir(self) -> Path:
        return self.resolved_artifact_dir / "screenshots"

    @property
    def resolved_agent_output_dir(self) -> Path:
        return self.resolved_artifact_dir / "agent-outputs"

    @property
    def resolved_trace_dir(self) -> Path:
        return self.resolved_artifact_dir / "traces"

    @property
    def resolved_eval_artifact_dir(self) -> Path:
        return self.resolved_artifact_dir / "evals"

    def provider_readiness_warnings(self) -> tuple[ProviderReadinessWarning, ...]:
        warnings: list[ProviderReadinessWarning] = []
        if self.search_provider_enabled:
            warnings.extend(self._missing_key_warnings_for_search_provider())
        if self.video_search_provider_enabled:
            warnings.extend(self._missing_key_warnings_for_video_search_provider())
        if self.transcript_provider_enabled:
            warnings.extend(self._warnings_for_transcript_provider())
        if self.amazon_product_intelligence_provider_enabled:
            warnings.extend(
                self._missing_key_warnings_for_amazon_product_intelligence_provider()
            )
        if self.ikea_store_intelligence_provider_enabled:
            warnings.extend(self._warnings_for_ikea_store_intelligence_provider())
        return tuple(warnings)

    def _missing_key_warnings_for_search_provider(
        self,
    ) -> tuple[ProviderReadinessWarning, ...]:
        if (
            self.search_provider == SearchProviderName.TAVILY
            and self.tavily_api_key is None
        ):
            return (
                _missing_provider_key_warning(
                    provider="search:tavily",
                    env_var="CARTCART_TAVILY_API_KEY",
                ),
            )
        if (
            self.search_provider == SearchProviderName.BRAVE
            and self.brave_search_api_key is None
        ):
            return (
                _missing_provider_key_warning(
                    provider="search:brave",
                    env_var="CARTCART_BRAVE_SEARCH_API_KEY",
                ),
            )
        return ()

    def _missing_key_warnings_for_video_search_provider(
        self,
    ) -> tuple[ProviderReadinessWarning, ...]:
        if (
            self.video_search_provider == VideoSearchProviderName.YOUTUBE
            and self.youtube_data_api_key is None
        ):
            return (
                _missing_provider_key_warning(
                    provider="video_search:youtube",
                    env_var="CARTCART_YOUTUBE_DATA_API_KEY",
                ),
            )
        return ()

    def _missing_key_warnings_for_amazon_product_intelligence_provider(
        self,
    ) -> tuple[ProviderReadinessWarning, ...]:
        if (
            self.amazon_product_intelligence_provider
            == AmazonProductIntelligenceProviderName.SERPAPI
            and self.serpapi_api_key is None
        ):
            return (
                _missing_provider_key_warning(
                    provider="amazon_product_intelligence:serpapi",
                    env_var="CARTCART_SERPAPI_API_KEY",
                ),
            )
        return ()

    def _warnings_for_transcript_provider(
        self,
    ) -> tuple[ProviderReadinessWarning, ...]:
        if self.transcript_provider != TranscriptProviderName.YT_DLP:
            return ()

        from app.providers.youtube_transcript import inspect_ytdlp_transcript_runtime

        return tuple(
            ProviderReadinessWarning(
                provider="transcript:yt_dlp",
                code=issue.code,
                message=issue.message,
            )
            for issue in inspect_ytdlp_transcript_runtime(
                self.youtube_transcript_deno_executable
            )
        )

    def _warnings_for_ikea_store_intelligence_provider(
        self,
    ) -> tuple[ProviderReadinessWarning, ...]:
        if (
            self.ikea_store_intelligence_provider
            == IKEAStoreIntelligenceProviderName.SEARCH
            and not self.search_provider_enabled
        ):
            return (
                ProviderReadinessWarning(
                    provider="ikea_store_intelligence:search",
                    code="provider_dependency_disabled",
                    message=(
                        "IKEA store intelligence uses the configured general search "
                        "provider, but live search is disabled. Fixture mode can still run."
                    ),
                ),
            )
        return ()


def _missing_provider_key_warning(
    *,
    provider: str,
    env_var: str,
) -> ProviderReadinessWarning:
    return ProviderReadinessWarning(
        provider=provider,
        code="missing_provider_key",
        message=(
            f"{provider} is enabled but {env_var} is not set. "
            "Fixture and stub modes can still run; live provider calls are disabled."
        ),
        missing_env_var=env_var,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
