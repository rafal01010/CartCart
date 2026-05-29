from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class EnvironmentMode(StrEnum):
    LOCAL = "local"
    TEST = "test"
    FIXTURE = "fixture"
    LIVE = "live"
    PRODUCTION = "production"


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
    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    database_path: Path | None = None
    artifact_dir: Path | None = None

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
