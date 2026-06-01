from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
    TAVILY = "tavily"


class ShoppingProviderName(StrEnum):
    DISABLED = "disabled"
    FIXTURE = "fixture"
    SERPAPI = "serpapi"


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
    search_provider: SearchProviderName = SearchProviderName.FIXTURE
    search_provider_enabled: bool = False
    extraction_provider: ExtractionProviderName = ExtractionProviderName.FIXTURE
    extraction_provider_enabled: bool = False
    shopping_provider: ShoppingProviderName = ShoppingProviderName.DISABLED
    shopping_provider_enabled: bool = False
    tavily_api_key: SecretStr | None = Field(default=None, min_length=1)
    brave_search_api_key: SecretStr | None = Field(default=None, min_length=1)
    serpapi_api_key: SecretStr | None = Field(default=None, min_length=1)
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
    cross_session_preference_profiling_enabled: Literal[False] = False

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
        if self.extraction_provider_enabled:
            warnings.extend(self._missing_key_warnings_for_extraction_provider())
        if self.shopping_provider_enabled:
            warnings.extend(self._missing_key_warnings_for_shopping_provider())
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

    def _missing_key_warnings_for_extraction_provider(
        self,
    ) -> tuple[ProviderReadinessWarning, ...]:
        if (
            self.extraction_provider == ExtractionProviderName.TAVILY
            and self.tavily_api_key is None
        ):
            return (
                _missing_provider_key_warning(
                    provider="extraction:tavily",
                    env_var="CARTCART_TAVILY_API_KEY",
                ),
            )
        return ()

    def _missing_key_warnings_for_shopping_provider(
        self,
    ) -> tuple[ProviderReadinessWarning, ...]:
        if (
            self.shopping_provider == ShoppingProviderName.SERPAPI
            and self.serpapi_api_key is None
        ):
            return (
                _missing_provider_key_warning(
                    provider="shopping:serpapi",
                    env_var="CARTCART_SERPAPI_API_KEY",
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
