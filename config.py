"""Application configuration for HustlerOS."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment."""

    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str

    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    APP_VERSION: str = "0.1.0"
    LOOP_INTERVAL_S: int = 5
    ALERTENGINE_BASE_URL: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings and fail on first access if invalid."""

    return Settings()


def reset_settings_cache() -> None:
    """Clear cached settings (used by tests)."""

    get_settings.cache_clear()
