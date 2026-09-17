from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration loaded from the repository-level local .env file."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    demo_instance_id: str | None = None
    reporting_timezone: str = "America/New_York"

    database_url: str | None = None
    # Separate connection fields are useful for container secrets and avoid URL
    # interpolation/escaping. DATABASE_URL remains the existing local override.
    database_host: str | None = None
    database_port: int = 5432
    database_name: str | None = None
    database_user: str | None = None
    database_password: SecretStr | None = None
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        origins = {origin.strip() for origin in self.cors_origins.split(",") if origin.strip()}
        if "http://localhost:5173" in origins:
            origins.add("http://127.0.0.1:5173")
        if "http://127.0.0.1:5173" in origins:
            origins.add("http://localhost:5173")
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()
