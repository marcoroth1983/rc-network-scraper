"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = "postgresql+asyncpg://rcscout:rcscout_dev@db:5432/rcscout"
    SCRAPE_DELAY: float = 1.0


settings = Settings()
