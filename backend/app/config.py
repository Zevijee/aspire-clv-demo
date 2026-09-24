"""Environment configuration. Reading settings does not open a database connection."""
from pathlib import Path
from secrets import token_urlsafe
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env',
        env_file_encoding='utf-8', env_prefix='API_', extra='ignore',
        hide_input_in_errors=True,
    )

    database_url: SecretStr = Field(validation_alias='DATABASE_URL')
    # Signs the session cookie. Generated per process when unset, which is fine
    # for one developer -- restarting signs everyone out -- and wrong for a
    # server, where two workers would sign with different keys and each reject
    # the other's cookie. Set API_SESSION_SECRET there.
    session_secret: SecretStr = Field(default_factory=lambda: SecretStr(token_urlsafe(32)))
    # Refuses to send the cookie over plain HTTP. Off locally, on in production.
    session_https_only: bool = False
    session_hours: int = Field(default=12, ge=1, le=720)
    cors_origins: tuple[str, ...] = (
        'http://localhost:5173', 'http://127.0.0.1:5173',
    )
    timezone: str = 'America/New_York'
    pool_size: int = Field(default=5, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_timeout_seconds: int = Field(default=15, ge=1, le=120)
    connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    statement_timeout_ms: int = Field(default=30000, ge=1000, le=300000)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError('Use an installed IANA timezone, such as America/New_York.') from None
        return value

    @field_validator('cors_origins')
    @classmethod
    def valid_origins(cls, values):
        from urllib.parse import urlsplit
        for value in values:
            origin = urlsplit(value)
            if (origin.scheme not in ('http', 'https') or not origin.netloc
                    or origin.path or origin.query or origin.fragment or origin.username):
                raise ValueError('CORS origins must be full http(s) origins without paths or credentials.')
        return values
