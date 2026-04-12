"""Application configuration via pydantic-settings."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = "postgresql+asyncpg://rcscout:rcscout_dev@db:5432/rcscout"
    SCRAPE_DELAY: float = 1.0
    RECHECK_DELAY: float = 2.0

    # Required — no default (startup fails with clear error if missing)
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    JWT_SECRET: str

    # Optional with sensible defaults
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30
    PUBLIC_BASE_URL: str = "http://localhost:8002"   # used for OAuth redirect_uri
    FRONTEND_URL: str = "http://localhost:4200"
    ALLOWED_ORIGINS: str = "http://localhost:4200"  # comma-separated
    COOKIE_SECURE: bool = False  # set True in production (HTTPS)

    @field_validator("JWT_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse comma-separated ALLOWED_ORIGINS into a list."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()
