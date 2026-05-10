"""Application configuration for HustlerOS."""

from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    LOG_LEVEL: str = "INFO"
    LOOP_INTERVAL_S: int = 5
    ALERTENGINE_BASE_URL: str = ""
    ENVIRONMENT: str = "development"
    APP_VERSION: str = "0.1.0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _fix_database_url(self) -> "Settings":
        """
        Convert postgresql:// to postgresql+asyncpg://
        Railway injects postgresql:// but SQLAlchemy
        async requires postgresql+asyncpg://
        """
        if self.DATABASE_URL.startswith("postgresql://"):
            self.DATABASE_URL = self.DATABASE_URL.replace(
                "postgresql://",
                "postgresql+asyncpg://",
                1,
            )
        return self

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings and fail on first access if invalid."""
    return Settings()

def reset_settings_cache() -> None:
    """Clear cached settings (used by tests)."""
    get_settings.cache_clear()
